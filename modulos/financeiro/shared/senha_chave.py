"""
Senha-chave de acesso ao Ambiente Financeiro — uma segunda camada, na
frente de tudo, além do controle por e-mail que já existe
(`shared/permissoes.py`). Quem não tiver essa senha não chega nem à
tela de "acesso negado" por e-mail — é bloqueado antes.

A senha nunca fica em texto puro no código nem em log: só o hash
(`werkzeug.security`) é guardado em `config/senha_chave.json`. Trocar a
senha é trocar o hash, não editar um valor legível — a mesma regra que já
vale para as credenciais do Projuris e do certificado A1 (nunca em
arquivo versionado, nunca em log).

Quem desbloqueia numa sessão de navegador fica desbloqueado enquanto essa
sessão (cookie assinado do Flask) durar — a senha não é pedida a cada
clique, só ao abrir o navegador/sessão de novo.
"""

from __future__ import annotations

import json
from pathlib import Path

from werkzeug.security import check_password_hash

RAIZ = Path(__file__).resolve().parent.parent
CAMINHO = RAIZ / "config" / "senha_chave.json"

# Nome da chave na sessão Flask — não confundir com o cookie
# "financeiro_sessao", que guarda extrato/títulos em memória e é outra
# coisa (ver shared/sessao.py).
CHAVE_SESSAO = "financeiro_desbloqueado"


def _hash_configurado() -> str:
    try:
        with open(CAMINHO, encoding="utf-8") as f:
            return str(json.load(f).get("hash") or "")
    except (FileNotFoundError, json.JSONDecodeError):
        return ""


def configurada() -> bool:
    """Se não houver hash configurado, o módulo fica inacessível por
    padrão — falhar fechado é o comportamento certo aqui, não abrir."""
    return bool(_hash_configurado())


def verificar(senha: str) -> bool:
    hash_config = _hash_configurado()
    if not hash_config or not senha:
        return False
    return check_password_hash(hash_config, senha)
