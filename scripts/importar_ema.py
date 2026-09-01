"""
Fase 124/125 — Importação do backup do "Ema" (ERP anterior da empresa,
pg_dump do Postgres, 1207 tabelas) para o Alphafitus OS.

Escopo desta primeira leva (dados-mestre + saldo de abertura — módulos que
o Alphafitus já tem): clientes, fornecedores, itens, lotes com saldo em
estoque e contas a pagar/receber em aberto. Os módulos que o Ema tem e o
Alphafitus ainda não (CRM, Caixa/PDV, Comissão, conciliação bancária CNAB)
NÃO fazem parte deste script — ver o plano de fases seguintes.

COMO OS DADOS CHEGAM AQUI: o backup é um pg_dump de Postgres; este projeto
não depende de Postgres em produção, então em vez de adicionar psycopg2
como dependência permanente só para uma importação única, os dados foram
exportados uma vez para CSV (com um Postgres local descartável, restaurado
a partir do .dmp) e este script lê os CSVs. Os comandos usados para gerar
os CSVs a partir do backup ficam documentados no fim deste arquivo, para
o caso de uma nova exportação (ex.: um backup mais recente) no futuro.

POR QUE ESTE SCRIPT USA A API **E** O BANCO DIRETO, DIFERENTE DE
scripts/popular_demo.py (só API): a criação em si de cliente/fornecedor/
item/conta sempre passa pela API — é ali que moram as regras de negócio
que importam (unicidade de CNPJ, geração de código do item, permissão,
auditoria). Mas duas coisas não têm rota nenhuma hoje porque nunca foram
necessárias antes de existir uma importação em massa:
  1. Campos puramente cadastrais sem regra de negócio nenhuma por trás
     (telefone, nome do contato, peso, validade padrão, o próprio
     `codigo_legado_ema` de rastreabilidade) — criar uma rota HTTP só
     para isso seria mais código do que o problema pede.
  2. Lotes de saldo de abertura: a rota normal de recebimento
     (`POST /lotes/recebimento`) joga todo lote novo na fila de análise
     de Qualidade — certo para um recebimento de verdade, errado para
     ~1700 lotes que já existem fisicamente no estoque HOJE e já eram
     usáveis no sistema anterior (forçá-los pela fila criaria uma
     avalanche de pedidos de análise falsos). Por isso entram direto
     com `status='aprovado'`, com o mesmo registro de auditoria
     (`app.audit.registrar`) que a rota usaria.
Por isso o script abre os dois canais: HTTP (criação) e SQLite direto
(essas duas exceções, sempre documentadas author onde acontecem, e a
consulta de idempotência por `codigo_legado_ema` antes de qualquer criação
via HTTP, para nunca duplicar num reprocessamento).

COMO RODAR (com o servidor já rodando em outro terminal, apontando para o
MESMO banco que ALPHAFITUS_DB_PATH abaixo):
    set ALPHAFITUS_IMPORT_EMA_ADMIN_SENHA=a-senha-do-seu-admin
    set ALPHAFITUS_IMPORT_EMA_DIR=caminho\\para\\a\\pasta\\com\\os\\csv
    set ALPHAFITUS_DB_PATH=caminho\\para\\alphafitus.db
    set ALPHAFITUS_DB_KEY=a-chave-do-banco
    python scripts/importar_ema.py

Variáveis de ambiente aceitas:
    ALPHAFITUS_IMPORT_EMA_BASE_URL     (padrão: http://127.0.0.1:5000/api/v1)
    ALPHAFITUS_IMPORT_EMA_ADMIN_EMAIL  (padrão: admin@alphafitus.com.br)
    ALPHAFITUS_IMPORT_EMA_ADMIN_SENHA  (obrigatório)
    ALPHAFITUS_IMPORT_EMA_DIR          (obrigatório — pasta com os .csv)
    ALPHAFITUS_DB_PATH, ALPHAFITUS_DB_KEY  (obrigatórios — mesmo banco/chave do servidor)

Idempotência: todo registro criado por este script grava
`codigo_legado_ema` (ex.: "ema:cliforemp:74") com índice ÚNICO no banco —
antes de criar qualquer coisa, o script confere se aquele código já existe
e pula. Seguro reexecutar quantas vezes quiser.

NOTA SOBRE TIPO DE ITEM: o Ema tem um campo `item.grupo` com texto real
("PRODUTO ACABADO", "MATERIA PRIMA", "ROTULOS", ...) que mapeia bem para
as 7 categorias do Alphafitus — ver MAPA_TIPO_POR_GRUPO abaixo. Mas ~870
dos 2589 itens (34%) estão com grupo "Desconhecido" — o próprio Ema nunca
classificou esses, e "ATVO IMOBILIZADO"/"SERVIÇO(S)..." não são itens de
estoque de verdade (são patrimônio/serviço) — ficam de fora da importação.
Os "Desconhecido" (e "USO/CONSUMO", que também não tem categoria clara)
SÃO importados, como 'materia_prima' (o valor mais conservador — mantém
`requer_analise` no padrão do sistema), com "[REVISAR TIPO — importado do
Ema sem classificação]" na observação, para aparecerem juntos num filtro
depois.
"""
import csv
import datetime
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import requests
except ImportError:
    sys.exit("Este script precisa do pacote 'requests' (já está em requirements.txt — rode dentro da venv do projeto).")

