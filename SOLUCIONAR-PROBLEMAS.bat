@echo off
chcp 65001 >nul
title Revision - Biblioteca Laser
setlocal
cd /d "%~dp0"

echo.
echo  ============================================================
echo    REVISION DE LA BIBLIOTECA
echo  ============================================================
echo.

echo  Carpeta de la app:
echo    %CD%
echo.

echo  Python del sistema:
where python 2>nul || echo    (no encontrado en el sistema)
echo.

echo  Entorno propio (.venv):
if exist ".venv\Scripts\python.exe" (
  echo    OK
  .venv\Scripts\python.exe --version
  .venv\Scripts\python.exe -c "import PIL; print('   Pillow OK', PIL.__version__)" 2>nul || echo    Pillow: NO instalado
) else (
  echo    NO existe. Abre "INICIAR Biblioteca.bat" para crearlo.
)
echo.

echo  Archivos de la app:
for %%F in (app.py db.py indexar.py ui.html) do (
  if exist "%%F" (echo    OK  %%F) else (echo    FALTA  %%F)
)
echo.

echo  Datos:
if exist "config.json" (echo    OK  config.json) else (echo    -   config.json  ^(se crea al elegir la carpeta^))
if exist "biblioteca.json" (echo    OK  biblioteca.json) else (echo    -   biblioteca.json  ^(se crea al indexar^))
if exist "biblioteca.db" (echo    OK  biblioteca.db  ^(favoritos, clientes, ventas^)) else (echo    -   biblioteca.db  ^(se crea al usar la app^))
echo.

echo  Carpeta de modelos configurada:
if exist "config.json" (type config.json) else (echo    todavia no se ha elegido)
echo.

echo  LightBurn:
if exist "C:\Program Files\LightBurn\LightBurn.exe" (echo    OK  C:\Program Files\LightBurn\LightBurn.exe) else (echo    no esta en la ruta habitual ^(se abrira con el programa por defecto^))
echo.

echo  ============================================================
echo   Saca una foto de esta ventana si necesitas ayuda.
echo  ============================================================
echo.
pause
endlocal
