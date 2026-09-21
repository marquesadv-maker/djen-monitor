"""Testes de ponta a ponta da aba de NFS-e.

O ponto central: cadastro fiscal em branco **bloqueia** a emissão, e nota
válida ainda assim não é transmitida enquanto a URL oficial do web service
não estiver registrada. A tela diz o que enviaria; não envia.
"""

from __future__ import annotations

import io
import json

import pytest

from ..nfse.api import rotas as rotas_nfse

TAREFAS = (
    "Tarefa;Cliente;CNPJ;Valor;Competência;Contrato;Área\n"
    "8821;Cliente Exemplo Ltda;11.444.777/0001-61;5.000,00;08/2026;REF-2026-014;Trabalhista\n"
    "8822;Cliente Sem Documento;;3.000,00;08/2026;;Cível\n"
).encode()

ENDERECO = {
    "logradouro": "Rua A, 100", "bairro": "Centro",
    "municipio_ibge": "1702109", "uf": "TO", "cep": "77800000",
}


@pytest.fixture
def config_nfse(tmp_path, monkeypatch):
    """Cadastro fiscal completo, só para os testes — o do repositório
    continua em branco de propósito."""
    destino = tmp_path / "config"
    destino.mkdir()
    (destino / "prestador.json").write_text(json.dumps({
        "cnpj": "11222333000181",
        "inscricao_municipal": "12345",
        "razao_social": "Escritório de Teste",
        "optante_simples": True,
        "item_lc116_padrao": "1701",
        "aliquota_iss": 2.0,
        "serie_rps": "A",
        "municipio_incidencia_ibge": "1702109",
    }), encoding="utf-8")
    (destino / "webservice.json").write_text(json.dumps({
        "homologacao": {"url": "", "confirmado_em": "", "origem": ""},
        "producao": {"url": "", "confirmado_em": "", "origem": ""},
        "ambiente_padrao": "homologacao",
    }), encoding="utf-8")
    monkeypatch.setattr(rotas_nfse, "CONFIG", destino)
    return destino


def _importar_tarefas(cliente):
    return cliente.post("/financeiro/nfse/api/tarefas",
                        data={"arquivo": (io.BytesIO(TAREFAS), "tarefas.csv")},
                        content_type="multipart/form-data")


# ── Permissões ───────────────────────────────────────────────────────

def test_padrao_e_negar(cliente):
    assert cliente.get("/financeiro/nfse/").status_code == 403
    assert cliente.get("/financeiro/nfse/api/estado").status_code == 403


def test_transmitir_exige_gravacao(cliente, permissoes_tmp, config_nfse):
    permissoes_tmp(nfse="operacao")
    _importar_tarefas(cliente)
    resposta = cliente.post("/financeiro/nfse/api/transmitir",
                            json={"tarefa": "8821"})
    assert resposta.status_code == 403


# ── Tarefas ──────────────────────────────────────────────────────────

def test_importa_tarefas_e_aponta_o_que_falta(cliente, permissoes_tmp):
    permissoes_tmp(nfse="operacao")

    dados = _importar_tarefas(cliente).get_json()

    assert "Li 2 tarefa(s)" in dados["resumo"]
    primeira, segunda = dados["tarefas"]
    assert primeira["pronta"] is True
    assert primeira["tomador_documento"] == "****0161"   # documento mascarado
    assert primeira["competencia"] == "08/2026"
    assert "CNPJ/CPF do tomador" in segunda["faltando"]


# ── Prévia ───────────────────────────────────────────────────────────

def test_cadastro_fiscal_em_branco_bloqueia_a_emissao(cliente, permissoes_tmp):
    permissoes_tmp(nfse="operacao")
    _importar_tarefas(cliente)

    dados = cliente.post("/financeiro/nfse/api/previa", json={
        "tarefa": "8821",
        "tomador": {"endereco": ENDERECO},
        "servico": {"competencia": "2026-08"},
    }).get_json()

    assert dados["pode_transmitir"] is False
    texto = " ".join(dados["bloqueios"])
    assert "CNPJ do prestador" in texto
    assert "Inscrição municipal" in texto


def test_previa_completa_calcula_iss_e_liquido(cliente, permissoes_tmp, config_nfse):
    permissoes_tmp(nfse="operacao")
    _importar_tarefas(cliente)

    dados = cliente.post("/financeiro/nfse/api/previa", json={
        "tarefa": "8821",
        "tomador": {"endereco": ENDERECO},
        "servico": {"competencia": "2026-08"},
    }).get_json()

    assert dados["bloqueios"] == []
    assert dados["pode_transmitir"] is True
    assert dados["valores"]["bruto"] == "R$ 5.000,00"
    assert dados["valores"]["iss"] == "R$ 100,00"
    # ISS não retido: o líquido continua igual ao bruto.
    assert dados["valores"]["liquido"] == "R$ 5.000,00"
    assert "Contrato REF-2026-014" in dados["previa"]


