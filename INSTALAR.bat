@echo off
chcp 65001 >nul
title Instalar Biblioteca Laser
REM ============================================================
REM  Se ejecuta UNA SOLA VEZ.
REM  Deja un acceso directo "Biblioteca Laser" en el Escritorio.
REM  Despues de esto, el papa nunca mas ve una ventana negra.
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo  ============================================================
echo    BIBLIOTECA LASER  -  instalacion
echo  ============================================================
echo.
echo    Esto se hace una sola vez. Demora unos minutos.
echo.

REM ------------------------------------------------ 1) buscar Python
set "PYEXE="
if exist ".venv\Scripts\pythonw.exe" goto venv_listo

echo  [1/4] Buscando Python...

py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do set "PYEXE=%%P"
)
if not defined PYEXE (
    python -c "import sys" >nul 2>&1
    if not errorlevel 1 (
        for /f "delims=" %%P in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "PYEXE=%%P"
    )
)
if not defined PYEXE (
    for %%V in (313 312 311 310) do (
        if not defined PYEXE if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" (
            set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
        )
    )
)

if not defined PYEXE (
    echo  [1/4] Este PC no tiene Python. Lo instalo ahora. Espera...
    echo.
    set "INST=%TEMP%\biblioteca-python.exe"
    if exist "!INST!" del /q "!INST!"
    where curl >nul 2>&1
    if not errorlevel 1 (
        curl -L -s -o "!INST!" "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"
    )
    if not exist "!INST!" (
        powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile \"%TEMP%\biblioteca-python.exe\"" >nul 2>&1
    )
    if not exist "!INST!" goto no_python
    echo        Instalando Python...
    "!INST!" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0
    del /q "!INST!" >nul 2>&1
    for %%V in (312 313) do (
        if not defined PYEXE if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" (
            set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
        )
    )
    if not defined PYEXE goto no_python
)

echo  [2/4] Preparando el programa...
"%PYEXE%" -m venv .venv
if not exist ".venv\Scripts\pythonw.exe" goto error_venv

:venv_listo
set "PY=.venv\Scripts\python.exe"
set "PYW=.venv\Scripts\pythonw.exe"

REM ------------------------------------------------ 2) las librerias
echo  [3/4] Instalando lo que necesita (solo la primera vez)...
"%PY%" -m pip install --upgrade pip >nul 2>&1
"%PY%" -m pip install --quiet pillow pywebview
if errorlevel 1 (
    echo.
    echo   AVISO: algo no se pudo instalar. Reviso...
    "%PY%" -m pip install pillow pywebview
)

REM comprobar que quedo listo para abrir en ventana propia
"%PY%" -c "import webview" >nul 2>&1
if errorlevel 1 (
    echo.
    echo   AVISO: no pude dejar la ventana propia. La biblioteca va a
    echo          abrirse en el navegador, que igual funciona bien.
    echo.
)

REM ------------------------------------------------ 3) el acceso directo
echo  [4/4] Creando el acceso directo en el Escritorio...
"%PY%" crear_acceso.py
if errorlevel 1 (
    echo   AVISO: no pude crear el acceso directo automaticamente.
    echo          Igual puedes abrir la biblioteca con este mismo archivo.
)

echo.
echo  ============================================================
echo    LISTO
echo  ============================================================
echo.
echo    Ya tienes en tu Escritorio el icono:
echo.
echo         Biblioteca Laser
echo.
echo    De ahora en adelante abrela con ese icono.
echo    Se abre en su propia ventana, sin esta ventana negra.
echo.
echo    Voy a abrirla ahora para que la veas.
echo.
ping -n 4 127.0.0.1 >nul 2>&1
start "" "%PYW%" lanzador.py
echo    (ya puedes cerrar esta ventana)
echo.
pause
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
echo   ERROR: no pude preparar el programa.
echo   Sacale una foto a esta ventana y mandasela a Ruperto.
echo.
pause

:fin
endlocal
