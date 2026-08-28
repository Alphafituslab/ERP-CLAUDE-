"""
Fase 116/121 — Importação do backup do sistema "Anvisa Technical Memorial"
(Node/React/Postgres, hospedado no Replit) para o módulo Memorial Técnico
do AlphafitusOS.

Pedido do usuário: "trazer tudo igual... verificar se está tudo
funcionando perfeitamente" — importa TUDO que já tem tabela de destino no
AlphafitusOS: empresas, produtos, memoriais, padronizações, assinaturas,
anexos, histórico e catálogos.

Dois itens do export são DELIBERADAMENTE deixados de fora, por não terem
tabela de destino ainda (nada é perdido — o arquivo original continua
intacto em disco, pode ser reimportado quando essas fases existirem):
  - `tabelasNutricionais` (Fase 118, ainda não construída) — no export
    atual está vazio (0 itens) mesmo, então não há nada a perder agora.
  - `snapshots` (Fase 120, biblioteca de snapshots, ainda não construída).

Também NÃO importa `usuarios`/`permissoes` do export — são de um sistema
de login inteiramente diferente; as contas reais (Clayton, Caroline
Batista, Edson Zaldguer, Tabata) já foram criadas manualmente no
AlphafitusOS antes desta importação, com e-mails reais encontrados nos
próprios dados do memorial (campos emailRT/emailAnalistaSenior).

Mapeamento de autoria: `criado_por` (NOT NULL em empresas/produtos/
memoriais/anexos) não tem equivalente direto no export — usa sempre o
Administrador (Clayton, id 1) como "quem criou o registro no banco", já
que isso é só metadado técnico. A autoria REGULATÓRIA de verdade
(elaborado_por, aprovado_por, analista_senior, quem assinou) é importada
fielmente a partir dos campos de texto/assinatura reais do memorial —
não é a mesma coisa que `criado_por`.

Uso:
    python scripts/importar_memorial_anvisa.py <caminho_do_json> [--banco <caminho_do_db>] [--confirmar]

Sem --confirmar, roda em modo de teste: imprime um resumo do que SERIA
importado, sem gravar nada (dry-run). Com --confirmar, grava de verdade,
tudo dentro de uma única transação (tudo ou nada).
"""
import argparse
import json
import sqlite3
import sys
import unicodedata


def normalizar(s):
    if not s:
        return ""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.lower().strip()


# Nome (normalizado) -> id do usuário real já criado no AlphafitusOS.
def mapa_usuarios(conn):
    linhas = conn.execute("SELECT id, nome FROM usuarios").fetchall()
    return {normalizar(nome): uid for uid, nome in linhas}


ADMIN_ID = 1  # Clayton — usado como criado_por padrão (ver docstring acima)


def _now_iso():
    import datetime
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# ---------------------------------------------------------------------
# CATÁLOGOS — de-para de campo camelCase (export) -> snake_case (destino),
# um dict por catálogo, na MESMA estrutura de CATALOGOS_CONFIG em
# app/routes/memorial_catalogos.py (Fase 115).
# ---------------------------------------------------------------------
CATALOGO_CAMPOS = {
    "metodologias": {"categoria": "categoria", "nome": "nome", "descricao": "descricao",
                      "norma": "norma", "referencia": "referencia", "principio": "principio",
                      "aplicacao": "aplicacao"},
    "nutrientes": {"nome": "nome", "unidade": "unidade", "doseMinima": "dose_minima",
                   "doseMaxima": "dose_maxima", "unidadeDose": "unidade_dose", "categoria": "categoria",
                   "descricao": "descricao", "purezaPadrao": "pureza_padrao", "vdReferencia": "vd_referencia",
                   "grupoPopulacional": "grupo_populacional", "fundamentoLegal": "fundamento_legal",
                   "aceitacaoMin": "aceitacao_min", "aceitacaoMax": "aceitacao_max",
                   "tipoComposicao": "tipo_composicao", "fonteMateriaprima": "fonte_materia_prima"},
    "legislacoes": {"codigo": "codigo", "titulo": "titulo", "categoria": "categoria",
                     "ano": "ano", "descricao": "descricao"},
    "alegacoes": {"ativo": "ativo_nutricional", "alegacao": "alegacao", "referencia": "referencia",
                  "categoria": "categoria"},
    "tipos_produto": {"nome": "nome", "temCapsula": "tem_capsula"},
    "advertencias": {"texto": "texto"},
    "armazenamento": {"texto": "texto"},
    "modo_uso": {"descricao": "descricao", "tipo": "tipo"},
    "justificativas": {"titulo": "titulo", "texto": "texto"},
    "referencias": {"substancia": "substancia", "referencia": "referencia", "descricao": "descricao",
                     "tipo": "tipo", "autoIncluir": "auto_incluir", "grupo": "grupo", "doi": "doi"},
    "componentes": {"nome": "nome", "purezaPadrao": "pureza_padrao", "unidade": "unidade",
                     "categoria": "categoria", "descricao": "descricao", "aceitacaoMin": "aceitacao_min",
                     "aceitacaoMax": "aceitacao_max"},
    "opcoes_capsula": {"nome": "nome"},
    "tipos_pote": {"nome": "nome", "larguraRotulo": "largura_rotulo", "comprimentoRotulo": "comprimento_rotulo"},
}
# chave no JSON de export ("dados.catalogos.<chave>") -> chave do catálogo no AlphafitusOS
CATALOGO_CHAVE_EXPORT_PARA_DESTINO = {
    "metodologias": "metodologias", "componentes": "componentes", "legislacoes": "legislacoes",
    "alegacoes": "alegacoes", "nutrientes": "nutrientes", "tiposProduto": "tipos_produto",
    "tiposPote": "tipos_pote", "opcoesCapsula": "opcoes_capsula", "advertencias": "advertencias",
    "armazenamento": "armazenamento", "modoUso": "modo_uso", "justificativas": "justificativas",
    "referencias": "referencias",
}

