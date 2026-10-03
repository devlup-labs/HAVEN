@echo off
setlocal
cd /d "%~dp0"

set NUM_NODES=5
if not "%~1"=="" set NUM_NODES=%~1

echo ==================================================
echo      HAVEN Multi-Node Test Environment (Windows)
echo      Simulating %NUM_NODES% Virtual Nodes
echo ==================================================
echo.

:: 1. Generate Renode configuration (Cross-platform socket mode)
echo [1/3] Generating Renode script for %NUM_NODES% nodes...
python renode\generate_network.py %NUM_NODES% socket
echo.

:: 2. Start the Wireless Mesh Router in a separate command window
echo [2/3] Launching Wireless Mesh Router (Ports 4001..400%NUM_NODES%)...
start "HAVEN Wireless Mesh Router" cmd /k "python bridge\tcp_test_server.py %NUM_NODES% direct"
echo.

:: 3. Start Renode
echo [3/3] Launching Renode with %NUM_NODES% virtual Cortex-M3 nodes...
where renode >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    start "Renode" renode renode\haven.resc
) else (
    if exist "C:\Program Files\Renode\bin\Renode.exe" (
        start "Renode" "C:\Program Files\Renode\bin\Renode.exe" renode\haven.resc
    ) else if exist "%LOCALAPPDATA%\Programs\Renode\bin\Renode.exe" (
        start "Renode" "%LOCALAPPDATA%\Programs\Renode\bin\Renode.exe" renode\haven.resc
    ) else (
        echo [WARNING] Could not find 'renode' in PATH or default locations.
        echo Please ensure Renode is installed or launch it manually with:
        echo    renode renode\haven.resc
    )
)

echo.
echo ==================================================
echo HAVEN is now running on Windows!
echo - Each node's UART is attached to TCP port 4001..400%NUM_NODES%
echo - The Wireless Mesh Router connects to them and relays packets.
echo ==================================================
echo.
pause
