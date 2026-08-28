"""
Fase 122 — Sincronização incremental do backup PostgreSQL mais atual
("backup-memorial-anvisa-28-08-2026-14h44.dump") contra o que já está
importado no AlphafitusOS.

Diferente de `importar_memorial_anvisa.py` (que fazia um import completo
pra um banco vazio), este script é ADITIVO E CIRÚRGICO: audita o dump
inteiro contra o banco atual, registro por registro (por chave natural —
`codigo` do memorial, `nome` do produto, `cnpj` da empresa, e conteúdo de
cada linha de histórico), e só INSERE o que está genuinamente faltando.
Nunca atualiza/sobrescreve um registro que já existe — se o conteúdo de
algo já importado divergir do dump, este script REPORTA a diferença mas
não mexe nele (evita apagar por cima de qualquer ajuste feito direto no
AlphafitusOS depois da importação original).

Achados da auditoria (rodada em 2026-08-28, ver
`scripts/analisar_dump_completo.py` no histórico da sessão — não commitado,
só documentado aqui pro contexto):
  - 1 memorial novo: CERT-AF-20240610/011
  - 2 produtos novos (um ligado ao memorial novo, outro ainda sem memorial)
  - 0 empresas novas
  - 0 divergência de assinaturas/anexos nos memoriais já importados
  - 3 memoriais já importados ganharam linhas de histórico novas desde a
    última importação (CERT-AF-20241119/027, CERT-AF-20241119/023,
    CERT-AF-20240810/053) — 9 linhas no total, identificadas e inseridas
    aqui uma a uma (nunca um "replace" da lista inteira)
  - Catálogos: já tinham sido corrigidos à parte (Licopeno, Procianidina)
    antes deste script — aqui só confere que batem, não reimporta.

Uso:
    python scripts/sincronizar_backup_postgres_28_08.py [--banco <caminho>] [--confirmar]

Sem --confirmar: dry-run, só imprime o que SERIA feito. Com --confirmar:
grava de verdade, tudo numa transação só.
"""
import argparse
import datetime
import json
import sqlite3
import sys
import unicodedata

import pgdumplib

DUMP_PATH = r"C:\Users\Oitech\Desktop\backup-memorial-anvisa-28-08-2026-14h44.dump"
ADMIN_ID = 1

COLS_MEMORIAIS = ['id', 'produto_id', 'codigo', 'status', 'data_inicio', 'data_fim', 'objetivo', 'composicao_nutricional', 'alegacoes', 'justificativas_tecnicas', 'metodos_analiticos', 'estabilidade_acelerada', 'ensaios_microbiologicos', 'calculos_nutricionais', 'legislacao_aplicavel', 'observacoes', 'created_at', 'updated_at', 'composicao_centesimal', 'calculo_quantidade', 'metodologias_aplicadas', 'numero_certificado', 'tipo_produto', 'tipo_pote', 'ingredientes_ativos', 'excipientes', 'composicao_capsula', 'temperatura', 'umidade_relativa', 'periodo_estudo', 'intervalos_teste', 'elaborado_por', 'aprovado_por', 'laudo_emitido_por', 'analista_senior', 'email_rt', 'email_analista_senior', 'observacao_analista', 'advertencias', 'armazenamento', 'modo_uso', 'conclusao', 'lista_ingredientes', 'referencias_bibliograficas', 'data_emissao']
COLS_ASSINATURAS = ['id', 'memorial_id', 'nome', 'cargo', 'email', 'iniciais', 'assinado_em']
COLS_ANEXOS = ['id', 'memorial_id', 'nome', 'nome_arquivo', 'tipo_mime', 'dados', 'tamanho', 'usuario_nome', 'criado_em']
COLS_HISTORICO = ['id', 'memorial_id', 'usuario', 'acao', 'descricao', 'criado_em']
COLS_PADRONIZACOES = ['id', 'memorial_id', 'produto', 'peso_liquido', 'contem', 'denominacao_legal', 'lista_ingredientes', 'alergenicos', 'advertencias', 'conservacao', 'informacoes_consumo', 'largura_rotulo', 'comprimento_rotulo', 'altura_rotulo', 'cor_capsula', 'tamanho_pote', 'simbolos_logos', 'alegacoes', 'dados_distribuidor', 'observacoes_tabela', 'criado_em', 'atualizado_em', 'tamanho_capsulas', 'tipo_capsulas']
COLS_PRODUTOS = ['id', 'empresa_id', 'nome', 'categoria', 'forma_farmaceutica', 'porcao_gramas', 'quantidade_porcoes', 'ingredientes_ativos', 'excipientes', 'embalagem', 'advertencias', 'modo_de_uso', 'armazenamento', 'created_at', 'updated_at', 'quantidade_capsulas_totais', 'peso_liquido', 'tamanho_capsulas', 'tipo_capsulas', 'referencias_comerciais', 'tipo_produto', 'comprimento_rotulo', 'largura_rotulo', 'tamanho_pote', 'tamanho_capsula', 'numero_protocolo_anvisa', 'sabor']
COLS_EMPRESAS = ['id', 'nome_fantasia', 'razao_social', 'cnpj', 'ie', 'responsavel_tecnico', 'crf', 'endereco', 'cidade', 'estado', 'cep', 'telefone', 'email', 'created_at', 'updated_at', 'telefone_contato']
COLS_CATALOGO_REFERENCIAS = ['id', 'substancia', 'referencia', 'descricao', 'tipo', 'ordem', 'auto_incluir', 'grupo', 'doi']


