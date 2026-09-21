"""
Motor determinístico de conciliação bancária.

Cruza lançamentos de extrato contra títulos (contas a receber / a pagar)
aplicando as regras R1..R5 descritas em references/conciliacao/motor-matching.md.

Nenhuma aleatoriedade, nenhuma dependência externa: a mesma entrada
produz sempre a mesma saída, o que é o que torna o resultado auditável.

Uso:
    from motor_conciliacao import conciliar, Lancamento, Titulo

    resultado = conciliar(lancamentos, titulos)
    for item in resultado:
        print(item.status, item.confianca, item.explicacao)
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

# --------------------------------------------------------------------------
# Configuração
# --------------------------------------------------------------------------

TOLERANCIA_DIAS = 5
TOLERANCIA_VALOR_PCT = 2.0
LIMIAR_AUTOMATICO = 90
LIMIAR_SUGESTAO = 70

RUIDO_BANCARIO = {
    "ted", "pix", "doc", "transf", "transferencia", "pgto", "pagto",
    "pagamento", "receb", "recebimento", "cred", "credito", "deb",
    "debito", "liq", "liquidacao", "cobranca", "titulo", "boleto",
    "ref", "nf", "de", "da", "do", "para", "ltda", "me", "sa", "eireli",
}


# --------------------------------------------------------------------------
# Modelos
# --------------------------------------------------------------------------

@dataclass
class Lancamento:
    """Um lançamento do extrato bancário."""
    id: str
    data: date
    descricao: str
    valor_centavos: int          # positivo = crédito, negativo = débito
    documento: str = ""
    contraparte: str = ""
    fitid: str = ""              # identificador OFX, quando houver

    @property
    def tipo(self) -> str:
        return "credito" if self.valor_centavos >= 0 else "debito"


@dataclass
class Titulo:
    """Um título do financeiro (conta a receber ou a pagar)."""
    id: str
    tipo: str                    # "receber" | "pagar"
    descricao: str
    contraparte: str
    valor_centavos: int          # sempre positivo
    vencimento: date
    documento: str = ""
    status: str = "aberto"       # aberto | pago | cancelado | parcial


@dataclass
class Resultado:
    lancamento: Lancamento
    titulo: Optional[Titulo]
    confianca: int
    regra: str
    explicacao: str
    dif_valor_centavos: int
    dif_dias: int
    status: str                  # automatico | sugestao | divergencia
    tipo_divergencia: Optional[str] = None
    candidatos: list = field(default_factory=list)


# --------------------------------------------------------------------------
# Normalização
# --------------------------------------------------------------------------

def normalizar_texto(texto: str) -> str:
    """Minúsculas, sem acento, sem pontuação, espaços colapsados."""
    if not texto:
        return ""
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = texto.lower()
    texto = re.sub(r"[^\w\s]", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def tokens_significativos(texto: str) -> set[str]:
    """Tokens com 4+ caracteres, sem o ruído bancário."""
    return {
        t for t in normalizar_texto(texto).split()
        if len(t) >= 4 and t not in RUIDO_BANCARIO
    }


def normalizar_documento(doc: str) -> str:
    """Mantém apenas os dígitos."""
    return re.sub(r"\D", "", doc or "")


def raiz_cnpj(doc: str) -> str:
    """Os 8 primeiros dígitos de um CNPJ — mesma empresa, filial diferente."""
    d = normalizar_documento(doc)
    return d[:8] if len(d) == 14 else ""


def parse_valor_br(texto: str) -> int:
    """'1.234,56' -> 123456 centavos. Aceita sinal e símbolo de moeda."""
    if texto is None:
        raise ValueError("valor vazio")
    if isinstance(texto, (int, float)):
        return int(round(float(texto) * 100))
    s = str(texto).strip()
    negativo = s.startswith("-") or s.endswith("-") or "(" in s
    s = re.sub(r"[^\d,.-]", "", s).replace("(", "").replace(")", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")   # 1.234,56
    elif "," in s:
        s = s.replace(",", ".")                    # 1234,56
    s = s.lstrip("-").rstrip("-")
    if not s:
        raise ValueError("valor não numérico")
    centavos = int(round(float(s) * 100))
    return -centavos if negativo else centavos


# --------------------------------------------------------------------------
# Comparações auxiliares
# --------------------------------------------------------------------------

def _dif_dias(a: date, b: date) -> int:
    return abs((a - b).days)


def _dentro_tolerancia_valor(v1: int, v2: int, pct: float) -> bool:
    if v2 == 0:
        return v1 == 0
    return abs(v1 - v2) / abs(v2) * 100 <= pct


def _similaridade_tokens(texto_a: str, texto_b: str) -> float:
    """Fração dos tokens de B presentes em A. 0.0 a 1.0."""
    ta, tb = tokens_significativos(texto_a), tokens_significativos(texto_b)
    if not tb:
        return 0.0
    return len(ta & tb) / len(tb)


def _fmt(centavos: int) -> str:
    s = f"{abs(centavos) / 100:,.2f}".replace(",", "~").replace(".", ",").replace("~", ".")
    return f"R$ {s}"


# --------------------------------------------------------------------------
# Regras
# --------------------------------------------------------------------------

def pontuar(lanc: Lancamento, tit: Titulo,
            tol_dias: int = TOLERANCIA_DIAS,
            tol_valor: float = TOLERANCIA_VALOR_PCT) -> tuple[int, str, str]:
    """Retorna (confiança, regra, explicação) para um par lançamento/título."""

    valor_lanc = abs(lanc.valor_centavos)
    dif_valor = valor_lanc - tit.valor_centavos
    dif_dias = _dif_dias(lanc.data, tit.vencimento)
    valor_exato = dif_valor == 0

    doc_l = normalizar_documento(lanc.documento)
    doc_t = normalizar_documento(tit.documento)

    # R1 — documento exato
    if doc_l and doc_t and doc_l == doc_t:
        if valor_exato:
            return 98, "R1 — documento e valor exatos", (
                f"Documento {tit.documento} confere e o valor é idêntico ({_fmt(valor_lanc)})."
            )
        return 95, "R1 — documento exato", (
            f"Documento {tit.documento} confere. "
            f"Diferença de valor: {_fmt(dif_valor)}."
        )

    # R1b — mesma raiz de CNPJ
    if raiz_cnpj(lanc.documento) and raiz_cnpj(lanc.documento) == raiz_cnpj(tit.documento):
        if valor_exato:
            return 88, "R1b — mesma empresa (raiz CNPJ) e valor exato", (
                "Raiz de CNPJ igual (filial diferente) e valor idêntico."
            )

    # R2 — valor exato + data dentro da tolerância
    if valor_exato and dif_dias <= tol_dias:
        score = max(85, 90 - dif_dias)
        return score, "R2 — valor exato + data próxima", (
            f"Valor idêntico ({_fmt(valor_lanc)}) e vencimento "
            f"{'no mesmo dia' if dif_dias == 0 else f'{dif_dias} dia(s) de diferença'}."
        )

    # R3 — valor exato + descrição similar
    if valor_exato:
        sim = max(
            _similaridade_tokens(lanc.descricao, tit.contraparte),
            _similaridade_tokens(lanc.contraparte, tit.contraparte),
        )
        if sim >= 0.5:
            return 80, "R3 — valor exato + contraparte na descrição", (
                f"Valor idêntico ({_fmt(valor_lanc)}) e o nome de {tit.contraparte} "
                f"aparece no histórico, embora a data esteja {dif_dias} dias fora."
            )

    # R4 — contraparte confere + valor dentro da tolerância
    contraparte_bate = (
        (doc_l and doc_t and doc_l == doc_t)
        or _similaridade_tokens(lanc.descricao, tit.contraparte) >= 0.5
        or _similaridade_tokens(lanc.contraparte, tit.contraparte) >= 0.5
    )
    if contraparte_bate and _dentro_tolerancia_valor(valor_lanc, tit.valor_centavos, tol_valor):
        sentido = "a menos" if dif_valor < 0 else "a mais"
        return 75, "R4 — contraparte + valor próximo", (
            f"Contraparte {tit.contraparte} confere. O crédito veio "
            f"{_fmt(dif_valor)} {sentido} que o título — verificar se há "
            f"tarifa, retenção, desconto ou juros."
        )

    # R5 — combinação de sinais fracos
    score = 0
    sinais = []
    if _dentro_tolerancia_valor(valor_lanc, tit.valor_centavos, tol_valor):
        score += 30
        sinais.append("valor próximo")
    if dif_dias <= tol_dias:
        score += 20
        sinais.append("data próxima")
    if doc_l and doc_t and (doc_l in doc_t or doc_t in doc_l):
        score += 20
        sinais.append("documento parcialmente igual")
    if _similaridade_tokens(lanc.descricao, tit.contraparte) > 0:
        score += 20
        sinais.append("fragmento da contraparte no histórico")

    if score > 0:
        score = min(score, 70)
        return score, "R5 — sinais fracos combinados", (
            "Correspondência fraca: " + ", ".join(sinais) + ". Requer conferência."
        )

    return 0, "sem correspondência", "Nenhum sinal de correspondência com este título."


# --------------------------------------------------------------------------
# Conciliação
# --------------------------------------------------------------------------

def conciliar(lancamentos: list[Lancamento],
              titulos: list[Titulo],
              tol_dias: int = TOLERANCIA_DIAS,
              tol_valor: float = TOLERANCIA_VALOR_PCT,
              limiar_auto: int = LIMIAR_AUTOMATICO) -> list[Resultado]:
    """Cruza lançamentos contra títulos e classifica cada resultado.

    Um título já usado por um lançamento não é oferecido a outro: isso
    é o que faz duplicidade aparecer como divergência em vez de virar
    dois matches sobre o mesmo título.
    """
    resultados: list[Resultado] = []
    titulos_usados: set[str] = set()

    abertos = [t for t in titulos if t.status in ("aberto", "parcial")]

    # Duplicidades: mesmo valor, mesma contraparte, até 3 dias de distância.
    duplicados = _detectar_duplicidades(lancamentos)

    for lanc in lancamentos:
        pontuados = []
        for tit in abertos:
            if tit.id in titulos_usados:
                continue
            if not _tipo_compativel(lanc, tit):
                continue
            score, regra, expl = pontuar(lanc, tit, tol_dias, tol_valor)
            if score > 0:
                pontuados.append((score, regra, expl, tit))

        pontuados.sort(key=lambda x: (-x[0], x[3].id))

        if not pontuados:
            resultados.append(_divergencia(
                lanc, None, 0, "sem correspondência",
                "Nenhum título em aberto corresponde a este lançamento.",
                "sem_titulo",
            ))
            continue

        score, regra, expl, tit = pontuados[0]

        # Ambiguidade: dois ou mais títulos empatados na faixa automática.
        empatados = [p for p in pontuados if p[0] == score]
        if len(empatados) > 1 and score >= limiar_auto:
            resultados.append(_divergencia(
                lanc, tit, score, regra,
                f"{len(empatados)} títulos igualmente prováveis — escolha manual necessária.",
                "ambiguidade",
                candidatos=[p[3] for p in empatados],
            ))
            continue

        if lanc.id in duplicados:
            resultados.append(_divergencia(
                lanc, tit, score, regra,
                "Há outro lançamento de mesmo valor e contraparte em datas próximas; "
                "confirme se não é duplicidade antes de conciliar.",
                "duplicidade",
            ))
            continue

        dif_valor = abs(lanc.valor_centavos) - tit.valor_centavos
        dif_dias = _dif_dias(lanc.data, tit.vencimento)

        if score >= limiar_auto:
            status, tipo_div = "automatico", None
            titulos_usados.add(tit.id)
        elif score >= LIMIAR_SUGESTAO:
            status, tipo_div = "sugestao", None
        else:
            status = "divergencia"
            tipo_div = ("valor_divergente" if dif_valor != 0
                        else "data_divergente" if dif_dias > tol_dias
                        else "descricao_insuficiente")

        resultados.append(Resultado(
            lancamento=lanc, titulo=tit, confianca=score, regra=regra,
            explicacao=expl, dif_valor_centavos=dif_valor, dif_dias=dif_dias,
            status=status, tipo_divergencia=tipo_div,
            candidatos=[p[3] for p in pontuados[1:4]],
        ))

    return resultados


def _tipo_compativel(lanc: Lancamento, tit: Titulo) -> bool:
    """Crédito casa com 'receber'; débito casa com 'pagar'."""
    return (lanc.valor_centavos >= 0) == (tit.tipo == "receber")


def _detectar_duplicidades(lancamentos: list[Lancamento]) -> set[str]:
    """IDs de lançamentos que parecem duplicados entre si."""
    suspeitos: set[str] = set()
    for i, a in enumerate(lancamentos):
        for b in lancamentos[i + 1:]:
            if a.valor_centavos != b.valor_centavos:
                continue
            if _dif_dias(a.data, b.data) > 3:
                continue
            if _similaridade_tokens(a.descricao, b.descricao) >= 0.6:
                suspeitos.add(a.id)
                suspeitos.add(b.id)
    return suspeitos


def _divergencia(lanc, tit, score, regra, explicacao, tipo, candidatos=None) -> Resultado:
    return Resultado(
        lancamento=lanc,
        titulo=tit,
        confianca=score,
        regra=regra,
        explicacao=explicacao,
        dif_valor_centavos=(abs(lanc.valor_centavos) - tit.valor_centavos) if tit else 0,
        dif_dias=_dif_dias(lanc.data, tit.vencimento) if tit else 0,
        status="divergencia",
        tipo_divergencia=tipo,
        candidatos=candidatos or [],
    )


# --------------------------------------------------------------------------
# Resumo
# --------------------------------------------------------------------------

def resumir(resultados: list[Resultado]) -> dict:
    """Totais por status, para os KPIs e para o texto de apresentação."""
    def soma(itens):
        return sum(abs(r.lancamento.valor_centavos) for r in itens)

    auto = [r for r in resultados if r.status == "automatico"]
    sug = [r for r in resultados if r.status == "sugestao"]
    div = [r for r in resultados if r.status == "divergencia"]

    total = len(resultados) or 1
    return {
        "total_lancamentos": len(resultados),
        "automatico": {"qtd": len(auto), "valor_centavos": soma(auto)},
        "sugestao": {"qtd": len(sug), "valor_centavos": soma(sug)},
        "divergencia": {"qtd": len(div), "valor_centavos": soma(div)},
        "taxa_automatica_pct": round(len(auto) / total * 100, 1),
        "por_tipo_divergencia": {
            tipo: len([r for r in div if r.tipo_divergencia == tipo])
            for tipo in {r.tipo_divergencia for r in div if r.tipo_divergencia}
        },
    }


if __name__ == "__main__":
    # Verificação rápida do motor com um caso de cada tipo.
    hoje = date(2026, 2, 10)
    lancs = [
        Lancamento("L1", hoje, "TED TRANSPORTES SAO JOAO LTDA", 1500000, "12345678000190"),
        Lancamento("L2", hoje + timedelta(days=2), "PIX ALIMENTOS NORTE", 850000),
        Lancamento("L3", hoje, "CREDITO NAO IDENTIFICADO", 99900),
        Lancamento("L4", hoje, "PIX ALIMENTOS NORTE", 850000),
    ]
    tits = [
        Titulo("T1", "receber", "NF 1021", "Transportes Sao Joao Ltda", 1500000,
               hoje, "12345678000190"),
        Titulo("T2", "receber", "NF 1022", "Alimentos Norte", 850000, hoje),
    ]
    for r in conciliar(lancs, tits):
        print(f"{r.lancamento.id}  {r.status:12}  {r.confianca:3}  {r.regra}")
        print(f"      {r.explicacao}")
    print()
    print(resumir(conciliar(lancs, tits)))
