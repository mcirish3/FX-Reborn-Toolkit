@echo off
rem Compiles fxcompat.dll. Run from an x64 VS Developer Command Prompt, or set VCVARS to vcvars64.bat.
if defined VCVARS call "%VCVARS%" >nul
cd /d "%~dp0"
cl /nologo /W4 /O2 /MT /GS /guard:cf /LD fxcompat_static.cpp /link /out:fxcompat.dll /implib:fxcompat.lib /incremental:no
