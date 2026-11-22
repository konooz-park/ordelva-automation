# ORDELVA – hardware & software check (read-only, changes nothing)
# Writes system_report.json in the project folder and prints a recommendation.
$ErrorActionPreference = "SilentlyContinue"
$root = Split-Path -Parent $PSScriptRoot

function Ver($cmd, $arg = "--version") {
    $c = Get-Command $cmd -ErrorAction SilentlyContinue
    if (-not $c) { return $null }
    try { return ((& $cmd $arg 2>&1) | Select-Object -First 1).ToString().Trim() } catch { return "present" }
}

$os   = Get-CimInstance Win32_OperatingSystem
$cpu  = Get-CimInstance Win32_Processor | Select-Object -First 1
$ramGB = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
$drive = (Get-Item $root).PSDrive.Name
$disk = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$($drive):'"
$freeGB = [math]::Round($disk.FreeSpace / 1GB, 1)
$gpus = @(Get-CimInstance Win32_VideoController | ForEach-Object {
    [ordered]@{ name = $_.Name; driver = $_.DriverVersion; vram_gb_reported = [math]::Round($_.AdapterRAM / 1GB, 1) } })

$nv = $null; $vram = 0
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    $q = nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader,nounits 2>$null | Select-Object -First 1
    if ($q) { $p = $q.Split(","); $vram = [math]::Round([double]$p[1].Trim() / 1024, 1)
              $nv = [ordered]@{ name = $p[0].Trim(); vram_gb = $vram; driver = $p[2].Trim()
                                cuda = ((nvidia-smi 2>$null | Select-String "CUDA Version:\s*([\d.]+)").Matches.Groups[1].Value) } }
}

# Recommendation
if ($nv -and $vram -ge 8)       { $llm = "qwen2.5:7b";  $why = "NVIDIA GPU with $vram GB VRAM" }
elseif ($ramGB -ge 15)          { $llm = "qwen2.5:7b";  $why = "$ramGB GB RAM, CPU inference (slow but fine for a few scripts/day)" }
elseif ($ramGB -ge 7.5)         { $llm = "qwen2.5:3b";  $why = "$ramGB GB RAM – small model" }
else                            { $llm = "";            $why = "under 8 GB RAM – write scripts by hand / skip local LLM" }

$report = [ordered]@{
    checked_at = (Get-Date).ToString("s")
    windows    = "$($os.Caption) $($os.Version) build $($os.BuildNumber)"
    cpu        = "$($cpu.Name.Trim()) – $($cpu.NumberOfCores) cores / $($cpu.NumberOfLogicalProcessors) threads"
    ram_gb     = $ramGB
    disk_free_gb = $freeGB
    gpus       = $gpus
    nvidia     = $nv
    tools      = [ordered]@{
        python = (Ver "py" "--version"); python_exe = (Ver "python"); git = (Ver "git"); ffmpeg = (Ver "ffmpeg" "-version")
        docker = (Ver "docker"); ollama = (Ver "ollama" "--version"); winget = (Ver "winget") }
    recommendation = [ordered]@{ ollama_model = $llm; reason = $why
        whisper_device = $(if ($nv) { "cuda (needs CUDA 12 + cuDNN 9) – default stays cpu" } else { "cpu" })
        render_estimate = "about 0.1–0.3 s per 1080p frame per CPU core (a 60 s short ≈ 3–10 min)" }
}
$report | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 (Join-Path $root "system_report.json")
$report | ConvertTo-Json -Depth 5
if ($freeGB -lt 10) { Write-Warning "Less than 10 GB free on drive $drive – models + renders need ~8 GB." }
