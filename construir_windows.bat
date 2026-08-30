@echo off
REM ============================================================================
REM  construir_windows.bat
REM  Genera EL INSTALADOR de Windows (un unico Setup.exe) en dos pasos:
REM    1) empaqueta el programa a un ejecutable con PyInstaller
REM    2) lo envuelve en un instalador con Inno Setup
REM
REM  Requisitos (una sola vez):
REM    - Python instalado y en el PATH
REM    - Inno Setup 6 instalado:  https://jrsoftware.org/isdl.php
REM
REM  Uso: doble clic en este fichero, o ejecutarlo en una consola dentro de la
REM  carpeta del programa. El instalador queda en la carpeta Output\.
REM ============================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo [1/3] Instalando PyInstaller (si falta)...
python -m pip install pyinstaller || goto :error

echo.
echo [2/3] Empaquetando el programa a un ejecutable...
python empaquetar.py || goto :error

REM --- leer la version desde version.py (para el nombre del instalador) ---
set "VER=0.0.0"
for /f "tokens=2 delims== " %%v in ('findstr /r "__version__" version.py') do set "VER=%%~v"

echo.
echo [3/3] Creando el instalador Setup.exe (version %VER%)...
REM ISCC es el compilador de Inno Setup. Si no esta en esta ruta, ajustala.
set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
  echo No se encontro Inno Setup ^(ISCC.exe^). Instalalo desde https://jrsoftware.org/isdl.php
  goto :error
)
"%ISCC%" /DMyAppVersion=%VER% instalador_windows.iss || goto :error

echo.
echo ============================================================================
echo  LISTO. El instalador esta en:  Output\GestorParcelas-Setup-%VER%.exe
echo  Ese unico fichero es el que puedes enviar por correo o pen-drive.
echo ============================================================================
pause
goto :eof

:error
echo.
echo Hubo un error. Revisa los mensajes de arriba.
pause
exit /b 1
