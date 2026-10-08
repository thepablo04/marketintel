@echo off
setlocal
cd /d "%~dp0"
title MarketIntel
where py >nul 2>&1
if %errorlevel%==0 (set "PYTHON=py") else (set "PYTHON=python")
%PYTHON% -c "import flask, flask_cors, yfinance, pandas, requests, dotenv, exchange_calendars, tzdata" >nul 2>&1
if errorlevel 1 (
  echo Instalando dependencias de MarketIntel...
  %PYTHON% -m pip install -r requirements.txt
  if errorlevel 1 (echo No se pudieron instalar las dependencias.& pause & exit /b 1)
)
start "" /b %PYTHON% abrir_marketintel.py
%PYTHON% servidor.py
if errorlevel 1 pause
endlocal
