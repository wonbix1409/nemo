@echo off
cd /d "%~dp0"
if not exist .venv (
  echo [Nemo] Creating virtual environment...
  py -3.12 -m venv .venv 2>nul || python -m venv .venv
  if errorlevel 1 ( echo [Nemo] Python 3.12 not found. Install it from python.org ^(tick "Add to PATH"^). & pause & exit /b 1 )
  call .venv\Scripts\activate.bat
  python -m pip install --upgrade pip
  pip install -r requirements.txt
) else (
  call .venv\Scripts\activate.bat
)
python app.py
if errorlevel 1 pause
