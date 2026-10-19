@echo off
setlocal
cd /d "%~dp0"
where uv >nul 2>nul
if errorlevel 1 (
  echo [PaperMind] Installing uv ...
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  set "PATH=%USERPROFILE%\.local\bin;%PATH%"
)
uv sync --frozen --no-dev
if errorlevel 1 exit /b 1
if "%PAPERMIND_NO_OPEN%"=="1" (
  uv run --no-dev papermind serve %*
) else (
  uv run --no-dev papermind serve --open %*
)