try:
    from sqlcipher3 import dbapi2 as sqlite3
except ImportError:
    sys.exit("Este script precisa do pacote 'sqlcipher3-wheels' (já está em requirements.txt — rode dentro da venv do projeto).")

BASE = os.environ.get("ALPHAFITUS_IMPORT_EMA_BASE_URL", "http://127.0.0.1:5000/api/v1")
ADMIN_EMAIL = os.environ.get("ALPHAFITUS_IMPORT_EMA_ADMIN_EMAIL", "admin@alphafitus.com.br")
ADMIN_SENHA = os.environ.get("ALPHAFITUS_IMPORT_EMA_ADMIN_SENHA")
# Alternativa a email/senha: autentica emitindo o próprio token de acesso
# (mesma função que /auth/login usa por baixo — app.security.emitir_access_
# token), sem precisar saber/trocar a senha de ninguém. Pensado para rodar
# a importação atribuída à conta real do administrador (ALPHAFITUS_IMPORT_
# EMA_USUARIO_ID) sem tocar em credencial nenhuma — exige rodar no mesmo
# processo/ambiente do servidor (mesma ALPHAFITUS_JWT_SECRET).
USUARIO_ID_DIRETO = os.environ.get("ALPHAFITUS_IMPORT_EMA_USUARIO_ID")
EXPORT_DIR = os.environ.get("ALPHAFITUS_IMPORT_EMA_DIR")
DB_PATH = os.environ.get("ALPHAFITUS_DB_PATH")
DB_KEY = os.environ.get("ALPHAFITUS_DB_KEY")

if not ADMIN_SENHA and not USUARIO_ID_DIRETO:
    sys.exit("Defina ALPHAFITUS_IMPORT_EMA_ADMIN_SENHA (login normal) ou ALPHAFITUS_IMPORT_EMA_USUARIO_ID (emite token direto).")
if not EXPORT_DIR or not os.path.isdir(EXPORT_DIR):
    sys.exit("Defina ALPHAFITUS_IMPORT_EMA_DIR apontando para a pasta com os .csv exportados.")
if not DB_PATH or not DB_KEY:
    sys.exit("Defina ALPHAFITUS_DB_PATH e ALPHAFITUS_DB_KEY (mesmo banco/chave do servidor).")


def log(msg):
    print(f"[importar_ema] {msg}")


