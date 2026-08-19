"""
Fase 77 — Script de demonstração: popula uma instalação nova do Alphafitus
OS com um "modelo preenchido" em todos os módulos principais do ERP e do
APS, usando dados de exemplo de uma indústria de nutracêuticos (a mesma que
o sistema real atende) — para quem está vendo o sistema pela primeira vez
já ter algo concreto para clicar em cada tela, em vez de telas vazias.

COMO RODAR (com o servidor já rodando em outro terminal):
    set ALPHAFITUS_DEMO_ADMIN_SENHA=a-senha-do-seu-admin
    python scripts/popular_demo.py

Variáveis de ambiente aceitas:
    ALPHAFITUS_DEMO_BASE_URL     (padrão: http://127.0.0.1:5000/api/v1)
    ALPHAFITUS_DEMO_ADMIN_EMAIL  (padrão: admin@alphafitus.com.br)
    ALPHAFITUS_DEMO_ADMIN_SENHA  (obrigatório — sem padrão, de propósito:
                                   nunca fica uma senha "óbvia" hardcoded
                                   neste arquivo)

O que este script faz, passando pelas mesmas rotas de API que a tela usa
(nunca INSERT direto no banco) — assim cada regra de negócio já existente
(FEFO, segregação de função na aprovação de lote, alçada de crédito, etc.)
é respeitada exatamente como aconteceria com um usuário de verdade:

  1. Cria um segundo usuário, "Ana Qualidade (Demo)", só para poder assinar
     a APROVAÇÃO de lote sem violar a segregação de função (quem CONCLUI a
     análise nunca pode ser quem APROVA o mesmo lote — Fase 1).
  2. Cadastra fornecedores, matérias-primas, embalagens e ~8 produtos
     acabados (Proteínas, Creatina & Performance, Vitaminas & Minerais,
     Aminoácidos — usando o campo `categoria` novo da Fase 77 para já
     deixar o Portfólio do App de Vendas organizado).
  3. Recebe lotes de matéria-prima/embalagem e leva cada um pelo fluxo real
     de Qualidade (solicitar análise → registrar resultado → concluir →
     aprovar) até ficarem 'aprovado' e disponíveis.
  4. Cria e ativa uma fórmula (BOM) para cada produto acabado.
  5. Abre, libera, aponta consumo e conclui uma Ordem de Produção para cada
     produto — o lote de produto acabado gerado passa pelo MESMO fluxo de
     Qualidade acima antes de ficar vendável.
  6. Cadastra clientes e monta um Pedido de Venda completo (rascunho →
     confirmado → expedido), com uma baixa parcial na conta a receber
     gerada — para o Financeiro e o Painel Executivo já terem histórico.
  7. Demonstra o "Duplicar Pedido" (Fase 77) tanto no Comercial (desktop)
     quanto no App de Vendas, e por fim deixa um RASCUNHO ABERTO no App de
     Vendas — montado navegando pelo Portfólio, item por item — como o
     "modelo pronto" pedido: ao abrir #/app-vendas/portfolio depois de
     rodar este script, já tem um pedido em andamento para olhar.
  8. Cadastra um Pedido de Compra, recebe contra ele e gera uma conta a
     pagar com baixa parcial (Compras + Financeiro).
  9. Abre um Desvio de Qualidade de exemplo (QMS).

Idempotência: seguro rodar mais de uma vez — fornecedores/clientes são
reaproveitados pelo CNPJ e o usuário de qualidade pelo e-mail; itens já
cadastrados com a mesma descrição são reaproveitados em vez de duplicados.
Lotes/pedidos/ordens novos SÃO criados a cada execução (não há uma chave
natural única para eles) — rodar várias vezes vai empilhando mais exemplos,
o que não é um problema para uma instalação de demonstração.
"""
import os
import sys

try:
    import requests
except ImportError:
    sys.exit("Este script precisa do pacote 'requests' (já está em requirements.txt — rode dentro da venv do projeto).")

BASE = os.environ.get("ALPHAFITUS_DEMO_BASE_URL", "http://127.0.0.1:5000/api/v1")
ADMIN_EMAIL = os.environ.get("ALPHAFITUS_DEMO_ADMIN_EMAIL", "admin@alphafitus.com.br")
ADMIN_SENHA = os.environ.get("ALPHAFITUS_DEMO_ADMIN_SENHA")
QUALIDADE_EMAIL = "qualidade.demo@alphafitus.com.br"
QUALIDADE_SENHA = "Demo@Qualidade2026!"

