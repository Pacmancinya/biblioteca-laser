@echo off
chcp 65001 >nul
title Buscar actualizaciones - Biblioteca Laser
setlocal
cd /d "%~dp0"

echo.
echo  ============================================================
echo    BUSCAR ACTUALIZACIONES
echo  ============================================================
echo.
echo  (Tambien puedes hacerlo dentro de la biblioteca,
echo   en el boton del engranaje arriba a la derecha.)

if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

"%PY%" actualizar.py

echo.
pause
endlocal