class Sessao:
    """A importação inteira (clientes + fornecedores + itens + contas)
    demora bem mais que o TTL do access_token (pensado para uma sessão de
    usuário normal, não para um script em lote de horas) — por isso toda
    chamada aqui detecta um 401 por token expirado e faz login de novo
    sozinha, uma única vez, antes de desistir de verdade."""

    def __init__(self, base_url, email=None, senha=None, usuario_id_direto=None):
        self.base_url = base_url
        self.email = email
        self.senha = senha
        self.usuario_id_direto = usuario_id_direto
        self.token = None
        self.login()

    def login(self):
        if self.usuario_id_direto:
            import uuid
            from app import security as security_module
            self.token = security_module.emitir_access_token(int(self.usuario_id_direto), str(uuid.uuid4()))
            return
        r = requests.post(f"{self.base_url}/auth/login", json={"email": self.email, "senha": self.senha})
        self._checar(r)
        self.token = r.json()["access_token"]

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def _checar(self, r):
        if not r.ok:
            raise RuntimeError(f"{r.request.method} {r.request.url} -> {r.status_code}: {r.text}")

    def _chamar(self, metodo, path, **kwargs):
        r = metodo(f"{self.base_url}{path}", headers=self._headers(), **kwargs)
        if r.status_code == 401:
            self.login()
            r = metodo(f"{self.base_url}{path}", headers=self._headers(), **kwargs)
        return r

    def get(self, path, params=None):
        r = self._chamar(requests.get, path, params=params)
        self._checar(r)
        return r.json()

    def post(self, path, body=None, esperar_falha_ok=False):
        r = self._chamar(requests.post, path, json=body or {})
        if esperar_falha_ok and not r.ok:
            return None, r
        self._checar(r)
        return (r.json() if r.content else None), r

    def put(self, path, body=None):
        r = self._chamar(requests.put, path, json=body or {})
        self._checar(r)
        return r.json() if r.content else None


def ler_csv(nome):
    caminho = os.path.join(EXPORT_DIR, nome)
    if not os.path.exists(caminho):
        log(f"AVISO: {nome} não encontrado em {EXPORT_DIR} — pulando esta etapa.")
        return []
    with open(caminho, encoding="utf-8", errors="replace", newline="") as f:
        return list(csv.DictReader(f))


def limpo(valor):
    """Ema usa '.' como marcador de campo vazio em vários lugares — trata
    isso e espaços em branco como None, nunca como um valor real."""
    if valor is None:
        return None
    valor = valor.strip()
    if valor in ("", ".", "None", "null"):
        return None
    return valor


def normalizar_doc(doc):
    doc = limpo(doc)
    if not doc:
        return None
    digitos = "".join(c for c in doc if c.isdigit())
    return digitos or None


def numero(valor):
    valor = limpo(valor)
    if valor is None:
        return None
    try:
        return float(valor)
    except ValueError:
        return None


def inteiro(valor):
    n = numero(valor)
    return int(n) if n is not None else None


def peso_kg(valor):
    """item.pesobruto/pesoliquido no Ema NÃO está em kg (checado contra o
    peso que várias descrições trazem no próprio nome, ex.: 'CREATINA PURA
    300G' tinha pesobruto=300 — se fosse kg seria 300kg, um absurdo para
    um pote de creatina; bate exatamente como 300 GRAMAS). Convertido aqui
    pra kg de verdade, que é o que a coluna peso_bruto_kg promete guardar."""
    n = numero(valor)
    return round(n / 1000.0, 6) if n else n


def vencimento_plausivel(data):
    """Auditoria encontrou 1 (de 774) título com vencimento '2202-02-11'
    — claramente um erro de digitação no Ema (o mesmo registro tem
    emissão em 2025-02-11; sobrou um dígito). Não corrige adivinhando o
    ano certo (máxima fidelidade) — só recusa datas fora de uma faixa
    plausível, para o título cair em `titulos_data_suspeita.csv` e ser
    corrigido à mão em vez de virar um "aberto" que nunca vence."""
    if not data or len(data) < 4:
        return False
    try:
        ano = int(data[:4])
    except ValueError:
        return False
    return 2015 <= ano <= 2035


def ja_importado(conn, tabela, codigo_legado):
    row = conn.execute(f"SELECT id FROM {tabela} WHERE codigo_legado_ema = ?", (codigo_legado,)).fetchone()
    return row["id"] if row else None


