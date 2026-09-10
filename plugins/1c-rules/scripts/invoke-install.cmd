@echo off
setlocal
set "SCRIPT=%~dp0invoke-install.ps1"
set "CMD=%~1"
set "TOOL=%~2"
if "%CMD%"=="" set "CMD=ensure"
if "%TOOL%"=="" set "TOOL=auto"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" -Action %CMD% -Tool %TOOL%
exit /b %ERRORLEVEL%
