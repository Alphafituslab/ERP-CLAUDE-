"""
Conexão e utilitários de banco de dados.

Usa SQLite no ambiente de desenvolvimento/testes (disponível sem instalação
extra neste ambiente). O schema (migrations/*.sql) foi escrito para ser
facilmente portado para PostgreSQL na instalação de produção — ver README.md
seção "Migrando para PostgreSQL".

As migrations são aplicadas em ordem e de forma incremental: cada arquivo
representa uma fase do projeto (schema.sql = Fase 1, schema_fase2.sql =
Fase 2, e assim por diante) e uma tabela de controle `_migrations` registra
o que já foi aplicado, para que atualizar para uma fase nova NUNCA apague
ou recrie o que já existe — só adiciona o que é novo.
"""
import os
import sqlite3
from contextlib import contextmanager

# Fase 123 — pedido do usuário: banco criptografado de verdade (SQLCipher),
# não só um arquivo .db comum. `sqlcipher3-wheels` é um fork do módulo
# `sqlite3` da própria biblioteca padrão com suporte a `PRAGMA key` — API
# idêntica (mesmo `Row`, mesmo `PARSE_DECLTYPES`), então o resto do
# sistema inteiro (que sempre passou por `_connect()`, nunca abriu o
# arquivo por fora) não precisou mudar uma linha sequer. Import como
# `sqlite3` mesmo (apelidado) de propósito: todo o resto do arquivo (e
# de app/context.py, que reaproveita esta função) já usa `sqlite3.Row`/
# `sqlite3.PARSE_DECLTYPES` etc. — trocar o nome do módulo aqui, sem
# tocar nos usos, é o que mantém a mudança contida numa função só.
from sqlcipher3 import dbapi2 as sqlite3  # noqa: F811 (troca intencional do sqlite3 padrão)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "data", "alphafitus.db")
MIGRATIONS_DIR = os.path.join(BASE_DIR, "migrations")