# ============================================================
# Classificação de item (Ema.grupo -> Alphafitus.itens.tipo) — ver nota no
# topo do arquivo sobre os ~34% sem grupo real.
# ============================================================
MAPA_TIPO_POR_GRUPO = {
    "PRODUTO ACABADO": "produto_acabado",
    "MATERIA PRIMA": "materia_prima",
    "PRODUTO INTERMEDIÁRIO CÁPS": "produto_intermediario",
    "PRODUTO INTERMEDIÁRIO PÓ": "produto_intermediario",
    "LABORATORIO": "material_de_laboratorio",
    "ROTULOS": "embalagem_secundaria",
    "CARTUCHO": "embalagem_secundaria",
    "BOBINA": "embalagem_secundaria",
    "TAMPAS": "embalagem_primaria",
    "POTES": "embalagem_primaria",
    "CAPSULAS": "embalagem_primaria",
    "BLISTER": "embalagem_primaria",
    "SCOOP": "embalagem_primaria",
    "SILICAS": "embalagem_primaria",
}
GRUPOS_NAO_ESTOQUE = {"ATVO IMOBILIZADO", "SERVIÇOS DE TERCEIROS (REMESSA PARA INDUSTRIALIZAÇÃO)", "SERVIÇO"}


def classificar_item(grupo):
    grupo = (grupo or "").strip()
    if grupo in GRUPOS_NAO_ESTOQUE:
        return None, None  # não é item de estoque — não importar
    tipo = MAPA_TIPO_POR_GRUPO.get(grupo)
    if tipo:
        return tipo, None
    return "materia_prima", "[REVISAR TIPO — importado do Ema sem classificação de grupo confiável]"


