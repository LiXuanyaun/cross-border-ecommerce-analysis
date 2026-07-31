@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\start_web.ps1" -Mode private -OpenBrowser
if errorlevel 1 (
  echo.
  echo CrossBorder startup failed. Review the error above, then press any key to close.
  pause >nul
)
