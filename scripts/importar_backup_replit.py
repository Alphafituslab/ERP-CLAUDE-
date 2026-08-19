"""
Importa um backup JSON exportado do sistema antigo (Node.js/React/Postgres,
hospedado no Replit) — "Memorial Técnico ANVISA" — para dentro de um banco
Alphafitus OS já inicializado (schema + seed já aplicados).

Uso:

    python scripts/importar_backup_replit.py \
        --backup /caminho/para/Memorial-backup-alphafitus-AAAA-MM-DD_HHhMM.json \
        --db data/alphafitus.db

O banco de destino PRECISA já ter passado por `init_db()` (schema) e por
`seed.py` (permissões, perfis padrão e o usuário administrador) antes de
rodar este script — ele não cria schema nem seed, só importa dados.

O QUE ESTE SCRIPT IMPORTA (mapeado para as tabelas já existentes no
Alphafitus OS, Fase 1 a 27):
    - 1 `memorial_empresas`  (a empresa/marca do backup)
    - N `memorial_produtos` (todos os produtos, ligados à empresa acima)
    - N `memoriais`          (todos os memoriais, com os 35 campos de
      conteúdo técnico — objetivo, composição nutricional, alegações etc.)
    - N `memorial_assinaturas` (todas as assinaturas já registradas)
    - N `memorial_historico`   (o histórico narrativo completo de cada
      memorial, com timestamp original preservado)
    - N `memorial_anexos`      (os arquivos anexados, com o conteúdo em si,
      não só o nome)
    - N `memorial_padronizacoes` (as padronizações de rótulo já salvas)
    - ~660 itens de catálogo em `memorial_catalogo_itens`, nos 10
      catálogos que o Alphafitus OS já suporta (Fase 26): metodologias,
      nutrientes, legislações, alegações, tipos de produto, advertências,
      armazenamento, modo de uso, justificativas, referências.

SIMPLIFICAÇÕES DELIBERADAS (documentadas aqui e no relatório impresso ao
final da importação):
    1. O backup tem 4 catálogos a mais que o sistema original usava
       internamente (componentes, tabelas nutricionais alternativas, tipos
       de pote, opções de cápsula) que o Alphafitus OS ainda não tem como
       cadastro próprio (Fase 26 cobriu só os 10 que aparecem no menu
       "Catálogos"). Esses ~113 itens NÃO são importados — ficam
       registrados no relatório final, para entrar numa fase futura se o
       cliente pedir.
    2. Vários campos do memorial no sistema antigo eram tabelas dinâmicas
       (JSON, com o próprio usuário montando linhas/colunas pela UI):
       composição nutricional, composição centesimal, cálculo de
       quantidade, cálculos nutricionais por ingrediente, legislação
       aplicável, conclusão, metodologias aplicadas e referências
       bibliográficas. O Alphafitus OS guarda esses mesmos campos como
       texto livre (mais simples, sem um construtor de tabela dinâmica
       nesta fase) — este script converte cada uma dessas estruturas num
       texto formatado e legível (não é o dado bruto jogado como JSON na
       tela), mas a formatação exata (colunas, alinhamento) da tela antiga
       não é reproduzida. Ver as funções `formatar_*` abaixo.
    3. Os únicos 3 usuários que de fato assinaram algum memorial no backup
       (Clayton Borges da Silva, Edson Zaldguer, Caroline Batista) são
       criados como usuários de verdade no Alphafitus OS (perfil
       "Regulatório"), com senha temporária e troca obrigatória no
       primeiro login — sem eles não daria para satisfazer a integridade
       referencial de `memorial_assinaturas`. Um quarto usuário do backup
       (Tabata, perfil "visualizador", nunca assinou nada) é importado
       também, para manter a lista de usuários fiel ao backup, mas com
       login desativado por padrão (`status='inativo'`) já que não há
       e-mail dela no backup para gerar uma senha temporária de verdade —
       um administrador pode reativar e definir e-mail/senha depois, se
       for necessário.
    4. Nomes de histórico que não batem com nenhum dos 4 usuários acima
       (ex.: "Edson Cardoso", "Sistema") são preservados como texto em
       `usuario_nome`, sem vincular a nenhum usuário de verdade
       (`usuario_id` fica NULL) — o mesmo texto que aparecia no sistema
       antigo continua aparecendo na tela.

Este script é seguro de reexecutar contra o MESMO banco de destino: cada
entidade é importada checando antes se já existe algo com a mesma chave
natural (CNPJ da empresa, código do memorial, id original preservado nas
tabelas do Memorial Técnico) — se já existe, pula, não duplica.
"""
import argparse
import base64
import datetime
import json
import os
import secrets
import sqlite3
import string
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

from app import security  # noqa: E402

