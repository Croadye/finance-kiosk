@echo off
setlocal
start "MoneyKioskServer" /MIN cmd /c "call venv\Scripts\activate.bat && uvicorn app.main:app --host 0.0.0.0 --port 8000"
timeout /t 2 /nobreak >nul
start "" "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --kiosk http://localhost:8000 --edge-kiosk-type=fullscreen
