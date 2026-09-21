"""
Rotas da aba de NFS-e (Araguaína/TO — WebISS, ABRASF 2.02).

Monta, valida e mostra a prévia; para antes de transmitir. A transmissão
só sai do modo simulação quando a URL oficial do web service estiver
registrada, o cadastro fiscal confirmado pelo contador, o certificado
e-CNPJ disponível e a habilitação ligada no ambiente — e, mesmo assim,
uma nota por chamada, com aprovação daquela nota.

O motivo de tanto rigor está em `references/nfse/webiss-araguaina.md`:
em Araguaína a NFS-e **não pode ser cancelada por web service**, só
substituída pelo portal. Nota errada vira obrigação tributária e
documento errado na mão do cliente.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from flask import Blueprint, jsonify, make_response, render_template, request

from ...shared import auditoria, modo, sessao
from ...shared.permissoes import exigir, identificar, resumo_acesso
from .leitor_tarefas import TarefaNF, ler_tarefas
from .rps_builder import (Prestador, Servico, Tomador, alertas_sigilo,
                          base_calculo_centavos, montar_rps, previa,
                          so_digitos, validar, valor_iss_centavos,
                          valor_liquido_centavos)

RAIZ = Path(__file__).resolve().parent.parent.parent
CONFIG = RAIZ / "nfse" / "config"
COOKIE_SESSAO = "financeiro_sessao"

bp = Blueprint(
    "nfse", __name__,
    url_prefix="/financeiro/nfse",
    template_folder=str(RAIZ / "nfse" / "web" / "templates"),
    static_folder=str(RAIZ / "nfse" / "web" / "static"),
    static_url_path="/static",
)


# --------------------------------------------------------------------------
# Configuração
# --------------------------------------------------------------------------

def _json(caminho: Path) -> dict:
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def config_prestador() -> dict:
    return _json(CONFIG / "prestador.json")


def montar_prestador() -> Prestador:
    cfg = config_prestador()
    return Prestador(
        cnpj=cfg.get("cnpj", ""),
        inscricao_municipal=cfg.get("inscricao_municipal", ""),
        razao_social=cfg.get("razao_social", ""),
        optante_simples=cfg.get("optante_simples"),
        incentivador_cultural=bool(cfg.get("incentivador_cultural")),
        regime_especial=cfg.get("regime_especial", ""),
    )


def brl(centavos: int) -> str:
    inteiro = f"{abs(centavos) / 100:,.2f}".replace(",", "~").replace(".", ",").replace("~", ".")
    return f"{'-' if centavos < 0 else ''}R$ {inteiro}"


def estado_sessao() -> tuple[dict, str]:
    chave = request.cookies.get(COOKIE_SESSAO) or sessao.nova_chave()
    return sessao.obter(chave), chave


def responder(dados: dict, chave: str, status: int = 200):
    resposta = make_response(jsonify(dados), status)
    resposta.set_cookie(COOKIE_SESSAO, chave, httponly=True, samesite="Lax",
                        max_age=8 * 3600)
    return resposta


# --------------------------------------------------------------------------
# Montagem a partir da tarefa
# --------------------------------------------------------------------------

def discriminacao_padrao(tarefa: TarefaNF) -> str:
    """Modelo de `references/nfse/dados-rps.md`: descreve o serviço sem
    expor parte, processo ou matéria sensível."""
    area = tarefa.area or "—"
    competencia = f"{tarefa.competencia:%m/%Y}" if tarefa.competencia else "MM/AAAA"
    referencia = tarefa.referencia_interna or "(referência interna não informada)"
    return (f"Honorários advocatícios contratuais — {area} — "
            f"competência {competencia}. Contrato {referencia}.")


def _servico_de(dados: dict, tarefa: TarefaNF | None) -> Servico:
    cfg = config_prestador()
    competencia = dados.get("competencia") or (
        f"{tarefa.competencia:%Y-%m}" if tarefa and tarefa.competencia else "")
    try:
        ano, mes = (int(p) for p in str(competencia).replace("/", "-").split("-")[:2])
        if mes > 12:                       # veio MM-AAAA
            ano, mes = mes, ano
        competencia_data = date(ano, mes, 1)
    except (ValueError, TypeError):
        competencia_data = date(1900, 1, 1)   # inválida de propósito: bloqueia

    aliquota = dados.get("aliquota_iss", cfg.get("aliquota_iss"))
    return Servico(
        item_lc116=str(dados.get("item_lc116") or cfg.get("item_lc116_padrao") or ""),
        discriminacao=dados.get("discriminacao") or (
            discriminacao_padrao(tarefa) if tarefa else ""),
        valor_centavos=int(dados.get("valor_centavos")
                           or (tarefa.valor_centavos if tarefa else 0)),
        competencia=competencia_data,
        aliquota_iss=float(aliquota) if aliquota not in (None, "") else None,
        iss_retido=bool(dados.get("iss_retido")),
        valor_deducoes_centavos=int(dados.get("valor_deducoes_centavos") or 0),
        valor_desconto_centavos=int(dados.get("valor_desconto_centavos") or 0),
        retencoes={k: int(v) for k, v in (dados.get("retencoes") or {}).items() if v},
        regime_fixo_declarado=bool(dados.get("regime_fixo_declarado")
                                   or cfg.get("regime_fixo_por_profissional")),
    )


def _tomador_de(dados: dict, tarefa: TarefaNF | None) -> Tomador:
    endereco = dados.get("endereco") or {}
    return Tomador(
        documento=dados.get("documento") or (tarefa.tomador_documento if tarefa else ""),
        nome=dados.get("nome") or (tarefa.tomador_nome if tarefa else ""),
        logradouro=endereco.get("logradouro", ""),
        numero=endereco.get("numero", ""),
        bairro=endereco.get("bairro", ""),
        municipio_ibge=endereco.get("municipio_ibge", ""),
        uf=endereco.get("uf", ""),
        cep=endereco.get("cep", ""),
        email=dados.get("email") or (tarefa.email if tarefa else ""),
    )


def _tarefa_json(tarefa: TarefaNF) -> dict:
    return {
        "tarefa": tarefa.tarefa,
        "tomador_nome": tarefa.tomador_nome,
        "tomador_documento": f"****{tarefa.tomador_documento[-4:]}"
                             if len(tarefa.tomador_documento) >= 4 else "",
        "valor": brl(tarefa.valor_centavos),
        "valor_centavos": tarefa.valor_centavos,
        "competencia": f"{tarefa.competencia:%m/%Y}" if tarefa.competencia else "",
        "referencia_interna": tarefa.referencia_interna,
        "area": tarefa.area,
        "responsavel": tarefa.responsavel,
        "faltando": tarefa.faltando,
        "pronta": not tarefa.faltando,
    }


# --------------------------------------------------------------------------
# Páginas
# --------------------------------------------------------------------------

@bp.get("/")
@exigir("nfse", "leitura")
def pagina_nfse():
    cfg = config_prestador()
    return render_template(
        "nfse.html",
        acesso=resumo_acesso(),
        situacao=modo.situacao("nfse"),
        prestador={k: v for k, v in cfg.items() if not k.startswith("_")},
    )


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------

@bp.get("/api/estado")
@exigir("nfse", "leitura")
def api_estado():
    estado, chave = estado_sessao()
    cfg = config_prestador()
    ws = _json(CONFIG / "webservice.json")
    return responder({
        "situacao": modo.situacao("nfse"),
        "acesso": resumo_acesso(),
        "prestador": {
            "razao_social": cfg.get("razao_social", ""),
            "cnpj": f"****{so_digitos(cfg.get('cnpj', ''))[-4:]}" if cfg.get("cnpj") else "",
            "inscricao_municipal": cfg.get("inscricao_municipal", ""),
            "item_lc116_padrao": cfg.get("item_lc116_padrao", ""),
            "aliquota_iss": cfg.get("aliquota_iss"),
            "regime_fixo_por_profissional": cfg.get("regime_fixo_por_profissional"),
            "serie_rps": cfg.get("serie_rps", ""),
            "confirmado_em": cfg.get("confirmado_em", ""),
        },
        "ambiente": ws.get("ambiente_padrao", "homologacao"),
        "tarefas": len(estado["rps"].get("tarefas", [])),
    }, chave)


@bp.post("/api/tarefas")
@exigir("nfse", "operacao")
def api_tarefas():
    estado, chave = estado_sessao()
    arquivo = request.files.get("arquivo")
    if not arquivo:
        return responder({"erro": "Nenhum arquivo enviado."}, chave, 400)

    resultado = ler_tarefas(arquivo.read(), arquivo.filename or "")
    if resultado.erro:
        return responder({"erro": resultado.erro}, chave, 422)

    estado["rps"]["tarefas"] = resultado.tarefas
    auditoria.registrar(
        aba="nfse", usuario=identificar(), acao="importar_tarefas",
        resultado="sucesso",
        detalhe={"arquivo": arquivo.filename, "tarefas": len(resultado.tarefas),
                 "ambiente": _json(CONFIG / "webservice.json").get("ambiente_padrao", "")},
    )
    return responder({
        "resumo": resultado.resumo(),
        "avisos": resultado.avisos,
        "tarefas": [_tarefa_json(t) for t in resultado.tarefas],
    }, chave)


@bp.post("/api/previa")
@exigir("nfse", "operacao")
def api_previa():
    """Monta e valida o RPS de **uma** tarefa e devolve a prévia. Não transmite."""
    estado, chave = estado_sessao()
    corpo = request.get_json(silent=True) or {}

    tarefas = {t.tarefa: t for t in estado["rps"].get("tarefas", [])}
    tarefa = tarefas.get(str(corpo.get("tarefa", "")))

    prestador = montar_prestador()
    tomador = _tomador_de(corpo.get("tomador") or {}, tarefa)
    servico = _servico_de(corpo.get("servico") or {}, tarefa)

    bloqueios = validar(prestador, tomador, servico)
    avisos = alertas_sigilo(servico.discriminacao)

    xml = ""
    if not bloqueios:
        try:
            xml = montar_rps(prestador, tomador, servico, numero_rps=0,
                             serie=config_prestador().get("serie_rps", ""))
        except ValueError as erro:
            bloqueios.append(str(erro))

    auditoria.registrar(
        aba="nfse", usuario=identificar(), acao="montar_previa",
        resultado="sucesso" if not bloqueios else "bloqueado",
        detalhe={"tarefa": tarefa.tarefa if tarefa else "(avulsa)",
                 "tomador_documento": f"****{so_digitos(tomador.documento)[-4:]}"
                                      if tomador.documento else "",
                 "valor_centavos": servico.valor_centavos,
                 "competencia": servico.competencia.isoformat(),
                 "ambiente": _json(CONFIG / "webservice.json").get("ambiente_padrao", "")},
        resposta="; ".join(bloqueios),
    )

    return responder({
        "previa": previa(prestador, tomador, servico,
                         origem=(f"tarefa {tarefa.tarefa} · contrato "
                                 f"{tarefa.referencia_interna or '—'}") if tarefa else ""),
        "bloqueios": bloqueios,
        "alertas_sigilo": avisos,
        "pode_transmitir": not bloqueios,
        "valores": {
            "bruto": brl(servico.valor_centavos),
            "base_calculo": brl(base_calculo_centavos(servico)),
            "iss": brl(valor_iss_centavos(servico)),
            "liquido": brl(valor_liquido_centavos(servico)),
            "iss_retido": servico.iss_retido,
            "regime_fixo": servico.regime_fixo_declarado,
        },
        "xml_montado": bool(xml),
        "situacao": modo.situacao("nfse"),
    }, chave)


@bp.post("/api/transmitir")
@exigir("nfse", "gravacao")
def api_transmitir():
    """Transmite **uma** nota ao WebISS. Em simulação, diz o que faria.

    Antes de qualquer envio real: `ConsultarNfsePorRps`. Se já existe nota
    para aquele RPS, não transmite de novo — é assim que nota duplicada
    nasce quando a tarefa não foi concluída no Projuris.
    """
    estado, chave = estado_sessao()
    corpo = request.get_json(silent=True) or {}

    if isinstance(corpo.get("tarefa"), list) or corpo.get("lote"):
        return responder({
            "erro": ("Transmissão é uma nota por chamada. Lote dá menos "
                     "rastreabilidade e pode ficar parcialmente processado."),
        }, chave, 400)

    tarefas = {t.tarefa: t for t in estado["rps"].get("tarefas", [])}
    tarefa = tarefas.get(str(corpo.get("tarefa", "")))

    prestador = montar_prestador()
    tomador = _tomador_de(corpo.get("tomador") or {}, tarefa)
    servico = _servico_de(corpo.get("servico") or {}, tarefa)

    bloqueios = validar(prestador, tomador, servico)
    if bloqueios:
        auditoria.registrar(aba="nfse", usuario=identificar(), acao="transmitir",
                            resultado="bloqueado",
                            detalhe={"tarefa": corpo.get("tarefa", "")},
                            resposta="; ".join(bloqueios))
        return responder({
            "erro": "A nota não passou na validação — não transmiti.",
            "bloqueios": bloqueios,
        }, chave, 422)

    ws = _json(CONFIG / "webservice.json")
    ambiente = ws.get("ambiente_padrao", "homologacao")
    detalhe = {
        "tarefa": tarefa.tarefa if tarefa else "(avulsa)",
        "tomador_documento": f"****{so_digitos(tomador.documento)[-4:]}",
        "valor_centavos": servico.valor_centavos,
        "competencia": servico.competencia.isoformat(),
        "serie_rps": config_prestador().get("serie_rps", ""),
        "ambiente": ambiente,
    }

    pendencias = modo.pendencias_nfse()
    if pendencias:
        auditoria.registrar(aba="nfse", usuario=identificar(), acao="transmitir",
                            resultado="simulado", detalhe=detalhe,
                            resposta="; ".join(pendencias))
        return responder({
            "simulacao": True,
            "ambiente": ambiente,
            "mensagem": (
                f"Modo simulação: **não transmiti**. Enviaria uma nota de "
                f"{brl(servico.valor_centavos)} para {tomador.nome}, "
                f"competência {servico.competencia:%m/%Y}, no ambiente de {ambiente}."
            ),
            "enviaria": detalhe,
            "pendencias": pendencias,
        }, chave, 200)

    # Caminho real: só alcançável com URL registrada, cadastro confirmado,
    # certificado presente e habilitação ligada. Mantido completo para que a
    # virada de chave não precise de código novo escrito às pressas.
    import os

    from .nfse_webiss import ControleNumeracao, NfseWebISS

    numeracao = ControleNumeracao(CONFIG / "numeracao.json")
    serie = config_prestador().get("serie_rps", "")
    numero = numeracao.proximo(serie)

    servico_ws = NfseWebISS(
        ambiente=ambiente,
        certificado_pfx=ws.get("certificado_pfx", ""),
        senha_certificado=os.environ.get(
            ws.get("senha_certificado_env", "FINANCEIRO_CERT_SENHA"), ""),
        numeracao=numeracao,
        permitir_transmissao=True,
    )

    try:
        ja_emitida = servico_ws.consultar_por_rps(
            numero, serie, prestador.cnpj, prestador.inscricao_municipal)
        if ja_emitida:
            return responder({
                "erro": f"Já existe NFS-e para o RPS {numero}/{serie}. Não transmiti.",
                "nfse": ja_emitida,
            }, chave, 409)

        xml = montar_rps(prestador, tomador, servico, numero_rps=numero, serie=serie)
        resposta = servico_ws.gerar_nfse(
            xml_rps=xml, numero_rps=numero, serie=serie,
            tarefa_origem=detalhe["tarefa"],
            tomador_documento=so_digitos(tomador.documento),
            valor_centavos=servico.valor_centavos,
            usuario=identificar(),
        )
    except Exception as erro:
        auditoria.registrar(aba="nfse", usuario=identificar(), acao="transmitir",
                            resultado="falha", detalhe={**detalhe, "numero_rps": numero},
                            resposta=str(erro))
        return responder({"erro": f"A transmissão falhou: {erro}",
                          "transmitido": False}, chave, 502)

    numeracao.confirmar(serie, numero)     # só depois do sucesso
    auditoria.registrar(aba="nfse", usuario=identificar(), acao="transmitir",
                        resultado="sucesso",
                        detalhe={**detalhe, "numero_rps": numero,
                                 "numero_nfse": (resposta or {}).get("numero", ""),
                                 "codigo_verificacao": (resposta or {}).get(
                                     "codigo_verificacao", "")},
                        resposta=json.dumps(resposta, ensure_ascii=False)[:500])
    return responder({"transmitido": True, "numero_rps": numero,
                      "ambiente": ambiente, "resposta": resposta,
                      "lembrete": ("Conclua a tarefa no Projuris e grave número "
                                   "e código de verificação. Se a gravação no "
                                   "ERP falhar, a nota existe no fisco e não "
                                   "no sistema.")}, chave)


@bp.get("/api/auditoria")
@exigir("nfse", "leitura")
def api_auditoria():
    _, chave = estado_sessao()
    return responder({"registros": auditoria.ler(limite=100, aba="nfse")}, chave)
