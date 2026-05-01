@echo off
echo ============================================================
echo   AgentTrace DevTools
echo   Backend:  http://127.0.0.1:8765
echo   Frontend: http://localhost:5173
echo ============================================================
echo.

:: Start Python backend in a new window
start "AgentTrace Backend" cmd /c "cd /d %~dp0 && python server.py --port 8765"

:: Wait for backend
timeout /t 2 /nobreak >nul

:: Start Vite dev server
echo Starting Vite dev server...
call npm run dev
