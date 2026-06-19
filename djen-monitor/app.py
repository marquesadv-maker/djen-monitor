"""
Monitor DJEN × Projuris — Marques Advogados S.S
Plataforma Web — Flask Backend
"""

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import quote

import requests
import urllib3
from flask import Flask, jsonify, render_template, request

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

# ─── Configurações fixas ──────────────────────────────────────────────────
PROJURIS_AUTH_URL  = "https://apigw.projurisadv.com.br/auth/token"
PROJURIS_BASE_URL  = "https://api.projurisadv.com.br/adv-service"
DJEN_BASE_URL      = "https://comunicaapi.pje.jus.br/api/v1"

PROJURIS_USERNAME      = "mariaelisanolasco@outlook.com$$marques-advogados3"
PROJURIS_CLIENT_ID     = "api_cliente_codigo_53034"
PROJURIS_CLIENT_SECRET = "mh1gELhl6bf3hnDIL550Z4rTyWJiZKQI"

PALAVRAS_URGENTES   = ["audiencia","pericia","contestacao","defesa","prazo","intimacao"]
PALAVRAS_IMPORTANTES = ["sentenca","acordao","recurso","apelacao","execucao",
                        "penhora","leilao","cumprimento","manifestacao"]

TRIBUNAIS_DISPONIVEIS = [
    # ── Nacionais ──────────────────────────────────────────────
    "CJF","CNJ","SEEU","STJ","STM","TSE","TST",
    # ── Tribunais de Justiça Estaduais ─────────────────────────
    "TJAC","TJAL","TJAM","TJAP","TJBA","TJCE","TJDFT",
    "TJES","TJGO","TJMA","TJMG","TJMMG","TJMS","TJMT",
    "TJPA","TJPB","TJPE","TJPI","TJPR","TJRJ","TJRN",
    "TJRO","TJRR","TJRS","TJMRS","TJSC","TJSE","TJSP","TJMSP","TJTO",
    # ── Tribunais Regionais Eleitorais ─────────────────────────
    "TRE-AC","TRE-AL","TRE-AM","TRE-AP","TRE-BA","TRE-ES",
    "TRE-GO","TRE-MA","TRE-MS","TRE-MT","TRE-PA","TRE-PE",
    "TRE-PI","TRE-PR","TRE-RJ","TRE-RN","TRE-RO","TRE-RS",
    "TRE-SC","TRE-SP","TRE-TO",
    # ── Tribunais Regionais Federais ───────────────────────────
    "TRF1","TRF2","TRF3","TRF4","TRF5","TRF6",
    # ── Tribunais Regionais do Trabalho ────────────────────────
    "TRT1","TRT2","TRT3","TRT4","TRT5","TRT6","TRT7","TRT8",
    "TRT9","TRT10","TRT11","TRT12","TRT13","TRT14","TRT15",
    "TRT16","TRT17","TRT18","TRT19","TRT20","TRT21","TRT22",
    "TRT23","TRT24",
]


# ═══════════════════════════════════════════════════════════════
# POWERSHELL HELPERS (para Projuris — evita timeout IPv6 do requests)
# ═══════════════════════════════════════════════════════════════


def _projuris_session(token: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    })
    return s


def autenticar_projuris(senha: str) -> str:
    body = (
        f"username={quote(PROJURIS_USERNAME)}"
        f"&password={quote(senha)}"
        f"&grant_type=password"
        f"&client_id={PROJURIS_CLIENT_ID}"
        f"&client_secret={PROJURIS_CLIENT_SECRET}"
    )
    resp = requests.post(
        PROJURIS_AUTH_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    resp.raise_for_status()
    token = resp.json().get("access_token", "")
    if not token or len(token) < 20:
        raise ValueError("Falha na autenticação. Verifique a senha.")
    return token


def _projuris_raw(token: str, method: str, url: str, body=None) -> dict:
    result = {"_status": None, "_body": "", "_parsed": {}, "_error": None}
    try:
        s = _projuris_session(token)
        if method.upper() == "GET":
            resp = s.get(url, timeout=30)
        else:
            resp = s.post(url, json=body or {}, timeout=30)
        result["_status"] = resp.status_code
        result["_body"] = resp.text
        try:
            result["_parsed"] = resp.json()
        except Exception:
            pass
    except Exception as e:
        result["_error"] = str(e)
    return result


def projuris_post(token: str, endpoint: str, body: dict) -> dict:
    raw = _projuris_raw(token, "POST", f"{PROJURIS_BASE_URL}/{endpoint}", body)
    if raw.get("_error"):
        return {"_api_error": raw["_error"]}
    return raw.get("_parsed") or {}


def projuris_get(token: str, endpoint: str) -> dict:
    raw = _projuris_raw(token, "GET", f"{PROJURIS_BASE_URL}/{endpoint}")
    return raw.get("_parsed") or {}


# ═══════════════════════════════════════════════════════════════
# DJEN
# ═══════════════════════════════════════════════════════════════

_DJEN_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Referer": "https://comunicaapi.pje.jus.br/",
}


