import logging
import os
import socket

from flask import Flask, jsonify, send_from_directory

from .context import ApiError, close_db

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")

# Pedido do usuário: "cada modificação seja uma versão" — um número único,
# visível no rodapé do menu lateral (ver app.js), que sobe a cada fase
# entregue. MESMO número usado em `installer/AlphafitusOS.iss`
# (MyAppVersion) — assim o que aparece na tela É o que está de fato
# instalado, sem duas fontes de verdade divergentes.
VERSAO_SISTEMA = "152.0"


def create_app(test_config: dict = None) -> Flask:
    app = Flask(
        __name__,
        static_folder=os.path.join(FRONTEND_DIR, "static"),
        static_url_path="/static",
    )
    if test_config:
        app.config.update(test_config)

    @app.teardown_appcontext
    def _teardown(exception=None):
        close_db(exception)

    @app.errorhandler(ApiError)
    def _handle_api_error(err: ApiError):
        return jsonify({"erro": err.codigo, "mensagem": err.mensagem}), err.status

    @app.errorhandler(404)
    def _handle_404(err):
        return jsonify({"erro": "nao_encontrado", "mensagem": "Rota não encontrada."}), 404

    @app.errorhandler(405)
    def _handle_405(err):
        return jsonify({"erro": "metodo_nao_permitido", "mensagem": "Método HTTP não permitido para esta rota."}), 405

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        # ApiError (e suas subclasses AuthError/ForbiddenError) já são
        # tratadas por _handle_api_error acima, que o Flask despacha por
        # especificidade de classe antes de chegar aqui.
        app.logger.exception("Erro não tratado")
        return jsonify({"erro": "erro_interno", "mensagem": "Erro interno do servidor."}), 500

    from .routes import (
        auth, usuarios, perfis, permissoes, empresas, auditoria, documentos, notificacoes,
        itens, fornecedores, lotes, analises, desvios, formulas, producao, estoque, comercial, financeiro,
        relatorios, rastreabilidade, custeio, memorial, aps, memorial_catalogos,
        memorial_anexos, memorial_padronizacao, vendas_app, memorial_administracao, sistema, compras,
        cotacoes, fiscal, boletos, tipos_etapa_producao, painel_tempo_real, painel_executivo,
        solicitacoes_material, fluxo, transportadoras, tabelas_preco, clientes_documentos, terminais,
        nfe_entrada, terceirizacao, portal_terceirizacao, contratos, portal_contrato,
    )
    app.register_blueprint(auth.bp)
    app.register_blueprint(usuarios.bp)
    app.register_blueprint(perfis.bp)
    app.register_blueprint(permissoes.bp)
    app.register_blueprint(empresas.bp)
    app.register_blueprint(auditoria.bp)
    app.register_blueprint(documentos.bp)
    app.register_blueprint(notificacoes.bp)
    app.register_blueprint(itens.bp)
    app.register_blueprint(fornecedores.bp)
    app.register_blueprint(lotes.bp)
    app.register_blueprint(analises.bp)
    app.register_blueprint(desvios.bp)
    app.register_blueprint(formulas.bp)
    app.register_blueprint(producao.bp)
    app.register_blueprint(estoque.bp)
    app.register_blueprint(comercial.bp)
    app.register_blueprint(financeiro.bp)
    app.register_blueprint(relatorios.bp)
    app.register_blueprint(rastreabilidade.bp)
    app.register_blueprint(custeio.bp)
    app.register_blueprint(memorial.bp)
    app.register_blueprint(aps.bp)
    app.register_blueprint(memorial_catalogos.bp)
    app.register_blueprint(memorial_anexos.bp)
    app.register_blueprint(memorial_padronizacao.bp)
    app.register_blueprint(vendas_app.bp)
    app.register_blueprint(memorial_administracao.bp)
    app.register_blueprint(sistema.bp)
    app.register_blueprint(compras.bp)
    app.register_blueprint(cotacoes.bp)
    app.register_blueprint(fiscal.bp)
    app.register_blueprint(boletos.bp)
    app.register_blueprint(tipos_etapa_producao.bp)
    app.register_blueprint(painel_tempo_real.bp)
    app.register_blueprint(painel_executivo.bp)
    app.register_blueprint(solicitacoes_material.bp)
    app.register_blueprint(fluxo.bp)
    app.register_blueprint(transportadoras.bp)
    app.register_blueprint(tabelas_preco.bp)
    app.register_blueprint(clientes_documentos.bp)
    app.register_blueprint(terminais.bp)
    app.register_blueprint(nfe_entrada.bp)
    app.register_blueprint(terceirizacao.bp)
    app.register_blueprint(portal_terceirizacao.bp)
    app.register_blueprint(contratos.bp)
    app.register_blueprint(portal_contrato.bp)

    @app.get("/api/v1/saude")
    def saude():
        # Fase 111 — campos novos usados pela pílula de status "SERVIDOR
        # CONECTADO" no menu (ver renderShell em app.js): todo Flask que
        # responde aqui É o servidor, por definição (não existe um "modo
        # terminal" no backend — o terminal é só um navegador apontado pra
        # cá, ver installer/payload/instalar_terminal.ps1). `nome_maquina`
        # ajuda a diferenciar qual servidor físico está respondendo, útil
        # se a empresa um dia tiver mais de um ambiente.
        try:
            nome_maquina = socket.gethostname()
        except Exception:
            nome_maquina = None
        return jsonify({
            "status": "ok", "servico": "Alphafitus OS", "versao": VERSAO_SISTEMA,
            "modo": "servidor", "nome_maquina": nome_maquina,
        })

    @app.get("/")
    def frontend_index():
        return send_from_directory(FRONTEND_DIR, "index.html")

    # Fase 38 — manifest.json e o service worker precisam ser servidos a
    # partir da RAIZ do site (não de /static/), senão o navegador não os
    # aceita como válidos para instalar o app no celular/tablet: o
    # manifest também é lido a partir de "/", e o escopo padrão de um
    # service worker é o diretório de onde ele foi servido — registrado
    # como "/sw.js" (ver app.js), ele passa a cobrir o site inteiro.
    @app.get("/manifest.json")
    def frontend_manifest():
        return send_from_directory(FRONTEND_DIR, "manifest.json")

    @app.get("/sw.js")
    def frontend_service_worker():
        resposta = send_from_directory(FRONTEND_DIR, "sw.js")
        resposta.headers["Cache-Control"] = "no-cache"
        return resposta

    # Fase 136 — Terceirização Premium: portal do cliente. Página estática
    # única (o token não é usado aqui no servidor pra nada — só o
    # JavaScript da própria página o lê de `location.pathname` e chama a
    # API com ele); QUALQUER validação de verdade acontece no backend, em
    # cada chamada à API (`app/routes/portal_terceirizacao.py`). Servida
    # tanto localmente (uso interno/teste) quanto pelo túnel público em
    # whatts.alphafitus.com.br:9445 — mesmo processo Flask nos dois casos.
    @app.get("/portal/terceirizacao/<token>")
    def portal_terceirizacao_pagina(token):
        return send_from_directory(FRONTEND_DIR, "portal_terceirizacao.html")

    # Fase 147 — portal do CONTRATO (mesma receita da linha acima, mas
    # próprio de cada contrato — funciona com ou sem projeto do Monte sua
    # linha vinculado, ver app/routes/portal_contrato.py).
    @app.get("/portal/contrato/<token>")
    def portal_contrato_pagina(token):
        return send_from_directory(FRONTEND_DIR, "portal_contrato.html")

    if not app.debug:
        logging.basicConfig(level=logging.INFO)

    return app
