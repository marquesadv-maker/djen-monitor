"""Testes do leitor de títulos exportados do Projuris."""

from __future__ import annotations

from datetime import date

from ..conciliacao.api.leitor_titulos import ler_titulos, vencidos

CSV = (
    "Código;Tipo;Cliente/Fornecedor;CPF/CNPJ;Valor;Vencimento;Situação;Banco;Categoria\n"
    "T1;Receber;Transportes Sao Joao Ltda;12.345.678/0001-90;15.000,00;10/02/2026;Em aberto;Itaú;Honorários\n"
    "T2;Receber;Alimentos Norte;;8.500,00;08/02/2026;Em aberto;Itaú;Honorários\n"
    "T3;Pagar;Locadora Central;;3.500,00;05/02/2026;Pago;Itaú;Aluguel\n"
    ";;;;;;;;\n"
).encode()


def test_le_titulos_com_tipo_status_e_dimensoes():
    resultado = ler_titulos(CSV, "titulos.csv")

    assert resultado.ok, resultado.erro
    assert len(resultado.titulos) == 3

    primeiro = resultado.titulos[0]
    assert primeiro.id == "T1"
    assert primeiro.tipo == "receber"
    assert primeiro.valor_centavos == 1500000
    assert primeiro.vencimento == date(2026, 2, 10)
    assert primeiro.documento == "12.345.678/0001-90"
    assert primeiro.status == "aberto"

    assert resultado.titulos[2].tipo == "pagar"
    assert resultado.titulos[2].status == "pago"
    assert resultado.extras["T1"]["banco"] == "Itaú"
    assert resultado.extras["T3"]["categoria"] == "Aluguel"


def test_sem_coluna_de_tipo_exige_que_o_usuario_informe():
    csv = ("Cliente;Valor;Vencimento\n"
           "Cliente X;1.000,00;01/03/2026\n").encode()

    assert "receber ou a pagar" in ler_titulos(csv, "t.csv").erro

    resultado = ler_titulos(csv, "t.csv", tipo_padrao="receber")
    assert resultado.ok
    assert resultado.titulos[0].tipo == "receber"


def test_colunas_obrigatorias_ausentes_bloqueiam():
    csv = "Cliente;Observação\nCliente X;nada\n".encode()
    erro = ler_titulos(csv, "t.csv", tipo_padrao="receber").erro
    assert "valor" in erro and "vencimento" in erro


def test_avisa_quando_falta_documento_para_a_regra_mais_forte():
    csv = ("Cliente;Valor;Vencimento\nCliente X;1.000,00;01/03/2026\n").encode()
    resultado = ler_titulos(csv, "t.csv", tipo_padrao="receber")
    assert any("R1" in aviso for aviso in resultado.avisos)


def test_status_desconhecido_vira_aberto_e_rende_aviso():
    csv = ("Cliente;Valor;Vencimento\nCliente X;1.000,00;01/03/2026\n").encode()
    resultado = ler_titulos(csv, "t.csv", tipo_padrao="receber")
    assert resultado.titulos[0].status == "aberto"
    assert any("aberto" in aviso for aviso in resultado.avisos)


def test_vencidos_considera_apenas_titulos_em_aberto():
    resultado = ler_titulos(CSV, "titulos.csv")
    lista = vencidos(resultado.titulos, referencia=date(2026, 2, 9))
    assert [t.id for t in lista] == ["T2"]
