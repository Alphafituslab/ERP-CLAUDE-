"""
Importação do HISTÓRICO de Comissão e CNAB do ERP anterior "Ema" — Fase
160, continuação da migração de dados-mestre feita em 2026-08-31 (ver
scripts/importar_ema.py e migrations/schema_fase124.sql).

Diferente daquele script, este NÃO fala com a API HTTP do Alphafitus —
grava direto no SQLite, porque as duas tabelas de destino
(comissoes_historico_ema/cnab_historico_ema) são um ARQUIVO histórico de
consulta, sem regra de negócio nenhuma pra validar (não são a tabela
`boletos` operacional, que continua exigindo conta_receber_id de verdade
pra qualquer boleto ATIVO — nunca mistura os dois).

Funil de vendas do Ema (cliente_funil/crm_funil) foi investigado e
DELIBERADAMENTE deixado de fora: a tabela de nomes de fase
(crm_funil_fase) está vazia no backup, então os registros de "mudança de
fase" não têm rótulo nenhum pra mostrar — nada de real valor pra trazer.

Como gerar os CSVs de novo, se vier um backup novo do Ema (mesmo Postgres
descartável "ema_import" já documentado em scripts/importar_ema.py):

    \\copy (
        SELECT ce.idcomissao, ce.idvendrepre, cf.razao AS nome_vendedor, ce.idcliforemp,
               ce.data, ce.valor, ce.valorentrada, ce.valorsaida, ce.numeronf, ce.descricao
        FROM comissao_extrato ce
        LEFT JOIN cliforemp cf ON cf.idcliforemp = ce.idvendrepre
        WHERE ce.excluido = 'N'
        ORDER BY ce.idcomissao
    ) TO 'comissao_extrato.csv' WITH CSV HEADER

    \\copy (
        SELECT cri.idretorno, cri.idretornoitem, cri.nossonumero, cri.documento, cri.vencimento,
               cri.valorrecebido, cri.datapagamento, cri.dataprocessamento, cri.idocorrencia,
               rb.idreceber, r.idcliforemp, r.valor AS valor_titulo
        FROM cnab_retorno_item cri
        JOIN receber_boleto rb ON rb.nossonumero = cri.nossonumero
        JOIN receber r ON r.idreceber = rb.idreceber
        ORDER BY cri.idretorno, cri.idretornoitem
    ) TO 'cnab_retorno_item.csv' WITH CSV HEADER

(o segundo já filtra pra só os itens que batem com um "nosso número"
conhecido em receber_boleto — dos 7661 itens de retorno reais, só 1060
batem; o resto é ruído de configuração/teste da época sem título real
associado, confirmado olhando os valores e datas na investigação.)
"""
import csv
import os
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from sqlcipher3 import dbapi2 as sqlite3
except ImportError:
    sys.exit("Este script precisa do pacote 'sqlcipher3-wheels' (rode dentro da venv do projeto).")

EXPORT_DIR = os.environ.get("ALPHAFITUS_IMPORT_EMA_DIR")
DB_PATH = os.environ.get("ALPHAFITUS_DB_PATH")
DB_KEY = os.environ.get("ALPHAFITUS_DB_KEY")

if not EXPORT_DIR or not os.path.isdir(EXPORT_DIR):
    sys.exit("Defina ALPHAFITUS_IMPORT_EMA_DIR apontando para a pasta com os .csv exportados.")
if not DB_PATH or not DB_KEY:
    sys.exit("Defina ALPHAFITUS_DB_PATH e ALPHAFITUS_DB_KEY (mesmo banco/chave do servidor).")


def log(msg):
    print(f"[importar_ema_comissao_cnab] {msg}")


def ler_csv(nome):
    caminho = os.path.join(EXPORT_DIR, nome)
    if not os.path.exists(caminho):
        log(f"AVISO: {nome} não encontrado em {EXPORT_DIR} — pulando esta etapa.")
        return []
    with open(caminho, encoding="utf-8", errors="replace", newline="") as f:
        return list(csv.DictReader(f))


def limpo(valor):
    if valor is None:
        return None
    valor = valor.strip()
    if valor in ("", ".", "None", "null"):
        return None
    return valor


