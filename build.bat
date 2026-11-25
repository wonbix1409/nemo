@echo off
cd /d "%~dp0"
if not exist .venv (
  echo [Nemo] Creating virtual environment...
  py -3.12 -m venv .venv 2>nul || python -m venv .venv
  if errorlevel 1 ( echo [Nemo] Python 3.12 not found. & pause & exit /b 1 )
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller

echo [Nemo] Running core tests via selftest...
python app.py --selftest
if errorlevel 1 ( echo [Nemo] Selftest failed, see output above. & pause & exit /b 1 )

echo [Nemo] Building Nemo.exe ...
pyinstaller --noconfirm --windowed --name Nemo ^
  --collect-all natasha --collect-all slovnet --collect-all navec ^
  --collect-all razdel --collect-all yargy ^
  --collect-all pymorphy2 --collect-all pymorphy2_dicts_ru --copy-metadata pymorphy2_dicts_ru ^
  --hidden-import docx --icon assets\nemo.ico --add-data "assets;assets" ^
  app.py
if errorlevel 1 ( echo [Nemo] Build failed. & pause & exit /b 1 )

echo.
echo [Nemo] Done: dist\Nemo\Nemo.exe  (copy the whole dist\Nemo folder)
pause
