@echo off
chcp 65001 >nul
title EV Route Optimizer Launcher

REM Trailing slash kaldir (cd komutu icin)
set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

echo.
echo ========================================
echo    EV Route Optimizer - Launcher
echo ========================================
echo.

REM .venv kontrolu
if not exist "%PROJECT_DIR%\.venv\Scripts\activate.bat" (
    echo [HATA] .venv bulunamadi.
    echo.
    echo Once asagidakileri calistir:
    echo   python -m venv .venv
    echo   .venv\Scripts\activate
    echo   pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

REM frontend node_modules kontrolu
if not exist "%PROJECT_DIR%\frontend\node_modules" (
    echo [HATA] frontend\node_modules bulunamadi.
    echo.
    echo Once asagidakileri calistir:
    echo   cd frontend
    echo   npm install
    echo.
    pause
    exit /b 1
)

REM Backend varsa onu durdur (port 8000 cakismasini onler)
echo [1/3] 8000 portunu kontrol ediliyor...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING" 2^>nul') do (
    echo       PID %%a 8000'de calisiyor, durduruluyor...
    taskkill /PID %%a /F >nul 2>&1
)

REM Backend baslat
echo [2/3] Backend baslatiliyor (FastAPI, port 8000)...
start "EV Backend - FastAPI" cmd /k "cd /d "%PROJECT_DIR%" && set PYTHONIOENCODING=utf-8 && .venv\Scripts\activate && echo. && echo === Backend: http://127.0.0.1:8000 === && echo. && uvicorn app.api.main:app --host 127.0.0.1 --port 8000"

REM Backend warmup
timeout /t 5 /nobreak >nul

REM Frontend baslat
echo [3/3] Frontend baslatiliyor (Vite, port 5173)...
start "EV Frontend - Vite" cmd /k "cd /d "%PROJECT_DIR%\frontend" && echo. && echo === Frontend: http://localhost:5173 === && echo. && npm run dev"

REM Frontend warmup
timeout /t 6 /nobreak >nul

echo.
echo ========================================
echo    Sunucular calisir durumda
echo ========================================
echo    Backend:  http://127.0.0.1:8000
echo    Frontend: http://localhost:5173
echo ========================================
echo.
echo    Tarayici aciliyor...
start http://localhost:5173

echo.
echo    Sunuculari kapatmak icin acilan iki
echo    pencereyi de kapatin (veya Ctrl+C).
echo.
timeout /t 5 /nobreak >nul
exit