def buscar_djen(data_inicio: str, data_fim: str, tribunais: list,
                numero_oab: str, uf_oab: str, nome_advogado: str = "") -> tuple:
    """Busca todas as publicações do advogado sem filtrar por tribunal.
    Uma única requisição paginada retorna tudo — evita rate limit da API."""
    todas = []
    erros = []
    tribs_set = set(tribunais)
    pagina = 1

    while True:
        params = {
            "pagina": pagina,
            "itensPorPagina": 50,
            "meio": "D",
            "dataDisponibilizacaoInicio": data_inicio,
            "dataDisponibilizacaoFim": data_fim,
            "numeroOab": numero_oab,
            "ufOab": uf_oab,
        }
        if nome_advogado:
            params["nomeAdvogado"] = nome_advogado

        tentativas = 0
        resp = None
        while tentativas < 4:
            try:
                resp = requests.get(f"{DJEN_BASE_URL}/comunicacao",
                                    params=params, headers=_DJEN_HEADERS,
                                    timeout=45)
                if resp.status_code in (403, 404):
                    erros.append(f"DJEN bloqueou acesso (HTTP {resp.status_code})")
                    return todas, erros
                if resp.status_code in (500, 502, 503, 504):
                    corpo = ""
                    try:
                        corpo = ": " + resp.text[:300]
                    except Exception:
                        pass
                    tentativas += 1
                    if tentativas >= 4:
                        erros.append(f"DJEN HTTP {resp.status_code}{corpo}")
                        return todas, erros
                    time.sleep(5 * tentativas)
                    continue
                resp.raise_for_status()
                break
            except requests.exceptions.RequestException as e:
                tentativas += 1
                if tentativas >= 4:
                    erros.append(f"DJEN p{pagina}: {str(e)[:80]}")
                    resp = None
                else:
                    time.sleep(3)

        if resp is None:
            break

        try:
            dados = resp.json()
        except Exception:
            break

        itens = dados.get("items", []) if isinstance(dados, dict) else dados
        if not itens:
            break

        for item in itens:
            trib = item.get("siglaTribunal", "")
            item["_tribunal"] = trib
            item["_classificacao"] = classificar(item)
            # Filtrar pelos tribunais selecionados
            if not tribs_set or trib in tribs_set:
                todas.append(item)

        if len(itens) < 50:
            break
        pagina += 1
        time.sleep(0.5)  # respeitar rate limit

    return todas, erros


def normalizar(texto: str) -> str:
    subs = {"ê":"e","é":"e","è":"e","á":"a","ã":"a","â":"a","à":"a",
            "ç":"c","ó":"o","õ":"o","ô":"o","ú":"u","í":"i","î":"i"}
    for k, v in subs.items():
        texto = texto.replace(k, v)
    return texto.lower()


def classificar(pub: dict) -> str:
    txt = normalizar(pub.get("texto","") + " " + pub.get("tipoComunicacao",""))
    if any(p in txt for p in PALAVRAS_URGENTES):
        return "URGENTE"
    if any(p in txt for p in PALAVRAS_IMPORTANTES):
        return "IMPORTANTE"
    return "INFORMATIVA"


def extrair_numero(pub: dict) -> str:
    num = (pub.get("numeroprocessocommascara") or
           pub.get("numero_processo") or "")
    if not num:
        match = re.search(r'\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}',
                          pub.get("texto", ""))
        if match:
            num = match.group(0)
    return str(num).strip()


def extrair_partes(pub: dict) -> tuple:
    dest = pub.get("destinatarios", [])
    ativos   = [d["nome"] for d in dest if d.get("polo") == "A"]
    passivos = [d["nome"] for d in dest if d.get("polo") == "P"]
    return (", ".join(ativos), ", ".join(passivos))


