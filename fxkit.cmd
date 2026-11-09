@echo off
rem FX Reborn Toolkit command line. Usage: fxkit scan^|gate^|build^|package ...  (fxkit -h for help)
setlocal
set "FXK_HOME=%~dp0"
if not exist "%FXK_HOME%python\python.exe" goto system
"%FXK_HOME%python\python.exe" "%FXK_HOME%fxkit.py" %*
exit /b %ERRORLEVEL%
:system
py -3.13 "%FXK_HOME%fxkit.py" %*
exit /b %ERRORLEVEL%