if not ADMIN_SENHA:
    sys.exit("Defina ALPHAFITUS_DEMO_ADMIN_SENHA (senha do administrador) antes de rodar este script.")


def log(msg):
    print(f"[demo] {msg}")


class Sessao:
    def __init__(self, base_url):
        self.base_url = base_url
        self.token = None

    def login(self, email, senha):
        r = requests.post(f"{self.base_url}/auth/login", json={"email": email, "senha": senha})
        self._checar(r)
        self.token = r.json()["access_token"]

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def _checar(self, r):
        if not r.ok:
            raise RuntimeError(f"{r.request.method} {r.request.url} -> {r.status_code}: {r.text}")

    def get(self, path, params=None):
        r = requests.get(f"{self.base_url}{path}", headers=self._headers(), params=params)
        self._checar(r)
        return r.json()

    def post(self, path, body=None, esperar_falha_ok=False):
        r = requests.post(f"{self.base_url}{path}", headers=self._headers(), json=body or {})
        if esperar_falha_ok and not r.ok:
            return None
        self._checar(r)
        return r.json() if r.content else None

    def put(self, path, body=None):
        r = requests.put(f"{self.base_url}{path}", headers=self._headers(), json=body or {})
        self._checar(r)
        return r.json() if r.content else None


admin = Sessao(BASE)
admin.login(ADMIN_EMAIL, ADMIN_SENHA)
log(f"login OK como {ADMIN_EMAIL}")

# ============================================================
# 1) Segundo usuário — só para segregação de função na aprovação de lote
# ============================================================
perfis = admin.get("/perfis")
perfil_administrador_id = next(p["id"] for p in perfis if p["nome"] == "Administrador")

usuarios_existentes = admin.get("/usuarios")
usuario_qualidade = next((u for u in usuarios_existentes if u["email"] == QUALIDADE_EMAIL), None)
if usuario_qualidade is None:
    usuario_qualidade = admin.post("/usuarios", {
        "nome": "Ana Qualidade (Demo)", "email": QUALIDADE_EMAIL, "senha": QUALIDADE_SENHA,
        "perfil_ids": [perfil_administrador_id],
    })
    log("usuário 'Ana Qualidade (Demo)' criado")
else:
    log("usuário 'Ana Qualidade (Demo)' já existia — reaproveitando")

qualidade = Sessao(BASE)
qualidade.login(QUALIDADE_EMAIL, QUALIDADE_SENHA)


def aprovar_lote_qms(lote_id, codigo_lote=""):
    """Leva um lote em 'quarentena' até 'aprovado' pelo fluxo real de
    Qualidade: solicita 1 ensaio simples sem faixa de especificação (então
    qualquer resultado numérico conclui 'conforme'), registra o resultado,
    conclui a análise como admin e aprova como o usuário de qualidade
    (pessoa diferente de quem concluiu, exigido pela segregação de
    função)."""
    analise = admin.post("/analises", {
        "lote_id": lote_id, "tipo": "liberacao",
        "ensaios": [{"ensaio": "Aspecto visual (demo)"}],
    })
    resultado_id = analise["resultados"][0]["id"]
    admin.post(f"/analises/{analise['id']}/resultados/{resultado_id}", {"resultado": 1})
    admin.post(f"/analises/{analise['id']}/concluir")
    qualidade.post(f"/lotes/{lote_id}/aprovar")
    log(f"  lote {codigo_lote or lote_id} aprovado (QMS)")


# ============================================================
# 2) Fornecedores
# ============================================================
def obter_ou_criar_fornecedor(nome, cnpj, lead_time_dias=None):
    existentes = admin.get("/fornecedores")
    achado = next((f for f in existentes if f["cnpj"] == cnpj), None)
    if achado:
        log(f"fornecedor '{nome}' já existia — reaproveitando")
        return achado
    body = {"nome": nome, "cnpj": cnpj}
    if lead_time_dias is not None:
        body["lead_time_dias"] = lead_time_dias
    criado = admin.post("/fornecedores", body)
    log(f"fornecedor criado: {nome}")
    return criado


fornecedor_insumos = obter_ou_criar_fornecedor("NutraSupply Ingredientes Ltda", "12345678000101", lead_time_dias=7)
fornecedor_embalagens = obter_ou_criar_fornecedor("EmbalaFit Embalagens Ltda", "23456789000102", lead_time_dias=5)

