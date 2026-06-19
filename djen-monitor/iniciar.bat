@echo off
chcp 65001 >nul
title Monitor DJEN x Projuris — Marques Advogados
echo.
echo  ============================================================
echo   Monitor DJEN x Projuris — Marques Advogados S.S
echo  ============================================================
echo.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
echo  Iniciando servidor... aguarde.
echo  Acesse: http://localhost:5000
echo.
python -X utf8 app.py
pause
