"""
Fase 152 — Relay HTTP do Portal do Cliente (Terceirização/Contratos).

**Este arquivo roda só no VPS** (`46.202.151.252`), nunca na máquina
Windows — não faz parte do build do PyInstaller nem do instalador. Ver
`tunel_portal_service.py` pro lado Windows (o "agente" que consome este
relay) e a documentação completa da Fase 152 na memória do projeto
([[project_terceirizacao_premium]]) pro histórico de por que o antigo
túnel SSH reverso (Fase 138) foi abandonado.

Substitui, no Caddy (`whatts.alphafitus.com.br:9445`), o antigo upstream
`127.0.0.1:18500` (o túnel SSH) por `127.0.0.1:18600` (este relay) — o
bloco `@portal path /portal/* /api/v1/portal/*` do Caddyfile não muda
em nada além da porta.

Arquitetura (ver desenho completo no docstring de tunel_portal_service.py):
visitante -> Caddy -> este relay (fica "pendurado" esperando) -> agente
Windows via long-poll -> AlphafitusOS local -> volta o mesmo caminho.

Tudo em memória de processo — reiniciar este serviço derruba qualquer
pedido "em voo" (o visitante recebe timeout e recarrega a página; mesma
degradação que já existia se o túnel antigo caísse no meio de uma
requisição). Não há streaming de corpo — cada pedido/resposta é
bufferizado inteiro em memória, por isso `MAX_CONTENT_LENGTH` abaixo:
suficiente pra HTML/JSON/PDF do portal, não para uploads gigantes.
"""
import base64
import os
import secrets
import threading
import time
import uuid

from flask import Flask, Response, jsonify, request

SEGREDO_AGENTE = os.environ["PORTAL_RELAY_SEGREDO"]  # obrigatório — sem valor padrão de propósito
TIMEOUT_VISITANTE_SEGUNDOS = 25
TIMEOUT_LONGPOLL_AGENTE_SEGUNDOS = 30
MAX_CONTENT_LENGTH = 25 * 1024 * 1024  # 25 MB — HTML/JSON/PDF do portal cabem folgado

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

_lock = threading.Lock()
_fila_pendente = []  # ids na ordem de chegada, ainda sem agente atendendo
_pedidos = {}  # id -> {"metodo","path","headers","corpo_b64","evento","resposta"}

# Cabeçalhos que nunca devem ser retransmitidos (nem do visitante pro
# agente, nem da resposta do agente de volta pro visitante) — são
# calculados de novo em cada perna da retransmissão, retransmitir o
# valor antigo corromperia a resposta (`Content-Length` desatualizado
# depois do relay recodificar em JSON/base64, `Transfer-Encoding`
# `chunked` que não faz sentido aqui, `Connection` que é por-conexão).
_CABECALHOS_NUNCA_RETRANSMITIR = {"host", "content-length", "transfer-encoding", "connection"}


def _autorizado():
    return secrets.compare_digest(request.headers.get("Authorization", ""), f"Bearer {SEGREDO_AGENTE}")


@app.route("/portal/<path:subpath>", methods=["GET", "POST", "PUT", "DELETE"])
@app.route("/api/v1/portal/<path:subpath>", methods=["GET", "POST", "PUT", "DELETE"])
def handle_visitante(subpath):
    caminho = request.path + (("?" + request.query_string.decode("utf-8")) if request.query_string else "")
    pedido_id = uuid.uuid4().hex
    evento = threading.Event()
    with _lock:
        _pedidos[pedido_id] = {
            "metodo": request.method,
            "path": caminho,
            "headers": {k: v for k, v in request.headers.items() if k.lower() not in _CABECALHOS_NUNCA_RETRANSMITIR},
            "corpo_b64": base64.b64encode(request.get_data()).decode("ascii"),
            "evento": evento,
            "resposta": None,
        }
        _fila_pendente.append(pedido_id)

    recebeu_resposta = evento.wait(TIMEOUT_VISITANTE_SEGUNDOS)
    with _lock:
        pedido = _pedidos.pop(pedido_id, None)

    if not recebeu_resposta or pedido is None or pedido["resposta"] is None:
        return Response(
            "O sistema está temporariamente indisponível (nenhuma máquina conectada agora). "
            "Tente novamente em instantes.",
            status=503, mimetype="text/plain",
        )

    resposta = pedido["resposta"]
    corpo = base64.b64decode(resposta["corpo_b64"])
    cabecalhos = [(k, v) for k, v in resposta["headers"].items() if k.lower() not in _CABECALHOS_NUNCA_RETRANSMITIR]
    return Response(corpo, status=resposta["status_code"], headers=cabecalhos)


@app.get("/agente/proximo")
def agente_proximo():
    if not _autorizado():
        return jsonify({"erro": "nao_autorizado"}), 401

    prazo_final = time.time() + TIMEOUT_LONGPOLL_AGENTE_SEGUNDOS
    while time.time() < prazo_final:
        with _lock:
            if _fila_pendente:
                pedido_id = _fila_pendente.pop(0)
                pedido = _pedidos.get(pedido_id)
                if pedido is not None:
                    return jsonify({
                        "id": pedido_id, "metodo": pedido["metodo"], "path": pedido["path"],
                        "headers": pedido["headers"], "corpo_b64": pedido["corpo_b64"],
                    })
        time.sleep(0.25)
    return ("", 204)


@app.post("/agente/resposta/<pedido_id>")
def agente_resposta(pedido_id):
    if not _autorizado():
        return jsonify({"erro": "nao_autorizado"}), 401
    dados = request.get_json(force=True, silent=True) or {}
    if "status_code" not in dados or "corpo_b64" not in dados:
        return jsonify({"erro": "payload_invalido"}), 400
    with _lock:
        pedido = _pedidos.get(pedido_id)
        if pedido is None:
            return jsonify({"erro": "pedido_nao_encontrado_ou_expirado"}), 404
        pedido["resposta"] = {
            "status_code": dados["status_code"],
            "headers": dados.get("headers") or {},
            "corpo_b64": dados["corpo_b64"],
        }
        pedido["evento"].set()
    return jsonify({"ok": True})


@app.get("/agente/saude")
def agente_saude():
    with _lock:
        pendentes = len(_fila_pendente)
        em_andamento = len(_pedidos) - pendentes
    return jsonify({"status": "ok", "pedidos_na_fila": pendentes, "pedidos_em_andamento": em_andamento})


if __name__ == "__main__":
    from waitress import serve
    porta = int(os.environ.get("PORTAL_RELAY_PORTA", "18600"))
    serve(app, host="127.0.0.1", port=porta, threads=16)
