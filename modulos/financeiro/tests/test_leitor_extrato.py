"""Testes do leitor de extrato.

O que estes testes protegem é o que `formatos-extrato.md` chama de erro
que passa despercebido: sinal invertido, linha de saldo contada como
lançamento e arquivo ilegível apresentado como processado.
"""

from __future__ import annotations

from datetime import date

from ..conciliacao.api.leitor_extrato import (chave_reimportacao,
                                              detectar_reimportacao,
                                              ler_extrato, mascarar_conta)

OFX = """OFXHEADER:100
<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS>
<BANKACCTFROM><ACCTID>0012345678</ACCTID></BANKACCTFROM>
<BANKTRANLIST>
<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20260210120000[-3:BRT]<TRNAMT>15000.00
<FITID>A1<MEMO>TED TRANSPORTES SAO JOAO LTDA<NAME>TRANSPORTES SAO JOAO</STMTTRN>
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260211<TRNAMT>350.50
<FITID>A2<MEMO>TARIFA PACOTE SERVICOS</STMTTRN>
</BANKTRANLIST></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>
"""


def test_ofx_le_lancamentos_e_identifica_fitid():
    resultado = ler_extrato(OFX.encode(), "extrato.ofx")

    assert resultado.ok
    assert resultado.formato == "ofx"
    assert len(resultado.lancamentos) == 2
    assert resultado.conta_mascarada == "****5678"

    credito, debito = resultado.lancamentos
    assert credito.valor_centavos == 1500000
    assert credito.data == date(2026, 2, 10)
    assert credito.fitid == "A1"
    # TRNTYPE DEBIT com valor positivo precisa virar negativo, senão a
    # tarifa entraria no KPI de entrada.
    assert debito.valor_centavos == -35050


def test_ofx_sem_transacoes_diz_que_nao_leu():
    resultado = ler_extrato(b"OFXHEADER:100\n<OFX></OFX>", "vazio.ofx")
    assert not resultado.ok
    assert "sem transações" in resultado.erro


def test_csv_latin1_com_ponto_e_virgula_e_coluna_tipo():
    conteudo = (
        "Banco Exemplo - Extrato de conta corrente\n"
        "Data;Histórico;Documento;Valor;Tipo\n"
        "10/02/2026;PIX ALIMENTOS NORTE;12345678000190;8.500,00;C\n"
        "11/02/2026;PAGAMENTO FORNECEDOR;;1.200,35;D\n"
        "SALDO ANTERIOR;;;;\n"
    ).encode("latin-1")

    resultado = ler_extrato(conteudo, "extrato.csv")

    assert resultado.ok, resultado.erro
    assert resultado.encoding in ("cp1252", "latin-1")
    assert len(resultado.lancamentos) == 2
    assert resultado.lancamentos[0].valor_centavos == 850000
    assert resultado.lancamentos[1].valor_centavos == -120035
    assert resultado.ignoradas == 1          # a linha de saldo, contada
    assert "Li 2 lançamento(s)" in resultado.resumo()
    assert "ignorei 1" in resultado.resumo()


def test_csv_com_colunas_separadas_de_entrada_e_saida():
    conteudo = (
        "Data,Historico,Entrada,Saida\n"
        "05/03/2026,RECEBIMENTO CLIENTE,\"2.000,00\",\n"
        "06/03/2026,ALUGUEL,,\"3.500,00\"\n"
    ).encode()

    resultado = ler_extrato(conteudo, "extrato.csv")

    assert [l.valor_centavos for l in resultado.lancamentos] == [200000, -350000]


def test_csv_com_valor_negativo_mantem_o_sinal():
    conteudo = ("Data;Descrição;Valor\n"
                "01/04/2026;TARIFA;-45,90\n"
                "02/04/2026;CREDITO;1.000,00\n").encode()

    resultado = ler_extrato(conteudo, "extrato.csv")

    assert [l.valor_centavos for l in resultado.lancamentos] == [-4590, 100000]


def test_cabecalho_desconhecido_pede_mapeamento_em_vez_de_adivinhar():
    conteudo = "col_a;col_b;col_c\n1;2;3\n4;5;6\n".encode()

    resultado = ler_extrato(conteudo, "estranho.csv")

    assert resultado.precisa_mapeamento
    assert not resultado.ok
    assert resultado.colunas == ["col_a", "col_b", "col_c"]


def test_pdf_nao_e_apresentado_como_processado():
    resultado = ler_extrato(b"%PDF-1.7 conteudo binario", "extrato.pdf")

    assert not resultado.ok
    assert resultado.lancamentos == []
    assert "OFX ou CSV" in resultado.erro


def test_arquivo_vazio_nao_prossegue():
    assert "vazio" in ler_extrato(b"", "x.csv").erro


def test_reimportacao_usa_fitid_quando_existe():
    primeira = ler_extrato(OFX.encode(), "extrato.ofx")
    segunda = ler_extrato(OFX.encode(), "extrato.ofx")

    repetidos = detectar_reimportacao(segunda.lancamentos, primeira.lancamentos)

    assert len(repetidos) == 2
    assert chave_reimportacao(repetidos[0]).startswith("fitid:")


def test_reimportacao_sem_fitid_cai_para_data_valor_historico():
    conteudo = "Data;Histórico;Valor\n10/02/2026;PIX CLIENTE;1.000,00\n".encode()
    primeira = ler_extrato(conteudo, "e.csv")
    segunda = ler_extrato(conteudo, "e.csv")

    repetidos = detectar_reimportacao(segunda.lancamentos, primeira.lancamentos)

    assert len(repetidos) == 1
    assert chave_reimportacao(repetidos[0]).startswith("dvh:")


def test_mascara_de_conta():
    assert mascarar_conta("0012345678") == "****5678"
    assert mascarar_conta("12") == "****"
