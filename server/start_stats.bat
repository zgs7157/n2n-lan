@echo off
rem n2n visit stats launcher (Windows)
rem Double-click to run the stats service in the background (no console window).
cd /d "%~dp0"

if exist visit_stats.exe (
  echo [n2n website visit stats]
  echo First run creates stats_config.json next to this file.
  echo You can edit admin_key / port there and restart.
  echo.
  start "" /b visit_stats.exe
  echo Stats service started in background. Default port 8088.
  echo Admin page: http://YOUR_PUBLIC_IP:8088/admin?key=n2n2026
  echo Stop it: Task Manager - end process "visit_stats.exe"
) else (
  echo visit_stats.exe not found. Put this file together with visit_stats.exe.
)
echo.
pause
