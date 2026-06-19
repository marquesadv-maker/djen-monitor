@echo off
echo ============================================
echo  Enviando djen-monitor para o GitHub...
echo ============================================
echo.

cd /d "C:\Users\maria\OneDrive\Area de Trabalho\CLAUDE\djen-monitor"
if errorlevel 1 (
    cd /d "C:\Users\maria\OneDrive\Área de Trabalho\CLAUDE\djen-monitor"
)

echo Pasta atual:
cd
echo.

git init
echo.

git add .
echo.

git commit -m "Monitor DJEN x Projuris"
echo.

git branch -M main
echo.

git remote remove origin 2>nul
git remote add origin https://github.com/marquesadv-maker/djen-monitor.git
echo.

echo ============================================
echo  Fazendo push para o GitHub...
echo  (Sera solicitado usuario e token do GitHub)
echo ============================================
echo.

git push -u origin main

echo.
echo ============================================
echo  Concluido! Verifique o resultado acima.
echo ============================================
echo.
pause