def extrair_prazo(texto: str) -> str:
    for pat in [r'prazo\s+de\s+(\d+)\s+dias?\s+úteis?',
                r'prazo\s+de\s+(\d+)\s+dias?',
                r'(\d+)\s+dias?\s+para\s+(?:apresentar|manifestar|contestar|recorrer)']:
        m = re.search(pat, texto.lower())
        if m:
            return f"{m.group(1)} dias"
    return ""


# ═══════════════════════════════════════════════════════════════
# CRUZAMENTO PROJURIS
# ═══════════════════════════════════════════════════════════════

_SITUACOES_CONCLUIDAS = {
    "CONCLUIDA", "CONCLUÍDO", "REALIZADA", "REALIZADO", "FINALIZADA",
    "FINALIZADO", "ENCERRADA", "ENCERRADO", "ARQUIVADA", "ARQUIVADO",
    "CANCELADA", "CANCELADO", "INATIVA", "INATIVO",
}


def _extrair_lista(dados: dict, *chaves) -> list:
    """Tenta extrair lista do retorno da API usando múltiplas chaves possíveis."""
    for chave in chaves:
        val = dados.get(chave)
        if isinstance(val, list):
            return val
    if isinstance(dados, list):
        return dados
    # Retorno pode ser objeto com lista aninhada
    for v in dados.values():
        if isinstance(v, list) and len(v) > 0:
            return v
    return []


def verificar_atividades_projuris(token: str, codigo_processo: int,
                                   processo_data: dict) -> bool:
    """Verifica se há atividades/movimentações no processo.

    Estratégia (ordem de prioridade):
    1. intimacao/consulta → filtra client-side por codigoProcesso,
       checa tipoSituacao (qualquer ≠ PENDENTE = processado/tem tarefa)
    2. Fallback: flags flMovimentado / flParado do próprio processo
    """
    # ── Estratégia 1: intimações vinculadas ao processo ──────────────
    try:
        raw = _projuris_raw(token, "POST",
                            f"{PROJURIS_BASE_URL}/intimacao/consulta",
                            {"pagina": 0, "tamanhoPagina": 100})
        parsed = raw.get("_parsed", {})
        lista = parsed.get("intimacaoConsultaWs", []) if isinstance(parsed, dict) else []
        # Filtrar client-side por codigoProcesso
        vinculadas = [i for i in lista
                      if i.get("codigoProcesso") == codigo_processo]
        if vinculadas:
            for intim in vinculadas:
                sit = str(intim.get("tipoSituacao", "PENDENTE")).upper()
                if sit not in ("PENDENTE", "NOVA", ""):
                    return True   # intimação já foi processada → tem tarefa
            # Todas PENDENTE → sem tarefa
            return False
    except Exception:
        pass

    # ── Estratégia 2 (fallback): flags do processo ────────────────────
    fl_encerrado  = processo_data.get("flEncerrado", False)
    fl_movimentado = processo_data.get("flMovimentado", False)
    fl_parado      = processo_data.get("flParado", False)

    if fl_encerrado:
        return True   # Encerrado = atividade concluída
    if fl_parado:
        return False  # Explicitamente parado = sem atividade recente
    if fl_movimentado:
        return True   # Tem movimentação = alguém está trabalhando

    return False


