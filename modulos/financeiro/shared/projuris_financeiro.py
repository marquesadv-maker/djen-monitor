"""
Cliente da API do Projuris ADV para o módulo Financeiro.

Leitura liberada. Escrita bloqueada por padrão: a baixa de título é
irreversível na prática e os endpoints financeiros ainda não foram
confirmados por inspeção real (ver references/projuris-financeiro.md).

Para habilitar escrita é preciso, nesta ordem:
  1. confirmar o endpoint de baixa inspecionando a chamada real no Projuris;
  2. registrá-lo em ENDPOINTS abaixo;
  3. instanciar com permitir_escrita=True e aprovar item a item.

A senha nunca é lida de arquivo nem gravada em log — é passada em memória,
solicitada ao usuário a cada sessão.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

AUTH_HOST = "https://apigw.projurisadv.com.br"
SERVICE_HOST = "https://adv-service.projurisadv.com.br"

TENANT_SLUG = "marques-advogados3"
TENANT_ID = 53034

INTERVALO_MIN_S = 0.15          # 480 req/min
MARGEM_RENOVACAO_S = 120        # renova o token 2 min antes de expirar

# Endpoints financeiros: preencher SOMENTE com caminhos confirmados por
# inspeção da chamada real. Caminho adivinhado pode gravar no lugar errado.
ENDPOINTS: dict[str, str] = {
    # "contas_receber": "/financeiro/...",
    # "contas_pagar":   "/financeiro/...",
    # "baixa":          "/financeiro/...",
}


class EscritaBloqueada(RuntimeError):
    """Tentativa de escrita sem habilitação explícita."""


class EndpointNaoConfirmado(RuntimeError):
    """Endpoint ainda não mapeado por inspeção real."""


@dataclass
class Auditoria:
    momento: str
    usuario: str
    acao: str
    lancamento: str
    titulo: str
    valor_centavos: int
    confianca: int
    regra: str
    resultado: str
    resposta: str = ""


class ProjurisFinanceiro:
    def __init__(self, usuario: str, senha: str, *, permitir_escrita: bool = False):
        """usuario no formato 'email' — o sufixo do tenant é acrescentado aqui."""
        self._usuario = usuario if "$$" in usuario else f"{usuario}$${TENANT_SLUG}"
        self._senha = senha
        self.permitir_escrita = permitir_escrita
        self._token: Optional[str] = None
        self._expira_em: Optional[datetime] = None
        self._ultima_chamada = 0.0
        self.log: list[Auditoria] = []

    # ---------------------------------------------------------------- auth

    def _autenticar(self) -> None:
        dados = urllib.parse.urlencode({
            "grant_type": "password",
            "username": self._usuario,
            "password": self._senha,
        }).encode()

        req = urllib.request.Request(
            f"{AUTH_HOST}/auth/token",
            data=dados,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read())

        self._token = payload["access_token"]
        expira = int(payload.get("expires_in", 1500))
        self._expira_em = datetime.now() + timedelta(seconds=expira)

    def _token_valido(self) -> str:
        if (self._token is None or self._expira_em is None
                or datetime.now() >= self._expira_em - timedelta(seconds=MARGEM_RENOVACAO_S)):
            self._autenticar()
        return self._token  # type: ignore[return-value]

    # ------------------------------------------------------------ requests

    def _aguardar(self) -> None:
        decorrido = time.monotonic() - self._ultima_chamada
        if decorrido < INTERVALO_MIN_S:
            time.sleep(INTERVALO_MIN_S - decorrido)
        self._ultima_chamada = time.monotonic()

    def _chamar(self, metodo: str, caminho: str,
                params: dict | None = None,
                corpo: dict | None = None) -> Any:
        if metodo != "GET" and not self.permitir_escrita:
            raise EscritaBloqueada(
                f"{metodo} {caminho} bloqueado. A escrita no financeiro exige "
                "endpoint confirmado, teste acompanhado e habilitação explícita "
                "(permitir_escrita=True). Ver references/projuris-financeiro.md."
            )

        self._aguardar()
        url = f"{SERVICE_HOST}{caminho}"
        if params:
            url += "?" + urllib.parse.urlencode(params)

        dados = json.dumps(corpo).encode() if corpo is not None else None
        req = urllib.request.Request(
            url,
            data=dados,
            headers={
                "Authorization": f"Bearer {self._token_valido()}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method=metodo,
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            bruto = resp.read()
        return json.loads(bruto) if bruto else None

    def _endpoint(self, chave: str) -> str:
        caminho = ENDPOINTS.get(chave)
        if not caminho:
            raise EndpointNaoConfirmado(
                f"Endpoint '{chave}' ainda não mapeado. Siga o procedimento de "
                "descoberta na seção 4 de references/projuris-financeiro.md: "
                "inspecione a chamada real no DevTools e registre o caminho em "
                "ENDPOINTS. Não adivinhe o caminho."
            )
        return caminho

    # ------------------------------------------------------------- leitura

    def contas_receber(self, inicio: str, fim: str) -> list[dict]:
        """Títulos a receber com vencimento no período (AAAA-MM-DD)."""
        return self._chamar("GET", self._endpoint("contas_receber"),
                            params={"dataInicio": inicio, "dataFim": fim}) or []

    def contas_pagar(self, inicio: str, fim: str) -> list[dict]:
        """Títulos a pagar com vencimento no período (AAAA-MM-DD)."""
        return self._chamar("GET", self._endpoint("contas_pagar"),
                            params={"dataInicio": inicio, "dataFim": fim}) or []

    def baixas_do_periodo(self, inicio: str, fim: str) -> list[dict]:
        """Baixas já lançadas — evita conciliar duas vezes o mesmo título."""
        return self._chamar("GET", self._endpoint("baixas"),
                            params={"dataInicio": inicio, "dataFim": fim}) or []

    # -------------------------------------------------------------- escrita

    def registrar_baixa(self, *, titulo_id: str, data_pagamento: str,
                        valor_centavos: int, observacao: str,
                        confianca: int, regra: str,
                        lancamento_ref: str) -> dict:
        """Grava a baixa de um título. Exige permitir_escrita=True.

        Chame uma vez por título, depois de o usuário ter aprovado aquele
        item específico. Aprovação genérica não autoriza lote.
        """
        corpo = {
            "tituloId": titulo_id,
            "dataPagamento": data_pagamento,
            "valor": valor_centavos / 100,
            "observacao": observacao,
        }

        registro = Auditoria(
            momento=datetime.now().isoformat(timespec="seconds"),
            usuario=self._usuario,
            acao="baixa",
            lancamento=lancamento_ref,
            titulo=titulo_id,
            valor_centavos=valor_centavos,
            confianca=confianca,
            regra=regra,
            resultado="pendente",
        )

        try:
            resposta = self._chamar("POST", self._endpoint("baixa"), corpo=corpo)
            registro.resultado = "sucesso"
            registro.resposta = json.dumps(resposta, ensure_ascii=False)[:500]
            return resposta or {}
        except Exception as erro:
            registro.resultado = "falha"
            registro.resposta = str(erro)[:500]
            raise
        finally:
            self.log.append(registro)

    def exportar_log(self, caminho: str) -> None:
        """Grava o log de auditoria em JSON (append-only)."""
        existente = []
        try:
            with open(caminho, encoding="utf-8") as f:
                existente = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        existente.extend(vars(r) for r in self.log)
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(existente, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    print(__doc__)
    print("Endpoints confirmados:", list(ENDPOINTS) or "nenhum — ver seção 4 da referência")
