"""Fixtures dos testes do módulo Financeiro.

Nenhum teste toca a configuração real: permissões e log de auditoria são
redirecionados para arquivos temporários. Teste que escreve no
`permissoes.json` do repositório é teste que pode liberar acesso sem
ninguém perceber.
"""

from __future__ import annotations

import json

import pytest

from werkzeug.security import generate_password_hash

from ..conciliacao.api import rotas as rotas_conciliacao
from ..servidor_financeiro import criar_app
from ..shared import permissoes, senha_chave, sessao

USUARIO = "teste@marquesss.com.br"
SENHA_CHAVE_TESTE = "senha-de-teste-123"


@pytest.fixture
def permissoes_tmp(tmp_path, monkeypatch):
    """Cria um arquivo de permissões temporário e devolve um setter."""
    caminho = tmp_path / "permissoes.json"

    def definir(conciliacao: str = "negado", nfse: str = "negado",
                usuario: str = USUARIO):
        caminho.write_text(json.dumps({
            "modulo": "financeiro",
            "padrao": "negado",
            "cabecalho_identidade": "X-Usuario-Financeiro",
            "usuarios": [{"identificador": usuario,
                          "conciliacao": conciliacao, "nfse": nfse}],
        }), encoding="utf-8")

    definir()
    monkeypatch.setattr(permissoes, "CAMINHO_PERMISSOES", caminho)
    return definir


@pytest.fixture
def senha_chave_tmp(tmp_path, monkeypatch):
    """Hash de teste para a senha-chave, isolado do config/senha_chave.json
    real — o mesmo cuidado de permissoes_tmp: teste não deve depender (nem
    escrever) na senha de verdade."""
    caminho = tmp_path / "senha_chave.json"
    caminho.write_text(json.dumps({
        "hash": generate_password_hash(SENHA_CHAVE_TESTE),
    }), encoding="utf-8")
    monkeypatch.setattr(senha_chave, "CAMINHO", caminho)
    return caminho


@pytest.fixture
def log_tmp(tmp_path, monkeypatch):
    caminho = tmp_path / "auditoria.jsonl"
    monkeypatch.setenv("FINANCEIRO_LOG_AUDITORIA", str(caminho))
    return caminho


@pytest.fixture
def cliente(permissoes_tmp, log_tmp, monkeypatch):
    monkeypatch.delenv("FINANCEIRO_ESCRITA_CONCILIACAO", raising=False)
    monkeypatch.delenv("FINANCEIRO_TRANSMISSAO_NFSE", raising=False)
    monkeypatch.setenv("FINANCEIRO_SECRET_KEY", "chave-de-teste-nao-usar-em-producao")
    sessao._sessoes.clear()

    app = criar_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        c.environ_base["HTTP_X_USUARIO_FINANCEIRO"] = USUARIO
        # A maioria dos testes exercita o controle por e-mail (permissoes.py),
        # não a senha-chave — pré-desbloqueia aqui; quem quiser testar a
        # senha-chave em si usa o cliente sem sessão (ver test_senha_chave.py).
        with c.session_transaction() as sessao_navegador:
            sessao_navegador[senha_chave.CHAVE_SESSAO] = True
        yield c


@pytest.fixture
def cliente_bloqueado(permissoes_tmp, senha_chave_tmp, log_tmp, monkeypatch):
    """Como `cliente`, mas sem pré-desbloquear a senha-chave — para testar
    o próprio portão, não o que vem depois dele."""
    monkeypatch.delenv("FINANCEIRO_ESCRITA_CONCILIACAO", raising=False)
    monkeypatch.delenv("FINANCEIRO_TRANSMISSAO_NFSE", raising=False)
    monkeypatch.setenv("FINANCEIRO_SECRET_KEY", "chave-de-teste-nao-usar-em-producao")
    sessao._sessoes.clear()

    app = criar_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        c.environ_base["HTTP_X_USUARIO_FINANCEIRO"] = USUARIO
        yield c


@pytest.fixture
def regras_padrao(monkeypatch, tmp_path):
    """Regras conhecidas, para o teste não depender do JSON do repositório."""
    caminho = tmp_path / "regras.json"
    caminho.write_text(json.dumps({
        "tolerancia_dias": 5, "tolerancia_valor_pct": 2.0,
        "limiar_automatico": 90, "limiar_sugestao": 70,
        "limiar_minimo_automatico_permitido": 85,
    }), encoding="utf-8")
    monkeypatch.setattr(rotas_conciliacao, "CAMINHO_REGRAS", caminho)
    return caminho
