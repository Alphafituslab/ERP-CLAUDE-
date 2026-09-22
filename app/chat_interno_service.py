"""
Fase 191d — pedido do usuário: "ao invés de mandar login/senha por
WhatsApp (que depende do número aparelho estar conectado ao Evolution
API, e vive caindo), mandar pelo chat interno" — o Whatts Inbox já tem
um chat privado entre colaboradores (`chat_interno_conversas`/
`chat_interno_mensagens`, ver whatts-interativo-claude) que não depende
de WhatsApp nenhum, é 100% interno ao próprio sistema.

O Whatts Inbox de produção (`whatts-inbox.service`) é um processo
TOTALMENTE separado do AlphafitusOS — mesma VPS, banco SQLite próprio
(`whatsapp.db`, sem relação nenhuma com o `alphafitus.db` do ERP), sem
API HTTP pronta pra "mandar mensagem em nome de outro sistema". Em vez
de inventar uma rota nova só pra isso, escrevemos direto no arquivo do
banco dele — mesmo espírito (e mesma cautela) do que
`senha_sync_service._sincronizar_whatts_local` já faz pro Whatts
BUNDLED (instalação local) — só que aqui é o arquivo do banco de
PRODUÇÃO, então: (1) só faz INSERT (nunca mexe numa linha já existente,
igual ao chat_interno_service.py original), (2) nunca deixa uma falha
aqui derrubar o fluxo principal (criar usuário / resetar senha) — toda
chamada devolve (sucesso, motivo), nunca levanta exceção pra quem
chamou.

Quem manda a mensagem é sempre a conta "Assistente Seja Alpha"
(sistema@alphafitus.com.br) — o mesmo bot que já aparece na lista de
colaboradores do chat interno hoje, com o selo "só chat interno" (não é
uma pessoa de verdade, existe só pra isso).
"""
import datetime
import os
import sqlite3

EMAIL_BOT_SISTEMA = "sistema@alphafitus.com.br"


def _caminho_banco_whatts():
    return os.environ.get("ALPHAFITUS_WHATTS_INBOX_DB")


def _now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def enviar_mensagem_chat_interno(email_destinatario, texto):
    """Manda `texto` pro colaborador com este e-mail, em nome do
    "Assistente Seja Alpha", reaproveitando a conversa já existente entre
    os dois se houver (mesma regra de "1 conversa por par" do chat
    interno de verdade) ou criando uma nova.

    Devolve (True, None) em sucesso, (False, "motivo em português") em
    qualquer caso que impeça o envio — banco não configurado nesta
    instalação, colaborador sem conta no chat interno, ou qualquer erro
    inesperado de banco. NUNCA levanta exceção: quem chama (criar
    usuário / resetar senha) não pode travar por causa disto."""
    caminho = _caminho_banco_whatts()
    if not caminho or not os.path.isfile(caminho):
        return False, "Chat interno não está configurado nesta instalação."
    email_destinatario = (email_destinatario or "").strip().lower()
    if not email_destinatario:
        return False, "Este usuário não tem e-mail cadastrado."

    conn = None
    try:
        conn = sqlite3.connect(caminho, timeout=10)
        conn.row_factory = sqlite3.Row
        bot = conn.execute("SELECT id FROM usuarios WHERE email = ?", (EMAIL_BOT_SISTEMA,)).fetchone()
        if bot is None:
            return False, "Conta do Assistente Seja Alpha não foi encontrada no chat interno."
        destinatario = conn.execute(
            "SELECT id FROM usuarios WHERE email = ?", (email_destinatario,)
        ).fetchone()
        if destinatario is None:
            return False, "Este e-mail ainda não tem conta no chat interno (Whatts Inbox)."

        bot_id, destinatario_id = bot["id"], destinatario["id"]
        conversa = conn.execute(
            """
            SELECT id, criado_por_id FROM chat_interno_conversas
            WHERE (criado_por_id = ? AND participante_id = ?) OR (criado_por_id = ? AND participante_id = ?)
            ORDER BY id DESC LIMIT 1
            """,
            (bot_id, destinatario_id, destinatario_id, bot_id),
        ).fetchone()

        agora = _now_iso()
        if conversa is None:
            cur = conn.execute(
                """
                INSERT INTO chat_interno_conversas
                    (criado_por_id, participante_id, setor_destino, criado_em, nao_lidas_participante)
                VALUES (?, ?, ?, ?, 1)
                """,
                (bot_id, destinatario_id, "Sistema", agora),
            )
            conversa_id = cur.lastrowid
            remetente_id = bot_id
        else:
            conversa_id = conversa["id"]
            remetente_id = bot_id
            campo_nao_lida = "nao_lidas_participante" if bot_id == conversa["criado_por_id"] else "nao_lidas_criador"
            conn.execute(
                f"UPDATE chat_interno_conversas SET status = 'aberta', fechada_em = NULL, "
                f"{campo_nao_lida} = {campo_nao_lida} + 1 WHERE id = ?",
                (conversa_id,),
            )

        conn.execute(
            """
            INSERT INTO chat_interno_mensagens (conversa_id, usuario_id, texto, tipo, criado_em)
            VALUES (?, ?, ?, 'texto', ?)
            """,
            (conversa_id, remetente_id, texto, agora),
        )
        conn.execute(
            "UPDATE chat_interno_conversas SET ultima_mensagem_em = ?, ultima_mensagem_preview = ? WHERE id = ?",
            (agora, (texto or "")[:120], conversa_id),
        )
        conn.commit()
        return True, None
    except Exception as erro:  # nunca deixa isso derrubar o fluxo principal
        return False, f"Falha ao enviar pelo chat interno: {erro}"
    finally:
        if conn is not None:
            conn.close()
