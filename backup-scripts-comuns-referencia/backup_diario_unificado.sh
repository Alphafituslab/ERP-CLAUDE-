#!/bin/bash
# Backup diario UNIFICADO -> MinIO: um unico arquivo .tar.gz por dia,
# contendo Memorial + Protocolo + HPLC (Postgres) + Whatts Inbox (SQLite)
# + a copia mais recente do backup do ERP (gerada pelo mecanismo proprio
# dele, so reaproveitada aqui, nao duplicada). Pedido do usuario
# (2026-09-22): "nao quero coisas separadas, quero um backup so".
#
# Pedido do usuario, mesma data: "apos a conclusao verificar se deu tudo
# certo e, caso encontre erro, refazer o bkp" -- cada pedaco e VERIFICADO
# de verdade antes de ser aceito (pg_restore --list nos dumps, integrity_
# check no sqlite, tamanho minimo plausivel no arquivo do ERP, e o .tar.gz
# final e relido antes do envio) -- nunca so "o comando rodou sem erro".
# Se qualquer verificacao falhar, tenta a rodada INTEIRA de novo do zero
# (MAX_TENTATIVAS vezes) antes de desistir e avisar.
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
MAX_TENTATIVAS=2
LOG_BASE="[backup-unificado]"
sucesso=0
aviso_ja_enviado=0

# Rede de seguranca pra qualquer falha INESPERADA (nao prevista pelos
# `|| falhas=$((falhas+1))` abaixo) -- ex.: disco cheio no mkdir, o
# proprio `docker`/`mc` sumirem do PATH etc. Sem isso, um erro fora do
# fluxo normal sairia calado, exatamente o tipo de silencio que causou o
# caso de 2026-09-11.
avisar_se_nao_avisou() {
  if [ "$sucesso" -ne 1 ] && [ "$aviso_ja_enviado" -ne 1 ]; then
    echo "$LOG_BASE saida inesperada -- avisando por seguranca." >&2
    /opt/backup-scripts-comuns/avisar_falha_backup.sh "erro_inesperado" || true
  fi
}
trap avisar_se_nao_avisou EXIT

verificar_dump_postgres() {
  local container="$1" arquivo="$2"
  docker cp "$arquivo" "${container}:/tmp/verif_backup_unificado.dump" 2>/dev/null || return 1
  docker exec "$container" pg_restore --list /tmp/verif_backup_unificado.dump >/dev/null 2>&1
  local resultado=$?
  docker exec "$container" rm -f /tmp/verif_backup_unificado.dump 2>/dev/null || true
  return $resultado
}

verificar_sqlite() {
  local arquivo="$1" resultado
  resultado=$(sqlite3 "$arquivo" "PRAGMA integrity_check;" 2>/dev/null | head -1)
  [ "$resultado" = "ok" ]
}

