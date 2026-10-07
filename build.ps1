$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
$pyinstaller = Join-Path $root ".venv\Scripts\pyinstaller.exe"
if (-not (Test-Path $python)) {
    python -m venv (Join-Path $root ".venv")
}
& $python -m pip install -r (Join-Path $root "requirements.txt")
& $python (Join-Path $root "tools\make_icon.py")

$dist = Join-Path $env:TEMP "jarvisai-dist"
$work = Join-Path $env:TEMP "jarvisai-work"
$spec = Join-Path $env:TEMP "jarvisai-spec"
foreach ($path in @($dist, $work, $spec)) {
    if (Test-Path $path) { Remove-Item $path -Recurse -Force }
}

& $pyinstaller `
    --noconfirm `
    --clean `
    --windowed `
    --name JarvisAI `
    --icon (Join-Path $root "assets\icon.ico") `
    --distpath $dist `
    --workpath $work `
    --specpath $spec `
    --add-data "$root\jarvisai\hud;jarvisai\hud" `
    --add-data "$root\assets\wake;assets\wake" `
    --add-data "$root\assets\wake\melspectrogram.onnx;openwakeword\resources\models" `
    --add-data "$root\assets\wake\embedding_model.onnx;openwakeword\resources\models" `
    --add-data "$root\assets\wake\hey_jarvis_v0.1.onnx;openwakeword\resources\models" `
    --collect-all openwakeword `
    --collect-all webview `
    --collect-all edge_tts `
    --collect-all _sounddevice_data `
    (Join-Path $root "jarvisai\__main__.py")
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

$app = Join-Path $dist "JarvisAI"
Copy-Item (Join-Path $root "installer\uninstall.ps1") (Join-Path $app "uninstall.ps1") -Force

$payload = Join-Path $env:TEMP "jarvisai-payload"
if (Test-Path $payload) { Remove-Item $payload -Recurse -Force }
New-Item -ItemType Directory -Path $payload | Out-Null
$zip = Join-Path $payload "payload.zip"
tar.exe -a -cf $zip -C $app .

$outDir = Join-Path $root "dist"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$setup = Join-Path $outDir "JarvisAI-Setup.exe"
if (Test-Path $setup) { Remove-Item $setup -Force }
$setupWork = Join-Path $env:TEMP "jarvisai-setup-work"
$setupSpec = Join-Path $env:TEMP "jarvisai-setup-spec"
foreach ($path in @($setupWork, $setupSpec)) {
    if (Test-Path $path) { Remove-Item $path -Recurse -Force }
}

& $pyinstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name JarvisAI-Setup `
    --icon (Join-Path $root "assets\icon.ico") `
    --distpath $outDir `
    --workpath $setupWork `
    --specpath $setupSpec `
    --add-data "$zip;." `
    (Join-Path $root "installer\setup_app.py")
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $setup)) {
    throw "Installer was not created."
}
Write-Output "Installer: $setup"