# Ordem de aplicação. Adicione o arquivo da próxima fase ao FINAL desta
# lista — nunca reordene ou remova entradas antigas, ou bancos já
# existentes vão tentar reaplicar migrations já feitas.
SCHEMA_FILES = [
    "schema.sql",         # Fase 1 — Fundação
    "schema_fase2.sql",   # Fase 2 — Qualidade e Laboratório
    "schema_fase3.sql",   # Fase 3 — Produção / PCP / MES básico
    "schema_fase4.sql",   # Fase 4 — Estoque / WMS básico
    "schema_fase5.sql",   # Fase 5 — Comercial / CRM básico + Pedidos de Venda
    "schema_fase6.sql",   # Fase 6 — Financeiro básico (Contas a Receber e a Pagar)
    # (Fase 7 — Painel Gerencial/BI não tem arquivo de schema: é 100%
    # agregação sobre tabelas que já existem, sem nenhuma tabela nova.)
    "schema_fase8.sql",   # Fase 8 — Rastreabilidade avançada / simulação de recall
    "schema_fase9.sql",   # Fase 9 — Apontamento de perdas/refugo na produção
    # (Fase 10 — CoA em PDF e Fase 11 — Relatório de Recall em PDF não têm
    # arquivo de schema: são 100% export/leitura sobre tabelas já
    # existentes.)
    "schema_fase12.sql",  # Fase 12 — Reserva de material ao liberar ordem + disponibilidade real compartilhada
    "schema_fase13.sql",  # Fase 13 — Custeio de produção (custo real + custo das perdas, via custo médio de compra)
    "schema_fase14.sql",  # Fase 14 — Estorno de baixa (Contas a Receber e a Pagar)
    # (Fase 15 — Fluxo de Caixa Projetado e Fase 16 — Bloqueio em Massa por
    # Recall não têm arquivo de schema: são 100% agregação/ação sobre
    # tabelas que já existem, sem nenhuma tabela nova.)
    "schema_fase17.sql",  # Fase 17 — Contagem de Inventário Cíclico/Geral
    # (Fases 18, 19 e 20 — exportação do Painel Gerencial em PDF/CSV e o
    # DRE Simplificado — não têm arquivo de schema: são 100%
    # agregação/export sobre tabelas que já existem, sem nenhuma tabela
    # nova.)
    "schema_fase21.sql",  # Fase 21 — Aprovação de 2º usuário para ajuste de contagem com divergência grande
    "schema_fase22.sql",  # Fase 22 — Aprovação dupla para estorno de baixa acima de um valor de alçada
    # (Fase 23 — Geração Automática de Código de Item não tem arquivo de
    # schema: reaproveita a coluna "codigo" já UNIQUE desde a Fase 2.)
    "schema_fase24.sql",  # Fase 24 — Memorial Técnico ANVISA (fundação: empresas, produtos, memoriais, assinaturas, histórico)
    "schema_fase25.sql",  # Fase 25 — APS: centros de trabalho + agendamento de ordem de produção com capacidade finita
    "schema_fase26.sql",  # Fase 26 — Catálogos do Memorial Técnico ANVISA (Metodologias, Nutrientes, Legislações, Alegações, Tipos de Produto, Advertências, Armazenamento, Modo de Uso, Justificativas, Referências)
    "schema_fase27.sql",  # Fase 27 — Memorial Técnico ANVISA: Anexos de arquivo e Padronização de Rótulo
    # (Fase 28 — APS: Agenda Visual/Gantt e Fase 29 — Memorial Técnico:
    # Catálogos como Seletores não têm arquivo de schema: são 100%
    # frontend sobre rotas/tabelas que já existem, sem nenhuma tabela ou
    # coluna nova.)
    "schema_fase30.sql",  # Fase 30 — Custo de Mão de Obra e Overhead na Produção
    "schema_fase31.sql",  # Fase 31 — Aprovação Dupla para o Registro de Baixa Acima do Valor de Alçada
    "schema_fase32.sql",  # Fase 32 — Limiar de Divergência de Contagem Configurável pela Tela
    "schema_fase33.sql",  # Fase 33 — Limite de Prazo para Estorno de Baixa Configurável pela Tela
    "schema_fase34.sql",  # Fase 34 — Alçada por Valor Monetário do Ajuste de Contagem
    "schema_fase35.sql",  # Fase 35 — Agendamento/Cadência Automática de Contagens Cíclicas
    "schema_fase36.sql",  # Fase 36 — App de Vendas: Rascunho com Reserva Temporária, Verbas Comerciais e Comissão
    "schema_fase37.sql",  # Fase 37 — Notificações do Sistema com Envio Real por E-mail
    "schema_fase40.sql",  # Fase 40 — Conciliação Bancária (Importação de Extrato OFX)
    "schema_fase41.sql",  # Fase 41 — DRE Completo (Despesas Operacionais + Impostos sobre Vendas)
    # (Fase 42 — Painel Gerencial: Filtro por Período e Fase 43 — Memorial
    # Técnico: Exportar "PDF Completo" não têm arquivo de schema: são 100%
    # agregação/export sobre tabelas que já existem, sem nenhuma tabela ou
    # coluna nova.)
    "schema_fase44.sql",  # Fase 44 — Memorial Técnico ANVISA: Administração — Usuários Online
    # (Fase 45 — Painel Gerencial: Exportar em XLSX, Fase 46 — Memorial
    # Técnico: Snapshots & Restauração, Fase 47 — Backups do Sistema e
    # Fase 48 — Gerenciar Usuários não têm arquivo de schema próprio: são
    # 100% export/leitura bruta de tabelas já existentes (45, 46, 47) ou
    # 100% frontend reaproveitando a tela central de Usuários (48), sem
    # nenhuma tabela ou coluna nova.)
    "schema_fase49.sql",  # Fase 49 — Memorial Técnico ANVISA: Administração — Configurações
    "schema_fase50.sql",  # Fase 50 — Apontamento de Perda/Refugo por Etapa do Processo
    # Fase 51 — Menu Lateral Agrupado por Módulo não tem arquivo de schema
    # próprio: é 100% frontend (app.js/styles.css), nenhuma tabela ou
    # coluna nova.
    "schema_fase52.sql",  # Fase 52 — Painel Gerencial: Filtro por Empresa
    "schema_fase53.sql",  # Fase 53 — Recall: Decisão sobre Pedidos Já Expedidos
    "schema_fase54.sql",  # Fase 54 — MRP: Sugestão Automática de Compra
    "schema_fase55.sql",  # Fase 55 — Conciliação Bancária: Lote + Janela Configurável
    "schema_fase56.sql",  # Fase 56 — DRE: Impostos Detalhados (PIS/COFINS/ICMS/ISS)
    "schema_fase57.sql",  # Fase 57 — MRP: Lead Time de Compra do Fornecedor
    "schema_fase58.sql",  # Fase 58 — Pedido de Compra formal
    "schema_fase59.sql",  # Fase 59 — Conta a Pagar gerada a partir do Pedido de Compra
    "schema_fase60.sql",  # Fase 60 — Pedido de Compra: Alerta de Atraso (Lead Time do Fornecedor)
    "schema_fase61.sql",  # Fase 61 — Alçada por Valor no Envio do Pedido de Compra
    # (Fase 62 — Desempenho de Fornecedor / Scorecard não tem arquivo de
    # schema: é 100% agregação sobre tabelas que já existem, sem nenhuma
    # tabela ou coluna nova.)
    "schema_fase63.sql",  # Fase 63 — Limite de Crédito do Cliente (Alçada na Confirmação do Pedido de Venda)
    # (Fase 64 — Desempenho de Cliente / Scorecard não tem arquivo de
    # schema: é 100% agregação sobre tabelas que já existem, sem nenhuma
    # tabela ou coluna nova.)
    # (Fase 65 — Bloqueio de Lote Vencido na Alocação FEFO não tem arquivo
    # de schema: reaproveita a coluna `lotes.validade` já existente desde a
    # Fase 2 — só filtra e sinaliza, sem nenhuma tabela ou coluna nova.)
    "schema_fase66.sql",  # Fase 66 — Cotação Comparativa de Fornecedores (RFQ) antes do Pedido de Compra
    "schema_fase67.sql",  # Fase 67 — Backup Automático Agendado, Envio para Nuvem/E-mail, Restauração
    # (Fase 68 — Servidor e Terminais (Instalação Real, Serviço do Windows)
    # não tem arquivo de schema: é infraestrutura de instalação/rede, sem
    # nenhuma tabela ou coluna nova.)
    "schema_fase69.sql",  # Fase 69 — Painel Gerencial: Série Histórica / Tendência
    "schema_fase70.sql",  # Fase 70 — Fiscal: Emissão de NF-e (provedor terceirizado)
    "schema_fase71.sql",  # Fase 71 — Financeiro: Emissão de Boleto Bancário (provedor terceirizado)
    "schema_fase72.sql",  # Fase 72 — Auditoria de Segurança: índices únicos contra condições de corrida (NF-e/boleto)
    "schema_fase73.sql",  # Fase 73 — Auditoria de Segurança (continuação): triggers contra corrida na reserva FEFO (vendas/produção)
    "schema_fase75.sql",  # Fase 75 — Etapas de Processo Configuráveis (Pesagem, Tempo de Mistura) + Painel de Chão de Fábrica em Tempo Real
    # (Fase 76 — Painel Executivo não tem arquivo de schema: reaproveita
    # tabelas e permissões já existentes, sem nenhuma tabela ou coluna nova.)
    "schema_fase77.sql",  # Fase 77 — Portfólio dinâmico no App de Vendas + Duplicar Pedido (Comercial e App de Vendas)
    "schema_fase78.sql",  # Fase 78 — SPED Fiscal (1/5): Notas Fiscais de Entrada (captura estruturada)
    "schema_fase79.sql",  # Fase 79 — SPED Fiscal (2/5): Configuração Fiscal (parâmetros de apuração)
    "schema_fase80.sql",  # Fase 80 — Solicitações de Materiais/EPI (pedido → aprovação → entrega → confirmação)
    "schema_fase81.sql",  # Fase 81 — Catálogo de Fluxo Configurável (multi-entidade), base do Painel Kanban
    "schema_fase83.sql",  # Fase 83 — Aprovação Financeira obrigatória em todo Pedido de Venda
    "schema_fase84.sql",  # Fase 84 — Granel intermediário como etapa + Centro de Trabalho por etapa + Apontamento Diário
    "schema_fase85.sql",  # Fase 85 — Liberação do lote condicionada à NF-e de Entrada (configurável)
    "schema_fase86.sql",  # Fase 86 — Transportadora / Coleta (MVP)
    "schema_fase92.sql",  # Fase 92 — 2FA obrigatório por perfil (Administrador e Financeiro por padrão)
    "schema_fase95.sql",  # Fase 95 — 2FA: confiar neste dispositivo por 24h (não repetir o código em todo login)
    "schema_fase99.sql",  # Fase 99 — Tabelas de Preço (pré-preenchimento de preço no Pedido de Venda, por cliente)
    "schema_fase100.sql",  # Fase 100 — Catálogo de Fluxo: setor (perfil) responsável por cada etapa, opcional
    "schema_fase101.sql",  # Fase 101 — Consulta de CNPJ ao cadastrar cliente (clientes.email)
    "schema_fase102.sql",  # Fase 102 — Aprovação Financeira de Cadastro de Cliente (clientes já existentes ficam aprovados)
    "schema_fase103.sql",  # Fase 103 — Documentos do Cliente (obrigatório ao cadastrar pelo App de Vendas em campo)
    "schema_fase105.sql",  # Fase 105 — APS como módulo de permissão próprio (separado de "producao")
    "schema_fase111.sql",  # Fase 111 — Arquitetura Servidor + Terminais: registro de terminais conectados
    "schema_fase113.sql",  # Fase 113 — Foto de perfil do operador (usuarios.foto_perfil)
    "schema_fase114.sql",  # Fase 114 — Portfólio com fotos (itens.imagem) + forma_pagamento no App de Vendas
    "schema_fase115.sql",  # Fase 115 — Memorial Técnico: campos/catálogos faltando (paridade com sistema antigo)
    "schema_fase123.sql",  # Fase 123 — Recebimento e Importação de NF-e: unidades/conversão, vínculo fornecedor-produto, notas_fiscais_entrada
    "schema_fase124.sql",  # Fase 124 — Importação Ema: campos faltando em clientes/fornecedores/itens/lotes/contas + codigo_legado_ema
    "schema_fase125.sql",  # Fase 125 — Importação Ema: contas_receber ganha lançamento avulso (pedido_venda_id agora opcional) + descricao
    "schema_fase126.sql",  # Fase 126 — Boleto: substitui Asaas por CNAB 240 direto (Sicredi/Unicred)
    "schema_fase127.sql",  # Fase 127 — Catálogo de métodos e condições de pagamento (cliente padrão + pedido de venda)
    "schema_fase128.sql",  # Fase 128 — tabela_preco_condicoes: cada tabela de preço configura seus próprios método+prazo
    "schema_fase130.sql",  # Fase 130 — Backup: destinos Local, Google Drive e aviso por WhatsApp
    "schema_fase131.sql",  # Fase 131 — Pedidos de Venda: tela própria com filtros + tipo_pedido (terceirização/marca própria)
    "schema_fase132.sql",  # Fase 132 — Pedidos de Venda: canal_origem (comercial/app_vendas) + backfill de vendedor_id
    "schema_fase134.sql",  # Fase 134 — Terceirização Premium (Fase A): catálogo de embalagem, projetos, briefings, arquivos
    "schema_fase135.sql",  # Fase 135 — Terceirização Premium (Fase B): aprovação interna multi-departamento
    "schema_fase136.sql",  # Fase 136 — Terceirização Premium (Fase C): link seguro + portal do cliente
    "schema_fase137.sql",  # Fase 137 — Terceirização Premium: ajustes (nome do Memorial, reordenação, prévia + confirmação do cliente)
    "schema_fase139.sql",  # Fase 139 — Terceirização Premium: ficha cadastral (dados fiscais do cliente + quem assina/condição comercial por projeto)
]