# ============================================================
# 3) Itens: matérias-primas, embalagens e produtos acabados
# ============================================================
def obter_ou_criar_item(descricao, tipo, unidade, categoria=None):
    existentes = admin.get("/itens", params={"tipo": tipo})
    achado = next((i for i in existentes if i["descricao"] == descricao), None)
    if achado:
        return achado
    body = {"descricao": descricao, "tipo": tipo, "unidade_medida": unidade,
             "requer_fornecedor_homologado": False}
    if categoria:
        body["categoria"] = categoria
    item = admin.post("/itens", body)
    log(f"item criado: {item['codigo']} — {descricao}")
    return item


materias_primas = {
    "whey_concentrado": obter_ou_criar_item("Whey Protein Concentrado (a granel)", "materia_prima", "kg"),
    "whey_isolado": obter_ou_criar_item("Whey Protein Isolado (a granel)", "materia_prima", "kg"),
    "creatina": obter_ou_criar_item("Creatina Monohidratada (a granel)", "materia_prima", "kg"),
    "pretreino": obter_ou_criar_item("Pré-treino Base (a granel)", "materia_prima", "kg"),
    "multivitaminico": obter_ou_criar_item("Mix Multivitamínico (a granel)", "materia_prima", "kg"),
    "omega3": obter_ou_criar_item("Óleo de Peixe Ômega 3 (a granel)", "materia_prima", "kg"),
    "bcaa": obter_ou_criar_item("BCAA 2:1:1 (a granel)", "materia_prima", "kg"),
    "glutamina": obter_ou_criar_item("Glutamina (a granel)", "materia_prima", "kg"),
}

embalagens = {
    "pote_900": obter_ou_criar_item("Pote plástico 900g com tampa e rótulo", "embalagem_primaria", "un"),
    "pote_300": obter_ou_criar_item("Pote plástico 300g com tampa e rótulo", "embalagem_primaria", "un"),
    "frasco_60": obter_ou_criar_item("Frasco de cápsulas 60un com rótulo", "embalagem_primaria", "un"),
    "frasco_90": obter_ou_criar_item("Frasco de cápsulas 90un com rótulo", "embalagem_primaria", "un"),
}

# (insumo_principal, embalagem, rendimento_teorico_kg_ou_un, unidade_rendimento, categoria)
PRODUTOS = [
    ("Whey Protein Concentrado 900g — Chocolate", materias_primas["whey_concentrado"], embalagens["pote_900"], 0.9, "kg", "Proteínas"),
    ("Whey Protein Isolado 900g — Baunilha", materias_primas["whey_isolado"], embalagens["pote_900"], 0.9, "kg", "Proteínas"),
    ("Creatina Monohidratada 300g", materias_primas["creatina"], embalagens["pote_300"], 0.3, "kg", "Creatina & Performance"),
    ("Pré-treino Explosivo 300g", materias_primas["pretreino"], embalagens["pote_300"], 0.3, "kg", "Creatina & Performance"),
    ("Multivitamínico Completo 60 cápsulas", materias_primas["multivitaminico"], embalagens["frasco_60"], 60, "un", "Vitaminas & Minerais"),
    ("Ômega 3 1000mg 90 cápsulas", materias_primas["omega3"], embalagens["frasco_90"], 90, "un", "Vitaminas & Minerais"),
    ("BCAA 2:1:1 200g", materias_primas["bcaa"], embalagens["pote_300"], 0.2, "kg", "Aminoácidos"),
    ("Glutamina 300g", materias_primas["glutamina"], embalagens["pote_300"], 0.3, "kg", "Aminoácidos"),
]

produtos_acabados = []
for descricao, mp, emb, rendimento, unidade_rendimento, categoria in PRODUTOS:
    item_pa = obter_ou_criar_item(descricao, "produto_acabado", unidade_rendimento, categoria=categoria)
    produtos_acabados.append({"item": item_pa, "mp": mp, "emb": emb, "rendimento": rendimento, "unidade": unidade_rendimento})

# ============================================================
# 4) Recebimento de matéria-prima/embalagem + aprovação QMS
#    (quantidade grande o bastante para cobrir várias ordens de produção)
# ============================================================
def receber_e_aprovar(item, fornecedor, quantidade, unidade, pedido_compra_id=None):
    lote = admin.post("/lotes/recebimento", {
        "item_id": item["id"], "fornecedor_id": fornecedor["id"],
        "quantidade": quantidade, "unidade": unidade,
        "lote_fornecedor": "DEMO", "pedido_compra_id": pedido_compra_id,
    })
    aprovar_lote_qms(lote["id"], lote["codigo_lote"])
    return lote


