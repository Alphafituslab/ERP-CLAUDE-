"""
Helper de trilha de auditoria. Toda ação crítica do sistema deve chamar
`registrar` dentro da MESMA transação da alteração que está sendo auditada,
para que auditoria e dado nunca fiquem dessincronizados.

A imutabilidade é garantida em duas camadas (defesa em profundidade):
  1. Aqui: não existe nenhuma função de update/delete para a tabela auditoria.
  2. No banco: triggers em schema.sql bloqueiam UPDATE/DELETE mesmo que
     alguém tente via SQL direto.
"""
import json


def registrar(conn, *, tabela: str, registro_id, usuario_id, acao: str,
              valor_anterior=None, valor_novo=None, motivo: str = None,
              ip: str = None, dispositivo: str = None):
    conn.execute(
        """
        INSERT INTO auditoria (tabela, registro_id, usuario_id, acao,
                                valor_anterior, valor_novo, motivo, ip, dispositivo)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            tabela,
            str(registro_id) if registro_id is not None else None,
            usuario_id,
            acao,
            json.dumps(valor_anterior, ensure_ascii=False, default=str) if valor_anterior is not None else None,
            json.dumps(valor_novo, ensure_ascii=False, default=str) if valor_novo is not None else None,
            motivo,
            ip,
            dispositivo,
        ),
    )


def listar(conn, *, tabela: str = None, usuario_id: int = None,
           data_inicio: str = None, data_fim: str = None, limite: int = 200):
    clausulas = []
    params = []
    if tabela:
        clausulas.append("tabela = ?")
        params.append(tabela)
    if usuario_id:
        clausulas.append("usuario_id = ?")
        params.append(usuario_id)
    if data_inicio:
        clausulas.append("criado_em >= ?")
        params.append(data_inicio)
    if data_fim:
        clausulas.append("criado_em <= ?")
        params.append(data_fim)
    where = f"WHERE {' AND '.join(clausulas)}" if clausulas else ""
    sql = f"SELECT * FROM auditoria {where} ORDER BY id DESC LIMIT ?"
    params.append(limite)
    cur = conn.execute(sql, params)
    return [dict(r) for r in cur.fetchall()]