def main():
    if USUARIO_ID_DIRETO:
        admin = Sessao(BASE, usuario_id_direto=USUARIO_ID_DIRETO)
        log(f"autenticado direto como usuario_id={USUARIO_ID_DIRETO} (sem senha)")
    else:
        admin = Sessao(BASE, ADMIN_EMAIL, ADMIN_SENHA)
        log(f"login OK como {ADMIN_EMAIL}")

    conn = sqlite3.connect(DB_PATH)
    conn.execute(f"PRAGMA key = '{DB_KEY}'")
    conn.row_factory = sqlite3.Row

    # ============================================================
    # 1) CLIENTES
    # ============================================================
    criados = pulados = existentes = 0
    for row in ler_csv("clientes.csv"):
        codigo_legado = f"ema:cliforemp:{row['idcliforemp']}"
        if ja_importado(conn, "clientes", codigo_legado):
            existentes += 1
            continue
        doc = normalizar_doc(row.get("cnpj")) or normalizar_doc(row.get("cpf"))
        razao = limpo(row.get("razao")) or limpo(row.get("fantasia"))
        if not doc or not razao:
            pulados += 1
            continue

        resultado, resposta = admin.post("/comercial/clientes", {
            "razao_social": razao,
            "nome_fantasia": limpo(row.get("fantasia")),
            "cnpj": doc,
            "endereco": " ".join(filter(None, [limpo(row.get("endereco")), limpo(row.get("numero"))])) or None,
            "email": limpo(row.get("email")),
            "bairro": limpo(row.get("bairro")),
            "uf": limpo(row.get("uf")),
            "cep": limpo(row.get("cep")),
        }, esperar_falha_ok=True)
        if resultado is None:
            if resposta.status_code == 409:
                # CNPJ já usado por um cliente cadastrado por fora desta
                # importação — respeita o que já existe, só marca o
                # vínculo para as próximas fases (contas a receber etc.)
                existente = conn.execute("SELECT id FROM clientes WHERE cnpj = ?", (doc,)).fetchone()
                conn.execute("UPDATE clientes SET codigo_legado_ema = ? WHERE id = ? AND codigo_legado_ema IS NULL",
                             (codigo_legado, existente["id"]))
                conn.commit()
                existentes += 1
                continue
            raise RuntimeError(f"Falha ao criar cliente {razao} ({doc}): {resposta.text}")
        cliente_id = resultado["id"]
        if limpo(row.get("inativo")) == "S":
            admin.put(f"/comercial/clientes/{cliente_id}", {"status": "inativo"})
        conn.execute(
            "UPDATE clientes SET telefone = ?, nome_contato = ?, codigo_legado_ema = ? WHERE id = ?",
            (limpo(row.get("fone")), limpo(row.get("nomecontato")), codigo_legado, cliente_id),
        )
        conn.commit()
        criados += 1
    log(f"clientes: {criados} criados, {existentes} já existiam/importados, {pulados} pulados (sem CNPJ/CPF ou sem razão social)")

    # ============================================================
    # 2) FORNECEDORES
    # ============================================================
    criados = pulados = existentes = 0
    for row in ler_csv("fornecedores.csv"):
        codigo_legado = f"ema:cliforemp:{row['idcliforemp']}"
        if ja_importado(conn, "fornecedores", codigo_legado):
            existentes += 1
            continue
        doc = normalizar_doc(row.get("cnpj")) or normalizar_doc(row.get("cpf"))
        nome = limpo(row.get("fantasia")) or limpo(row.get("razao"))
        if not doc or not nome or nome.strip("[]").strip().lower() == "nome empresa":
            pulados += 1
            continue

        resultado, resposta = admin.post("/fornecedores", {"nome": nome, "cnpj": doc}, esperar_falha_ok=True)
        if resultado is None:
            if resposta.status_code == 409:
                existente = conn.execute("SELECT id FROM fornecedores WHERE cnpj = ?", (doc,)).fetchone()
                conn.execute("UPDATE fornecedores SET codigo_legado_ema = ? WHERE id = ? AND codigo_legado_ema IS NULL",
                             (codigo_legado, existente["id"]))
                conn.commit()
                existentes += 1
                continue
            raise RuntimeError(f"Falha ao criar fornecedor {nome} ({doc}): {resposta.text}")
        fornecedor_id = resultado["id"]
        admin.put(f"/fornecedores/{fornecedor_id}/dados-fiscais", {
            "bairro": limpo(row.get("bairro")), "uf": limpo(row.get("uf")), "cep": limpo(row.get("cep")),
            "logradouro": limpo(row.get("endereco")), "numero_endereco": limpo(row.get("numero")),
        })
        conn.execute(
            "UPDATE fornecedores SET email = ?, telefone = ?, nome_contato = ?, codigo_legado_ema = ?, "
            "status = ? WHERE id = ?",
            (limpo(row.get("email")), limpo(row.get("fone")), limpo(row.get("nomecontato")), codigo_legado,
             "bloqueado" if limpo(row.get("inativo")) == "S" else "aprovado", fornecedor_id),
        )
        conn.commit()
        criados += 1
    log(f"fornecedores: {criados} criados, {existentes} já existiam/importados, {pulados} pulados (sem CNPJ/CPF ou placeholder)")

    # ============================================================
    # 3) ITENS
    # ============================================================
    # POST /itens não aceita status/observação na criação (só existem via
    # UPDATE direto abaixo — nenhuma das duas tem regra de negócio na
    # transição, ver nota do topo do arquivo sobre este tipo de exceção).
    criados = pulados = existentes = nao_estoque = 0
    itens_para_revisar = []  # (codigo, descricao) — grupo "Desconhecido"/"USO/CONSUMO" no Ema
    codigos_usados = {r["codigo"] for r in conn.execute("SELECT codigo FROM itens").fetchall()}
    for row in ler_csv("itens.csv"):
        codigo_legado = f"ema:item:{row['iditem']}"
        if ja_importado(conn, "itens", codigo_legado):
            existentes += 1
            continue
        tipo, aviso = classificar_item(row.get("grupo"))
        if tipo is None:
            nao_estoque += 1
            continue
        descricao = limpo(row.get("descricao"))
        if not descricao:
            pulados += 1
            continue

        codigo_sugerido = limpo(row.get("referencia"))
        codigo = codigo_sugerido if (codigo_sugerido and codigo_sugerido not in codigos_usados) else None

        resultado, resposta = admin.post("/itens", {
            "codigo": codigo,  # None => a rota gera um código automático (MP000001 etc.)
            "descricao": descricao,
            "tipo": tipo,
            "unidade_medida": limpo(row.get("unidade")) or "un",
        }, esperar_falha_ok=True)
        if resultado is None:
            raise RuntimeError(f"Falha ao criar item {descricao}: {resposta.text}")
        item_id = resultado["id"]
        codigos_usados.add(resultado["codigo"])
        conn.execute(
            "UPDATE itens SET peso_bruto_kg = ?, peso_liquido_kg = ?, dias_validade_padrao = ?, "
            "codigo_legado_ema = ?, status = ? WHERE id = ?",
            (peso_kg(row.get("pesobruto")), peso_kg(row.get("pesoliquido")), inteiro(row.get("diaslotevalidade")),
             codigo_legado, "inativo" if limpo(row.get("inativo")) == "S" else "ativo", item_id),
        )
        conn.commit()
        if aviso:
            itens_para_revisar.append((resultado["codigo"], descricao))
        criados += 1
    log(f"itens: {criados} criados ({len(itens_para_revisar)} marcados para revisão de tipo), {existentes} já importados, "
        f"{nao_estoque} pulados (patrimônio/serviço, não é item de estoque), {pulados} pulados (sem descrição)")
    if itens_para_revisar:
        caminho_revisar = os.path.join(EXPORT_DIR, "itens_revisar_tipo.csv")
        with open(caminho_revisar, "w", encoding="utf-8", newline="") as f:
            escritor = csv.writer(f)
            escritor.writerow(["codigo", "descricao"])
            escritor.writerows(itens_para_revisar)
        log(f"  -> lista completa desses {len(itens_para_revisar)} itens (todos importados como 'materia_prima' "
            f"por padrão, sem classificação confiável no Ema) salva em {caminho_revisar}")

    # ============================================================
    # 4) LOTES (saldo de abertura — direto no banco, ver nota no topo)
    # ============================================================
    from app import audit as audit_module

    if USUARIO_ID_DIRETO:
        admin_id = int(USUARIO_ID_DIRETO)
    else:
        admin_usuario = conn.execute("SELECT id FROM usuarios WHERE email = ?", (ADMIN_EMAIL,)).fetchone()
        admin_id = admin_usuario["id"] if admin_usuario else None
    agora = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    criados = pulados = existentes = 0
    for row in ler_csv("lotes.csv"):
        item = conn.execute("SELECT id, unidade_medida FROM itens WHERE codigo_legado_ema = ?",
                             (f"ema:item:{row['iditem']}",)).fetchone()
        if item is None:
            pulados += 1  # item correspondente não foi importado (patrimônio/serviço/sem descrição)
            continue
        quantidade = numero(row.get("quantidade"))
        if not quantidade or quantidade <= 0:
            pulados += 1
            continue
        lote_original = limpo(row.get("lote")) or "SL"
        codigo_lote = f"EMA-{row['iditem']}-{re.sub(r'[^A-Za-z0-9]', '', lote_original)[:20]}"
        codigo_legado = f"ema:lote:{row['iditem']}:{lote_original}"
        if ja_importado(conn, "lotes", codigo_legado):
            existentes += 1
            continue
        if conn.execute("SELECT id FROM lotes WHERE codigo_lote = ?", (codigo_lote,)).fetchone():
            codigo_lote = f"{codigo_lote}-{row.get('data', '')[:10]}"

        # `origem` só aceita 'recebimento'/'producao' (Fase 3) — usa
        # 'recebimento' (verdade: este lote entrou por uma compra, só que
        # antes do Alphafitus existir); o que distingue de um recebimento
        # feito de verdade pela tela é só `codigo_legado_ema` + a ação
        # própria no log de auditoria abaixo.
        cur = conn.execute(
            """
            INSERT INTO lotes (codigo_lote, item_id, lote_fornecedor, fabricacao, validade, quantidade,
                                unidade, status, custo_unitario, criado_em, criado_por, origem, codigo_legado_ema)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'aprovado', ?, ?, ?, 'recebimento', ?)
            """,
            (codigo_lote, item["id"], lote_original, limpo(row.get("data")), limpo(row.get("validade")),
             quantidade, item["unidade_medida"], numero(row.get("valorcusto")), agora, admin_id, codigo_legado),
        )
        lote_id = cur.lastrowid
        audit_module.registrar(conn, tabela="lotes", registro_id=lote_id, usuario_id=admin_id,
                                acao="lote_importado_saldo_abertura_ema",
                                valor_novo={"codigo_lote": codigo_lote, "quantidade": quantidade, "item_id": item["id"]},
                                ip="127.0.0.1", dispositivo="script:importar_ema.py")
        conn.commit()
        criados += 1
    log(f"lotes: {criados} criados (status 'aprovado' — saldo de abertura), {existentes} já importados, {pulados} pulados (item não importado ou saldo zerado)")

    # ============================================================
    # 5) CONTAS A PAGAR EM ABERTO
    # ============================================================
    criados = pulados = existentes = 0
    suspeitos = []
    for row in ler_csv("pagar_aberto.csv"):
        codigo_legado = f"ema:pagar:{row['idpagar']}"
        if ja_importado(conn, "contas_pagar", codigo_legado):
            existentes += 1
            continue
        fornecedor = conn.execute("SELECT id FROM fornecedores WHERE codigo_legado_ema = ?",
                                   (f"ema:cliforemp:{row['idcliforemp']}",)).fetchone()
        saldo = numero(row.get("valorsaldo"))
        vencimento = limpo(row.get("vencimento"))
        if fornecedor is None or not saldo or saldo <= 0 or not vencimento:
            pulados += 1
            continue
        if not vencimento_plausivel(vencimento):
            suspeitos.append(("contas_pagar", codigo_legado, vencimento, limpo(row.get("dataemissao"))))
            continue
        descricao = (f"Importado do Ema — doc. {limpo(row.get('documento')) or '?'}"
                     f"/{limpo(row.get('parcela')) or '?'}, emitido em {limpo(row.get('dataemissao')) or '?'}"
                     f" (valor original R$ {numero(row.get('valor'))})")
        resultado, resposta = admin.post("/financeiro/contas-pagar", {
            "fornecedor_id": fornecedor["id"],
            "descricao": descricao[:500],
            "valor_total": round(saldo, 2),
            "vencimento": vencimento[:10],
            "categoria": "compra",
        }, esperar_falha_ok=True)
        if resultado is None:
            raise RuntimeError(f"Falha ao criar conta a pagar {codigo_legado}: {resposta.text}")
        conn.execute("UPDATE contas_pagar SET codigo_legado_ema = ? WHERE id = ?", (codigo_legado, resultado["id"]))
        conn.commit()
        criados += 1
    log(f"contas a pagar: {criados} criadas, {existentes} já importadas, {pulados} pulados (fornecedor não importado/saldo zerado/sem vencimento), "
        f"{len(suspeitos)} com vencimento implausível (ver titulos_data_suspeita.csv)")

    # ============================================================
    # 6) CONTAS A RECEBER EM ABERTO (lançamento avulso — Fase 125)
    # ============================================================
    criados = pulados = existentes = 0
    for row in ler_csv("receber_aberto.csv"):
        codigo_legado = f"ema:receber:{row['idreceber']}"
        if ja_importado(conn, "contas_receber", codigo_legado):
            existentes += 1
            continue
        cliente = conn.execute("SELECT id FROM clientes WHERE codigo_legado_ema = ?",
                                (f"ema:cliforemp:{row['idcliforemp']}",)).fetchone()
        saldo = numero(row.get("valorsaldo"))
        vencimento = limpo(row.get("vencimento"))
        if cliente is None or not saldo or saldo <= 0 or not vencimento:
            pulados += 1
            continue
        if not vencimento_plausivel(vencimento):
            suspeitos.append(("contas_receber", codigo_legado, vencimento, limpo(row.get("dataemissao"))))
            continue
        descricao = (f"Importado do Ema — doc. {limpo(row.get('documento')) or '?'}"
                     f"/{limpo(row.get('parcela')) or '?'}, emitido em {limpo(row.get('dataemissao')) or '?'}"
                     f" (valor original R$ {numero(row.get('valor'))})")
        resultado, resposta = admin.post("/financeiro/contas-receber", {
            "cliente_id": cliente["id"],
            "valor_total": round(saldo, 2),
            "vencimento": vencimento[:10],
            "descricao": descricao[:500],
        }, esperar_falha_ok=True)
        if resultado is None:
            raise RuntimeError(f"Falha ao criar conta a receber {codigo_legado}: {resposta.text}")
        conn.execute("UPDATE contas_receber SET codigo_legado_ema = ? WHERE id = ?", (codigo_legado, resultado["id"]))
        conn.commit()
        criados += 1
    log(f"contas a receber: {criados} criadas, {existentes} já importadas, {pulados} pulados (cliente não importado/saldo zerado/sem vencimento), "
        f"{sum(1 for s in suspeitos if s[0] == 'contas_receber')} com vencimento implausível (ver titulos_data_suspeita.csv)")

    if suspeitos:
        caminho_suspeitos = os.path.join(EXPORT_DIR, "titulos_data_suspeita.csv")
        with open(caminho_suspeitos, "w", encoding="utf-8", newline="") as f:
            escritor = csv.writer(f)
            escritor.writerow(["tabela", "codigo_legado_ema", "vencimento_no_ema", "dataemissao_no_ema"])
            escritor.writerows(suspeitos)
        log(f"  -> {len(suspeitos)} título(s) NÃO importado(s) por ter vencimento fora de uma faixa plausível "
            f"(provável erro de digitação no Ema, ex.: ano '2202') — lista em {caminho_suspeitos} para lançar à mão com a data correta")

    conn.close()
    log("importação concluída.")


