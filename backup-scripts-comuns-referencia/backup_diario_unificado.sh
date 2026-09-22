#!/bin/bash
# Backup diario UNIFICADO -> MinIO: um unico arquivo .tar.gz por dia,
# contendo Memorial + Protocolo + HPLC (Postgres) + Whatts Inbox (SQLite)
# + a copia mais recente do backup do ERP (gerada pelo mecanismo proprio
# dele, so reaproveitada aqui, nao duplicada). Pedido do usuario
# (2026-09-22): "nao quero coisas separadas, quero um backup so".
#
# O ERP continua com seu PROPRIO agendador interno (nuvem + e-mail +
# Google Drive + aviso por WhatsApp) -- este script so PEGA a copia mais
# recente que ele ja gerou e inclui dentro do pacote unico, nao substitui
# nem duplica esse mecanismo.
#
# Retencao (mantem so os 2 pacotes mais recentes) em
# /opt/backup-scripts-comuns/aplicar_retencao_backups.sh, com credencial
# SEPARADA (so leitura+delete, nunca grava) -- protecao contra ransomware.
set -e
DATA=$(date +%Y-%m-%d_%H-%M-%S)
LOG_PREFIX="[backup-unificado ${DATA}]"
TMP_DIR="/tmp/backup_unificado_${DATA}"
PACOTE="/tmp/alphafitus-backup-completo_${DATA}.tar.gz"

# Pedido do usuario (2026-09-22): "se o bkp nao concluir por qualquer
# coisa deve retornar para nunca ficar bkp pela metade... sempre se
# certificar do bkp completo". Esta trap cobre QUALQUER motivo de saida
# com erro (nao so as falhas que a gente ja previu abaixo) -- limpa os
# arquivos temporarios (nunca sobe nada parcial) E avisa pelo chat interno,
# pra nunca mais repetir o caso de 2026-09-11 (agendador quebrado por 10
# dias sem ninguem perceber, so descoberto numa auditoria).
avisar_e_limpar_em_falha() {
  local codigo="$?"
  rm -rf "$TMP_DIR" "$PACOTE"
  if [ "$codigo" -ne 0 ]; then
    echo "$LOG_PREFIX FALHOU (codigo $codigo) -- nenhum pacote foi enviado." >&2
    /opt/backup-scripts-comuns/avisar_falha_backup.sh "codigo_saida_${codigo}" || true
  fi
}
trap avisar_e_limpar_em_falha EXIT

mkdir -p "$TMP_DIR"

dump_postgres() {
  local nome="$1" container="$2" usuario="$3" banco="$4"
  if ! docker exec "$container" pg_dump -U "$usuario" -Fc "$banco" > "$TMP_DIR/${nome}.dump" 2>"$TMP_DIR/${nome}.erro.log"; then
    echo "$LOG_PREFIX ERRO no pg_dump de ${nome}:" >&2
    cat "$TMP_DIR/${nome}.erro.log" >&2
    return 1
  fi
  echo "$LOG_PREFIX ${nome} (postgres) ok"
}

dump_sqlite() {
  local nome="$1" caminho_db="$2"
  if ! sqlite3 "$caminho_db" ".backup '${TMP_DIR}/${nome}.db'" 2>"$TMP_DIR/${nome}.erro.log"; then
    echo "$LOG_PREFIX ERRO no backup sqlite de ${nome}:" >&2
    cat "$TMP_DIR/${nome}.erro.log" >&2
    return 1
  fi
  echo "$LOG_PREFIX ${nome} (sqlite) ok"
}

falhas=0
dump_postgres "protocolo" alphafitus_db alphafitus alphafitus || falhas=$((falhas+1))
dump_postgres "memorial" memorial_db memorial memorial || falhas=$((falhas+1))
dump_postgres "hplc" hplc_db hplc_admin hplc_treinador || falhas=$((falhas+1))
dump_sqlite "whatts-inbox" /opt/whatts-inbox/backend/data/whatsapp.db || falhas=$((falhas+1))

# ERP: nao gera backup aqui -- pega o mais recente que o proprio
# agendador dele ja subiu pro MinIO (mesmo bucket, raiz).
ultimo_erp=$(/tmp/mc ls alphafitus/alphafitus-backups/ 2>/dev/null | grep 'Alphafitus-Backup-Completo-' | awk '{print $NF}' | sort | tail -1)
if [ -z "$ultimo_erp" ]; then
  echo "$LOG_PREFIX ERRO: nenhum backup do ERP encontrado em alphafitus-backups/ para incluir no pacote." >&2
  falhas=$((falhas+1))
else
  if /tmp/mc cp "alphafitus/alphafitus-backups/${ultimo_erp}" "$TMP_DIR/erp.db" >/dev/null; then
    echo "$LOG_PREFIX erp (copia de ${ultimo_erp}) ok"
  else
    echo "$LOG_PREFIX ERRO ao copiar backup do ERP (${ultimo_erp})." >&2
    falhas=$((falhas+1))
  fi
fi

if [ "$falhas" -gt 0 ]; then
  echo "$LOG_PREFIX terminou com $falhas falha(s) na coleta -- pacote NAO sera montado nem enviado." >&2
  exit "$falhas"
fi

rm -f "$TMP_DIR"/*.erro.log
tar -czf "$PACOTE" -C "$TMP_DIR" .
/tmp/mc cp "$PACOTE" "alphafitus/alphafitus-backups/consolidado/alphafitus-backup-completo_${DATA}.tar.gz"
echo "$LOG_PREFIX pacote unico enviado: alphafitus-backup-completo_${DATA}.tar.gz"
