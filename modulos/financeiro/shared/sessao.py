"""
Estado de trabalho por sessão, em memória.

Extrato bancário e títulos ficam só aqui, enquanto a aba está aberta:
não são gravados em disco nem versionados (LGPD, arts. 6º e 46 — princípios
da necessidade e da segurança). Fechou a sessão ou reiniciou o serviço, o
dado vai embora e o arquivo é importado de novo.

O histórico de chaves de importação é o que permite avisar "este extrato
já foi importado" antes de conciliar duas vezes o mesmo título.
"""

from __future__ import annotations

import secrets
import threading
from datetime import datetime, timedelta
from typing import Any

VALIDADE = timedelta(hours=8)
TETO_SESSOES = 50

_sessoes: dict[str, dict[str, Any]] = {}
_trava = threading.Lock()


def nova_chave() -> str:
    return secrets.token_urlsafe(24)


def obter(chave: str) -> dict:
    """Devolve o estado da sessão, criando um vazio quando não existir."""
    agora = datetime.now()
    with _trava:
        _expirar(agora)
        estado = _sessoes.get(chave)
        if estado is None:
            if len(_sessoes) >= TETO_SESSOES:
                mais_antiga = min(_sessoes, key=lambda k: _sessoes[k]["visto_em"])
                _sessoes.pop(mais_antiga, None)
            estado = _estado_vazio()
            _sessoes[chave] = estado
        estado["visto_em"] = agora
        return estado


def limpar(chave: str) -> None:
    with _trava:
        _sessoes.pop(chave, None)


def _estado_vazio() -> dict:
    return {
        "visto_em": datetime.now(),
        "extrato": None,          # ResultadoLeitura
        "titulos": None,          # ResultadoTitulos
        "resultados": [],         # list[Resultado] do motor
        "aprovados": {},          # {lancamento_id: {"titulo_id", "momento"}}
        "chaves_importadas": [],  # detecção de reimportação
        "rps": {},                # prévias montadas na aba NFS-e
    }


def _expirar(agora: datetime) -> None:
    vencidas = [k for k, v in _sessoes.items() if agora - v["visto_em"] > VALIDADE]
    for chave in vencidas:
        _sessoes.pop(chave, None)
