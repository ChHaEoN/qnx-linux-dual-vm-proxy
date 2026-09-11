<#
.SYNOPSIS
  Run M4's timed runs T<Start>..T<End> of one r2 kimg back to back, each with a
  fresh byte-exact COM3 capture.

.DESCRIPTION
  Phase 3b, results/orin-native-port/20260909T1100Z/m4-design.md §6.1
  (revision 2); the untracked m3-tloop.ps1 that ran M3's T-runs, made generic.

  For each run t<i>:
    1. stop any older capture (a powershell.exe whose command line names
       capture-com3-raw.ps1; COM3 is exclusive) and confirm it gone
    2. start capture-com3-raw.ps1 from PowerShell, -Seconds set to capture_s
       from orin-native/shim/out/m4/<Image>.params (a Git Bash capture receives
       nothing, m2-runs.md:135-137)
    3. wait up to 20 s for its '--- raw capture started' header
    4. run 'bash orin-native/startup/m4-board.sh run <Image>' with
       M4_RUN_ID=t<i>, M4_COM3_LOG, M4_RECORD_DIR, M4_QUIESCE=1 and
       M4_GOVERNOR_PIN=1 (the owner decisions O4 and O5 as they ran, §2.0)
    5. stop the capture
    6. stop the loop at the first run whose parse log lacks
       'M4PC run_verdict=pass'. A failed T-run is never replaced (§2.3).
  ORIN_HOST and ORIN_KEY are inherited from the caller's environment; this
  script writes no address, user name or key path anywhere.

  Every run needs the owner at the plug (§10): a native image that hangs after
  kexec does not recover by itself.

.EXAMPLE
  $env:ORIN_HOST = '<user>@<address>'; $env:ORIN_KEY = '<key file>'
  powershell -ExecutionPolicy Bypass -File orin-native\m4\m4-tloop.ps1 -Image m4-r2-k512-n2000 -RecordDir results\orin-native-port\<utc>\m4
#>
param(
  [Parameter(Mandatory = $true)][ValidatePattern('^m4-r2-(k[0-9]+|lin)-n[0-9]+$')][string]$Image,
  [ValidateRange(1, 5)][int]$Start = 1,
  [ValidateRange(1, 5)][int]$End = 5,
  [Parameter(Mandatory = $true)][string]$RecordDir,
  [string]$Bash
)

$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot  = [System.IO.Path]::GetFullPath((Join-Path $scriptDir '..\..')).TrimEnd('\')
$params    = Join-Path $repoRoot "orin-native\shim\out\m4\$Image.params"
$capture   = Join-Path $scriptDir 'capture-com3-raw.ps1'
$harness   = ($repoRoot -replace '\\','/') + '/orin-native/startup/m4-board.sh'

if ($End -lt $Start) { Write-Host "REFUSED: -End $End is before -Start $Start"; exit 2 }
if (-not $env:ORIN_HOST) { Write-Host 'REFUSED: ORIN_HOST is not set in this environment'; exit 2 }
if (-not (Test-Path -LiteralPath $params)) { Write-Host "REFUSED: no $Image.params under orin-native/shim/out/m4 (build the image first)"; exit 2 }

$captureS = $null
foreach ($line in [System.IO.File]::ReadAllLines($params)) {
  if ($line -match '^capture_s=([0-9]+)$') { $captureS = [int]$Matches[1] }
}
if (-not $captureS) { Write-Host "REFUSED: $Image.params has no capture_s"; exit 2 }

if (-not $Bash) {
  $cmd = Get-Command bash.exe -ErrorAction SilentlyContinue
  if ($cmd -and $cmd.Source -notlike '*\System32\*') { $Bash = $cmd.Source }
  elseif (Test-Path -LiteralPath 'C:\Program Files\Git\bin\bash.exe') { $Bash = 'C:\Program Files\Git\bin\bash.exe' }
}
if (-not $Bash -or -not (Test-Path -LiteralPath $Bash)) { Write-Host 'REFUSED: Git Bash not found; pass -Bash <path to bash.exe>'; exit 2 }

New-Item -ItemType Directory -Force -Path $RecordDir | Out-Null
$recFull = [System.IO.Path]::GetFullPath($RecordDir)
$recFwd  = $recFull -replace '\\','/'

function Stop-Captures {
  $procs = @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
    Where-Object { $_.CommandLine -like '*capture-com3-raw.ps1*' -and $_.ProcessId -ne $PID })
  foreach ($p in $procs) { try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop } catch { } }
  foreach ($p in $procs) {
    for ($i = 0; $i -lt 100; $i++) {
      if (-not (Get-Process -Id $p.ProcessId -ErrorAction SilentlyContinue)) { break }
      Start-Sleep -Milliseconds 100
    }
    if (Get-Process -Id $p.ProcessId -ErrorAction SilentlyContinue) {
      Write-Host "capture pid $($p.ProcessId) did not stop within 10 s"
      return $false
    }
  }
  return $true
}

for ($t = $Start; $t -le $End; $t++) {
  $run = "t$t"
  $com3 = Join-Path $recFull "com3-$Image-$run.log"
  if (Test-Path -LiteralPath $com3) { Write-Host "REFUSED: $com3 exists; run ids are never reused"; exit 2 }
  if (-not (Stop-Captures)) { exit 5 }
  Start-Sleep -Milliseconds 700
  $cap = Start-Process -FilePath powershell.exe -PassThru -WindowStyle Hidden -ArgumentList @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $capture,
    '-Port', 'COM3', '-Seconds', "$captureS", '-Out', $com3)
  $opened = $false
  for ($i = 0; $i -lt 80; $i++) {
    if ((Test-Path -LiteralPath $com3) -and (Select-String -LiteralPath $com3 -Pattern '^--- raw capture started' -Quiet)) { $opened = $true; break }
    if (Test-Path -LiteralPath $com3) {
      if (Select-String -LiteralPath $com3 -Pattern '^FAILED to open' -Quiet) { break }
    }
    Start-Sleep -Milliseconds 250
  }
  if (-not $opened) { Write-Host "[$(Get-Date -Format s)] $Image $run capture did not open; stopping"; [void](Stop-Captures); exit 5 }
  Write-Host "[$(Get-Date -Format s)] $Image $run started (capture pid $($cap.Id), seconds=$captureS)"

  $env:M4_RUN_ID       = $run
  $env:M4_COM3_LOG     = $com3 -replace '\\','/'
  $env:M4_RECORD_DIR   = $recFwd
  $env:M4_QUIESCE      = '1'
  $env:M4_GOVERNOR_PIN = '1'
  Push-Location $repoRoot
  try {
    & $Bash $harness run $Image
    $rc = $LASTEXITCODE
  } finally {
    Pop-Location
  }
  [void](Stop-Captures)
  Write-Host "[$(Get-Date -Format s)] $Image $run finished rc=$rc"

  $parseLog = Join-Path $recFull "out\$Image-$run-parse.log"
  $pass = (Test-Path -LiteralPath $parseLog) -and (Select-String -LiteralPath $parseLog -Pattern '^M4PC run_verdict=pass$' -Quiet)
  if (-not $pass) {
    Write-Host "stopping after $run for inspection: no 'M4PC run_verdict=pass' in $parseLog (harness rc=$rc)"
    if ($rc -ne 0) { exit $rc }
    exit 6
  }
}
Write-Host "all runs t$Start..t$End of $Image done"
exit 0
