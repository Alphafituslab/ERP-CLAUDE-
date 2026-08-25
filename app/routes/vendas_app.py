"""
Fase 36 — Aplicativo de Vendas para Vendedores (força de vendas em campo).

Este blueprint é a superfície HTTP usada pelo app do vendedor — NUNCA pela
tela de desktop de Comercial (que continua em app/routes/comercial.py, sem
nenhuma mudança de comportamento para quem já usa ela hoje). As duas telas
compartilham o mesmo pedido de venda de sempre (`pedidos_venda` e afins) e,
onde a regra de negócio é idêntica (confirmar = alocar por FEFO; cancelar =
liberar a reserva), reaproveitam literalmente a mesma função Python
(`confirmar_pedido_internamente` / `cancelar_pedido_internamente`, extraídas
de comercial.py na Fase 36) — não existem duas implementações da mesma
regra que possam um dia divergir.

O que é NOVO aqui, e não existe em lugar nenhum do sistema antes da Fase 36:

1) RESERVA TEMPORÁRIA ("soft-hold") — quando um vendedor coloca um item no
   carrinho de um rascunho, ele passa a contar como "comprometido" para
   TODOS OS OUTROS vendedores (ver `_comprometido_em_rascunhos_abertos`),
   sem tocar em nenhuma tabela de reserva física de estoque — essa
   continua só existindo depois da confirmação de verdade
   (`pedido_venda_reservas`), exatamente como desde a Fase 5. A reserva
   soft dura enquanto a "sessão" do rascunho (`sessoes_rascunho_app_vendas`)
   estiver ativa; ela se encerra de três formas — ver o comentário no topo
   de migrations/schema_fase36.sql para o detalhe de cada uma.

   Importante: quem realmente "ganha" o estoque na disputa entre dois
   vendedores que colocaram o mesmo item no carrinho é decidido no
   ENVIO (`enviar_rascunho`, abaixo), que reaproveita a alocação FEFO real
   de `confirmar_pedido_internamente` — ou seja, a garantia final não é
   nova nem depende de nenhum lock novo: é a mesma garantia de
   "confirmação tudo-ou-nada contra o saldo físico" que o sistema já tem
   desde a Fase 5. O soft-hold só existe para dar VISIBILIDADE justa antes
   disso (evitar que um vendedor monte um pedido inteiro em cima de um
   saldo que, para ele, já não é mais real).

2) VERBA COMERCIAL — crédito do CLIENTE (não do vendedor), gerado
   progressivamente a cada venda EXPEDIDA (ver comercial.py:expedir) e
   utilizável para abater o valor de um pedido futuro qualquer, aplicado
   aqui ainda no rascunho (`aplicar_verba_rascunho`) e congelado na
   confirmação — ver o cabeçalho de migrations/schema_fase36.sql para o
   racional completo e a limitação documentada (ainda não existe reversão
   de verba, por não existir ainda um fluxo de devolução de pedido).

3) COMISSÃO DO VENDEDOR — nesta versão (MVP), um único percentual global
   (`configuracoes_comercial.percentual_comissao_padrao`), sem ainda
   permitir um percentual diferente por vendedor. O vendedor vê SEMPRE dois
   números lado a lado (`minhas_comissoes`, abaixo): a comissão PROJETADA
   (sobre o valor total da conta a receber gerada pela venda) e a comissão
   REALIZADA (proporcional ao que já foi efetivamente baixado/liquidado
   daquela conta — nunca sobre o valor cheio antes de o cliente pagar) —
   exatamente a distinção pedida: "ele pode ver a projeção, mas a comissão
   será sempre na liquidez do boleto, ou no pagamento efetivo da compra".

Limitações desta fase, documentadas de propósito (não são bugs — são
escolhas conscientes de escopo para a primeira entrega, a serem revistas
"conforme for usando", como o próprio usuário pediu):
  - Um vendedor só pode ter UM rascunho aberto por vez neste app (não um
    carrinho por cliente). Simplifica a primeira versão; se o uso real
    mostrar que múltiplos carrinhos simultâneos são necessários, dá para
    remover essa restrição sem quebrar nada do que já existe.
  - "Fechar o app" é detectado por MELHOR ESFORÇO: o app deveria chamar
    `abandonar_rascunho` ao fechar, mas nenhum evento de fechamento de
    navegador/app é 100% confiável — por isso existe TAMBÉM a expiração
    automática por inatividade (`_expirar_sessoes_rascunho_vencidas`),
    verificada de forma OPORTUNISTA (não é um cron de sistema de verdade)
    no início de toda rota deste blueprint — mesmo espírito já usado nos
    agendamentos de contagem de estoque da Fase 35.
  - Não existe ainda uma tabela de preços por item — o vendedor digita o
    preço unitário manualmente, exatamente como a tela de desktop já
    exige desde a Fase 5 (não é uma regressão desta fase).
"""
import datetime

from flask import Blueprint, g, jsonify, request

from .. import audit
from ..context import ApiError, ForbiddenError, client_device, client_ip, get_db
from ..permissions import requires_permission
from .clientes_documentos import _inserir_documento_cliente, _validar_e_decodificar_documento
from .comercial import (
    CAMPOS_FISCAIS_CLIENTE_EDITAVEIS,
    _alocar_fefo,
    _cliente_ou_404,
    _gerar_numero_pedido,
    _now_iso,
    _pedido_detalhado,
    _pedido_ou_404,
    _validar_item_vendavel,
    cancelar_pedido_internamente,
    confirmar_pedido_ou_solicitar_aprovacao,
)
from .financeiro import _total_baixado

bp = Blueprint("vendas_app", __name__, url_prefix="/api/v1/vendas-app")

# "Impossivelmente grande": usado só para perguntar a `_alocar_fefo` "o
# quanto você conseguiria cobrir agora, no limite?" sem de fato alocar nada
# (é código de LEITURA — ver `_saldo_fisico_disponivel_item`). O custo do
# loop dentro de `_alocar_fefo` depende do número de combinações
# (lote, posição) existentes para o item, nunca do tamanho deste número.
QUANTIDADE_IMPOSSIVEL = 10 ** 9