CAMPOS_MEMORIAL = (
    "objetivo", "composicao_nutricional", "lista_ingredientes", "alegacoes",
    "justificativas_tecnicas", "metodos_analiticos", "estabilidade_acelerada",
    "ensaios_microbiologicos", "calculos_nutricionais", "legislacao_aplicavel",
    "observacoes", "conclusao", "referencias_bibliograficas", "composicao_centesimal",
    "calculo_quantidade", "metodologias_aplicadas", "tipo_produto", "tipo_pote",
    "ingredientes_ativos", "excipientes", "composicao_capsula", "temperatura",
    "umidade_relativa", "periodo_estudo", "intervalos_teste", "advertencias",
    "armazenamento", "modo_uso", "elaborado_por", "aprovado_por", "laudo_emitido_por",
    "analista_senior", "email_rt", "email_analista_senior", "observacao_analista",
    "data_emissao",
)

CAMPOS_PRODUTO = (
    "ingredientes_ativos", "excipientes", "embalagem", "advertencias", "modo_de_uso",
    "armazenamento", "quantidade_capsulas_totais", "peso_liquido", "tamanho_capsulas",
    "tipo_capsulas", "tipo_produto", "referencias_comerciais", "comprimento_rotulo",
    "largura_rotulo", "tamanho_pote", "tamanho_capsula", "numero_protocolo_anvisa",
)

CAMPOS_PADRONIZACAO = (
    "produto", "peso_liquido", "contem", "denominacao_legal", "lista_ingredientes",
    "alergenicos", "advertencias", "conservacao", "informacoes_consumo",
    "largura_rotulo", "comprimento_rotulo", "altura_rotulo", "cor_capsula",
    "tamanho_capsulas", "tipo_capsulas", "tamanho_pote", "simbolos_logos",
    "alegacoes", "dados_distribuidor", "observacoes_tabela",
)

# catálogo do backup -> (catalogo no Alphafitus OS, mapa de campo backup -> campo interno)
CATALOGOS_MAPA = {
    "metodologias": ("metodologias", {
        "categoria": "categoria", "nome": "nome", "descricao": "descricao",
        "norma": "norma", "referencia": "referencia", "principio": "principio",
        "aplicacao": "aplicacao",
    }),
    "nutrientes": ("nutrientes", {
        "nome": "nome", "unidade": "unidade", "doseMinima": "dose_minima",
        "doseMaxima": "dose_maxima", "unidadeDose": "unidade_dose",
        "categoria": "categoria", "descricao": "descricao",
    }),
    "legislacoes": ("legislacoes", {
        "codigo": "codigo", "titulo": "titulo", "categoria": "categoria",
        "ano": "ano", "descricao": "descricao",
    }),
    "alegacoes": ("alegacoes", {
        "ativo": "ativo_nutricional", "alegacao": "alegacao",
        "referencia": "referencia", "categoria": "categoria",
    }),
    "tiposProduto": ("tipos_produto", {"nome": "nome", "temCapsula": "tem_capsula"}),
    "advertencias": ("advertencias", {"texto": "texto"}),
    "armazenamento": ("armazenamento", {"texto": "texto"}),
    "modoUso": ("modo_uso", {"descricao": "descricao", "tipo": "tipo"}),
    "justificativas": ("justificativas", {"titulo": "titulo", "texto": "texto"}),
    "referencias": ("referencias", {
        "substancia": "substancia", "referencia": "referencia", "descricao": "descricao",
        "tipo": "tipo", "autoIncluir": "auto_incluir",
    }),
}
# Catálogos que existem no backup mas o Alphafitus OS (Fase 26) ainda não
# tem como cadastro próprio — deliberadamente NÃO importados (ver docstring).
CATALOGOS_NAO_SUPORTADOS = ("componentes", "tabelasNutricionais", "tiposPote", "opcoesCapsula")

USUARIOS_PARA_CRIAR = {
    # nome no backup -> (email, perfil no Alphafitus OS)
    "Clayton Borges da Silva": ("claytombs1@gmail.com", "Regulatório"),
    "Edson Zaldguer": ("edsonzaldguer@alphafitus.com.br", "Regulatório"),
    "Caroline Batista": ("carolinepacheco@alphafitus.com.br", "Regulatório"),
}
# Usuário do backup que nunca assinou nada e não tem e-mail conhecido —
# importado só para registro, com login desativado (ver simplificação 3).
USUARIO_SEM_EMAIL = "Tabata"


def _gerar_senha_temporaria():
    alfabeto = string.ascii_letters + string.digits
    while True:
        senha = "".join(secrets.choice(alfabeto) for _ in range(14)) + "!9"
        if security.validar_politica_senha(senha) == []:
            return senha


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# ---------------------------------------------------------------------------
# Formatação de campos que no sistema antigo eram tabelas dinâmicas (JSON) e
# no Alphafitus OS são texto livre — ver simplificação 2 na docstring.
# ---------------------------------------------------------------------------