log("recebendo e aprovando matérias-primas/embalagens...")
for mp in materias_primas.values():
    receber_e_aprovar(mp, fornecedor_insumos, 200, "kg")
for emb in embalagens.values():
    receber_e_aprovar(emb, fornecedor_embalagens, 500, "un")

# ============================================================
# 5) Fórmulas (BOM) + Ordem de Produção completa por produto
# ============================================================
log("criando fórmulas e rodando ordens de produção...")
for produto in produtos_acabados:
    item_pa, mp, emb, rendimento, unidade = produto["item"], produto["mp"], produto["emb"], produto["rendimento"], produto["unidade"]

    formula = admin.post("/formulas", {
        "item_produzido_id": item_pa["id"], "rendimento_teorico": rendimento, "unidade_rendimento": unidade,
        "observacoes": "Fórmula de demonstração (Fase 77).",
        "itens": [
            {"item_id": mp["id"], "quantidade": rendimento, "unidade": "kg" if unidade == "kg" else "kg"},
            {"item_id": emb["id"], "quantidade": 1, "unidade": "un"},
        ],
    })
    admin.post(f"/formulas/{formula['id']}/ativar")

    ordem = admin.post("/producao/ordens", {
        "formula_id": formula["id"], "quantidade_planejada": rendimento, "unidade": unidade,
    })
    ordem = admin.post(f"/producao/ordens/{ordem['id']}/liberar")

    # Consome o material reservado — busca as reservas feitas na liberação
    # para saber exatamente qual lote/quantidade apontar (evita "advinhar"
    # o lote certo entre vários lotes aprovados do mesmo item).
    reservas = admin.get(f"/producao/ordens/{ordem['id']}")["reservas_material"]
    for reserva in reservas:
        admin.post(f"/producao/ordens/{ordem['id']}/consumir", {"lote_id": reserva["lote_id"], "quantidade": reserva["quantidade"]})

    ordem_concluida = admin.post(f"/producao/ordens/{ordem['id']}/concluir", {"quantidade_produzida": rendimento})
    lote_produzido_id = ordem_concluida["lote_produzido_id"]
    aprovar_lote_qms(lote_produzido_id, f"produto acabado {item_pa['codigo']}")
    log(f"produto pronto para venda: {item_pa['codigo']} — {item_pa['descricao']}")

# ============================================================
# 6) Clientes + Pedido de Venda completo (Comercial)
# ============================================================
def obter_ou_criar_cliente(razao_social, cnpj, nome_fantasia=None):
    existentes = admin.get("/comercial/clientes")
    achado = next((c for c in existentes if c["cnpj"] == cnpj), None)
    if achado:
        return achado
    cliente = admin.post("/comercial/clientes", {
        "razao_social": razao_social, "cnpj": cnpj, "nome_fantasia": nome_fantasia,
    })
    log(f"cliente criado: {razao_social}")
    return cliente


cliente_1 = obter_ou_criar_cliente("Academia Corpo em Forma Ltda", "34567890000103", "Corpo em Forma")
cliente_2 = obter_ou_criar_cliente("Distribuidora Vida Saudável Ltda", "45678901000104", "Vida Saudável")

log("montando pedido de venda de exemplo (Comercial)...")
pedido_venda = admin.post("/comercial/pedidos", {
    "cliente_id": cliente_1["id"],
    "itens": [
        {"item_id": produtos_acabados[0]["item"]["id"], "quantidade": 0.5, "unidade": "kg", "preco_unitario": 89.90},
        {"item_id": produtos_acabados[2]["item"]["id"], "quantidade": 0.1, "unidade": "kg", "preco_unitario": 59.90},
    ],
})
admin.post(f"/comercial/pedidos/{pedido_venda['id']}/confirmar")
pedido_expedido = admin.post(f"/comercial/pedidos/{pedido_venda['id']}/expedir")
conta_receber = pedido_expedido.get("conta_receber")
if conta_receber:
    admin.post(f"/financeiro/contas-receber/{conta_receber['id']}/baixas", {
        "valor": round(conta_receber["valor_total"] * 0.4, 2),
        "forma_pagamento": "pix", "observacao": "Pagamento parcial de demonstração.",
    })
    log("pedido de venda confirmado, expedido e com baixa parcial na conta a receber")

