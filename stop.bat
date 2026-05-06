@echo off
chcp 65001 >nul
title EV Route Optimizer - Stop

echo.
echo Backend (8000) ve Frontend (5173) durduruluyor...
echo.

REM 8000 portu
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING" 2^>nul') do (
    echo   Backend PID %%a durduruluyor...
    taskkill /PID %%a /F >nul 2>&1
)

REM 5173 portu
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173" ^| findstr "LISTENING" 2^>nul') do (
    echo   Frontend PID %%a durduruluyor...
    taskkill /PID %%a /F >nul 2>&1
)

echo.
echo Tamam.
timeout /t 2 /nobreak >nul
exit