# ============================================================
# CONFIGURAÇÃO DO MÓDULO COMERCIAL
# ============================================================
def _configuracao_comercial(conn):
    row = conn.execute("SELECT * FROM configuracoes_comercial WHERE id = 1").fetchone()
    if row is None:
        # Defensivo (Fase 73): nunca deveria acontecer num banco
        # inicializado pelas migrations (a Fase 36 já semeia a linha
        # única), mas devolve o padrão em vez de um 500 — mesmo espírito de
        # `estoque._configuracao_estoque`/`financeiro._limite_dias_estorno_
        # baixa`, que já tratam esse caso defensivamente.
        return {
            "id": 1, "percentual_verba_gerada": 0, "percentual_comissao_padrao": 0,
            "minutos_expiracao_rascunho": 240, "atualizado_em": None, "atualizado_por": None,
        }
    return dict(row)


def _nova_expiracao(conn):
    minutos = _configuracao_comercial(conn)["minutos_expiracao_rascunho"]
    return (datetime.datetime.utcnow() + datetime.timedelta(minutes=minutos)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@bp.get("/configuracao")
@requires_permission("comercial", "configurar_comercial")
def obter_configuracao():
    conn = get_db()
    return jsonify(_configuracao_comercial(conn))


@bp.put("/configuracao")
@requires_permission("comercial", "configurar_comercial")
def editar_configuracao():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()
    atual = _configuracao_comercial(conn)

    percentual_verba_gerada = dados.get("percentual_verba_gerada", atual["percentual_verba_gerada"])
    percentual_comissao_padrao = dados.get("percentual_comissao_padrao", atual["percentual_comissao_padrao"])
    minutos_expiracao_rascunho = dados.get("minutos_expiracao_rascunho", atual["minutos_expiracao_rascunho"])
    try:
        percentual_verba_gerada = float(percentual_verba_gerada)
        percentual_comissao_padrao = float(percentual_comissao_padrao)
        minutos_expiracao_rascunho = int(minutos_expiracao_rascunho)
    except (TypeError, ValueError):
        raise ApiError("percentual_verba_gerada, percentual_comissao_padrao e minutos_expiracao_rascunho devem ser numéricos.", status=400)

    if not (0 <= percentual_verba_gerada <= 100):
        raise ApiError("percentual_verba_gerada deve estar entre 0 e 100.", status=400)
    if not (0 <= percentual_comissao_padrao <= 100):
        raise ApiError("percentual_comissao_padrao deve estar entre 0 e 100.", status=400)
    if minutos_expiracao_rascunho <= 0:
        raise ApiError("minutos_expiracao_rascunho deve ser maior que zero.", status=400)

    # Fase 73 (achado de auditoria — Fase 72): esta era uma das duas
    # tabelas de configuração singleton que ainda usava UPDATE simples em
    # vez do padrão INSERT...ON CONFLICT DO UPDATE já usado nas outras 7
    # (configuracoes_estoque, configuracoes_financeiro, etc. — ver
    # estoque.py/financeiro.py/memorial_administracao.py/notificacoes.py/
    # sistema.py). Um UPDATE simples silenciosamente não faz nada se a
    # linha id=1 nunca existiu (0 linhas afetadas, sem erro); o upsert
    # garante o mesmo comportamento robusto dos demais — cria a linha se
    # faltar, atualiza se já existir.
    conn.execute(
        """
        INSERT INTO configuracoes_comercial
            (id, percentual_verba_gerada, percentual_comissao_padrao, minutos_expiracao_rascunho, atualizado_em, atualizado_por)
        VALUES (1, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            percentual_verba_gerada = excluded.percentual_verba_gerada,
            percentual_comissao_padrao = excluded.percentual_comissao_padrao,
            minutos_expiracao_rascunho = excluded.minutos_expiracao_rascunho,
            atualizado_em = excluded.atualizado_em,
            atualizado_por = excluded.atualizado_por
        """,
        (percentual_verba_gerada, percentual_comissao_padrao, minutos_expiracao_rascunho, _now_iso(), usuario_atual["id"]),
    )
    audit.registrar(conn, tabela="configuracoes_comercial", registro_id=1, usuario_id=usuario_atual["id"],
                     acao="configuracao_comercial_alterada", valor_anterior=atual,
                     valor_novo={"percentual_verba_gerada": percentual_verba_gerada,
                                 "percentual_comissao_padrao": percentual_comissao_padrao,
                                 "minutos_expiracao_rascunho": minutos_expiracao_rascunho},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify(_configuracao_comercial(conn))


# ============================================================
# CADASTRO DE CLIENTE EM CAMPO (Fase 103) — documento obrigatório
# ============================================================
# Pedido do usuário: quando o vendedor visita um cliente e cadastra ele pelo
# app, é obrigatório anexar ao menos um documento do cliente (ou bater foto
# na hora, via `capture="environment"` no input de arquivo do navegador —
# o frontend cuida disso, aqui só chega o base64 já capturado).
#
# Cliente + documento(s) são criados numa ÚNICA chamada, tudo-ou-nada:
# `app/context.py::close_db` faz commit automático ao fim de QUALQUER
# request que não estoure uma exceção não tratada — inclusive um ApiError
# (4xx) tratado por `_handle_api_error`. Ou seja, se o cliente já tivesse
# sido inserido e só DEPOIS a validação do documento falhasse, o INSERT do
# cliente teria sido mantido mesmo com o pedido inteiro "falhando" para
# quem chamou. Por isso TODOS os documentos são validados/decodificados
# ANTES de qualquer INSERT (nem o do cliente, nem o de nenhum documento) —
# mesmo cuidado já usado noutras rotas multi-escrita do sistema (ex.:
# confirmar_pedido_ou_solicitar_aprovacao, em comercial.py).
@bp.post("/clientes")
@requires_permission("comercial", "cadastrar_cliente")
def criar_cliente_em_campo():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    conn = get_db()

    razao_social = (dados.get("razao_social") or "").strip()
    cnpj = (dados.get("cnpj") or "").strip()
    if not razao_social or not cnpj:
        raise ApiError("Informe razao_social e cnpj.", status=400)
    if conn.execute("SELECT id FROM clientes WHERE cnpj = ?", (cnpj,)).fetchone():
        raise ApiError("Já existe um cliente com este CNPJ.", status=409)

    documentos_entrada = dados.get("documentos")
    if not documentos_entrada or not isinstance(documentos_entrada, list):
        raise ApiError(
            "É obrigatório anexar ao menos um documento do cliente (foto ou arquivo) para cadastrar pelo "
            "aplicativo de vendas.",
            status=400, codigo="documento_obrigatorio",
        )
    # Valida e decodifica TODOS os documentos primeiro (sem escrever nada
    # ainda) — ver nota acima sobre por que a ordem importa aqui.
    documentos_validados = [_validar_e_decodificar_documento(doc) for doc in documentos_entrada]

    valores_fiscais = [dados.get(campo) for campo in CAMPOS_FISCAIS_CLIENTE_EDITAVEIS]
    cur = conn.execute(
        f"""
        INSERT INTO clientes (razao_social, nome_fantasia, cnpj, endereco, email, criado_por,
               {', '.join(CAMPOS_FISCAIS_CLIENTE_EDITAVEIS)})
        VALUES (?, ?, ?, ?, ?, ?, {', '.join('?' for _ in CAMPOS_FISCAIS_CLIENTE_EDITAVEIS)})
        """,
        (razao_social, dados.get("nome_fantasia"), cnpj, dados.get("endereco"), dados.get("email"),
         usuario_atual["id"], *valores_fiscais),
    )
    cliente_id = cur.lastrowid
    audit.registrar(conn, tabela="clientes", registro_id=cliente_id, usuario_id=usuario_atual["id"],
                     acao="cliente_criado_via_app_vendas", valor_novo={"razao_social": razao_social, "cnpj": cnpj},
                     ip=client_ip(), dispositivo=client_device())

    documentos_ids = []
    for doc_validado in documentos_validados:
        documento_id = _inserir_documento_cliente(conn, cliente_id, doc_validado, usuario_atual["id"])
        documentos_ids.append(documento_id)
        audit.registrar(
            conn, tabela="clientes_documentos", registro_id=documento_id, usuario_id=usuario_atual["id"],
            acao="documento_cliente_enviado",
            valor_novo={"cliente_id": cliente_id, "nome_arquivo": doc_validado[1], "tamanho": doc_validado[4]},
            ip=client_ip(), dispositivo=client_device(),
        )

    cliente = _cliente_ou_404(conn, cliente_id)
    cliente["documentos_ids"] = documentos_ids
    return jsonify({"cliente": cliente}), 201


# ============================================================
# SALDO DISPONÍVEL PARA VENDA (físico real + reserva temporária)
# ============================================================
def _saldo_fisico_disponivel_item(conn, item_id):
    """Reaproveita a MESMA alocação FEFO usada em confirmar_pedido_internamente
    (comercial.py) com uma quantidade impossível só para descobrir quanto
    ela conseguiria cobrir agora — ou seja, o saldo físico já líquido de
    tudo que outros pedidos 'confirmado' e ordens de produção
    'liberada'/'em_producao' têm reservado. Não escreve nada no banco (é só
    leitura); reaproveitar em vez de recalcular do zero garante que o
    número mostrado ao vendedor no catálogo é exatamente o mesmo que vai
    decidir, no envio, se o pedido dele cabe ou não."""
    _, coberto = _alocar_fefo(conn, item_id, QUANTIDADE_IMPOSSIVEL)
    return coberto


def _comprometido_em_rascunhos_abertos(conn, item_id, excluir_pedido_id=None):
    """Soma da quantidade deste item já colocada em rascunhos do APP DE
    VENDAS cuja sessão ainda está viva (não encerrada e ainda não vencida)
    — é isto que dá a um vendedor a "reserva temporária" pedida: enquanto
    outro vendedor está com um item no carrinho, ele desaparece do saldo
    disponível mostrado aqui para os demais, sem tocar em nenhuma tabela de
    reserva física de estoque. `excluir_pedido_id` deixa de fora o próprio
    rascunho de quem está perguntando, para o vendedor ver o saldo já
    considerando o que ELE MESMO colocou no carrinho, não como um
    concorrente do próprio carrinho (ver `_saldo_disponivel_para_venda`)."""
    params = [item_id, _now_iso()]
    clausula_excluir = ""
    if excluir_pedido_id is not None:
        clausula_excluir = "AND pv.id != ?"
        params.append(excluir_pedido_id)
    total = conn.execute(
        f"""
        SELECT COALESCE(SUM(pvi.quantidade), 0) AS total
        FROM pedido_venda_itens pvi
        JOIN pedidos_venda pv ON pv.id = pvi.pedido_id
        JOIN sessoes_rascunho_app_vendas s ON s.pedido_venda_id = pv.id
        WHERE pvi.item_id = ? AND pv.status = 'rascunho'
          AND s.encerrada_em IS NULL AND s.expira_em > ?
          {clausula_excluir}
        """,
        params,
    ).fetchone()["total"]
    return total


def _saldo_disponivel_para_venda(conn, item_id, excluir_pedido_id=None):
    """O TETO até onde o rascunho de `excluir_pedido_id` (se informado) pode
    crescer para este item: saldo físico menos o que TODOS OS OUTROS
    rascunhos abertos já comprometeram. Por ser um teto (não um "quanto
    ainda posso somar"), quem chama compara a quantidade TOTAL já no
    próprio rascunho + a quantidade nova pedida contra este valor — nunca
    soma este valor a mais quantidade já reservada pelo próprio vendedor
    (ver `adicionar_item_rascunho`)."""
    fisico = _saldo_fisico_disponivel_item(conn, item_id)
    comprometido_por_outros = _comprometido_em_rascunhos_abertos(conn, item_id, excluir_pedido_id)
    return max(0.0, fisico - comprometido_por_outros)


# ============================================================
# SESSÃO DE RASCUNHO (reserva temporária) — ciclo de vida
# ============================================================
def _expirar_sessoes_rascunho_vencidas(conn):
    """Varredura OPORTUNISTA (não um cron de sistema de verdade — mesmo
    espírito da Fase 35): roda no início de toda rota deste blueprint.
    Encontra toda sessão ainda ativa cujo `expira_em` já passou, cancela o
    pedido correspondente (só se ele AINDA estiver em 'rascunho' — se por
    algum motivo já tiver sido confirmado/cancelado por outro caminho
    antes desta varredura rodar, não toca nele) e marca a sessão como
    encerrada por 'expirado'."""
    agora = _now_iso()
    vencidas = conn.execute(
        """
        SELECT s.*, pv.status AS pedido_status
        FROM sessoes_rascunho_app_vendas s
        JOIN pedidos_venda pv ON pv.id = s.pedido_venda_id
        WHERE s.encerrada_em IS NULL AND s.expira_em <= ?
        """,
        (agora,),
    ).fetchall()
    for sessao in vencidas:
        sessao = dict(sessao)
        if sessao["pedido_status"] == "rascunho":
            cancelar_pedido_internamente(
                conn, sessao["pedido_venda_id"], sessao["vendedor_id"],
                "Rascunho expirado automaticamente pelo aplicativo de vendas por inatividade.",
            )
        conn.execute(
            "UPDATE sessoes_rascunho_app_vendas SET encerrada_em = ?, motivo_encerramento = 'expirado' WHERE id = ?",
            (agora, sessao["id"]),
        )
        audit.registrar(conn, tabela="sessoes_rascunho_app_vendas", registro_id=sessao["id"], usuario_id=sessao["vendedor_id"],
                         acao="sessao_rascunho_expirada", valor_anterior={"expira_em": sessao["expira_em"]},
                         valor_novo={"motivo_encerramento": "expirado"}, ip=client_ip(), dispositivo=client_device())


def _sessao_ativa_do_vendedor(conn, vendedor_id):
    row = conn.execute(
        "SELECT * FROM sessoes_rascunho_app_vendas WHERE vendedor_id = ? AND encerrada_em IS NULL ORDER BY id DESC LIMIT 1",
        (vendedor_id,),
    ).fetchone()
    return dict(row) if row else None


def _sessao_do_pedido_ou_erro(conn, pedido_id, vendedor_id):
    """Checagem central que implementa "fechar perde o direito, e se outro
    enviar primeiro o direito já era": qualquer chamada contra um rascunho
    cuja sessão já foi encerrada (por expiração, por o próprio vendedor ter
    fechado, ou porque já foi enviado) cai aqui como erro — mesmo que o
    pedido em si ainda exista."""
    sessao = conn.execute(
        "SELECT * FROM sessoes_rascunho_app_vendas WHERE pedido_venda_id = ?", (pedido_id,)
    ).fetchone()
    if sessao is None:
        raise ApiError("Este pedido não é um rascunho do aplicativo de vendas.", status=404)
    sessao = dict(sessao)
    if sessao["vendedor_id"] != vendedor_id:
        raise ForbiddenError("Este rascunho pertence a outro vendedor.")
    if sessao["encerrada_em"] is not None:
        raise ApiError(
            f"Este rascunho não está mais ativo (motivo: {sessao['motivo_encerramento']}) — provavelmente "
            "por inatividade, ou porque foi fechado ou enviado. Inicie um novo rascunho.",
            status=409, codigo="rascunho_encerrado",
        )
    return sessao


def _tocar_sessao(conn, sessao_id):
    """"Heartbeat": qualquer interação com o rascunho (adicionar/remover
    item, aplicar verba, ou simplesmente consultar `meu_rascunho` — que é
    o que o app chama ao sincronizar com o ERP) empurra a expiração para
    frente, para que um vendedor ainda ativamente montando um pedido nunca
    perca a reserva por só ter demorado mais que `minutos_expiracao_rascunho`
    entre um clique e outro."""
    nova_expiracao = _nova_expiracao(conn)
    conn.execute("UPDATE sessoes_rascunho_app_vendas SET expira_em = ? WHERE id = ?", (nova_expiracao, sessao_id))
    return nova_expiracao


# ============================================================
# VERBA COMERCIAL DO CLIENTE
# ============================================================
def _saldo_verba_disponivel(conn, cliente_id):
    row = conn.execute(
        """
        SELECT COALESCE(SUM(CASE WHEN tipo = 'gerada' THEN valor ELSE -valor END), 0) AS saldo
        FROM verbas_comerciais_lancamentos WHERE cliente_id = ?
        """,
        (cliente_id,),
    ).fetchone()
    return row["saldo"]


@bp.get("/clientes/<int:cliente_id>/verba")
@requires_permission("vendas_app", "usar")
def verba_cliente(cliente_id):
    conn = get_db()
    _cliente_ou_404(conn, cliente_id)
    saldo = _saldo_verba_disponivel(conn, cliente_id)
    extrato = conn.execute(
        "SELECT * FROM verbas_comerciais_lancamentos WHERE cliente_id = ? ORDER BY id DESC LIMIT 200",
        (cliente_id,),
    ).fetchall()
    return jsonify({"cliente_id": cliente_id, "saldo_disponivel": saldo, "extrato": [dict(r) for r in extrato]})


# ============================================================
# CATÁLOGO
# ============================================================
@bp.get("/catalogo")
@requires_permission("vendas_app", "usar")
def catalogo():
    usuario_atual = g.usuario_atual
    conn = get_db()
    _expirar_sessoes_rascunho_vencidas(conn)
    busca = (request.args.get("busca") or "").strip()

    sessao_ativa = _sessao_ativa_do_vendedor(conn, usuario_atual["id"])
    excluir_pedido_id = sessao_ativa["pedido_venda_id"] if sessao_ativa else None

    clausula_busca = ""
    params = []
    if busca:
        clausula_busca = "AND (i.codigo LIKE ? OR i.descricao LIKE ?)"
        params.extend([f"%{busca}%", f"%{busca}%"])
    itens = conn.execute(
        f"""
        SELECT i.* FROM itens i
        WHERE i.status = 'ativo' AND i.tipo = 'produto_acabado' {clausula_busca}
        ORDER BY i.descricao
        """,
        params,
    ).fetchall()

    resultado = []
    for item in itens:
        item = dict(item)
        item["saldo_disponivel_para_venda"] = _saldo_disponivel_para_venda(conn, item["id"], excluir_pedido_id)
        resultado.append(item)
    return jsonify(resultado)


# ============================================================
# PORTFÓLIO (Fase 77) — mesma consulta do catálogo acima, mas agrupada por
# categoria para a tela do vendedor navegar visualmente (cartões clicáveis)
# em vez de escolher num <select> comprido. `categoria` é opcional
# (ver migrations/schema_fase77.sql) — item sem categoria cadastrada cai em
# "Outros", nunca fica invisível no Portfólio por falta desse campo.
# ============================================================
CATEGORIA_PADRAO_PORTFOLIO = "Outros"


@bp.get("/portfolio")
@requires_permission("vendas_app", "usar")
def portfolio():
    usuario_atual = g.usuario_atual
    conn = get_db()
    _expirar_sessoes_rascunho_vencidas(conn)
    busca = (request.args.get("busca") or "").strip()

    sessao_ativa = _sessao_ativa_do_vendedor(conn, usuario_atual["id"])
    excluir_pedido_id = sessao_ativa["pedido_venda_id"] if sessao_ativa else None

    clausula_busca = ""
    params = []
    if busca:
        clausula_busca = "AND (i.codigo LIKE ? OR i.descricao LIKE ? OR i.categoria LIKE ?)"
        params.extend([f"%{busca}%", f"%{busca}%", f"%{busca}%"])
    itens = conn.execute(
        f"""
        SELECT i.* FROM itens i
        WHERE i.status = 'ativo' AND i.tipo = 'produto_acabado' {clausula_busca}
        ORDER BY COALESCE(i.categoria, '{CATEGORIA_PADRAO_PORTFOLIO}'), i.descricao
        """,
        params,
    ).fetchall()

    categorias = {}
    for item in itens:
        item = dict(item)
        item["saldo_disponivel_para_venda"] = _saldo_disponivel_para_venda(conn, item["id"], excluir_pedido_id)
        categoria = item["categoria"] or CATEGORIA_PADRAO_PORTFOLIO
        categorias.setdefault(categoria, []).append(item)

    return jsonify({
        "categorias": [{"nome": nome, "itens": lista} for nome, lista in categorias.items()],
        "total_itens": len(itens),
    })


# ============================================================
# DUPLICAR PEDIDO (Fase 77) — "usar como modelo": copia os itens de
# qualquer pedido já existente (do próprio vendedor ou não, rascunho ou já
# enviado/expedido) para um rascunho NOVO no App de Vendas, do MESMO jeito
# que o vendedor montaria manualmente item a item. Reaproveita
# `iniciar_rascunho`/`adicionar_item_rascunho` por baixo dos panos (mesmas
# validações de saldo disponível e de "só um rascunho aberto por vez") em
# vez de inserir direto no banco, para nunca divergir da regra de negócio
# de quem monta o carrinho na mão.
# ============================================================
@bp.post("/pedidos/<int:pedido_origem_id>/duplicar")
@requires_permission("vendas_app", "usar")
def duplicar_pedido(pedido_origem_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    _expirar_sessoes_rascunho_vencidas(conn)

    if _sessao_ativa_do_vendedor(conn, usuario_atual["id"]) is not None:
        raise ApiError(
            "Você já tem um rascunho aberto — envie-o ou abandone-o antes de duplicar outro pedido "
            "(o aplicativo de vendas trabalha com um carrinho por vez nesta versão).",
            status=409, codigo="rascunho_ja_aberto",
        )
    origem = _pedido_ou_404(conn, pedido_origem_id)
    itens_origem = conn.execute(
        "SELECT item_id, quantidade, unidade, preco_unitario FROM pedido_venda_itens WHERE pedido_id = ? ORDER BY id",
        (pedido_origem_id,),
    ).fetchall()
    if not itens_origem:
        raise ApiError("Este pedido não tem itens para duplicar.", status=400)

    cliente = _cliente_ou_404(conn, origem["cliente_id"])
    if cliente["status"] != "ativo":
        raise ApiError("Não é possível duplicar: o cliente deste pedido está inativo.", status=400)

    numero = _gerar_numero_pedido()
    cur = conn.execute(
        "INSERT INTO pedidos_venda (numero, cliente_id, criado_por, vendedor_id) VALUES (?, ?, ?, ?)",
        (numero, origem["cliente_id"], usuario_atual["id"], usuario_atual["id"]),
    )
    pedido_id = cur.lastrowid
    expira_em = _nova_expiracao(conn)
    cur_sessao = conn.execute(
        "INSERT INTO sessoes_rascunho_app_vendas (pedido_venda_id, vendedor_id, expira_em) VALUES (?, ?, ?)",
        (pedido_id, usuario_atual["id"], expira_em),
    )

    # Itens sem saldo suficiente hoje (ex.: estoque caiu desde o pedido
    # original) são pulados em vez de travar a duplicação inteira — o
    # vendedor vê no retorno quais entraram e quais ficaram de fora, e
    # decide se completa manualmente com outra quantidade/item.
    itens_incluidos = []
    itens_pulados = []
    for linha in itens_origem:
        item_id, quantidade, unidade, preco_unitario = linha["item_id"], linha["quantidade"], linha["unidade"], linha["preco_unitario"]
        try:
            _validar_item_vendavel(conn, item_id)
        except ApiError:
            itens_pulados.append({"item_id": item_id, "motivo": "item não está mais disponível para venda"})
            continue
        saldo_disponivel = _saldo_disponivel_para_venda(conn, item_id, excluir_pedido_id=pedido_id)
        if quantidade > saldo_disponivel + 0.0000001:
            itens_pulados.append({"item_id": item_id, "motivo": f"saldo insuficiente hoje (disponível: {saldo_disponivel})"})
            continue
        conn.execute(
            "INSERT INTO pedido_venda_itens (pedido_id, item_id, quantidade, unidade, preco_unitario) VALUES (?, ?, ?, ?, ?)",
            (pedido_id, item_id, quantidade, unidade, preco_unitario),
        )
        itens_incluidos.append(item_id)

    audit.registrar(conn, tabela="pedidos_venda", registro_id=pedido_id, usuario_id=usuario_atual["id"],
                     acao="rascunho_app_vendas_duplicado_de_outro_pedido",
                     valor_novo={"numero": numero, "pedido_origem_id": pedido_origem_id, "itens_incluidos": itens_incluidos, "itens_pulados": itens_pulados},
                     ip=client_ip(), dispositivo=client_device())

    pedido = _pedido_detalhado(conn, pedido_id)
    pedido["sessao"] = {"id": cur_sessao.lastrowid, "expira_em": expira_em}
    pedido["itens_pulados_da_duplicacao"] = itens_pulados
    return jsonify({"rascunho": pedido}), 201


# ============================================================
# RASCUNHO (carrinho) do vendedor logado
# ============================================================
@bp.get("/meu-rascunho")
@requires_permission("vendas_app", "usar")
def meu_rascunho():
    """Chamada pelo app sempre que sincroniza com o ERP — além de devolver
    o rascunho atual (ou null, se não houver nenhum aberto), estende a
    validade da sessão (ver `_tocar_sessao`), porque sincronizar com
    sucesso é, em si, sinal de que o vendedor ainda está com o app aberto
    e trabalhando nele."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    _expirar_sessoes_rascunho_vencidas(conn)
    sessao = _sessao_ativa_do_vendedor(conn, usuario_atual["id"])
    if sessao is None:
        return jsonify({"rascunho": None})

    nova_expiracao = _tocar_sessao(conn, sessao["id"])
    pedido = _pedido_detalhado(conn, sessao["pedido_venda_id"])
    pedido["sessao"] = {"id": sessao["id"], "criado_em": sessao["criado_em"], "expira_em": nova_expiracao}
    return jsonify({"rascunho": pedido})


@bp.post("/rascunhos")
@requires_permission("vendas_app", "usar")
def iniciar_rascunho():
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    cliente_id = dados.get("cliente_id")
    conn = get_db()
    _expirar_sessoes_rascunho_vencidas(conn)

    if not cliente_id:
        raise ApiError("Informe cliente_id.", status=400)
    cliente = _cliente_ou_404(conn, cliente_id)
    if cliente["status"] != "ativo":
        raise ApiError("Não é possível criar pedido para um cliente inativo.", status=400)

    if _sessao_ativa_do_vendedor(conn, usuario_atual["id"]) is not None:
        raise ApiError(
            "Você já tem um rascunho aberto — envie-o ou abandone-o antes de iniciar outro (o aplicativo de "
            "vendas trabalha com um carrinho por vez nesta versão).",
            status=409, codigo="rascunho_ja_aberto",
        )

    numero = _gerar_numero_pedido()
    cur = conn.execute(
        "INSERT INTO pedidos_venda (numero, cliente_id, criado_por, vendedor_id) VALUES (?, ?, ?, ?)",
        (numero, cliente_id, usuario_atual["id"], usuario_atual["id"]),
    )
    pedido_id = cur.lastrowid
    expira_em = _nova_expiracao(conn)
    cur_sessao = conn.execute(
        "INSERT INTO sessoes_rascunho_app_vendas (pedido_venda_id, vendedor_id, expira_em) VALUES (?, ?, ?)",
        (pedido_id, usuario_atual["id"], expira_em),
    )
    audit.registrar(conn, tabela="pedidos_venda", registro_id=pedido_id, usuario_id=usuario_atual["id"],
                     acao="rascunho_app_vendas_iniciado", valor_novo={"numero": numero, "cliente_id": cliente_id},
                     ip=client_ip(), dispositivo=client_device())

    pedido = _pedido_detalhado(conn, pedido_id)
    pedido["sessao"] = {"id": cur_sessao.lastrowid, "expira_em": expira_em}
    return jsonify({"rascunho": pedido}), 201


@bp.post("/rascunhos/<int:pedido_id>/itens")
@requires_permission("vendas_app", "usar")
def adicionar_item_rascunho(pedido_id):
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    item_id = dados.get("item_id")
    quantidade = dados.get("quantidade")
    unidade = dados.get("unidade")
    preco_unitario = dados.get("preco_unitario")
    conn = get_db()
    _expirar_sessoes_rascunho_vencidas(conn)
    sessao = _sessao_do_pedido_ou_erro(conn, pedido_id, usuario_atual["id"])

    if not item_id or not quantidade or not unidade or preco_unitario is None:
        raise ApiError("Informe item_id, quantidade, unidade e preco_unitario.", status=400)
    try:
        quantidade = float(quantidade)
        preco_unitario = float(preco_unitario)
    except (TypeError, ValueError):
        raise ApiError("quantidade e preco_unitario devem ser numéricos.", status=400)
    if quantidade <= 0:
        raise ApiError("quantidade deve ser maior que zero.", status=400)
    if preco_unitario <= 0:
        raise ApiError("preco_unitario deve ser maior que zero.", status=400)
    _validar_item_vendavel(conn, item_id)

    ja_no_rascunho = conn.execute(
        "SELECT COALESCE(SUM(quantidade), 0) AS total FROM pedido_venda_itens WHERE pedido_id = ? AND item_id = ?",
        (pedido_id, item_id),
    ).fetchone()["total"]
    saldo_disponivel = _saldo_disponivel_para_venda(conn, item_id, excluir_pedido_id=pedido_id)
    if ja_no_rascunho + quantidade > saldo_disponivel + 0.0000001:
        raise ApiError(
            f"Saldo insuficiente: você já tem {ja_no_rascunho} deste item no seu rascunho e está pedindo mais "
            f"{quantidade}, mas o saldo disponível para venda agora é {saldo_disponivel} (descontando o que "
            "outros vendedores já têm reservado em rascunhos abertos e o que já está confirmado em outros "
            "pedidos). Alguém pode ter colocado este item no carrinho depois da última sincronização.",
            status=409, codigo="saldo_insuficiente",
        )

    cur = conn.execute(
        "INSERT INTO pedido_venda_itens (pedido_id, item_id, quantidade, unidade, preco_unitario) VALUES (?, ?, ?, ?, ?)",
        (pedido_id, item_id, quantidade, unidade, preco_unitario),
    )
    nova_expiracao = _tocar_sessao(conn, sessao["id"])
    audit.registrar(conn, tabela="pedido_venda_itens", registro_id=cur.lastrowid, usuario_id=usuario_atual["id"],
                     acao="item_pedido_adicionado_via_app_vendas",
                     valor_novo={"pedido_id": pedido_id, "item_id": item_id, "quantidade": quantidade, "preco_unitario": preco_unitario},
                     ip=client_ip(), dispositivo=client_device())

    pedido = _pedido_detalhado(conn, pedido_id)
    pedido["sessao_expira_em"] = nova_expiracao
    return jsonify({"rascunho": pedido}), 201


@bp.delete("/rascunhos/<int:pedido_id>/itens/<int:item_linha_id>")
@requires_permission("vendas_app", "usar")
def remover_item_rascunho(pedido_id, item_linha_id):
    usuario_atual = g.usuario_atual
    conn = get_db()
    _expirar_sessoes_rascunho_vencidas(conn)
    sessao = _sessao_do_pedido_ou_erro(conn, pedido_id, usuario_atual["id"])

    linha = conn.execute(
        "SELECT * FROM pedido_venda_itens WHERE id = ? AND pedido_id = ?", (item_linha_id, pedido_id)
    ).fetchone()
    if linha is None:
        raise ApiError("Item do pedido não encontrado.", status=404)

    conn.execute("DELETE FROM pedido_venda_itens WHERE id = ?", (item_linha_id,))
    nova_expiracao = _tocar_sessao(conn, sessao["id"])
    audit.registrar(conn, tabela="pedido_venda_itens", registro_id=item_linha_id, usuario_id=usuario_atual["id"],
                     acao="item_pedido_removido_via_app_vendas", valor_anterior=dict(linha),
                     ip=client_ip(), dispositivo=client_device())

    pedido = _pedido_detalhado(conn, pedido_id)
    pedido["sessao_expira_em"] = nova_expiracao
    return jsonify({"rascunho": pedido})


@bp.post("/rascunhos/<int:pedido_id>/verba")
@requires_permission("vendas_app", "usar")
def aplicar_verba_rascunho(pedido_id):
    """Define quanto do saldo de verba comercial do CLIENTE deste rascunho
    será usado para abater o valor deste pedido. Chamar de novo com um
    valor diferente (inclusive 0, para remover) SUBSTITUI o valor anterior
    — nada é lançado no ledger de verbas ainda (isso só acontece na
    expedição, ver comercial.py:expedir); aqui é só uma intenção congelada
    no próprio pedido (`pedidos_venda.verba_utilizada`)."""
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    valor = dados.get("valor")
    conn = get_db()
    _expirar_sessoes_rascunho_vencidas(conn)
    sessao = _sessao_do_pedido_ou_erro(conn, pedido_id, usuario_atual["id"])
    pedido = _pedido_ou_404(conn, pedido_id)

    try:
        valor = float(valor)
    except (TypeError, ValueError):
        raise ApiError("Informe valor numérico de verba a aplicar (0 para remover).", status=400)
    if valor < 0:
        raise ApiError("valor não pode ser negativo.", status=400)

    itens_pedido = conn.execute(
        "SELECT quantidade, preco_unitario FROM pedido_venda_itens WHERE pedido_id = ?", (pedido_id,)
    ).fetchall()
    valor_bruto = sum(i["quantidade"] * i["preco_unitario"] for i in itens_pedido)
    if valor > valor_bruto + 0.0000001:
        raise ApiError(f"O valor de verba ({valor}) não pode ser maior que o valor do pedido ({valor_bruto}).", status=400)

    saldo_verba = _saldo_verba_disponivel(conn, pedido["cliente_id"])
    if valor > saldo_verba + 0.0000001:
        raise ApiError(f"O cliente só tem R$ {saldo_verba:.2f} de saldo de verba comercial disponível.", status=400)

    conn.execute("UPDATE pedidos_venda SET verba_utilizada = ? WHERE id = ?", (valor, pedido_id))
    nova_expiracao = _tocar_sessao(conn, sessao["id"])
    audit.registrar(conn, tabela="pedidos_venda", registro_id=pedido_id, usuario_id=usuario_atual["id"],
                     acao="verba_aplicada_no_rascunho", valor_anterior={"verba_utilizada": pedido["verba_utilizada"]},
                     valor_novo={"verba_utilizada": valor}, ip=client_ip(), dispositivo=client_device())

    pedido_detalhado = _pedido_detalhado(conn, pedido_id)
    pedido_detalhado["sessao_expira_em"] = nova_expiracao
    return jsonify({"rascunho": pedido_detalhado})


@bp.post("/rascunhos/<int:pedido_id>/abandonar")
@requires_permission("vendas_app", "usar")
def abandonar_rascunho(pedido_id):
    """Chamada pelo app quando o vendedor fecha/descarta o rascunho de
    propósito — melhor esforço (não existe evento de fechamento de app 100%
    confiável, ver docstring do módulo); a expiração automática por
    inatividade é a rede de segurança para quando isto não é chamado."""
    usuario_atual = g.usuario_atual
    conn = get_db()
    _expirar_sessoes_rascunho_vencidas(conn)
    sessao = _sessao_do_pedido_ou_erro(conn, pedido_id, usuario_atual["id"])

    cancelar_pedido_internamente(
        conn, pedido_id, usuario_atual["id"],
        "Rascunho descartado pelo próprio vendedor no aplicativo de vendas (ex.: app fechado).",
    )
    agora = _now_iso()
    conn.execute(
        "UPDATE sessoes_rascunho_app_vendas SET encerrada_em = ?, motivo_encerramento = 'fechado_pelo_usuario' WHERE id = ?",
        (agora, sessao["id"]),
    )
    audit.registrar(conn, tabela="sessoes_rascunho_app_vendas", registro_id=sessao["id"], usuario_id=usuario_atual["id"],
                     acao="sessao_rascunho_fechada_pelo_usuario", valor_novo={"motivo_encerramento": "fechado_pelo_usuario"},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify({"status": "ok"})


# Fase 114 — pedido do usuário: "...até colocar o cliente, forma de
# pagamento e ser enviado ao módulo de pedidos". Mesmos valores já usados
# na baixa de conta a receber (Financeiro), pra não inventar um vocabulário
# novo de forma de pagamento dentro do sistema — "dinheiro" cobre também
# "a combinar", que é como o vendedor usa esta opção em campo quando ainda
# não fechou a forma exata com o cliente.
FORMAS_PAGAMENTO_VALIDAS = ("pix", "boleto", "cartao", "dinheiro")


@bp.post("/rascunhos/<int:pedido_id>/enviar")
@requires_permission("vendas_app", "enviar_pedido")
def enviar_rascunho(pedido_id):
    """"Enviar o pedido" = confirmar de verdade, reaproveitando a mesma
    alocação FEFO tudo-ou-nada da tela de desktop
    (`confirmar_pedido_ou_solicitar_aprovacao`, que por sua vez chama
    `confirmar_pedido_internamente` quando cabe no limite de crédito do
    cliente — Fase 63). É AQUI, e não no soft-hold, que a disputa entre
    dois vendedores pelo mesmo saldo se resolve de fato: quem confirmar
    primeiro com sucesso consome o saldo físico real; se o outro vendedor
    tentar enviar depois e o saldo não bater mais, esta chamada falha com
    o mesmo erro de "saldo em estoque insuficiente" que a tela de desktop
    sempre teve — nenhum lock novo foi necessário para isso.

    Fase 63 — se o cliente tiver limite de crédito configurado e este
    pedido estourá-lo, o pedido NÃO é confirmado na hora: vira uma
    solicitação pendente (mesma tela de Comercial no desktop mostra e
    decide sobre ela — o app de vendas não tem uma tela própria de
    aprovação, isso é decisão de quem administra a régua de crédito). Do
    ponto de vista do vendedor, a sessão de rascunho termina do mesmo
    jeito nos dois casos: o rascunho já foi "enviado", só o que muda é se
    ele já virou uma venda confirmada ou se está aguardando aprovação."""
    usuario_atual = g.usuario_atual
    dados = request.get_json(silent=True) or {}
    forma_pagamento = dados.get("forma_pagamento")
    conn = get_db()
    _expirar_sessoes_rascunho_vencidas(conn)
    sessao = _sessao_do_pedido_ou_erro(conn, pedido_id, usuario_atual["id"])

    # Fase 114 — só o App de Vendas exige forma de pagamento no envio (a
    # tela de desktop, em comercial.py, continua sem essa exigência — quem
    # decide isso lá é o Financeiro, na hora da baixa, como sempre foi).
    if forma_pagamento not in FORMAS_PAGAMENTO_VALIDAS:
        raise ApiError(
            f"Informe uma forma de pagamento válida: {', '.join(FORMAS_PAGAMENTO_VALIDAS)}.", status=400,
        )
    conn.execute("UPDATE pedidos_venda SET forma_pagamento = ? WHERE id = ?", (forma_pagamento, pedido_id))

    pedido, status_http = confirmar_pedido_ou_solicitar_aprovacao(conn, pedido_id, usuario_atual["id"])

    agora = _now_iso()
    conn.execute(
        "UPDATE sessoes_rascunho_app_vendas SET encerrada_em = ?, motivo_encerramento = 'enviado' WHERE id = ?",
        (agora, sessao["id"]),
    )
    audit.registrar(conn, tabela="sessoes_rascunho_app_vendas", registro_id=sessao["id"], usuario_id=usuario_atual["id"],
                     acao="sessao_rascunho_enviada", valor_novo={"motivo_encerramento": "enviado"},
                     ip=client_ip(), dispositivo=client_device())
    return jsonify({"pedido": pedido}), status_http


# ============================================================
# MINHAS VENDAS E COMISSÕES
# ============================================================
@bp.get("/minhas-comissoes")
@requires_permission("vendas_app", "usar")
def minhas_comissoes():
    """Vendas (contas a receber geradas por pedidos deste vendedor) cujo
    VENCIMENTO cai no mês/ano pedido — é essa a leitura de "a receber no
    mês". Para cada uma, mostra a comissão PROJETADA (percentual sobre o
    valor total da conta, assumindo que será integralmente paga) ao lado
    da comissão REALIZADA (o mesmo percentual, mas só sobre o que já foi
    efetivamente baixado/liquidado até agora — nunca sobre o valor cheio
    antes do pagamento, exatamente como pedido)."""
    usuario_atual = g.usuario_atual
    conn = get_db()

    hoje = datetime.datetime.utcnow()
    ano = request.args.get("ano", type=int) or hoje.year
    mes = request.args.get("mes", type=int) or hoje.month
    if mes < 1 or mes > 12:
        raise ApiError("mes deve estar entre 1 e 12.", status=400)
    ano_mes = f"{ano:04d}-{mes:02d}"

    percentual = _configuracao_comercial(conn)["percentual_comissao_padrao"]

    contas = conn.execute(
        """
        SELECT cr.*, pv.numero AS pedido_numero, pv.id AS pedido_id, c.razao_social AS cliente_razao_social
        FROM contas_receber cr
        JOIN pedidos_venda pv ON pv.id = cr.pedido_venda_id
        JOIN clientes c ON c.id = pv.cliente_id
        WHERE pv.vendedor_id = ? AND strftime('%Y-%m', cr.vencimento) = ?
        ORDER BY cr.vencimento, cr.id
        """,
        (usuario_atual["id"], ano_mes),
    ).fetchall()

    linhas = []
    total_vendas = 0.0
    total_projetada = 0.0
    total_realizada = 0.0
    for conta in contas:
        conta = dict(conta)
        total_baixado = _total_baixado(conn, "contas_receber_baixas", "conta_receber_id", conta["id"])
        comissao_projetada = conta["valor_total"] * percentual / 100.0
        comissao_realizada = total_baixado * percentual / 100.0
        linhas.append({
            "conta_receber_id": conta["id"],
            "numero_conta": conta["numero"],
            "pedido_id": conta["pedido_id"],
            "pedido_numero": conta["pedido_numero"],
            "cliente_razao_social": conta["cliente_razao_social"],
            "vencimento": conta["vencimento"],
            "status": conta["status"],
            "valor_total": conta["valor_total"],
            "total_baixado": total_baixado,
            "comissao_projetada": comissao_projetada,
            "comissao_realizada": comissao_realizada,
        })
        total_vendas += conta["valor_total"]
        total_projetada += comissao_projetada
        total_realizada += comissao_realizada

    return jsonify({
        "ano": ano,
        "mes": mes,
        "percentual_comissao": percentual,
        "total_vendas": total_vendas,
        "total_comissao_projetada": total_projetada,
        "total_comissao_realizada": total_realizada,
        "contas": linhas,
    })
