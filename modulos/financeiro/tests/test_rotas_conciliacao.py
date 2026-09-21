"""Testes de ponta a ponta da aba de conciliação.

O que estes testes garantem, e que é o núcleo da skill: padrão negar,
aprovação item a item, e escrita que **não acontece** enquanto houver
pendência de implantação — respondendo o que faria, não silêncio.
"""

from __future__ import annotations

import io
import json

EXTRATO = (
    "Data;Histórico;Documento;Valor;Tipo\n"
    "10/02/2026;TED TRANSPORTES SAO JOAO LTDA;12345678000190;15.000,00;C\n"
    "11/02/2026;PAGAMENTO LOCADORA CENTRAL;;3.500,00;D\n"
    "12/02/2026;CREDITO NAO IDENTIFICADO;;999,00;C\n"
).encode()

TITULOS = (
    "Código;Tipo;Cliente/Fornecedor;CPF/CNPJ;Valor;Vencimento;Situação\n"
    "T1;Receber;Transportes Sao Joao Ltda;12345678000190;15.000,00;10/02/2026;Em aberto\n"
    "T2;Pagar;Locadora Central;;3.500,00;11/02/2026;Em aberto\n"
).encode()


def _arquivo(conteudo: bytes, nome: str) -> dict:
    return {"arquivo": (io.BytesIO(conteudo), nome)}


def _importar_tudo(cliente):
    cliente.post("/financeiro/conciliacao/api/extrato",
                 data=_arquivo(EXTRATO, "extrato.csv"),
                 content_type="multipart/form-data")
    cliente.post("/financeiro/conciliacao/api/titulos",
                 data=_arquivo(TITULOS, "titulos.csv"),
                 content_type="multipart/form-data")


# ── Permissões ───────────────────────────────────────────────────────

def test_padrao_e_negar(cliente):
    assert cliente.get("/financeiro/conciliacao/").status_code == 403
    resposta = cliente.get("/financeiro/conciliacao/api/estado")
    assert resposta.status_code == 403
    assert resposta.get_json()["erro"] == "acesso_negado"


def test_url_direta_nao_burla_o_controle(cliente, permissoes_tmp):
    permissoes_tmp(conciliacao="leitura")
    # Nível de leitura não pode importar extrato, mesmo chamando a API na mão.
    resposta = cliente.post("/financeiro/conciliacao/api/extrato",
                            data=_arquivo(EXTRATO, "extrato.csv"),
                            content_type="multipart/form-data")
    assert resposta.status_code == 403
    assert resposta.get_json()["nivel_exigido"] == "operacao"


def test_leitura_abre_a_pagina_e_o_painel_vazio(cliente, permissoes_tmp):
    permissoes_tmp(conciliacao="leitura")
    assert cliente.get("/financeiro/conciliacao/dashboard").status_code == 200

    painel = cliente.get("/financeiro/conciliacao/api/painel").get_json()
    assert painel["vazio"] is True
    assert painel["kpis"]["margem"] == "—"


# ── Fluxo de conciliação ─────────────────────────────────────────────

def test_importa_concilia_e_explica_cada_item(cliente, permissoes_tmp, regras_padrao):
    permissoes_tmp(conciliacao="operacao")

    extrato = cliente.post("/financeiro/conciliacao/api/extrato",
                           data=_arquivo(EXTRATO, "extrato.csv"),
                           content_type="multipart/form-data").get_json()
    assert "Li 3 lançamento(s)" in extrato["resumo"]

    titulos = cliente.post("/financeiro/conciliacao/api/titulos",
                           data=_arquivo(TITULOS, "titulos.csv"),
                           content_type="multipart/form-data").get_json()
    assert "Li 2 título(s)" in titulos["resumo"]

    dados = cliente.post("/financeiro/conciliacao/api/conciliar").get_json()

    assert dados["resumo"]["total_lancamentos"] == 3
    assert dados["resumo"]["automatico"]["qtd"] == 2
    assert len(dados["divergencia"]) == 1
    assert dados["divergencia"][0]["tipo_divergencia"] == "sem_titulo"
    # Toda linha carrega o porquê, não só a porcentagem.
    assert all(item["explicacao"] for item in dados["automatico"])
    assert dados["automatico"][0]["regra"].startswith("R1")


def test_conciliar_sem_titulos_explica_em_vez_de_quebrar(cliente, permissoes_tmp):
    permissoes_tmp(conciliacao="operacao")
    cliente.post("/financeiro/conciliacao/api/extrato",
                 data=_arquivo(EXTRATO, "extrato.csv"),
                 content_type="multipart/form-data")

    resposta = cliente.post("/financeiro/conciliacao/api/conciliar")

    assert resposta.status_code == 409
    assert "endpoints financeiros do Projuris" in resposta.get_json()["erro"]


