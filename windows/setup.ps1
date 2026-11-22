# ORDELVA-Automation – one-time setup on Windows 10/11
# Run from the project folder:   powershell -ExecutionPolicy Bypass -File windows\setup.ps1
# It asks before each install. Nothing paid, no account needed. Re-running is safe.
param([switch]$Yes, [switch]$SkipOllama)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
function Ask($q) { if ($Yes) { return $true }; return ((Read-Host "$q [Y/n]") -notmatch '^(n|no)$') }
function RefreshPath { $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User") }
function Has($c) { [bool](Get-Command $c -ErrorAction SilentlyContinue) }

Write-Host "`n== 1/7 System check ==" -ForegroundColor Yellow
& "$PSScriptRoot\check_system.ps1" | Out-Null
$rep = Get-Content system_report.json -Raw | ConvertFrom-Json
Write-Host "Windows: $($rep.windows)`nCPU: $($rep.cpu)`nRAM: $($rep.ram_gb) GB  Free disk: $($rep.disk_free_gb) GB"
Write-Host "GPU(s): $(($rep.gpus | ForEach-Object { $_.name }) -join ', ')"
if ($rep.nvidia) { Write-Host "NVIDIA: $($rep.nvidia.name) $($rep.nvidia.vram_gb) GB, CUDA $($rep.nvidia.cuda)" } else { Write-Host "NVIDIA CUDA: not available (CPU mode)" }

Write-Host "`n== 2/7 Required tools ==" -ForegroundColor Yellow
if (-not (Has winget)) { throw "winget not found. Install 'App Installer' from the Microsoft Store, then re-run." }
$py = $null
foreach ($v in "3.12","3.11") { try { & py "-$v" -c "import sys" 2>$null; if ($LASTEXITCODE -eq 0) { $py = $v; break } } catch {} }
if (-not $py) {
    if (Ask "Install Python 3.12 (python.org build via winget)?") {
        winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements; RefreshPath; $py = "3.12"
    } else { throw "Python 3.11/3.12 is required." }
}
if (-not (Has ffmpeg)) {
    if (Ask "Install FFmpeg (Gyan.FFmpeg via winget)?") { winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements; RefreshPath }
    if (-not (Has ffmpeg)) { Write-Warning "Open a NEW PowerShell window after setup so ffmpeg is on PATH." }
}

Write-Host "`n== 3/7 Python environment (.venv) ==" -ForegroundColor Yellow
if (-not (Test-Path .venv\Scripts\python.exe)) { & py "-$py" -m venv .venv }
& .venv\Scripts\python.exe -m pip install --upgrade pip
& .venv\Scripts\python.exe -m pip install -r requirements.txt

Write-Host "`n== 4/7 Narration model (Kokoro-82M, Apache-2.0, ~350 MB) ==" -ForegroundColor Yellow
New-Item -ItemType Directory -Force models | Out-Null
$files = @{
  "kokoro-v1.0.onnx" = "7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5"
  "voices-v1.0.bin"  = "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d" }
foreach ($f in $files.Keys) {
  $dst = "models\$f"
  if (-not (Test-Path $dst) -or (Get-FileHash $dst -Algorithm SHA256).Hash.ToLower() -ne $files[$f]) {
    Write-Host "Downloading $f ..."
    Invoke-WebRequest -UseBasicParsing "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/$f" -OutFile $dst
  }
  if ((Get-FileHash $dst -Algorithm SHA256).Hash.ToLower() -ne $files[$f]) { throw "Checksum mismatch for $f – do not use this file; delete it and re-run." }
}
Write-Host "Model checksums verified."

Write-Host "`n== 5/7 Local LLM (Ollama, optional) ==" -ForegroundColor Yellow
$model = $rep.recommendation.ollama_model
$chosen = ""
if (-not $SkipOllama -and $model) {
  if (-not (Has ollama) -and (Ask "Install Ollama (free, local LLM runtime) for automatic script drafts?")) {
      winget install -e --id Ollama.Ollama --accept-package-agreements --accept-source-agreements; RefreshPath }
  if (Has ollama) {
      Write-Host "Pulling $model (one-time download, 2–5 GB) ..."
      ollama pull $model
      $chosen = $model
  }
} else { Write-Host "Skipped ($($rep.recommendation.reason))." }
# write config.json (keeps existing values). whisper_device stays "cpu"; set "cuda" by hand once CUDA 12 + cuDNN 9 exist.
& .venv\Scripts\python.exe -c "import json,os,sys; p='config.json'; c=json.load(open(p,encoding='utf-8')) if os.path.exists(p) else {}; m=sys.argv[1]; c.update({'ollama_model': m} if m else {}); json.dump(c, open(p,'w',encoding='utf-8'), indent=2)" "$chosen"

Write-Host "`n== 6/7 Component test ==" -ForegroundColor Yellow
& .\ordelva.bat check

Write-Host "`n== 7/7 Reproduction test: render the Doggerland short ==" -ForegroundColor Yellow
if (Ask "Render the Doggerland test short now (3–15 min depending on CPU)?") {
  & .\ordelva.bat render doggerland-short
  Write-Host "Result: $root\output\doggerland-short.mp4"
}
Write-Host "`nDone. Start the control panel with: start_dashboard.bat" -ForegroundColor Green
