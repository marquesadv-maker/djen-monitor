"""
Modo de operação do módulo: simulação ou escrita.

A skill lista o que ainda está pendente (endpoints do Projuris não
confirmados, URL do WebISS não obtida, cadastro fiscal em branco).
Enquanto houver pendência, a escrita fica em **modo simulação**: mostra
o que faria, não faz — e diz isso ao usuário, em vez de silenciosamente
não fazer nada.

Este arquivo é a fonte única dessa decisão. A pendência é lida da
configuração real, não de uma chave que alguém possa virar por engano:
habilitar a escrita exige registrar o endpoint/URL **e** ligar a variável
de ambiente correspondente.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _json(caminho: Path) -> dict:
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _ligado(variavel: str) -> bool:
    return os.environ.get(variavel, "").strip().lower() in ("1", "true", "sim")


def pendencias_conciliacao() -> list[str]:
    """O que falta para a baixa no Projuris deixar de ser simulada."""
    faltas: list[str] = []

    try:
        from .projuris_financeiro import ENDPOINTS
    except ImportError:                                   # pragma: no cover
        ENDPOINTS = {}

    if not ENDPOINTS.get("baixa"):
        faltas.append(
            "Endpoint de baixa do Projuris não confirmado — inspecionar a "
            "chamada real no DevTools e registrar em shared/projuris_financeiro.py "
            "(seção 4 de references/projuris-financeiro.md)."
        )
    if not (ENDPOINTS.get("contas_receber") and ENDPOINTS.get("contas_pagar")):
        faltas.append(
            "Endpoints de contas a receber/pagar não confirmados — a leitura "
            "usa arquivo exportado do Projuris enquanto isso."
        )
    if not _ligado("FINANCEIRO_ESCRITA_CONCILIACAO"):
        faltas.append(
            "Escrita não habilitada no ambiente (FINANCEIRO_ESCRITA_CONCILIACAO). "
            "Antes de ligar: teste acompanhado em título de valor baixo, "
            "procedimento de estorno conhecido e aprovação explícita."
        )
    return faltas


def pendencias_nfse() -> list[str]:
    """O que falta para a transmissão ao WebISS deixar de ser simulada."""
    faltas: list[str] = []

    ws = _json(RAIZ / "nfse" / "config" / "webservice.json")
    ambiente = ws.get("ambiente_padrao", "homologacao")
    if not (ws.get(ambiente) or {}).get("url"):
        faltas.append(
            f"URL do web service ({ambiente}) não registrada — obter da "
            "Secretaria Municipal da Fazenda de Araguaína. URL adivinhada é "
            "pior que não transmitir."
        )

    prestador = _json(RAIZ / "nfse" / "config" / "prestador.json")
    campos = {
        "cnpj": "CNPJ do prestador",
        "inscricao_municipal": "inscrição municipal",
        "item_lc116_padrao": "item da LC 116/2003",
        "serie_rps": "série do RPS",
    }
    vazios = [rotulo for campo, rotulo in campos.items() if not prestador.get(campo)]
    if prestador.get("optante_simples") is None:
        vazios.append("opção pelo Simples Nacional")
    if prestador.get("aliquota_iss") is None and not prestador.get("regime_fixo_por_profissional"):
        vazios.append("alíquota de ISS ou declaração de regime fixo por profissional")
    if vazios:
        faltas.append("Cadastro fiscal incompleto: " + ", ".join(vazios) +
                      " — confirmar com o contador.")

    certificado = ws.get("certificado_pfx", "")
    if not certificado or not Path(certificado).exists():
        faltas.append(
            f"Certificado A1 não encontrado em {certificado or '(caminho não definido)'} "
            "— confirmar que é o e-CNPJ da sociedade, não o e-CPF do PJe."
        )
    if not os.environ.get(ws.get("senha_certificado_env", "FINANCEIRO_CERT_SENHA"), ""):
        faltas.append("Senha do certificado ausente no ambiente (variável ou cofre).")
    if not _ligado("FINANCEIRO_TRANSMISSAO_NFSE"):
        faltas.append(
            "Transmissão não habilitada no ambiente (FINANCEIRO_TRANSMISSAO_NFSE). "
            "Em Araguaína a NFS-e não se cancela por web service — só por "
            "substituição no portal."
        )
    return faltas


def situacao(aba: str) -> dict:
    """Resumo que a tela mostra no alto da página."""
    faltas = pendencias_conciliacao() if aba == "conciliacao" else pendencias_nfse()
    ambiente_nfse = _json(RAIZ / "nfse" / "config" / "webservice.json").get(
        "ambiente_padrao", "homologacao")
    return {
        "aba": aba,
        "modo": "simulacao" if faltas else "escrita",
        "simulacao": bool(faltas),
        "pendencias": faltas,
        "ambiente": ambiente_nfse if aba == "nfse" else "",
    }
