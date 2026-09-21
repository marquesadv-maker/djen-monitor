"""Testes da senha-chave — o portão na frente do módulo inteiro, além do
controle por e-mail (esse é testado em test_rotas_conciliacao.py e
test_rotas_nfse.py, que já entram desbloqueados via a fixture `cliente`).
"""

from __future__ import annotations

import json

from .conftest import SENHA_CHAVE_TESTE
from ..shared import senha_chave


# ── Portão HTTP ──────────────────────────────────────────────────────

def test_sem_desbloquear_qualquer_pagina_redireciona_para_entrar(cliente_bloqueado):
    resposta = cliente_bloqueado.get("/financeiro")
    assert resposta.status_code == 302
    assert "/financeiro/entrar" in resposta.headers["Location"]


def test_tela_de_entrada_e_saude_e_estaticos_nao_exigem_senha(cliente_bloqueado):
    assert cliente_bloqueado.get("/financeiro/entrar").status_code == 200
    assert cliente_bloqueado.get("/financeiro/saude").status_code == 200
    assert cliente_bloqueado.get("/financeiro/static/financeiro.css").status_code == 200


def test_senha_errada_nao_desbloqueia(cliente_bloqueado):
    resposta = cliente_bloqueado.post("/financeiro/entrar", data={"senha": "chuta-qualquer-coisa"})
    assert resposta.status_code == 401
    assert b"Senha incorreta" in resposta.data

    # ainda bloqueado depois da tentativa errada
    assert cliente_bloqueado.get("/financeiro").status_code == 302


def test_senha_certa_desbloqueia_e_o_desbloqueio_vale_para_o_resto_da_sessao(cliente_bloqueado):
    resposta = cliente_bloqueado.post("/financeiro/entrar", data={"senha": SENHA_CHAVE_TESTE})
    assert resposta.status_code == 302
    assert resposta.headers["Location"] == "/financeiro"

    # mesmo cliente (mesmo cookie de sessão) — não pede de novo
    seguinte = cliente_bloqueado.get("/financeiro/saude")
    assert seguinte.status_code == 200
    pagina = cliente_bloqueado.get("/financeiro")
    assert pagina.status_code in (200, 403)   # 403 só se o e-mail não tiver nível — não é o portão


def test_sair_bloqueia_de_novo(cliente_bloqueado):
    cliente_bloqueado.post("/financeiro/entrar", data={"senha": SENHA_CHAVE_TESTE})
    cliente_bloqueado.post("/financeiro/sair")
    assert cliente_bloqueado.get("/financeiro").status_code == 302


def test_tentativas_ficam_no_log_de_auditoria_sem_a_senha_em_si(cliente_bloqueado, log_tmp):
    cliente_bloqueado.post("/financeiro/entrar", data={"senha": "errada"})
    cliente_bloqueado.post("/financeiro/entrar", data={"senha": SENHA_CHAVE_TESTE})

    registros = [json.loads(l) for l in log_tmp.read_text(encoding="utf-8").splitlines()]
    tentativas = [r for r in registros if r["aba"] == "acesso"]

    assert [t["resultado"] for t in tentativas] == ["falha", "sucesso"]
    conteudo_bruto = log_tmp.read_text(encoding="utf-8")
    assert "errada" not in conteudo_bruto
    assert SENHA_CHAVE_TESTE not in conteudo_bruto


# ── shared/senha_chave.py isolado ───────────────────────────────────

def test_verificar_aceita_a_senha_certa_e_recusa_qualquer_outra(senha_chave_tmp):
    assert senha_chave.verificar(SENHA_CHAVE_TESTE) is True
    assert senha_chave.verificar("outra-coisa") is False
    assert senha_chave.verificar("") is False


def test_sem_config_falha_fechado(tmp_path, monkeypatch):
    """Arquivo de hash ausente não é 'sem senha, deixa passar' — é
    'ninguém entra', o mesmo padrão de permissoes.py."""
    monkeypatch.setattr(senha_chave, "CAMINHO", tmp_path / "nao-existe.json")
    assert senha_chave.configurada() is False
    assert senha_chave.verificar(SENHA_CHAVE_TESTE) is False
    assert senha_chave.verificar("") is False


def test_config_corrompida_falha_fechado(tmp_path, monkeypatch):
    caminho = tmp_path / "senha_chave.json"
    caminho.write_text("{isso nao e json}", encoding="utf-8")
    monkeypatch.setattr(senha_chave, "CAMINHO", caminho)
    assert senha_chave.verificar(SENHA_CHAVE_TESTE) is False


def test_configurada_reflete_a_presenca_do_hash(senha_chave_tmp):
    assert senha_chave.configurada() is True