def get_db_path():
    return os.environ.get("ALPHAFITUS_DB_PATH", DEFAULT_DB_PATH)


def _obter_chave_criptografia():
    """A chave mora em `ALPHAFITUS_DB_KEY` (mesmo arquivo config_ambiente.bat
    que já guarda ALPHAFITUS_JWT_SECRET) — nunca no código. `PRAGMA key`
    não aceita parâmetro vinculado (`?`) como uma query normal, então o
    valor entra por f-string; a checagem abaixo (só letras/dígitos) existe
    exatamente pra isso nunca virar uma injeção via um valor manual
    esquisito colocado na variável de ambiente."""
    chave = os.environ.get("ALPHAFITUS_DB_KEY")
    if not chave:
        raise RuntimeError(
            "ALPHAFITUS_DB_KEY não configurada — obrigatória desde que o banco passou a ser "
            "criptografado (SQLCipher, Fase 123). Defina em config_ambiente.bat a mesma chave "
            "usada na migração do banco."
        )
    if not chave.isalnum():
        raise RuntimeError("ALPHAFITUS_DB_KEY só pode conter letras e números (restrição de segurança).")
    return chave


def _connect(db_path=None):
    path = db_path or get_db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.execute(f"PRAGMA key = '{_obter_chave_criptografia()}'")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _garantir_tabela_migrations(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS _migrations (
            arquivo     TEXT PRIMARY KEY,
            aplicado_em TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        )
        """
    )
    conn.commit()


def aplicar_migrations(db_path=None):
    """Aplica todas as migrations de SCHEMA_FILES que ainda não constam em
    `_migrations`, na ordem da lista. Seguro de rodar repetidamente e seguro
    de rodar num banco que já tem dados de fases anteriores — só adiciona o
    que falta."""
    path = db_path or get_db_path()
    conn = _connect(path)
    try:
        _garantir_tabela_migrations(conn)
        aplicadas = {r["arquivo"] for r in conn.execute("SELECT arquivo FROM _migrations").fetchall()}
        for nome_arquivo in SCHEMA_FILES:
            if nome_arquivo in aplicadas:
                continue
            caminho = os.path.join(MIGRATIONS_DIR, nome_arquivo)
            if not os.path.exists(caminho):
                continue
            with open(caminho, "r", encoding="utf-8") as f:
                conn.executescript(f.read())
            conn.execute("INSERT INTO _migrations (arquivo) VALUES (?)", (nome_arquivo,))
            conn.commit()
    finally:
        conn.close()


def init_db(db_path=None, drop_existing=False):
    """Cria/atualiza o schema. Com drop_existing=True, apaga o banco antes
    (usado pelos testes, para partir de um estado limpo). Sem
    drop_existing, é seguro chamar em um banco já existente — é exatamente
    o comando usado para atualizar de uma fase para a próxima."""
    path = db_path or get_db_path()
    if drop_existing and os.path.exists(path):
        os.remove(path)
    aplicar_migrations(path)


def caminho_restauracao_pendente(db_path=None):
    """Fase 67 — onde a tela de Restauração deixa o arquivo de backup
    enviado pelo usuário, ESPERANDO o próximo início do sistema (ver a
    nota de escopo completa em migrations/schema_fase67.sql: nunca troca
    o banco com o servidor já respondendo requisições, só no início)."""
    path = db_path or get_db_path()
    return path + ".restauracao_pendente"


def aplicar_restauracao_pendente_se_houver(db_path=None):
    """Chamada por run.py ANTES de abrir o banco de verdade (tanto no
    modo de desenvolvimento quanto sob waitress-serve, já que as duas
    formas executam o código de nível de módulo de run.py). Se existir um
    arquivo de restauração pendente (deixado pela tela de Restauração —
    ver `restaurar_backup` em app/routes/sistema.py):
      1. guarda uma cópia de segurança do banco ATUAL (carimbada com
         data/hora) — mesmo que ele esteja corrompido ou "hackeado", para
         nunca destruir evidência/dados por engano;
      2. move (`os.replace`, atômico dentro do mesmo diretório) o arquivo
         pendente para o lugar do banco de verdade;
      3. apaga o marcador pendente.
    Sempre roda ANTES de qualquer conexão de aplicação ser aberta, então
    não existe risco de "arquivo em uso" mesmo no Windows. Devolve um
    dict com o que foi feito (ou None se não havia nada pendente) — só
    para o log de início do servidor, não é usado pela aplicação em si."""
    import datetime
    import shutil

    path = db_path or get_db_path()
    pendente = caminho_restauracao_pendente(path)
    if not os.path.exists(pendente):
        return None

    resultado = {"restaurado_de": pendente, "copia_seguranca": None}
    if os.path.exists(path):
        agora = datetime.datetime.utcnow().strftime("%Y%m%d_%Hh%Mmin%Ss")
        copia_seguranca = os.path.join(
            os.path.dirname(path), f"antes_da_restauracao_{agora}.db"
        )
        shutil.copy2(path, copia_seguranca)
        resultado["copia_seguranca"] = copia_seguranca

    os.replace(pendente, path)
    return resultado


@contextmanager
def get_conn(db_path=None):
    conn = _connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def row_to_dict(row):
    if row is None:
        return None
    return dict(row)


def rows_to_list(rows):
    return [dict(r) for r in rows]