def _tentar_json(valor):
    if not valor:
        return None
    bruto = valor[len("__CALCV1__"):] if valor.startswith("__CALCV1__") else valor
    try:
        return json.loads(bruto)
    except (TypeError, ValueError):
        return None


def formatar_composicao_nutricional(valor):
    obj = _tentar_json(valor)
    if obj is None:
        return valor or ""
    try:
        chave = "dadosAlimento" if obj.get("tipoTabela") == "alimento" and obj.get("dadosAlimento") else "dadosPadrao"
        tabela = json.loads(obj[chave]) if isinstance(obj.get(chave), str) else obj.get(chave)
        if not tabela:
            return valor
        linhas_txt = []
        cab = f"Porção: {tabela.get('descricaoPorcao', '')} ({tabela.get('porcaoGramas', '')} g) — " \
              f"{tabela.get('porcoesPorEmbalagem', '')} porções por embalagem — grupo etário: {tabela.get('grupoEtario', '')}"
        linhas_txt.append(cab)
        linhas_txt.append("")
        for linha in tabela.get("linhas", []):
            if not linha.get("ativo", True):
                continue
            partes = [linha.get("nome", "")]
            if linha.get("por100g"):
                partes.append(f"por 100g: {linha['por100g']}")
            partes.append(f"quantidade: {linha.get('quantidade', '')}")
            if linha.get("vd"):
                partes.append(f"VD: {linha['vd']}")
            linhas_txt.append("- " + " | ".join(partes))
        if tabela.get("rodapeNaoContem"):
            linhas_txt.append("")
            linhas_txt.append(tabela["rodapeNaoContem"])
        if tabela.get("rodapeVD"):
            linhas_txt.append(tabela["rodapeVD"])
        return "\n".join(linhas_txt)
    except Exception:
        return valor


def formatar_composicao_centesimal(valor):
    obj = _tentar_json(valor)
    if obj is None:
        return valor or ""
    try:
        linhas_txt = []
        if obj.get("descricaoMassa"):
            linhas_txt.append(obj["descricaoMassa"])
            linhas_txt.append("")
        for linha in obj.get("linhas", []):
            partes = [f"{linha.get('componente', '')} ({linha.get('categoria', '')})"]
            partes.append(f"{linha.get('quantidadeIngrediente', '')} {linha.get('unidadeEntrada', '')} "
                          f"(elementar: {linha.get('quantidadeElementar', '')})")
            if linha.get("purezaAtivo") is not None:
                partes.append(f"pureza: {linha['purezaAtivo']}%")
            if linha.get("aceitacaoMin") or linha.get("aceitacaoMax"):
                partes.append(f"aceitação: {linha.get('aceitacaoMin', '')}–{linha.get('aceitacaoMax', '')}%")
            linhas_txt.append("- " + " | ".join(partes))
        return "\n".join(linhas_txt)
    except Exception:
        return valor


def formatar_calculo_quantidade(valor):
    obj = _tentar_json(valor)
    if obj is None:
        return valor or ""
    try:
        linhas_txt = [f"Unidade: {obj.get('unidade', '')}"]
        for chave, desc in (obj.get("descricoes") or {}).items():
            linhas_txt.append(f"- {chave}: {desc.get('massaDescricao', '')} / {desc.get('totalDescricao', '')}")
        return "\n".join(linhas_txt)
    except Exception:
        return valor


def formatar_calculos_nutricionais(valor):
    obj = _tentar_json(valor)
    if obj is None:
        return valor or ""
    try:
        linhas_txt = []
        for n in obj.get("nutrientes", []):
            partes = [f"{n.get('nutriente', '')} (fonte: {n.get('fonte', '')})"]
            partes.append(f"qtd. ingrediente: {n.get('qtdIngrediente', '')} {n.get('unidade', '')}")
            if n.get("fatorConversao") is not None:
                partes.append(f"fator de conversão: {n['fatorConversao']}%")
            if n.get("doseMinRef") not in (None, ""):
                partes.append(f"dose ref.: {n.get('doseMinRef', '')}–{n.get('doseMaxRef', '')}")
            if n.get("grupoPopulacional"):
                partes.append(f"grupo populacional: {n['grupoPopulacional']}")
            if n.get("aceitacaoMin") is not None:
                partes.append(f"aceitação: {n.get('aceitacaoMin', '')}–{n.get('aceitacaoMax', '')}%")
            linhas_txt.append("- " + "\n  ".join(partes))
            if n.get("fundamentoLegal"):
                linhas_txt.append(f"  Fundamento legal: {n['fundamentoLegal']}")
        return "\n".join(linhas_txt)
    except Exception:
        return valor


