"""Testes do agregador do dashboard.

Cobrem os dois erros que `dashboard.md` destaca: somar crédito com débito
no mesmo KPI e transformar "sem entrada" em 0%.
"""

from __future__ import annotations

from datetime import date

from ..conciliacao.api.agregador import Filtros, montar_painel, pct
from ..shared.formatacao import brl
from ..conciliacao.api.motor_conciliacao import (Lancamento, Titulo, conciliar)


def _dados():
    lancamentos = [
        Lancamento("L1", date(2026, 2, 10), "TED TRANSPORTES SAO JOAO",
                   1500000, "12345678000190"),
        Lancamento("L2", date(2026, 2, 11), "ALUGUEL LOCADORA CENTRAL", -350000),
        Lancamento("L3", date(2026, 3, 5), "PIX ALIMENTOS NORTE", 850000),
    ]
    titulos = [
        Titulo("T1", "receber", "NF 1021", "Transportes Sao Joao Ltda",
               1500000, date(2026, 2, 10), "12345678000190"),
        Titulo("T2", "pagar", "Aluguel", "Locadora Central", 350000,
               date(2026, 2, 11)),
        Titulo("T3", "receber", "NF 1022", "Alimentos Norte", 850000,
               date(2026, 3, 5)),
    ]
    return conciliar(lancamentos, titulos), titulos


def test_kpis_separam_credito_de_debito():
    resultados, titulos = _dados()
    painel = montar_painel(resultados, titulos)

    assert painel.kpis["entrada_centavos"] == 2350000
    assert painel.kpis["saida_centavos"] == 350000
    assert painel.kpis["saldo_centavos"] == 2000000
    assert painel.kpis["margem_pct"] == 85.1


def test_periodo_sem_entrada_nao_vira_margem_zero():
    lanc = [Lancamento("L1", date(2026, 2, 11), "ALUGUEL", -350000)]
    tit = [Titulo("T1", "pagar", "Aluguel", "Locadora", 350000, date(2026, 2, 11))]

    painel = montar_painel(conciliar(lanc, tit), tit)

    assert painel.kpis["entrada_centavos"] == 0
    assert painel.kpis["margem_pct"] is None
    assert pct(painel.kpis["margem_pct"]) == "—"


def test_serie_mensal_agrupa_por_mes():
    resultados, titulos = _dados()
    painel = montar_painel(resultados, titulos)

    assert [m["rotulo"] for m in painel.mensal] == ["fev/26", "mar/26"]
    assert painel.mensal[0]["entrada_centavos"] == 1500000
    assert painel.mensal[0]["saida_centavos"] == 350000


def test_filtro_sem_resultado_devolve_vazio_e_nao_painel_de_zeros():
    resultados, titulos = _dados()

    painel = montar_painel(resultados, titulos, filtros=Filtros(ano=2019))

    assert painel.vazio
    assert painel.filtros_ativos
    assert painel.kpis == {}


def test_rankings_separam_clientes_de_fornecedores():
    resultados, titulos = _dados()
    painel = montar_painel(resultados, titulos)

    assert [c["nome"] for c in painel.top_clientes] == [
        "Transportes Sao Joao Ltda", "Alimentos Norte"]
    assert [f["nome"] for f in painel.top_fornecedores] == ["Locadora Central"]


def test_status_de_recebimentos_classifica_pago_vencido_e_a_vencer():
    resultados, titulos = _dados()
    titulos.append(Titulo("T4", "receber", "NF 1023", "Cliente Atrasado",
                          500000, date(2026, 1, 5)))
    titulos.append(Titulo("T5", "receber", "NF 1024", "Cliente Futuro",
                          700000, date(2026, 12, 20)))

    fatias = {f["rotulo"]: f["valor_centavos"]
              for f in montar_painel(resultados, titulos,
                                     referencia=date(2026, 3, 10)).status_recebimentos}

    assert fatias["Pago"] == 2350000
    assert fatias["Vencido"] == 500000
    assert fatias["A Vencer"] == 700000


def test_formatacao_de_moeda():
    assert brl(123456789) == "R$ 1.234.567,89"
    assert brl(-4590) == "-R$ 45,90"
    assert brl(150000000, abreviar=True) == "R$ 1,5 Mi"
    assert brl(None) == "—"
    assert pct(85.14) == "85,1%"
