#!/usr/bin/env bash
# Ambiente Financeiro — Marques Advogados S/S
# Linux/macOS e servidor MarquesPro. Equivalente ao iniciar_financeiro.bat.
set -euo pipefail

# A raiz do repositório é o diretório de trabalho: o módulo é importado
# como pacote (modulos.financeiro).
cd "$(dirname "$0")/../.."

PORTA="${FINANCEIRO_PORTA:-8010}"

if [ -z "${FINANCEIRO_USUARIO_LOCAL:-}" ]; then
  read -rp "  Seu e-mail (o mesmo cadastrado em permissoes.json): " FINANCEIRO_USUARIO_LOCAL
  export FINANCEIRO_USUARIO_LOCAL
fi

# O ambiente virtual fica dentro do módulo, não na raiz do repositório:
# nada do financeiro se espalha pelo restante do projeto.
VENV="modulos/financeiro/.venv"
PY="${PYTHON:-python3}"
if [ ! -d "$VENV" ]; then
  echo "  Criando ambiente virtual em $VENV..."
  "$PY" -m venv "$VENV"
fi
# shellcheck disable=SC1091
. "$VENV/bin/activate"
pip install -q -r modulos/financeiro/requirements.txt

cat <<FIM

  ============================================================
   Ambiente Financeiro — conciliação bancária · NFS-e
  ============================================================

  Acesse: http://localhost:${PORTA}/financeiro

  Se aparecer "Acesso negado", inclua seu e-mail em
  modulos/financeiro/config/permissoes.json — o padrão do módulo é negar.

  Para encerrar: Ctrl+C

FIM

exec python -m modulos.financeiro.servidor_financeiro
