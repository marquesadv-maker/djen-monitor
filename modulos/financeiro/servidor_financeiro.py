"""
Entrypoint do módulo Financeiro do MarquesPro.

Serviço próprio, porta própria, arquivos próprios. Não importa nada dos
outros módulos do painel e não é importado por eles — se este processo
cair, o monitor DJEN e os demais robôs seguem funcionando exatamente como
antes.

Execução local:
    python -m modulos.financeiro.servidor_financeiro

Produção (atrás do nginx, que já autentica e injeta a identidade):
    gunicorn "modulos.financeiro.servidor_financeiro:criar_app()" -b 127.0.0.1:8010
"""

from __future__ import annotations

import os
from pathlib import Path

from flask import Blueprint, Flask, redirect, render_template

from .conciliacao.api.rotas import bp as bp_conciliacao
from .nfse.api.rotas import bp as bp_nfse
from .shared import modo
from .shared.permissoes import resumo_acesso

RAIZ = Path(__file__).resolve().parent

# Layout e CSS comuns às duas abas — internos a este módulo.
bp_web = Blueprint(
    "financeiro_web", __name__,
    template_folder=str(RAIZ / "web" / "templates"),
    static_folder=str(RAIZ / "web" / "static"),
    static_url_path="/financeiro/static",
)


@bp_web.get("/financeiro")
@bp_web.get("/financeiro/")
def indice():
    acesso = resumo_acesso()
    if not acesso["algum_acesso"]:
        return render_template(
            "sem_acesso.html", acesso=acesso, situacao=None,
            mensagem=("Você não tem acesso a nenhuma aba do financeiro. "
                      "É o padrão do módulo: negar até que a responsável "
                      "inclua o usuário na lista."),
        ), 403
    return render_template("indice.html", acesso=acesso, situacao=None,
                           pagina="indice")


@bp_web.get("/financeiro/saude")
def saude():
    """Sem dado sensível: só o suficiente para o nginx e para o plantão."""
    return {
        "modulo": "financeiro",
        "ok": True,
        "conciliacao": modo.situacao("conciliacao")["modo"],
        "nfse": modo.situacao("nfse")["modo"],
    }


def criar_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024   # extrato de um mês
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(bp_web)
    app.register_blueprint(bp_conciliacao)
    app.register_blueprint(bp_nfse)

    @app.get("/")
    def raiz():
        return redirect("/financeiro")

    @app.errorhandler(413)
    def arquivo_grande(_):
        return {
            "erro": ("Arquivo acima do limite de 20 MB. Exporte o extrato em "
                     "períodos menores."),
        }, 413

    return app


if __name__ == "__main__":
    porta = int(os.environ.get("FINANCEIRO_PORTA", "8010"))
    criar_app().run(host=os.environ.get("FINANCEIRO_HOST", "127.0.0.1"),
                    port=porta, debug=False)