def test_documento_aparece_mascarado(cliente, permissoes_tmp, regras_padrao):
    permissoes_tmp(conciliacao="operacao")
    _importar_tudo(cliente)

    dados = cliente.post("/financeiro/conciliacao/api/conciliar").get_json()
    item = dados["automatico"][0]

    assert item["documento"] == "****0190"
    assert "12345678000190" not in json.dumps(dados, ensure_ascii=False)


def test_painel_reflete_a_conciliacao(cliente, permissoes_tmp, regras_padrao):
    permissoes_tmp(conciliacao="operacao")
    _importar_tudo(cliente)
    cliente.post("/financeiro/conciliacao/api/conciliar")

    painel = cliente.get("/financeiro/conciliacao/api/painel").get_json()

    assert painel["vazio"] is False
    assert painel["kpis"]["entrada"] == "R$ 15.000,00"
    assert painel["kpis"]["saida"] == "R$ 3.500,00"
    assert painel["kpis"]["saldo"] == "R$ 11.500,00"


def test_filtro_sem_dado_mostra_estado_vazio(cliente, permissoes_tmp, regras_padrao):
    permissoes_tmp(conciliacao="operacao")
    _importar_tudo(cliente)
    cliente.post("/financeiro/conciliacao/api/conciliar")

    painel = cliente.get("/financeiro/conciliacao/api/painel?ano=2019").get_json()

    assert painel["vazio"] is True
    assert painel["filtros_ativos"] is True


# ── Escrita ──────────────────────────────────────────────────────────

def test_baixa_exige_nivel_de_gravacao(cliente, permissoes_tmp, regras_padrao):
    permissoes_tmp(conciliacao="operacao")
    _importar_tudo(cliente)
    cliente.post("/financeiro/conciliacao/api/conciliar")

    resposta = cliente.post("/financeiro/conciliacao/api/baixa",
                            json={"lancamento_id": "L00001"})
    assert resposta.status_code == 403


def test_baixa_sem_aprovacao_previa_e_recusada(cliente, permissoes_tmp, regras_padrao):
    permissoes_tmp(conciliacao="gravacao")
    _importar_tudo(cliente)
    cliente.post("/financeiro/conciliacao/api/conciliar")

    resposta = cliente.post("/financeiro/conciliacao/api/baixa",
                            json={"lancamento_id": "L00001"})

    assert resposta.status_code == 409
    assert "aprovado" in resposta.get_json()["erro"]


def test_lote_e_recusado_mesmo_com_permissao(cliente, permissoes_tmp, regras_padrao):
    permissoes_tmp(conciliacao="gravacao")
    _importar_tudo(cliente)
    cliente.post("/financeiro/conciliacao/api/conciliar")

    resposta = cliente.post("/financeiro/conciliacao/api/baixa",
                            json={"lancamento_id": ["L00001", "L00002"]})

    assert resposta.status_code == 400
    assert "item a item" in resposta.get_json()["erro"]


def test_baixa_em_simulacao_diz_o_que_faria_e_nao_grava(cliente, permissoes_tmp,
                                                       regras_padrao, log_tmp):
    permissoes_tmp(conciliacao="gravacao")
    _importar_tudo(cliente)
    cliente.post("/financeiro/conciliacao/api/conciliar")
    cliente.post("/financeiro/conciliacao/api/aprovar",
                 json={"lancamento_id": "L00001"})

    dados = cliente.post("/financeiro/conciliacao/api/baixa",
                         json={"lancamento_id": "L00001"}).get_json()

    assert dados["simulacao"] is True
    assert "não gravei" in dados["mensagem"]
    assert dados["gravaria"]["titulo"] == "T1"
    assert any("Endpoint de baixa" in p for p in dados["pendencias"])

    registros = [json.loads(l) for l in log_tmp.read_text(encoding="utf-8").splitlines()]
    baixa = [r for r in registros if r["acao"] == "baixa"]
    assert baixa and baixa[0]["resultado"] == "simulado"


def test_log_de_auditoria_registra_importacao_e_aprovacao(cliente, permissoes_tmp,
                                                          regras_padrao, log_tmp):
    permissoes_tmp(conciliacao="gravacao")
    _importar_tudo(cliente)
    cliente.post("/financeiro/conciliacao/api/conciliar")
    cliente.post("/financeiro/conciliacao/api/aprovar",
                 json={"lancamento_id": "L00001"})

    acoes = [json.loads(l)["acao"]
             for l in log_tmp.read_text(encoding="utf-8").splitlines()]

    assert acoes[:4] == ["importar_extrato", "importar_titulos", "conciliar",
                         "aprovar_sugestao"]
