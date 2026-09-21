"""
Agregação para o dashboard financeiro.

Camada de dados separada da apresentação, como pede
references/conciliacao/dashboard.md: quando a origem deixar de ser o
arquivo importado e passar a ser a API do Projuris, só este arquivo muda.

Duas decisões que o arquivo de referência trata como erro comum e que
aqui são explícitas:

- crédito e débito nunca entram no mesmo KPI — o sinal é conferido antes;
- período sem entrada devolve margem `None` (a tela mostra "—"), não 0%.
  Zero e "sem dado" significam coisas diferentes para quem lê.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from .motor_conciliacao import Resultado, Titulo

MESES = ("", "jan", "fev", "mar", "abr", "mai", "jun",
         "jul", "ago", "set", "out", "nov", "dez")

TETO_CLIENTES = 10
TETO_FORNECEDORES = 15


@dataclass
class Filtros:
    ano: int | None = None
    mes: int | None = None
    banco: str = ""
    forma_pagamento: str = ""
    categoria_entrada: str = ""
    categoria_saida: str = ""

    @classmethod
    def de_dict(cls, dados: dict | None) -> "Filtros":
        dados = dados or {}

        def inteiro(chave: str) -> int | None:
            bruto = str(dados.get(chave, "")).strip()
            return int(bruto) if bruto.isdigit() else None

        def texto(chave: str) -> str:
            bruto = str(dados.get(chave, "")).strip()
            return "" if bruto.lower() in ("", "todos", "todas") else bruto

        return cls(
            ano=inteiro("ano"), mes=inteiro("mes"),
            banco=texto("banco"), forma_pagamento=texto("forma_pagamento"),
            categoria_entrada=texto("categoria_entrada"),
            categoria_saida=texto("categoria_saida"),
        )

    @property
    def ativos(self) -> bool:
        return any([self.ano, self.mes, self.banco, self.forma_pagamento,
                    self.categoria_entrada, self.categoria_saida])


@dataclass
class Painel:
    kpis: dict = field(default_factory=dict)
    mensal: list[dict] = field(default_factory=list)
    status_recebimentos: list[dict] = field(default_factory=list)
    top_clientes: list[dict] = field(default_factory=list)
    top_fornecedores: list[dict] = field(default_factory=list)
    opcoes_filtro: dict = field(default_factory=dict)
    vazio: bool = True
    filtros_ativos: bool = False
    total_lancamentos: int = 0


def montar_painel(resultados: list[Resultado], titulos: list[Titulo],
                  extras: dict[str, dict[str, str]] | None = None,
                  filtros: Filtros | None = None,
                  referencia: date | None = None) -> Painel:
    """Monta KPIs e séries a partir do resultado da conciliação."""
    filtros = filtros or Filtros()
    extras = extras or {}
    referencia = referencia or date.today()

    opcoes = _opcoes_filtro(resultados, extras)
    selecionados = [r for r in resultados if _passa(r, filtros, extras)]

    painel = Painel(
        opcoes_filtro=opcoes,
        filtros_ativos=filtros.ativos,
        total_lancamentos=len(selecionados),
        vazio=not selecionados,
    )
    if not selecionados:
        return painel

    conciliados = [r for r in selecionados if r.status in ("automatico", "sugestao")]

    entrada = sum(r.lancamento.valor_centavos for r in conciliados
                  if r.lancamento.valor_centavos > 0)
    saida = sum(-r.lancamento.valor_centavos for r in conciliados
                if r.lancamento.valor_centavos < 0)

    painel.kpis = {
        "entrada_centavos": entrada,
        "saida_centavos": saida,
        "saldo_centavos": entrada - saida,
        # Sem entrada no período a margem não existe — e não é zero.
        "margem_pct": round((entrada - saida) / entrada * 100, 1) if entrada else None,
        "lancamentos_conciliados": len(conciliados),
        "lancamentos_divergentes": len([r for r in selecionados
                                        if r.status == "divergencia"]),
    }
    painel.mensal = _serie_mensal(conciliados)
    painel.status_recebimentos = _status_recebimentos(selecionados, titulos, referencia)
    painel.top_clientes = _ranking(conciliados, "receber", TETO_CLIENTES)
    painel.top_fornecedores = _ranking(conciliados, "pagar", TETO_FORNECEDORES)
    return painel


# --------------------------------------------------------------------------
# Filtros
# --------------------------------------------------------------------------

def _passa(resultado: Resultado, filtros: Filtros,
           extras: dict[str, dict[str, str]]) -> bool:
    data_lanc = resultado.lancamento.data
    if filtros.ano and data_lanc.year != filtros.ano:
        return False
    if filtros.mes and data_lanc.month != filtros.mes:
        return False

    dimensoes = extras.get(resultado.titulo.id, {}) if resultado.titulo else {}
    if filtros.banco and dimensoes.get("banco", "") != filtros.banco:
        return False
    if filtros.forma_pagamento and dimensoes.get("forma_pagamento", "") != filtros.forma_pagamento:
        return False

    credito = resultado.lancamento.valor_centavos >= 0
    categoria = dimensoes.get("categoria", "")
    if filtros.categoria_entrada and (not credito or categoria != filtros.categoria_entrada):
        return False
    if filtros.categoria_saida and (credito or categoria != filtros.categoria_saida):
        return False
    return True


def _opcoes_filtro(resultados: list[Resultado],
                   extras: dict[str, dict[str, str]]) -> dict:
    """Só oferece o filtro que tem dado por trás.

    Um seletor de Banco sempre vazio faria o usuário procurar um filtro
    que não existe; a tela prefere dizer que a origem do campo ainda não
    foi definida.
    """
    anos, meses = set(), set()
    bancos, formas = set(), set()
    cat_entrada, cat_saida = set(), set()

    for r in resultados:
        anos.add(r.lancamento.data.year)
        meses.add(r.lancamento.data.month)
        dimensoes = extras.get(r.titulo.id, {}) if r.titulo else {}
        if dimensoes.get("banco"):
            bancos.add(dimensoes["banco"])
        if dimensoes.get("forma_pagamento"):
            formas.add(dimensoes["forma_pagamento"])
        if dimensoes.get("categoria"):
            destino = cat_entrada if r.lancamento.valor_centavos >= 0 else cat_saida
            destino.add(dimensoes["categoria"])

    return {
        "ano": sorted(anos),
        "mes": [{"valor": m, "rotulo": MESES[m]} for m in sorted(meses)],
        "banco": sorted(bancos),
        "forma_pagamento": sorted(formas),
        "categoria_entrada": sorted(cat_entrada),
        "categoria_saida": sorted(cat_saida),
    }


# --------------------------------------------------------------------------
# Séries
# --------------------------------------------------------------------------

def _serie_mensal(conciliados: list[Resultado]) -> list[dict]:
    acumulado: dict[tuple[int, int], dict] = defaultdict(
        lambda: {"entrada_centavos": 0, "saida_centavos": 0}
    )
    for r in conciliados:
        chave = (r.lancamento.data.year, r.lancamento.data.month)
        valor = r.lancamento.valor_centavos
        if valor >= 0:
            acumulado[chave]["entrada_centavos"] += valor
        else:
            acumulado[chave]["saida_centavos"] += -valor

    serie = []
    for (ano, mes), valores in sorted(acumulado.items()):
        serie.append({
            "ano": ano,
            "mes": mes,
            "rotulo": f"{MESES[mes]}/{str(ano)[-2:]}",
            "entrada_centavos": valores["entrada_centavos"],
            "saida_centavos": valores["saida_centavos"],
            "total_centavos": valores["entrada_centavos"] - valores["saida_centavos"],
        })
    return serie


def _status_recebimentos(resultados: list[Resultado], titulos: list[Titulo],
                         referencia: date) -> list[dict]:
    """Rosca: Pago, Vencido, A Vencer, Não Conciliado — em reais."""
    conciliados_ids = {r.titulo.id for r in resultados
                       if r.titulo and r.status in ("automatico", "sugestao")}

    pago = vencido = a_vencer = 0
    for titulo in titulos:
        if titulo.tipo != "receber" or titulo.status == "cancelado":
            continue
        if titulo.status == "pago" or titulo.id in conciliados_ids:
            pago += titulo.valor_centavos
        elif titulo.vencimento < referencia:
            vencido += titulo.valor_centavos
        else:
            a_vencer += titulo.valor_centavos

    nao_conciliado = sum(r.lancamento.valor_centavos for r in resultados
                         if r.status == "divergencia" and r.lancamento.valor_centavos > 0)

    fatias = [
        {"rotulo": "Pago", "valor_centavos": pago, "cor": "pago"},
        {"rotulo": "Vencido", "valor_centavos": vencido, "cor": "vencido"},
        {"rotulo": "A Vencer", "valor_centavos": a_vencer, "cor": "a_vencer"},
        {"rotulo": "Não Conciliado", "valor_centavos": nao_conciliado,
         "cor": "nao_conciliado"},
    ]
    return [f for f in fatias if f["valor_centavos"] > 0]


def _ranking(conciliados: list[Resultado], tipo: str, teto: int) -> list[dict]:
    """Top clientes (receber) ou fornecedores (pagar), por valor conciliado."""
    acumulado: dict[str, int] = defaultdict(int)
    for r in conciliados:
        if not r.titulo or r.titulo.tipo != tipo:
            continue
        nome = (r.titulo.contraparte or r.lancamento.contraparte
                or r.lancamento.descricao or "(sem identificação)").strip()
        acumulado[nome] += abs(r.lancamento.valor_centavos)

    ordenado = sorted(acumulado.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"nome": nome, "valor_centavos": valor}
            for nome, valor in ordenado[:teto]]


# --------------------------------------------------------------------------
# Formatação (usada também pelas respostas em texto)
# --------------------------------------------------------------------------

def brl(centavos: int | None, abreviar: bool = False) -> str:
    """`R$ 1.234.567,89`. Abreviação só acima de 1 milhão, quando pedida."""
    if centavos is None:
        return "—"
    negativo = centavos < 0
    valor = abs(centavos) / 100
    if abreviar and valor >= 1_000_000:
        texto = f"R$ {valor / 1_000_000:.1f} Mi".replace(".", ",")
    else:
        inteiro = f"{valor:,.2f}".replace(",", "~").replace(".", ",").replace("~", ".")
        texto = f"R$ {inteiro}"
    return f"-{texto}" if negativo else texto


def pct(valor: float | None) -> str:
    return "—" if valor is None else f"{valor:.1f}".replace(".", ",") + "%"
