#!/bin/bash
# Retenção dos backups no MinIO — pedido do usuário (2026-09-11): manter só
# os N mais recentes de cada sistema a cada backup novo, apagar o resto,
# pra não encher o armazenamento (bucket/disco da VPS).
#
# Usa o alias `mc` "alphafitus-cleanup", uma credencial SEPARADA e DEDICADA
# só a isto (policy "alphafitus-cleanup": ListBucket + DeleteObject, nada
# mais) — de propósito NUNCA a mesma credencial que os scripts de backup e
# o próprio ERP usam pra ENVIAR (essa continua só com PutObject/GetObject/
# ListBucket, policy "alphafitus-backup-restrita"). É proteção deliberada
# contra ransomware: mesmo que o servidor ou a aplicação seja comprometida,
# quem só tem a credencial de ESCRITA de backup não consegue apagar
# backups já existentes. Rodar esta limpeza com uma credencial separada,
# só usada aqui, preserva essa garantia.
set -e
MANTER=2

# $1 = prefixo completo (com barra no fim); $2 = filtro grep opcional nos
# nomes de arquivo (por padrão, tudo dentro do prefixo).
aplicar_retencao() {
  local prefixo="$1"
  local filtro="${2:-.}"
  local arquivos total apagar nome

  arquivos=$(/tmp/mc ls "alphafitus-cleanup/${prefixo}" 2>/dev/null | awk '{print $NF}' | grep -E "$filtro" | sort || true)
  total=$(echo "$arquivos" | grep -c . || true)
  if [ "$total" -le "$MANTER" ]; then
    echo "[$prefixo] $total arquivo(s) — dentro do limite ($MANTER), nada a apagar."
    return
  fi

  apagar=$(echo "$arquivos" | head -n "$((total - MANTER))")
  while IFS= read -r nome; do
    [ -z "$nome" ] && continue
    /tmp/mc rm "alphafitus-cleanup/${prefixo}${nome}"
    echo "[$prefixo] removido: $nome"
  done <<< "$apagar"
}

aplicar_retencao "alphafitus-backups/consolidado/"
# Backups do ERP ficam na raiz do bucket (sem prefixo) — filtro pelo nome
# pra nunca tocar em `alphafitus_PRE_SQLCIPHER_backup.db` (arquivo único,
# histórico, não faz parte da rotina diária) nem nas pastas dos outros
# sistemas.
aplicar_retencao "alphafitus-backups/" "^Alphafitus-Backup-Completo-"
