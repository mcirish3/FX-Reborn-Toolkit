@echo off
rem Builds the self-test: AVX2/BMI2 kernels (/arch:AVX2) + scalar reference and driver (/arch:AVX).
rem Run from an x64 VS Developer Command Prompt, or set VCVARS to vcvars64.bat.
if defined VCVARS call "%VCVARS%" >nul
cd /d "%~dp0"
if not exist bin mkdir bin
cl /nologo /O2 /MT /arch:AVX2 /c kernels.cpp /Fo:bin\kernels.obj || exit /b 1
cl /nologo /O2 /MT /arch:AVX /c reference.cpp /Fo:bin\reference.obj || exit /b 1
cl /nologo /O2 /MT /arch:AVX /c main.cpp /Fo:bin\main.obj || exit /b 1
link /nologo bin\main.obj bin\kernels.obj bin\reference.obj /out:bin\selftest.exe || exit /b 1
rem DLL variant: the AVX2 code lives in kernels.dll, loaded by selftest_dll.exe
cl /nologo /O2 /MT /arch:AVX2 /DKERNELS_DLL /c kernels.cpp /Fo:bin\kernels_dll.obj || exit /b 1
link /nologo /DLL bin\kernels_dll.obj /out:bin\kernels.dll /implib:bin\kernels.lib || exit /b 1
cl /nologo /O2 /MT /arch:AVX /DKERNELS_IMPORT /c main.cpp /Fo:bin\main_dll.obj || exit /b 1
link /nologo bin\main_dll.obj bin\reference.obj bin\kernels.lib /out:bin\selftest_dll.exe || exit /b 1
