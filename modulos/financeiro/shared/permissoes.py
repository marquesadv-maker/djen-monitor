"""
Controle de acesso do módulo Financeiro.

Padrão **negar**: quem não está em `config/permissoes.json` não vê o item
na navegação e também não alcança a API por URL direta. Esconder botão no
frontend é conveniência; o controle é aqui, no backend.

As duas abas têm níveis independentes — a mesma pessoa pode ter `leitura`
em NFS-e e `gravacao` em conciliação.

A identidade vem do cabeçalho posto pelo proxy reverso (nginx) que já
autentica o painel. Este módulo não implementa login próprio: inventar
uma autenticação paralela daria a impressão de proteção sem o rigor de
uma de verdade.
"""

from __future__ import annotations

import json
import os
from functools import wraps
from pathlib import Path

from flask import g, jsonify, render_template, request

RAIZ = Path(__file__).resolve().parent.parent
CAMINHO_PERMISSOES = RAIZ / "config" / "permissoes.json"

# Ordem crescente: quem tem 'gravacao' também pode operar e ler.
NIVEIS = ("negado", "leitura", "operacao", "gravacao")
ABAS = ("conciliacao", "nfse")

CABECALHO_PADRAO = "X-Usuario-Financeiro"


def carregar() -> dict:
    """Lê o arquivo a cada chamada: mudar permissão não exige reiniciar o serviço."""
    try:
        with open(CAMINHO_PERMISSOES, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"padrao": "negado", "usuarios": []}
    except json.JSONDecodeError as erro:
        # Arquivo quebrado nega tudo. Falhar fechado é o comportamento certo
        # num módulo de faturamento.
        return {"padrao": "negado", "usuarios": [], "_erro": str(erro)}


def identificar() -> str:
    """Quem está pedindo. Vazio quando não há identidade — o que nega tudo."""
    cfg = carregar()
    cabecalho = cfg.get("cabecalho_identidade") or CABECALHO_PADRAO
    usuario = request.headers.get(cabecalho, "") if request else ""
    if not usuario:
        # Uso local, fora do nginx. Não é atalho de permissão: o usuário
        # apontado aqui ainda precisa estar na lista com o nível necessário.
        usuario = os.environ.get("FINANCEIRO_USUARIO_LOCAL", "")
    return usuario.strip().lower()


def nivel_de(usuario: str, aba: str) -> str:
    """Nível do usuário naquela aba, conforme o arquivo. Padrão: negado."""
    if aba not in ABAS:
        raise ValueError(f"Aba inválida: {aba!r}")
    if not usuario:
        return "negado"

    cfg = carregar()
    for registro in cfg.get("usuarios", []):
        ident = str(registro.get("identificador", "")).strip().lower()
        if ident and ident == usuario:
            nivel = str(registro.get(aba, "")).strip().lower()
            return nivel if nivel in NIVEIS else "negado"
    return "negado"


def tem_nivel(usuario: str, aba: str, minimo: str) -> bool:
    if minimo not in NIVEIS:
        raise ValueError(f"Nível inválido: {minimo!r}")
    return NIVEIS.index(nivel_de(usuario, aba)) >= NIVEIS.index(minimo)


def resumo_acesso() -> dict:
    """O que o usuário atual pode ver — usado pela navegação e pelo banner."""
    usuario = identificar()
    cfg = carregar()
    niveis = {aba: nivel_de(usuario, aba) for aba in ABAS}
    return {
        "usuario": usuario,
        "identificado": bool(usuario),
        "niveis": niveis,
        "algum_acesso": any(n != "negado" for n in niveis.values()),
        "lista_vazia": not cfg.get("usuarios"),
        "responsavel": cfg.get("responsavel", ""),
        "cabecalho_identidade": cfg.get("cabecalho_identidade") or CABECALHO_PADRAO,
    }


def exigir(aba: str, minimo: str):
    """Decorator de rota. Nega com 403 e diz o que falta, sem expor a lista."""
    def decorador(func):
        @wraps(func)
        def envolvido(*args, **kwargs):
            usuario = identificar()
            if not tem_nivel(usuario, aba, minimo):
                atual = nivel_de(usuario, aba)
                if not usuario:
                    motivo = (
                        "Usuário não identificado. O painel envia a identidade "
                        f"no cabeçalho {carregar().get('cabecalho_identidade') or CABECALHO_PADRAO}."
                    )
                else:
                    motivo = (
                        f"Seu nível nesta aba é '{atual}' e esta ação exige "
                        f"'{minimo}'. A lista de acesso é definida pela "
                        "responsável pelo financeiro."
                    )
                if "/api/" in request.path:
                    return jsonify({
                        "erro": "acesso_negado",
                        "aba": aba,
                        "nivel_exigido": minimo,
                        "nivel_atual": atual,
                        "mensagem": motivo,
                    }), 403
                # Página: a negativa também é tela, não JSON cru.
                return render_template("sem_acesso.html", mensagem=motivo,
                                       acesso=resumo_acesso(), situacao=None), 403
            g.usuario_financeiro = usuario
            g.nivel_financeiro = nivel_de(usuario, aba)
            return func(*args, **kwargs)
        return envolvido
    return decorador
