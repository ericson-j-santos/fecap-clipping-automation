#requires -Version 5.1
# Version: 5.0.0
[CmdletBinding()]
param(
    [string]$PortalUrl = "https://monitoring.knewin.com/",
    [string]$BaseDir = (Join-Path $env:USERPROFILE ".fecap-clipping"),
    [string]$Wheelhouse = "",
    [switch]$Offline,
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$EvidenceDir = Join-Path $BaseDir "evidence"
$LogPath = Join-Path $EvidenceDir "knewin-session-bootstrap.jsonl"
$ProfileDir = Join-Path $BaseDir "knewin-profile"
$VenvDir = Join-Path $BaseDir "venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$EvidencePath = Join-Path $EvidenceDir "knewin-auth-probe.json"
$Requirements = Join-Path $RepoRoot "requirements-local.txt"
$ProbeScript = Join-Path $PSScriptRoot "probe_knewin_session.py"

New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
New-Item -ItemType Directory -Force -Path $ProfileDir | Out-Null

function Write-Event {
    param(
        [string]$Level,
        [string]$Step,
        [string]$Message,
        [Nullable[int]]$Code = $null
    )
    $entry = [ordered]@{
        timestamp = (Get-Date).ToUniversalTime().ToString("o")
        level = $Level
        step = $Step
        message = $Message
        offline = [bool]$Offline
    }
    if ($null -ne $Code) { $entry.code = [int]$Code }
    $json = $entry | ConvertTo-Json -Compress
    Add-Content -Path $LogPath -Value $json -Encoding UTF8
    Write-Host "[$Level] $Step - $Message"
}

function Fail {
    param([int]$Code, [string]$Step, [string]$Message)
    Write-Event -Level "ERROR" -Step $Step -Message $Message -Code $Code
    Write-Host "ERRO [$Code]: $Message" -ForegroundColor Red
    exit $Code
}

function Refresh-ProcessPath {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

function Test-Python {
    param([string]$Exe, [string[]]$PrefixArgs = @())
    try {
        $output = & $Exe @PrefixArgs -c "import sys; print(sys.executable); raise SystemExit(0 if sys.version_info >= (3, 11) else 9)" 2>&1
        return ($LASTEXITCODE -eq 0 -and (($output | Out-String) -notmatch "Microsoft Store|Python was not found|Python não foi encontrado"))
    } catch {
        return $false
    }
}

function Resolve-Python {
    Refresh-ProcessPath
    $candidates = @(
        @{ Exe = "py"; Args = @("-3") },
        @{ Exe = "python"; Args = @() },
        @{ Exe = "python3"; Args = @() }
    )
    foreach ($candidate in $candidates) {
        if ((Get-Command $candidate.Exe -ErrorAction SilentlyContinue) -and
            (Test-Python -Exe $candidate.Exe -PrefixArgs $candidate.Args)) {
            return $candidate
        }
    }

    $roots = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python"),
        (Join-Path $env:ProgramFiles "Python312"),
        (Join-Path $env:ProgramFiles "Python311")
    ) | Where-Object { $_ -and (Test-Path $_) }

    foreach ($root in $roots) {
        $found = Get-ChildItem -Path $root -Filter python.exe -Recurse -ErrorAction SilentlyContinue |
            Where-Object { Test-Python -Exe $_.FullName } |
            Select-Object -First 1
        if ($found) { return @{ Exe = $found.FullName; Args = @() } }
    }
    return $null
}

function Invoke-Python {
    param(
        [hashtable]$Python,
        [string[]]$Arguments,
        [string]$Step
    )
    $all = @($Python.Args) + @($Arguments)
    Write-Event -Level "INFO" -Step $Step -Message ("Executando Python: " + ($Arguments -join " "))
    & $Python.Exe @all
    $code = [int]$LASTEXITCODE
    Write-Event -Level $(if ($code -eq 0) { "INFO" } else { "WARN" }) -Step $Step -Message "Python terminou." -Code $code
    return $code
}

function Install-OfficialPython {
    if ($Offline) { Fail 11 "python" "Python não disponível em modo offline." }
    if ($SkipInstall) { Fail 12 "python" "Python não disponível e -SkipInstall foi informado." }
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) { Fail 13 "python" "Python não encontrado e winget não está disponível." }

    Write-Event -Level "WARN" -Step "python" -Message "Instalando/reparando Python 3.12 oficial no escopo do usuário."
    & winget install --id Python.Python.3.12 -e --scope user --accept-package-agreements --accept-source-agreements --silent --force
    if ($LASTEXITCODE -ne 0) { Fail 14 "python" "winget não conseguiu instalar/reparar Python 3.12." }
    Refresh-ProcessPath
}

Set-Content -Path $LogPath -Value "" -Encoding UTF8
Write-Event -Level "INFO" -Step "bootstrap" -Message "Início do bootstrap Knewin v5.0.0."

$BasePython = Resolve-Python
if (-not $BasePython) {
    Install-OfficialPython
    $BasePython = Resolve-Python
}
if (-not $BasePython) { Fail 15 "python" "Python 3.11+ continua indisponível após bootstrap." }