tentativa=1
while [ "$tentativa" -le "$MAX_TENTATIVAS" ] && [ "$sucesso" -ne 1 ]; do
  DATA=$(date +%Y-%m-%d_%H-%M-%S)
  LOG_PREFIX="${LOG_BASE} tentativa ${tentativa}/${MAX_TENTATIVAS} ${DATA}"
  TMP_DIR="/tmp/backup_unificado_${DATA}"
  PACOTE="/tmp/alphafitus-backup-completo_${DATA}.tar.gz"
  mkdir -p "$TMP_DIR"
  falhas=0

  dump_postgres_verificado() {
    local nome="$1" container="$2" usuario="$3" banco="$4"
    if ! docker exec "$container" pg_dump -U "$usuario" -Fc "$banco" > "$TMP_DIR/${nome}.dump" 2>"$TMP_DIR/${nome}.erro.log"; then
      echo "$LOG_PREFIX ERRO no pg_dump de ${nome}:" >&2
      cat "$TMP_DIR/${nome}.erro.log" >&2
      return 1
    fi
    if ! verificar_dump_postgres "$container" "$TMP_DIR/${nome}.dump"; then
      echo "$LOG_PREFIX ERRO: dump de ${nome} gerado mas NAO passou na verificacao (pg_restore --list falhou)." >&2
      return 1
    fi
    echo "$LOG_PREFIX ${nome} (postgres) ok e verificado"
  }

  dump_sqlite_verificado() {
    local nome="$1" caminho_db="$2"
    # Achado numa auditoria de falhas (2026-09-22): se o arquivo de ORIGEM
    # nao existisse, o `sqlite3` cria um banco novo e VAZIO na hora em vez
    # de falhar -- esse banco vazio passa no integrity_check normalmente,
    # entao sem este check o script "teria sucesso" com um backup vazio.
    if [ ! -f "$caminho_db" ]; then
      echo "$LOG_PREFIX ERRO: banco de origem de ${nome} nao existe em ${caminho_db}." >&2
      return 1
    fi
    if ! sqlite3 "$caminho_db" ".backup '${TMP_DIR}/${nome}.db'" 2>"$TMP_DIR/${nome}.erro.log"; then
      echo "$LOG_PREFIX ERRO no backup sqlite de ${nome}:" >&2
      cat "$TMP_DIR/${nome}.erro.log" >&2
      return 1
    fi
    if ! verificar_sqlite "$TMP_DIR/${nome}.db"; then
      echo "$LOG_PREFIX ERRO: sqlite de ${nome} gerado mas NAO passou no integrity_check." >&2
      return 1
    fi
    # Mesmo raciocinio do arquivo do ERP: um banco valido mas absurdamente
    # pequeno (ex.: origem vazia por outro motivo) e mais suspeito que
    # tranquilizador -- 100KB e bem abaixo do tamanho real observado (~9MB).
    tamanho=$(stat -c%s "${TMP_DIR}/${nome}.db" 2>/dev/null || echo 0)
    if [ "$tamanho" -lt 102400 ]; then
      echo "$LOG_PREFIX ERRO: sqlite de ${nome} passou no integrity_check mas esta suspeito (so ${tamanho} bytes)." >&2
      return 1
    fi
    echo "$LOG_PREFIX ${nome} (sqlite) ok e verificado (${tamanho} bytes)"
  }

  dump_postgres_verificado "protocolo" alphafitus_db alphafitus alphafitus || falhas=$((falhas+1))
  dump_postgres_verificado "memorial" memorial_db memorial memorial || falhas=$((falhas+1))
  dump_postgres_verificado "hplc" hplc_db hplc_admin hplc_treinador || falhas=$((falhas+1))
  dump_sqlite_verificado "whatts-inbox" /opt/whatts-inbox/backend/data/whatsapp.db || falhas=$((falhas+1))

  # ERP: nao gera backup aqui -- pega o mais recente que o proprio
  # agendador dele ja subiu pro MinIO. Nao da pra rodar integrity_check
  # nele aqui (SQLCipher, a chave vive so no ambiente do ERP) -- o
  # tamanho minimo plausivel (bem abaixo do ~112MB tipico) e a melhor
  # verificacao possivel sem tocar na chave de criptografia.
  ultimo_erp=$(/tmp/mc ls alphafitus/alphafitus-backups/ 2>/dev/null | grep 'Alphafitus-Backup-Completo-' | awk '{print $NF}' | sort | tail -1)
  if [ -z "$ultimo_erp" ]; then
    echo "$LOG_PREFIX ERRO: nenhum backup do ERP encontrado em alphafitus-backups/." >&2
    falhas=$((falhas+1))
  elif /tmp/mc cp "alphafitus/alphafitus-backups/${ultimo_erp}" "$TMP_DIR/erp.db" >/dev/null 2>&1; then
    tamanho_erp=$(stat -c%s "$TMP_DIR/erp.db" 2>/dev/null || echo 0)
    if [ "$tamanho_erp" -lt 10000000 ]; then
      echo "$LOG_PREFIX ERRO: copia do ERP suspeita (so ${tamanho_erp} bytes, esperado dezenas de MB)." >&2
      falhas=$((falhas+1))
    else
      echo "$LOG_PREFIX erp (copia de ${ultimo_erp}, ${tamanho_erp} bytes) ok"
    fi
  else
    echo "$LOG_PREFIX ERRO ao copiar backup do ERP (${ultimo_erp})." >&2
    falhas=$((falhas+1))
  fi

  if [ "$falhas" -eq 0 ]; then
    rm -f "$TMP_DIR"/*.erro.log
    tar -czf "$PACOTE" -C "$TMP_DIR" .
    if tar -tzf "$PACOTE" >/dev/null 2>&1 && /tmp/mc cp "$PACOTE" "alphafitus/alphafitus-backups/consolidado/alphafitus-backup-completo_${DATA}.tar.gz" >/dev/null 2>&1; then
      echo "$LOG_PREFIX pacote unico enviado e verificado: alphafitus-backup-completo_${DATA}.tar.gz"
      sucesso=1
    else
      echo "$LOG_PREFIX ERRO ao montar/verificar/enviar o pacote final." >&2
    fi
  fi

  rm -rf "$TMP_DIR" "$PACOTE"

  if [ "$sucesso" -ne 1 ]; then
    echo "$LOG_PREFIX tentativa ${tentativa} falhou -- tentando de novo do zero." >&2
    tentativa=$((tentativa+1))
  fi
done

if [ "$sucesso" -ne 1 ]; then
  echo "$LOG_BASE FALHOU apos $MAX_TENTATIVAS tentativa(s) -- nenhum pacote foi enviado hoje." >&2
  /opt/backup-scripts-comuns/avisar_falha_backup.sh "${MAX_TENTATIVAS}_tentativas_esgotadas" || true
  aviso_ja_enviado=1
  exit 1
fi
