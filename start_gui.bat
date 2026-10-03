@echo off
setlocal
cd /d "%~dp0"

set NODES=8
if not "%~1"=="" set NODES=%~1

echo ==================================================
echo   Starting HAVEN Network GUI Simulator (%NODES% Nodes)
echo ==================================================
echo.
python sim\haven_gui.py %NODES%
pause
