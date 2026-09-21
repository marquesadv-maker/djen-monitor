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
import secrets
from pathlib import Path

from flask import (Blueprint, Flask, redirect, render_template, request,
                   session)

from .conciliacao.api.rotas import bp as bp_conciliacao
from .nfse.api.rotas import bp as bp_nfse
from .shared import auditoria, modo, senha_chave
from .shared.permissoes import identificar, resumo_acesso

RAIZ = Path(__file__).resolve().parent

# Caminhos que respondem sem a senha-chave: a própria tela de entrada, o
# health check (usado por monitoramento, não por gente clicando) e os
# arquivos estáticos — a tela de entrada precisa do próprio CSS/logo para
# não renderizar quebrada antes de alguém digitar a senha.
CAMINHOS_LIVRES = {"/financeiro/entrar", "/financeiro/sair", "/financeiro/saude"}

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
    """Sem dado sensível: só o suficiente para o nginx e para o plantão.

    Fora da senha-chave de propósito — é o endpoint que o monitoramento
    bate para saber se o serviço está de pé, não uma pessoa navegando.
    """
    return {
        "modulo": "financeiro",
        "ok": True,
        "conciliacao": modo.situacao("conciliacao")["modo"],
        "nfse": modo.situacao("nfse")["modo"],
    }


@bp_web.route("/financeiro/entrar", methods=["GET", "POST"])
def tela_entrar():
    """Senha-chave do módulo inteiro — camada extra, além do controle por
    e-mail em `shared/permissoes.py`. Quem já está desbloqueado nesta
    sessão de navegador é mandado direto para o índice."""
    if session.get(senha_chave.CHAVE_SESSAO):
        return redirect("/financeiro")

    if request.method == "GET":
        return render_template("entrar.html", erro=None)

    senha = request.form.get("senha", "")
    if senha_chave.verificar(senha):
        session.clear()
        session[senha_chave.CHAVE_SESSAO] = True
        session.permanent = True
        auditoria.registrar(aba="acesso", usuario=identificar(),
                            acao="entrar", resultado="sucesso")
        return redirect("/financeiro")

    auditoria.registrar(aba="acesso", usuario=identificar(),
                        acao="entrar", resultado="falha")
    return render_template("entrar.html", erro="Senha incorreta."), 401


@bp_web.post("/financeiro/sair")
def tela_sair():
    session.pop(senha_chave.CHAVE_SESSAO, None)
    return redirect("/financeiro/entrar")


def _chave_secreta() -> str:
    """Assina o cookie de sessão do Flask (a senha-chave em si nunca vai
    no cookie, só a marca de "desbloqueado"). Uma variável de ambiente
    tem prioridade; sem ela, gera uma vez e persiste fora do
    versionamento — trocar a cada reinício derrubaria todo mundo logado
    toda vez que o serviço reiniciasse."""
    variavel = os.environ.get("FINANCEIRO_SECRET_KEY")
    if variavel:
        return variavel
    caminho = RAIZ / "dados" / ".chave_secreta"
    if caminho.exists():
        return caminho.read_text(encoding="utf-8").strip()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    chave = secrets.token_hex(32)
    caminho.write_text(chave, encoding="utf-8")
    return chave


def _e_caminho_livre(caminho: str) -> bool:
    return caminho in CAMINHOS_LIVRES or "/static/" in caminho


def criar_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024   # extrato de um mês
    app.config["JSON_SORT_KEYS"] = False
    app.secret_key = _chave_secreta()
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    app.register_blueprint(bp_web)
    app.register_blueprint(bp_conciliacao)
    app.register_blueprint(bp_nfse)

    @app.before_request
    def exigir_senha_chave():
        if _e_caminho_livre(request.path):
            return None
        if not session.get(senha_chave.CHAVE_SESSAO):
            return redirect("/financeiro/entrar")
        return None

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
