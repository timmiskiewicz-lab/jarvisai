@echo off
setlocal EnableExtensions
set "DEST=%LOCALAPPDATA%\JarvisAI"
echo Installing JarvisAI...
taskkill /F /IM JarvisAI.exe >nul 2>&1
if not exist "%DEST%" mkdir "%DEST%"
if exist "%SystemRoot%\Sysnative\tar.exe" (
  "%SystemRoot%\Sysnative\tar.exe" -xf "%~dp0payload.zip" -C "%DEST%"
) else (
  tar -xf "%~dp0payload.zip" -C "%DEST%"
)
if errorlevel 1 (
  echo Could not unpack JarvisAI.
  pause
  exit /b 1
)
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v JarvisAI /t REG_SZ /d "\"%DEST%\JarvisAI.exe\"" /f >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0shortcut.ps1" -Dest "%DEST%"
start "" "%DEST%\JarvisAI.exe"
exit /b 0
