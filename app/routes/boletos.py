"""
Fase 71 — Financeiro: rotas HTTP finas em cima de app/boleto_service.py
(mesmo padrão de app/routes/fiscal.py em cima de app/nfe_service.py, Fase 70).
"""
import datetime
import sqlite3

from flask import Blueprint, g, jsonify, request

from .. import audit
from .. import boleto_service
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


# ============================================================
# CONFIGURAÇÃO
# ============================================================
@bp.get("/configuracao")
@requires_permission("financeiro", "configurar_boleto")
def obter_configuracao():
    conn = get_db()
    return jsonify(boleto_service.config_publica(boleto_service.obter_configuracao(conn)))


@bp.put("/configuracao")
@requires_permission("financeiro", "configurar_boleto")
def atualizar_configuracao():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()
    anterior = boleto_service.obter_configuracao(conn)

    nova = boleto_service.salvar_configuracao(conn, dados, usuario_atual["id"])

    audit.registrar(
        conn, tabela="configuracoes_boleto", registro_id=1, usuario_id=usuario_atual["id"],
        acao="configuracao_boleto_atualizada",
        valor_anterior={"provedor": anterior.get("provedor"), "ambiente": anterior.get("ambiente")},
        valor_novo={"provedor": nova.get("provedor"), "ambiente": nova.get("ambiente")},
        ip=client_ip(), dispositivo=client_device(),
    )
    return jsonify(boleto_service.config_publica(nova))


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
    usuario_atual = g.usuario_atual
    conn = get_db()

    conta = _conta_receber_ou_404(conn, conta_id)
    if conta["status"] in ("pago", "cancelado"):
        raise ApiError(f"Esta conta a receber já está '{conta['status']}' — não é possível gerar boleto.", status=400)
    if boleto_service.existe_boleto_ativo_para_conta(conn, conta_id):
        raise ApiError("Já existe um boleto PENDENTE para esta conta a receber.", status=409)

    config = boleto_service.obter_configuracao(conn)
    if not config.get("token_api"):
        raise ApiError("Configure o token de API do provedor de boleto antes de gerar (Financeiro > Configuração de Boleto).", status=400)

    cliente = _cliente_ou_404(conn, conta["cliente_id"])
    total_baixado = conn.execute(
        "SELECT COALESCE(SUM(valor), 0) AS total FROM contas_receber_baixas WHERE conta_receber_id = ?", (conta_id,)
    ).fetchone()["total"]
    saldo_aberto = round(conta["valor_total"] - total_baixado, 2)
    if saldo_aberto <= 0:
        raise ApiError("Esta conta a receber não tem saldo em aberto — não é possível gerar boleto.", status=400)

    id_cliente_asaas = boleto_service.buscar_ou_criar_cliente_asaas(config, cliente)
    if id_cliente_asaas != cliente.get("id_externo_asaas"):
        conn.execute("UPDATE clientes SET id_externo_asaas = ? WHERE id = ?", (id_cliente_asaas, cliente["id"]))

    referencia = boleto_service.gerar_referencia(conta_id)
    vencimento = conta["vencimento"] if conta["vencimento"] >= _hoje_iso_data() else _hoje_iso_data()
    resultado = boleto_service._gerar_no_provedor(
        config, id_cliente_asaas, saldo_aberto, vencimento,
        f"Alphafitus OS — Conta a receber {conta['numero']}", referencia,
    )

    # Fase 72 (auditoria de segurança): a checagem `existe_boleto_ativo_
    # para_conta` acima rodou ANTES da chamada de rede ao Asaas, o que
    # amplia ainda mais a janela para duas requisições concorrentes
    # gerarem, cada uma, um boleto "pendente" para a mesma conta a
    # receber. O índice único parcial `idx_boletos_conta_receber_
    # pendente_unico` (schema_fase72.sql) é quem garante isso de
    # verdade, a nível de banco; aqui só convertemos a IntegrityError que
    # uma corrida perdida geraria num 409 amigável, em vez de um 500
    # genérico.
    try:
        cur = conn.execute(
            """
            INSERT INTO boletos
                (conta_receber_id, cliente_id, ambiente, status, referencia_provedor, id_pagamento_provedor,
                 valor, vencimento, linha_digitavel, codigo_barras, url_boleto, mensagem_provedor, criado_por, atualizado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                conta_id, cliente["id"], config["ambiente"], resultado["status"], referencia, resultado.get("id_pagamento_provedor"),
                saldo_aberto, vencimento, resultado.get("linha_digitavel"), resultado.get("codigo_barras"),
                resultado.get("url_boleto"), resultado.get("mensagem_provedor"), usuario_atual["id"], boleto_service._now_iso(),
            ),
        )
    except sqlite3.IntegrityError:
        raise ApiError(
            "Já existe um boleto PENDENTE para esta conta a receber — outra geração para a "
            "mesma conta provavelmente aconteceu ao mesmo tempo. Consulte os boletos desta "
            "conta antes de tentar de novo.",
            status=409,
        )
    boleto_id = cur.lastrowid

    audit.registrar(
        conn, tabela="boletos", registro_id=boleto_id, usuario_id=usuario_atual["id"],
        acao="boleto_gerado",
        valor_novo={"conta_receber_id": conta_id, "ambiente": config["ambiente"], "valor": saldo_aberto, "status": resultado["status"]},
        ip=client_ip(), dispositivo=client_device(),
    )
    return jsonify(_boleto_ou_404(conn, boleto_id)), 201


@bp.post("/<int:boleto_id>/consultar-status")
# Fase 73 (achado de auditoria — Fase 72): esta rota parece só LEITURA
# ("consultar" status), mas quando o provedor confirma pagamento
# (pendente -> recebido), ela registra uma baixa financeira de verdade no
# ledger de contas_receber_baixas (ver abaixo) — o mesmo efeito de
# `registrar_baixa_receber` (financeiro.py), que exige a permissão de
# ESCRITA `financeiro.registrar_baixa_receber`, não `financeiro.
# visualizar`. Antes desta fase, qualquer perfil com permissão só de
# VISUALIZAR o módulo Financeiro conseguia, na prática, dar baixa numa
# conta a receber clicando em "Consultar status".
@requires_permission("financeiro", "registrar_baixa_receber")
def consultar_status(boleto_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    boleto = _boleto_ou_404(conn, boleto_id)

    if boleto["status"] != "pendente":
        # Já é um status final para fins de consulta (recebido/vencido/
        # cancelado/erro) — não gasta uma chamada de rede à toa. "vencido"
        # ainda pode, na prática, ser pago em atraso do lado do provedor,
        # mas isso é responsabilidade de um botão de "Consultar status"
        # específico se o cliente pedir — não muda automaticamente aqui.
        return jsonify(boleto)

    config = boleto_service.obter_configuracao(conn)
    resultado = boleto_service._consultar_no_provedor(config, boleto["id_pagamento_provedor"])

    conn.execute(
        """
        UPDATE boletos SET status = ?, linha_digitavel = COALESCE(?, linha_digitavel),
               codigo_barras = COALESCE(?, codigo_barras), url_boleto = COALESCE(?, url_boleto),
               mensagem_provedor = ?, atualizado_em = ?
        WHERE id = ?
        """,
        (
            resultado["status"], resultado.get("linha_digitavel"), resultado.get("codigo_barras"),
            resultado.get("url_boleto"), resultado.get("mensagem_provedor"), boleto_service._now_iso(), boleto_id,
        ),
    )
    audit.registrar(
        conn, tabela="boletos", registro_id=boleto_id, usuario_id=usuario_atual["id"],
        acao="boleto_status_consultado", valor_anterior={"status": boleto["status"]}, valor_novo={"status": resultado["status"]},
        ip=client_ip(), dispositivo=client_device(),
    )

    # Fase 71 — quando o provedor confirma que o boleto foi PAGO (transição
    # pendente -> recebido), o sistema registra a baixa automaticamente no
    # ledger de contas_receber_baixas — SEM passar pela fila de aprovação
    # de baixas acima da alçada (Fase 31): aquela fila existe para
    # desconfiar de um HUMANO afirmando "isto foi pago" sem prova; aqui é o
    # próprio gateway de pagamentos confirmando o recebimento, uma fonte
    # com mais autoridade que um lançamento manual, então o registro é
    # direto. Só acontece na transição (boleto["status"] antes era
    # 'pendente'), nunca de novo se a mesma consulta for repetida depois.
    if boleto["status"] == "pendente" and resultado["status"] == "recebido":
        conta = _conta_receber_ou_404(conn, boleto["conta_receber_id"])
        total_baixado_atual = conn.execute(
            "SELECT COALESCE(SUM(valor), 0) AS total FROM contas_receber_baixas WHERE conta_receber_id = ?",
            (conta["id"],),
        ).fetchone()["total"]
        valor_baixa = min(boleto["valor"], conta["valor_total"] - total_baixado_atual)
        if valor_baixa > 0.0000001:
            cur = conn.execute(
                """
                INSERT INTO contas_receber_baixas (conta_receber_id, valor, forma_pagamento, data_pagamento, observacao, criado_por)
                VALUES (?, ?, 'boleto', ?, ?, ?)
                """,
                (conta["id"], valor_baixa, _hoje_iso_data(), f"Baixa automática — boleto #{boleto_id} confirmado pelo provedor.", usuario_atual["id"]),
            )
            novo_status = "pago" if (total_baixado_atual + valor_baixa) >= conta["valor_total"] - 0.0000001 else "pago_parcial"
            conn.execute("UPDATE contas_receber SET status = ? WHERE id = ?", (novo_status, conta["id"]))
            audit.registrar(
                conn, tabela="contas_receber_baixas", registro_id=cur.lastrowid, usuario_id=usuario_atual["id"],
                acao="baixa_receber_registrada_automaticamente_por_boleto",
                valor_novo={"conta_receber_id": conta["id"], "valor": valor_baixa, "boleto_id": boleto_id, "novo_status": novo_status},
                ip=client_ip(), dispositivo=client_device(),
            )

    return jsonify(_boleto_ou_404(conn, boleto_id))


@bp.post("/<int:boleto_id>/cancelar")
@requires_permission("financeiro", "cancelar_boleto")
def cancelar_boleto(boleto_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    justificativa = (dados.get("justificativa") or "").strip()
    conn = get_db()
    boleto = _boleto_ou_404(conn, boleto_id)

    if boleto["status"] != "pendente":
        raise ApiError("Só é possível cancelar um boleto ainda pendente (não pago, vencido ou já cancelado).", status=400)
    if not justificativa:
        raise ApiError("Informe a justificativa do cancelamento.", status=400)

    config = boleto_service.obter_configuracao(conn)
    boleto_service._cancelar_no_provedor(config, boleto["id_pagamento_provedor"])

    conn.execute(
        "UPDATE boletos SET status = 'cancelado', justificativa_cancelamento = ?, cancelado_em = ?, cancelado_por = ?, atualizado_em = ? WHERE id = ?",
        (justificativa, boleto_service._now_iso(), usuario_atual["id"], boleto_service._now_iso(), boleto_id),
    )
    audit.registrar(
        conn, tabela="boletos", registro_id=boleto_id, usuario_id=usuario_atual["id"],
        acao="boleto_cancelado", valor_anterior={"status": "pendente"}, valor_novo={"status": "cancelado", "justificativa": justificativa},
        ip=client_ip(), dispositivo=client_device(),
    )
    return jsonify(_boleto_ou_404(conn, boleto_id))