def verificar_projuris(token: str, numero: str) -> dict:
    """Consulta o Projuris pelo número CNJ e verifica atividades."""
    resultado = {
        "encontrado": False, "id": None, "processo": None,
        "status": "NAO_CADASTRADO", "erro": None,
        "tem_atividade": False, "_debug": {}
    }
    if not numero:
        resultado["status"] = "SEM_NUMERO"
        return resultado

    # Tentar com máscara e sem máscara
    candidatos = [numero]
    sem_mascara = re.sub(r'\D', '', numero)
    if sem_mascara and sem_mascara != numero:
        candidatos.append(sem_mascara)

    for num_tentativa in candidatos:
        dados = projuris_post(token, "v2/processo/consulta",
                              {"pagina": 0, "tamanhoPagina": 5,
                               "numeroProcesso": num_tentativa})

        if "_api_error" in dados or "_parse_error" in dados:
            resultado["erro"] = str(dados)[:200]
            resultado["status"] = "ERRO_API"
            resultado["_debug"]["processo"] = dados
            return resultado

        processos = _extrair_lista(dados,
                                   "processoConsultaResumoWs", "processos",
                                   "content", "items", "data", "resultado")
        resultado["_debug"][f"busca_{num_tentativa}"] = {
            "keys": list(dados.keys()), "total": len(processos)
        }

        if processos:
            p = processos[0]
            codigo = (p.get("codigoProcesso") or p.get("codigo") or
                      p.get("id") or p.get("idProcesso"))
            tem_ativ = (
                verificar_atividades_projuris(token, codigo, p)
                if codigo else False
            )
            debug_ativ = {}
            resultado.update({
                "encontrado": True,
                "id": codigo,
                "processo": p,
                "status": "CADASTRADO",
                "advogado": p.get("advogadoResponsavel", ""),
                "situacao": p.get("situacao", ""),
                "encerrado": p.get("flEncerrado", False),
                "tem_atividade": tem_ativ,
                "_debug": {**resultado["_debug"], "atividades": debug_ativ},
            })
            return resultado

    return resultado


# ═══════════════════════════════════════════════════════════════
# DEDUPLICAÇÃO
# ═══════════════════════════════════════════════════════════════

def deduplicar(publicacoes: list) -> list:
    """Remove duplicatas mantendo uma publicação por (numero_processo, id_comunicacao)."""
    vistos = set()
    resultado = []
    for pub in publicacoes:
        chave = (pub.get("id", ""), extrair_numero(pub))
        if chave not in vistos:
            vistos.add(chave)
            resultado.append(pub)
    return resultado


# ═══════════════════════════════════════════════════════════════
# ROTAS FLASK
# ═══════════════════════════════════════════════════════════════

@app.route("/")
def index():
    from flask import make_response
    resp = make_response(render_template("index.html", tribunais=TRIBUNAIS_DISPONIVEIS))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    return resp


@app.route("/api/buscar", methods=["POST"])
def buscar():
    dados = request.json
    data_inicio   = dados.get("dataInicio", "")
    data_fim      = dados.get("dataFim", data_inicio)
    tribunais     = dados.get("tribunais", ["TJTO","TRT10","TRT8","TRF1"])
    numero_oab    = dados.get("numeroOab", "2265")
    uf_oab        = dados.get("ufOab", "TO")
    nome_advogado = dados.get("nomeAdvogado", "")
    senha         = dados.get("senha", "")

    if not data_inicio:
        return jsonify({"erro": "Data de início obrigatória"}), 400
    if not senha:
        return jsonify({"erro": "Senha do Projuris obrigatória"}), 400

    # 1. Autenticar Projuris
    try:
        token = autenticar_projuris(senha)
    except Exception as e:
        return jsonify({"erro": f"Falha na autenticação Projuris: {e}"}), 401

    # 2. Buscar DJEN
    publicacoes, erros_djen = buscar_djen(
        data_inicio, data_fim, tribunais, numero_oab, uf_oab, nome_advogado
    )

    # 3. Deduplicar
    publicacoes = deduplicar(publicacoes)

    # 4. Cruzar com Projuris — buscar números únicos em paralelo
    numeros_unicos = list({extrair_numero(p) for p in publicacoes if extrair_numero(p)})

    processos_cache = {}
    def _verificar(num):
        return num, verificar_projuris(token, num)

    with ThreadPoolExecutor(max_workers=5) as pool:
        for num, proj in pool.map(_verificar, numeros_unicos):
            processos_cache[num] = proj

    resultados = []
    for pub in publicacoes:
        num = extrair_numero(pub)
        polo_ativo, polo_passivo = extrair_partes(pub)
        texto_html = pub.get("texto", "")
        texto_limpo = re.sub(r"<[^>]+>", " ", texto_html).strip()
        texto_limpo = re.sub(r"\s+", " ", texto_limpo)
        prazo = extrair_prazo(texto_limpo)

        proj = processos_cache.get(num, {"encontrado": False, "status": "SEM_NUMERO"})

        cls = pub.get("_classificacao", "INFORMATIVA")
        if not proj["encontrado"]:
            status_final = "NAO_CADASTRADO"
        elif not proj.get("tem_atividade", False):
            status_final = "CADASTRADO_SEM_TAREFA"
        else:
            status_final = "INFORMATIVA"

        resultados.append({
            "numero": num,
            "tribunal": pub.get("siglaTribunal", pub.get("_tribunal", "")),
            "orgao": pub.get("nomeOrgao", ""),
            "data": pub.get("datadisponibilizacao", pub.get("data_disponibilizacao", "")),
            "tipo": pub.get("tipoComunicacao", ""),
            "tipoDoc": pub.get("tipoDocumento", ""),
            "classificacao": cls,
            "poloAtivo": polo_ativo,
            "poloPassivo": polo_passivo,
            "teor": texto_limpo[:300],
            "prazo": prazo,
            "link": pub.get("link", ""),
            "projuris": {
                "encontrado": proj["encontrado"],
                "id": proj.get("id"),
                "status": proj.get("status"),
                "encerrado": proj.get("encerrado", False),
                "temAtividade": proj.get("tem_atividade", False),
                "erro": proj.get("erro"),
            },
            "statusFinal": status_final,
        })

    # 5. Estatísticas
    total = len(resultados)
    cadastrados    = sum(1 for r in resultados if r["projuris"]["encontrado"])
    nao_cadastrados = sum(1 for r in resultados if not r["projuris"]["encontrado"])
    sem_tarefa     = sum(1 for r in resultados if r["statusFinal"] == "CADASTRADO_SEM_TAREFA")
    urgentes       = sum(1 for r in resultados if r["classificacao"] == "URGENTE"
                         and r["statusFinal"] in ("NAO_CADASTRADO","CADASTRADO_SEM_TAREFA"))

    return jsonify({
        "ok": True,
        "stats": {
            "total": total,
            "cadastrados": cadastrados,
            "naoCadastrados": nao_cadastrados,
            "semTarefa": sem_tarefa,
            "urgentes": urgentes,
            "errosDjen": len(erros_djen),
        },
        "resultados": resultados,
        "errosDjen": erros_djen,
        "periodo": f"{data_inicio} a {data_fim}",
        "tribunais": tribunais,
        "geradoEm": datetime.now().strftime("%d/%m/%Y %H:%M"),
    })


