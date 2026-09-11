<#
.SYNOPSIS
  Build one M4 TCG rehearsal host image: the M4 host script, the counter and
  its fixtures inside a Windows-TCG QHV host (m4-design.md §11.2).

.DESCRIPTION
  Implements results/orin-native-port/20260909T1100Z/m4-design.md §11.2
  (revision 2), derived from orin-native/m4dry/build-m4dry-image.ps1 (steps 1-9)
  with only the design's changes and the notes of that file's §14. The variant is
  a REBUILT host IFS and disk that carries the byte-identical guest IFS and guest
  disk. It is not the canonical host image, nothing it produces feeds the Phase-4
  twin diff, and no -k value here is ever copied to a board image (DD:1710-1715).

  It writes only under qhv/m4tcg/ (git-ignored through /qhv/) and the tool
  binaries in orin-native/tools/ (git-ignored). It never runs
  scripts/build-qhv.bat, never points mkqnximage at qhv/host or qhv/guest, and
  never deletes a directory. The canonical images are only read and hashed,
  before and after the build.

  Variants (§11.2, §11.4):
    r0    MODE=trace: clock, fixtures, probe, L0, format, count, block v over the console
    k512  MODE=full: 15 IPC iterations in a ring of 512 buffers per CPU (the size that held under TCG)
    k16   MODE=full: the same in a ring of 16 buffers per CPU, built to wrap

  Steps:
    1. the TCG profile values for the §4.1 markers
    2. canonical checks: path refusal, qhv/host/output/SHA256SUMS, guest pins
    3. guest copy: qhv/guest -> qhv/m4tcg/guest.partial -> qhv/m4tcg/guest, then its pins
    4. tools: make bwait trcctl stamp clkcmp m4count in the SDP environment (not
       tcu-cat: under QEMU virt 0x0C168000 is not a TCU mailbox); client sha256
    5. stage host-<variant>/local: the snippets, m4-host.ksh (TCG profile),
       m4-g2.conf (checked against the as-run printf text), the fixtures and
       m4tcg.params (LF, no BOM); kshcheck --selftest, then kshcheck on the script
    6. mkqnximage from host-<variant>, killed at 1800 s
    7. text checks of the generated build files
    8. hashes after: the guest copy and the canonical images; M4TCG-SHA256SUMS
  Exit 0 only when every check passed; it stops at the first failure with
  "FAIL: <what>".

  Licence (NC QDL v7): SDP files are handled as opaque files only: copied into our
  own image by mkqnximage and hashed. Nothing QNX-shipped is inspected.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File orin-native\m4\build-m4tcg-image.ps1 -Variant r0
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File orin-native\m4\build-m4tcg-image.ps1 -Variant k512 -Tag a
#>
param(
  [ValidateSet('r0','k512','k16')][string]$Variant = 'r0',
  [ValidatePattern('^[a-z0-9]{0,16}$')][string]$Tag = '',
  [ValidateSet('status0','none')][string]$E3 = 'status0',
  [ValidateRange(10, 3600)][int]$Grace = 150
)

$ErrorActionPreference = 'Stop'

$GuestIfsPin  = '968029316b940f53580228f44e393877e032e251d78f3c752600cae726a7cf4f'
$GuestDiskPin = 'cf5b06d0b3cb524201c71440fdda42a18d2636d45938acd8ec95cfa21314216b'
$ClientPinM3  = '52cb4dcad5a3632f88092289ef68668cc1fc604f150f3e2f8b9f31dc82caa7eb'
$MakeBoundSec       = 600
$MkqnximageBoundSec = 1800
$PythonBoundSec     = 120

$scriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot    = [System.IO.Path]::GetFullPath((Join-Path $scriptDir '..\..')).TrimEnd('\')
$repoFwd     = $repoRoot -replace '\\','/'
$canonHost   = Join-Path $repoRoot 'qhv\host'
$canonGuest  = Join-Path $repoRoot 'qhv\guest'
$runRoot     = Join-Path $repoRoot 'qhv\m4tcg'
$vName       = $Variant
if ($Tag) { $vName = "$Variant-$Tag" }
$hostDir     = Join-Path $runRoot "host-$vName"
$stageDir    = Join-Path $runRoot "stage-$vName"
$guestCopy   = Join-Path $runRoot 'guest'
$guestPart   = Join-Path $runRoot 'guest.partial'
$buildLog    = Join-Path $runRoot "build-$vName.log"
$toolsDir    = Join-Path $repoRoot 'orin-native\tools'
$clientBin   = Join-Path $repoRoot 'ipc-test\qnx-host-client\qnx-host-client'
$kshTemplate = Join-Path $repoRoot 'orin-native\startup\m4-host.ksh.in'
$confSrc     = Join-Path $repoRoot 'orin-native\qhv\g2-m3.conf'
$asrunPost   = Join-Path $canonHost 'output\build\post_startup.sh'
$canonSysBld = Join-Path $canonHost 'output\build\system.build'
$fixDir      = Join-Path $scriptDir 'fixtures'
$parser      = Join-Path $scriptDir 'parse-m4.py'
if ($env:QNX_INSTALL_ROOT) { $sdpRoot = $env:QNX_INSTALL_ROOT } else { $sdpRoot = Join-Path $env:USERPROFILE 'qnx800' }
$sdpEnv      = Join-Path $sdpRoot 'qnxsdp-env.bat'
$sdpTarget   = Join-Path $sdpRoot 'target\qnx\aarch64le'
$utf8NoBom   = New-Object System.Text.UTF8Encoding $false

# ---------------------------------------------------------------- helpers (as build-m4dry-image.ps1)

function Log([string]$Line) {
  Write-Host $Line
  [System.IO.File]::AppendAllText($buildLog, $Line + "`n", $utf8NoBom)
}

function Fail([string]$What) {
  Log "FAIL: $What"
  throw 'M4TCG-FAIL'
}

function Read-Text([string]$Path) { return [System.IO.File]::ReadAllText($Path) }

function Write-Lf([string]$Path, [string]$Text) {
  [System.IO.File]::WriteAllText($Path, $Text.Replace("`r`n", "`n"), $utf8NoBom)
}

function Get-Sha256([string]$Path) { return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant() }
function Get-Md5([string]$Path) { return (Get-FileHash -Algorithm MD5 -LiteralPath $Path).Hash.ToLowerInvariant() }
function Get-NormPath([string]$Path) { return ([System.IO.Path]::GetFullPath($Path) -replace '/','\').TrimEnd('\') }

function Test-Under([string]$Path, [string]$Base) {
  $a = Get-NormPath $Path
  $b = Get-NormPath $Base
  return ($a -ieq $b) -or $a.StartsWith($b + '\', [System.StringComparison]::OrdinalIgnoreCase)
}

function Assert-TargetPath([string]$Path) {
  if ((Test-Under $Path $canonHost) -or (Test-Under $Path $canonGuest)) {
    Fail "path_refused $Path (equals or lies under qhv/host or qhv/guest)"
  }
  $a = Get-NormPath $Path
  $b = Get-NormPath $runRoot
  if (-not $a.StartsWith($b + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
    Fail "path_refused $Path (does not lie under qhv/m4tcg/)"
  }
}

function Test-Canonical([string]$When) {
  $bad = 'CHANGED'
  if ($When -eq 'pre') { $bad = 'MISMATCH' }
  $sums = Join-Path $canonHost 'output\SHA256SUMS'
  if (-not (Test-Path -LiteralPath $sums)) { Fail "canonical_$When=$bad qhv/host/output/SHA256SUMS is missing" }
  $n = 0
  foreach ($line in [System.IO.File]::ReadAllLines($sums)) {
    $m = [regex]::Match($line, '^([0-9a-fA-F]{64}) [ *]?(\S+)\s*$')
    if (-not $m.Success) { continue }
    $want = $m.Groups[1].Value.ToLowerInvariant()
    $name = $m.Groups[2].Value
    $got  = Get-Sha256 (Join-Path $canonHost ('output\' + $name))
    if ($got -ne $want) {
      Log "canonical_$When qhv/host/output/$name sha256=$got $bad (SHA256SUMS: $want)"
      Fail "canonical_$When=$bad qhv/host/output/$name"
    }
    Log "canonical_$When qhv/host/output/$name sha256=$got ok"
    $n++
  }
  if ($n -ne 2) { Fail "canonical_$When=$bad SHA256SUMS lists $n files, expected 2" }
  foreach ($pin in @(@('ifs.bin', $GuestIfsPin), @('disk-qvm', $GuestDiskPin))) {
    $got = Get-Sha256 (Join-Path $canonGuest ('output\' + $pin[0]))
    if ($got -ne $pin[1]) {
      Log "canonical_$When qhv/guest/output/$($pin[0]) sha256=$got $bad (pin: $($pin[1]))"
      Fail "canonical_$When=$bad qhv/guest/output/$($pin[0])"
    }
    Log "canonical_$When qhv/guest/output/$($pin[0]) sha256=$got ok"
  }
  Log "canonical_$When=ok"
}

function Test-GuestCopy([string]$When) {
  $gi = Get-Sha256 (Join-Path $guestCopy 'output\ifs.bin')
  $gd = Get-Sha256 (Join-Path $guestCopy 'output\disk-qvm')
  if ($gi -ne $GuestIfsPin -or $gd -ne $GuestDiskPin) {
    Log "guest_copy_$When=MISMATCH ifs.bin=$gi disk-qvm=$gd"
    Fail "guest_copy_$When=MISMATCH: the owner renames qhv/m4tcg/guest; the next build copies afresh"
  }
  Log "guest_copy_$When=ok ifs.bin=$gi disk-qvm=$gd"
}

function Invoke-CmdBounded([string]$Name, [string[]]$CmdLines, [string]$WorkDir, [int]$Seconds) {
  $cmdFile = Join-Path $stageDir "$Name.cmd"
  $outFile = Join-Path $stageDir "$Name.out.log"
  $errFile = Join-Path $stageDir "$Name.err.log"
  [System.IO.File]::WriteAllText($cmdFile, (($CmdLines -join "`r`n") + "`r`n"), (New-Object System.Text.ASCIIEncoding))
  Log "run $Name bound_s=$Seconds workdir=$WorkDir"
  foreach ($l in $CmdLines) { Log "  | $l" }
  $p = Start-Process -FilePath $env:ComSpec -ArgumentList @('/d', '/c', ('"' + $cmdFile + '"')) `
         -WorkingDirectory $WorkDir -NoNewWindow -PassThru `
         -RedirectStandardOutput $outFile -RedirectStandardError $errFile
  $null = $p.Handle
  $killed = $false
  if (-not $p.WaitForExit($Seconds * 1000)) {
    $killed = $true
    $tk = Start-Process -FilePath (Join-Path $env:SystemRoot 'System32\taskkill.exe') `
            -ArgumentList @('/T', '/F', '/PID', "$($p.Id)") -NoNewWindow -PassThru
    $null = $tk.WaitForExit(30000)
    $null = $p.WaitForExit(15000)
  }
  $code = $null
  if ($p.HasExited) { $code = $p.ExitCode }
  $text = ''
  foreach ($f in @($outFile, $errFile)) {
    if (Test-Path -LiteralPath $f) { $text += [System.IO.File]::ReadAllText($f) }
  }
  [System.IO.File]::AppendAllText($buildLog,
    "----- $Name output -----`n" + $text.Replace("`r`n", "`n") + "`n----- end of $Name output -----`n", $utf8NoBom)
  $codeText = 'none'
  if ($null -ne $code) { $codeText = "$code" }
  Log "run $Name exit=$codeText killed=$([int]$killed)"
  return [pscustomobject]@{ Code = $code; Killed = $killed; Text = $text }
}

function Invoke-PythonBounded([string]$Name, [string[]]$PyArgs, [int]$Seconds) {
  $py = (Get-Command python -ErrorAction Stop).Source
  $quoted = @()
  foreach ($x in $PyArgs) { if ($x -match '\s') { $quoted += ('"' + $x + '"') } else { $quoted += $x } }
  return (Invoke-CmdBounded $Name @('@echo off', ('"' + $py + '" ' + ($quoted -join ' ') + ' 2>&1'), 'exit /b %ERRORLEVEL%') $repoRoot $Seconds)
}

# ---------------------------------------------------------------- main

$exitCode = 1
try {
  New-Item -ItemType Directory -Force -Path $runRoot | Out-Null
  Log ''
  Log ('===== build-m4tcg-image.ps1 start utc=' + (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') + ' =====')
  Log "variant=$Variant tag=$(if ($Tag) { $Tag } else { 'none' }) dir=qhv/m4tcg/host-$vName e3=$E3 grace=$Grace image=rebuilt-host guest=byte-identical"

  # 1. The TCG profile (§11.2).
  switch ($Variant) {
    'r0'   { $mode = 'trace'; $rung = 'r0'; $kind = 'probe'; $tlArgs = '-r -k 64 -M -S 8M';  $traceNeed = 44;  $fmtNeed = 463; $cntNeed = 303
             $capV = 262144; $capC = 0; $forms = 'v'; $cntOut = '-v /dev/shmem/flt.v -V 262144' }
    'k512' { $mode = 'full';  $rung = 'r1'; $kind = 'ring';  $tlArgs = '-r -k 512 -M -S 36M'; $traceNeed = 100; $fmtNeed = 484; $cntNeed = 304
             $capV = 1048576; $capC = 524288; $forms = 'v c'; $cntOut = '-v /dev/shmem/flt.v -V 1048576 -c /dev/shmem/flt.c -C 524288' }
    'k16'  { $mode = 'full';  $rung = 'r1'; $kind = 'ring';  $tlArgs = '-r -k 16 -M -S 4M';   $traceNeed = 36;  $fmtNeed = 324; $cntNeed = 304
             $capV = 1048576; $capC = 524288; $forms = 'v c'; $cntOut = '-v /dev/shmem/flt.v -V 1048576 -c /dev/shmem/flt.c -C 524288' }
  }
  if ($E3 -eq 'none') { $cntOut += ' -E none' }
  Log "profile rung=tcg-$Variant mode=$mode tl_args='$tlArgs' trace_need=$traceNeed fmt_need=$fmtNeed cnt_need=$cntNeed forms='$forms' cnt_out='$cntOut'"

  # 2. Canonical checks.
  foreach ($d in @($hostDir, $stageDir, $guestCopy, $guestPart)) { Assert-TargetPath $d }
  if ((Test-Path -LiteralPath $hostDir) -and (@(Get-ChildItem -LiteralPath $hostDir -Force).Count -gt 0)) {
    Fail "host_dir_not_empty $hostDir (use a new -Tag; no script deletes a directory)"
  }
  if (-not (Test-Path -LiteralPath $sdpEnv)) { Fail "no SDP environment script at $sdpEnv" }
  Test-Canonical 'pre'

  # 3. The guest copy.
  if (Test-Path -LiteralPath $guestPart) { Fail 'guest_copy refused: qhv/m4tcg/guest.partial exists (an interrupted copy; the owner renames it)' }
  if (Test-Path -LiteralPath $guestCopy) {
    Log 'guest_copy=existing (a completed earlier copy)'
  } else {
    Copy-Item -LiteralPath $canonGuest -Destination $guestPart -Recurse
    Rename-Item -LiteralPath $guestPart -NewName 'guest'
    Log 'guest_copy=fresh (qhv/guest -> qhv/m4tcg/guest.partial -> qhv/m4tcg/guest)'
  }
  Test-GuestCopy 'pre'

  # 4. Tools.
  New-Item -ItemType Directory -Force -Path $stageDir | Out-Null
  $r = Invoke-CmdBounded 'make-tools' @(
    '@echo off',
    "call `"$sdpEnv`" >nul 2>&1",
    '@echo off',
    "make -C `"$repoFwd/orin-native/tools`" bwait trcctl stamp clkcmp m4count 2>&1",
    'exit /b %ERRORLEVEL%'
  ) $repoRoot $MakeBoundSec
  if ($r.Killed -or $r.Code -ne 0) { Fail 'tools: make bwait trcctl stamp clkcmp m4count failed' }
  foreach ($t in @('bwait', 'trcctl', 'stamp', 'clkcmp', 'm4count')) {
    $tp = Join-Path $toolsDir $t
    if (-not (Test-Path -LiteralPath $tp)) { Fail "tools: $t was not built" }
    Log "sha256 orin-native/tools/$t=$(Get-Sha256 $tp)"
  }
  if (-not (Test-Path -LiteralPath $clientBin)) { Fail 'ipc-test/qnx-host-client/qnx-host-client is missing' }
  $clientSha = Get-Sha256 $clientBin
  Log "sha256 ipc-test/qnx-host-client/qnx-host-client=$clientSha m3_pin=$(if ($clientSha -eq $ClientPinM3) { 'match' } else { 'DIFFERS (recorded, not refused)' })"
  foreach ($rel in @('sbin\qvm', 'usr\sbin\tracelogger', 'lib\libtracelog.so.1', 'usr\bin\traceprinter', 'usr\lib\libtraceparser.so.1', 'usr\bin\toybox')) {
    $f = Join-Path $sdpTarget $rel
    if (-not (Test-Path -LiteralPath $f)) { Fail "SDP file missing: aarch64le/$($rel -replace '\\','/')" }
    Log "sha256 sdp aarch64le/$($rel -replace '\\','/')=$(Get-Sha256 $f) (opaque hash only)"
  }

  # 5. Stage.
  New-Item -ItemType Directory -Force -Path $hostDir | Out-Null
  Copy-Item -LiteralPath (Join-Path $canonHost 'local') -Destination (Join-Path $hostDir 'local') -Recurse
  $snip = Join-Path $hostDir 'local\snippets'
  if (-not (Test-Path -LiteralPath $snip)) { Fail 'the copied local/ has no snippets directory' }
  Write-Lf (Join-Path $snip 'post_start.custom') (Read-Text (Join-Path $scriptDir 'post_start-m4tcg.custom'))

  $dfPath = Join-Path $snip 'data_files.custom'
  $dfWant = "[perms=555] hypervisor/qnx-host-client=$repoFwd/ipc-test/qnx-host-client/qnx-host-client"
  if (-not (Test-Path -LiteralPath $dfPath)) { Fail 'data_files.custom is missing from the copied local/snippets' }
  $df = (Read-Text $dfPath).Replace("`r`n", "`n").Trim()
  if ($df -ne $dfWant) { Fail "data_files.custom is not exactly the canonical client line: '$df'" }

  # m4-g2.conf: the stripped g2-m3.conf with its load line put back, equal to the as-run printf text.
  $postLines = (Read-Text $asrunPost).Replace("`r`n", "`n").Split("`n")
  $hits = @($postLines | Where-Object { $_.StartsWith("printf 'system mkqnximage-guest") })
  if ($hits.Count -ne 1) { Fail "post_startup.sh has $($hits.Count) printf 'system mkqnximage-guest lines, expected 1" }
  $s = $hits[0].Substring("printf '".Length)
  $k = $s.IndexOf("'")
  if ($k -lt 0) { Fail 'the as-run printf has no closing quote' }
  $asrun = $s.Substring(0, $k).Replace('\n', "`n")
  if ($asrun.Contains('\')) { Fail 'the as-run printf has an escape other than \n' }
  $confLines = New-Object System.Collections.Generic.List[string]
  foreach ($l in (Read-Text $confSrc).Replace("`r`n", "`n").Split("`n")) {
    if ($l -match '^\s*(#|$)') { continue }
    if ($l -eq 'load /proc/boot/guest-ifs.bin') { $l = 'load /data/hypervisor/guest/ifs.bin' }
    $confLines.Add($l)
  }
  $confText = ($confLines -join "`n") + "`n"
  if ($confText -ne $asrun) { Fail 'm4-g2.conf (stripped g2-m3.conf, load line restored) is not the as-run configuration text' }
  $confPath = Join-Path $stageDir 'm4-g2.conf'
  Write-Lf $confPath $confText
  Log 'check m4-g2.conf equals the as-run printf text: ok'

  foreach ($i in 1..4) {
    $src = Join-Path $fixDir "m4fix-$i.txt"
    if (-not (Test-Path -LiteralPath $src)) { Fail "fixture m4fix-$i.txt is missing" }
    Write-Lf (Join-Path $stageDir "m4fix-$i.txt") (Read-Text $src)
  }

  $guestMd5  = Get-Md5 (Join-Path $guestCopy 'output\ifs.bin')
  $diskMd5   = Get-Md5 (Join-Path $guestCopy 'output\disk-qvm')
  $guestSha  = Get-Sha256 (Join-Path $guestCopy 'output\ifs.bin')
  $diskSha   = Get-Sha256 (Join-Path $guestCopy 'output\disk-qvm')
  $confMd5   = Get-Md5 $confPath
  $confSha   = Get-Sha256 $confPath

  $tpl = (Read-Text $kshTemplate).Replace("`r`n", "`n")
  $kept = New-Object System.Collections.Generic.List[string]
  foreach ($l in $tpl.Split("`n")) { if (-not $l.StartsWith('##')) { $kept.Add($l) } }
  $ksh = $kept -join "`n"
  $subs = [ordered]@{
    '@RUNG@' = "tcg-$Variant"; '@MODE@' = $mode; '@P@' = '2'; '@CPUS@' = '0 1'; '@RATES@' = '0'; '@IO_BOUND@' = '600'
    '@B@' = '/system/bin'; '@X@' = '/system/bin'
    '@GUEST_IFS@' = '/data/hypervisor/guest/ifs.bin'; '@GUEST_DISK@' = '/data/hypervisor/guest/disk-qvm'
    '@CONF@' = '/system/bin/m4-g2.conf'; '@CLIENT@' = '/data/hypervisor/qnx-host-client'
    '@STARTUP_LINE@' = 'tcg-profile'; '@A@' = '0'
    '@GUEST_SHA256@' = $guestSha; '@DISK_SHA256@' = $diskSha; '@CONF_SHA256@' = $confSha; '@CLIENT_SHA256@' = $clientSha
    '@GUEST_MD5@' = $guestMd5; '@DISK_MD5@' = $diskMd5; '@CONF_MD5@' = $confMd5
    '@ITERS@' = '15'; '@IPC_BOUND@' = '600'; '@BANNER_BOUND@' = '600'; '@GRACE@' = "$Grace"; '@GRACE_WAIT@' = "$($Grace + 10)"
    '@KIND@' = $kind; '@TL_ARGS@' = $tlArgs; '@TL_BOUND@' = '797'; '@TRACE_NEED_MB@' = "$traceNeed"
    '@FMT_NEED@' = "$fmtNeed"; '@CNT_NEED@' = "$cntNeed"
    '@TP_BOUND@' = '1800'; '@CNT_BOUND@' = '900'; '@HASH_BOUND@' = '120'
    '@CNT_OUT@' = $cntOut; '@FORMS@' = $forms
    '@SEND_V@' = '1800'; '@SEND_T_V@' = '1795'; '@SEND_C@' = '1800'; '@SEND_T_C@' = '1795'
    '@TRANSPORT@' = 'console'
    '@FIX@' = '/system/bin/m4fix-1.txt /system/bin/m4fix-2.txt /system/bin/m4fix-3.txt /system/bin/m4fix-4.txt'
  }
  foreach ($key in $subs.Keys) { $ksh = $ksh.Replace($key, [string]$subs[$key]) }
  $left = [regex]::Matches($ksh, '@[A-Z0-9_]+@')
  if ($left.Count -gt 0) { Fail "host script: marker $($left[0].Value) survived substitution" }
  $kshPath = Join-Path $stageDir 'm4-host.ksh'
  Write-Lf $kshPath $ksh
  Log "sha256 staged m4-host.ksh=$(Get-Sha256 $kshPath)"

  $r = Invoke-PythonBounded 'kshcheck-selftest' @(($parser -replace '\\','/'), 'kshcheck', '--selftest') $PythonBoundSec
  if ($r.Killed -or $r.Code -ne 0) { Fail 'kshcheck --selftest failed' }
  $r = Invoke-PythonBounded 'kshcheck' @(($parser -replace '\\','/'), 'kshcheck', ($kshPath -replace '\\','/')) $PythonBoundSec
  if ($r.Killed -or $r.Code -ne 0) { Fail 'the generated host script breaks the pipe-free rule (kshcheck)' }
  Log 'check kshcheck --selftest and kshcheck m4-host.ksh: ok'

  $params = [ordered]@{
    image = "tcg-$Variant"; rung = $rung; mode = $mode; variant = $Variant; profile = 'tcg'; p = '2'
    transport = 'console'; iters = '15'; guard_s = '-'; kind = $kind; tl_args = $tlArgs; forms = $forms
    cap_v = "$capV"; cap_c = "$capC"; e3 = $E3; fixtures = 'm4fix-1.txt,m4fix-2.txt,m4fix-3.txt,m4fix-4.txt'; kimg_sha256 = '-'; ksh_sha256 = (Get-Sha256 $kshPath)
  }
  $paramsText = "# m4tcg.params: TCG rehearsal parameters (m4-design.md §11.2); emulated, never a board image's.`n"
  foreach ($key in $params.Keys) { $paramsText += "$key=$($params[$key])`n" }
  Write-Lf (Join-Path $stageDir 'm4tcg.params') $paramsText

  $sysLines = New-Object System.Collections.Generic.List[string]
  $sysLines.Add('bin/traceprinter=usr/bin/traceprinter')
  $sysLines.Add('lib/libtraceparser.so.1=usr/lib/libtraceparser.so.1')
  foreach ($t in @('bwait', 'trcctl', 'stamp', 'clkcmp', 'm4count')) { $sysLines.Add("[perms=555] bin/$t=$repoFwd/orin-native/tools/$t") }
  $sysLines.Add("[perms=555] bin/m4-host.ksh=$repoFwd/qhv/m4tcg/stage-$vName/m4-host.ksh")
  $sysLines.Add("[perms=444] bin/m4-g2.conf=$repoFwd/qhv/m4tcg/stage-$vName/m4-g2.conf")
  foreach ($i in 1..4) { $sysLines.Add("[perms=444] bin/m4fix-$i.txt=$repoFwd/qhv/m4tcg/stage-$vName/m4fix-$i.txt") }
  # The script calls $X/rm with X=/system/bin; the canonical system image has no bin/rm (§14).
  $canonSys = @((Read-Text $canonSysBld).Replace("`r`n", "`n").Split("`n") | ForEach-Object { $_.Trim() })
  if (@($canonSys | Where-Object { $_ -match '(^|\]\s*)/?bin/rm=' }).Count -eq 0) { $sysLines.Add('bin/rm=usr/bin/toybox') }
  $sfPath = Join-Path $snip 'system_files.custom'
  $sf = ''
  if (Test-Path -LiteralPath $sfPath) { $sf = (Read-Text $sfPath).Replace("`r`n", "`n") }
  if ($sf.Length -gt 0 -and -not $sf.EndsWith("`n")) { $sf += "`n" }
  Write-Lf $sfPath ($sf + ($sysLines -join "`n") + "`n")
  foreach ($n in @('data_files.custom', 'ifs_files.custom', 'ifs_start.custom', 'profile.custom')) {
    $p = Join-Path $snip $n
    if (Test-Path -LiteralPath $p) { Write-Lf $p (Read-Text $p) }
  }

  $optPath = Join-Path $hostDir 'local\options'
  $opt = (Read-Text $optPath).Replace("`r`n", "`n")
  $optRe = New-Object System.Text.RegularExpressions.Regex '(?m)^OPT_GUEST=.*$'
  $optHits = $optRe.Matches($opt)
  if ($optHits.Count -ne 1) { Fail "local/options has $($optHits.Count) OPT_GUEST= lines, expected 1" }
  $optNewLine = "OPT_GUEST='$repoFwd/qhv/m4tcg/guest'"
  Log "options: '$($optHits[0].Value)' -> '$optNewLine' (the only line changed)"
  Write-Lf $optPath $optRe.Replace($opt, $optNewLine.Replace('$', '$$'))
  foreach ($f in Get-ChildItem -LiteralPath $snip -File) { Log "sha256 snippet $($f.Name)=$(Get-Sha256 $f.FullName)" }

  # 6. Build.
  $mkArgs = "--type=qemu --arch=aarch64le --hostname=qnx-qhv --qvm=yes --guest=$repoFwd/qhv/m4tcg/guest --build"
  $mkPre  = @('@echo off', "call `"$sdpEnv`" >nul 2>&1", '@echo off', "cd /d `"$hostDir`"")
  $r = Invoke-CmdBounded 'mkqnximage' ($mkPre + @("call mkqnximage $mkArgs < NUL 2>&1", 'exit /b %ERRORLEVEL%')) $hostDir $MkqnximageBoundSec
  if ((-not $r.Killed) -and $r.Code -ne 0 -and $r.Text -match '(?i)ssh-ident|prompt') {
    Log 'mkqnximage failed on a prompt: one rerun with --ssh-ident=none'
    $r = Invoke-CmdBounded 'mkqnximage-sshnone' ($mkPre + @("call mkqnximage $mkArgs --ssh-ident=none < NUL 2>&1", 'exit /b %ERRORLEVEL%')) $hostDir $MkqnximageBoundSec
  }
  if ($r.Killed) { Fail "mkqnximage was killed at $MkqnximageBoundSec s" }
  if ($r.Code -ne 0) { Fail "mkqnximage exit=$($r.Code)" }

  # 7. Text checks (§11.2).
  $bdir = Join-Path $hostDir 'output\build'
  $ps = Read-Text (Join-Path $bdir 'post_startup.sh')
  if (-not $ps.Contains('/system/bin/m4-host.ksh')) { Fail 'post_startup.sh does not run /system/bin/m4-host.ksh' }
  if ($ps.Contains('qvm @')) { Fail "post_startup.sh contains 'qvm @': the canonical snippet leaked in" }
  Log 'check post_startup.sh runs /system/bin/m4-host.ksh and has no "qvm @": ok'
  $sb = @((Read-Text (Join-Path $bdir 'system.build')).Replace("`r`n", "`n").Split("`n") | ForEach-Object { $_.Trim() })
  foreach ($want in ($sysLines + @('bin/tracelogger=usr/sbin/tracelogger'))) {
    if ($sb -notcontains $want) { Fail "system.build lacks the line '$want'" }
  }
  if (@($sb | Where-Object { $_ -match '^lib/libtracelog\.so\.1=' }).Count -lt 1) { Fail 'system.build lacks lib/libtracelog.so.1' }
  Log 'check system.build has every added line, bin/tracelogger and lib/libtracelog.so.1: ok'
  $ib = @((Read-Text (Join-Path $bdir 'ifs.build')).Replace("`r`n", "`n").Split("`n") | ForEach-Object { $_.Trim() })
  foreach ($tool in @('md5sum', 'cksum', 'wc', 'cp', 'cmp', 'rm', 'head', 'tail', 'grep', 'cat', 'qvm', 'qvm-check', 'slog2info', 'devb-loopback')) {
    $inSys = @($sb | Where-Object { $_ -match ('(^|\]\s*)/?bin/' + [regex]::Escape($tool) + '=') }).Count -gt 0
    $inIfs = @($ib | Where-Object { $_ -match ('^(\[[^\]]*\]\s*)?(bin/)?' + [regex]::Escape($tool) + '(=|$)') }).Count -gt 0
    if (-not ($inSys -or $inIfs)) { Fail "neither system.build nor ifs.build provides $tool" }
    Log "check $tool provided by $(if ($inSys) { 'system.build' } else { 'ifs.build' }): ok"
  }
  if (-not (($ib -join "`n") -match '(?m)^[^#\n]*procnto-smp-instr')) { Fail 'ifs.build does not boot procnto-smp-instr' }
  $db = (Read-Text (Join-Path $bdir 'data.build')).Replace("`r`n", "`n").Split("`n")
  foreach ($gname in @('ifs.bin', 'disk-qvm')) {
    $want = "$repoFwd/qhv/m4tcg/guest/output/$gname"
    $srcs = @()
    foreach ($l in $db) {
      $m = [regex]::Match($l, '^\s*(?:\[[^\]]*\]\s*)?/?hypervisor/guest/' + [regex]::Escape($gname) + '\s*=\s*(.*?)\s*$')
      if ($m.Success) { $srcs += $m.Groups[1].Value }
    }
    if ($srcs.Count -eq 0) { Fail "data.build names no source for hypervisor/guest/$gname" }
    foreach ($s2 in $srcs) { if ($s2 -ne $want) { Fail "data.build: hypervisor/guest/$gname=$s2 (want $want)" } }
    Log "check data.build hypervisor/guest/$gname=${want}: ok"
  }
  foreach ($o in @('ifs.bin', 'disk-qemu')) {
    if (-not (Test-Path -LiteralPath (Join-Path $hostDir "output\$o"))) { Fail "output/$o was not produced" }
  }

  # 8. Hashes after.
  Test-GuestCopy 'post'
  Test-Canonical 'post'
  $vi = Get-Sha256 (Join-Path $hostDir 'output\ifs.bin')
  $vd = Get-Sha256 (Join-Path $hostDir 'output\disk-qemu')
  [System.IO.File]::WriteAllText((Join-Path $hostDir 'output\M4TCG-SHA256SUMS'), "$vi *ifs.bin`n$vd *disk-qemu`n", $utf8NoBom)
  Log "variant sha256 ifs.bin=$vi"
  Log "variant sha256 disk-qemu=$vd"
  Log "BUILD_OK variant=$Variant tag=$(if ($Tag) { $Tag } else { 'none' })"
  $exitCode = 0
} catch {
  if ("$_" -ne 'M4TCG-FAIL') {
    try { Log "FAIL: exception: $_" } catch { Write-Host "FAIL: exception: $_" }
  }
  $exitCode = 1
}
exit $exitCode
