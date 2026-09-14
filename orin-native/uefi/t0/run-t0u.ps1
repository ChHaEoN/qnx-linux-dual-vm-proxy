<#
.SYNOPSIS
  T0u: compile m5load-rules.h for the host and run its unit tests.

.DESCRIPTION
  Phase 3b, results/orin-native-port/20260909T1100Z/s1-design.md §15.13.4, the
  T0u row. Builds t0/t0u-rules.c with the host C compiler (MSVC, found through
  vswhere) into a git-ignored output directory and runs it. The test uses only
  synthetic maps and trees: no firmware, no board, no QNX byte.

  Exit 0 when every check passes; 1 on any failure; 2 when no host compiler is
  found.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File orin-native\uefi\t0\run-t0u.ps1
#>

param(
  [string]$OutDir
)

$ErrorActionPreference = 'Stop'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$uefi = Split-Path -Parent $here
if (-not $OutDir) { $OutDir = Join-Path $uefi 'out\t0u' }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$vcvars = $null
if (Test-Path $vswhere) {
  $paths = & $vswhere -all -products '*' -property installationPath
  foreach ($p in $paths) {
    $cand = Join-Path $p 'VC\Auxiliary\Build\vcvars64.bat'
    if (Test-Path $cand) { $vcvars = $cand; break }
  }
}
if (-not $vcvars) {
  Write-Host 'T0U no host compiler: no vcvars64.bat under any Visual Studio installation'
  exit 2
}

$src = Join-Path $here 't0u-rules.c'
$exe = Join-Path $OutDir 't0u-rules.exe'
# A named object file, not a directory: cl reads a trailing \" as an escaped quote.
$obj = Join-Path $OutDir 't0u-rules.obj'
$log = Join-Path $OutDir 'build.log'

# /W4 /WX: the header must build warning-free on a second compiler too.
# vcvars64.bat calls vswhere.exe itself, so its directory goes on PATH; cmd does
# the redirection, so compiler output on stderr is not a PowerShell error.
if (Test-Path $exe) { Remove-Item -Force $exe }
$vsdir = Split-Path -Parent $vswhere
$cmd = "set `"PATH=%PATH%;$vsdir`" && call `"$vcvars`" >nul && cl /nologo /W4 /WX /TC /Fo`"$obj`" /Fe`"$exe`" `"$src`" > `"$log`" 2>&1"
cmd.exe /c $cmd
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $exe)) {
  Get-Content $log | Write-Host
  Write-Host 'T0U RESULT FAIL build'
  exit 1
}

& $exe
exit $LASTEXITCODE
