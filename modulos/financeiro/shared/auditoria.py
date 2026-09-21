"""
Log de auditoria do módulo Financeiro — único, append-only, sem exclusão
pela interface.

Vale para as duas abas. Regra 6 da skill: tudo que é gravado fica
registrado; sem log, não grave. Por isso `registrar` é chamado também
quando a ação é recusada ou simulada — o que não aconteceu e por quê é
tão auditável quanto o que aconteceu.

O formato é JSONL (uma linha por registro): acrescentar nunca reescreve
o que já está no arquivo, então um erro no meio da gravação não corrompe
o histórico anterior.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

RAIZ = Path(__file__).resolve().parent.parent
CAMINHO_PADRAO = RAIZ / "dados" / "auditoria" / "financeiro.jsonl"

ABAS = ("conciliacao", "nfse", "acesso")
RESULTADOS = ("sucesso", "falha", "simulado", "recusado", "bloqueado")

_trava = threading.Lock()


def caminho_log() -> Path:
    """Permite apontar o log para fora do repositório em produção."""
    return Path(os.environ.get("FINANCEIRO_LOG_AUDITORIA", CAMINHO_PADRAO))


def registrar(*, aba: str, usuario: str, acao: str, resultado: str,
              detalhe: dict[str, Any] | None = None,
              resposta: str = "") -> dict:
    """Acrescenta um registro ao log e devolve o que foi gravado.

    `detalhe` carrega o que cada aba precisa provar depois:

    - conciliação: lançamento, título, valor, confiança, regra
    - NFS-e: tarefa de origem, tomador, valor, RPS (número/série),
      NFS-e (número/código de verificação) e **ambiente**
    - acesso: tentativa de entrada na senha-chave do módulo (sem a senha
      em si, nunca)

    O campo ambiente é o que separa nota de teste de nota real quando o
    log for revisto meses depois — por isso a aba nfse deve sempre enviá-lo.
    """
    if aba not in ABAS:
        raise ValueError(f"Aba inválida: {aba!r}. Use {ABAS}.")
    if resultado not in RESULTADOS:
        raise ValueError(f"Resultado inválido: {resultado!r}. Use {RESULTADOS}.")

    registro = {
        "momento": datetime.now().isoformat(timespec="seconds"),
        "aba": aba,
        "usuario": usuario or "(não identificado)",
        "acao": acao,
        "resultado": resultado,
        "detalhe": detalhe or {},
        "resposta": (resposta or "")[:1000],
    }

    destino = caminho_log()
    linha = json.dumps(registro, ensure_ascii=False, default=str)
    with _trava:
        destino.parent.mkdir(parents=True, exist_ok=True)
        with open(destino, "a", encoding="utf-8") as f:
            f.write(linha + "\n")
            f.flush()
            os.fsync(f.fileno())
    return registro


def ler(limite: int = 200, aba: str | None = None) -> list[dict]:
    """Últimos registros, do mais recente para o mais antigo.

    Só leitura: não existe função de exclusão ou edição neste módulo, e
    isso é deliberado.
    """
    registros = [r for r in _iterar() if aba is None or r.get("aba") == aba]
    return list(reversed(registros[-limite:]))


def _iterar() -> Iterator[dict]:
    destino = caminho_log()
    if not destino.exists():
        return
    with open(destino, encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if not linha:
                continue
            try:
                yield json.loads(linha)
            except json.JSONDecodeError:
                # Linha corrompida não derruba a leitura do restante do log.
                yield {"momento": "", "aba": "", "usuario": "", "acao": "",
                       "resultado": "falha", "detalhe": {},
                       "resposta": "linha ilegível no log"}
