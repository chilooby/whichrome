@echo off
setlocal
rem Whichrome launcher for Windows. Plugin installs put bin/ on the Bash tool's PATH.
set "HERE=%~dp0"
where python >nul 2>&1 && (python "%HERE%whichrome.py" %* & exit /b %errorlevel%)
where py >nul 2>&1 && (py "%HERE%whichrome.py" %* & exit /b %errorlevel%)
echo whichrome: needs Python 3.9+ on PATH. 1>&2
exit /b 1
