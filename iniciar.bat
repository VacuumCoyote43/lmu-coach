@echo off
rem Abre LMU Coach (sesiones + botón de modo coach).
rem   iniciar.bat         -> app de escritorio
rem   iniciar.bat coach   -> solo el overlay del coach
rem   iniciar.bat demo    -> overlay con coche simulado, sin el juego
cd /d "%~dp0"
set PYW=%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe
if "%1"=="demo" (
    start "" "%PYW%" -m lmu_coach --demo
) else if "%1"=="coach" (
    start "" "%PYW%" -m lmu_coach
) else (
    start "" "%PYW%" -m lmu_coach.gui
)
