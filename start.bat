@echo off
REM ============================================================
REM LORIS - Doppio Clic per Avviare (Windows Launcher)
REM ============================================================
cd /d "%~dp0"

echo ============================================================
echo   🐾 LORIS - Local Overview of Resources, Investments ^& Spending
echo ============================================================

where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERRORE] Python non e installato su questo computer.
    echo Per favore scarica Python da: https://www.python.org/downloads/
    echo Assicurati di spuntare "Add Python to PATH" durante l'installazione!
    pause
    exit /b 1
)

if not exist .venv (
    echo [PRIMO AVVIO] Configurazione ambiente in corso...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    echo [OK] Configurazione completata!
) else (
    call .venv\Scripts\activate.bat
)

set PYTHONPATH=%cd%\src;%PYTHONPATH%
echo Avvio dashboard LORIS nel browser...
streamlit run src\app_streamlit.py
pause
