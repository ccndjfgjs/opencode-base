@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_opencode_proxy.ps1" %*
if errorlevel 1 pause
endlocal
