"""
Fase 123 (Parte 2) — sobe o Whatts Inbox (cópia vendorizada nesta mesma
pasta, `whatts_bundled/`, congelada a partir de
github.com/Alphafituslab/whatts-interativo-claude — o projeto original e
o site em produção `whatts.alphafitus.com.br` nunca são tocados) como um
SEGUNDO servidor HTTP, na porta 5050, dentro do MESMO processo do
AlphafitusOS — mesmo princípio de isolamento por thread já usado dentro
do próprio Whatts para o agendador/backup (`whatts_app/scheduler.py`,
`whatts_app/backup.py`): thread daemon própria, qualquer falha aqui é só
logada, NUNCA derruba o servidor principal do AlphafitusOS.

Login, banco de dados e tela de conversa continuam exatamente como no
Whatts Inbox original — é literalmente o mesmo aplicativo, só rodando
localmente também, sem SSO nem banco compartilhado com o AlphafitusOS
(evita de propósito qualquer colisão de tabela — o Whatts tem sua própria
`usuarios`, sem nenhuma relação com a do AlphafitusOS).
"""
import logging
import os
import threading


def _pasta_whatts_bundled():
    return os.path.dirname(os.path.abspath(__file__))


def _preparar_ambiente(pasta_instalacao):
    """Gera (uma única vez, na primeira execução) a chave JWT própria do
    Whatts e aponta o banco dele para dentro da MESMA pasta `data/` que o
    AlphafitusOS já usa — arquivo diferente (`whatts.db`, nunca
    `alphafitus.db`), zero colisão. Mesma ideia de
    `app_launcher.gerar_config_ambiente_se_necessario`, mas com um
    arquivo de configuração próprio — o Whatts é um módulo independente,
    não precisa da MESMA chave/segredo do AlphafitusOS."""
    caminho_config = os.path.join(pasta_instalacao, "config_whatts.bat")
    if os.path.isfile(caminho_config):
        variaveis = {}
        with open(caminho_config, "r", encoding="utf-8") as f:
            for linha in f:
                linha = linha.strip()
                if linha.lower().startswith("set "):
                    resto = linha[4:]
                    if "=" in resto:
                        chave, valor = resto.split("=", 1)
                        variaveis[chave.strip().strip('"')] = valor.strip().strip('"')
        for chave, valor in variaveis.items():
            os.environ.setdefault(chave, valor)
    else:
        import secrets

        chave = secrets.token_hex(32)
        with open(caminho_config, "w", encoding="utf-8") as f:
            f.write("@echo off\n")
            f.write("rem Gerado automaticamente pelo AlphafitusOS na primeira\n")
            f.write("rem execucao deste computador, para o modulo WhatsApp\n")
            f.write("rem (Whatts Inbox) incluso. NAO apague nem compartilhe.\n")
            f.write(f'set "WPP_JWT_SECRET={chave}"\n')
        os.environ.setdefault("WPP_JWT_SECRET", chave)

    os.environ.setdefault("WPP_DB_PATH", os.path.join(pasta_instalacao, "data", "whatts.db"))
    os.environ.setdefault("WPP_HOST", "127.0.0.1")
    os.environ.setdefault("WPP_PORT", "5050")


def _rodar_servidor():
    pasta_whatts = _pasta_whatts_bundled()
    import sys

    if pasta_whatts not in sys.path:
        sys.path.insert(0, pasta_whatts)

    from whatts_app import backup as whatts_backup
    from whatts_app import create_app as whatts_create_app
    from whatts_app import db as whatts_db_module
    from whatts_app import scheduler as whatts_scheduler

    whatts_db_module.init_db()

    import whatts_seed  # renomeado de propósito (era seed.py) para nunca colidir com o seed.py do AlphafitusOS

    whatts_seed.rodar_seed(imprimir=False)

    app_whatts = whatts_create_app()
    whatts_scheduler.iniciar_agendador_em_background()
    whatts_backup.iniciar_backup_em_background()

    import waitress

    porta = int(os.environ.get("WPP_PORT", "5050"))
    host = os.environ.get("WPP_HOST", "127.0.0.1")
    logging.info("Whatts Inbox (módulo WhatsApp incluso) iniciando em http://%s:%s", host, porta)
    waitress.serve(app_whatts, host=host, port=porta, threads=8)


def iniciar_em_thread(pasta_instalacao):
    """Prepara o ambiente e sobe o servidor numa thread daemon. Nunca
    lança exceção para quem chama — qualquer problema (dependência
    faltando, porta ocupada, erro de banco) fica só no log, e o
    AlphafitusOS continua funcionando normalmente sem o módulo WhatsApp."""
    try:
        _preparar_ambiente(pasta_instalacao)
    except Exception:
        logging.exception("Whatts Inbox (módulo WhatsApp): falha ao preparar ambiente — módulo não será iniciado")
        return False

    def _alvo():
        try:
            _rodar_servidor()
        except Exception:
            logging.exception("Whatts Inbox (módulo WhatsApp): falha ao iniciar — o restante do AlphafitusOS não foi afetado")

    threading.Thread(target=_alvo, daemon=True, name="whatts-bundled").start()
    return True
