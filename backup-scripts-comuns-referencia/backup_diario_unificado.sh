#!/bin/bash
# Backup diario UNIFICADO -> MinIO: um unico arquivo .tar.gz por dia,
# contendo Memorial + Protocolo + HPLC (Postgres) + Whatts Inbox (SQLite)
# + a copia mais recente do backup do ERP (gerada pelo mecanismo proprio
# dele, so reaproveitada aqui, nao duplicada). Pedido do usuario
# (2026-09-22): "nao quero coisas separadas, quero um backup so" e depois
# "seja ousado, verifique ainda mais fundo -- os backups tem que ser
# impecaveis".
#
# Cada peca e VERIFICADA de verdade antes de ser aceita (pg_restore
# --list nos dumps, integrity_check + tamanho no sqlite, tamanho +
# ATUALIDADE no arquivo do ERP, .tar.gz relido antes do envio) -- nunca
# so "o comando rodou sem erro". Qualquer falha refaz a rodada INTEIRA do
# zero (MAX_TENTATIVAS vezes) antes de desistir e avisar pelo chat interno.
# Lock (flock) impede duas execucoes simultaneas, e `timeout` em todo
# comando externo impede um travamento virar um cron preso pra sempre.
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

# Achado numa auditoria mais funda (2026-09-22): o trap de aviso so
# ficava ativo DEPOIS da trava (lock) abaixo -- se a propria trava
# falhasse (ex.: disco cheio, /tmp sem espaco), essa falha sairia
# TOTALMENTE silenciosa, sem aviso nenhum (exatamente o tipo de silencio
# do caso de 2026-09-11). Estas variaveis e o trap agora sao a
# PRIMEIRISSIMA coisa que roda, antes de qualquer comando que possa falhar.
MAX_TENTATIVAS=2
TIMEOUT_COMANDO=120
LOG_BASE="[backup-unificado]"
sucesso=0
aviso_ja_enviado=0

avisar_se_nao_avisou() {
  if [ "$sucesso" -ne 1 ] && [ "$aviso_ja_enviado" -ne 1 ]; then
    echo "$LOG_BASE saida inesperada -- avisando por seguranca." >&2
    /opt/backup-scripts-comuns/avisar_falha_backup.sh "erro_inesperado" || true
  fi
}
trap avisar_se_nao_avisou EXIT

# Pedido do usuario (2026-09-22): o backup do ERP roda no MESMO horario
# (3h) que este script. Sem lock, uma segunda execucao manual (ou um cron
# atrasado por sobrecarga) rodaria por cima da primeira, dobrando a carga
# nos bancos de producao à toa. `flock` com `-n` (nao bloqueia, so
# desiste na hora) garante isso sem risco de duas instancias travadas
# esperando uma a outra.
LOCKFILE="/tmp/.backup_diario_unificado.lock"
exec 200>"$LOCKFILE"
if ! flock -n 200; then
  echo "$LOG_BASE ja existe uma execucao em andamento -- desistindo desta (evita rodar em dobro)." >&2
  sucesso=1
  aviso_ja_enviado=1
  exit 0
fi

