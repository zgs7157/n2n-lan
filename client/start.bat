@echo off
rem N2N Room Manager launcher (Windows)
cd /d "%~dp0"
if exist n2n_room_manager.exe (
    start "" n2n_room_manager.exe
    exit /b 0
)
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw n2n_room_manager.py
) else (
    start "" python n2n_room_manager.py
)