def _formatar_lista_selecionadas(obj, campo_titulo, campos_corpo):
    linhas_txt = []
    for item in obj.get("selecionadas", []):
        titulo = None
        for chave in campo_titulo:
            if item.get(chave):
                titulo = item[chave]
                break
        corpo_partes = []
        for chave in campos_corpo:
            if item.get(chave) and item.get(chave) != titulo:
                corpo_partes.append(str(item[chave]))
        linha = f"- {titulo}" if titulo else "-"
        if corpo_partes:
            linha += ": " + " — ".join(corpo_partes)
        linhas_txt.append(linha)
    return "\n".join(linhas_txt)


def formatar_alegacoes(valor):
    obj = _tentar_json(valor)
    if obj is None:
        return valor or ""
    try:
        return _formatar_lista_selecionadas(obj, ("ativo",), ("alegacao", "referencia", "categoria"))
    except Exception:
        return valor


def formatar_legislacao_aplicavel(valor):
    obj = _tentar_json(valor)
    if obj is None:
        return valor or ""
    try:
        return _formatar_lista_selecionadas(obj, ("codigo",), ("titulo", "categoria"))
    except Exception:
        return valor


def formatar_conclusao(valor):
    obj = _tentar_json(valor)
    if obj is None:
        return valor or ""
    try:
        return _formatar_lista_selecionadas(obj, ("titulo",), ("texto",))
    except Exception:
        return valor


def formatar_metodologias_aplicadas(valor):
    obj = _tentar_json(valor)
    if obj is None:
        return valor or ""
    try:
        return _formatar_lista_selecionadas(obj, ("nome",), ("descricao", "criterio"))
    except Exception:
        return valor


def formatar_justificativas_tecnicas(valor):
    # Só ~12 dos 49 memoriais usam a forma estruturada ({"selecionadas": [...]}
    # — as outras já são texto puro digitado à mão); os dois casos precisam
    # ser aceitos.
    obj = _tentar_json(valor)
    if obj is None or not isinstance(obj, dict) or "selecionadas" not in obj:
        return valor or ""
    try:
        return _formatar_lista_selecionadas(obj, ("titulo",), ("texto",))
    except Exception:
        return valor


def formatar_ensaios_microbiologicos(valor):
    # Idem: só parte dos memoriais usa a tabela estruturada
    # ({"linhas": [...], "observacao": ...}); o resto já é texto puro.
    obj = _tentar_json(valor)
    if obj is None or not isinstance(obj, dict) or "linhas" not in obj:
        return valor or ""
    try:
        linhas_txt = []
        for linha in obj.get("linhas", []):
            linhas_txt.append(
                f"- {linha.get('analise', '')}: n={linha.get('n', '')}, c={linha.get('c', '')}, "
                f"m={linha.get('m', '')}, M={linha.get('M', '')}"
            )
        if obj.get("observacao"):
            linhas_txt.append("")
            linhas_txt.append(obj["observacao"])
        return "\n".join(linhas_txt)
    except Exception:
        return valor


def formatar_advertencias_ou_armazenamento(valor):
    # {"selecionadas": [{"id":, "texto":}, ...]} — cada item só tem texto,
    # sem título, diferente do formato usado em alegações/legislação/etc.
    obj = _tentar_json(valor)
    if obj is None or not isinstance(obj, dict) or "selecionadas" not in obj:
        return valor or ""
    try:
        return "\n".join(f"- {item.get('texto', '')}" for item in obj.get("selecionadas", []) if item.get("texto"))
    except Exception:
        return valor


def formatar_modo_uso_memorial(valor):
    # {"selecionado": {"id":, "descricao":, "tipo":}} — um único item
    # escolhido (não é lista, diferente de advertências/armazenamento).
    obj = _tentar_json(valor)
    if obj is None or not isinstance(obj, dict) or "selecionado" not in obj:
        return valor or ""
    try:
        sel = obj.get("selecionado") or {}
        return sel.get("descricao", "") or ""
    except Exception:
        return valor


def formatar_referencias_bibliograficas(valor, catalogo_referencias_por_id):
    obj = _tentar_json(valor)
    if obj is None:
        return valor or ""
    if not isinstance(obj, list):
        return valor or ""
    try:
        linhas_txt = []
        for item_id in obj:
            ref = catalogo_referencias_por_id.get(item_id)
            if ref:
                linha = f"- {ref.get('substancia', '')} — {ref.get('referencia', '')}"
                if ref.get("tipo"):
                    linha += f" ({ref['tipo']})"
            else:
                linha = f"- {item_id}"
            linhas_txt.append(linha)
        return "\n".join(linhas_txt)
    except Exception:
        return valor or ""


