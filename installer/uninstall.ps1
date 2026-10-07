$ErrorActionPreference = "SilentlyContinue"
Get-Process -Name JarvisAI | Stop-Process -Force
Start-Sleep -Milliseconds 400
Remove-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "JarvisAI"
$programs = [Environment]::GetFolderPath("Programs")
Remove-Item (Join-Path $programs "JarvisAI.lnk") -Force
Remove-Item (Join-Path $programs "Uninstall JarvisAI.lnk") -Force
$dest = Join-Path $env:LOCALAPPDATA "JarvisAI"
Start-Process -FilePath "powershell.exe" -WindowStyle Hidden -ArgumentList @(
    "-NoProfile",
    "-Command",
    "Start-Sleep -Seconds 2; Remove-Item -LiteralPath '$dest' -Recurse -Force"
)
