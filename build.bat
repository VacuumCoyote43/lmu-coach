@echo off
rem Genera dist\LMU Coach\LMU Coach.exe y el instalador dist\LMU-Coach-Setup-x.y.z.exe
cd /d "%~dp0"
set PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
"%PY%" -m PyInstaller lmu_coach.spec --noconfirm || exit /b 1
rem build\ solo contiene archivos intermedios (su .exe no funciona suelto): se borra para evitar confusiones
rmdir /s /q build
rem Version leida de lmu_coach\version.py (linea __version__ = "x.y.z")
for /f "tokens=2 delims==" %%v in ('findstr /b "__version__" lmu_coach\version.py') do set VER=%%v
set VER=%VER:"=%
set VER=%VER: =%
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" /DAppVersion=%VER% installer.iss || exit /b 1
echo.
echo Listo: dist\LMU-Coach-Setup-*.exe
