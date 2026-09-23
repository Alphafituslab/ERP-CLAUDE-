import os

import waitress

from app import create_app
from app import backup_service
from app import db as db_module

# Mesma sequência de run.py (nunca rodava aqui — achado numa auditoria de
# proteção de dados pedida pelo usuário em 2026-09-11: o agendador de
# backup automático estava configurado como "ativo" na tela, mas como esta
# era a entrada real usada em produção desde a migração pra VPS
# (Fase 157b), ele NUNCA tinha sido iniciado de fato — 10 dias sem nenhum
# backup automático do ERP, sem erro nenhum visível em lugar nenhum).
_resultado_restauracao = db_module.aplicar_restauracao_pendente_se_houver()
if _resultado_restauracao:
    print(f"Restauração de backup pendente aplicada: {_resultado_restauracao}")

if not os.path.exists(db_module.get_db_path()):
    print(f"Banco não encontrado em {db_module.get_db_path()}. Criando schema...")
    db_module.init_db()
else:
    db_module.init_db()

app = create_app()

backup_service.iniciar_agendador_em_background()

waitress.serve(app, host="127.0.0.1", port=5010, threads=8)
