@echo off
rem Genera dist\LMU Coach\LMU Coach.exe y el instalador dist\LMU-Coach-Setup-x.y.z.exe
cd /d "%~dp0"
set PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
"%PY%" -m PyInstaller lmu_coach.spec --noconfirm || exit /b 1
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer.iss || exit /b 1
echo.
echo Listo: dist\LMU-Coach-Setup-*.exe
