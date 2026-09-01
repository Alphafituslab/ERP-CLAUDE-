"""
Fase 126 — Financeiro: rotas HTTP em cima de app/cnab_service.py,
substituindo por completo a integração com o Asaas (Fase 71). Ver a nota
de escopo completa em migrations/schema_fase126.sql e o aviso de
confiabilidade no topo de app/cnab_service.py — a estrutura do arquivo
CNAB 240 ainda não foi validada contra o manual real do Sicredi/Unicred.
"""
import datetime

from flask import Blueprint, g, jsonify, request

from .. import audit
from .. import cnab_service
from ..context import ApiError, client_device, client_ip, get_db
from ..permissions import requires_permission

bp = Blueprint("boletos", __name__, url_prefix="/api/v1/financeiro/boletos")


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _hoje_iso_data():
    return datetime.datetime.utcnow().strftime("%Y-%m-%d")


def _conta_receber_ou_404(conn, conta_id):
    row = conn.execute("SELECT * FROM contas_receber WHERE id = ?", (conta_id,)).fetchone()
    if row is None:
        raise ApiError("Conta a receber não encontrada.", status=404)
    return dict(row)


def _cliente_ou_404(conn, cliente_id):
    row = conn.execute("SELECT * FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
    if row is None:
        raise ApiError("Cliente não encontrado.", status=404)
    return dict(row)


def _boleto_ou_404(conn, boleto_id):
    row = conn.execute("SELECT * FROM boletos WHERE id = ?", (boleto_id,)).fetchone()
    if row is None:
        raise ApiError("Boleto não encontrado.", status=404)
    return dict(row)


def _empresa_unica(conn):
    """CNAB precisa dos dados do cedente (a própria empresa) — mesmo
    raciocínio já documentado em project_cnab_boleto_sicredi_unicred:
    modelo de empresa única, não multi-empresa."""
    row = conn.execute("SELECT * FROM empresas LIMIT 1").fetchone()
    if row is None:
        raise ApiError("Cadastre os dados da empresa (Administração > Empresa) antes de gerar boletos.", status=400)
    return dict(row)


# ============================================================
# CONFIGURAÇÃO
# ============================================================
@bp.get("/configuracao")
@requires_permission("financeiro", "configurar_boleto")
def obter_configuracao():
    conn = get_db()
    return jsonify(cnab_service.config_publica(cnab_service.obter_configuracao(conn)))


@bp.put("/configuracao")
@requires_permission("financeiro", "configurar_boleto")
def atualizar_configuracao():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()
    anterior = cnab_service.obter_configuracao(conn)

    nova = cnab_service.salvar_configuracao(conn, dados, usuario_atual["id"])

    audit.registrar(
        conn, tabela="configuracoes_boleto", registro_id=1, usuario_id=usuario_atual["id"],
        acao="configuracao_boleto_atualizada",
        valor_anterior={"banco_codigo": anterior.get("banco_codigo"), "ambiente": anterior.get("ambiente")},
        valor_novo={"banco_codigo": nova.get("banco_codigo"), "ambiente": nova.get("ambiente")},
        ip=client_ip(), dispositivo=client_device(),
    )
    return jsonify(cnab_service.config_publica(nova))


# ============================================================
# BOLETOS
# ============================================================
@bp.get("")
@requires_permission("financeiro", "visualizar")
def listar_boletos():
    conn = get_db()
    conta_receber_id = request.args.get("conta_receber_id", type=int)
    if conta_receber_id:
        rows = conn.execute(
            "SELECT * FROM boletos WHERE conta_receber_id = ? ORDER BY id DESC", (conta_receber_id,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM boletos ORDER BY id DESC LIMIT 500").fetchall()
    return jsonify([dict(r) for r in rows])


@bp.get("/<int:boleto_id>")
@requires_permission("financeiro", "visualizar")
def obter_boleto(boleto_id):
    conn = get_db()
    return jsonify(_boleto_ou_404(conn, boleto_id))


@bp.post("/contas-receber/<int:conta_id>/gerar")
@requires_permission("financeiro", "gerar_boleto")
def gerar_boleto(conta_id):
    """Emissão 100% local — CNAB não tem API, então "gerar boleto" aqui só
    significa: reservar um nosso_número, calcular linha digitável/código
    de barras, e deixar pronto pra entrar na próxima remessa. Nada é
    enviado a banco nenhum nesta chamada (isso só acontece em
    /remessa/gerar)."""
    usuario_atual = g.usuario_atual
    conn = get_db()

    conta = _conta_receber_ou_404(conn, conta_id)
    if conta["status"] in ("pago", "cancelado"):
        raise ApiError(f"Esta conta a receber já está '{conta['status']}' — não é possível gerar boleto.", status=400)
    ja_ativo = conn.execute(
        "SELECT id FROM boletos WHERE conta_receber_id = ? AND status IN ('pendente', 'em_remessa')", (conta_id,)
    ).fetchone()
    if ja_ativo:
        raise ApiError("Já existe um boleto ativo (pendente ou em remessa) para esta conta a receber.", status=409)

    config = cnab_service.obter_configuracao(conn)
    cliente = _cliente_ou_404(conn, conta["cliente_id"])
    total_baixado = conn.execute(
        "SELECT COALESCE(SUM(valor), 0) AS total FROM contas_receber_baixas WHERE conta_receber_id = ?", (conta_id,)
    ).fetchone()["total"]
    saldo_aberto = round(conta["valor_total"] - total_baixado, 2)
    if saldo_aberto <= 0:
        raise ApiError("Esta conta a receber não tem saldo em aberto — não é possível gerar boleto.", status=400)

    nosso_numero = str(config["proximo_nosso_numero"])
    vencimento = conta["vencimento"] if conta["vencimento"] >= _hoje_iso_data() else _hoje_iso_data()
    codigo_barras, linha_digitavel = cnab_service.gerar_codigo_barras_e_linha_digitavel(
        config, nosso_numero, saldo_aberto, vencimento
    )

    cur = conn.execute(
        """
        INSERT INTO boletos
            (conta_receber_id, cliente_id, ambiente, status, banco_codigo, nosso_numero,
             valor, vencimento, linha_digitavel, codigo_barras, criado_por, atualizado_em)
        VALUES (?, ?, ?, 'pendente', ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            conta_id, cliente["id"], config["ambiente"], config["banco_codigo"], nosso_numero,
            saldo_aberto, vencimento, linha_digitavel, codigo_barras, usuario_atual["id"], _now_iso(),
        ),
    )
    boleto_id = cur.lastrowid
    conn.execute("UPDATE configuracoes_boleto SET proximo_nosso_numero = proximo_nosso_numero + 1 WHERE id = 1")

    audit.registrar(
        conn, tabela="boletos", registro_id=boleto_id, usuario_id=usuario_atual["id"],
        acao="boleto_gerado",
        valor_novo={"conta_receber_id": conta_id, "banco_codigo": config["banco_codigo"], "nosso_numero": nosso_numero, "valor": saldo_aberto},
        ip=client_ip(), dispositivo=client_device(),
    )
    return jsonify(_boleto_ou_404(conn, boleto_id)), 201


@bp.post("/<int:boleto_id>/cancelar")
@requires_permission("financeiro", "cancelar_boleto")
def cancelar_boleto(boleto_id):
    """Cancela SÓ no Alphafitus — se o boleto já foi remetido ao banco
    (status 'em_remessa'), cancelar aqui não cancela lá; o operador
    também precisa instruir o cancelamento pelo internet banking. Isso é
    inerente a um fluxo por arquivo (sem API), não uma limitação que dá
    pra contornar no código."""
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    justificativa = (dados.get("justificativa") or "").strip()
    conn = get_db()
    boleto = _boleto_ou_404(conn, boleto_id)

    if boleto["status"] not in ("pendente", "em_remessa"):
        raise ApiError("Só é possível cancelar um boleto pendente ou já remetido (não pago/vencido/já cancelado).", status=400)
    if not justificativa:
        raise ApiError("Informe a justificativa do cancelamento.", status=400)

    conn.execute(
        "UPDATE boletos SET status = 'cancelado', justificativa_cancelamento = ?, cancelado_em = ?, cancelado_por = ?, atualizado_em = ? WHERE id = ?",
        (justificativa, _now_iso(), usuario_atual["id"], _now_iso(), boleto_id),
    )
    audit.registrar(
        conn, tabela="boletos", registro_id=boleto_id, usuario_id=usuario_atual["id"],
        acao="boleto_cancelado", valor_anterior={"status": boleto["status"]}, valor_novo={"status": "cancelado", "justificativa": justificativa},
        ip=client_ip(), dispositivo=client_device(),
    )
    return jsonify(_boleto_ou_404(conn, boleto_id))


# ============================================================
# REMESSA
# ============================================================
@bp.get("/remessa/pendentes")
@requires_permission("financeiro", "gerar_boleto")
def listar_pendentes_para_remessa():
    conn = get_db()
    rows = conn.execute("SELECT * FROM boletos WHERE status = 'pendente' ORDER BY vencimento").fetchall()
    return jsonify([dict(r) for r in rows])


@bp.post("/remessa/gerar")
@requires_permission("financeiro", "gerar_boleto")
def gerar_remessa():
    """Gera o arquivo CNAB 240 de remessa com todos os boletos 'pendente'
    (ou só os informados em `boleto_ids`), devolve o CONTEÚDO do arquivo
    pra tela baixar (mesmo padrão de baixarArquivo() já usado em SPED
    Fiscal/NF-e), e marca cada título como 'em_remessa'. Não envia nada a
    banco nenhum — quem sobe o arquivo no internet banking é o operador."""
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    config = cnab_service.obter_configuracao(conn)
    empresa = _empresa_unica(conn)

    ids_informados = dados.get("boleto_ids")
    if ids_informados:
        placeholders = ",".join("?" for _ in ids_informados)
        rows = conn.execute(
            f"SELECT * FROM boletos WHERE id IN ({placeholders}) AND status = 'pendente'", ids_informados
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM boletos WHERE status = 'pendente'").fetchall()
    if not rows:
        raise ApiError("Nenhum boleto pendente para incluir na remessa.", status=400)

    boletos_para_arquivo = []
    for row in rows:
        boleto = dict(row)
        conta = _conta_receber_ou_404(conn, boleto["conta_receber_id"])
        boleto["numero"] = conta["numero"]
        boleto["cliente"] = _cliente_ou_404(conn, boleto["cliente_id"])
        boletos_para_arquivo.append(boleto)

    conteudo = cnab_service.montar_remessa(config, empresa, boletos_para_arquivo)

    numero_remessa = config["proximo_numero_remessa"]
    nome_arquivo = f"REMESSA_{config['banco_codigo']}_{numero_remessa:07d}.rem"
    valor_total = sum(b["valor"] for b in boletos_para_arquivo)

    cur = conn.execute(
        """
        INSERT INTO cnab_remessas (banco_codigo, numero_sequencial_arquivo, quantidade_titulos, valor_total, nome_arquivo, gerado_por)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (config["banco_codigo"], numero_remessa, len(boletos_para_arquivo), valor_total, nome_arquivo, usuario_atual["id"]),
    )
    remessa_id = cur.lastrowid
    ids = [b["id"] for b in boletos_para_arquivo]
    conn.execute(
        f"UPDATE boletos SET status = 'em_remessa', cnab_remessa_id = ?, atualizado_em = ? WHERE id IN ({','.join('?' for _ in ids)})",
        (remessa_id, _now_iso(), *ids),
    )
    conn.execute("UPDATE configuracoes_boleto SET proximo_numero_remessa = proximo_numero_remessa + 1 WHERE id = 1")

    audit.registrar(
        conn, tabela="cnab_remessas", registro_id=remessa_id, usuario_id=usuario_atual["id"],
        acao="remessa_cnab_gerada",
        valor_novo={"banco_codigo": config["banco_codigo"], "quantidade_titulos": len(ids), "valor_total": valor_total, "nome_arquivo": nome_arquivo},
        ip=client_ip(), dispositivo=client_device(),
    )
    return jsonify({
        "remessa_id": remessa_id, "nome_arquivo": nome_arquivo, "conteudo": conteudo,
        "quantidade_titulos": len(ids), "valor_total": valor_total,
    }), 201


@bp.get("/remessa")
@requires_permission("financeiro", "visualizar")
def listar_remessas():
    conn = get_db()
    rows = conn.execute("SELECT * FROM cnab_remessas ORDER BY id DESC LIMIT 200").fetchall()
    return jsonify([dict(r) for r in rows])


# ============================================================
# RETORNO
# ============================================================
@bp.post("/retorno/processar")
# Mesmo raciocínio já documentado em consultar_status (Fase 73, Asaas):
# esta rota "processa um arquivo" mas na prática registra baixas de
# verdade em contas_receber_baixas quando o retorno confirma pagamento —
# por isso exige a permissão de ESCRITA financeiro.registrar_baixa_receber,
# não só financeiro.visualizar.
@requires_permission("financeiro", "registrar_baixa_receber")
def processar_retorno():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conteudo = dados.get("conteudo")
    nome_arquivo = (dados.get("nome_arquivo") or "retorno.ret").strip()
    if not conteudo or not conteudo.strip():
        raise ApiError("Informe o conteúdo do arquivo de retorno.", status=400)
    conn = get_db()
    config = cnab_service.obter_configuracao(conn)

    ocorrencias = cnab_service.processar_retorno(conteudo)
    if not ocorrencias:
        raise ApiError("Nenhuma ocorrência de título reconhecida neste arquivo — confira se é mesmo um retorno CNAB 240 de cobrança.", status=400)

    quantidade_baixas = 0
    detalhes = []
    for ocorrencia in ocorrencias:
        boleto_row = conn.execute(
            "SELECT * FROM boletos WHERE nosso_numero = ? AND banco_codigo = ?",
            (ocorrencia["nosso_numero"], config["banco_codigo"]),
        ).fetchone()
        if boleto_row is None:
            detalhes.append({**ocorrencia, "resultado": "nosso_numero não encontrado — ignorado"})
            continue
        boleto = dict(boleto_row)
        conn.execute(
            "UPDATE boletos SET ultima_ocorrencia_retorno = ?, atualizado_em = ? WHERE id = ?",
            (ocorrencia["codigo_ocorrencia"], _now_iso(), boleto["id"]),
        )

        if ocorrencia["codigo_ocorrencia"] in cnab_service.OCORRENCIAS_LIQUIDACAO and boleto["status"] == "em_remessa":
            conta = _conta_receber_ou_404(conn, boleto["conta_receber_id"])
            total_baixado_atual = conn.execute(
                "SELECT COALESCE(SUM(valor), 0) AS total FROM contas_receber_baixas WHERE conta_receber_id = ?",
                (conta["id"],),
            ).fetchone()["total"]
            valor_baixa = min(ocorrencia["valor_pago"] or boleto["valor"], conta["valor_total"] - total_baixado_atual)
            if valor_baixa > 0.0000001:
                cur = conn.execute(
                    """
                    INSERT INTO contas_receber_baixas (conta_receber_id, valor, forma_pagamento, data_pagamento, observacao, criado_por)
                    VALUES (?, ?, 'boleto', ?, ?, ?)
                    """,
                    (conta["id"], valor_baixa, _hoje_iso_data(),
                     f"Baixa automática — boleto #{boleto['id']} confirmado por retorno CNAB (ocorrência {ocorrencia['codigo_ocorrencia']}).",
                     usuario_atual["id"]),
                )
                novo_status_conta = "pago" if (total_baixado_atual + valor_baixa) >= conta["valor_total"] - 0.0000001 else "pago_parcial"
                conn.execute("UPDATE contas_receber SET status = ? WHERE id = ?", (novo_status_conta, conta["id"]))
                conn.execute("UPDATE boletos SET status = 'recebido', atualizado_em = ? WHERE id = ?", (_now_iso(), boleto["id"]))
                audit.registrar(
                    conn, tabela="contas_receber_baixas", registro_id=cur.lastrowid, usuario_id=usuario_atual["id"],
                    acao="baixa_receber_registrada_automaticamente_por_retorno_cnab",
                    valor_novo={"conta_receber_id": conta["id"], "valor": valor_baixa, "boleto_id": boleto["id"]},
                    ip=client_ip(), dispositivo=client_device(),
                )
                quantidade_baixas += 1
                detalhes.append({**ocorrencia, "resultado": f"baixa registrada (R$ {valor_baixa:.2f})"})
                continue
        elif ocorrencia["codigo_ocorrencia"] in cnab_service.OCORRENCIAS_BAIXA:
            conn.execute("UPDATE boletos SET status = 'cancelado', atualizado_em = ? WHERE id = ?", (_now_iso(), boleto["id"]))
            detalhes.append({**ocorrencia, "resultado": "boleto baixado pelo banco — marcado como cancelado"})
            continue
        detalhes.append({**ocorrencia, "resultado": "ocorrência registrada, sem ação automática"})

    cur = conn.execute(
        """
        INSERT INTO cnab_retornos (banco_codigo, nome_arquivo, quantidade_titulos_lidos, quantidade_baixas_geradas, conteudo_bruto, processado_por)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (config["banco_codigo"], nome_arquivo, len(ocorrencias), quantidade_baixas, conteudo, usuario_atual["id"]),
    )
    retorno_id = cur.lastrowid
    audit.registrar(
        conn, tabela="cnab_retornos", registro_id=retorno_id, usuario_id=usuario_atual["id"],
        acao="retorno_cnab_processado",
        valor_novo={"nome_arquivo": nome_arquivo, "quantidade_titulos_lidos": len(ocorrencias), "quantidade_baixas_geradas": quantidade_baixas},
        ip=client_ip(), dispositivo=client_device(),
    )
    return jsonify({
        "retorno_id": retorno_id, "quantidade_titulos_lidos": len(ocorrencias),
        "quantidade_baixas_geradas": quantidade_baixas, "detalhes": detalhes,
    }), 201


@bp.get("/retorno")
@requires_permission("financeiro", "visualizar")
def listar_retornos():
    conn = get_db()
    rows = conn.execute(
        "SELECT id, banco_codigo, nome_arquivo, quantidade_titulos_lidos, quantidade_baixas_geradas, processado_em, processado_por FROM cnab_retornos ORDER BY id DESC LIMIT 200"
    ).fetchall()
    return jsonify([dict(r) for r in rows])