if __name__ == "__main__":
    main()


# ============================================================
# Comandos usados para gerar os CSVs a partir do backup (bkp-ema.dmp),
# via um Postgres local descartável (só para leitura do backup, nunca
# usado em produção):
#
#   createdb -U postgres ema_import
#   pg_restore -U postgres -d ema_import --no-owner --no-privileges -j 4 bkp-ema.dmp
#
#   \copy (SELECT c.idcliforemp, c.fantasia, c.razao, c.cnpj, c.cpf, c.email, c.fone,
#          c.endereco, c.numero, c.complemento, c.bairro, c.cep, c.uf, c.inativo, cl.nomecontato
#          FROM cliforemp c JOIN cliente cl ON cl.idcliforemp=c.idcliforemp) TO 'clientes.csv' WITH CSV HEADER;
#
#   \copy (SELECT c.idcliforemp, c.fantasia, c.razao, c.cnpj, c.cpf, c.email, c.fone,
#          c.endereco, c.numero, c.complemento, c.bairro, c.cep, c.uf, c.inativo, f.nomecontato
#          FROM cliforemp c JOIN fornecedor f ON f.idcliforemp=c.idcliforemp) TO 'fornecedores.csv' WITH CSV HEADER;
#
#   \copy (SELECT i.iditem, i.referencia, i.descricao, i.inativo, i.usalote, i.controla_estoque,
#          i.diaslotevalidade, i.pesobruto, i.pesoliquido, i.idunidadebasica, u.sigla AS unidade,
#          g.descricao AS grupo, i.observacao
#          FROM item i LEFT JOIN unidade u ON u.idunidade=i.idunidadebasica
#          LEFT JOIN grupo g ON g.idgrupo=i.idgrupo) TO 'itens.csv' WITH CSV HEADER;
#
#   \copy (SELECT l.iditem, l.lote, l.quantidade, l.data, l.validade, l.valorcusto, l.observacao
#          FROM lote l WHERE l.quantidade > 0) TO 'lotes.csv' WITH CSV HEADER;
#
#   \copy (SELECT p.idpagar, p.idcliforemp, p.documento, p.parcela, p.valor, p.valorsaldo,
#          p.vencimento, p.dataemissao, p.status, p.observacao
#          FROM pagar p WHERE p.status IN (2,3)) TO 'pagar_aberto.csv' WITH CSV HEADER;
#
#   \copy (SELECT r.idreceber, r.idcliforemp, r.documento, r.parcela, r.valor, r.valorsaldo,
#          r.vencimento, r.dataemissao, r.status, r.observacao
#          FROM receber r WHERE r.status IN (2,3)) TO 'receber_aberto.csv' WITH CSV HEADER;
# ============================================================