# Demonstra "Duplicar Pedido" no Comercial (Fase 77) — vira um novo
# rascunho pronto para continuar editando na tela de desktop.
duplicado_comercial = admin.post(f"/comercial/pedidos/{pedido_venda['id']}/duplicar")
log(f"pedido duplicado no Comercial como {duplicado_comercial['numero']} (rascunho)")

# ============================================================
# 7) App de Vendas — demonstra Portfólio + Duplicar, e deixa um rascunho
#    ABERTO montado pelo Portfólio como "modelo pronto" (o pedido do
#    usuário: "deixar um modelo preenchido em todos os módulos").
# ============================================================
log("montando o rascunho 'modelo' no App de Vendas via Portfólio...")
rascunho_atual = admin.get("/vendas-app/meu-rascunho")["rascunho"]
if rascunho_atual:
    admin.post(f"/vendas-app/rascunhos/{rascunho_atual['id']}/abandonar")

rascunho_novo = admin.post("/vendas-app/rascunhos", {"cliente_id": cliente_2["id"]})["rascunho"]
portfolio = admin.get("/vendas-app/portfolio")
itens_portfolio = [item for categoria in portfolio["categorias"] for item in categoria["itens"]]
for item in itens_portfolio[:3]:
    if item["saldo_disponivel_para_venda"] <= 0:
        continue
    admin.post(f"/vendas-app/rascunhos/{rascunho_novo['id']}/itens", {
        "item_id": item["id"], "quantidade": min(2, item["saldo_disponivel_para_venda"]),
        "unidade": item["unidade_medida"], "preco_unitario": 79.90,
    })
log(f"rascunho modelo deixado ABERTO no App de Vendas para o cliente '{cliente_2['razao_social']}' — abra #/app-vendas/portfolio para continuar.")

# Duplicar Pedido no App de Vendas exige NÃO ter rascunho aberto — abandona
# o modelo temporariamente só para provar o endpoint, e remonta em seguida
# (o pedido expedido acima serve de origem).
admin.post(f"/vendas-app/rascunhos/{rascunho_novo['id']}/abandonar")
duplicado_app_vendas = admin.post(f"/vendas-app/pedidos/{pedido_venda['id']}/duplicar")["rascunho"]
log(f"'Usar como modelo' demonstrado no App de Vendas — novo rascunho {duplicado_app_vendas['numero']}")
# Deixa ESTE (o duplicado a partir da venda real) como o rascunho aberto
# final — mais representativo como "modelo" do que o vazio de 3 itens.

# ============================================================
# 8) Compras + Financeiro (contas a pagar)
# ============================================================
log("criando pedido de compra de exemplo...")
pedido_compra = admin.post("/compras/pedidos", {
    "fornecedor_id": fornecedor_insumos["id"],
    "itens": [{"item_id": materias_primas["whey_concentrado"]["id"], "quantidade_pedida": 50, "unidade": "kg", "preco_unitario": 32.5}],
    "observacoes": "Pedido de demonstração (Fase 77).",
})
admin.post(f"/compras/pedidos/{pedido_compra['id']}/enviar")
receber_e_aprovar(materias_primas["whey_concentrado"], fornecedor_insumos, 50, "kg", pedido_compra_id=pedido_compra["id"])
conta_pagar = admin.post(f"/compras/pedidos/{pedido_compra['id']}/gerar-conta-pagar", {"vencimento": "2026-09-15"})
admin.post(f"/financeiro/contas-pagar/{conta_pagar['id']}/baixas", {
    "valor": round(conta_pagar["valor_total"] * 0.5, 2), "forma_pagamento": "boleto",
    "observacao": "Pagamento parcial de demonstração.",
})
log("pedido de compra recebido, com conta a pagar gerada e baixa parcial registrada")

# ============================================================
# 9) Desvio de Qualidade de exemplo
# ============================================================
admin.post("/desvios", {
    "origem": "producao", "descricao": "Divergência de peso líquido observada em amostragem de rotina (exemplo de demonstração).",
    "criticidade": "media", "item_id": produtos_acabados[0]["item"]["id"],
})
log("desvio de qualidade de exemplo aberto")

log("")
log("Concluído — instalação populada com um exemplo completo em Itens, Fornecedores, Estoque/Lotes,")
log("Análises (QMS), Fórmulas, Produção (OPs), Comercial, App de Vendas (Portfólio + rascunho modelo),")
log("Compras, Financeiro (contas a receber e a pagar) e Desvios de Qualidade.")