@app.route("/api/cruzar", methods=["POST"])
def cruzar():
    """Recebe publicações já buscadas pelo browser e cruza com Projuris."""
    dados = request.json or {}
    publicacoes = dados.get("publicacoes", [])
    senha       = dados.get("senha", "")
    data_inicio = dados.get("dataInicio", "")
    data_fim    = dados.get("dataFim", data_inicio)

    if not senha:
        return jsonify({"erro": "Senha do Projuris obrigatória"}), 400
    if not publicacoes:
        return jsonify({"erro": "Nenhuma publicação recebida"}), 400

    try:
        token = autenticar_projuris(senha)
    except Exception as e:
        return jsonify({"erro": f"Falha na autenticação Projuris: {e}"}), 401

    # Classificar e extrair números únicos
    for pub in publicacoes:
        pub["_classificacao"] = classificar(pub)

    numeros_unicos = list({extrair_numero(p) for p in publicacoes if extrair_numero(p)})

    processos_cache = {}
    def _verificar(num):
        return num, verificar_projuris(token, num)

    with ThreadPoolExecutor(max_workers=5) as pool:
        for num, proj in pool.map(_verificar, numeros_unicos):
            processos_cache[num] = proj

    resultados = []
    for pub in publicacoes:
        num = extrair_numero(pub)
        polo_ativo, polo_passivo = extrair_partes(pub)
        texto_html = pub.get("texto", "")
        texto_limpo = re.sub(r"<[^>]+>", " ", texto_html).strip()
        texto_limpo = re.sub(r"\s+", " ", texto_limpo)
        prazo = extrair_prazo(texto_limpo)

        proj = processos_cache.get(num, {"encontrado": False, "status": "SEM_NUMERO"})
        cls  = pub.get("_classificacao", "INFORMATIVA")

        if not proj["encontrado"]:
            status_final = "NAO_CADASTRADO"
        elif not proj.get("tem_atividade", False):
            status_final = "CADASTRADO_SEM_TAREFA"
        else:
            status_final = "INFORMATIVA"

        resultados.append({
            "numero":      num,
            "tribunal":    pub.get("siglaTribunal", pub.get("_tribunal", "")),
            "orgao":       pub.get("nomeOrgao", ""),
            "data":        pub.get("datadisponibilizacao", pub.get("data_disponibilizacao", "")),
            "tipo":        pub.get("tipoComunicacao", ""),
            "tipoDoc":     pub.get("tipoDocumento", ""),
            "classificacao": cls,
            "poloAtivo":   polo_ativo,
            "poloPassivo": polo_passivo,
            "teor":        texto_limpo[:300],
            "prazo":       prazo,
            "link":        pub.get("link", ""),
            "projuris": {
                "encontrado":   proj["encontrado"],
                "id":           proj.get("id"),
                "status":       proj.get("status"),
                "encerrado":    proj.get("encerrado", False),
                "temAtividade": proj.get("tem_atividade", False),
                "erro":         proj.get("erro"),
            },
            "statusFinal": status_final,
        })

    total          = len(resultados)
    cadastrados    = sum(1 for r in resultados if r["projuris"]["encontrado"])
    nao_cadastrados = total - cadastrados
    sem_tarefa     = sum(1 for r in resultados if r["statusFinal"] == "CADASTRADO_SEM_TAREFA")
    urgentes       = sum(1 for r in resultados if r["classificacao"] == "URGENTE"
                         and r["statusFinal"] in ("NAO_CADASTRADO", "CADASTRADO_SEM_TAREFA"))

    return jsonify({
        "ok": True,
        "stats": {
            "total": total, "cadastrados": cadastrados,
            "naoCadastrados": nao_cadastrados, "semTarefa": sem_tarefa,
            "urgentes": urgentes,
        },
        "resultados":  resultados,
        "periodo":     f"{data_inicio} a {data_fim}",
        "geradoEm":    datetime.now().strftime("%d/%m/%Y %H:%M"),
    })