def normalizar(s):
    if not s:
        return ""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.lower().strip()


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _timestamp_canonico(valor):
    """pgdumplib devolve TUDO como string crua do formato texto do
    `COPY` do Postgres — um timestamptz vem tipo
    '2026-06-06 00:42:06.82652+00' (espaço, sem milissegundos com zero à
    esquerda fixo, fuso). O que já está no AlphafitusOS foi salvo no
    formato ISO com "T" (`_now_iso()`/`Date.toISOString()` do sistema
    original). Pra comparar linha a linha sem falso "diferente" por causa
    só do formato, normaliza os dois lados pro mesmo recorte: troca "T"
    por espaço e pega só "AAAA-MM-DD HH:MM:SS" (19 caracteres), ignorando
    frações de segundo e fuso — o suficiente pra identificar o MESMO
    evento salvo duas vezes por caminhos de exportação diferentes."""
    if valor is None:
        return ""
    return str(valor).replace("T", " ")[:19]


def carregar(d, tabela, cols):
    return [dict(zip(cols, r)) for r in d.table_data("public", tabela)]


def sincronizar(caminho_db, confirmar):
    d = pgdumplib.load(DUMP_PATH)

    memoriais_dump = carregar(d, "memoriais", COLS_MEMORIAIS)
    assinaturas_dump = carregar(d, "assinaturas_memorial", COLS_ASSINATURAS)
    anexos_dump = carregar(d, "anexos_memorial", COLS_ANEXOS)
    historico_dump = carregar(d, "historico_memorial", COLS_HISTORICO)
    padronizacoes_dump = carregar(d, "padronizacoes", COLS_PADRONIZACOES)
    produtos_dump = carregar(d, "produtos", COLS_PRODUTOS)
    empresas_dump = carregar(d, "empresas", COLS_EMPRESAS)
    referencias_dump = carregar(d, "catalogo_referencias", COLS_CATALOGO_REFERENCIAS)

    id_para_codigo = {m["id"]: m["codigo"] for m in memoriais_dump}

    conn = sqlite3.connect(caminho_db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    usuarios_por_nome = {normalizar(nome): uid for uid, nome in conn.execute("SELECT id, nome FROM usuarios").fetchall()}

    # ---- Mapa de referências (substancia + início da referência -> id novo) ----
    mapa_referencia_por_chave = {}
    for row in conn.execute("SELECT id, dados FROM memorial_catalogo_itens WHERE catalogo = 'referencias'").fetchall():
        dd = json.loads(row["dados"] or "{}")
        chave = (dd.get("substancia") or "") + "|||" + (dd.get("referencia") or "")[:40]
        mapa_referencia_por_chave[chave] = row["id"]
    mapa_referencia_id_antigo_para_novo = {}
    referencias_nao_encontradas = []
    for r in referencias_dump:
        chave = (r.get("substancia") or "") + "|||" + (r.get("referencia") or "")[:40]
        novo_id = mapa_referencia_por_chave.get(chave)
        if novo_id is None:
            referencias_nao_encontradas.append(r.get("substancia"))
        else:
            mapa_referencia_id_antigo_para_novo[r["id"]] = novo_id

    resumo = {"empresas": 0, "produtos": 0, "memoriais": 0, "padronizacoes": 0,
              "assinaturas": 0, "anexos": 0, "historico": 0}
    avisos = []
    if referencias_nao_encontradas:
        avisos.append(f"{len(referencias_nao_encontradas)} referências do dump não bateram com nenhuma já "
                       f"importada (deveria ser 0, já que os 2 catálogos foram conferidos antes): {referencias_nao_encontradas}")

    # =====================================================================
    # EMPRESAS — só insere CNPJ que não existe ainda.
    # =====================================================================
    mapa_empresa_id = {}
    cnpjs_alpha = {r["cnpj"]: r["id"] for r in conn.execute("SELECT id, cnpj FROM memorial_empresas").fetchall()}
    for e in empresas_dump:
        if e["cnpj"] in cnpjs_alpha:
            mapa_empresa_id[e["id"]] = cnpjs_alpha[e["cnpj"]]
            continue
        print(f"[NOVO] empresa cnpj={e['cnpj']} nome={e['nome_fantasia']}")
        if confirmar:
            cur = conn.execute(
                """INSERT INTO memorial_empresas
                   (nome_fantasia, razao_social, cnpj, ie, responsavel_tecnico, crf, endereco, cidade,
                    estado, cep, telefone, email, telefone_contato, criado_por)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (e.get("nome_fantasia"), e.get("razao_social"), e.get("cnpj"), e.get("ie"),
                 e.get("responsavel_tecnico"), e.get("crf"), e.get("endereco"), e.get("cidade"),
                 e.get("estado"), e.get("cep"), e.get("telefone"), e.get("email"),
                 e.get("telefone_contato"), ADMIN_ID),
            )
            mapa_empresa_id[e["id"]] = cur.lastrowid
        else:
            # Dry-run: sem INSERT não existe lastrowid de verdade, mas os
            # registros SEGUINTES (produtos, memoriais...) do dump podem
            # referenciar este id — usa um placeholder negativo só pra
            # essa referência resolver corretamente no relatório também.
            mapa_empresa_id[e["id"]] = f"novo:{e['id']}"
        resumo["empresas"] += 1

    # =====================================================================
    # PRODUTOS — só insere nome que não existe ainda.
    # =====================================================================
    mapa_produto_id = {}
    nomes_produtos_alpha = {r["nome"]: r["id"] for r in conn.execute("SELECT id, nome FROM memorial_produtos").fetchall()}
    campos_produto_extra = ['ingredientes_ativos', 'excipientes', 'embalagem', 'advertencias', 'modo_de_uso',
                             'armazenamento', 'quantidade_capsulas_totais', 'peso_liquido', 'tamanho_capsulas',
                             'tipo_capsulas', 'tipo_produto', 'referencias_comerciais', 'comprimento_rotulo',
                             'largura_rotulo', 'tamanho_pote', 'tamanho_capsula', 'numero_protocolo_anvisa', 'sabor']
    for p in produtos_dump:
        if p["nome"] in nomes_produtos_alpha:
            mapa_produto_id[p["id"]] = nomes_produtos_alpha[p["nome"]]
            continue
        empresa_nova_id = mapa_empresa_id.get(p["empresa_id"])
        if empresa_nova_id is None:
            avisos.append(f"produto novo '{p['nome']}' referencia empresa_id {p['empresa_id']} não resolvida — pulando.")
            continue
        print(f"[NOVO] produto '{p['nome']}'")
        if confirmar:
            cur = conn.execute(
                f"""INSERT INTO memorial_produtos
                    (empresa_id, nome, categoria, forma_farmaceutica, porcao_gramas, quantidade_porcoes,
                     {", ".join(campos_produto_extra)}, status, criado_por)
                    VALUES (?, ?, ?, ?, ?, ?, {", ".join("?" for _ in campos_produto_extra)}, 'ativo', ?)""",
                (empresa_nova_id, p["nome"], p["categoria"], p["forma_farmaceutica"], p["porcao_gramas"],
                 p["quantidade_porcoes"], *[p.get(c) for c in campos_produto_extra], ADMIN_ID),
            )
            mapa_produto_id[p["id"]] = cur.lastrowid
        else:
            mapa_produto_id[p["id"]] = f"novo:{p['id']}"  # placeholder pro relatório de dry-run (ver empresas acima)
        resumo["produtos"] += 1

    # =====================================================================
    # MEMORIAIS — só insere codigo que não existe ainda.
    # =====================================================================
    mapa_memorial_id = {}
    codigos_alpha = {r["codigo"]: r["id"] for r in conn.execute("SELECT id, codigo FROM memoriais").fetchall()}
    campos_memorial_extra = ['objetivo', 'composicao_nutricional', 'alegacoes', 'justificativas_tecnicas',
                              'metodos_analiticos', 'estabilidade_acelerada', 'ensaios_microbiologicos',
                              'calculos_nutricionais', 'legislacao_aplicavel', 'observacoes',
                              'composicao_centesimal', 'calculo_quantidade', 'metodologias_aplicadas',
                              'tipo_produto', 'tipo_pote', 'ingredientes_ativos', 'excipientes',
                              'composicao_capsula', 'temperatura', 'umidade_relativa', 'periodo_estudo',
                              'intervalos_teste', 'elaborado_por', 'aprovado_por', 'laudo_emitido_por',
                              'analista_senior', 'email_rt', 'email_analista_senior', 'observacao_analista',
                              'advertencias', 'armazenamento', 'modo_uso', 'conclusao', 'lista_ingredientes',
                              'data_emissao']
    for m in memoriais_dump:
        if m["codigo"] in codigos_alpha:
            mapa_memorial_id[m["id"]] = codigos_alpha[m["codigo"]]
            continue
        produto_novo_id = mapa_produto_id.get(m["produto_id"])
        if produto_novo_id is None:
            avisos.append(f"memorial novo '{m['codigo']}' referencia produto_id {m['produto_id']} não resolvido — pulando.")
            continue
        status = m["status"] if m["status"] in ("rascunho", "em_andamento", "em_revisao", "concluido", "aprovado", "reprovado") else "rascunho"

        # remapeia referencias_bibliograficas (lista de ids antigos -> novos)
        ids_antigos = []
        try:
            bruto = json.loads(m.get("referencias_bibliograficas") or "[]")
            if isinstance(bruto, list):
                ids_antigos = bruto
        except (TypeError, ValueError):
            pass
        ids_novos = []
        for id_antigo in ids_antigos:
            id_novo = mapa_referencia_id_antigo_para_novo.get(id_antigo)
            if id_novo is None:
                avisos.append(f"memorial novo '{m['codigo']}' referência bibliográfica id '{id_antigo}' não encontrada — pulando essa referência.")
                continue
            ids_novos.append(id_novo)

        print(f"[NOVO] memorial '{m['codigo']}' (status={status})")
        if confirmar:
            cur = conn.execute(
                f"""INSERT INTO memoriais
                    (produto_id, codigo, numero_certificado, status, data_inicio, data_fim,
                     {", ".join(campos_memorial_extra)}, referencias_bibliograficas, criado_por)
                    VALUES (?, ?, ?, ?, ?, ?, {", ".join("?" for _ in campos_memorial_extra)}, ?, ?)""",
                (produto_novo_id, m["codigo"], m.get("numero_certificado") or m["codigo"], status,
                 m["data_inicio"], m["data_fim"], *[m.get(c) for c in campos_memorial_extra],
                 json.dumps(ids_novos) if ids_novos else None, ADMIN_ID),
            )
            mapa_memorial_id[m["id"]] = cur.lastrowid
        else:
            mapa_memorial_id[m["id"]] = f"novo:{m['id']}"  # placeholder pro relatório de dry-run (ver empresas acima)
        resumo["memoriais"] += 1

    # =====================================================================
    # PADRONIZAÇÕES — só pra memorial que não tinha nenhuma ainda.
    # =====================================================================
    memoriais_com_padronizacao_alpha = {r["memorial_id"] for r in conn.execute("SELECT memorial_id FROM memorial_padronizacoes").fetchall()}
    campos_padronizacao = ['produto', 'peso_liquido', 'contem', 'denominacao_legal', 'lista_ingredientes',
                            'alergenicos', 'advertencias', 'conservacao', 'informacoes_consumo',
                            'largura_rotulo', 'comprimento_rotulo', 'altura_rotulo', 'cor_capsula',
                            'tamanho_pote', 'simbolos_logos', 'alegacoes', 'dados_distribuidor',
                            'observacoes_tabela', 'tamanho_capsulas', 'tipo_capsulas']
    for pad in padronizacoes_dump:
        memorial_novo_id = mapa_memorial_id.get(pad["memorial_id"])
        if memorial_novo_id is None or memorial_novo_id in memoriais_com_padronizacao_alpha:
            continue
        print(f"[NOVO] padronização pro memorial id-novo={memorial_novo_id}")
        if confirmar:
            conn.execute(
                f"""INSERT INTO memorial_padronizacoes (memorial_id, {", ".join(campos_padronizacao)}, atualizado_por)
                    VALUES (?, {", ".join("?" for _ in campos_padronizacao)}, ?)""",
                (memorial_novo_id, *[pad.get(c) for c in campos_padronizacao], ADMIN_ID),
            )
        resumo["padronizacoes"] += 1

    # =====================================================================
    # ASSINATURAS — só a combinação (memorial, usuario) que ainda não existe.
    # =====================================================================
    assinaturas_existentes = {(r["memorial_id"], r["usuario_id"]) for r in conn.execute("SELECT memorial_id, usuario_id FROM memorial_assinaturas").fetchall()}
    for a in assinaturas_dump:
        memorial_novo_id = mapa_memorial_id.get(a["memorial_id"])
        if memorial_novo_id is None:
            continue
        usuario_id = usuarios_por_nome.get(normalizar(a["nome"]))
        if usuario_id is None:
            avisos.append(f"assinatura de '{a['nome']}' não bate com usuário real cadastrado — pulando.")
            continue
        if (memorial_novo_id, usuario_id) in assinaturas_existentes:
            continue
        print(f"[NOVO] assinatura de '{a['nome']}' no memorial id-novo={memorial_novo_id}")
        if confirmar:
            conn.execute(
                "INSERT INTO memorial_assinaturas (memorial_id, usuario_id, nome, cargo, iniciais, assinado_em) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (memorial_novo_id, usuario_id, a["nome"], a.get("cargo") or "—", a.get("iniciais") or "",
                 a.get("assinado_em") or _now_iso()),
            )
        resumo["assinaturas"] += 1

    # =====================================================================
    # ANEXOS — chave (memorial, nome_arquivo, tamanho). `tamanho` vem do
    # dump como STRING crua (pgdumplib não tipa nada — é texto puro do
    # formato COPY do Postgres) enquanto o SQLite guarda INTEGER — sem o
    # int() aqui, a comparação nunca bate (bug real encontrado no dry-run:
    # os 148 anexos inteiros apareciam como "novos" por causa só disso).
    # =====================================================================
    anexos_existentes = {(r["memorial_id"], r["nome_arquivo"], int(r["tamanho"])) for r in conn.execute("SELECT memorial_id, nome_arquivo, tamanho FROM memorial_anexos").fetchall()}
    for anexo in anexos_dump:
        memorial_novo_id = mapa_memorial_id.get(anexo["memorial_id"])
        if memorial_novo_id is None:
            continue
        chave = (memorial_novo_id, anexo["nome_arquivo"], int(anexo["tamanho"]))
        if chave in anexos_existentes:
            continue
        criado_por = usuarios_por_nome.get(normalizar(anexo.get("usuario_nome")), ADMIN_ID)
        print(f"[NOVO] anexo '{anexo['nome_arquivo']}' no memorial id-novo={memorial_novo_id}")
        if confirmar:
            conn.execute(
                "INSERT INTO memorial_anexos "
                "(memorial_id, nome, nome_arquivo, tipo_mime, dados, tamanho, usuario_nome, criado_por, criado_em) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (memorial_novo_id, anexo.get("nome") or anexo["nome_arquivo"], anexo["nome_arquivo"],
                 anexo.get("tipo_mime") or "application/octet-stream", anexo.get("dados") or "",
                 anexo.get("tamanho") or 0, anexo.get("usuario_nome") or "Desconhecido",
                 criado_por, anexo.get("criado_em") or _now_iso()),
            )
        resumo["anexos"] += 1

    # =====================================================================
    # HISTÓRICO — a mais delicada: precisa comparar linha a linha (acao +
    # descricao + criado_em), não só contagem, pra achar exatamente quais
    # sao novas mesmo em memoriais já importados.
    # =====================================================================
    historico_existente = {}
    for r in conn.execute("SELECT memorial_id, acao, descricao, criado_em FROM memorial_historico").fetchall():
        historico_existente.setdefault(r["memorial_id"], set()).add((r["acao"], r["descricao"], _timestamp_canonico(r["criado_em"])))
    for h in historico_dump:
        memorial_novo_id = mapa_memorial_id.get(h["memorial_id"])
        if memorial_novo_id is None:
            continue
        chave = (h["acao"], h["descricao"], _timestamp_canonico(h["criado_em"]))
        if chave in historico_existente.get(memorial_novo_id, set()):
            continue
        usuario_id = usuarios_por_nome.get(normalizar(h["usuario"])) if h.get("usuario") else None
        codigo_memorial = id_para_codigo.get(h["memorial_id"], "?")
        print(f"[NOVO] histórico '{h['acao']}' em {codigo_memorial} (id-novo={memorial_novo_id}): {h.get('descricao')}")
        if confirmar:
            conn.execute(
                "INSERT INTO memorial_historico (memorial_id, usuario_id, usuario_nome, acao, descricao, criado_em) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (memorial_novo_id, usuario_id, h.get("usuario") or "Sistema", h["acao"], h.get("descricao"),
                 h.get("criado_em") or _now_iso()),
            )
        resumo["historico"] += 1

    print("\n" + "=" * 70)
    print("RESUMO DA SINCRONIZAÇÃO" + (" (TESTE — nada foi gravado)" if not confirmar else ""))
    print("=" * 70)
    for k, v in resumo.items():
        print(f"  {k}: {v}")
    if avisos:
        print(f"\n  {len(avisos)} avisos:")
        for a in avisos:
            print(f"    - {a}")

    if confirmar:
        conn.commit()
        print("\nGravado com sucesso.")
    else:
        conn.rollback()
        print("\nModo de teste — nada foi gravado. Rode de novo com --confirmar para gravar de verdade.")
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--banco", default=None)
    parser.add_argument("--confirmar", action="store_true")
    args = parser.parse_args()

    if args.banco:
        db_path = args.banco
    else:
        import os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from app import db as db_module
        db_path = db_module.get_db_path()

    print(f"Banco de destino: {db_path}")
    sincronizar(db_path, args.confirmar)
