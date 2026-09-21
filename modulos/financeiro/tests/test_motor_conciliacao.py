"""Testes do motor de conciliação isolados de rotas/agregador.

Cobrem duas garantias que vivem no próprio motor, não na camada HTTP:
o piso do limiar automático (para que valha também para quem chama
`conciliar()` direto, não só pela rota) e a direção da diferença de valor
na explicação da R1.
"""

from __future__ import annotations

from datetime import date

from ..conciliacao.api.motor_conciliacao import (LIMIAR_MINIMO_AUTOMATICO,
                                                   Lancamento, Titulo,
                                                   conciliar)


def test_limiar_abaixo_do_piso_e_ignorado_mesmo_chamando_o_motor_direto():
    """R3 marca 80 de confiança; um limiar_auto=50 tentaria classificar
    isso como automático. O motor precisa recusar, sem depender de
    ninguém aplicar o piso antes de chamá-lo."""
    hoje = date(2026, 2, 10)
    lancamentos = [
        # Valor exato, nome da contraparte no histórico, data bem fora da
        # tolerância — só fecha por R3 (confiança 80).
        Lancamento("L1", hoje, "PGTO TRANSPORTES SAO JOAO", 1500000),
    ]
    titulos = [
        Titulo("T1", "receber", "NF 1021", "Transportes Sao Joao Ltda",
               1500000, hoje - date.resolution * 40),
    ]

    resultados = conciliar(lancamentos, titulos, limiar_auto=50)

    assert resultados[0].confianca == 80
    # Mesmo pedindo limiar_auto=50 (que aceitaria 80), o piso de
    # LIMIAR_MINIMO_AUTOMATICO (85) prevalece: R3 fica como sugestão.
    assert resultados[0].status == "sugestao"
    assert LIMIAR_MINIMO_AUTOMATICO == 85


def test_diferenca_de_valor_na_r1_mostra_a_direcao():
    """Documento bate mas o valor diverge: a frase precisa dizer se veio
    a mais ou a menos, não só a diferença em módulo."""
    hoje = date(2026, 2, 10)

    menos = conciliar(
        [Lancamento("L1", hoje, "PGTO", 140000, "12345678000190")],
        [Titulo("T1", "receber", "NF", "Cliente", 150000, hoje, "12345678000190")],
    )
    assert "a menos" in menos[0].explicacao
    assert "a mais" not in menos[0].explicacao

    mais = conciliar(
        [Lancamento("L1", hoje, "PGTO", 160000, "12345678000190")],
        [Titulo("T1", "receber", "NF", "Cliente", 150000, hoje, "12345678000190")],
    )
    assert "a mais" in mais[0].explicacao
    assert "a menos" not in mais[0].explicacao
