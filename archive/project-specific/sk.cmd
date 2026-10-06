@echo off
rem sk.cmd - call the DSH <-> SketchUp bridge client (.cmd version, immune to
rem PowerShell execution policy). ASCII only on purpose: cmd.exe reads .cmd files
rem in the OEM codepage, so non-ASCII comments here would print garbage.
rem
rem Usage: sk.cmd ping | sk.cmd info | sk.cmd ruby "puts Sketchup.version"
setlocal
set PY=C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe
set CLI=%~dp0sk_client.py
set PYTHONIOENCODING=utf-8
if "%~1"=="" (
  "%PY%" "%CLI%" shell
) else (
  "%PY%" "%CLI%" %*
)
exit /b %ERRORLEVEL%