def test_iss_retido_reduz_o_liquido_e_nao_o_valor_do_servico(cliente, permissoes_tmp,
                                                             config_nfse):
    permissoes_tmp(nfse="operacao")
    _importar_tarefas(cliente)

    dados = cliente.post("/financeiro/nfse/api/previa", json={
        "tarefa": "8821",
        "tomador": {"endereco": ENDERECO},
        "servico": {"competencia": "2026-08", "iss_retido": True},
    }).get_json()

    assert dados["valores"]["bruto"] == "R$ 5.000,00"
    assert dados["valores"]["liquido"] == "R$ 4.900,00"


def test_discriminacao_com_processo_gera_alerta_de_sigilo(cliente, permissoes_tmp,
                                                          config_nfse):
    permissoes_tmp(nfse="operacao")
    _importar_tarefas(cliente)

    dados = cliente.post("/financeiro/nfse/api/previa", json={
        "tarefa": "8821",
        "tomador": {"endereco": ENDERECO},
        "servico": {
            "competencia": "2026-08",
            "discriminacao": ("Honorários — processo 0000123-45.2026.5.10.0821 "
                              "— reclamante João"),
        },
    }).get_json()

    alertas = " ".join(dados["alertas_sigilo"])
    assert "número de processo" in alertas
    assert "identificar a parte" in alertas


def test_item_lc116_com_ponto_e_recusado(cliente, permissoes_tmp, config_nfse):
    permissoes_tmp(nfse="operacao")
    _importar_tarefas(cliente)

    dados = cliente.post("/financeiro/nfse/api/previa", json={
        "tarefa": "8821",
        "tomador": {"endereco": ENDERECO},
        "servico": {"competencia": "2026-08", "item_lc116": "17.01"},
    }).get_json()

    assert any("sem ponto" in b for b in dados["bloqueios"])


def test_competencia_futura_e_recusada(cliente, permissoes_tmp, config_nfse):
    permissoes_tmp(nfse="operacao")
    _importar_tarefas(cliente)

    dados = cliente.post("/financeiro/nfse/api/previa", json={
        "tarefa": "8821",
        "tomador": {"endereco": ENDERECO},
        "servico": {"competencia": "2099-01"},
    }).get_json()

    assert any("futura" in b for b in dados["bloqueios"])


# ── Transmissão ──────────────────────────────────────────────────────

def test_transmissao_em_simulacao_diz_o_que_enviaria(cliente, permissoes_tmp,
                                                     config_nfse, log_tmp):
    permissoes_tmp(nfse="gravacao")
    _importar_tarefas(cliente)

    dados = cliente.post("/financeiro/nfse/api/transmitir", json={
        "tarefa": "8821",
        "tomador": {"endereco": ENDERECO},
        "servico": {"competencia": "2026-08"},
    }).get_json()

    assert dados["simulacao"] is True
    assert "não transmiti" in dados["mensagem"]
    assert dados["enviaria"]["ambiente"] == "homologacao"
    assert any("URL do web service" in p for p in dados["pendencias"])

    registros = [json.loads(l) for l in log_tmp.read_text(encoding="utf-8").splitlines()]
    transmissao = [r for r in registros if r["acao"] == "transmitir"]
    # O ambiente fica no log: é o que separa nota de teste de nota real.
    assert transmissao[0]["resultado"] == "simulado"
    assert transmissao[0]["detalhe"]["ambiente"] == "homologacao"


def test_nota_invalida_nao_chega_a_transmitir(cliente, permissoes_tmp, config_nfse):
    permissoes_tmp(nfse="gravacao")
    _importar_tarefas(cliente)

    resposta = cliente.post("/financeiro/nfse/api/transmitir", json={
        "tarefa": "8822",                       # tarefa sem documento do tomador
        "tomador": {"endereco": ENDERECO},
        "servico": {"competencia": "2026-08"},
    })

    assert resposta.status_code == 422
    assert "não transmiti" in resposta.get_json()["erro"]


def test_lote_e_recusado(cliente, permissoes_tmp, config_nfse):
    permissoes_tmp(nfse="gravacao")
    _importar_tarefas(cliente)

    resposta = cliente.post("/financeiro/nfse/api/transmitir",
                            json={"tarefa": ["8821", "8822"]})

    assert resposta.status_code == 400
    assert "uma nota por chamada" in resposta.get_json()["erro"]
