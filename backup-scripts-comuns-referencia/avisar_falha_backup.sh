#!/bin/bash
# Avisa pelo chat interno quando o backup diario unificado falha.
# Pedido do usuario (2026-09-22): nunca mais repetir o caso de 2026-09-11,
# em que o agendador de backup do ERP ficou 10 dias quebrado sem ninguem
# perceber -- uma falha SILENCIOSA (so num log que ninguem olha) e tao
# ruim quanto nao ter backup nenhum. Roda direto (root, mesmo usuario do
# cron), sem depender do processo do ERP estar de pe.
FALHAS="${1:-desconhecido}"
DESTINATARIO="claytonborges@alphafitus.com.br"
cd /opt/alphafitus-erp/backend || exit 0
set -a
source /opt/alphafitus-erp/config_ambiente.env
set +a
venv/bin/python -c "
import sys
sys.path.insert(0, '.')
from app import create_app
app = create_app()
with app.app_context():
    from app.chat_interno_service import enviar_mensagem_chat_interno
    texto = '⚠️ Backup automático diário FALHOU (${FALHAS} sistema(s) com erro). Nenhum pacote foi enviado hoje — ver /var/log/backup_unificado.log na VPS.'
    ok, erro = enviar_mensagem_chat_interno('${DESTINATARIO}', texto)
    print('aviso_enviado=' + str(ok) + ' erro=' + str(erro))
" 2>&1