# ---------------------------------------------------------------------------
# Importação em si
# ---------------------------------------------------------------------------

class Relatorio:
    def __init__(self):
        self.linhas = []
        self.contadores = {}

    def contar(self, chave, n=1):
        self.contadores[chave] = self.contadores.get(chave, 0) + n

    def avisar(self, texto):
        self.linhas.append(texto)

    def imprimir(self):
        print("\n" + "=" * 70)
        print("RELATÓRIO DA IMPORTAÇÃO")
        print("=" * 70)
        for chave, n in self.contadores.items():
            print(f"  {chave}: {n}")
        if self.linhas:
            print("\nAvisos:")
            for linha in self.linhas:
                print(f"  - {linha}")
        print("=" * 70)


def conectar(db_path):
    if not os.path.exists(db_path):
        raise SystemExit(
            f"O banco '{db_path}' não existe. Rode primeiro `python run.py` (ou "
            f"`python -c \"from app.db import init_db; init_db()\"`) e depois "
            f"`python seed.py` para criar o schema e os dados iniciais, antes de importar."
        )
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    tabelas = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    faltando = {"memoriais", "memorial_empresas", "memorial_produtos", "memorial_anexos",
                "memorial_padronizacoes", "memorial_catalogo_itens", "perfis", "usuarios"} - tabelas
    if faltando:
        raise SystemExit(
            f"O banco '{db_path}' não tem as tabelas {sorted(faltando)} — rode as migrations "
            f"até a Fase 27 antes de importar (`python -c \"from app.db import init_db; init_db()\"`)."
        )
    return conn


def garantir_usuarios(conn, relatorio, senhas_impressas):
    perfis_por_nome = {r["nome"]: r["id"] for r in conn.execute("SELECT id, nome FROM perfis").fetchall()}
    if "Regulatório" not in perfis_por_nome:
        raise SystemExit(
            "O perfil 'Regulatório' não existe neste banco — rode `python seed.py` "
            "(ele já cria esse perfil) antes de importar."
        )

    ids_por_nome = {}
    for nome, (email, nome_perfil) in USUARIOS_PARA_CRIAR.items():
        existente = conn.execute("SELECT id FROM usuarios WHERE email = ?", (email,)).fetchone()
        if existente:
            ids_por_nome[nome] = existente["id"]
            relatorio.avisar(f"Usuário '{nome}' <{email}> já existia (id {existente['id']}) — não recriado.")
            continue
        senha = _gerar_senha_temporaria()
        cur = conn.execute(
            """
            INSERT INTO usuarios (nome, email, senha_hash, status, senha_deve_trocar, criado_em)
            VALUES (?, ?, ?, 'ativo', 1, ?)
            """,
            (nome, email, security.hash_password(senha), _now_iso()),
        )
        usuario_id = cur.lastrowid
        conn.execute(
            "INSERT INTO usuario_perfil (usuario_id, perfil_id, atribuido_em) VALUES (?, ?, ?)",
            (usuario_id, perfis_por_nome[nome_perfil], _now_iso()),
        )
        ids_por_nome[nome] = usuario_id
        senhas_impressas.append((nome, email, senha))
        relatorio.contar("usuarios criados")

    # Tabata: sem e-mail conhecido no backup, importada inativa (ver simplificação 3).
    email_tabata = "tabata@alphafitus.com.br"
    existente = conn.execute("SELECT id FROM usuarios WHERE email = ?", (email_tabata,)).fetchone()
    if existente:
        ids_por_nome[USUARIO_SEM_EMAIL] = existente["id"]
    else:
        senha = _gerar_senha_temporaria()
        cur = conn.execute(
            """
            INSERT INTO usuarios (nome, email, senha_hash, status, senha_deve_trocar, criado_em)
            VALUES (?, ?, ?, 'inativo', 1, ?)
            """,
            (USUARIO_SEM_EMAIL, email_tabata, security.hash_password(senha), _now_iso()),
        )
        usuario_id = cur.lastrowid
        conn.execute(
            "INSERT INTO usuario_perfil (usuario_id, perfil_id, atribuido_em) VALUES (?, ?, ?)",
            (usuario_id, perfis_por_nome["Regulatório"], _now_iso()),
        )
        ids_por_nome[USUARIO_SEM_EMAIL] = usuario_id
        relatorio.contar("usuarios criados")
        relatorio.avisar(
            f"Usuário 'Tabata' importado com status inativo (sem e-mail no backup) — "
            f"e-mail provisório {email_tabata}, reative e ajuste depois se for usá-lo."
        )

    conn.commit()
    return ids_por_nome


