param(
    [Parameter(Mandatory = $true)]
    [string]$Dest
)

$shell = New-Object -ComObject WScript.Shell
$programs = [Environment]::GetFolderPath("Programs")
$exe = Join-Path $Dest "JarvisAI.exe"

$app = $shell.CreateShortcut((Join-Path $programs "JarvisAI.lnk"))
$app.TargetPath = $exe
$app.WorkingDirectory = $Dest
$app.Description = "JarvisAI"
$app.Save()

$remove = $shell.CreateShortcut((Join-Path $programs "Uninstall JarvisAI.lnk"))
$remove.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$remove.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $Dest 'uninstall.ps1')`""
$remove.WorkingDirectory = $Dest
$remove.Description = "Uninstall JarvisAI"
$remove.Save()
