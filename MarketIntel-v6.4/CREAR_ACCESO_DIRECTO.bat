@echo off
setlocal
cd /d "%~dp0"
title MarketIntel - Crear acceso directo
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0crear_acceso_directo.ps1"
if errorlevel 1 (
  echo No se pudo crear el acceso directo de MarketIntel.
  pause
  exit /b 1
)
endlocal
