@echo off
setlocal
cd /d "%~dp0"
set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;%PATH%"
where uv >nul 2>nul
if errorlevel 1 (
  echo [PaperMind] Installing uv ...
  set "PSModulePath="
  "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
)
where uv >nul 2>nul
if errorlevel 1 (
  echo [PaperMind] uv installer failed, trying pip ...
  python -m pip install --user uv
  for /f "delims=" %%i in ('python -c "import sysconfig;print(sysconfig.get_path('scripts','nt_user'))"') do set "PATH=%%i;%PATH%"
)
where uv >nul 2>nul
if errorlevel 1 (
  echo [PaperMind] Could not install uv. Please install it from https://docs.astral.sh/uv/ and run again.
  exit /b 1
)
uv sync --frozen --no-dev
if errorlevel 1 exit /b 1
if "%PAPERMIND_NO_OPEN%"=="1" (
  uv run --no-dev papermind serve %*
) else (
  uv run --no-dev papermind serve --open %*
)
