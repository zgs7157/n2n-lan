@echo off
rem n2n supernode launcher for Windows Server
rem Usage: start_supernode.bat [port] [federation-name]
rem   port: UDP port, default 7654
rem   federation-name: optional, recommended (supernode side only, clients need no change)
rem   e.g.  start_supernode.bat 7654 myroom
cd /d "%~dp0"
set PORT=7654
if not "%1"=="" set PORT=%1
set FED=
if not "%2"=="" set FED=-F %2
echo Starting n2n supernode on UDP port %PORT% %FED% ...
netsh advfirewall firewall add rule name="n2n supernode" dir=in action=allow protocol=UDP localport=%PORT% >nul 2>&1
supernode.exe -p %PORT% -f %FED%
pause
