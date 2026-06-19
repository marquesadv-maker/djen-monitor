#!/usr/bin/env python3
"""
Monitor DJEN x Projuris — Marques Advogados S.S
OAB/TO 2.265 — Micheline R. Nolasco Marques
"""

import requests
import json
import re
import time
import sys
import subprocess
import tempfile
import os
from datetime import date, timedelta, datetime
from urllib.parse import urlencode

# ─── Configurações fixas ──────────────────────────────────────────────────
PROJURIS_AUTH_URL  = "https://apigw.projurisadv.com.br/auth/token"
PROJURIS_BASE_URL  = "https://api.projurisadv.com.br/adv-service"
DJEN_BASE_URL      = "https://comunicaapi.pje.jus.br/api/v1"

PROJURIS_USERNAME      = "mariaelisanolasco@outlook.com$$marques-advogados3"
PROJURIS_CLIENT_ID     = "api_cliente_codigo_53034"
PROJURIS_CLIENT_SECRET = "mh1gELhl6bf3hnDIL550Z4rTyWJiZKQI"

OAB_NUMERO = "2265"
OAB_UF     = "TO"

TRIBUNAIS_PADRAO = ["TJTO", "TRT10", "TRT8", "TRF1"]

PALAVRAS_URGENTES = [
    "audiência", "audiencia", "perícia", "pericia",
    "contestação", "contestacao", "defesa", "prazo", "intimação", "intimacao"
]
PALAVRAS_IMPORTANTES = [
    "sentença", "sentenca", "acórdão", "acordao",
    "recurso", "apelação", "apelacao", "execução", "execucao",
    "penhora", "leilão", "leilao", "cumprimento", "manifestação", "manifestacao"
]


# ═══════════════════════════════════════════════════════════════
# RESOLUÇÃO DE DATA
# ═══════════════════════════════════════════════════════════════

def resolver_data(entrada: str) -> date:
    entrada = entrada.strip().lower()
    hoje = date.today()
    if entrada in ("hoje", "today", "h", ""):
        return hoje
    if entrada in ("ontem", "yesterday", "o"):
        return hoje - timedelta(days=1)
    for fmt_sep in [("/", 0, 1, 2), ("-", 0, 1, 2)]:
        sep = fmt_sep[0]
        if sep in entrada:
            partes = entrada.split(sep)
            if len(partes) == 3:
                try:
                    d, m, a = int(partes[0]), int(partes[1]), int(partes[2])
                    if a < 100:
                        a += 2000
                    return date(a, m, d)
                except:
                    pass
    try:
        return date.fromisoformat(entrada)
    except:
        pass
    raise ValueError(f"Data inválida: '{entrada}'. Use hoje/ontem/DD/MM/AAAA")


# ═══════════════════════════════════════════════════════════════
# AUTENTICAÇÃO PROJURIS
# ═══════════════════════════════════════════════════════════════

def _ps_script(script: str) -> str:
    """Grava script em arquivo temp e executa via PowerShell."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".ps1",
                                     encoding="utf-8", delete=False) as f:
        f.write(script)
        path = f.name
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-File", path],
            capture_output=True, text=True, encoding="utf-8", timeout=90
        )
        out = result.stdout.strip()
        err = result.stderr.strip()
        if not out and err:
            raise RuntimeError(f"PowerShell erro: {err[:300]}")
        return out
    finally:
        try:
            os.unlink(path)
        except:
            pass


def autenticar_projuris(senha: str) -> str:
    from urllib.parse import quote
    user_enc   = quote(PROJURIS_USERNAME)
    senha_enc  = quote(senha)
    script = f"""
$body = "username={user_enc}&password={senha_enc}&grant_type=password&client_id={PROJURIS_CLIENT_ID}&client_secret={PROJURIS_CLIENT_SECRET}"
$r = Invoke-RestMethod -Uri "{PROJURIS_AUTH_URL}" -Method POST -ContentType "application/x-www-form-urlencoded" -Body $body
Write-Output $r.access_token
"""
    token = _ps_script(script)
    if not token or len(token) < 20:
        raise ValueError("Token não retornado pelo Projuris. Verifique a senha.")
    return token


def _projuris_post(token: str, endpoint: str, body: dict) -> dict:
    """Faz POST autenticado no Projuris via PowerShell script file."""
    body_json = json.dumps(body, ensure_ascii=False)
    script = f"""
