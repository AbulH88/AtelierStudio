@echo off
REM ============================================================
REM  Atelier Studio launcher
REM  Double-click this to start the web app and open it.
REM  ComfyUI itself is started from the "Start ComfyUI" button
REM  on the page (or run Windows_Run_GPU.bat in ComfyUI_V82).
REM ============================================================

cd /d "%~dp0webapp"

echo Starting Atelier web app...
start "Atelier Web App" cmd /c "python app.py"

REM give Flask a moment to bind the port
timeout /t 3 >nul

echo Opening the studio in your browser...
start "" "http://127.0.0.1:8000"

echo.
echo  Atelier Studio is running.
echo  Page:  http://127.0.0.1:8000
echo  - Click "Start ComfyUI" on the page to power up the 5090 engine.
echo  - Close this window only when you are done (it keeps the app alive).
echo.
pause
