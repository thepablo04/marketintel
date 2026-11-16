@echo off
setlocal
cd /d "%~dp0"
title MarketIntel - Elegir perfil del navegador
where py >nul 2>&1
if errorlevel 1 (
  python iniciar_app.py --elegir-perfil
) else (
  py -3 iniciar_app.py --elegir-perfil
)
if errorlevel 1 pause
endlocal
