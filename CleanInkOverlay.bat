@echo off
rem CleanInkOverlay launcher: starts the web UI at http://127.0.0.1:8000 (recorder on/off from the page).
rem Keep this file ASCII-only: cmd mis-parses non-ASCII batch files after chcp 65001.
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
python -m uv --version >nul 2>&1 || (
  echo uv is missing, installing it...
  python -m pip install --user uv || (echo failed to install uv & pause & exit /b 1)
)
rem uv sync checks .venv and Python 3.13 and (re)creates them when missing or broken
python -m uv sync || (echo uv sync failed & pause & exit /b 1)
if not exist "web\dist\index.html" (
  echo building the frontend...
  pushd web && call npm install --no-audit --no-fund && call npm run build && popd
)
start "" cmd /c "timeout /t 3 >nul & start "" http://127.0.0.1:8000"
python -m uv run python -m app.backend %*
pause
