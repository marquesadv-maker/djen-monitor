#!/usr/bin/env python3
"""Busca publicacoes DJEN do dia sem depender do Projuris."""

import requests, json, re, sys

DJEN_BASE = "https://comunicaapi.pje.jus.br/api/v1"
OAB = "2265"; UF = "TO"
DATA = "2026-06-18"
TRIBUNAIS = ["TJTO", "TRT10", "TRT8", "TRF1"]

URGENTES    = ["audiencia", "pericia", "contestacao", "defesa", "prazo", "intimacao"]
IMPORTANTES = ["sentenca", "acordao", "recurso", "apelacao", "execucao",
               "penhora", "leilao", "cumprimento", "manifestacao"]

def normalizar(texto):
    subs = {"ê":"e","é":"e","è":"e","á":"a","ã":"a","â":"a","à":"a",
            "ç":"c","ó":"o","õ":"o","ô":"o","ú":"u","í":"i","î":"i"}
    for k, v in subs.items():
        texto = texto.replace(k, v)
    return texto.lower()

todas = []
for trib in TRIBUNAIS:
    pag = 1
    while True:
        r = requests.get(f"{DJEN_BASE}/comunicacao", params={
            "pagina": pag, "itensPorPagina": 20, "meio": "D",
            "tribunal": trib, "dataDisponibilizacaoInicio": DATA,
            "dataDisponibilizacaoFim": DATA, "numeroOab": OAB, "ufOab": UF
        }, timeout=30)
        dados = r.json()
        itens = dados.get("items", [])
        if not itens:
            break
        for i in itens:
            i["_tribunal"] = trib
        todas.extend(itens)
        print(f"  {trib} p.{pag}: {len(itens)} publicacoes", flush=True)
        if len(itens) < 20:
            break
        pag += 1

print(f"\nTOTAL: {len(todas)} publicacoes encontradas\n")
print("=" * 70)

urgentes = imp = info = 0
for pub in todas:
    texto_norm = normalizar(pub.get("texto", "") + " " + pub.get("tipoComunicacao", ""))
    if any(x in texto_norm for x in URGENTES):
        cls = "URGENTE"
        urgentes += 1
    elif any(x in texto_norm for x in IMPORTANTES):
        cls = "IMPORTANTE"
        imp += 1
    else:
        cls = "INFORMATIVA"
        info += 1

    num  = pub.get("numeroprocessocommascara") or pub.get("numero_processo", "SEM NUMERO")
    trib = pub.get("siglaTribunal", pub.get("_tribunal", "?"))
    orgao = pub.get("nomeOrgao", "?")
    data_pub = pub.get("datadisponibilizacao", pub.get("data_disponibilizacao", "?"))
    tipo = pub.get("tipoComunicacao", "?")
    tipo_doc = pub.get("tipoDocumento", "")
    link = pub.get("link", "")

    destinos = pub.get("destinatarios", [])
    ativos   = [d["nome"] for d in destinos if d.get("polo") == "A"]
    passivos = [d["nome"] for d in destinos if d.get("polo") == "P"]

    texto_html = pub.get("texto", "")
    texto_limpo = re.sub(r"<[^>]+>", " ", texto_html).strip()
    texto_limpo = re.sub(r"\s+", " ", texto_limpo)[:220]

    print(f"[{cls}] {trib} | {num}")
    print(f"  Tipo  : {tipo} / {tipo_doc}")
    print(f"  Orgao : {orgao}")
    print(f"  Data  : {data_pub}")
    if ativos:
        print(f"  Polo A: {' | '.join(ativos)}")
    if passivos:
        print(f"  Polo P: {' | '.join(passivos)}")
    print(f"  Teor  : {texto_limpo}")
    if link:
        print(f"  Link  : {link}")
    print()

print("=" * 70)
print(f"RESUMO: {urgentes} URGENTES | {imp} IMPORTANTES | {info} INFORMATIVAS")
print(f"TOTAL : {len(todas)} publicacoes em {DATA}")
