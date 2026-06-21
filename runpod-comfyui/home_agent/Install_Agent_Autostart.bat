@echo off
REM Run once (as your user) to make the home agent start automatically at logon,
REM so the studio site can always start/stop ComfyUI remotely.

schtasks /Create /TN "AtelierHomeAgent" /TR "\"%~dp0Start_Agent.bat\"" /SC ONLOGON /RL HIGHEST /F
echo.
echo Installed. The home agent will launch at every logon.
echo To start it now without rebooting, just double-click Start_Agent.bat.
echo (To remove later: schtasks /Delete /TN "AtelierHomeAgent" /F)
pause
