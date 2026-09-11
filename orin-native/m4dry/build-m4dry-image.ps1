<#
.SYNOPSIS
  Build one variant QHV host image for the Phase 3b checklist 7b dry run: the
  M4 trace recipe inside a Windows-TCG QHV host.

.DESCRIPTION
  Implements results/orin-native-port/20260909T1100Z/m4-dryrun-design.md,
  section 5.5 (revision 2). The variant is a REBUILT host IFS and disk that
  carries the byte-identical guest IFS and guest disk. It is not the canonical
  host image, and nothing it produces feeds the Phase-4 twin diff.

  It writes only under qhv/m4dry/ (git-ignored through /qhv/) and the tool
  binaries in orin-native/tools/ (git-ignored). It never runs
  scripts/build-qhv.bat, never points mkqnximage at qhv/host or qhv/guest, and
  never deletes a directory: a stale directory is renamed by the owner. The
  canonical images are only read and hashed, before and after the build.

  Steps, numbered as the design's section 5.5:
    1. variant parameters (@W2_K@, @TRACE_SET@, @SET_LINES@, @W1_SECS@, @GRACE@)
    2. canonical checks: path refusal, qhv/host/output/SHA256SUMS, guest pins
    3. guest copy: qhv/guest -> run/guest.partial -> run/guest, then its pins
    4. tools: make bwait clkcmp trcctl in the SDP environment; client sha256
    5. stage run/host-<variant>/local, the host script and the awk (LF, no BOM)
    6. mkqnximage from run/host-<variant>, killed at 1800 s; one rerun with
       --ssh-ident=none if it failed on a prompt
    7. check the generated text build files (our own build output, text only)
    8. hashes after: the guest copy and the canonical images; M4DRY-SHA256SUMS
    9. everything above recorded in qhv/m4dry/build-<variant>.log
  Native commands run from a generated .cmd file under cmd /c, started with
  Start-Process so that the bound can kill the whole tree (taskkill /T).
  It exits 0 only when every check passed, and stops at the first failure with
  "FAIL: <what>".

  Licence (NC QDL v7): SDP files are handled as opaque files only: copied into
  our own image by mkqnximage and hashed. Nothing QNX-shipped is inspected.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File orin-native\m4dry\build-m4dry-image.ps1
  The 'plan' variant: exactly the plan's W2 flags, default qvm trace settings.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File orin-native\m4dry\build-m4dry-image.ps1 -Variant vtwfe
  Adds 'set trace-vtimer on' and 'set trace-wfe on' to the qvm configuration.
#>
param(
  [ValidateSet('plan','k64','vtwfe')][string]$Variant = 'plan',
  [ValidateRange(1,3600)][int]$W1Secs = 60,
  [ValidateRange(1,3600)][int]$Grace = 150
)

$ErrorActionPreference = 'Stop'

# Pins (design sections 4.3 and 5.5). Values only: the files they identify are
# QNX-derived and stay out of git.
$GuestIfsPin  = '968029316b940f53580228f44e393877e032e251d78f3c752600cae726a7cf4f'
$GuestDiskPin = 'cf5b06d0b3cb524201c71440fdda42a18d2636d45938acd8ec95cfa21314216b'
$ClientPinM3  = '52cb4dcad5a3632f88092289ef68668cc1fc604f150f3e2f8b9f31dc82caa7eb'
$MakeBoundSec       = 600
$MkqnximageBoundSec = 1800

$scriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot   = [System.IO.Path]::GetFullPath((Join-Path $scriptDir '..\..')).TrimEnd('\')
$repoFwd    = $repoRoot -replace '\\','/'
$canonHost  = Join-Path $repoRoot 'qhv\host'
$canonGuest = Join-Path $repoRoot 'qhv\guest'
$runRoot    = Join-Path $repoRoot 'qhv\m4dry'
$hostDir    = Join-Path $runRoot "host-$Variant"
$stageDir   = Join-Path $runRoot "stage-$Variant"
$guestCopy  = Join-Path $runRoot 'guest'
$guestPart  = Join-Path $runRoot 'guest.partial'
$buildLog   = Join-Path $runRoot "build-$Variant.log"
$toolsDir   = Join-Path $repoRoot 'orin-native\tools'
$clientBin  = Join-Path $repoRoot 'ipc-test\qnx-host-client\qnx-host-client'
if ($env:QNX_INSTALL_ROOT) { $sdpRoot = $env:QNX_INSTALL_ROOT } else { $sdpRoot = Join-Path $env:USERPROFILE 'qnx800' }
$sdpEnv     = Join-Path $sdpRoot 'qnxsdp-env.bat'
$sdpTarget  = Join-Path $sdpRoot 'target\qnx\aarch64le'
$utf8NoBom  = New-Object System.Text.UTF8Encoding $false

# ---------------------------------------------------------------- helpers

function Log([string]$Line) {
  Write-Host $Line
  [System.IO.File]::AppendAllText($buildLog, $Line + "`n", $utf8NoBom)
}

function Fail([string]$What) {
  Log "FAIL: $What"
  throw 'M4DRY-FAIL'
}

function Read-Text([string]$Path) {
  return [System.IO.File]::ReadAllText($Path)
}

# Every file that enters the image: LF line endings, no BOM (design 5.5 step 5).
function Write-Lf([string]$Path, [string]$Text) {
  [System.IO.File]::WriteAllText($Path, $Text.Replace("`r`n", "`n"), $utf8NoBom)
}

function Get-Sha256([string]$Path) {
  return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Get-Md5([string]$Path) {
  return (Get-FileHash -Algorithm MD5 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Get-NormPath([string]$Path) {
  return ([System.IO.Path]::GetFullPath($Path) -replace '/','\').TrimEnd('\')
}

function Test-Under([string]$Path, [string]$Base) {
  $a = Get-NormPath $Path
  $b = Get-NormPath $Base
  return ($a -ieq $b) -or $a.StartsWith($b + '\', [System.StringComparison]::OrdinalIgnoreCase)
}

# Design 4.3 step 1: never inside a canonical tree, always under qhv/m4dry/.
function Assert-TargetPath([string]$Path) {
  if ((Test-Under $Path $canonHost) -or (Test-Under $Path $canonGuest)) {
    Fail "path_refused $Path (equals or lies under qhv/host or qhv/guest)"
  }
  $a = Get-NormPath $Path
  $b = Get-NormPath $runRoot
  if (-not $a.StartsWith($b + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
    Fail "path_refused $Path (does not lie under qhv/m4dry/)"
  }
}

# Design 4.3 steps 2 and 3. 'pre' calls a mismatch MISMATCH (not the baseline
# this design assumes); 'post' calls it CHANGED (something wrote to it).
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

# Design 4.4 steps 1 and 3: the guest copy against the two pins.
function Test-GuestCopy([string]$When) {
  $gi = Get-Sha256 (Join-Path $guestCopy 'output\ifs.bin')
  $gd = Get-Sha256 (Join-Path $guestCopy 'output\disk-qvm')
  if ($gi -ne $GuestIfsPin -or $gd -ne $GuestDiskPin) {
    Log "guest_copy_$When=MISMATCH ifs.bin=$gi disk-qvm=$gd"
    if ($When -eq 'pre') {
      Fail 'guest_copy_pre=MISMATCH: a stale or damaged qhv/m4dry/guest; the owner renames it and the next build copies afresh'
    }
    Fail 'guest_copy_post=MISMATCH: the variant is invalid; the owner renames qhv/m4dry/guest and the variant directory'
  }
  Log "guest_copy_$When=ok ifs.bin=$gi disk-qvm=$gd"
}

# Run generated cmd lines, bounded. Output goes to the stage directory and is
# appended to the build log.
function Invoke-CmdBounded([string]$Tag, [string[]]$CmdLines, [string]$WorkDir, [int]$Seconds) {
  $cmdFile = Join-Path $stageDir "$Tag.cmd"
  $outFile = Join-Path $stageDir "$Tag.out.log"
  $errFile = Join-Path $stageDir "$Tag.err.log"
  [System.IO.File]::WriteAllText($cmdFile, (($CmdLines -join "`r`n") + "`r`n"), (New-Object System.Text.ASCIIEncoding))
  Log "run $Tag bound_s=$Seconds workdir=$WorkDir"
  foreach ($l in $CmdLines) { Log "  | $l" }
  $p = Start-Process -FilePath $env:ComSpec -ArgumentList @('/d', '/c', ('"' + $cmdFile + '"')) `
         -WorkingDirectory $WorkDir -NoNewWindow -PassThru `
         -RedirectStandardOutput $outFile -RedirectStandardError $errFile
  $null = $p.Handle   # PS 5.1: without this read, ExitCode can come back empty
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
    "----- $Tag output -----`n" + $text.Replace("`r`n", "`n") + "`n----- end of $Tag output -----`n", $utf8NoBom)
  $codeText = 'none'
  if ($null -ne $code) { $codeText = "$code" }
  Log "run $Tag exit=$codeText killed=$([int]$killed)"
  return [pscustomobject]@{ Code = $code; Killed = $killed; Text = $text }
}

# ---------------------------------------------------------------- main

$exitCode = 1
try {
  New-Item -ItemType Directory -Force -Path $runRoot | Out-Null
  Log ''
  Log ('===== build-m4dry-image.ps1 start utc=' + (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') + ' =====')
  Log "variant=$Variant w1_secs=$W1Secs grace=$Grace image=rebuilt-host guest=byte-identical"
  Log "repo=$repoRoot sdp=$sdpRoot"

  # 1. Variant parameters.
  $w2k = ''
  $traceSet = 'defaults'
  $setLines = ''
  if ($Variant -eq 'k64') { $w2k = '64' }
  if ($Variant -eq 'vtwfe') {
    $traceSet = 'vtimer-wfe'
    # Literal backslash-n: it lands inside the host script's printf format.
    $setLines = 'set trace-vtimer on\nset trace-wfe on\n'
  }
  $buildUtc = (Get-Date).ToUniversalTime().ToString("yyyyMMdd'T'HHmmss'Z'")
  Log "params W2_K='$w2k' TRACE_SET=$traceSet SET_LINES='$setLines' BUILD_UTC=$buildUtc"

  # 2. Canonical checks.
  foreach ($d in @($hostDir, $stageDir, $guestCopy, $guestPart)) { Assert-TargetPath $d }
  if ((Test-Path -LiteralPath $hostDir) -and (@(Get-ChildItem -LiteralPath $hostDir -Force).Count -gt 0)) {
    Fail "host_dir_not_empty $hostDir (the owner renames it; no script deletes a directory)"
  }
  if (-not (Test-Path -LiteralPath $sdpEnv)) { Fail "no SDP environment script at $sdpEnv" }
  Test-Canonical 'pre'

  # 3. The guest copy.
  if (Test-Path -LiteralPath $guestPart) {
    Fail 'guest_copy refused: qhv/m4dry/guest.partial exists (an earlier copy was interrupted; the owner renames it)'
  }
  if (Test-Path -LiteralPath $guestCopy) {
    Log 'guest_copy=existing (a completed earlier copy)'
  } else {
    Copy-Item -LiteralPath $canonGuest -Destination $guestPart -Recurse
    Rename-Item -LiteralPath $guestPart -NewName 'guest'
    Log 'guest_copy=fresh (qhv/guest -> qhv/m4dry/guest.partial -> qhv/m4dry/guest)'
  }
  Test-GuestCopy 'pre'

  # 4. Tools, in the SDP environment.
  New-Item -ItemType Directory -Force -Path $stageDir | Out-Null
  $r = Invoke-CmdBounded 'make-tools' @(
    '@echo off',
    "call `"$sdpEnv`" >nul 2>&1",
    '@echo off',
    "make -C `"$repoFwd/orin-native/tools`" bwait clkcmp trcctl 2>&1",
    'exit /b %ERRORLEVEL%'
  ) $repoRoot $MakeBoundSec
  if ($r.Killed -or $r.Code -ne 0) { Fail 'tools: make bwait clkcmp trcctl failed' }
  foreach ($t in @('bwait', 'clkcmp', 'trcctl')) {
    $tp = Join-Path $toolsDir $t
    if (-not (Test-Path -LiteralPath $tp)) { Fail "tools: $t was not built" }
    Log "sha256 orin-native/tools/$t=$(Get-Sha256 $tp)"
  }
  if (-not (Test-Path -LiteralPath $clientBin)) { Fail 'ipc-test/qnx-host-client/qnx-host-client is missing' }
  $clientSha = Get-Sha256 $clientBin
  if ($clientSha -eq $ClientPinM3) {
    Log "sha256 ipc-test/qnx-host-client/qnx-host-client=$clientSha m3_pin=match"
  } else {
    Log "sha256 ipc-test/qnx-host-client/qnx-host-client=$clientSha m3_pin=DIFFERS ($ClientPinM3; recorded, not refused)"
  }
  foreach ($rel in @('sbin\qvm', 'usr\sbin\tracelogger', 'lib\libtracelog.so.1', 'usr\bin\traceprinter', 'usr\lib\libtraceparser.so.1')) {
    $f = Join-Path $sdpTarget $rel
    if (-not (Test-Path -LiteralPath $f)) { Fail "SDP file missing: aarch64le/$($rel -replace '\\','/')" }
    Log "sha256 sdp aarch64le/$($rel -replace '\\','/')=$(Get-Sha256 $f) (opaque hash only)"
  }

  # 5. Stage the build directory.
  New-Item -ItemType Directory -Force -Path $hostDir | Out-Null
  Copy-Item -LiteralPath (Join-Path $canonHost 'local') -Destination (Join-Path $hostDir 'local') -Recurse
  $snip = Join-Path $hostDir 'local\snippets'
  if (-not (Test-Path -LiteralPath $snip)) { Fail 'the copied local/ has no snippets directory' }

  Write-Lf (Join-Path $snip 'post_start.custom') (Read-Text (Join-Path $scriptDir 'post_start-m4dry.custom'))

  $dfPath = Join-Path $snip 'data_files.custom'
  $dfWant = "[perms=555] hypervisor/qnx-host-client=$repoFwd/ipc-test/qnx-host-client/qnx-host-client"
  if (-not (Test-Path -LiteralPath $dfPath)) { Fail 'data_files.custom is missing from the copied local/snippets' }
  $df = (Read-Text $dfPath).Replace("`r`n", "`n").Trim()
  if ($df -ne $dfWant) { Fail "data_files.custom is not exactly the canonical client line: '$df'" }

  $sysLines = @(
    'bin/traceprinter=usr/bin/traceprinter',
    'lib/libtraceparser.so.1=usr/lib/libtraceparser.so.1',
    "[perms=555] bin/bwait=$repoFwd/orin-native/tools/bwait",
    "[perms=555] bin/clkcmp=$repoFwd/orin-native/tools/clkcmp",
    "[perms=555] bin/trcctl=$repoFwd/orin-native/tools/trcctl",
    "[perms=555] bin/m4dry-host.ksh=$repoFwd/qhv/m4dry/stage-$Variant/m4dry-host.ksh",
    "[perms=444] bin/m4dry-count.awk=$repoFwd/qhv/m4dry/stage-$Variant/m4dry-count.awk"
  )
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
  $optNewLine = "OPT_GUEST='$repoFwd/qhv/m4dry/guest'"
  Log "options: '$($optHits[0].Value)' -> '$optNewLine' (the only line changed)"
  Write-Lf $optPath $optRe.Replace($opt, $optNewLine.Replace('$', '$$'))

  $guestMd5  = Get-Md5 (Join-Path $guestCopy 'output\ifs.bin')
  $diskMd5   = Get-Md5 (Join-Path $guestCopy 'output\disk-qvm')
  $clientMd5 = Get-Md5 $clientBin
  Log "md5 pins substituted: guest_md5=$guestMd5 disk_md5=$diskMd5 client_md5=$clientMd5"

  $tpl = (Read-Text (Join-Path $scriptDir 'm4dry-host.ksh.in')).Replace("`r`n", "`n")
  $kept = New-Object System.Collections.Generic.List[string]
  foreach ($l in $tpl.Split("`n")) { if (-not $l.StartsWith('##')) { $kept.Add($l) } }
  $ksh = $kept -join "`n"
  $subs = [ordered]@{
    '@VARIANT@'    = $Variant
    '@BUILD_UTC@'  = $buildUtc
    '@TRACE_SET@'  = $traceSet
    '@SET_LINES@'  = $setLines
    '@W2_K@'       = $w2k
    '@W1_SECS@'    = "$W1Secs"
    '@GRACE@'      = "$Grace"
    '@GUEST_MD5@'  = $guestMd5
    '@DISK_MD5@'   = $diskMd5
    '@CLIENT_MD5@' = $clientMd5
  }
  foreach ($k in $subs.Keys) { $ksh = $ksh.Replace($k, [string]$subs[$k]) }
  $left = [regex]::Matches($ksh, '@[A-Z0-9_]+@')
  if ($left.Count -gt 0) { Fail "host script: marker $($left[0].Value) survived substitution" }
  $kshPath = Join-Path $stageDir 'm4dry-host.ksh'
  $awkPath = Join-Path $stageDir 'm4dry-count.awk'
  Write-Lf $kshPath $ksh
  Write-Lf $awkPath (Read-Text (Join-Path $scriptDir 'm4dry-count.awk'))
  foreach ($f in @($kshPath, $awkPath)) { Log "sha256 staged $(Split-Path -Leaf $f)=$(Get-Sha256 $f)" }
  foreach ($f in Get-ChildItem -LiteralPath $snip -File) { Log "sha256 snippet $($f.Name)=$(Get-Sha256 $f.FullName)" }

  # 6. Build.
  $mkArgs = "--type=qemu --arch=aarch64le --hostname=qnx-qhv --qvm=yes --guest=$repoFwd/qhv/m4dry/guest --build"
  $mkPre  = @('@echo off', "call `"$sdpEnv`" >nul 2>&1", '@echo off', "cd /d `"$hostDir`"")
  $r = Invoke-CmdBounded 'mkqnximage' ($mkPre + @("call mkqnximage $mkArgs < NUL 2>&1", 'exit /b %ERRORLEVEL%')) $hostDir $MkqnximageBoundSec
  $sshIdent = 'as-canonical'
  if ((-not $r.Killed) -and $r.Code -ne 0 -and $r.Text -match '(?i)ssh-ident|prompt') {
    Log 'mkqnximage failed on a prompt: one rerun with --ssh-ident=none (design 5.5 step 6)'
    $r = Invoke-CmdBounded 'mkqnximage-sshnone' ($mkPre + @("call mkqnximage $mkArgs --ssh-ident=none < NUL 2>&1", 'exit /b %ERRORLEVEL%')) $hostDir $MkqnximageBoundSec
    $sshIdent = 'none (differs from canonical; the dry run uses no ssh)'
  }
  Log "mkqnximage command: mkqnximage $mkArgs < NUL"
  Log "ssh_ident=$sshIdent"
  if ($r.Killed) { Fail "mkqnximage was killed at $MkqnximageBoundSec s" }
  if ($r.Code -ne 0) { Fail "mkqnximage exit=$($r.Code)" }

  # 7. Check the generated text.
  $bdir = Join-Path $hostDir 'output\build'
  $ps = Read-Text (Join-Path $bdir 'post_startup.sh')
  if (-not $ps.Contains('/system/bin/m4dry-host.ksh')) {
    Fail 'post_startup.sh does not call /system/bin/m4dry-host.ksh (compare output/option_files/ with local/snippets/)'
  }
  if ($ps.Contains('qvm @')) { Fail "post_startup.sh contains 'qvm @': the canonical snippet leaked in" }
  Log 'check post_startup.sh calls /system/bin/m4dry-host.ksh and has no "qvm @": ok'

  $sb = @((Read-Text (Join-Path $bdir 'system.build')).Replace("`r`n", "`n").Split("`n") | ForEach-Object { $_.Trim() })
  foreach ($want in ($sysLines + @('bin/tracelogger=usr/sbin/tracelogger'))) {
    if ($sb -notcontains $want) { Fail "system.build lacks the line '$want'" }
    Log "check system.build has '$want': ok"
  }
  if (@($sb | Where-Object { $_ -match '^lib/libtracelog\.so\.1=' }).Count -lt 1) { Fail 'system.build lacks lib/libtracelog.so.1' }
  Log 'check system.build has lib/libtracelog.so.1: ok'

  $ifsb = Read-Text (Join-Path $bdir 'ifs.build')
  if (-not ($ifsb -match '(?m)^[^#\r\n]*procnto-smp-instr')) { Fail 'ifs.build does not boot procnto-smp-instr' }
  Log 'check ifs.build boots procnto-smp-instr: ok'

  $db = (Read-Text (Join-Path $bdir 'data.build')).Replace("`r`n", "`n").Split("`n")
  foreach ($gname in @('ifs.bin', 'disk-qvm')) {
    $want = "$repoFwd/qhv/m4dry/guest/output/$gname"
    $srcs = @()
    foreach ($l in $db) {
      $m = [regex]::Match($l, '^\s*(?:\[[^\]]*\]\s*)?/?hypervisor/guest/' + [regex]::Escape($gname) + '\s*=\s*(.*?)\s*$')
      if ($m.Success) { $srcs += $m.Groups[1].Value }
    }
    if ($srcs.Count -eq 0) { Fail "data.build names no source for hypervisor/guest/$gname" }
    foreach ($s in $srcs) {
      if ($s -ne $want) { Fail "data.build: hypervisor/guest/$gname=$s (want $want)" }
    }
    Log "check data.build hypervisor/guest/$gname=$want (sources=$($srcs.Count)): ok"
  }
  foreach ($o in @('ifs.bin', 'disk-qemu')) {
    if (-not (Test-Path -LiteralPath (Join-Path $hostDir "output\$o"))) { Fail "output/$o was not produced" }
  }

  # 8. Hashes after.
  Test-GuestCopy 'post'
  Test-Canonical 'post'
  $vi = Get-Sha256 (Join-Path $hostDir 'output\ifs.bin')
  $vd = Get-Sha256 (Join-Path $hostDir 'output\disk-qemu')
  [System.IO.File]::WriteAllText((Join-Path $hostDir 'output\M4DRY-SHA256SUMS'), "$vi *ifs.bin`n$vd *disk-qemu`n", $utf8NoBom)
  Log "variant sha256 ifs.bin=$vi"
  Log "variant sha256 disk-qemu=$vd"
  Log "wrote qhv/m4dry/host-$Variant/output/M4DRY-SHA256SUMS"

  Log "BUILD_OK variant=$Variant"
  $exitCode = 0
} catch {
  if ("$_" -ne 'M4DRY-FAIL') {
    try { Log "FAIL: exception: $_" } catch { Write-Host "FAIL: exception: $_" }
  }
  $exitCode = 1
}
exit $exitCode
