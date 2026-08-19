"""
Fase 40 — Conciliação Bancária: parser de extrato no formato OFX (Open
Financial Exchange), o formato de exportação de extrato que praticamente
todo banco brasileiro oferece (Internet Banking → "Exportar extrato" →
OFX/Money/Quicken).

Deliberadamente NÃO usa nenhuma biblioteca de terceiros (`ofxparse` ou
equivalente não estava disponível neste ambiente, sem acesso de rede para
instalar pacotes novos — mesma restrição documentada no restante deste
projeto). Em vez disso, um parser tolerante por expressão regular: a
maioria dos bancos ainda exporta OFX na versão 1.x, que é SGML (não XML
de verdade) — elementos "folha" como `<TRNAMT>` não têm fechamento
(`</TRNAMT>`), só elementos "contêiner" como `<STMTTRN>` fecham de
verdade. Um parser XML de verdade rejeitaria esse arquivo; a abordagem
aqui extrai cada bloco `<STMTTRN>...</STMTTRN>` (que sempre fecha) e, de
dentro dele, cada tag de interesse por regex — funciona tanto para OFX
1.x (SGML) quanto 2.x (XML de verdade), sem depender de qual dos dois é.
"""
import re

_RE_STMTTRN = re.compile(r"<STMTTRN>(.*?)</STMTTRN>", re.IGNORECASE | re.DOTALL)


def _extrair_tag(bloco, tag):
    """Extrai o valor de uma tag OFX 'folha' (sem fechamento garantido) —
    para até a próxima quebra de linha ou até a próxima tag `<...>`, o que
    vier primeiro."""
    m = re.search(rf"<{tag}>\s*([^\r\n<]*)", bloco, re.IGNORECASE)
    return m.group(1).strip() if m else None


def _parsear_data(dtposted):
    """OFX guarda data/hora como YYYYMMDD[HHMMSS[.mmm]][[+-]TZ] — só os 8
    primeiros dígitos (YYYYMMDD) interessam para conciliação (comparamos
    por dia, não por hora)."""
    if not dtposted or len(dtposted) < 8 or not dtposted[:8].isdigit():
        return None
    ano, mes, dia = dtposted[0:4], dtposted[4:6], dtposted[6:8]
    return f"{ano}-{mes}-{dia}"


def _parsear_valor(trnamt):
    if trnamt is None:
        return None
    try:
        # OFX sempre usa "." como separador decimal, independente do
        # idioma do banco — não precisa (nem deve) trocar por vírgula.
        return round(float(trnamt.replace(",", ".")), 2)
    except ValueError:
        return None


def parse_ofx(conteudo):
    """Devolve {'banco': str|None, 'conta': str|None, 'transacoes': [...]}."""
    banco = _extrair_tag(conteudo, "BANKID") or _extrair_tag(conteudo, "ORG")
    conta = _extrair_tag(conteudo, "ACCTID")

    blocos = _RE_STMTTRN.findall(conteudo)
    if not blocos:
        raise ValueError(
            "Nenhuma transação (<STMTTRN>) encontrada no arquivo — confirme que é um extrato OFX exportado "
            "do Internet Banking do seu banco (não um PDF nem uma planilha)."
        )

    transacoes = []
    for bloco in blocos:
        valor = _parsear_valor(_extrair_tag(bloco, "TRNAMT"))
        data = _parsear_data(_extrair_tag(bloco, "DTPOSTED"))
        if valor is None or data is None:
            # Transação sem valor ou data utilizável não tem como ser
            # conciliada nem exibida com sentido — pulada silenciosamente
            # em vez de quebrar a importação inteira por uma linha ruim.
            continue
        fitid = _extrair_tag(bloco, "FITID")
        descricao = _extrair_tag(bloco, "MEMO") or _extrair_tag(bloco, "NAME") or _extrair_tag(bloco, "TRNTYPE") or ""
        transacoes.append({
            "fitid": fitid or None,
            "data": data,
            "valor": valor,
            "descricao": descricao.strip(),
        })

    return {"banco": banco, "conta": conta, "transacoes": transacoes}
