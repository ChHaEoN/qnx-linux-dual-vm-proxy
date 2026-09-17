<#
.SYNOPSIS
  Build one S1-F TCG rehearsal host image: the S1 host script, the Linux payload
  and the S1 tools inside a Windows-TCG QHV host (s1-design.md §4.2, §6.2-§6.4).

.DESCRIPTION
  Implements results/orin-native-port/20260909T1100Z/s1-design.md §4.2's
  build-s1tcg-image.ps1 row (revision 2; the owner took D1-D19 as recommended),
  derived from orin-native/m4/build-m4tcg-image.ps1 with only the design's
  changes. The variant is a REBUILT host IFS and disk. It carries the
  byte-identical canonical guest pair as the canonical host does, the board's
  stock Linux Image, our initrd and the pinned configuration at /data/s1/ (C2:
  the same path the board images use, so the configuration is staged byte for
  byte). It is not the canonical host image, nothing it produces feeds a twin
  diff, and every TCG figure is emulated (§10).

  It writes only under qhv/s1tcg/ (git-ignored through /qhv/) and the tool
  binaries in orin-native/tools/ (git-ignored by name). It never runs
  scripts/build-qhv.bat, never points mkqnximage at qhv/host or qhv/guest, and
  never deletes a directory. The canonical images are only read and hashed,
  before and after the build.

  Variants and modes (§4.2, §5.3, §6.2-§6.4). The mode is inside the image, so it
  is chosen here and launch-s1tcg.ps1 -Mode must name the same one. A variant with
  two modes has no default and refuses a build without -Mode, so an omitted flag
  cannot build T2's image for T1 (a deviation from §6.2 step 1, which omits it);
  a variant with one mode takes it by default:
    lin   -Mode dryrun (T1) or boot (T2), required: the pinned configuration
    hold  -Mode hold: T3, the ten-minute script path with a 64 MiB hold allocation
    q2    -Mode q2: B5's order rehearsed with the canonical QNX guest; only after
          T0 step 7 (D1 keeps the QNX guest, D14's limit in the generator), so it
          needs -D1QnxGuest
    d1    -Mode dryrun or boot, required: TCG diagnostic s1-d1, the logger line
          with debug and verbose added (§3.7); never a pass run
    d2    -Mode boot: TCG diagnostic s1-d2 (I-c), the stock L4T initrd staged at
          /data/s1/initrd.cpio.gz and rdinit=/bin/sh; never a pass run
    j1    -Mode dryrun: T-J1 (revision 3, §15.5 B6 and B8.5), the pinned configuration
          with memcanary-w staged beside memcanary for its --selftest only; no watch
          runs under TCG. Only this variant's tool list, files and params gain
          memcanary-w, so no T1-T3 image changes; never a pass run
  The image directory is qhv/s1tcg/host-<variant>[-<mode>]-<tag>: the mode is
  named when the variant has more than one. -Tag is required and must be new.

  The host script is always the TCG profile make-s1-images.sh --tcg rendered from
  orin-native/startup/s1-host.ksh.in, used unchanged: by default
  orin-native/shim/out/s1/tcg/s1tcg-<variant>/s1-host.ksh, where <variant> is
  lin-dryrun, lin-boot, hold, d1-dryrun, d1-boot, d2, q2 or j1, or -HostScript FILE.
  The template's @BOARD@/@TCG@/@DIAG@/@Q2@ line prefixes are resolved only by the
  generator. Checks: exactly one MODE=<Mode>, PROFILE=tcg and RUNG=tcg-<Variant>
  line; the generator's s1tcg.params beside the script, when present, agrees on
  mode, ksh_sha256 and every payload and tool sha256; no @[A-Z0-9_]+@ survives;
  no line outside a comment calls memcanary asinfo or verify (§3.8, §7.3); every
  item-5 stamp value this build computed (the payload, init and tool sha256s, the
  cmdline sha256 and tcg-profile) occurs in the text; and parse-s1.py kshcheck
  (parse-m4.py's rule, imported) passes.

  Steps:
    1. the variant, its mode and the TCG profile values
    2. canonical checks: path refusal, qhv/host/output/SHA256SUMS, guest pins
    3. inputs: Image pin and header, initrd pin (the manifest's output line
       agrees), init.sh against the manifest's pin, the configuration pin and
       cmdline pin, the variant's configuration derived and gated by
       parse-s1.py conf. -CheckOnly stops here, having written only the build log
       and the gate's command files under qhv/s1tcg/ (its configuration copy is
       removed); it also checks the host script (default or -HostScript) and the SDP files exist
    4. guest copy: qhv/guest -> qhv/s1tcg/guest.partial -> qhv/s1tcg/guest
    5. tools: make bwait stamp s1con memcanary (and memcanary-w for -Variant j1)
       in the SDP environment (not tcu-cat: under QEMU virt 0x0C168000 is not a
       TCU mailbox)
    6. stage host-<name>/local: post_start, data_files and system_files lines,
       s1-host.ksh (TCG profile), s1-g2.conf for q2, s1tcg.params (LF, no BOM);
       kshcheck --selftest, then kshcheck on the script
    7. mkqnximage from host-<name>, killed at 1800 s
    8. text checks of the generated build files (R30: data.build names the payload)
    9. hashes after: the inputs, the guest copy and the canonical images;
       S1TCG-SHA256SUMS
  Exit 0 only when every check passed; it stops at the first failure with
  "FAIL: <what>".

  The stamp values this build computes itself (the $subs table below: payload,
  init, configuration, cmdline and tool sha256s, tcg-profile) are what the host
  script's text is checked against; nothing is substituted into it here. Every
  wait bound, and the q2 grace, is the generator's TCG bound table
  (make-s1-images.sh bounds tcg), so -Grace no longer changes the script.

  Licence (NC QDL v7): SDP files are handled as opaque files only: copied into our
  own image by mkqnximage and hashed. Nothing QNX-shipped is inspected. The Linux
  Image and initrd are private copies (GPLv2, LGPL-2.1) and never committed.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File orin-native\s1\build-s1tcg-image.ps1 -Variant lin -Mode dryrun -Tag t1a
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File orin-native\s1\build-s1tcg-image.ps1 -Variant hold -Tag t3a -CheckOnly
#>
param(
  [ValidateSet('lin','hold','q2','d1','d2','j1')][string]$Variant = 'lin',
  [ValidateSet('','dryrun','boot','hold','q2')][string]$Mode = '',
  [Parameter(Mandatory = $true)][ValidatePattern('^[a-z0-9]{1,16}$')][string]$Tag,
  [string]$HostScript = '',
  [switch]$D1QnxGuest,
  [switch]$CheckOnly,
  [ValidateRange(10, 3600)][int]$Grace = 150
)

$ErrorActionPreference = 'Stop'

$GuestIfsPin    = '434647a7cabfe5a1b503fab6c6309894aceccd03d74bb3882ea81caff22a83bd'
$GuestDiskPin   = '55571618524e6cbc7a691b8109734783b479261a2f97206b71fa75f07ee31477'
$ClientPinM3    = '52cb4dcad5a3632f88092289ef68668cc1fc604f150f3e2f8b9f31dc82caa7eb'
$ImagePin       = 'b844b7cfaafd071a25f1dc91d2ad1d7369008c28ce84b25625efc425825a2120'
$StockInitrdPin = 'f0cdcc61064ff6e9ac99b1c4ff02468dbe9cf0c0e9404cf429524d741f6883f8'
$InitrdPin      = '44e81ea65903e25a66cafe6b35f28776bba1f6ae8082251cc8a988a689495ab6'
$ConfPin        = '85d51359229ea4fa9860de76519a523250e71c5c77666821a07e7f4561196e31'
$CmdlinePin     = 'da47f63ebedf99e1c560e1157ce176d6c56ad2953d040287bf6db8704f337638'
$MakeBoundSec       = 600
$MkqnximageBoundSec = 1800
$PythonBoundSec     = 120

# §4.2 variants. A variant with one mode defaults to it; one with two needs -Mode, because the mode is inside the image.
$VariantModes = @{ 'lin' = @('boot', 'dryrun'); 'hold' = @('hold'); 'q2' = @('q2'); 'd1' = @('boot', 'dryrun'); 'd2' = @('boot'); 'j1' = @('dryrun') }
if (-not $Mode) {
  if ($VariantModes[$Variant].Count -gt 1) {
    Write-Host "FAIL: -Variant $Variant needs -Mode $($VariantModes[$Variant] -join '|'): the mode is inside the image, so there is no default (T1 builds -Mode dryrun, T2 -Mode boot; s1-design.md 6.2-6.3)"
    exit 1
  }
  $Mode = $VariantModes[$Variant][0]
}
if ($VariantModes[$Variant] -notcontains $Mode) {
  Write-Host "FAIL: -Variant $Variant takes -Mode $($VariantModes[$Variant] -join '|'), not $Mode"
  exit 1
}
if ($Variant -eq 'q2' -and -not $D1QnxGuest) {
  Write-Host 'FAIL: -Variant q2 runs only after T0 step 7 (D1 keeps the QNX guest and D14''s limit is in the generator); pass -D1QnxGuest to confirm (s1-design.md 6.1, 6.4)'
  exit 1
}

$scriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot    = [System.IO.Path]::GetFullPath((Join-Path $scriptDir '..\..')).TrimEnd('\')
$repoFwd     = $repoRoot -replace '\\','/'
$canonHost   = Join-Path $repoRoot 'qhv\host'
$canonGuest  = Join-Path $repoRoot 'qhv\guest'
$runRoot     = Join-Path $repoRoot 'qhv\s1tcg'
$vName       = $Variant
if ($VariantModes[$Variant].Count -gt 1) { $vName = "$Variant-$Mode" }
$vName       = "$vName-$Tag"
$hostDir     = Join-Path $runRoot "host-$vName"
$stageDir    = Join-Path $runRoot "stage-$vName"
$guestCopy   = Join-Path $runRoot 'guest'
$guestPart   = Join-Path $runRoot 'guest.partial'
$buildLog    = Join-Path $runRoot "build-$vName.log"
$toolsDir    = Join-Path $repoRoot 'orin-native\tools'
$clientBin   = Join-Path $repoRoot 'ipc-test\qnx-host-client\qnx-host-client'
# make-s1-images.sh --tcg renders the TCG profile to orin-native/shim/out/s1/tcg/s1tcg-<variant>/ by default,
# <variant> being lin-dryrun, lin-boot, hold, d1-dryrun, d1-boot, d2 or q2.
$genVariant  = $Variant
if ($VariantModes[$Variant].Count -gt 1) { $genVariant = "$Variant-$Mode" }
$genDir      = Join-Path $repoRoot ('orin-native\shim\out\s1\tcg\s1tcg-' + $genVariant)
$imageRel    = 'orin-native/s1/out/l4t/Image'
$initrdRel   = 'orin-native/s1/out/initrd.cpio.gz'
$stockRel    = 'orin-native/s1/out/l4t/initrd'
$confSrc     = Join-Path $scriptDir 's1-linux.conf'
$initSrc     = Join-Path $scriptDir 'init.sh'
$manifest    = Join-Path $scriptDir 'initrd.manifest'
$g2Src       = Join-Path $repoRoot 'orin-native\qhv\g2-m3.conf'
$asrunPost   = Join-Path $canonHost 'output\build\post_startup.sh'
$canonSysBld = Join-Path $canonHost 'output\build\system.build'
$parser      = Join-Path $scriptDir 'parse-s1.py'
if ($env:QNX_INSTALL_ROOT) { $sdpRoot = $env:QNX_INSTALL_ROOT } else { $sdpRoot = Join-Path $env:USERPROFILE 'qnx800' }
$sdpEnv      = Join-Path $sdpRoot 'qnxsdp-env.bat'
$sdpTarget   = Join-Path $sdpRoot 'target\qnx\aarch64le'
$utf8NoBom   = New-Object System.Text.UTF8Encoding $false
$latin1      = [System.Text.Encoding]::GetEncoding(28591)

# ---------------------------------------------------------------- helpers (as build-m4tcg-image.ps1)

function Log([string]$Line) {
  Write-Host $Line
  [System.IO.File]::AppendAllText($buildLog, $Line + "`n", $utf8NoBom)
}

function Fail([string]$What) {
  Log "FAIL: $What"
  throw 'S1TCG-FAIL'
}

function Read-Text([string]$Path) { return [System.IO.File]::ReadAllText($Path) }

function Write-Lf([string]$Path, [string]$Text) {
  [System.IO.File]::WriteAllText($Path, $Text.Replace("`r`n", "`n"), $utf8NoBom)
}

function Get-Sha256([string]$Path) { return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant() }
function Get-Md5([string]$Path) { return (Get-FileHash -Algorithm MD5 -LiteralPath $Path).Hash.ToLowerInvariant() }
function Get-NormPath([string]$Path) { return ([System.IO.Path]::GetFullPath($Path) -replace '/','\').TrimEnd('\') }

function Get-BytesSha256([byte[]]$Bytes) {
  $h = [System.Security.Cryptography.SHA256]::Create()
  try { return (-join ($h.ComputeHash($Bytes) | ForEach-Object { $_.ToString('x2') })) } finally { $h.Dispose() }
}

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
    Fail "path_refused $Path (does not lie under qhv/s1tcg/)"
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
    Fail "guest_copy_$When=MISMATCH: the owner renames qhv/s1tcg/guest; the next build copies afresh"
  }
  Log "guest_copy_$When=ok ifs.bin=$gi disk-qvm=$gd"
}

function Test-Pin([string]$Rel, [string]$Want, [string]$When) {
  $p = Join-Path $repoRoot ($Rel -replace '/','\')
  if (-not (Test-Path -LiteralPath $p)) { Fail "input_$When $Rel is missing (D3's copy, or mkcpio.py build)" }
  $got = Get-Sha256 $p
  if ($got -ne $Want) {
    Log "input_$When $Rel sha256=$got MISMATCH (pin: $Want)"
    Fail "input_$When=MISMATCH $Rel"
  }
  Log "input_$When $Rel sha256=$got ok"
  return $p
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
$gateTemp = $null
try {
  New-Item -ItemType Directory -Force -Path $runRoot | Out-Null
  Log ''
  Log ('===== build-s1tcg-image.ps1 start utc=' + (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') + ' =====')
  Log "variant=$Variant mode=$Mode tag=$Tag dir=qhv/s1tcg/host-$vName check_only=$([int][bool]$CheckOnly) image=rebuilt-host guest=byte-identical"

  # 1. The TCG profile (§5.1, §6.2-§6.4).
  $gateMib = @{ 'dryrun' = 596; 'boot' = 596; 'hold' = 660; 'q2' = 1255 }[$Mode]
  $holdMib = 0
  $holdS   = 0
  if ($Mode -eq 'hold') { $holdMib = 64; $holdS = 600 }
  $guestSet = 'linux'
  if ($Mode -eq 'q2') { $guestSet = 'linux,qnx' }
  $initrdSrcRel = $initrdRel
  $initrdWant   = $InitrdPin
  if ($Variant -eq 'd2') { $initrdSrcRel = $stockRel; $initrdWant = $StockInitrdPin }
  Log "profile rung=tcg-$Variant mode=$Mode smp=4 not-a-twin-leg windows='tcg -m 2G' startup=tcg-profile canaries=none gpu_range=none guest_set=$guestSet hold_s=$holdS hold_mib=$holdMib mem_gate_mib=$gateMib initrd_src=$initrdSrcRel diagnostic=$(if ($Variant -eq 'd1' -or $Variant -eq 'd2' -or $Variant -eq 'j1') { 'yes (never a pass run)' } else { 'no' })"

  # 2. Canonical checks.
  foreach ($d in @($hostDir, $stageDir, $guestCopy, $guestPart)) { Assert-TargetPath $d }
  if ((Test-Path -LiteralPath $hostDir) -and (@(Get-ChildItem -LiteralPath $hostDir -Force).Count -gt 0)) {
    Fail "host_dir_not_empty $hostDir (use a new -Tag; no script deletes a directory)"
  }
  if ((Test-Path -LiteralPath $stageDir) -and (@(Get-ChildItem -LiteralPath $stageDir -Force).Count -gt 0)) {
    Fail "stage_dir_not_empty $stageDir (use a new -Tag; no script deletes a directory)"
  }
  if (-not (Test-Path -LiteralPath $sdpEnv)) { Fail "no SDP environment script at $sdpEnv" }
  Test-Canonical 'pre'

  # 3. Inputs.
  $imagePath = Test-Pin $imageRel $ImagePin 'pre'
  $hdr = New-Object byte[] 64
  $fs = [System.IO.File]::OpenRead($imagePath)
  try { $nHdr = $fs.Read($hdr, 0, 64) } finally { $fs.Close() }
  # Our reading of a Linux arm64 Image header (LX booting.html), not a QNX binary.
  if ($nHdr -ne 64 -or $latin1.GetString($hdr, 0, 2) -ne 'MZ' -or $latin1.GetString($hdr, 0x38, 4) -ne 'ARMd') {
    Fail "$imageRel has no MZ at 0 and ARMd at 0x38: not an arm64 Image"
  }
  Log "check $imageRel header MZ@0 ARMd@0x38: ok"
  $initrdPath = Test-Pin $initrdSrcRel $initrdWant 'pre'
  $man = (Read-Text $manifest).Replace("`r`n", "`n")
  $mo = [regex]::Matches($man, '(?m)^output\s+out/initrd\.cpio\.gz\s+([0-9a-f]{64})\s+([0-9a-f]{64})\s*$')
  if ($mo.Count -ne 1) { Fail "initrd.manifest has $($mo.Count) 'output out/initrd.cpio.gz' lines, expected 1" }
  if ($mo[0].Groups[1].Value -ne $InitrdPin) {
    Fail "initrd.manifest pins initrd.cpio.gz to $($mo[0].Groups[1].Value), this script to ${InitrdPin}: re-pin both together"
  }
  $mi = [regex]::Matches($man, '(?m)^file\s+init\s+0755\s+([0-9a-f]{64})\s+local\s+init\.sh\s*$')
  if ($mi.Count -ne 1) { Fail "initrd.manifest has $($mi.Count) 'file init 0755 <sha256> local init.sh' lines, expected 1" }
  $initSha = Get-Sha256 $initSrc
  if ($initSha -ne $mi[0].Groups[1].Value) { Fail "orin-native/s1/init.sh sha256=$initSha differs from initrd.manifest's pin $($mi[0].Groups[1].Value)" }
  Log "check initrd.manifest output pin and init.sh pin ($initSha): ok"

  $confBaseBytes = [System.IO.File]::ReadAllBytes($confSrc)
  $confBaseSha = Get-BytesSha256 $confBaseBytes
  if ($confBaseSha -ne $ConfPin) { Fail "orin-native/s1/s1-linux.conf sha256=$confBaseSha differs from the pin $ConfPin" }
  $confText = $latin1.GetString($confBaseBytes)
  switch ($Variant) {
    'd1' {
      $old = "`nlogger error,fatal,internal,warn,info stderr`n"
      $new = "`nlogger error,fatal,internal,warn,info,debug,verbose stderr`n"
      if (([regex]::Matches($confText, [regex]::Escape($old))).Count -ne 1) { Fail 'd1: the configuration has no single logger line to widen' }
      $confText = $confText.Replace($old, $new)
    }
    'd2' {
      if (([regex]::Matches($confText, [regex]::Escape(' rdinit=/init '))).Count -ne 1) { Fail 'd2: the configuration has no single rdinit=/init to replace' }
      $confText = $confText.Replace(' rdinit=/init ', ' rdinit=/bin/sh ')
    }
  }
  $confBytes = $latin1.GetBytes($confText)
  $confSha = Get-BytesSha256 $confBytes
  $cm = [regex]::Matches($confText, '(?m)^cmdline "([^"]*)"$')
  if ($cm.Count -ne 1) { Fail "the configuration has $($cm.Count) cmdline lines, expected 1" }
  $cmdlineSha = Get-BytesSha256 ($latin1.GetBytes($cm[0].Groups[1].Value))
  if ($Variant -ne 'd2' -and $cmdlineSha -ne $CmdlinePin) { Fail "cmdline sha256=$cmdlineSha differs from the pin $CmdlinePin" }
  $cpuLines = @($confText.Split("`n") | Where-Object { $_ -match '^cpu(\s|$)' })
  $ramLines = @($confText.Split("`n") | Where-Object { $_ -match '^ram\s' })
  if ($cpuLines.Count -lt 1 -or $ramLines.Count -ne 1) { Fail 'the configuration needs at least one cpu line and exactly one ram line' }
  $cpuJoined = $cpuLines -join ';'
  Log "configuration variant=$Variant sha256=$confSha cmdline_sha256=$cmdlineSha pinned=$(if ($confSha -eq $ConfPin) { 'yes' } else { 'no (diagnostic)' }) cpu_lines='$cpuJoined' ram_line='$($ramLines[0])'"

  # -CheckOnly gates a temporary copy under qhv/s1tcg/ (removed below) and keeps its command
  # files there as checkonly-<name>-conf-gate.*, so no stage directory is created.
  $gateName = 'conf-gate'
  if ($CheckOnly) {
    $gateTemp = Join-Path $runRoot "checkonly-$vName.conf"
    Assert-TargetPath $gateTemp
    $gateConf = $gateTemp
    $stageDir = $runRoot
    $gateName = "checkonly-$vName-conf-gate"
  } else {
    New-Item -ItemType Directory -Force -Path $stageDir | Out-Null
    $gateConf = Join-Path $stageDir 's1-linux.conf'
  }
  [System.IO.File]::WriteAllBytes($gateConf, $confBytes)
  if ((Get-Sha256 $gateConf) -ne $confSha) { Fail 'the staged configuration does not hash as derived' }
  $r = Invoke-PythonBounded $gateName @(($parser -replace '\\','/'), 'conf', ($gateConf -replace '\\','/')) $PythonBoundSec
  if ($r.Killed -or $r.Code -ne 0) { Fail "parse-s1.py conf refuses the $Variant configuration (s1-design.md 3.7)" }
  Log "check parse-s1.py conf on the $Variant configuration: ok"

  # The host script is always the generator's TCG rendering: s1-host.ksh.in carries @BOARD@, @TCG@, @DIAG@ and @Q2@
  # line prefixes that only make-s1-images.sh resolves. Without -HostScript, its default output for this variant.
  if (-not $HostScript) {
    $HostScript = Join-Path $genDir 's1-host.ksh'
    if (-not (Test-Path -LiteralPath $HostScript -PathType Leaf)) {
      Fail "no -HostScript, and no orin-native/shim/out/s1/tcg/s1tcg-$genVariant/s1-host.ksh: run 'bash orin-native/startup/make-s1-images.sh --tcg $genVariant' first"
    }
  }
  $hsPath = $null
  if ($HostScript) {
    if (-not (Test-Path -LiteralPath $HostScript -PathType Leaf)) { Fail "-HostScript '$HostScript' does not exist" }
    $hsPath = (Resolve-Path -LiteralPath $HostScript).ProviderPath
    if ((Test-Under $hsPath $canonHost) -or (Test-Under $hsPath $canonGuest)) { Fail "-HostScript lies under a canonical tree: $hsPath" }
    Log "check -HostScript exists outside the canonical trees: ok"
  }
  if ($CheckOnly) {
    Remove-Item -LiteralPath $gateTemp -Force
    $gateTemp = $null
    foreach ($rel in @('sbin\qvm', 'usr\bin\toybox', 'lib\dll\vdev-pl011.so', 'lib\dll\vdev-virtio-console.so')) {
      if (-not (Test-Path -LiteralPath (Join-Path $sdpTarget $rel))) { Fail "SDP file missing: aarch64le/$($rel -replace '\\','/')" }
    }
    Log 'check SDP files present (aarch64le sbin/qvm usr/bin/toybox lib/dll/vdev-pl011.so lib/dll/vdev-virtio-console.so): ok'
    Log "CHECK_ONLY_OK variant=$Variant mode=$Mode tag=$Tag (no copy, no make, no mkqnximage; only this log and qhv/s1tcg/checkonly-$vName-conf-gate.* were written)"
    $exitCode = 0
    throw 'S1TCG-CHECKONLY-DONE'
  }

  # 4. The guest copy.
  if (Test-Path -LiteralPath $guestPart) { Fail 'guest_copy refused: qhv/s1tcg/guest.partial exists (an interrupted copy; the owner renames it)' }
  if (Test-Path -LiteralPath $guestCopy) {
    Log 'guest_copy=existing (a completed earlier copy)'
  } else {
    Copy-Item -LiteralPath $canonGuest -Destination $guestPart -Recurse
    Rename-Item -LiteralPath $guestPart -NewName 'guest'
    Log 'guest_copy=fresh (qhv/guest -> qhv/s1tcg/guest.partial -> qhv/s1tcg/guest)'
  }
  Test-GuestCopy 'pre'

  # 5. Tools.
  $toolNames = @('bwait', 'stamp', 's1con', 'memcanary')
  # §15.5 B6: the watcher only in -Variant j1, so no other variant's tool list, files or params change.
  if ($Variant -eq 'j1') { $toolNames += 'memcanary-w' }
  $r = Invoke-CmdBounded 'make-tools' @(
    '@echo off',
    "call `"$sdpEnv`" >nul 2>&1",
    '@echo off',
    "make -C `"$repoFwd/orin-native/tools`" $($toolNames -join ' ') 2>&1",
    'exit /b %ERRORLEVEL%'
  ) $repoRoot $MakeBoundSec
  if ($r.Killed -or $r.Code -ne 0) { Fail "tools: make $($toolNames -join ' ') failed" }
  $toolSha = @{}
  foreach ($t in $toolNames) {
    $tp = Join-Path $toolsDir $t
    if (-not (Test-Path -LiteralPath $tp)) { Fail "tools: $t was not built" }
    $toolSha[$t] = Get-Sha256 $tp
    Log "sha256 orin-native/tools/$t=$($toolSha[$t])"
  }
  if (-not (Test-Path -LiteralPath $clientBin)) { Fail 'ipc-test/qnx-host-client/qnx-host-client is missing' }
  $clientSha = Get-Sha256 $clientBin
  Log "sha256 ipc-test/qnx-host-client/qnx-host-client=$clientSha m3_pin=$(if ($clientSha -eq $ClientPinM3) { 'match' } else { 'DIFFERS (recorded, not refused)' })"
  foreach ($rel in @('sbin\qvm', 'usr\bin\toybox', 'lib\dll\vdev-pl011.so', 'lib\dll\vdev-virtio-console.so')) {
    $f = Join-Path $sdpTarget $rel
    if (-not (Test-Path -LiteralPath $f)) { Fail "SDP file missing: aarch64le/$($rel -replace '\\','/')" }
    Log "sha256 sdp aarch64le/$($rel -replace '\\','/')=$(Get-Sha256 $f) (opaque hash only)"
  }

  # 6. Stage.
  New-Item -ItemType Directory -Force -Path $hostDir | Out-Null
  Copy-Item -LiteralPath (Join-Path $canonHost 'local') -Destination (Join-Path $hostDir 'local') -Recurse
  $snip = Join-Path $hostDir 'local\snippets'
  if (-not (Test-Path -LiteralPath $snip)) { Fail 'the copied local/ has no snippets directory' }
  Write-Lf (Join-Path $snip 'post_start.custom') (Read-Text (Join-Path $scriptDir 'post_start-s1tcg.custom'))

  # data_files.custom: the canonical client line, then the payload at /data/s1/ (C2).
  $dfPath = Join-Path $snip 'data_files.custom'
  $dfWant = "[perms=555] hypervisor/qnx-host-client=$repoFwd/ipc-test/qnx-host-client/qnx-host-client"
  if (-not (Test-Path -LiteralPath $dfPath)) { Fail 'data_files.custom is missing from the copied local/snippets' }
  $df = (Read-Text $dfPath).Replace("`r`n", "`n").Trim()
  if ($df -ne $dfWant) { Fail "data_files.custom is not exactly the canonical client line: '$df'" }
  $confStagedRel = "qhv/s1tcg/stage-$vName/s1-linux.conf"
  $dataLines = @(
    "[perms=444] s1/Image=$repoFwd/$imageRel",
    "[perms=444] s1/initrd.cpio.gz=$repoFwd/$initrdSrcRel",
    "[perms=444] s1/s1-linux.conf=$repoFwd/$confStagedRel"
  )
  Write-Lf $dfPath ($dfWant + "`n" + ($dataLines -join "`n") + "`n")

  $imageMd5  = Get-Md5 $imagePath
  $initrdMd5 = Get-Md5 $initrdPath
  $confMd5   = Get-Md5 $gateConf
  $guestSha  = Get-Sha256 (Join-Path $guestCopy 'output\ifs.bin')
  $diskSha   = Get-Sha256 (Join-Path $guestCopy 'output\disk-qvm')
  $guestMd5  = Get-Md5 (Join-Path $guestCopy 'output\ifs.bin')
  $diskMd5   = Get-Md5 (Join-Path $guestCopy 'output\disk-qvm')

  # q2 only: s1-g2.conf, the stripped g2-m3.conf with its load line put back, equal to the as-run text (M4's rule).
  $qconf = 'none'; $qconfSha = 'none'; $qconfMd5 = 'none'
  if ($Mode -eq 'q2') {
    $postLines = (Read-Text $asrunPost).Replace("`r`n", "`n").Split("`n")
    $hits = @($postLines | Where-Object { $_.StartsWith("printf 'system mkqnximage-guest") })
    if ($hits.Count -ne 1) { Fail "post_startup.sh has $($hits.Count) printf 'system mkqnximage-guest lines, expected 1" }
    $s = $hits[0].Substring("printf '".Length)
    $k = $s.IndexOf("'")
    if ($k -lt 0) { Fail 'the as-run printf has no closing quote' }
    $asrun = $s.Substring(0, $k).Replace('\n', "`n")
    if ($asrun.Contains('\')) { Fail 'the as-run printf has an escape other than \n' }
    $g2Lines = New-Object System.Collections.Generic.List[string]
    foreach ($l in (Read-Text $g2Src).Replace("`r`n", "`n").Split("`n")) {
      if ($l -match '^\s*(#|$)') { continue }
      if ($l -eq 'load /proc/boot/guest-ifs.bin') { $l = 'load /data/hypervisor/guest/ifs.bin' }
      $g2Lines.Add($l)
    }
    $g2Text = ($g2Lines -join "`n") + "`n"
    if ($g2Text -ne $asrun) { Fail 's1-g2.conf (stripped g2-m3.conf, load line restored) is not the as-run configuration text' }
    $g2Path = Join-Path $stageDir 's1-g2.conf'
    Write-Lf $g2Path $g2Text
    $qconf = '/system/bin/s1-g2.conf'; $qconfSha = Get-Sha256 $g2Path; $qconfMd5 = Get-Md5 $g2Path
    Log 'check s1-g2.conf equals the as-run printf text: ok'
  }

  $subs = [ordered]@{
    '@PROFILE@' = 'tcg'; '@RUNG@' = "tcg-$Variant"; '@MODE@' = $Mode; '@P@' = '4'; '@SMP@' = '4'; '@CPUS@' = '0 1 2 3'
    '@B@' = '/system/bin'; '@X@' = '/system/bin'; '@S1DIR@' = '/data/s1'
    '@IMAGE@' = '/data/s1/Image'; '@INITRD@' = '/data/s1/initrd.cpio.gz'; '@CONF@' = '/data/s1/s1-linux.conf'
    '@IMAGE_SHA256@' = (Get-Sha256 $imagePath); '@INITRD_SHA256@' = (Get-Sha256 $initrdPath); '@CONF_SHA256@' = $confSha
    '@CMDLINE_SHA256@' = $cmdlineSha; '@INIT_SHA256@' = $initSha
    '@S1CON_SHA256@' = $toolSha['s1con']; '@MEMCANARY_SHA256@' = $toolSha['memcanary']
    '@STAMP_SHA256@' = $toolSha['stamp']; '@BWAIT_SHA256@' = $toolSha['bwait']
    '@IMAGE_MD5@' = $imageMd5; '@INITRD_MD5@' = $initrdMd5; '@CONF_MD5@' = $confMd5
    '@STARTUP_SHA256@' = 'tcg-profile'; '@STARTUP_LINE@' = 'tcg-profile'; '@A@' = '0'
    '@CPU_LINES@' = $cpuJoined; '@RAM_LINE@' = $ramLines[0]; '@WINDOWS@' = 'tcg -m 2G'
    '@CANARIES@' = 'none'; '@GPU_RANGE@' = 'none'; '@GUEST_SET@' = $guestSet
    '@HOLD_S@' = "$holdS"; '@GUARD_S@' = 'none'; '@MEM_GATE_MIB@' = "$gateMib"; '@HOLD_MIB@' = "$holdMib"
    '@HB_COUNT@' = '10'; '@HB_SECS@' = '60'; '@HOLD_SECS@' = '600'; '@FDT_DUMP@' = '/dev/shmem/s1-fdt.dtb'
    '@DRYRUN_BOUND@' = '60'; '@L_KERNEL_BOUND@' = '900'; '@I_READY_BOUND@' = '1800'; '@SHELL_OK_BOUND@' = '120'
    '@END_OK_BOUND@' = '300'; '@SETTLE_S@' = '2'; '@HOLD_FILL_BOUND@' = '300'; '@HOLD_VERIFY_BOUND@' = '300'
    '@HASH_BOUND@' = '300'; '@IO_BOUND@' = '600'; '@QVMCHECK_BOUND@' = '60'; '@TEARDOWN_KILL_S@' = '15'
    '@HEAD_CAP@' = '2048'; '@TAIL_CAP@' = '1024'; '@TRANSPORT@' = 'console'
    '@GUEST_IFS@' = '/data/hypervisor/guest/ifs.bin'; '@GUEST_DISK@' = '/data/hypervisor/guest/disk-qvm'
    '@CLIENT@' = '/data/hypervisor/qnx-host-client'; '@QCONF@' = $qconf
    '@GUEST_SHA256@' = $guestSha; '@DISK_SHA256@' = $diskSha; '@CLIENT_SHA256@' = $clientSha; '@QCONF_SHA256@' = $qconfSha
    '@GUEST_MD5@' = $guestMd5; '@DISK_MD5@' = $diskMd5; '@QCONF_MD5@' = $qconfMd5
    '@ITERS@' = '15'; '@IPC_BOUND@' = '600'; '@BANNER_BOUND@' = '600'; '@GRACE@' = "$Grace"; '@GRACE_WAIT@' = "$($Grace + 10)"
  }
  $ksh = (Read-Text $hsPath).Replace("`r`n", "`n")
  $kshSource = "generator:$((Get-NormPath $hsPath).Replace((Get-NormPath $repoRoot) + '\', '') -replace '\\','/')"
  # The mode is inside the script. Its MODE, PROFILE and RUNG lines must be this build's, because launch-s1tcg.ps1
  # checks -Mode only against s1tcg.params, so a script rendered for another mode would pass there unnoticed.
  $kshLines = $ksh.Split("`n")
  foreach ($want in @("MODE=$Mode", 'PROFILE=tcg', "RUNG=tcg-$Variant")) {
    $nLines = @($kshLines | Where-Object { $_ -ceq $want }).Count
    if ($nLines -ne 1) { Fail "host script has $nLines lines '$want', expected 1: it was rendered for another variant or mode" }
  }
  # The generator's s1tcg.params beside the script, when present, must agree on the mode, the script and every stamp.
  $genParams = Join-Path (Split-Path -Parent $hsPath) 's1tcg.params'
  $gp = @{}
  if (Test-Path -LiteralPath $genParams) {
    foreach ($l in (Read-Text $genParams).Replace("`r`n", "`n").Split("`n")) {
      if ($l -match '^([a-z0-9_]+)=(.*)$') { $gp[$Matches[1]] = $Matches[2] }
    }
    $pairs = @(@('mode', $Mode), @('ksh_sha256', (Get-Sha256 $hsPath)), @('conf_sha256', $confSha),
               @('cmdline_sha256', $cmdlineSha), @('image_sha256', [string]$subs['@IMAGE_SHA256@']),
               @('initrd_sha256', [string]$subs['@INITRD_SHA256@']), @('init_sha256', $initSha),
               @('s1con_sha256', $toolSha['s1con']), @('memcanary_sha256', $toolSha['memcanary']),
               @('stamp_sha256', $toolSha['stamp']), @('bwait_sha256', $toolSha['bwait']))
    if ($Variant -eq 'j1') { $pairs += ,@('memcanary_w_sha256', $toolSha['memcanary-w']) }
    foreach ($kv in $pairs) {
      if ($gp[$kv[0]] -ne $kv[1]) { Fail "the generator's s1tcg.params has $($kv[0])=$($gp[$kv[0]]), this build computed $($kv[1])" }
    }
    Log "check the generator's s1tcg.params agrees on the mode, the script and every payload and tool sha256: ok"
  } else {
    Log "note: no s1tcg.params beside -HostScript; only the script text is checked"
  }
  $left = [regex]::Matches($ksh, '@[A-Z0-9_]+@')
  if ($left.Count -gt 0) { Fail "host script: marker $($left[0].Value) survived substitution" }
  # §3.8, §7.3: a TCG script never calls memcanary asinfo or verify.
  foreach ($l in $ksh.Split("`n")) {
    if ($l -match '^\s*#') { continue }
    if ($l -match 'memcanary["'']?\s+["'']?(asinfo|verify)\b') { Fail "host script (TCG profile) calls memcanary $($Matches[1]): '$($l.Trim())'" }
    # §15.4.8, §15.5 B5: memcanary-w only in -Variant j1, and there only its --selftest; watch never runs under TCG.
    if ($l -match 'memcanary-w') {
      if ($Variant -ne 'j1') { Fail "host script (TCG profile, -Variant $Variant) names memcanary-w, which only -Variant j1 carries: '$($l.Trim())'" }
      if ($l -match 'memcanary-w["'']?\s+["'']?(watch|asinfo|verify|alloc|hold)\b') { Fail "host script (TCG profile) calls memcanary-w $($Matches[1]): '$($l.Trim())'" }
    }
  }
  foreach ($key in @('@IMAGE_SHA256@', '@INITRD_SHA256@', '@CONF_SHA256@', '@CMDLINE_SHA256@', '@INIT_SHA256@',
                     '@S1CON_SHA256@', '@MEMCANARY_SHA256@', '@STAMP_SHA256@', '@BWAIT_SHA256@', '@STARTUP_SHA256@')) {
    if (-not $ksh.Contains([string]$subs[$key])) { Fail "host script lacks the item-5 stamp value of $key ($($subs[$key])): its S1 CONFIG cannot match this build" }
  }
  if ($Variant -eq 'j1' -and -not $ksh.Contains([string]$toolSha['memcanary-w'])) {
    Fail "host script lacks memcanary-w's sha256 ($($toolSha['memcanary-w'])): its S1 CONFIG cannot match this build"
  }
  Log "check host script ($kshSource): no marker left, no memcanary asinfo|verify, every item-5 stamp value present: ok"
  $kshPath = Join-Path $stageDir 's1-host.ksh'
  Write-Lf $kshPath $ksh
  $kshSha = Get-Sha256 $kshPath
  Log "sha256 staged s1-host.ksh=$kshSha"

  $r = Invoke-PythonBounded 'kshcheck-selftest' @(($parser -replace '\\','/'), 'kshcheck', '--selftest') $PythonBoundSec
  if ($r.Killed -or $r.Code -ne 0) { Fail 'kshcheck --selftest failed' }
  $r = Invoke-PythonBounded 'kshcheck' @(($parser -replace '\\','/'), 'kshcheck', ($kshPath -replace '\\','/')) $PythonBoundSec
  if ($r.Killed -or $r.Code -ne 0) { Fail 'the generated host script breaks the pipe-free rule (kshcheck)' }
  Log 'check kshcheck --selftest and kshcheck s1-host.ksh: ok'

  $params = [ordered]@{
    image = "tcg-$Variant"; variant = $Variant; mode = $Mode; tag = $Tag; profile = 'tcg'; smp = '4'; p = '4'
    diagnostic = $(if ($Variant -eq 'd1' -or $Variant -eq 'd2' -or $Variant -eq 'j1') { 'yes' } else { 'no' })
    guest_set = $guestSet; hold_s = "$holdS"; hold_mib = "$holdMib"; mem_gate_mib = "$gateMib"; guard_s = 'none'
    image_src = $imageRel; image_sha256 = [string]$subs['@IMAGE_SHA256@']
    initrd_src = $initrdSrcRel; initrd_sha256 = [string]$subs['@INITRD_SHA256@']
    conf = $confStagedRel; conf_sha256 = $confSha; cmdline_sha256 = $cmdlineSha; init_sha256 = $initSha
    s1con_sha256 = $toolSha['s1con']; memcanary_sha256 = $toolSha['memcanary']; stamp_sha256 = $toolSha['stamp']; bwait_sha256 = $toolSha['bwait']
    qconf_sha256 = $qconfSha; ksh_source = $kshSource; ksh_sha256 = $kshSha; kimg_sha256 = '-'
    # The generator's worst case for the script (a bound, never a result); launch-s1tcg.ps1 sizes its wall bound from it.
    ksh_worst_s = $(if ($gp.ContainsKey('ksh_worst_s') -and $gp['ksh_worst_s'] -match '^\d+$') { $gp['ksh_worst_s'] } else { '-' })
  }
  if ($Variant -eq 'j1') { $params['memcanary_w_sha256'] = $toolSha['memcanary-w'] }
  $paramsText = "# s1tcg.params: S1-F TCG rehearsal parameters (s1-design.md 4.2, 6.2-6.4); emulated, never a board image's.`n"
  foreach ($key in $params.Keys) { $paramsText += "$key=$($params[$key])`n" }
  Write-Lf (Join-Path $stageDir 's1tcg.params') $paramsText

  $sysLines = New-Object System.Collections.Generic.List[string]
  foreach ($t in $toolNames) { $sysLines.Add("[perms=555] bin/$t=$repoFwd/orin-native/tools/$t") }
  $sysLines.Add("[perms=555] bin/s1-host.ksh=$repoFwd/qhv/s1tcg/stage-$vName/s1-host.ksh")
  if ($Mode -eq 'q2') { $sysLines.Add("[perms=444] bin/s1-g2.conf=$repoFwd/qhv/s1tcg/stage-$vName/s1-g2.conf") }
  # The script calls $X/rm with X=/system/bin; the canonical system image has no bin/rm (m4-design.md §14, as build-m4tcg-image.ps1).
  $canonSys = @((Read-Text $canonSysBld).Replace("`r`n", "`n").Split("`n") | ForEach-Object { $_.Trim() })
  if (@($canonSys | Where-Object { $_ -match '(^|\]\s*)/?bin/rm=' }).Count -eq 0) { $sysLines.Add('bin/rm=usr/bin/toybox') }
  $sfPath = Join-Path $snip 'system_files.custom'
  $sf = ''
  if (Test-Path -LiteralPath $sfPath) { $sf = (Read-Text $sfPath).Replace("`r`n", "`n") }
  if ($sf.Length -gt 0 -and -not $sf.EndsWith("`n")) { $sf += "`n" }
  Write-Lf $sfPath ($sf + ($sysLines -join "`n") + "`n")
  foreach ($n in @('ifs_files.custom', 'ifs_start.custom', 'profile.custom')) {
    $p = Join-Path $snip $n
    if (Test-Path -LiteralPath $p) { Write-Lf $p (Read-Text $p) }
  }

  $optPath = Join-Path $hostDir 'local\options'
  $opt = (Read-Text $optPath).Replace("`r`n", "`n")
  $optRe = New-Object System.Text.RegularExpressions.Regex '(?m)^OPT_GUEST=.*$'
  $optHits = $optRe.Matches($opt)
  if ($optHits.Count -ne 1) { Fail "local/options has $($optHits.Count) OPT_GUEST= lines, expected 1" }
  $optNewLine = "OPT_GUEST='$repoFwd/qhv/s1tcg/guest'"
  Log "options: '$($optHits[0].Value)' -> '$optNewLine' (the only line changed)"
  Write-Lf $optPath $optRe.Replace($opt, $optNewLine.Replace('$', '$$'))
  foreach ($f in Get-ChildItem -LiteralPath $snip -File) { Log "sha256 snippet $($f.Name)=$(Get-Sha256 $f.FullName)" }

  # 7. Build.
  $mkArgs = "--type=qemu --arch=aarch64le --hostname=qnx-qhv --qvm=yes --guest=$repoFwd/qhv/s1tcg/guest --build"
  $mkPre  = @('@echo off', "call `"$sdpEnv`" >nul 2>&1", '@echo off', "cd /d `"$hostDir`"")
  $r = Invoke-CmdBounded 'mkqnximage' ($mkPre + @("call mkqnximage $mkArgs < NUL 2>&1", 'exit /b %ERRORLEVEL%')) $hostDir $MkqnximageBoundSec
  if ((-not $r.Killed) -and $r.Code -ne 0 -and $r.Text -match '(?i)ssh-ident|prompt') {
    Log 'mkqnximage failed on a prompt: one rerun with --ssh-ident=none'
    $r = Invoke-CmdBounded 'mkqnximage-sshnone' ($mkPre + @("call mkqnximage $mkArgs --ssh-ident=none < NUL 2>&1", 'exit /b %ERRORLEVEL%')) $hostDir $MkqnximageBoundSec
  }
  if ($r.Killed) { Fail "mkqnximage was killed at $MkqnximageBoundSec s" }
  if ($r.Code -ne 0) { Fail "mkqnximage exit=$($r.Code)" }

  # 8. Text checks.
  $bdir = Join-Path $hostDir 'output\build'
  $ps = Read-Text (Join-Path $bdir 'post_startup.sh')
  if (-not $ps.Contains('/system/bin/s1-host.ksh')) { Fail 'post_startup.sh does not run /system/bin/s1-host.ksh' }
  if ($ps.Contains('qvm @')) { Fail "post_startup.sh contains 'qvm @': the canonical snippet leaked in" }
  Log 'check post_startup.sh runs /system/bin/s1-host.ksh and has no "qvm @": ok'
  $sb = @((Read-Text (Join-Path $bdir 'system.build')).Replace("`r`n", "`n").Split("`n") | ForEach-Object { $_.Trim() })
  foreach ($want in $sysLines) {
    if ($sb -notcontains $want) { Fail "system.build lacks the line '$want'" }
  }
  foreach ($so in @('vdev-pl011.so', 'vdev-virtio-console.so')) {
    if (@($sb | Where-Object { $_ -match ('^(\[[^\]]*\]\s*)?/?lib/dll/' + [regex]::Escape($so) + '=') }).Count -lt 1) { Fail "system.build lacks lib/dll/$so" }
  }
  Log 'check system.build has every added line, lib/dll/vdev-pl011.so and lib/dll/vdev-virtio-console.so: ok'
  $ib = @((Read-Text (Join-Path $bdir 'ifs.build')).Replace("`r`n", "`n").Split("`n") | ForEach-Object { $_.Trim() })
  foreach ($tool in @('md5sum', 'base64', 'od', 'cat', 'rm', 'head', 'tail', 'wc', 'cmp', 'sleep', 'slay', 'pidin', 'devc-pty', 'qvm', 'qvm-check', 'slog2info')) {
    $inSys = @($sb | Where-Object { $_ -match ('(^|\]\s*)/?bin/' + [regex]::Escape($tool) + '=') }).Count -gt 0
    $inIfs = @($ib | Where-Object { $_ -match ('^(\[[^\]]*\]\s*)?(bin/)?' + [regex]::Escape($tool) + '(=|$)') }).Count -gt 0
    if (-not ($inSys -or $inIfs)) { Fail "neither system.build nor ifs.build provides $tool" }
    Log "check $tool provided by $(if ($inSys) { 'system.build' } else { 'ifs.build' }): ok"
  }
  if (-not (($ib -join "`n") -match '(?m)^[^#\n]*procnto-smp-instr')) { Fail 'ifs.build does not boot procnto-smp-instr' }
  $db = (Read-Text (Join-Path $bdir 'data.build')).Replace("`r`n", "`n").Split("`n")
  $dataWant = @(
    @('hypervisor/guest/ifs.bin', "$repoFwd/qhv/s1tcg/guest/output/ifs.bin"),
    @('hypervisor/guest/disk-qvm', "$repoFwd/qhv/s1tcg/guest/output/disk-qvm"),
    @('s1/Image', "$repoFwd/$imageRel"),
    @('s1/initrd.cpio.gz', "$repoFwd/$initrdSrcRel"),
    @('s1/s1-linux.conf', "$repoFwd/$confStagedRel")
  )
  foreach ($dw in $dataWant) {
    $srcs = @()
    foreach ($l in $db) {
      $m = [regex]::Match($l, '^\s*(?:\[[^\]]*\]\s*)?/?' + [regex]::Escape($dw[0]) + '\s*=\s*(.*?)\s*$')
      if ($m.Success) { $srcs += $m.Groups[1].Value }
    }
    if ($srcs.Count -eq 0) { Fail "data.build names no source for $($dw[0]) (R30)" }
    foreach ($s2 in $srcs) { if ($s2 -ne $dw[1]) { Fail "data.build: $($dw[0])=$s2 (want $($dw[1]))" } }
    Log "check data.build $($dw[0])=$($dw[1]): ok"
  }
  foreach ($o in @('ifs.bin', 'disk-qemu')) {
    if (-not (Test-Path -LiteralPath (Join-Path $hostDir "output\$o"))) { Fail "output/$o was not produced" }
  }

  # 9. Hashes after.
  $null = Test-Pin $imageRel $ImagePin 'post'
  $null = Test-Pin $initrdSrcRel $initrdWant 'post'
  if ((Get-Sha256 $gateConf) -ne $confSha) { Fail "input_post=CHANGED $confStagedRel" }
  if ((Get-Sha256 $initSrc) -ne $initSha) { Fail 'input_post=CHANGED orin-native/s1/init.sh' }
  foreach ($t in $toolNames) { if ((Get-Sha256 (Join-Path $toolsDir $t)) -ne $toolSha[$t]) { Fail "input_post=CHANGED orin-native/tools/$t" } }
  Log 'input_post staged configuration, init.sh and tools unchanged: ok'
  Test-GuestCopy 'post'
  Test-Canonical 'post'
  $vi = Get-Sha256 (Join-Path $hostDir 'output\ifs.bin')
  $vd = Get-Sha256 (Join-Path $hostDir 'output\disk-qemu')
  [System.IO.File]::WriteAllText((Join-Path $hostDir 'output\S1TCG-SHA256SUMS'), "$vi *ifs.bin`n$vd *disk-qemu`n", $utf8NoBom)
  Log "variant sha256 ifs.bin=$vi"
  Log "variant sha256 disk-qemu=$vd"
  Log "BUILD_OK variant=$Variant mode=$Mode tag=$Tag"
  $exitCode = 0
} catch {
  if ("$_" -eq 'S1TCG-CHECKONLY-DONE') {
    $exitCode = 0
  } else {
    if ("$_" -ne 'S1TCG-FAIL') {
      try { Log "FAIL: exception: $_" } catch { Write-Host "FAIL: exception: $_" }
    }
    $exitCode = 1
  }
} finally {
  if ($null -ne $gateTemp -and (Test-Path -LiteralPath $gateTemp)) { Remove-Item -LiteralPath $gateTemp -Force }
}
exit $exitCode
