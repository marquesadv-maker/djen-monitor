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

if "%FINANCEIRO_PORTA%"=="" set FINANCEIRO_PORTA=8010

if "%FINANCEIRO_USUARIO_LOCAL%"=="" (
  set /p FINANCEIRO_USUARIO_LOCAL="  Seu e-mail (o mesmo cadastrado em permissoes.json): "
)

echo.
echo  Instalando dependencias, se faltar alguma...
python -m pip install -q -r modulos\financeiro\requirements.txt

echo.
echo  Endereco: http://localhost:%FINANCEIRO_PORTA%/financeiro
echo  O navegador abre sozinho assim que o servidor responder.
echo.
echo  Se aparecer "Acesso negado", inclua seu e-mail em
echo  modulos\financeiro\config\permissoes.json — o padrao do modulo e negar.
echo.
echo  Esta janela precisa ficar aberta. Para encerrar: Ctrl+C
echo.

rem Abre o navegador em segundo plano assim que a porta responder — em vez
rem de um "timeout" fixo, que abriria cedo demais numa maquina lenta ou
rem tarde demais numa rapida. Espera ate 30s; se o servidor nao subir
rem nesse prazo, desiste em silencio (a janela do servidor mostra o erro).
start "" /b powershell -NoProfile -WindowStyle Hidden -Command ^
  "$u='http://localhost:%FINANCEIRO_PORTA%/financeiro/saude';" ^
  "for($i=0;$i -lt 30;$i++){" ^
  "  try{ if((Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200){" ^
  "    Start-Process ('http://localhost:%FINANCEIRO_PORTA%/financeiro'); break } }" ^
  "  catch{} Start-Sleep -Seconds 1 }"

python -X utf8 -m modulos.financeiro.servidor_financeiro
pause
