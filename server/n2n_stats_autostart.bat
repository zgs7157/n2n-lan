@echo off
rem n2n visit stats - autostart entry (launched by registry Run key)
netstat -ano | findstr /c:"LISTENING" | findstr /c:":8088" >nul
if %errorlevel%==0 exit /b
cd /d "%~dp0"
start "" /b visit_stats.exe
