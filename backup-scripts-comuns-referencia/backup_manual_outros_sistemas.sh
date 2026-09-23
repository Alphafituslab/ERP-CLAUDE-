#!/bin/bash
# Script PRIVILEGIADO (roda como root via sudo, chamado pelo processo do
# ERP) -- so gera e VERIFICA (restauracao real, num banco descartavel) o
# backup dos 3 sistemas Postgres + Whatts Inbox, entregando pro ERP poder
# montar o pacote unico manual. NAO aceita argumentos de proposito (regra
# de sudoers so libera esse comando exato, sem parametros -- superficie
# de ataque minima mesmo se o processo do ERP for comprometido).
#
# Pedido do usuario (2026-09-22): "os backups tem que ser impecaveis" --
# mesma verificacao real usada no backup agendado (nao so "o comando
# rodou sem erro"): cada dump Postgres e restaurado de verdade num banco
# descartavel (nunca toca no banco real) e confirmado com uma consulta;
# o Whatts Inbox passa por integrity_check + tamanho minimo. Se qualquer
# verificacao falhar, tenta a coleta INTEIRA de novo (2 tentativas) antes
# de desistir -- o ERP so mostra erro pro usuario se as duas falharem.
set -e
PASTA="/opt/alphafitus-erp/data/backup_manual"
MAX_TENTATIVAS=2
TIMEOUT_COMANDO=120
mkdir -p "$PASTA"
# Achado numa auditoria de seguranca (2026-09-23): esta pasta guarda por
# alguns segundos copias em TEXTO PURO dos bancos (antes do .tar.gz
# final). Forca 700 sempre, independente de qual dos dois lados (este
# script root, ou o processo Python do ERP) criou a pasta primeiro.
chown alphafitus-erp:alphafitus-erp "$PASTA"
chmod 700 "$PASTA"

limpar_pasta() {
  rm -f "$PASTA"/protocolo.dump "$PASTA"/memorial.dump "$PASTA"/hplc.dump "$PASTA"/whatts-inbox.db
}
# Qualquer saida com erro (inclusive um comando inesperado, nao so os
# `|| falhas=...` previstos abaixo) deixa a pasta compartilhada SEMPRE em
# um dos dois estados: vazia, ou com os 4 arquivos completos e verificados
# -- nunca uma mistura de arquivo velho + novo pela metade.
trap 'if [ "${sucesso:-0}" -ne 1 ]; then limpar_pasta; fi' EXIT

