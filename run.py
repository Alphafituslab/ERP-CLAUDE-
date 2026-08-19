"""
Ponto de entrada para desenvolvimento/local. Em produção no Windows, use o
comando via waitress (ver README.md), não este servidor de desenvolvimento.
"""
import os

from app import create_app
from app import backup_service
from app import db as db_module

# Fase 67 — se alguém enviou um backup pela tela de Restauração desde a
# última vez que o sistema rodou, é AQUI que a troca de verdade acontece
# — sempre antes de abrir qualquer conexão de aplicação, nunca com o
# servidor já respondendo requisições (ver a nota de escopo completa em
# migrations/schema_fase67.sql e em app/db.py).
_resultado_restauracao = db_module.aplicar_restauracao_pendente_se_houver()
if _resultado_restauracao:
    print(f"Restauração de backup pendente aplicada: {_resultado_restauracao}")

if not os.path.exists(db_module.get_db_path()):
    print(f"Banco não encontrado em {db_module.get_db_path()}. Criando schema...")
    db_module.init_db()
    print("Schema criado. Rode 'python seed.py' antes do primeiro uso, se ainda não rodou.")
else:
    # Fase 67 (e qualquer fase futura com nova migration) — mesma chamada
    # de sempre, agora também depois de uma possível restauração acima:
    # o banco restaurado pode ser de uma versão mais antiga do sistema,
    # então precisa passar pelas migrations novas de qualquer forma.
    db_module.init_db()

app = create_app()

# Fase 67 — inicia o agendador de backup automático em segundo plano.
# Deliberadamente AQUI (não dentro de `create_app()`) — ver a nota de
# escopo completa no topo de app/backup_service.py: se estivesse dentro
# de `create_app()`, cada teste automatizado (que chama `create_app()`
# livremente, muitas vezes por execução) abriria uma thread agendadora
# nova, vazando threads e arriscando disparar backups de verdade durante
# a bateria de testes.
backup_service.iniciar_agendador_em_background()

if __name__ == "__main__":
    if not os.environ.get("ALPHAFITUS_JWT_SECRET"):
        raise SystemExit(
            "Defina a variável de ambiente ALPHAFITUS_JWT_SECRET antes de iniciar "
            "(ex.: export ALPHAFITUS_JWT_SECRET=$(python -c \"import secrets;print(secrets.token_hex(32))\"))"
        )
    app.run(host="127.0.0.1", port=5000, debug=False)