$h = @{{
    Authorization = "Bearer {token}"
    Accept = "application/json"
    "Content-Type" = "application/json"
}}
$body = @'
{body_json}
'@
try {{
    $r = Invoke-RestMethod -Uri "{PROJURIS_BASE_URL}/{endpoint}" -Method POST -Headers $h -Body $body
    $r | ConvertTo-Json -Depth 6 -Compress
}} catch {{
    Write-Output ""
}}
"""
    out = _ps_script(script)
    if not out:
        return {}
    try:
        return json.loads(out)
    except:
        return {}


# ═══════════════════════════════════════════════════════════════
# BUSCA DJEN
# ═══════════════════════════════════════════════════════════════

def buscar_publicacoes_djen(data_iso: str, tribunais: list) -> list:
    todas = []
    erros = []

    for tribunal in tribunais:
        pagina = 1
        total_tribunal = 0
        while True:
            params = {
                "pagina": pagina,
                "itensPorPagina": 20,
                "meio": "D",
                "tribunal": tribunal,
                "dataDisponibilizacaoInicio": data_iso,
                "dataDisponibilizacaoFim": data_iso,
                "numeroOab": OAB_NUMERO,
                "ufOab": OAB_UF,
            }
            tentativas = 0
            resp = None
            while tentativas < 3:
                try:
                    resp = requests.get(
                        f"{DJEN_BASE_URL}/comunicacao",
                        params=params,
                        timeout=30
                    )
                    if resp.status_code == 503:
                        print(f"   ⏳ DJEN 503 ({tribunal} p.{pagina}) — aguardando 5s...")
                        time.sleep(5)
                        tentativas += 1
                        continue
                    resp.raise_for_status()
                    break
                except requests.exceptions.RequestException as e:
                    tentativas += 1
                    if tentativas >= 3:
                        erros.append(f"DJEN/{tribunal}/p{pagina}: {e}")
                        resp = None
                    else:
                        time.sleep(5)

            if resp is None:
                break

            try:
                dados = resp.json()
            except:
                erros.append(f"DJEN/{tribunal}/p{pagina}: resposta não é JSON")
                break

            # Normalizar estrutura da resposta
            if isinstance(dados, list):
                itens = dados
                total = len(dados)
            elif isinstance(dados, dict):
                itens = dados.get("comunicacoes",
                         dados.get("items",
                         dados.get("content",
                         dados.get("data", []))))
                total = dados.get("total", dados.get("totalElements", 0))
            else:
                break

            if not itens:
                break

            # Marcar tribunal de origem
            for item in itens:
                item["_tribunal"] = tribunal

            todas.extend(itens)
            total_tribunal += len(itens)

            print(f"   {tribunal}: página {pagina} — {len(itens)} publicações")

            if len(itens) < 20:
                break
            if total and total_tribunal >= total:
                break
            pagina += 1

        print(f"   ✅ {tribunal}: {total_tribunal} publicações no total")

    return todas, erros


# ═══════════════════════════════════════════════════════════════
# CLASSIFICAÇÃO DE URGÊNCIA
# ═══════════════════════════════════════════════════════════════

def classificar_publicacao(pub: dict) -> str:
    # Campo real da API DJEN: "texto" (não "conteudo")
    texto = (
        pub.get("texto", "") + " " +
        pub.get("tipoComunicacao", "") + " " +
        pub.get("tipoDocumento", "")
    ).lower()

    for p in PALAVRAS_URGENTES:
        if p in texto:
            return "URGENTE"
    for p in PALAVRAS_IMPORTANTES:
        if p in texto:
            return "IMPORTANTE"
    return "INFORMATIVA"


def extrair_numero_processo(pub: dict) -> str:
    # API DJEN usa "numeroprocessocommascara" para o CNJ com máscara
    # e "numero_processo" para só dígitos
    num = (
        pub.get("numeroprocessocommascara") or
        pub.get("numero_processo") or
        pub.get("numeroProcesso") or
        pub.get("numProcesso") or
        ""
    )
    if not num:
        texto = pub.get("texto", "")
        match = re.search(r'\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}', texto)
        if match:
            num = match.group(0)
    return str(num).strip() if num else ""


def extrair_partes(pub: dict) -> tuple:
    """Retorna (polo_ativo, polo_passivo) a partir de destinatarios[]"""
    destinatarios = pub.get("destinatarios", [])
    ativos   = [d["nome"] for d in destinatarios if d.get("polo") == "A"]
    passivos = [d["nome"] for d in destinatarios if d.get("polo") == "P"]
    return (", ".join(ativos) or "—", ", ".join(passivos) or "—")


def extrair_prazo(conteudo: str) -> str:
    conteudo_lower = conteudo.lower()
    padroes = [
        r'prazo\s+de\s+(\d+)\s+dias?\s+úteis?',
        r'prazo\s+de\s+(\d+)\s+dias?',
        r'no\s+prazo\s+de\s+(\d+)',
        r'(\d+)\s+dias?\s+para\s+(?:apresentar|manifestar|contestar|recorrer)',
    ]
    for padrao in padroes:
        match = re.search(padrao, conteudo_lower)
        if match:
            return f"{match.group(1)} dias"
    return ""


# ═══════════════════════════════════════════════════════════════
# CRUZAMENTO COM PROJURIS
# ═══════════════════════════════════════════════════════════════

def _headers_projuris(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def verificar_no_projuris(token: str, numero_processo: str) -> dict:
    resultado = {
        "encontrado": False,
        "id_projuris": None,
        "dados_processo": None,
        "tarefas": [],
        "status": "NAO CADASTRADO",
        "erro": None,
    }

    if not numero_processo:
        resultado["status"] = "SEM NUMERO DE PROCESSO"
        return resultado

    try:
        dados = _projuris_post(token, "v2/processo/consulta", {
            "pagina": 0, "tamanhoPagina": 3, "numeroProcesso": numero_processo
        })
        processos = dados.get("processoConsultaResumoWs", [])

        # Tentar com só dígitos se não encontrou
        if not processos:
            num_digitos = re.sub(r'\D', '', numero_processo)
            if num_digitos != numero_processo:
                dados2 = _projuris_post(token, "v2/processo/consulta", {
                    "pagina": 0, "tamanhoPagina": 3, "numeroProcesso": num_digitos
                })
                processos = dados2.get("processoConsultaResumoWs", [])

        if processos:
            processo = processos[0]
            resultado["encontrado"] = True
            resultado["id_projuris"] = processo.get("codigoProcesso")
            resultado["dados_processo"] = processo
            resultado["status"] = "CADASTRADO"

    except Exception as e:
        resultado["erro"] = str(e)[:120]
        resultado["status"] = "ERRO NA CONSULTA"
        return resultado

    return resultado


def determinar_status_tarefa(resultado_projuris: dict, classificacao: str) -> str:
    if not resultado_projuris["encontrado"]:
        return "⛔ NÃO CADASTRADO"

    if classificacao == "INFORMATIVA":
        return "🔵 INFORMATIVA"

    tarefas = resultado_projuris.get("tarefas", [])
    if not tarefas:
        return "⚠️ SEM TAREFA"

    # Verificar tarefas abertas
    abertas = [t for t in tarefas if str(t.get("situacao", t.get("status", ""))).upper()
               not in ("CONCLUIDA", "CONCLUÍDO", "CONCLUIDO", "FINALIZADA", "FECHADA")]

    if abertas:
        return "✅ REGULARIZADO"
    return "🔵 TAREFA CONCLUÍDA"


# ═══════════════════════════════════════════════════════════════
# GERAÇÃO DO RELATÓRIO
# ═══════════════════════════════════════════════════════════════

def gerar_relatorio(data_ref: date, tribunais: list, resultados: list, erros_djen: list) -> str:
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")
    data_str = data_ref.strftime("%d/%m/%Y")

    # Categorizar
    nao_cadastrados = []
    sem_tarefa = []
    regularizados = []
    informativos = []
    erros_processo = []

    for r in resultados:
        pub = r["publicacao"]
        proj = r["projuris"]
        classificacao = pub.get("_classificacao", "INFORMATIVA")
        status_final = r.get("_status_final", "")

        if proj.get("erro"):
            erros_processo.append(r)
        elif "NÃO CADASTRADO" in status_final or "SEM NÚMERO" in status_final:
            nao_cadastrados.append(r)
        elif "SEM TAREFA" in status_final:
            sem_tarefa.append(r)
        elif "REGULARIZADO" in status_final or "TAREFA CONCLUÍDA" in status_final:
            regularizados.append(r)
        else:
            informativos.append(r)

    total = len(resultados)
    total_cadastrados = sum(1 for r in resultados if r["projuris"].get("encontrado"))
    total_nao_cadastrados = len(nao_cadastrados)
    total_sem_tarefa = len(sem_tarefa)
    total_regularizados = len(regularizados)
    total_urgentes = sum(
        1 for r in resultados
        if r["publicacao"].get("_classificacao") == "URGENTE"
        and r.get("_status_final", "") in ("⛔ NÃO CADASTRADO", "⚠️ SEM TAREFA")
    )

    linhas = []
    L = linhas.append

    L("═══════════════════════════════════════════════════════════════")
    L("         RELATÓRIO DIÁRIO DE PUBLICAÇÕES — DJEN × PROJURIS")
    L("              Marques Advogados S.S | OAB/TO nº 2.265")
    L("═══════════════════════════════════════════════════════════════")
    L("")
    L(f"Data verificada  : {data_str}")
    L(f"Data de emissão  : {agora}")
    L(f"Tribunais        : {', '.join(tribunais)}")
    L(f"Advogada         : Micheline R. Nolasco Marques — OAB/TO 2.265")
    L("")
    L("──────────────────────────────────────────────────────────────")
    L("RESUMO EXECUTIVO")
    L("──────────────────────────────────────────────────────────────")
    L("")
    L("| Indicador                          | Quantidade |")
    L("|------------------------------------|-----------|")
    L(f"| Total de publicações localizadas   | {total:^9} |")
    L(f"| Processos cadastrados no Projuris  | {total_cadastrados:^9} |")
    L(f"| Processos NÃO cadastrados          | {total_nao_cadastrados:^9} |")
    L(f"| Publicações com tarefa registrada  | {total_regularizados:^9} |")
    L(f"| Publicações SEM tarefa registrada  | {total_sem_tarefa:^9} |")
    L(f"| Itens que exigem ação imediata     | {total_urgentes:^9} |")
    L("")

    # ── NÃO CADASTRADOS ──
    L("──────────────────────────────────────────────────────────────")
    L("⛔ AÇÃO URGENTE — PROCESSOS NÃO CADASTRADOS NO PROJURIS")
    L("──────────────────────────────────────────────────────────────")
    L("")
    if nao_cadastrados:
        for r in nao_cadastrados:
            pub = r["publicacao"]
            num = extrair_numero_processo(pub)
            texto = pub.get("texto", "")
            teor = re.sub(r'<[^>]+>', ' ', texto)[:250].strip()
            if len(texto) > 250:
                teor += "..."
            polo_ativo, polo_passivo = extrair_partes(pub)
            L(f"Processo    : {num or 'NAO IDENTIFICADO'}")
            L(f"Tribunal    : {pub.get('siglaTribunal', pub.get('_tribunal','?'))} | Orgao: {pub.get('nomeOrgao','?')}")
            L(f"Tipo        : {pub.get('_classificacao','?')} -- {pub.get('tipoComunicacao','?')} / {pub.get('tipoDocumento','')}")
            L(f"Publicado   : {pub.get('datadisponibilizacao', pub.get('data_disponibilizacao','?'))}")
            L(f"Partes      : {polo_ativo} (ativo) x {polo_passivo} (passivo)")
            L(f"Teor        : {teor}")
            L(f"Link        : {pub.get('link','')}")
            L(f"Acao        : Cadastrar processo no Projuris imediatamente")
            L("")
    else:
        L("Nenhum processo não cadastrado encontrado.")
        L("")

    # ── SEM TAREFA ──
    L("──────────────────────────────────────────────────────────────")
    L("⚠️  AÇÃO NECESSÁRIA — SEM TAREFA CADASTRADA NO PROJURIS")
    L("──────────────────────────────────────────────────────────────")
    L("")
    if sem_tarefa:
        for r in sem_tarefa:
            pub = r["publicacao"]
            proj = r["projuris"]
            num = extrair_numero_processo(pub)
            texto = pub.get("texto", "")
            prazo = extrair_prazo(texto)
            polo_ativo, polo_passivo = extrair_partes(pub)
            L(f"Processo    : {num}")
            L(f"ID Projuris : {proj.get('id_projuris','?')}")
            L(f"Tribunal    : {pub.get('siglaTribunal', pub.get('_tribunal','?'))}")
            L(f"Tipo        : {pub.get('_classificacao','?')} -- {pub.get('tipoComunicacao','?')}")
            L(f"Partes      : {polo_ativo} x {polo_passivo}")
            if prazo:
                L(f"Prazo       : {prazo} (a partir de {pub.get('datadisponibilizacao','?')})")
            L(f"Acao        : Criar tarefa no Projuris com prazo adequado")
            L(f"Link        : {pub.get('link','')}")
            L("")
    else:
        L("Nenhuma publicação sem tarefa encontrada.")
        L("")

    # ── REGULARIZADOS ──
    L("──────────────────────────────────────────────────────────────")
    L("✅ REGULARIZADOS — PUBLICAÇÕES COM CADASTRO E TAREFA OK")
    L("──────────────────────────────────────────────────────────────")
    L("")
    if regularizados:
        for i, r in enumerate(regularizados, 1):
            pub = r["publicacao"]
            proj = r["projuris"]
            num = extrair_numero_processo(pub)
            tarefas = proj.get("tarefas", [])
            desc_tarefa = tarefas[0].get("descricao", tarefas[0].get("titulo", "—")) if tarefas else "—"
            prazo_tarefa = tarefas[0].get("dataLimite", tarefas[0].get("prazo", "—")) if tarefas else "—"
            L(f"{i}. {num} | {pub.get('_classificacao','?')} | Tarefa: {desc_tarefa} | Prazo: {prazo_tarefa}")
    else:
        L("Nenhum processo regularizado encontrado.")
    L("")

    # ── INFORMATIVOS ──
    L("──────────────────────────────────────────────────────────────")
    L("🔵 PUBLICAÇÕES SEM CLASSIFICAÇÃO DE URGÊNCIA (INFORMATIVAS)")
    L("──────────────────────────────────────────────────────────────")
    L("")
    if informativos:
        for r in informativos:
            pub = r["publicacao"]
            proj = r["projuris"]
            num = extrair_numero_processo(pub)
            status_proj = "Cadastrado" if proj.get("encontrado") else "Não cadastrado"
            L(f"Processo: {num} | Tipo: {pub.get('tipoComunicacao','?')} | Projuris: {status_proj}")
    else:
        L("Nenhuma publicação informativa.")
    L("")

    # ── ERROS ──
    todos_erros = erros_djen + [
        f"Processo {extrair_numero_processo(r['publicacao'])}: {r['projuris'].get('erro')}"
        for r in erros_processo
    ]
    if todos_erros:
        L("──────────────────────────────────────────────────────────────")
        L("OBSERVAÇÕES E PENDÊNCIAS")
        L("──────────────────────────────────────────────────────────────")
        L("")
        for erro in todos_erros:
            L(f"⚠️  {erro}")
        L("")

    L("══════════════════════════════════════════════════════════════")
    L("Relatório gerado automaticamente — conferir sempre antes de protocolar ou agir.")
    L("Marques Advogados S.S | contato@marques.adv.br")
    L("══════════════════════════════════════════════════════════════")

    return "\n".join(linhas)


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Monitor DJEN x Projuris")
    parser.add_argument("--data",     default="", help="Data: hoje/ontem/DD/MM/AAAA")
    parser.add_argument("--senha",    default="", help="Senha Projuris")
    parser.add_argument("--tribunais",default="", help="Tribunais separados por vírgula")
    args = parser.parse_args()

    print("═══════════════════════════════════════════════════════════════")
    print("         MONITOR DJEN x PROJURIS -- Marques Advogados S.S")
    print("         OAB/TO 2.265 -- Micheline R. Nolasco Marques")
    print("═══════════════════════════════════════════════════════════════")
    print()

    # 1. Inputs
    data_input = args.data.strip() if args.data else input("Data das publicacoes (hoje/ontem/DD/MM/AAAA): ").strip()
    if not data_input:
        data_input = "hoje"

    try:
        data_ref = resolver_data(data_input)
    except ValueError as e:
        print(f"ERRO: {e}")
        sys.exit(1)

    senha = args.senha.strip() if args.senha else input("Senha do Projuris ADV: ").strip()
    if not senha:
        print("ERRO: Senha obrigatoria.")
        sys.exit(1)

    tribunais_input = args.tribunais.strip() if args.tribunais else input(f"Tribunais [{', '.join(TRIBUNAIS_PADRAO)}] (Enter = padrao): ").strip()
    tribunais = (
        [t.strip().upper() for t in tribunais_input.split(",")]
        if tribunais_input
        else TRIBUNAIS_PADRAO
    )

    print(f"\n🔄 Iniciando verificação para {data_ref.strftime('%d/%m/%Y')}...")
    print(f"   Tribunais: {', '.join(tribunais)}\n")

    # 2. Autenticar no Projuris
    print("🔐 Autenticando no Projuris ADV...")
    try:
        token = autenticar_projuris(senha)
        print("   ✅ Autenticado com sucesso\n")
    except Exception as e:
        print(f"   ❌ Falha na autenticação: {e}")
        sys.exit(1)

    # 3. Buscar DJEN
    print("📡 Buscando publicações no DJEN...")
    publicacoes, erros_djen = buscar_publicacoes_djen(data_ref.isoformat(), tribunais)
    print(f"\n   📋 Total: {len(publicacoes)} publicações encontradas\n")

    if not publicacoes:
        print("ℹ️  Nenhuma publicação encontrada para os critérios informados.")
        print("   (Verifique se a data é dia útil e se os tribunais estão corretos)\n")

    # 4. Classificar
    for pub in publicacoes:
        pub["_classificacao"] = classificar_publicacao(pub)

    # 5. Cruzar com Projuris
    print("🔍 Cruzando com Projuris ADV...")
    resultados = []
    for i, pub in enumerate(publicacoes, 1):
        num = extrair_numero_processo(pub)
        if num:
            print(f"   [{i}/{len(publicacoes)}] {num}...", end="\r")
        verificacao = verificar_no_projuris(token, num)
        classificacao = pub.get("_classificacao", "INFORMATIVA")
        status_final = determinar_status_tarefa(verificacao, classificacao)
        resultados.append({
            "publicacao": pub,
            "projuris": verificacao,
            "_status_final": status_final,
        })

    print(f"\n   ✅ Cruzamento concluído: {len(resultados)} publicações processadas\n")

    # 6. Gerar relatório
    print("📝 Gerando relatório...\n")
    relatorio = gerar_relatorio(data_ref, tribunais, resultados, erros_djen)

    nome_arquivo = f"relatorio_djen_{data_ref.strftime('%Y%m%d')}.md"
    caminho = f"C:\\Users\\maria\\OneDrive\\Área de Trabalho\\CLAUDE\\scripts\\{nome_arquivo}"
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(relatorio)

    print(relatorio)
    print(f"\n✅ Relatório salvo em: {caminho}")

    # Resumo final
    nao_cadastrados = sum(1 for r in resultados if "NÃO CADASTRADO" in r.get("_status_final",""))
    sem_tarefa = sum(1 for r in resultados if "SEM TAREFA" in r.get("_status_final",""))
    urgentes = nao_cadastrados + sem_tarefa
    print(f"\n📊 RESUMO: {len(publicacoes)} publicações | {urgentes} exigem ação imediata")
    print(f"   ⛔ {nao_cadastrados} processos não cadastrados | ⚠️ {sem_tarefa} sem tarefa")


if __name__ == "__main__":
    main()
