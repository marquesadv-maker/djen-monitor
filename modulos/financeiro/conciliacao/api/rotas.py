"""
Rotas da aba de Conciliação Bancária.

Leitura é livre para quem tem nível `leitura`; aceitar sugestão exige
`operacao`; gravar baixa exige `gravacao` **e** que não haja pendência
de implantação (shared/modo.py). Enquanto houver pendência, a rota de
baixa responde o que faria, registra no log como `simulado` e não grava.

Aprovação é item a item: a rota recebe um lançamento por chamada e
recusa lista. "Pode ir" genérico não autoriza lote.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from flask import (Blueprint, jsonify, make_response, render_template,
                   request)

from ...shared import auditoria, modo, sessao
from ...shared.formatacao import brl
from ...shared.permissoes import exigir, identificar, resumo_acesso
from .agregador import Filtros, montar_painel, pct
from .leitor_extrato import (chave_reimportacao, detectar_reimportacao,
                             ler_extrato)
from .leitor_titulos import ler_titulos
from .motor_conciliacao import conciliar, resumir

RAIZ = Path(__file__).resolve().parent.parent.parent
CAMINHO_REGRAS = RAIZ / "conciliacao" / "config" / "regras.json"

COOKIE_SESSAO = "financeiro_sessao"

bp = Blueprint(
    "conciliacao", __name__,
    url_prefix="/financeiro/conciliacao",
    template_folder=str(RAIZ / "conciliacao" / "web" / "templates"),
    static_folder=str(RAIZ / "conciliacao" / "web" / "static"),
    static_url_path="/static",
)


# --------------------------------------------------------------------------
# Regras e sessão
# --------------------------------------------------------------------------

def carregar_regras() -> dict:
    padrao = {"tolerancia_dias": 5, "tolerancia_valor_pct": 2.0,
              "limiar_automatico": 90, "limiar_sugestao": 70,
              "limiar_minimo_automatico_permitido": 85}
    try:
        with open(CAMINHO_REGRAS, encoding="utf-8") as f:
            padrao.update({k: v for k, v in json.load(f).items()
                           if not k.startswith("_")})
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    piso = padrao["limiar_minimo_automatico_permitido"]
    if padrao["limiar_automatico"] < piso:
        # Abaixo disso R3 e R4 entrariam no automático, e nenhuma das duas
        # tem força para justificar baixa sem olho humano.
        padrao["limiar_automatico"] = piso
        padrao["_ajuste"] = (
            f"Limiar automático abaixo de {piso} não é aceito; usei {piso}."
        )
    return padrao


def estado_sessao() -> tuple[dict, str]:
    chave = request.cookies.get(COOKIE_SESSAO) or sessao.nova_chave()
    return sessao.obter(chave), chave


def responder(dados: dict, chave: str, status: int = 200):
    resposta = make_response(jsonify(dados), status)
    resposta.set_cookie(COOKIE_SESSAO, chave, httponly=True, samesite="Lax",
                        max_age=8 * 3600)
    return resposta


# --------------------------------------------------------------------------
# Máscaras (LGPD)
# --------------------------------------------------------------------------

def mascarar_documento(documento: str) -> str:
    digitos = re.sub(r"\D", "", documento or "")
    if len(digitos) < 5:
        return documento or ""
    return f"****{digitos[-4:]}"


def _mascarar_texto(texto: str) -> str:
    """Sequências longas de dígitos viram ****1234 — a tela não precisa do
    CPF/CNPJ inteiro para o usuário conferir um match."""
    return re.sub(r"\d{5,}", lambda m: f"****{m.group()[-4:]}", texto or "")


# --------------------------------------------------------------------------
# Serialização
# --------------------------------------------------------------------------

def _titulo_json(titulo) -> dict | None:
    if titulo is None:
        return None
    return {
        "id": titulo.id,
        "tipo": titulo.tipo,
        "descricao": titulo.descricao,
        "contraparte": titulo.contraparte,
        "valor": brl(titulo.valor_centavos),
        "valor_centavos": titulo.valor_centavos,
        "vencimento": titulo.vencimento.strftime("%d/%m/%Y"),
        "documento": mascarar_documento(titulo.documento),
        "status": titulo.status,
    }


def _resultado_json(resultado, aprovados: dict) -> dict:
    lanc = resultado.lancamento
    return {
        "id": lanc.id,
        "data": lanc.data.strftime("%d/%m/%Y"),
        "descricao": _mascarar_texto(lanc.descricao),
        "contraparte": lanc.contraparte,
        "documento": mascarar_documento(lanc.documento),
        "valor": brl(lanc.valor_centavos),
        "valor_centavos": lanc.valor_centavos,
        "tipo": lanc.tipo,
        "titulo": _titulo_json(resultado.titulo),
        "confianca": resultado.confianca,
        "regra": resultado.regra,
        "explicacao": _mascarar_texto(resultado.explicacao),
        "dif_valor": brl(resultado.dif_valor_centavos),
        "dif_valor_centavos": resultado.dif_valor_centavos,
        "dif_dias": resultado.dif_dias,
        "status": resultado.status,
        "tipo_divergencia": resultado.tipo_divergencia,
        "candidatos": [_titulo_json(t) for t in resultado.candidatos],
        "aprovado": lanc.id in aprovados,
    }


def _resposta_conciliacao(resultados: list, aprovados: dict, regras: dict) -> dict:
    """Corpo comum de `/api/conciliar` e `/api/resultados`: resumo com
    valores em reais + os três blocos, cada um com o porquê do match."""
    resumo = resumir(resultados)
    return {
        "resumo": {
            **resumo,
            "automatico_valor": brl(resumo["automatico"]["valor_centavos"]),
            "sugestao_valor": brl(resumo["sugestao"]["valor_centavos"]),
            "divergencia_valor": brl(resumo["divergencia"]["valor_centavos"]),
        },
        "regras": regras,
        "automatico": [_resultado_json(r, aprovados) for r in resultados
                       if r.status == "automatico"],
        "sugestao": [_resultado_json(r, aprovados) for r in resultados
                     if r.status == "sugestao"],
        "divergencia": [_resultado_json(r, aprovados) for r in resultados
                        if r.status == "divergencia"],
    }


def _painel_json(painel) -> dict:
    kpis = painel.kpis or {}
    return {
        "vazio": painel.vazio,
        "filtros_ativos": painel.filtros_ativos,
        "total_lancamentos": painel.total_lancamentos,
        "kpis": {
            "entrada": brl(kpis.get("entrada_centavos")),
            "saida": brl(kpis.get("saida_centavos")),
            "saldo": brl(kpis.get("saldo_centavos")),
            "saldo_negativo": (kpis.get("saldo_centavos") or 0) < 0,
            "margem": pct(kpis.get("margem_pct")),
            "conciliados": kpis.get("lancamentos_conciliados", 0),
            "divergentes": kpis.get("lancamentos_divergentes", 0),
        },
        "mensal": [
            {**m, "entrada": brl(m["entrada_centavos"]),
             "saida": brl(m["saida_centavos"]),
             "total": brl(m["total_centavos"])}
            for m in painel.mensal
        ],
        "status_recebimentos": [
            {**f, "valor": brl(f["valor_centavos"])}
            for f in painel.status_recebimentos
        ],
        "top_clientes": [{**c, "valor": brl(c["valor_centavos"])}
                         for c in painel.top_clientes],
        "top_fornecedores": [{**f, "valor": brl(f["valor_centavos"])}
                             for f in painel.top_fornecedores],
        "opcoes_filtro": painel.opcoes_filtro,
        "atualizado_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
    }


# --------------------------------------------------------------------------
# Páginas
# --------------------------------------------------------------------------

@bp.get("/")
@exigir("conciliacao", "leitura")
def pagina_conciliacao():
    return render_template("conciliacao.html", acesso=resumo_acesso(),
                           situacao=modo.situacao("conciliacao"))


@bp.get("/dashboard")
@exigir("conciliacao", "leitura")
def pagina_dashboard():
    return render_template("dashboard.html", acesso=resumo_acesso(),
                           situacao=modo.situacao("conciliacao"))


# --------------------------------------------------------------------------
# API — leitura
# --------------------------------------------------------------------------

@bp.get("/api/estado")
@exigir("conciliacao", "leitura")
def api_estado():
    estado, chave = estado_sessao()
    extrato, titulos = estado["extrato"], estado["titulos"]
    return responder({
        "situacao": modo.situacao("conciliacao"),
        "acesso": resumo_acesso(),
        "regras": carregar_regras(),
        "extrato": {
            "carregado": bool(extrato and extrato.lancamentos),
            "formato": getattr(extrato, "formato", ""),
            "conta": getattr(extrato, "conta_mascarada", ""),
            "resumo": extrato.resumo() if extrato else "",
            "avisos": getattr(extrato, "avisos", []),
        },
        "titulos": {
            "carregado": bool(titulos and titulos.titulos),
            "resumo": titulos.resumo() if titulos else "",
            "avisos": getattr(titulos, "avisos", []),
        },
        "conciliado": bool(estado["resultados"]),
        "aprovados": len(estado["aprovados"]),
    }, chave)


@bp.post("/api/extrato")
@exigir("conciliacao", "operacao")
def api_extrato():
    estado, chave = estado_sessao()
    arquivo = request.files.get("arquivo")
    if not arquivo:
        return responder({"erro": "Nenhum arquivo enviado."}, chave, 400)

    mapeamento = request.form.get("mapeamento")
    resultado = ler_extrato(
        arquivo.read(), arquivo.filename or "",
        json.loads(mapeamento) if mapeamento else None,
    )

    if resultado.erro:
        auditoria.registrar(aba="conciliacao", usuario=identificar(),
                            acao="importar_extrato", resultado="falha",
                            detalhe={"arquivo": arquivo.filename},
                            resposta=resultado.erro)
        return responder({"erro": resultado.erro, "formato": resultado.formato},
                         chave, 422)

    if resultado.precisa_mapeamento:
        return responder({
            "precisa_mapeamento": True,
            "colunas": resultado.colunas,
            "amostra": resultado.amostra,
            "mensagem": ("Não reconheci o cabeçalho. Informe qual coluna é a "
                         "data, o valor e o histórico."),
        }, chave, 200)

    repetidos = detectar_reimportacao(
        resultado.lancamentos,
        [l for l in (estado["extrato"].lancamentos if estado["extrato"] else [])],
    )
    ja_vistos = [l for l in resultado.lancamentos
                 if chave_reimportacao(l) in set(estado["chaves_importadas"])]
    repetidos = {l.id: l for l in repetidos + ja_vistos}

    estado["extrato"] = resultado
    estado["resultados"] = []
    estado["aprovados"] = {}

    auditoria.registrar(
        aba="conciliacao", usuario=identificar(), acao="importar_extrato",
        resultado="sucesso",
        detalhe={"arquivo": arquivo.filename, "formato": resultado.formato,
                 "lancamentos": len(resultado.lancamentos),
                 "ignoradas": resultado.ignoradas,
                 "conta": resultado.conta_mascarada},
    )

    return responder({
        "resumo": resultado.resumo(),
        "formato": resultado.formato,
        "encoding": resultado.encoding,
        "conta": resultado.conta_mascarada,
        "lancamentos": len(resultado.lancamentos),
        "ignoradas": resultado.ignoradas,
        "motivos_ignoradas": resultado.motivos_ignoradas,
        "avisos": resultado.avisos,
        "reimportacao": {
            "detectada": bool(repetidos),
            "quantidade": len(repetidos),
            "mensagem": (
                f"{len(repetidos)} lançamento(s) deste arquivo já tinham sido "
                "importados nesta sessão. Reprocessar tudo ou só o que é novo?"
            ) if repetidos else "",
        },
    }, chave)


@bp.post("/api/titulos")
@exigir("conciliacao", "operacao")
def api_titulos():
    estado, chave = estado_sessao()
    arquivo = request.files.get("arquivo")
    if not arquivo:
        return responder({"erro": "Nenhum arquivo enviado."}, chave, 400)

    resultado = ler_titulos(arquivo.read(), arquivo.filename or "",
                            request.form.get("tipo", ""))
    if resultado.erro:
        return responder({"erro": resultado.erro}, chave, 422)

    anterior = estado["titulos"]
    if anterior and anterior.titulos:
        # Duas exportações (receber e pagar) somam em vez de substituir.
        conhecidos = {t.id for t in anterior.titulos}
        resultado.titulos = anterior.titulos + [t for t in resultado.titulos
                                                if t.id not in conhecidos]
        resultado.extras = {**anterior.extras, **resultado.extras}

    estado["titulos"] = resultado
    estado["resultados"] = []
    estado["aprovados"] = {}

    auditoria.registrar(
        aba="conciliacao", usuario=identificar(), acao="importar_titulos",
        resultado="sucesso",
        detalhe={"arquivo": arquivo.filename, "titulos": len(resultado.titulos),
                 "ignoradas": resultado.ignoradas},
    )
    return responder({
        "resumo": resultado.resumo(),
        "titulos": len(resultado.titulos),
        "ignoradas": resultado.ignoradas,
        "motivos_ignoradas": resultado.motivos_ignoradas,
        "avisos": resultado.avisos,
    }, chave)


@bp.post("/api/conciliar")
@exigir("conciliacao", "operacao")
def api_conciliar():
    estado, chave = estado_sessao()
    extrato, titulos = estado["extrato"], estado["titulos"]

    if not (extrato and extrato.lancamentos):
        return responder({"erro": "Importe o extrato antes de conciliar."},
                         chave, 409)
    if not (titulos and titulos.titulos):
        return responder({
            "erro": ("Importe os títulos (contas a receber/pagar) antes de "
                     "conciliar. Os endpoints financeiros do Projuris ainda "
                     "não foram confirmados, então a lista vem da exportação "
                     "da própria tela do sistema."),
        }, chave, 409)

    regras = carregar_regras()
    resultados = conciliar(
        extrato.lancamentos, titulos.titulos,
        tol_dias=int(regras["tolerancia_dias"]),
        tol_valor=float(regras["tolerancia_valor_pct"]),
        limiar_auto=int(regras["limiar_automatico"]),
    )
    estado["resultados"] = resultados
    estado["aprovados"] = {}
    estado["chaves_importadas"] = list({
        *estado["chaves_importadas"],
        *(chave_reimportacao(l) for l in extrato.lancamentos),
    })

    resumo = resumir(resultados)
    auditoria.registrar(
        aba="conciliacao", usuario=identificar(), acao="conciliar",
        resultado="sucesso",
        detalhe={"lancamentos": resumo["total_lancamentos"],
                 "automatico": resumo["automatico"]["qtd"],
                 "sugestao": resumo["sugestao"]["qtd"],
                 "divergencia": resumo["divergencia"]["qtd"],
                 "regras": {k: v for k, v in regras.items()
                            if not k.startswith("_")}},
    )

    return responder(
        _resposta_conciliacao(resultados, estado["aprovados"], regras), chave)


@bp.get("/api/resultados")
@exigir("conciliacao", "leitura")
def api_resultados():
    """Resultado que já está na sessão, sem reconciliar.

    Recarregar a página não pode apagar o trabalho: reconciliar zeraria as
    aprovações já dadas item a item.
    """
    estado, chave = estado_sessao()
    resultados, aprovados = estado["resultados"], estado["aprovados"]
    if not resultados:
        return responder({"conciliado": False}, chave)

    return responder({
        "conciliado": True,
        **_resposta_conciliacao(resultados, aprovados, carregar_regras()),
    }, chave)


@bp.get("/api/painel")
@exigir("conciliacao", "leitura")
def api_painel():
    estado, chave = estado_sessao()
    titulos = estado["titulos"]
    painel = montar_painel(
        estado["resultados"],
        titulos.titulos if titulos else [],
        extras=titulos.extras if titulos else {},
        filtros=Filtros.de_dict(request.args.to_dict()),
    )
    return responder(_painel_json(painel), chave)


@bp.get("/api/auditoria")
@exigir("conciliacao", "leitura")
def api_auditoria():
    estado, chave = estado_sessao()
    return responder({"registros": auditoria.ler(limite=100, aba="conciliacao")},
                     chave)


# --------------------------------------------------------------------------
# API — escrita
# --------------------------------------------------------------------------

@bp.post("/api/aprovar")
@exigir("conciliacao", "operacao")
def api_aprovar():
    """Aceite de uma sugestão. Marca a intenção; não grava no Projuris."""
    estado, chave = estado_sessao()
    corpo = request.get_json(silent=True) or {}
    lancamento_id = corpo.get("lancamento_id")

    if isinstance(lancamento_id, list):
        return responder({
            "erro": ("Aprovação é item a item. Envie um lançamento por "
                     "chamada — aprovação genérica não autoriza lote."),
        }, chave, 400)

    alvo = next((r for r in estado["resultados"]
                 if r.lancamento.id == lancamento_id), None)
    if alvo is None:
        return responder({"erro": f"Lançamento {lancamento_id} não está na sessão."},
                         chave, 404)
    if alvo.titulo is None:
        return responder({"erro": "Este lançamento não tem título correspondente."},
                         chave, 409)

    estado["aprovados"][alvo.lancamento.id] = {
        "titulo_id": alvo.titulo.id,
        "momento": datetime.now().isoformat(timespec="seconds"),
        "confianca": alvo.confianca,
        "regra": alvo.regra,
    }
    auditoria.registrar(
        aba="conciliacao", usuario=identificar(), acao="aprovar_sugestao",
        resultado="sucesso",
        detalhe={"lancamento": alvo.lancamento.id, "titulo": alvo.titulo.id,
                 "valor_centavos": abs(alvo.lancamento.valor_centavos),
                 "confianca": alvo.confianca, "regra": alvo.regra},
    )
    return responder({"aprovado": True, "lancamento_id": alvo.lancamento.id,
                      "titulo_id": alvo.titulo.id}, chave)


@bp.post("/api/baixa")
@exigir("conciliacao", "gravacao")
def api_baixa():
    """Grava a baixa de **um** título no Projuris.

    Em modo simulação devolve exatamente o que gravaria, registra no log
    como `simulado` e não chama a API. É o comportamento previsto enquanto
    o endpoint de baixa não for confirmado por inspeção real.
    """
    estado, chave = estado_sessao()
    corpo = request.get_json(silent=True) or {}
    lancamento_id = corpo.get("lancamento_id")

    if isinstance(lancamento_id, list) or corpo.get("lote"):
        return responder({
            "erro": ("Baixa é item a item: um título por chamada. "
                     "Estourar o rate limit no meio de um lote deixa a "
                     "gravação pela metade."),
        }, chave, 400)

    alvo = next((r for r in estado["resultados"]
                 if r.lancamento.id == lancamento_id), None)
    if alvo is None or alvo.titulo is None:
        return responder({"erro": "Lançamento sem título correspondente na sessão."},
                         chave, 404)
    if alvo.lancamento.id not in estado["aprovados"]:
        return responder({
            "erro": "Este item ainda não foi aprovado. Aprove antes de gravar.",
        }, chave, 409)

    valor_centavos = abs(alvo.lancamento.valor_centavos)
    detalhe = {
        "lancamento": alvo.lancamento.id,
        "titulo": alvo.titulo.id,
        "valor_centavos": valor_centavos,
        "data_pagamento": alvo.lancamento.data.isoformat(),
        "confianca": alvo.confianca,
        "regra": alvo.regra,
    }

    pendencias = modo.pendencias_conciliacao()
    if pendencias:
        auditoria.registrar(aba="conciliacao", usuario=identificar(),
                            acao="baixa", resultado="simulado", detalhe=detalhe,
                            resposta="; ".join(pendencias))
        return responder({
            "simulacao": True,
            "mensagem": (
                f"Modo simulação: **não gravei** no Projuris. Gravaria a baixa "
                f"do título {alvo.titulo.id} em {alvo.lancamento.data:%d/%m/%Y}, "
                f"no valor de {brl(valor_centavos)}."
            ),
            "gravaria": detalhe,
            "pendencias": pendencias,
        }, chave, 200)

    senha = (corpo.get("senha") or "").strip()
    if not senha:
        return responder({
            "erro": ("Senha do Projuris não informada. Ela é pedida a cada "
                     "sessão e não fica armazenada em arquivo, log ou código."),
        }, chave, 401)

    from ...shared.projuris_financeiro import ProjurisFinanceiro

    cliente = ProjurisFinanceiro(corpo.get("usuario", ""), senha,
                                 permitir_escrita=True)
    try:
        resposta = cliente.registrar_baixa(
            titulo_id=alvo.titulo.id,
            data_pagamento=alvo.lancamento.data.isoformat(),
            valor_centavos=valor_centavos,
            observacao=f"Conciliação automática — {alvo.regra}",
            confianca=alvo.confianca,
            regra=alvo.regra,
            lancamento_ref=alvo.lancamento.id,
        )
    except Exception as erro:
        auditoria.registrar(aba="conciliacao", usuario=identificar(),
                            acao="baixa", resultado="falha", detalhe=detalhe,
                            resposta=str(erro))
        return responder({"erro": f"A gravação falhou: {erro}",
                          "gravado": False}, chave, 502)

    auditoria.registrar(aba="conciliacao", usuario=identificar(), acao="baixa",
                        resultado="sucesso", detalhe=detalhe,
                        resposta=json.dumps(resposta, ensure_ascii=False)[:500])
    alvo.titulo.status = "pago"
    return responder({"gravado": True, "titulo_id": alvo.titulo.id,
                      "resposta": resposta}, chave)


@bp.post("/api/limpar")
@exigir("conciliacao", "operacao")
def api_limpar():
    """Descarta extrato e títulos da memória do servidor."""
    _, chave = estado_sessao()
    sessao.limpar(chave)
    auditoria.registrar(aba="conciliacao", usuario=identificar(),
                        acao="limpar_sessao", resultado="sucesso")
    return responder({"limpo": True}, chave)