def importar_empresa(conn, dados, relatorio, usuario_id_dono):
    empresa = dados["empresas"][0]
    existente = conn.execute(
        "SELECT id FROM memorial_empresas WHERE cnpj = ?", (empresa["cnpj"],)
    ).fetchone()
    if existente:
        relatorio.avisar(f"Empresa CNPJ {empresa['cnpj']} já existia (id {existente['id']}) — não recriada.")
        return existente["id"], {empresa["id"]: existente["id"]}

    cur = conn.execute(
        """
        INSERT INTO memorial_empresas
            (nome_fantasia, razao_social, cnpj, ie, responsavel_tecnico, crf, endereco,
             cidade, estado, cep, telefone, email, criado_por, criado_em)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (empresa["nomeFantasia"], empresa["razaoSocial"], empresa["cnpj"], empresa.get("ie"),
         empresa.get("responsavelTecnico"), empresa.get("crf"), empresa.get("endereco"),
         empresa.get("cidade"), empresa.get("estado"), empresa.get("cep"), empresa.get("telefone"),
         empresa.get("email"), usuario_id_dono, empresa.get("createdAt") or _now_iso()),
    )
    novo_id = cur.lastrowid
    conn.commit()
    relatorio.contar("empresas importadas")
    return novo_id, {empresa["id"]: novo_id}


def importar_produtos(conn, dados, relatorio, usuario_id_dono, empresa_id_map):
    produto_id_map = {}
    for p in dados["produtos"]:
        empresa_id = empresa_id_map.get(p["empresaId"])
        if empresa_id is None:
            relatorio.avisar(f"Produto '{p['nome']}' (id {p['id']}) referencia empresa desconhecida — pulado.")
            continue
        campos_extra = {c: p.get(_camel(c)) for c in CAMPOS_PRODUTO}
        colunas = ["empresa_id", "nome", "categoria", "forma_farmaceutica", "porcao_gramas",
                   "quantidade_porcoes", "criado_por", "criado_em"] + list(CAMPOS_PRODUTO)
        valores = [empresa_id, p["nome"], (p.get("categoria") or "").strip(),
                   (p.get("formaFarmaceutica") or "").strip(), float(p["porcaoGramas"]),
                   int(p["quantidadePorcoes"]), usuario_id_dono, p.get("createdAt") or _now_iso()]
        valores += [campos_extra[c] for c in CAMPOS_PRODUTO]
        placeholders = ", ".join("?" for _ in colunas)
        cur = conn.execute(
            f"INSERT INTO memorial_produtos ({', '.join(colunas)}) VALUES ({placeholders})",
            valores,
        )
        produto_id_map[p["id"]] = cur.lastrowid
        relatorio.contar("produtos importados")
    conn.commit()
    return produto_id_map


def _camel(campo_snake):
    partes = campo_snake.split("_")
    return partes[0] + "".join(p.title() for p in partes[1:])


_EXCECOES_CAMEL_MEMORIAL = {
    # campo interno (snake_case) -> chave real no backup, quando ela não
    # segue a convenção camelCase simples que `_camel()` produziria.
    "intervalos_teste": "intervalosTestе",  # 'е' final é cirílico (U+0435) no backup, em TODOS os 49 registros
    "email_rt": "emailRT",  # "RT" (Responsável Técnico) vem inteiro maiúsculo, não "Rt"
}


def _obter_campo_memorial(m, campo_snake):
    """Como `m.get(_camel(campo_snake))`, mas cobrindo as chaves do backup
    que não seguem a convenção camelCase simples (ver
    `_EXCECOES_CAMEL_MEMORIAL`) — sem isso, esses campos sumiriam
    silenciosamente em toda importação."""
    chave = _EXCECOES_CAMEL_MEMORIAL.get(campo_snake, _camel(campo_snake))
    return m.get(chave)


def importar_memoriais(conn, dados, relatorio, usuario_id_dono, produto_id_map, usuarios_id_map,
                        catalogo_referencias_por_id):
    memorial_id_map = {}
    formatadores = {
        "composicao_nutricional": formatar_composicao_nutricional,
        "composicao_centesimal": formatar_composicao_centesimal,
        "calculo_quantidade": formatar_calculo_quantidade,
        "calculos_nutricionais": formatar_calculos_nutricionais,
        "alegacoes": formatar_alegacoes,
        "legislacao_aplicavel": formatar_legislacao_aplicavel,
        "conclusao": formatar_conclusao,
        "metodologias_aplicadas": formatar_metodologias_aplicadas,
        "justificativas_tecnicas": formatar_justificativas_tecnicas,
        "ensaios_microbiologicos": formatar_ensaios_microbiologicos,
        "advertencias": formatar_advertencias_ou_armazenamento,
        "armazenamento": formatar_advertencias_ou_armazenamento,
        "modo_uso": formatar_modo_uso_memorial,
    }
    for m in dados["memoriais"]:
        produto_id = produto_id_map.get(m["produtoId"])
        if produto_id is None:
            relatorio.avisar(f"Memorial '{m['codigo']}' (id {m['id']}) referencia produto desconhecido — pulado.")
            continue
        existente = conn.execute("SELECT id FROM memoriais WHERE codigo = ?", (m["codigo"],)).fetchone()
        if existente:
            memorial_id_map[m["id"]] = existente["id"]
            relatorio.avisar(f"Memorial '{m['codigo']}' já existia (id {existente['id']}) — não recriado.")
            continue

        valores_campos = {}
        for campo in CAMPOS_MEMORIAL:
            bruto = _obter_campo_memorial(m, campo)
            if campo == "referencias_bibliograficas":
                valores_campos[campo] = formatar_referencias_bibliograficas(bruto, catalogo_referencias_por_id)
            elif campo in formatadores:
                valores_campos[campo] = formatadores[campo](bruto)
            else:
                valores_campos[campo] = bruto

        colunas = ["produto_id", "codigo", "numero_certificado", "status", "data_inicio", "data_fim",
                   "criado_por", "criado_em", "atualizado_por", "atualizado_em"] + list(CAMPOS_MEMORIAL)
        valores = [produto_id, m["codigo"], m["numeroCertificado"], m["status"], m["dataInicio"], m["dataFim"],
                   usuario_id_dono, m.get("createdAt") or _now_iso(), usuario_id_dono,
                   m.get("updatedAt") or m.get("createdAt") or _now_iso()]
        valores += [valores_campos[c] for c in CAMPOS_MEMORIAL]
        placeholders = ", ".join("?" for _ in colunas)
        cur = conn.execute(
            f"INSERT INTO memoriais ({', '.join(colunas)}) VALUES ({placeholders})",
            valores,
        )
        memorial_id_map[m["id"]] = cur.lastrowid
        relatorio.contar("memoriais importados")
    conn.commit()
    return memorial_id_map


def importar_assinaturas(conn, dados, relatorio, memorial_id_map, usuarios_id_map, usuario_id_dono):
    for a in dados["assinaturas"]:
        memorial_id = memorial_id_map.get(a["memorialId"])
        if memorial_id is None:
            continue
        usuario_id = usuarios_id_map.get(a["nome"])
        if usuario_id is None:
            relatorio.avisar(f"Assinatura de '{a['nome']}' no memorial id {a['memorialId']} "
                              f"não bate com nenhum usuário conhecido — atribuída ao responsável pela importação.")
            usuario_id = usuario_id_dono
        ja_existe = conn.execute(
            "SELECT 1 FROM memorial_assinaturas WHERE memorial_id = ? AND usuario_id = ?",
            (memorial_id, usuario_id),
        ).fetchone()
        if ja_existe:
            continue
        conn.execute(
            """
            INSERT INTO memorial_assinaturas (memorial_id, usuario_id, nome, cargo, iniciais, assinado_em)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (memorial_id, usuario_id, a["nome"], a.get("cargo") or "Responsável",
             a.get("iniciais") or "".join(p[0] for p in a["nome"].split()[:2]).upper(),
             a.get("assinadoEm") or _now_iso()),
        )
        relatorio.contar("assinaturas importadas")
    conn.commit()


