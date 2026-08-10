@echo off
chcp 65001 >nul
title Biblioteca Laser
REM ============================================================
REM  Biblioteca Laser - doble clic para abrir
REM  1) Busca Python de verdad (ignora el alias de Microsoft Store)
REM  2) Si no hay, lo instala solo
REM  3) Prepara el entorno y abre la biblioteca
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo  ============================================================
echo    BIBLIOTECA LASER
echo  ============================================================
echo.

if exist ".venv\Scripts\python.exe" goto venv_ok

echo  [1/3] Preparando por primera vez...
set "PYEXE="

REM --- 1) el lanzador "py" (la forma mas confiable en Windows) ---
py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do set "PYEXE=%%P"
)

REM --- 2) "python" del PATH, comprobando que NO sea el alias de la Store ---
if not defined PYEXE (
    python -c "import sys" >nul 2>&1
    if not errorlevel 1 (
        for /f "delims=" %%P in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "PYEXE=%%P"
    )
)

REM --- 3) instalaciones tipicas por usuario ---
if not defined PYEXE (
    for %%V in (313 312 311 310) do (
        if not defined PYEXE if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" (
            set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
        )
    )
)

REM --- 4) no hay Python: lo instalamos ---
if not defined PYEXE (
    echo  [1/3] Este PC no tiene Python. Lo instalo ahora ^(una sola vez, 2-3 minutos^).
    echo        No pide permisos de administrador. Espera...
    echo.
    set "INST=%TEMP%\biblioteca-python.exe"
    if exist "!INST!" del /q "!INST!"

    REM descarga con curl (viene en Windows 10/11); si no, con PowerShell
    where curl >nul 2>&1
    if not errorlevel 1 (
        curl -L -s -o "!INST!" "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"
    )
    if not exist "!INST!" (
        powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile \"%TEMP%\biblioteca-python.exe\"" >nul 2>&1
    )
    if not exist "!INST!" goto no_python

    echo        Instalando...
    "!INST!" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0
    del /q "!INST!" >nul 2>&1

    for %%V in (312 313) do (
        if not defined PYEXE if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" (
            set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
        )
    )
    if not defined PYEXE goto no_python
    echo  [1/3] Python instalado correctamente.
)

echo        Creando el entorno de la app...
"%PYEXE%" -m venv .venv
if not exist ".venv\Scripts\python.exe" goto error_venv

:venv_ok
set "PY=.venv\Scripts\python.exe"

REM --- 2. Dependencias (solo Pillow, para las miniaturas) ---
"%PY%" -c "import PIL" >nul 2>&1
if not errorlevel 1 goto deps_ok
echo  [2/3] Instalando lo necesario (solo la primera vez)...
"%PY%" -m pip install --upgrade pip >nul 2>&1
"%PY%" -m pip install pillow
if errorlevel 1 (
    echo.
    echo  AVISO: no pude instalar Pillow. La biblioteca igual funciona,
    echo         pero las fotos cargaran mas lento.
    echo.
)
:deps_ok

REM --- 3. Indice de modelos ---
if exist "biblioteca.json" goto indice_ok
echo  [3/3] Primera vez: elige la carpeta donde tienes tus modelos...
echo.
"%PY%" indexar.py
if errorlevel 1 goto error_indice
echo.
:indice_ok

"%PY%" app.py
goto fin

:no_python
echo.
echo  ============================================================
echo   NO PUDE INSTALAR PYTHON AUTOMATICAMENTE
echo  ============================================================
echo.
echo   Hazlo a mano (es rapido):
echo     1. Voy a abrirte la pagina de descarga.
echo     2. Descarga "Windows installer (64-bit)".
echo     3. AL INSTALARLO, MARCA LA CASILLA:
echo            [X] Add python.exe to PATH
echo     4. Cuando termine, vuelve a abrir este archivo.
echo.
pause
start "" "https://www.python.org/downloads/"
goto fin

:error_venv
echo.
echo  ERROR: no pude preparar el entorno de la app.
echo         Ejecuta SOLUCIONAR-PROBLEMAS.bat y manda una foto.
echo.
pause
goto fin

:error_indice
echo.
echo  No se eligio una carpeta de modelos.
echo  Vuelve a abrir este archivo y elige la carpeta donde estan.
echo.
pause
goto fin

:fin
endlocal
