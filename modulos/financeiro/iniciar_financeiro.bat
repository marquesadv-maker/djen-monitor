@echo off
chcp 65001 >nul
title Ambiente Financeiro — Marques Advogados
echo.
echo  ============================================================
echo   Ambiente Financeiro — Marques Advogados S/S
echo   Conciliacao bancaria  ·  NFS-e Araguaina/TO
echo  ============================================================
echo.

rem Sobe a partir da raiz do repositorio: o modulo e importado como
rem pacote (modulos.financeiro), entao o diretorio de trabalho e a raiz.
cd /d "%~dp0..\.."
set PYTHONIOENCODING=utf-8

if "%FINANCEIRO_USUARIO_LOCAL%"=="" (
  set /p FINANCEIRO_USUARIO_LOCAL="  Seu e-mail (o mesmo cadastrado em permissoes.json): "
)

echo.
echo  Instalando dependencias, se faltar alguma...
python -m pip install -q -r modulos\financeiro\requirements.txt

echo.
echo  Acesse: http://localhost:8010/financeiro
echo.
echo  Se aparecer "Acesso negado", inclua seu e-mail em
echo  modulos\financeiro\config\permissoes.json — o padrao do modulo e negar.
echo.
echo  Para encerrar: Ctrl+C
echo.

python -X utf8 -m modulos.financeiro.servidor_financeiro
pause
