@echo off
setlocal enableextensions

rem Stable Windows launcher. The official installation also places an
rem extensionless POSIX script on PATH, which PowerShell selects before a
rem usable Windows command on this machine.
set "HEROKU_CLI=%LOCALAPPDATA%\heroku\client\11.8.1-40e79ad\bin\heroku.cmd"

if not exist "%HEROKU_CLI%" (
  echo Heroku CLI executable not found: "%HEROKU_CLI%" 1>&2
  exit /b 1
)

call "%HEROKU_CLI%" %*