CAMPOS_PRODUTO_EXPORT = {
    "ingredientesAtivos": "ingredientes_ativos", "excipientes": "excipientes", "embalagem": "embalagem",
    "advertencias": "advertencias", "modoDeUso": "modo_de_uso", "armazenamento": "armazenamento",
    "quantidadeCapsulasTotais": "quantidade_capsulas_totais", "pesoLiquido": "peso_liquido",
    "tamanhoCapsulas": "tamanho_capsulas", "tipoCapsulas": "tipo_capsulas", "tipoProduto": "tipo_produto",
    "referenciasComerciais": "referencias_comerciais", "comprimentoRotulo": "comprimento_rotulo",
    "larguraRotulo": "largura_rotulo", "tamanhoPote": "tamanho_pote", "tamanhoCapsula": "tamanho_capsula",
    "numeroProtocoloAnvisa": "numero_protocolo_anvisa", "sabor": "sabor",
}

CAMPOS_MEMORIAL_EXPORT = {
    "objetivo": "objetivo", "composicaoNutricional": "composicao_nutricional",
    "listaIngredientes": "lista_ingredientes", "alegacoes": "alegacoes",
    "justificativasTecnicas": "justificativas_tecnicas", "metodosAnaliticos": "metodos_analiticos",
    "estabilidadeAcelerada": "estabilidade_acelerada", "ensaiosMicrobiologicos": "ensaios_microbiologicos",
    "calculosNutricionais": "calculos_nutricionais", "legislacaoAplicavel": "legislacao_aplicavel",
    "observacoes": "observacoes", "conclusao": "conclusao",
    "referenciasBibliograficas": "referencias_bibliograficas", "composicaoCentesimal": "composicao_centesimal",
    "calculoQuantidade": "calculo_quantidade", "metodologiasAplicadas": "metodologias_aplicadas",
    "tipoProduto": "tipo_produto", "tipoPote": "tipo_pote", "ingredientesAtivos": "ingredientes_ativos",
    "excipientes": "excipientes", "composicaoCapsula": "composicao_capsula", "temperatura": "temperatura",
    "umidadeRelativa": "umidade_relativa", "periodoEstudo": "periodo_estudo",
    "intervalosTestе": "intervalos_teste",  # sic — o export tem um "е" cirílico neste nome de campo
    "intervalosTeste": "intervalos_teste",  # variante normal, caso o export não tenha o typo em algum registro
    "advertencias": "advertencias", "armazenamento": "armazenamento", "modoUso": "modo_uso",
    "elaboradoPor": "elaborado_por", "aprovadoPor": "aprovado_por", "laudoEmitidoPor": "laudo_emitido_por",
    "analistaSenior": "analista_senior", "emailRT": "email_rt", "emailAnalistaSenior": "email_analista_senior",
    "observacaoAnalista": "observacao_analista", "dataEmissao": "data_emissao",
}

