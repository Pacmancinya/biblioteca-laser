@echo off
chcp 65001 >nul
title Biblioteca Laser
REM ============================================================
REM  Biblioteca Laser - doble clic para abrir
REM  1) Busca Python (si no esta, lo instala solo)
REM  2) Prepara el entorno la primera vez
REM  3) Revisa los modelos y abre la biblioteca
REM ============================================================
setlocal
cd /d "%~dp0"

echo.
echo  ============================================================
echo    BIBLIOTECA LASER
echo  ============================================================
echo.

REM --- 1. Entorno propio (.venv) ---
if exist ".venv\Scripts\python.exe" goto venv_ok

echo  [1/3] Preparando por primera vez...
where py >nul 2>&1
if %errorlevel%==0 (
    py -3 -m venv .venv
    if exist ".venv\Scripts\python.exe" goto venv_ok
)
where python >nul 2>&1
if %errorlevel%==0 (
    python -m venv .venv
    if exist ".venv\Scripts\python.exe" goto venv_ok
)
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" -m venv .venv
    if exist ".venv\Scripts\python.exe" goto venv_ok
)

echo  [1/3] Este PC no tiene Python: lo instalo (una sola vez, 2-3 minutos)...
powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile '$env:TEMP\biblio-python.exe'"
if not exist "%TEMP%\biblio-python.exe" goto no_python
"%TEMP%\biblio-python.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0
if not exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" goto no_python
echo  [1/3] Python instalado.
"%LOCALAPPDATA%\Programs\Python\Python312\python.exe" -m venv .venv
if not exist ".venv\Scripts\python.exe" goto no_python

:venv_ok
set "PY=.venv\Scripts\python.exe"

REM --- 2. Dependencias (solo Pillow, para las miniaturas) ---
"%PY%" -c "import PIL" >nul 2>&1
if %errorlevel%==0 goto deps_ok
echo  [2/3] Instalando lo necesario (solo la primera vez)...
"%PY%" -m pip install --upgrade pip >nul 2>&1
"%PY%" -m pip install pillow
if errorlevel 1 (
    echo.
    echo  AVISO: no pude instalar Pillow. La biblioteca igual funciona,
    echo         pero las fotos se veran mas lento.
    echo.
)
:deps_ok

REM --- 3. Indice de modelos ---
if exist "biblioteca.json" goto indice_ok
echo  [3/3] Primera vez: voy a revisar tus modelos...
echo.
"%PY%" indexar.py
if errorlevel 1 goto error_indice
echo.
:indice_ok

REM --- Abrir ---
"%PY%" app.py

goto fin

:no_python
echo.
echo  ERROR: no pude instalar Python automaticamente.
echo         Instalalo a mano desde https://www.python.org/downloads/
echo         (MARCA la casilla "Add Python to PATH") y vuelve a abrir este archivo.
echo.
pause
goto fin

:error_indice
echo.
echo  ERROR: no pude leer la carpeta de modelos.
echo         Vuelve a abrir este archivo y elige bien la carpeta.
echo.
pause
goto fin

:fin
endlocal