verificar_dump_postgres() {
  local container="$1" usuario="$2" arquivo="$3"
  local db_verif="verif_backup_manual_$$"
  timeout "$TIMEOUT_COMANDO" docker cp "$arquivo" "${container}:/tmp/verif_backup_manual.dump" 2>/dev/null || return 1
  if ! timeout "$TIMEOUT_COMANDO" docker exec "$container" createdb -U "$usuario" "$db_verif" 2>/dev/null; then
    docker exec "$container" rm -f /tmp/verif_backup_manual.dump 2>/dev/null || true
    return 1
  fi
  local ok=1
  if timeout "$TIMEOUT_COMANDO" docker exec "$container" pg_restore -U "$usuario" -d "$db_verif" --no-owner --no-acl /tmp/verif_backup_manual.dump >/dev/null 2>&1; then
    local total_tabelas
    total_tabelas=$(timeout "$TIMEOUT_COMANDO" docker exec "$container" psql -U "$usuario" -d "$db_verif" -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" 2>/dev/null | tr -d '[:space:]')
    if [ -n "$total_tabelas" ] && [ "$total_tabelas" -ge 5 ] 2>/dev/null; then
      ok=0
    fi
  fi
  docker exec "$container" dropdb -U "$usuario" "$db_verif" 2>/dev/null || true
  docker exec "$container" rm -f /tmp/verif_backup_manual.dump 2>/dev/null || true
  return $ok
}

verificar_sqlite() {
  local arquivo="$1" resultado
  resultado=$(sqlite3 "$arquivo" "PRAGMA integrity_check;" 2>/dev/null | head -1)
  [ "$resultado" = "ok" ]
}

sucesso=0
tentativa=1
while [ "$tentativa" -le "$MAX_TENTATIVAS" ] && [ "$sucesso" -ne 1 ]; do
  limpar_pasta
  falhas=0

  dump_postgres_verificado() {
    local nome="$1" container="$2" usuario="$3" banco="$4"
    if ! timeout "$TIMEOUT_COMANDO" docker exec "$container" pg_dump -U "$usuario" -Fc "$banco" > "$PASTA/${nome}.dump" 2>/tmp/erro_backup_manual_${nome}.log; then
      echo "ERRO no pg_dump de ${nome}:" >&2
      cat /tmp/erro_backup_manual_${nome}.log >&2
      return 1
    fi
    if ! verificar_dump_postgres "$container" "$usuario" "$PASTA/${nome}.dump"; then
      echo "ERRO: dump de ${nome} gerado mas NAO passou na verificacao (restauracao real de teste falhou)." >&2
      return 1
    fi
    echo "${nome} (postgres) ok e verificado"
  }

  dump_sqlite_verificado() {
    local nome="$1" caminho_db="$2"
    if [ ! -f "$caminho_db" ]; then
      echo "ERRO: banco de origem de ${nome} nao existe em ${caminho_db}." >&2
      return 1
    fi
    if ! timeout "$TIMEOUT_COMANDO" sqlite3 "$caminho_db" ".backup '${PASTA}/${nome}.db'" 2>/tmp/erro_backup_manual_${nome}.log; then
      echo "ERRO no backup sqlite de ${nome}:" >&2
      cat /tmp/erro_backup_manual_${nome}.log >&2
      return 1
    fi
    if ! verificar_sqlite "$PASTA/${nome}.db"; then
      echo "ERRO: sqlite de ${nome} gerado mas NAO passou no integrity_check." >&2
      return 1
    fi
    local tamanho
    tamanho=$(stat -c%s "$PASTA/${nome}.db" 2>/dev/null || echo 0)
    if [ "$tamanho" -lt 102400 ]; then
      echo "ERRO: sqlite de ${nome} passou no integrity_check mas esta suspeito (so ${tamanho} bytes)." >&2
      return 1
    fi
    echo "${nome} (sqlite) ok e verificado (${tamanho} bytes)"
  }

  dump_postgres_verificado "protocolo" alphafitus_db alphafitus alphafitus || falhas=$((falhas+1))
  dump_postgres_verificado "memorial" memorial_db memorial memorial || falhas=$((falhas+1))
  dump_postgres_verificado "hplc" hplc_db hplc_admin hplc_treinador || falhas=$((falhas+1))
  dump_sqlite_verificado "whatts-inbox" /opt/whatts-inbox/backend/data/whatsapp.db || falhas=$((falhas+1))
  rm -f /tmp/erro_backup_manual_*.log

  if [ "$falhas" -eq 0 ]; then
    sucesso=1
  else
    echo "tentativa ${tentativa}/${MAX_TENTATIVAS} falhou (${falhas} problema(s))." >&2
    tentativa=$((tentativa+1))
    [ "$tentativa" -le "$MAX_TENTATIVAS" ] && sleep 5
  fi
done

if [ "$sucesso" -ne 1 ]; then
  echo "FALHOU apos $MAX_TENTATIVAS tentativa(s)." >&2
  exit 1
fi

chown alphafitus-erp:alphafitus-erp "$PASTA"/protocolo.dump "$PASTA"/memorial.dump "$PASTA"/hplc.dump "$PASTA"/whatts-inbox.db
chmod 600 "$PASTA"/protocolo.dump "$PASTA"/memorial.dump "$PASTA"/hplc.dump "$PASTA"/whatts-inbox.db
echo "ok"