CAMPOS_PADRONIZACAO_EXPORT = {
    "produto": "produto", "pesoLiquido": "peso_liquido", "contem": "contem",
    "denominacaoLegal": "denominacao_legal", "listaIngredientes": "lista_ingredientes",
    "alergenicos": "alergenicos", "advertencias": "advertencias", "conservacao": "conservacao",
    "informacoesConsumo": "informacoes_consumo", "larguraRotulo": "largura_rotulo",
    "comprimentoRotulo": "comprimento_rotulo", "alturaRotulo": "altura_rotulo", "corCapsula": "cor_capsula",
    "tamanhoCapsulas": "tamanho_capsulas", "tipoCapsulas": "tipo_capsulas", "tamanhoPote": "tamanho_pote",
    "simbolosLogos": "simbolos_logos", "alegacoes": "alegacoes", "dadosDistribuidor": "dados_distribuidor",
    "observacoesTabela": "observacoes_tabela",
}


def importar(caminho_json, caminho_db, confirmar):
    with open(caminho_json, "r", encoding="utf-8") as f:
        export = json.load(f)
    dados = export["dados"]

    conn = sqlite3.connect(caminho_db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    usuarios_por_nome = mapa_usuarios(conn)

    resumo = {"empresas": 0, "produtos": 0, "memoriais": 0, "padronizacoes": 0,
              "assinaturas": 0, "assinaturas_puladas_duplicadas": 0, "anexos": 0,
              "historico": 0, "catalogo_itens": 0}

    mapa_empresa_id = {}
    mapa_produto_id = {}
    mapa_memorial_id = {}
    mapa_referencia_id = {}  # id string do export (catalogo_referencias) -> id inteiro novo

    # ---- Catálogos (importados ANTES dos memoriais: o campo
    # referenciasBibliograficas de cada memorial é uma lista de IDs do
    # catálogo "referencias" do sistema antigo — precisa do mapa
    # id-antigo -> id-novo pronto antes de remapear esse campo) ----
    catalogos_export = dados.get("catalogos", {})
    for chave_export, chave_destino in CATALOGO_CHAVE_EXPORT_PARA_DESTINO.items():
        itens = catalogos_export.get(chave_export, [])
        mapa_campos = CATALOGO_CAMPOS[chave_destino]
        for item in itens:
            campos = {}
            for velho, novo in mapa_campos.items():
                valor = item.get(velho)
                if novo == "tem_capsula" or novo == "auto_incluir":
                    valor = bool(valor) if valor is not None else False
                campos[novo] = valor
            ordem = item.get("ordem") or 0
            ativo = 1 if item.get("ativo", True) else 0
            cur = conn.execute(
                "INSERT INTO memorial_catalogo_itens (catalogo, ordem, ativo, dados, criado_por) "
                "VALUES (?, ?, ?, ?, ?)",
                (chave_destino, ordem, ativo, json.dumps(campos, ensure_ascii=False), ADMIN_ID),
            )
            if chave_destino == "referencias" and item.get("id") is not None:
                mapa_referencia_id[item["id"]] = cur.lastrowid
            resumo["catalogo_itens"] += 1

    # ---- Empresas ----
    for e in dados.get("empresas", []):
        cur = conn.execute(
            """INSERT INTO memorial_empresas
               (nome_fantasia, razao_social, cnpj, ie, responsavel_tecnico, crf, endereco, cidade,
                estado, cep, telefone, email, telefone_contato, criado_por)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (e.get("nomeFantasia"), e.get("razaoSocial"), e.get("cnpj"), e.get("ie"),
             e.get("responsavelTecnico"), e.get("crf"), e.get("endereco"), e.get("cidade"),
             e.get("estado"), e.get("cep"), e.get("telefone"), e.get("email"),
             e.get("telefoneContato"), ADMIN_ID),
        )
        mapa_empresa_id[e["id"]] = cur.lastrowid
        resumo["empresas"] += 1

    # ---- Produtos ----
    for p in dados.get("produtos", []):
        empresa_nova_id = mapa_empresa_id.get(p.get("empresaId"))
        if empresa_nova_id is None:
            print(f"  [AVISO] produto '{p.get('nome')}' (id export {p['id']}) referencia empresaId "
                  f"{p.get('empresaId')} que não foi importada — pulando produto.")
            continue
        extras = {novo: p.get(velho) for velho, novo in CAMPOS_PRODUTO_EXPORT.items()}
        colunas_extra = list(extras.keys())
        cur = conn.execute(
            f"""INSERT INTO memorial_produtos
                (empresa_id, nome, categoria, forma_farmaceutica, porcao_gramas, quantidade_porcoes,
                 {", ".join(colunas_extra)}, criado_por)
                VALUES (?, ?, ?, ?, ?, ?, {", ".join("?" for _ in colunas_extra)}, ?)""",
            (empresa_nova_id, p.get("nome"), p.get("categoria"), p.get("formaFarmaceutica"),
             p.get("porcaoGramas"), p.get("quantidadePorcoes"),
             *[extras[c] for c in colunas_extra], ADMIN_ID),
        )
        mapa_produto_id[p["id"]] = cur.lastrowid
        resumo["produtos"] += 1

    # ---- Memoriais ----
    for m in dados.get("memoriais", []):
        produto_novo_id = mapa_produto_id.get(m.get("produtoId"))
        if produto_novo_id is None:
            print(f"  [AVISO] memorial '{m.get('codigo')}' (id export {m['id']}) referencia produtoId "
                  f"{m.get('produtoId')} que não foi importado — pulando memorial.")
            continue
        status = m.get("status") or "rascunho"
        if status not in ("rascunho", "em_andamento", "em_revisao", "concluido", "aprovado", "reprovado"):
            status = "rascunho"
        extras = {}
        for velho, novo in CAMPOS_MEMORIAL_EXPORT.items():
            if velho in m and m.get(velho) is not None:
                extras[novo] = m.get(velho)
        for novo in set(CAMPOS_MEMORIAL_EXPORT.values()):
            extras.setdefault(novo, None)

        # `referenciasBibliograficas` não é texto livre: é um JSON com uma
        # LISTA DE IDs apontando pro catálogo de Referências do sistema
        # antigo (IDs string tipo "7k3sfn64"). Como os itens do catálogo
        # foram importados com IDs NOVOS (inteiros autoincrement), os IDs
        # antigos precisam ser remapeados aqui — sem isso, o link quebraria
        # silenciosamente (apontaria pra um id que não existe mais).
        ids_antigos = []
        try:
            bruto = json.loads(m.get("referenciasBibliograficas") or "[]")
            if isinstance(bruto, list):
                ids_antigos = [x for x in bruto if isinstance(x, str)]
        except (TypeError, ValueError):
            pass
        ids_novos = []
        for id_antigo in ids_antigos:
            id_novo = mapa_referencia_id.get(id_antigo)
            if id_novo is None:
                print(f"  [AVISO] memorial '{m.get('codigo')}' referencia bibliográfica com id "
                      f"'{id_antigo}' que não foi encontrado no catálogo importado — pulando essa referência.")
                continue
            ids_novos.append(id_novo)
        extras["referencias_bibliograficas"] = json.dumps(ids_novos) if ids_novos else None

        colunas_extra = list(extras.keys())
        # codigo/numero_certificado são UNIQUE — o export às vezes repete o
        # mesmo valor nos dois campos; usa codigo como está e, se faltar,
        # cai pro numeroCertificado (e vice-versa).
        codigo = m.get("codigo") or m.get("numeroCertificado")
        numero_certificado = m.get("numeroCertificado") or m.get("codigo")
        cur = conn.execute(
            f"""INSERT INTO memoriais
                (produto_id, codigo, numero_certificado, status, data_inicio, data_fim,
                 {", ".join(colunas_extra)}, criado_por)
                VALUES (?, ?, ?, ?, ?, ?, {", ".join("?" for _ in colunas_extra)}, ?)""",
            (produto_novo_id, codigo, numero_certificado, status,
             m.get("dataInicio") or "2000-01-01", m.get("dataFim") or "2000-01-01",
             *[extras[c] for c in colunas_extra], ADMIN_ID),
        )
        mapa_memorial_id[m["id"]] = cur.lastrowid
        resumo["memoriais"] += 1

    # ---- Padronizações ----
    for pad in dados.get("padronizacoes", []):
        memorial_novo_id = mapa_memorial_id.get(pad.get("memorialId"))
        if memorial_novo_id is None:
            continue
        extras = {novo: pad.get(velho) for velho, novo in CAMPOS_PADRONIZACAO_EXPORT.items()}
        colunas = list(extras.keys())
        conn.execute(
            f"""INSERT INTO memorial_padronizacoes (memorial_id, {", ".join(colunas)}, atualizado_por)
                VALUES (?, {", ".join("?" for _ in colunas)}, ?)""",
            (memorial_novo_id, *[extras[c] for c in colunas], ADMIN_ID),
        )
        resumo["padronizacoes"] += 1

    # ---- Assinaturas ----
    for a in dados.get("assinaturas", []):
        memorial_novo_id = mapa_memorial_id.get(a.get("memorialId"))
        if memorial_novo_id is None:
            continue
        usuario_id = usuarios_por_nome.get(normalizar(a.get("nome")))
        if usuario_id is None:
            print(f"  [AVISO] assinatura de '{a.get('nome')}' não bate com nenhum usuário real cadastrado — pulando.")
            continue
        ja_existe = conn.execute(
            "SELECT 1 FROM memorial_assinaturas WHERE memorial_id = ? AND usuario_id = ?",
            (memorial_novo_id, usuario_id),
        ).fetchone()
        if ja_existe:
            resumo["assinaturas_puladas_duplicadas"] += 1
            continue
        conn.execute(
            "INSERT INTO memorial_assinaturas (memorial_id, usuario_id, nome, cargo, iniciais, assinado_em) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (memorial_novo_id, usuario_id, a.get("nome"), a.get("cargo") or "—",
             a.get("iniciais") or "", a.get("assinadoEm") or _now_iso()),
        )
        resumo["assinaturas"] += 1

    # ---- Anexos ----
    for anexo in dados.get("anexos", []):
        memorial_novo_id = mapa_memorial_id.get(anexo.get("memorialId"))
        if memorial_novo_id is None:
            continue
        criado_por = usuarios_por_nome.get(normalizar(anexo.get("usuarioNome")), ADMIN_ID)
        conn.execute(
            "INSERT INTO memorial_anexos "
            "(memorial_id, nome, nome_arquivo, tipo_mime, dados, tamanho, usuario_nome, criado_por, criado_em) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (memorial_novo_id, anexo.get("nome") or anexo.get("nomeArquivo"), anexo.get("nomeArquivo"),
             anexo.get("tipoMime") or "application/octet-stream", anexo.get("dados") or "",
             anexo.get("tamanho") or 0, anexo.get("usuarioNome") or "Desconhecido",
             criado_por, anexo.get("criadoEm") or _now_iso()),
        )
        resumo["anexos"] += 1

    # ---- Histórico ----
    for h in dados.get("historico", []):
        memorial_novo_id = mapa_memorial_id.get(h.get("memorialId"))
        if memorial_novo_id is None:
            continue
        usuario_id = usuarios_por_nome.get(normalizar(h.get("usuario"))) if h.get("usuario") else None
        conn.execute(
            "INSERT INTO memorial_historico (memorial_id, usuario_id, usuario_nome, acao, descricao, criado_em) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (memorial_novo_id, usuario_id, h.get("usuario") or "Sistema", h.get("acao") or "evento",
             h.get("descricao"), h.get("criadoEm") or _now_iso()),
        )
        resumo["historico"] += 1

    print("\n" + "=" * 60)
    print("RESUMO DA IMPORTAÇÃO" + (" (TESTE — nada foi gravado)" if not confirmar else ""))
    print("=" * 60)
    for k, v in resumo.items():
        print(f"  {k}: {v}")

    if confirmar:
        conn.commit()
        print("\nGravado com sucesso.")
    else:
        conn.rollback()
        print("\nModo de teste — nada foi gravado. Rode de novo com --confirmar para gravar de verdade.")
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("caminho_json")
    parser.add_argument("--banco", default=None, help="Caminho do banco SQLite de destino (default: ALPHAFITUS_DB_PATH ou o banco padrão do sistema)")
    parser.add_argument("--confirmar", action="store_true", help="Grava de verdade (sem isso, roda em modo de teste/dry-run)")
    args = parser.parse_args()

    if args.banco:
        db_path = args.banco
    else:
        import os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from app import db as db_module
        db_path = db_module.get_db_path()

    print(f"Banco de destino: {db_path}")
    importar(args.caminho_json, db_path, args.confirmar)