@app.route("/api/ping")
def ping():
    return jsonify({"ok": True, "ts": datetime.now().isoformat()})


@app.route("/api/teste", methods=["POST"])
def teste():
    """Diagnóstico rápido: testa DJEN + Projuris e retorna erros detalhados."""
    dados = request.json or {}
    senha = dados.get("senha", "")
    resultado = {}

    # Teste DJEN
    try:
        resp = requests.get(
            f"{DJEN_BASE_URL}/comunicacao",
            params={"pagina": 1, "itensPorPagina": 1, "meio": "D",
                    "tribunal": "TRT10", "dataDisponibilizacaoInicio": "2025-03-10",
                    "dataDisponibilizacaoFim": "2025-03-10",
                    "numeroOab": "2265", "ufOab": "TO"},
            headers=_DJEN_HEADERS, timeout=20
        )
        erro_djen = None
        if resp.status_code not in (200,):
            try:
                erro_djen = resp.json()
            except Exception:
                erro_djen = resp.text[:200]
        resultado["djen"] = {
            "status": resp.status_code,
            "ok": resp.status_code == 200,
            "total": len(resp.json().get("items", [])) if resp.status_code == 200 else 0,
            "erro": erro_djen,
            "mensagem": "DJEN indisponível temporariamente. Tente novamente em alguns minutos." if resp.status_code in (500, 502, 503, 504) else None,
        }
    except Exception as e:
        resultado["djen"] = {"ok": False, "erro": str(e)}

    # Teste Projuris auth
    if senha:
        try:
            token = autenticar_projuris(senha)
            resultado["projuris_auth"] = {"ok": True, "token_len": len(token)}

            # Teste busca de processo
            try:
                r = projuris_post(token, "v2/processo/consulta",
                                  {"pagina": 0, "tamanhoPagina": 1})
                resultado["projuris_busca"] = {
                    "ok": "_api_error" not in r,
                    "chaves": list(r.keys())[:5],
                    "erro": r.get("_api_error"),
                }
            except Exception as e:
                resultado["projuris_busca"] = {"ok": False, "erro": str(e)}

        except Exception as e:
            resultado["projuris_auth"] = {"ok": False, "erro": str(e)}
    else:
        resultado["projuris_auth"] = {"ok": False, "erro": "senha não informada"}

    return jsonify(resultado)



