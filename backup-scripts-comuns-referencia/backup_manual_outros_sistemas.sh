#!/bin/bash
# Script PRIVILEGIADO (roda como root via sudo, chamado pelo processo do
# ERP) -- so gera o backup dos 3 sistemas Postgres + Whatts Inbox e
# entrega pro ERP poder montar o pacote unico manual. NAO aceita
# argumentos de proposito (regra de sudoers so libera esse comando exato,
# sem parametros -- superficie de ataque minima mesmo se o processo do
# ERP for comprometido).
#
# Pedido do usuario (2026-09-22): o botao "Salvar backup" do ERP deve
# baixar UM SO arquivo contendo Memorial+Protocolo+HPLC+Whatts+ERP direto
# no computador de quem clicou. O ERP nao tem (e nao deve ter) acesso ao
# Docker/aos dados dos outros sistemas por si so -- so este script, bem
# restrito, tem essa permissao.
set -e
PASTA="/opt/alphafitus-erp/data/backup_manual"
mkdir -p "$PASTA"

# Achado numa auditoria de falhas (2026-09-22): se um pg_dump falhasse no
# meio (ex.: container fora do ar), os arquivos dos sistemas que JA tinham
# terminado ficavam orfaos nesta pasta compartilhada, com dono ainda ROOT
# (o chown so acontece no fim) -- a proxima tentativa do botao encontraria
# um arquivo antigo/parcial que o processo do ERP nem consegue ler (dono
# errado), quebrando o proximo backup tambem. Este trap garante que uma
# falha em QUALQUER passo apaga os 4 arquivos antes de sair, deixando a
# pasta sempre em um dos dois estados: vazia, ou com os 4 completos.
limpar_em_falha() {
  rm -f "$PASTA"/protocolo.dump "$PASTA"/memorial.dump "$PASTA"/hplc.dump "$PASTA"/whatts-inbox.db
}
trap limpar_em_falha ERR

docker exec alphafitus_db pg_dump -U alphafitus -Fc alphafitus > "$PASTA/protocolo.dump"
docker exec memorial_db pg_dump -U memorial -Fc memorial > "$PASTA/memorial.dump"
docker exec hplc_db pg_dump -U hplc_admin -Fc hplc_treinador > "$PASTA/hplc.dump"
sqlite3 /opt/whatts-inbox/backend/data/whatsapp.db ".backup '${PASTA}/whatts-inbox.db'"

chown alphafitus-erp:alphafitus-erp "$PASTA"/protocolo.dump "$PASTA"/memorial.dump "$PASTA"/hplc.dump "$PASTA"/whatts-inbox.db
chmod 600 "$PASTA"/protocolo.dump "$PASTA"/memorial.dump "$PASTA"/hplc.dump "$PASTA"/whatts-inbox.db
trap - ERR
echo "ok"
