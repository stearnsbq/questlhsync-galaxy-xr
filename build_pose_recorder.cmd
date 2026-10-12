@echo off
setlocal
if "%~1"=="" (echo Usage: build_pose_recorder.cmd PATH_TO_QUESTLHSYNC & exit /b 2)
set "QLHS_SOURCE=%~f1"
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
for /f "usebackq delims=" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VS=%%i"
if not defined VS exit /b 1
call "%VS%\VC\Auxiliary\Build\vcvars64.bat" >nul || exit /b 1
cd /d "%~dp0"
if not exist build mkdir build
cl /nologo /EHsc /std:c++17 /MT /W4 /D_CRT_SECURE_NO_WARNINGS /I"%QLHS_SOURCE%\third_party\openvr\headers" /Fobuild\record_poses.obj src\record_poses.cpp /Fe:build\record_poses_v2.exe /link "%QLHS_SOURCE%\third_party\openvr\lib\win64\openvr_api.lib" || exit /b 1
copy /y "%QLHS_SOURCE%\third_party\openvr\bin\win64\openvr_api.dll" build\ >nul