@app.route("/api/debug-projuris", methods=["POST"])
def debug_projuris():
    """Diagnóstico completo: testa múltiplos campos e endpoints."""
    dados = request.json or {}
    senha  = dados.get("senha", "")
    numero = dados.get("numeroProcesso", "").strip()

    resultado = {"etapas": {}}

    # 1. Autenticação
    try:
        token = autenticar_projuris(senha)
        resultado["etapas"]["auth"] = {"ok": True, "token_len": len(token)}
    except Exception as e:
        resultado["etapas"]["auth"] = {"ok": False, "erro": str(e)}
        return jsonify(resultado)

    if not numero:
        return jsonify(resultado)

    num_digits = re.sub(r'\D', '', numero)

    # 2. Testar vários formatos e campos de busca
    # Montar lista de testes: (nome, método, url_completa, body_ou_None)
    BASE = PROJURIS_BASE_URL
    testes_raw = [
        # POST v2 consulta
        ("POST_v2_consulta_sem_filtro",   "POST", f"{BASE}/v2/processo/consulta",    {"pagina":0,"tamanhoPagina":3}),
        ("POST_v2_numero_mascara",        "POST", f"{BASE}/v2/processo/consulta",    {"pagina":0,"tamanhoPagina":5,"numeroProcesso":numero}),
        ("POST_v2_numero_digitos",        "POST", f"{BASE}/v2/processo/consulta",    {"pagina":0,"tamanhoPagina":5,"numeroProcesso":num_digits}),
        ("POST_v2_numeroCnj",             "POST", f"{BASE}/v2/processo/consulta",    {"pagina":0,"tamanhoPagina":5,"numeroCnj":numero}),
        # POST v1 consulta
        ("POST_v1_numero_mascara",        "POST", f"{BASE}/v1/processo/consulta",    {"pagina":0,"tamanhoPagina":5,"numeroProcesso":numero}),
        ("POST_v1_numero_digitos",        "POST", f"{BASE}/v1/processo/consulta",    {"pagina":0,"tamanhoPagina":5,"numeroProcesso":num_digits}),
        # GET com query param
        ("GET_v2_numero_mascara",         "GET",  f"{BASE}/v2/processo?numeroProcesso={quote(numero)}&pagina=0&tamanhoPagina=5", None),
        ("GET_v2_numero_digitos",         "GET",  f"{BASE}/v2/processo?numeroProcesso={num_digits}&pagina=0&tamanhoPagina=5",    None),
        ("GET_v1_numero_mascara",         "GET",  f"{BASE}/v1/processo?numeroProcesso={quote(numero)}&pagina=0&tamanhoPagina=5", None),
    ]

    for nome, metodo, url, body in testes_raw:
        raw_out = _projuris_raw(token, metodo, url, body)
        resultado["etapas"][nome] = {
            "status":    raw_out.get("_status"),
            "raw_trunc": raw_out.get("_body", "")[:400],
            "erro":      raw_out.get("_error"),
        }
        # Tentar parsear e extrair lista
        parsed = raw_out.get("_parsed", {})
        if isinstance(parsed, list):
            lista = parsed
        else:
            lista = _extrair_lista(parsed, "processoConsultaResumoWs", "processos",
                                   "content", "items", "data", "resultado")
        resultado["etapas"][nome]["total"] = len(lista)
        if lista:
            p = lista[0]
            codigo = (p.get("codigoProcesso") or p.get("codigo") or
                      p.get("id") or p.get("idProcesso"))
            resultado["etapas"][nome]["ACHADO"] = {
                "campos": list(p.keys()), "codigo": codigo, "sample": p
            }
            if codigo:
                raw_a = _projuris_raw(token, "POST",
                                      f"{BASE}/v2/atividade/consulta",
                                      {"pagina":0,"tamanhoPagina":20,"codigoProcesso":codigo})
                parsed_a = raw_a.get("_parsed", {})
                lista_a = _extrair_lista(parsed_a if isinstance(parsed_a, dict) else {},
                                         "atividadeConsultaResumoWs","atividades",
                                         "content","items","data")
                if isinstance(parsed_a, list):
                    lista_a = parsed_a
                resultado["etapas"]["ATIVIDADES"] = {
                    "total": len(lista_a),
                    "raw_trunc": raw_a.get("_body","")[:400],
                    "sample": lista_a[0] if lista_a else None,
                }
            break  # parar no primeiro que funcionou

    return jsonify(resultado)


if __name__ == "__main__":
    print("=" * 60)
    print("  Monitor DJEN x Projuris — Marques Advogados S.S")
    print("  Acesse: http://localhost:5000")
    print("=" * 60)
    app.run(debug=False, host="0.0.0.0", port=5000)
