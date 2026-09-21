"""Testes do modo de operação e do log de auditoria."""

from __future__ import annotations

import json

import pytest

from ..shared import auditoria, modo


# ── Modo ─────────────────────────────────────────────────────────────

def test_conciliacao_comeca_em_simulacao(monkeypatch):
    monkeypatch.delenv("FINANCEIRO_ESCRITA_CONCILIACAO", raising=False)

    situacao = modo.situacao("conciliacao")

    assert situacao["simulacao"] is True
    assert situacao["modo"] == "simulacao"
    assert any("Endpoint de baixa" in p for p in situacao["pendencias"])


def test_variavel_de_ambiente_sozinha_nao_libera_escrita(monkeypatch):
    """Ligar a variável sem confirmar o endpoint não basta — e é assim que
    evita que alguém 'destrave' o módulo por engano."""
    monkeypatch.setenv("FINANCEIRO_ESCRITA_CONCILIACAO", "1")

    pendencias = modo.pendencias_conciliacao()

    assert any("Endpoint de baixa" in p for p in pendencias)
    assert not any("não habilitada no ambiente" in p for p in pendencias)


def test_nfse_lista_url_cadastro_e_certificado(monkeypatch):
    monkeypatch.delenv("FINANCEIRO_TRANSMISSAO_NFSE", raising=False)

    pendencias = modo.pendencias_nfse()
    texto = " ".join(pendencias)

    assert "URL do web service" in texto
    assert "Cadastro fiscal incompleto" in texto
    assert "Certificado A1" in texto


# ── Auditoria ────────────────────────────────────────────────────────

def test_registro_e_gravado_em_jsonl(log_tmp):
    auditoria.registrar(aba="conciliacao", usuario="a@b.com", acao="baixa",
                        resultado="simulado",
                        detalhe={"titulo": "T1", "valor_centavos": 1500000})

    linhas = log_tmp.read_text(encoding="utf-8").strip().splitlines()
    registro = json.loads(linhas[0])

    assert len(linhas) == 1
    assert registro["aba"] == "conciliacao"
    assert registro["detalhe"]["titulo"] == "T1"
    assert registro["momento"]


def test_log_e_apenas_acrescentado(log_tmp):
    for i in range(3):
        auditoria.registrar(aba="nfse", usuario="a@b.com", acao=f"acao{i}",
                            resultado="sucesso")

    assert len(log_tmp.read_text(encoding="utf-8").strip().splitlines()) == 3
    # Não existe função de exclusão ou edição no módulo, e é deliberado.
    assert not hasattr(auditoria, "excluir")
    assert not hasattr(auditoria, "limpar")


def test_leitura_filtra_por_aba_e_devolve_do_mais_recente(log_tmp):
    auditoria.registrar(aba="conciliacao", usuario="a", acao="antiga",
                        resultado="sucesso")
    auditoria.registrar(aba="nfse", usuario="a", acao="outra_aba",
                        resultado="sucesso")
    auditoria.registrar(aba="conciliacao", usuario="a", acao="recente",
                        resultado="sucesso")

    registros = auditoria.ler(aba="conciliacao")

    assert [r["acao"] for r in registros] == ["recente", "antiga"]


def test_aba_ou_resultado_invalido_falha_alto(log_tmp):
    with pytest.raises(ValueError):
        auditoria.registrar(aba="marketing", usuario="a", acao="x",
                            resultado="sucesso")
    with pytest.raises(ValueError):
        auditoria.registrar(aba="nfse", usuario="a", acao="x", resultado="talvez")


def test_linha_corrompida_nao_derruba_a_leitura(log_tmp):
    auditoria.registrar(aba="nfse", usuario="a", acao="boa", resultado="sucesso")
    with open(log_tmp, "a", encoding="utf-8") as f:
        f.write("{isso não é json}\n")

    registros = auditoria.ler()

    assert len(registros) == 2
    assert any(r["resposta"] == "linha ilegível no log" for r in registros)
