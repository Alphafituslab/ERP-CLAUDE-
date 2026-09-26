"""
Fase 222 — pedido do usuário: o envio de Orçamento por WhatsApp estava
pegando cegamente `clientes.telefone` (um campo genérico de cadastro, sem
garantia nenhuma de ser um número de WhatsApp de verdade) e mandando direto
pra Evolution API — achado real em produção: o número "554935553003" (uma
linha fixa, sem o 9) voltou `{"exists": false}` e o envio falhou. Em vez
disso, buscar/gravar num contato de WhatsApp de verdade, igual a pessoa já
escolhe manualmente dentro do próprio Whatts Inbox.

Mesmo padrão de acesso cruzado já usado em `chat_interno_service.py`
(Fase 191d): o Whatts Inbox é um processo TOTALMENTE separado (Node/
Express, `whatts-inbox.service`), com o próprio banco SQLite
(`ALPHAFITUS_WHATTS_INBOX_DB`), sem API HTTP própria pra isso — em vez de
inventar uma rota nova nele, lemos/gravamos direto no arquivo do banco.
Nunca mexe numa linha alheia por engano: leitura é só SELECT, gravação é
upsert (INSERT ou, se já existir esse telefone, atualiza só o nome).

`EMPRESA_ID_PADRAO = 1` — confirmado por consulta direta ao banco de
produção (2026-09-26): a tabela `empresas` do Whatts Inbox tem só 2 linhas,
id=1 "Empresa padrão" (2032 contatos reais, incluindo o número do próprio
Clayton) e id=2 "Empresa Teste Isolamento" (vazia/teste) — nunca assumido,
verificado antes de escrever este código (regra de máxima fidelidade).
"""
import datetime
import os
import sqlite3

from .backup_service import normalizar_numero_brasileiro

EMPRESA_ID_PADRAO = 1


def _caminho_banco_whatts():
    return os.environ.get("ALPHAFITUS_WHATTS_INBOX_DB")


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def buscar_contatos(termo, limite=8):
    """Devolve até `limite` contatos (não-grupo) cujo nome ou telefone
    contém `termo` (case-insensitive). Lista vazia se o banco não está
    configurado nesta instalação ou não há nenhum contato — nunca levanta
    exceção, igual `chat_interno_service`."""
    caminho = _caminho_banco_whatts()
    if not caminho or not os.path.isfile(caminho) or not (termo or "").strip():
        return []
    termo_like = f"%{termo.strip()}%"
    conn = None
    try:
        conn = sqlite3.connect(caminho, timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT telefone, nome FROM whatsapp_contatos
            WHERE empresa_id = ? AND eh_grupo = 0
              AND (nome LIKE ? COLLATE NOCASE OR telefone LIKE ?)
            ORDER BY nome IS NULL, nome
            LIMIT ?
            """,
            (EMPRESA_ID_PADRAO, termo_like, termo_like, limite),
        ).fetchall()
        return [{"telefone": r["telefone"], "nome": r["nome"]} for r in rows]
    except Exception:
        return []
    finally:
        if conn:
            conn.close()


def salvar_contato(nome, telefone):
    """Upsert por (empresa_id, telefone) — nunca duplica um contato que já
    existe, só atualiza o nome se um novo foi informado. Devolve
    (True, telefone_normalizado) em sucesso, (False, motivo) em qualquer
    falha (banco não configurado, telefone vazio etc.) — nunca levanta
    exceção pra quem chama (o envio do orçamento não pode travar por causa
    disto)."""
    caminho = _caminho_banco_whatts()
    if not caminho or not os.path.isfile(caminho):
        return False, "WhatsApp (Whatts Inbox) não está configurado nesta instalação."
    numero = normalizar_numero_brasileiro(telefone)
    if not numero:
        return False, "Telefone inválido."
    nome = (nome or "").strip() or None
    agora = _now_iso()
    conn = None
    try:
        conn = sqlite3.connect(caminho, timeout=10)
        existente = conn.execute(
            "SELECT id FROM whatsapp_contatos WHERE empresa_id = ? AND telefone = ?",
            (EMPRESA_ID_PADRAO, numero),
        ).fetchone()
        if existente:
            if nome:
                conn.execute(
                    "UPDATE whatsapp_contatos SET nome = ?, nome_editado = 1, atualizado_em = ? WHERE id = ?",
                    (nome, agora, existente[0]),
                )
        else:
            conn.execute(
                """
                INSERT INTO whatsapp_contatos (empresa_id, telefone, nome, criado_em, atualizado_em, nome_editado)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (EMPRESA_ID_PADRAO, numero, nome, agora, agora, 1 if nome else 0),
            )
        conn.commit()
        return True, numero
    except Exception as exc:
        return False, f"Não foi possível salvar o contato: {exc}"
    finally:
        if conn:
            conn.close()
