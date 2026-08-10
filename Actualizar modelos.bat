@echo off
chcp 65001 >nul
title Actualizar Biblioteca Laser
setlocal
cd /d "%~dp0"

echo.
echo  Buscando modelos nuevos en tu carpeta...
echo.

if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

"%PY%" indexar.py
if errorlevel 1 (
  echo.
  echo  Hubo un problema. Abre primero "INICIAR Biblioteca.bat".
  echo.
  pause
  exit /b
)

echo.
echo  Listo. Ya puedes abrir la biblioteca.
echo.
pause
endlocal
