@echo off
chcp 65001 >nul
title Cambiar carpeta de modelos
setlocal
cd /d "%~dp0"

echo.
echo  Vas a elegir de nuevo donde estan tus modelos.
echo.

if exist "config.json" del /q "config.json"

if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

"%PY%" indexar.py
echo.
echo  Listo. Abre "INICIAR Biblioteca.bat".
echo.
pause
endlocal