# Verificacao REAL (2026-09-22, pedido do usuario: "os backups tem que
# ser impecaveis, nao podemos ter erro se por acaso for preciso usar").
# `pg_restore --list` (versao anterior desta funcao) so prova que o
# CABECALHO do arquivo e legivel -- um dump pode ter cabecalho valido e
# paginas de dados corrompidas por baixo, e --list nunca chegaria a ler
# essas paginas. A unica prova de verdade e restaurar pra valer, num
# banco DESCARTAVEL dentro do mesmo container (nunca toca no banco real),
# e confirmar com uma consulta que o schema restaurado tem uma quantidade
# plausivel de tabelas (>=5 -- bem abaixo do real, ~28-31, so pra pegar
# um restore vazio/quebrado sem falso-positivo por evolucao de schema).
verificar_dump_postgres() {
  local container="$1" usuario="$2" arquivo="$3"
  local db_verif="verif_backup_$$"
  timeout "$TIMEOUT_COMANDO" docker cp "$arquivo" "${container}:/tmp/verif_backup_unificado.dump" 2>/dev/null || return 1
  if ! timeout "$TIMEOUT_COMANDO" docker exec "$container" createdb -U "$usuario" "$db_verif" 2>/dev/null; then
    docker exec "$container" rm -f /tmp/verif_backup_unificado.dump 2>/dev/null || true
    return 1
  fi
  local ok=1
  if timeout "$TIMEOUT_COMANDO" docker exec "$container" pg_restore -U "$usuario" -d "$db_verif" --no-owner --no-acl /tmp/verif_backup_unificado.dump >/dev/null 2>&1; then
    local total_tabelas
    total_tabelas=$(timeout "$TIMEOUT_COMANDO" docker exec "$container" psql -U "$usuario" -d "$db_verif" -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" 2>/dev/null | tr -d '[:space:]')
    if [ -n "$total_tabelas" ] && [ "$total_tabelas" -ge 5 ] 2>/dev/null; then
      ok=0
    fi
  fi
  # Limpeza sempre roda, sucesso ou falha -- nunca deixa banco de
  # verificacao para tras no Postgres de producao.
  docker exec "$container" dropdb -U "$usuario" "$db_verif" 2>/dev/null || true
  docker exec "$container" rm -f /tmp/verif_backup_unificado.dump 2>/dev/null || true
  return $ok
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
    if ! timeout "$TIMEOUT_COMANDO" docker exec "$container" pg_dump -U "$usuario" -Fc "$banco" > "$TMP_DIR/${nome}.dump" 2>"$TMP_DIR/${nome}.erro.log"; then
      echo "$LOG_PREFIX ERRO no pg_dump de ${nome}:" >&2
      cat "$TMP_DIR/${nome}.erro.log" >&2
      return 1
    fi
    if ! verificar_dump_postgres "$container" "$usuario" "$TMP_DIR/${nome}.dump"; then
      echo "$LOG_PREFIX ERRO: dump de ${nome} gerado mas NAO passou na verificacao (restauracao real de teste falhou)." >&2
      return 1
    fi
    echo "$LOG_PREFIX ${nome} (postgres) ok e verificado"
  }

  dump_sqlite_verificado() {
    local nome="$1" caminho_db="$2"
    if [ ! -f "$caminho_db" ]; then
      echo "$LOG_PREFIX ERRO: banco de origem de ${nome} nao existe em ${caminho_db}." >&2
      return 1
    fi
    if ! timeout "$TIMEOUT_COMANDO" sqlite3 "$caminho_db" ".backup '${TMP_DIR}/${nome}.db'" 2>"$TMP_DIR/${nome}.erro.log"; then
      echo "$LOG_PREFIX ERRO no backup sqlite de ${nome}:" >&2
      cat "$TMP_DIR/${nome}.erro.log" >&2
      return 1
    fi
    if ! verificar_sqlite "$TMP_DIR/${nome}.db"; then
      echo "$LOG_PREFIX ERRO: sqlite de ${nome} gerado mas NAO passou no integrity_check." >&2
      return 1
    fi
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
  # agendador dele ja subiu pro MinIO. Alem de tamanho plausivel, checa
  # ATUALIDADE: como o ERP roda seu proprio backup no MESMO horario deste
  # script (3h), se ele demorar mais que o normal um dia, sem este check
  # eu pegaria silenciosamente o backup de ONTEM -- passaria em todas as
  # outras verificacoes (arquivo valido, tamanho certo) sem denunciar que
  # esta desatualizado. So aceita um backup do ERP gerado nas ultimas 6h.
  ultimo_erp=$(timeout 30 /tmp/mc ls alphafitus/alphafitus-backups/ 2>/dev/null | grep 'Alphafitus-Backup-Completo-' | awk '{print $NF}' | sort | tail -1)
  if [ -z "$ultimo_erp" ]; then
    echo "$LOG_PREFIX ERRO: nenhum backup do ERP encontrado em alphafitus-backups/." >&2
    falhas=$((falhas+1))
  else
    # Extrai o timestamp do nome (ex.: Alphafitus-Backup-Completo-2026-09-22T03-00-39.091Z.db)
    # e compara com agora -- em segundos, via `date -d`.
    ts_arquivo=$(echo "$ultimo_erp" | grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}-[0-9]{2}-[0-9]{2}' | sed -E 's/T([0-9]{2})-([0-9]{2})-([0-9]{2})/T\1:\2:\3/')
    idade_segundos=999999
    if [ -n "$ts_arquivo" ]; then
      # Achado numa auditoria mais funda (2026-09-22): o timestamp no nome
      # do arquivo e gerado em UTC (o "Z" original do .toISOString() do
      # Node) -- SEM o "Z" explicito aqui, `date -d` interpretaria a
      # string como horario LOCAL do servidor. Hoje o servidor esta em UTC
      # (coincidencia, nao garantia), entao funcionava; se o fuso do
      # servidor mudar um dia, essa conta ficaria silenciosamente errada.
      # Forcar "Z" deixa isto correto em qualquer fuso do servidor.
      epoch_arquivo=$(date -d "${ts_arquivo}Z" +%s 2>/dev/null || echo 0)
      epoch_agora=$(date +%s)
      if [ "$epoch_arquivo" -gt 0 ]; then
        idade_segundos=$((epoch_agora - epoch_arquivo))
      fi
    fi
    if [ "$idade_segundos" -gt 21600 ]; then
      echo "$LOG_PREFIX ERRO: backup do ERP mais recente (${ultimo_erp}) tem mais de 6h -- provavelmente desatualizado (agendador do ERP pode ter falhado hoje)." >&2
      falhas=$((falhas+1))
    elif timeout "$TIMEOUT_COMANDO" /tmp/mc cp "alphafitus/alphafitus-backups/${ultimo_erp}" "$TMP_DIR/erp.db" >/dev/null 2>&1; then
      tamanho_erp=$(stat -c%s "$TMP_DIR/erp.db" 2>/dev/null || echo 0)
      if [ "$tamanho_erp" -lt 10000000 ]; then
        echo "$LOG_PREFIX ERRO: copia do ERP suspeita (so ${tamanho_erp} bytes, esperado dezenas de MB)." >&2
        falhas=$((falhas+1))
      else
        echo "$LOG_PREFIX erp (copia de ${ultimo_erp}, ${tamanho_erp} bytes, idade ${idade_segundos}s) ok"
      fi
    else
      echo "$LOG_PREFIX ERRO ao copiar backup do ERP (${ultimo_erp})." >&2
      falhas=$((falhas+1))
    fi
  fi

  if [ "$falhas" -eq 0 ]; then
    rm -f "$TMP_DIR"/*.erro.log
    if tar -czf "$PACOTE" -C "$TMP_DIR" . && tar -tzf "$PACOTE" >/dev/null 2>&1 && timeout "$TIMEOUT_COMANDO" /tmp/mc cp "$PACOTE" "alphafitus/alphafitus-backups/consolidado/alphafitus-backup-completo_${DATA}.tar.gz" >/dev/null 2>&1; then
      echo "$LOG_PREFIX pacote unico enviado e verificado: alphafitus-backup-completo_${DATA}.tar.gz"
      sucesso=1
    else
      echo "$LOG_PREFIX ERRO ao montar/verificar/enviar o pacote final." >&2
    fi
  fi

  rm -rf "$TMP_DIR" "$PACOTE"

  if [ "$sucesso" -ne 1 ]; then
    tentativa=$((tentativa+1))
    if [ "$tentativa" -le "$MAX_TENTATIVAS" ]; then
      # Pausa real entre tentativas (nao so instantanea) -- o motivo mais
      # comum de falha por "atualidade" e o backup do ERP (mesmo horario
      # deste script) ainda estar rodando; sem esperar de verdade, os
      # retries aconteceriam rapido demais pra fazer diferenca.
      echo "$LOG_PREFIX tentativa falhou -- aguardando 60s antes de tentar de novo." >&2
      sleep 60
    else
      echo "$LOG_PREFIX tentativa falhou -- sem mais tentativas." >&2
    fi
  fi
done

if [ "$sucesso" -ne 1 ]; then
  echo "$LOG_BASE FALHOU apos $MAX_TENTATIVAS tentativa(s) -- nenhum pacote foi enviado hoje." >&2
  /opt/backup-scripts-comuns/avisar_falha_backup.sh "${MAX_TENTATIVAS}_tentativas_esgotadas" || true
  aviso_ja_enviado=1
  exit 1
fi
