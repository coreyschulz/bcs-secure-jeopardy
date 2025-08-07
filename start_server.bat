@echo off
REM BCS Secure Jeopardy Server Startup Script for Windows
REM Usage: start_server.bat [--local]
REM        --local: Start server for local network play only (no ngrok)

setlocal enabledelayedexpansion

set LOCAL_ONLY=false

REM Parse command line arguments
if "%1"=="--local" set LOCAL_ONLY=true

echo Starting BCS Secure Jeopardy Server...

REM Check if ngrok is installed (only if not in local mode)
if "%LOCAL_ONLY%"=="false" (
    where ngrok >nul 2>nul
    if errorlevel 1 (
        echo ERROR: ngrok is not installed. Please install it first:
        echo    Download from https://ngrok.com/download
        echo    Add ngrok.exe to your PATH
        echo.
        echo Or run in local mode with: start_server.bat --local
        exit /b 1
    )
)

REM Check if virtual environment exists
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat

REM Install dependencies
echo Installing dependencies...
pip install -r requirements.txt

REM Check server syntax
echo Validating server code...
python -m py_compile server.py
if errorlevel 1 (
    echo ERROR: Server code validation failed
    exit /b 1
)

if "%LOCAL_ONLY%"=="false" (
    REM Start ngrok in the background
    echo Starting ngrok tunnel...
    start /b ngrok http 9999 --log-level=info --log=stdout > ngrok.log 2>&1

    REM Wait for ngrok to start
    echo Waiting for ngrok to initialize...
    timeout /t 3 /nobreak >nul

    REM Get the ngrok URL using curl (Windows 10+ has curl)
    for /f "tokens=*" %%i in ('curl -s http://localhost:4040/api/tunnels ^| findstr /r "https://.*\.ngrok.*\.app"') do (
        set NGROK_LINE=%%i
    )

    REM Extract the URL from the JSON response
    for /f "tokens=2 delims=:" %%a in ("!NGROK_LINE!") do (
        set NGROK_URL=%%a
        set NGROK_URL=!NGROK_URL:"=!
        set NGROK_URL=https:!NGROK_URL!
    )

    if "!NGROK_URL!"=="" (
        echo ERROR: Failed to get ngrok URL. Please check ngrok.log for errors.
        exit /b 1
    )

    REM Extract just the hostname
    for /f "tokens=2 delims=/" %%a in ("!NGROK_URL!") do set NGROK_HOST=%%a

    REM Extract the game ID from the hostname
    for /f "tokens=1 delims=." %%a in ("!NGROK_HOST!") do set GAME_ID=%%a
)

REM Generate host password
for /f %%i in ('python -c "import uuid; print(str(uuid.uuid4()))"') do set HOST_PASSWORD=%%i

REM Start the Python server with password
echo Starting WebSocket server on port 9999...
start /b python server.py

REM Display connection information
echo.
echo Server is running!

if "%LOCAL_ONLY%"=="false" (
    REM Generate the join links
    set JOIN_LINK=https://bcsjeopardy.com/?code=!GAME_ID!
    set HOST_LINK=https://bcsjeopardy.com/host?code=!GAME_ID!
    
    echo ==================================================
    echo GAME ID: !GAME_ID!
    echo ==================================================
    echo.
    echo Players can join at: !JOIN_LINK!
    echo Host panel: !HOST_LINK!
    echo.
    echo Host password: !HOST_PASSWORD!
    echo.
    echo WebSocket URL: !NGROK_HOST!
    echo.
) else (
    echo ==================================================
    echo LOCAL NETWORK MODE
    echo ==================================================
    echo.
    echo Players on your network can connect using:
    echo    localhost:9999 (on this computer)
    REM Get local IP address
    for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4 Address"') do (
        set LOCAL_IP=%%a
        set LOCAL_IP=!LOCAL_IP: =!
        echo    !LOCAL_IP!:9999 (from other devices)
        goto :found_ip
    )
    :found_ip
    echo.
    echo Host password: !HOST_PASSWORD!
    echo.
)

echo Local access:
echo    Client: http://localhost:8000/jeopardy.html
echo    Host: http://localhost:8000/jeopardy_host.html
echo.
echo Server logs: jeopardy_server.log
if "%LOCAL_ONLY%"=="false" echo Ngrok logs: ngrok.log
echo.
echo Press Ctrl+C to stop the server
echo.

REM Keep the script running
:loop
timeout /t 1 /nobreak >nul
goto loop