def importar_historico(conn, dados, relatorio, memorial_id_map, usuarios_id_map):
    for h in dados["historico"]:
        memorial_id = memorial_id_map.get(h["memorialId"])
        if memorial_id is None:
            continue
        usuario_id = usuarios_id_map.get(h["usuario"])  # None é válido aqui (coluna aceita NULL)
        conn.execute(
            """
            INSERT INTO memorial_historico (memorial_id, usuario_id, usuario_nome, acao, descricao, criado_em)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (memorial_id, usuario_id, h.get("usuario") or "Sistema", h["acao"], h.get("descricao"),
             h.get("criadoEm") or _now_iso()),
        )
        relatorio.contar("eventos de histórico importados")
    conn.commit()


def importar_anexos(conn, dados, relatorio, memorial_id_map, usuarios_id_map, usuario_id_dono):
    for a in dados["anexos"]:
        memorial_id = memorial_id_map.get(a["memorialId"])
        if memorial_id is None:
            continue
        usuario_id = usuarios_id_map.get(a["usuarioNome"], usuario_id_dono)
        conn.execute(
            """
            INSERT INTO memorial_anexos
                (memorial_id, nome, nome_arquivo, tipo_mime, dados, tamanho, usuario_nome, criado_por, criado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (memorial_id, a["nome"], a["nomeArquivo"], a["tipoMime"], a["dados"], a["tamanho"],
             a["usuarioNome"], usuario_id, a.get("criadoEm") or _now_iso()),
        )
        relatorio.contar("anexos importados (arquivos)")
    conn.commit()


def importar_padronizacoes(conn, dados, relatorio, memorial_id_map, usuario_id_dono):
    for p in dados["padronizacoes"]:
        memorial_id = memorial_id_map.get(p["memorialId"])
        if memorial_id is None:
            continue
        ja_existe = conn.execute(
            "SELECT 1 FROM memorial_padronizacoes WHERE memorial_id = ?", (memorial_id,)
        ).fetchone()
        if ja_existe:
            continue
        colunas = ["memorial_id", "atualizado_por", "atualizado_em"] + list(CAMPOS_PADRONIZACAO)
        valores = [memorial_id, usuario_id_dono, _now_iso()]
        valores += [p.get(_camel(c)) for c in CAMPOS_PADRONIZACAO]
        placeholders = ", ".join("?" for _ in colunas)
        conn.execute(
            f"INSERT INTO memorial_padronizacoes ({', '.join(colunas)}) VALUES ({placeholders})",
            valores,
        )
        relatorio.contar("padronizações importadas")
    conn.commit()


def importar_catalogos(conn, dados, relatorio, usuario_id_dono):
    catalogos_backup = dados.get("catalogos", {})
    for chave_backup, (catalogo_interno, mapa_campos) in CATALOGOS_MAPA.items():
        itens = catalogos_backup.get(chave_backup) or []
        for item in itens:
            campos_json = {}
            for campo_backup, campo_interno in mapa_campos.items():
                valor = item.get(campo_backup)
                if isinstance(valor, bool):
                    valor = 1 if valor else 0
                campos_json[campo_interno] = valor
            ordem = item.get("ordem", 0) or 0
            ativo = item.get("ativo", True)
            ativo = 1 if (ativo is None or ativo) else 0
            conn.execute(
                """
                INSERT INTO memorial_catalogo_itens (catalogo, ordem, ativo, dados, criado_por, criado_em)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (catalogo_interno, ordem, ativo, json.dumps(campos_json, ensure_ascii=False),
                 usuario_id_dono, _now_iso()),
            )
            relatorio.contar(f"itens de catálogo importados ({catalogo_interno})")
    conn.commit()

    for chave in CATALOGOS_NAO_SUPORTADOS:
        n = len(catalogos_backup.get(chave) or [])
        if n:
            relatorio.avisar(
                f"Catálogo '{chave}' do backup tem {n} item(ns), mas o Alphafitus OS ainda não "
                f"tem esse cadastro (fora do escopo da Fase 26) — não importado."
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backup", required=True, help="Caminho do arquivo Memorial-backup-*.json")
    parser.add_argument("--db", required=True, help="Caminho do banco Alphafitus OS já inicializado (schema+seed)")
    args = parser.parse_args()

    with open(args.backup, "r", encoding="utf-8") as f:
        backup = json.load(f)
    dados = backup["dados"]

    conn = conectar(args.db)
    relatorio = Relatorio()
    senhas_impressas = []

    try:
        usuarios_id_map = garantir_usuarios(conn, relatorio, senhas_impressas)
        usuario_id_dono = usuarios_id_map.get("Clayton Borges da Silva") or list(usuarios_id_map.values())[0]

        catalogo_referencias_por_id = {r["id"]: r for r in (dados.get("catalogos", {}).get("referencias") or [])}

        _, empresa_id_map = importar_empresa(conn, dados, relatorio, usuario_id_dono)
        produto_id_map = importar_produtos(conn, dados, relatorio, usuario_id_dono, empresa_id_map)
        memorial_id_map = importar_memoriais(conn, dados, relatorio, usuario_id_dono, produto_id_map,
                                              usuarios_id_map, catalogo_referencias_por_id)
        importar_assinaturas(conn, dados, relatorio, memorial_id_map, usuarios_id_map, usuario_id_dono)
        importar_historico(conn, dados, relatorio, memorial_id_map, usuarios_id_map)
        importar_anexos(conn, dados, relatorio, memorial_id_map, usuarios_id_map, usuario_id_dono)
        importar_padronizacoes(conn, dados, relatorio, memorial_id_map, usuario_id_dono)
        importar_catalogos(conn, dados, relatorio, usuario_id_dono)
    finally:
        conn.close()

    relatorio.imprimir()
    if senhas_impressas:
        print("\nUsuários criados — senha temporária (troca obrigatória no primeiro login):")
        for nome, email, senha in senhas_impressas:
            print(f"  {nome} <{email}>: {senha}")


if __name__ == "__main__":
    main()