if (-not (Test-Path $VenvPython)) {
    Write-Event -Level "INFO" -Step "venv" -Message "Criando ambiente virtual isolado."
    $code = Invoke-Python -Python $BasePython -Arguments @("-m", "venv", $VenvDir) -Step "venv_create"
    if ($code -ne 0 -or -not (Test-Path $VenvPython)) {
        if ($Offline -or $SkipInstall) {
            Fail 20 "venv" "Não foi possível criar ambiente virtual com pip em modo sem instalação."
        }
        Remove-Item -Recurse -Force $VenvDir -ErrorAction SilentlyContinue
        Install-OfficialPython
        $BasePython = Resolve-Python
        if (-not $BasePython) { Fail 21 "venv" "Python oficial não foi localizado após reparo." }
        $code = Invoke-Python -Python $BasePython -Arguments @("-m", "venv", $VenvDir) -Step "venv_retry"
        if ($code -ne 0 -or -not (Test-Path $VenvPython)) {
            Fail 22 "venv" "Falha definitiva ao criar venv; o Python instalado não disponibilizou ensurepip."
        }
    }
}

$Python = @{ Exe = $VenvPython; Args = @() }
$code = Invoke-Python -Python $Python -Arguments @("-m", "pip", "--version") -Step "pip_check"
if ($code -ne 0) {
    $code = Invoke-Python -Python $Python -Arguments @("-m", "ensurepip", "--upgrade") -Step "pip_ensure"
    if ($code -ne 0) { Fail 23 "pip" "O venv existe, mas pip/ensurepip estão indisponíveis." }
    $code = Invoke-Python -Python $Python -Arguments @("-m", "pip", "--version") -Step "pip_recheck"
    if ($code -ne 0) { Fail 24 "pip" "pip continua indisponível após ensurepip." }
}

$importCode = Invoke-Python -Python $Python -Arguments @("-c", "import playwright") -Step "playwright_check"
if ($importCode -ne 0) {
    if ($SkipInstall) { Fail 30 "playwright" "Playwright ausente e -SkipInstall foi informado." }

    if ($Offline) {
        if (-not $Wheelhouse) { $Wheelhouse = Join-Path $RepoRoot "dist\wheelhouse" }
        if (-not (Test-Path $Wheelhouse)) {
            Fail 31 "playwright" "Modo offline: wheelhouse local não encontrado."
        }
        $code = Invoke-Python -Python $Python -Arguments @("-m", "pip", "install", "--no-index", "--find-links", $Wheelhouse, "-r", $Requirements) -Step "playwright_install_offline"
    } else {
        $code = Invoke-Python -Python $Python -Arguments @("-m", "pip", "install", "--disable-pip-version-check", "-r", $Requirements) -Step "playwright_install"
    }
    if ($code -ne 0) { Fail 32 "playwright" "Falha ao instalar dependências Python." }
}

$browserCheck = "from pathlib import Path; from playwright.sync_api import sync_playwright; p=sync_playwright().start(); x=p.chromium.executable_path; p.stop(); raise SystemExit(0 if Path(x).is_file() else 1)"
$browserCode = Invoke-Python -Python $Python -Arguments @("-c", $browserCheck) -Step "chromium_check"
if ($browserCode -ne 0) {
    if ($Offline) { Fail 40 "chromium" "Modo offline: Chromium do Playwright não está instalado." }
    if ($SkipInstall) { Fail 41 "chromium" "Chromium ausente e -SkipInstall foi informado." }
    $code = Invoke-Python -Python $Python -Arguments @("-m", "playwright", "install", "chromium") -Step "chromium_install"
    if ($code -ne 0) { Fail 42 "chromium" "Falha ao instalar Chromium do Playwright." }
}

if (-not (Test-Path $ProbeScript)) { Fail 50 "probe" "Script de sonda Knewin não encontrado no repositório." }

$env:KNEWIN_PORTAL_URL = $PortalUrl
$env:KNEWIN_PROFILE_DIR = $ProfileDir
$env:KNEWIN_AUTH_EVIDENCE = $EvidencePath

Write-Event -Level "INFO" -Step "probe" -Message "Executando sonda versionada; nenhuma credencial será persistida."
$code = Invoke-Python -Python $Python -Arguments @($ProbeScript) -Step "probe_run"

if (Test-Path $EvidencePath) {
    try {
        $evidence = Get-Content $EvidencePath -Raw | ConvertFrom-Json
        Write-Event -Level "INFO" -Step "evidence" -Message ("status=" + $evidence.status + "; session_reused=" + $evidence.session_reused + "; secrets_captured=" + $evidence.secrets_captured)
    } catch {
        Write-Event -Level "WARN" -Step "evidence" -Message "Evidência criada, mas não pôde ser interpretada."
    }
}

if ($code -ne 0) { Fail $code "probe" "Sonda Knewin encerrou sem PASS; consulte evidência e log estruturado." }
Write-Event -Level "INFO" -Step "complete" -Message "Bootstrap e sonda concluídos."
exit 0