def normalizar_nome(nome):
    """Remove acento e padroniza maiúsculas — 'Tábata' e 'TABATA HENRIQUE
    DE OLIVEIRA' precisam bater na comparação abaixo."""
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode("ascii")
    return sem_acento.strip().upper()


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(f"PRAGMA key = '{DB_KEY}'")
    conn.row_factory = sqlite3.Row

    def ja_importado(tabela, codigo_legado):
        return conn.execute(f"SELECT id FROM {tabela} WHERE codigo_legado_ema = ?", (codigo_legado,)).fetchone() is not None

    def cliente_id_por_legado(idcliforemp):
        idcliforemp = limpo(idcliforemp)
        if not idcliforemp:
            return None
        row = conn.execute("SELECT id FROM clientes WHERE codigo_legado_ema = ?", (f"ema:cliforemp:{idcliforemp}",)).fetchone()
        return row["id"] if row else None

    # ============================================================
    # 1) COMISSÃO — liga por NOME aos usuários que já existem no
    # Alphafitus hoje (confirmado com o usuário: "são os mesmos, pode
    # ligar por nome automaticamente"). Nomes no Alphafitus às vezes são
    # uma versão abreviada do nome completo do Ema (ex.: "Tabata" aqui,
    # "TÁBATA HENRIQUE DE OLIVEIRA" lá) — por isso o match tenta exato
    # primeiro e cai pra "nome do Ema começa com o nome do Alphafitus",
    # só quando isso aponta pra UM ÚNICO usuário (nunca um palpite
    # ambíguo). Quem não bater nada fica com usuario_id NULL, mas o nome
    # do Ema sempre fica gravado — nunca vira um registro sem identificação.
    # ============================================================
    usuarios_norm = [
        (normalizar_nome(row["nome"]), row["id"])
        for row in conn.execute("SELECT id, nome FROM usuarios").fetchall()
    ]

    def encontrar_usuario(nome_ema):
        nome_norm = normalizar_nome(nome_ema)
        for norm, uid in usuarios_norm:
            if norm == nome_norm:
                return uid
        candidatos = [uid for norm, uid in usuarios_norm if len(norm) >= 4 and nome_norm.startswith(norm)]
        return candidatos[0] if len(candidatos) == 1 else None

    criados = existentes = sem_usuario = 0
    for row in ler_csv("comissao_extrato.csv"):
        codigo_legado = f"ema:comissao:{row['idcomissao']}"
        if ja_importado("comissoes_historico_ema", codigo_legado):
            existentes += 1
            continue
        nome_vendedor = limpo(row.get("nome_vendedor")) or f"(vendedor Ema #{row.get('idvendrepre')})"
        usuario_id = encontrar_usuario(nome_vendedor)
        if usuario_id is None:
            sem_usuario += 1
        cliente_id = cliente_id_por_legado(row.get("idcliforemp"))
        conn.execute(
            """INSERT INTO comissoes_historico_ema
               (usuario_id, nome_vendedor_ema, cliente_id, data, valor, valor_entrada, valor_saida,
                numero_nf, descricao, codigo_legado_ema)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                usuario_id, nome_vendedor, cliente_id, row["data"], float(row["valor"] or 0),
                float(limpo(row.get("valorentrada")) or 0), float(limpo(row.get("valorsaida")) or 0),
                limpo(row.get("numeronf")), limpo(row.get("descricao")), codigo_legado,
            ),
        )
        criados += 1
    conn.commit()
    log(f"comissão: {criados} criados, {existentes} já existiam, {sem_usuario} sem usuário Alphafitus correspondente (gravados só com o nome do Ema)")

    # ============================================================
    # 2) CNAB — histórico de retorno bancário. O CSV já vem filtrado só
    # pros itens que batem com um "nosso número" conhecido; mesmo assim,
    # nem todo idreceber vai ter uma contas_receber viva (só as que
    # estavam em aberto na migração de agosto foram trazidas) — quando
    # não bate, contas_receber_id fica NULL, mas o registro histórico
    # continua sendo gravado (cliente_id/valor/data continuam reais).
    # ============================================================
    criados = existentes = sem_conta_receber = 0
    for row in ler_csv("cnab_retorno_item.csv"):
        codigo_legado = f"ema:cnab_retorno_item:{row['idretorno']}:{row['idretornoitem']}"
        if ja_importado("cnab_historico_ema", codigo_legado):
            existentes += 1
            continue
        cliente_id = cliente_id_por_legado(row.get("idcliforemp"))
        conta_receber_id = None
        idreceber = limpo(row.get("idreceber"))
        if idreceber:
            row_cr = conn.execute("SELECT id FROM contas_receber WHERE codigo_legado_ema = ?", (f"ema:receber:{idreceber}",)).fetchone()
            conta_receber_id = row_cr["id"] if row_cr else None
            if conta_receber_id is None:
                sem_conta_receber += 1
        conn.execute(
            """INSERT INTO cnab_historico_ema
               (cliente_id, contas_receber_id, nosso_numero, documento, vencimento, valor_titulo,
                valor_recebido, data_pagamento, data_processamento, codigo_ocorrencia, codigo_legado_ema)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                cliente_id, conta_receber_id, limpo(row.get("nossonumero")), limpo(row.get("documento")),
                limpo(row.get("vencimento")), float(limpo(row.get("valor_titulo")) or 0),
                float(limpo(row.get("valorrecebido")) or 0), limpo(row.get("datapagamento")),
                limpo(row.get("dataprocessamento")), limpo(row.get("idocorrencia")), codigo_legado,
            ),
        )
        criados += 1
    conn.commit()
    log(f"CNAB: {criados} criados, {existentes} já existiam, {sem_conta_receber} sem conta a receber viva correspondente (fica só como histórico de referência)")

    conn.close()


if __name__ == "__main__":
    main()
