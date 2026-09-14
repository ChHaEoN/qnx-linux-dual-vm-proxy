<#
.SYNOPSIS
  T0: rehearse M5LOAD.EFI under QEMU with edk2, on the PC, with no board.

.DESCRIPTION
  Phase 3b, results/orin-native-port/20260909T1100Z/m5-design.md §6.1 and §13
  decisions H and I; the J7a cases are s1-design.md §15.13.4's T0 table. Each
  case runs a T0 build of the loader - which embeds the contract probe, never a
  QNX byte - from the firmware's own UEFI Shell.

  Variant m5 (the M5 loader, or the J7a source with the switch off):
    T0b  -m 8G, `check`                  -> M5L CHECK PASS, then the Shell
    T0c  -m 8G, `check` then `go`        -> M5L-EBS ok, M5L-JUMP, PROBE ...
    T0d  -m 1536M, `check`               -> M5L REFUSE window: observed
           reason=type, because at 1536M the firmware's runtime services sit
           inside the window
    T0e  a blob byte flipped, `check`    -> M5L REFUSE crc src
    T0f  virtualization=off, `go`        -> M5L REFUSE el=1

  Variant j7a (M5L_J7A=1 T0=1 T0_PAD_LIKE=<kimg>), pre-registered in §15.13.4:
    T0b  -m 8G, `check`       -> every M5 token plus `M5L variant=j7a` directly
           after the start line, `M5L self ... canary=none`, `M5L fdt ...
           crc32=`, `M5L resmem done`, window-2 `M5L map` lines, three
           `preclaim=ok`, `M5L W2 PASS`, `M5L CHECK PASS`, Shell prompt
    T0c  as T0b, then `go`    -> `M5L-EBS ok`, `M5L-JUMP`, `PROBE EL=2 ...
           PC=0000000080080000`
    T0d  -m 1536M             -> any named refusal, then the Shell; never CHECK PASS
    T0e  as M5                -> as M5, the payload located by its own bytes
           with the padding
    T0fp virtualization=off, `go`, then `check` (T0f') -> `M5L REFUSE el=1`,
           the Shell, then `M5L CHECK PASS` with three `preclaim=ok` (UM10)
    T0h  -m 3G                -> as T0d
    T0i  -m 4G                -> as T0d
    T0j  -m 5280M             -> as T0d
    T0k  the switch-off T0 build (-SwitchOffDir), M5's cases b-f -> M5's tokens
    T0l  the T0_FORCE builds (-ForceFirstDir, -ForceLaterDir), `go` then
           `check` -> um6-first: `M5L GO`, `M5L REFUSE w2-final`, the Shell,
           then three `preclaim=ok` and `M5L CHECK PASS`; um6-later: `M5L GO`,
           `M5L-EBS FAIL`, a reset, no Shell prompt

  "The Shell prompt" is read from the next command's output: startup.nsh runs
  each command in turn and ends with `reset -s`, so a QEMU that exited on its
  own after a later command's tokens came back to the Shell. A reset is QEMU
  exiting under -no-reboot with no later command's tokens.

  A startup.nsh types the Shell commands. That file exists on the QEMU FAT
  drive only: the design forbids one on any filesystem the board can map
  (§7.4), and this script never writes outside its own output directory.

  Every log is a PC artefact. It still goes to a git-ignored path.

  Exit: 0 when every case run passes its expected tokens; 1 otherwise.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File orin-native\uefi\t0\run-t0.ps1
  powershell -NoProfile -ExecutionPolicy Bypass -File orin-native\uefi\t0\run-t0.ps1 -Case T0c -AcpiOn
  powershell -NoProfile -ExecutionPolicy Bypass -File orin-native\uefi\t0\run-t0.ps1 -Variant j7a `
    -LoaderDir <worktree>\orin-native\uefi\out\t0 -SwitchOffDir <dir> -ForceFirstDir <dir> -ForceLaterDir <dir>
#>

param(
  [ValidateSet('all', 'T0b', 'T0c', 'T0d', 'T0e', 'T0f', 'T0fp', 'T0h', 'T0i', 'T0j', 'T0k', 'T0l')][string]$Case = 'all',
  [ValidateSet('m5', 'j7a')][string]$Variant = 'm5',
  [string]$LoaderDir,
  [string]$SwitchOffDir,
  [string]$ForceFirstDir,
  [string]$ForceLaterDir,
  [string]$Qemu = 'E:\qemu-versions\qemu-11.1.0\qemu-system-aarch64.exe',
  [ValidateRange(0, 1800)][int]$TimeoutSeconds = 0,
  [switch]$AcpiOn,
  [string]$OutDir
)

$ErrorActionPreference = 'Stop'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$uefi = Split-Path -Parent $here
if (-not $LoaderDir) { $LoaderDir = Join-Path $uefi 'out\t0' }
if (-not $OutDir) { $OutDir = Join-Path $LoaderDir 'run' }
if ($TimeoutSeconds -eq 0) { $TimeoutSeconds = if ($Variant -eq 'j7a') { 420 } else { 90 } }

$m5Cases = @('T0b', 'T0c', 'T0d', 'T0e', 'T0f')
$j7aCases = @('T0b', 'T0c', 'T0d', 'T0e', 'T0fp', 'T0h', 'T0i', 'T0j', 'T0k', 'T0l')
$allowed = if ($Variant -eq 'j7a') { $j7aCases } else { $m5Cases }
if ($Case -ne 'all' -and $allowed -notcontains $Case) { throw "case $Case does not exist for variant $Variant" }

if (-not (Test-Path $Qemu)) { throw "no QEMU at $Qemu" }
$share = Join-Path (Split-Path -Parent $Qemu) 'share'
$code = Join-Path $share 'edk2-aarch64-code.fd'
$vars = Join-Path $share 'edk2-arm-vars.fd'
foreach ($f in @($code, $vars)) { if (-not (Test-Path $f)) { throw "no firmware file at $f" } }

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$W2_START = [decimal]0x100000000
$W2_END = [decimal]0x18A000000

# The variant an image carries: the J7a marker sits in .text, before the blob.
function Get-LoaderVariant {
  param([string]$Path)
  $fs = [System.IO.File]::OpenRead($Path)
  try {
    $n = [Math]::Min([long]65536, $fs.Length)
    $buf = New-Object byte[] $n
    [void]$fs.Read($buf, 0, $n)
  } finally { $fs.Dispose() }
  $text = [System.Text.Encoding]::ASCII.GetString($buf)
  if ($text.Contains('M5L variant=j7a')) { return 'j7a' }
  return 'm5'
}

function Resolve-Loader {
  param([string]$Dir, [string]$Want)
  $pe = Join-Path $Dir 'M5LOAD.EFI'
  if (-not (Test-Path $pe)) {
    throw "no T0 build at $pe - run: T0=1 [M5L_J7A=1 T0_PAD_LIKE=<kimg>] ./orin-native/uefi/build-m5-loader.sh"
  }
  $have = Get-LoaderVariant $pe
  if ($have -ne $Want) { throw "$pe is variant $have, expected $Want" }
  return $pe
}

function New-Esp {
  param([string]$Name, [string]$Loader, [string]$BlobFile, [string]$Commands, [switch]$CorruptBlob)

  $esp = Join-Path $OutDir "esp-$Name"
  if (Test-Path $esp) { Remove-Item -Recurse -Force $esp }
  New-Item -ItemType Directory -Force -Path $esp | Out-Null
  Copy-Item $Loader (Join-Path $esp 'M5LOAD.EFI')

  if ($CorruptBlob) {
    # T0e's negative control: flip one byte inside the embedded payload, so the
    # source CRC must refuse.
    #
    # The offset is derived from the payload itself, never written down. The
    # first attempt flipped 64 bytes from the end and the loader answered
    # CHECK PASS, correctly: the payload is padded to a page and the CRC covers
    # the payload's own length only (design 13 D), so the flip landed in
    # padding and the case passed for the wrong reason. A literal offset repeats
    # that silently the moment the payload moves or shrinks - it is a negative
    # control that can fail open, which is the one way a negative control must
    # never fail. So the embedded copy is located by its own bytes and the flip
    # is proved to land inside the CRC'd range.
    #
    # The J7a T0 payload is padded to the kimg's length (T0_PAD_LIKE), and the
    # CRC covers that whole length, padding included. A page-aligned candidate
    # is tested on its first page byte by byte, then over the whole payload by
    # sha256, so a many-megabyte payload is compared exactly without a
    # byte-by-byte PowerShell loop over all of it.
    $path = Join-Path $esp 'M5LOAD.EFI'
    if (-not (Test-Path $BlobFile)) { throw "T0e: no T0 payload at $BlobFile - rebuild with T0=1" }
    $bytes = [System.IO.File]::ReadAllBytes($path)
    $blob = [System.IO.File]::ReadAllBytes($BlobFile)
    if ($blob.Length -lt 64) { throw "T0e: the T0 payload is only $($blob.Length) bytes" }
    if ($bytes.Length -lt $blob.Length) { throw "T0e: the image is smaller than the payload" }

    # `.blob` carries `.align 12` and is linked last, and this is a flat image
    # whose file offsets equal its RVAs, so the embedded copy starts on a page
    # boundary. Only those candidates are tried; if the layout ever stops being
    # page-aligned this throws instead of flipping a byte somewhere harmless.
    $page = 4096
    $headLen = [Math]::Min($blob.Length, $page)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $want = [BitConverter]::ToString($sha.ComputeHash($blob))
    $hits = @()
    for ($off = [int]([math]::Floor(($bytes.Length - $blob.Length) / $page)) * $page; $off -ge 0; $off -= $page) {
      $same = $true
      for ($k = 0; $k -lt $headLen; $k++) {
        if ($bytes[$off + $k] -ne $blob[$k]) { $same = $false; break }
      }
      if ($same -and $blob.Length -gt $headLen) {
        $same = ([BitConverter]::ToString($sha.ComputeHash($bytes, $off, $blob.Length)) -eq $want)
      }
      if ($same) { $hits += $off }
    }
    if ($hits.Count -ne 1) {
      throw ("T0e: expected the payload exactly once on a page boundary, found {0}. " -f $hits.Count) +
            'Rebuild with T0=1, or check that .blob is still page-aligned and last.'
    }
    $start = $hits[0]
    $i = $start + [int]($blob.Length / 2)
    if ($i -lt $start -or $i -ge ($start + $blob.Length)) { throw "T0e: derived offset $i is outside the payload" }
    Write-Host ("T0e: payload at 0x{0:x}, {1} bytes; flipping 0x{2:x}, inside the CRC'd range" -f $start, $blob.Length, $i)
    $bytes[$i] = $bytes[$i] -bxor 0xFF
    [System.IO.File]::WriteAllBytes($path, $bytes)
  }

  # The Shell types these; QEMU only (§7.4).
  $nsh = "@echo -off`r`nfs0:`r`n$Commands`r`nreset -s`r`n"
  [System.IO.File]::WriteAllText((Join-Path $esp 'startup.nsh'), $nsh, [System.Text.ASCIIEncoding]::new())
  return $esp
}

function Invoke-Case {
  param([string]$Name, [string]$Loader, [string]$BlobFile, [string]$Memory, [string]$Commands,
        [switch]$NoVirt, [switch]$CorruptBlob)

  $esp = New-Esp -Name $Name -Loader $Loader -BlobFile $BlobFile -Commands $Commands -CorruptBlob:$CorruptBlob
  $log = Join-Path $OutDir "$Name.log"
  $scratchVars = Join-Path $OutDir "$Name-vars.fd"
  Copy-Item $vars $scratchVars -Force
  if (Test-Path $log) { Remove-Item -Force $log }

  $virt = if ($NoVirt) { 'off' } else { 'on' }
  # acpi=off is required, not optional. With ACPI on, QEMU's edk2 publishes no
  # device-tree configuration table at all and the loader refuses fdt; with it
  # off the tree appears and check passes (T0b, 2026-09-12: the design's Q2).
  # -AcpiOn exists only to reproduce that refusal.
  $machine = "virt,virtualization=$virt,gic-version=3"
  if (-not $AcpiOn) { $machine += ',acpi=off' }

  $qargs = @(
    '-M', $machine,
    '-cpu', 'max',
    '-smp', '1',
    '-m', $Memory,
    '-drive', "if=pflash,format=raw,unit=0,readonly=on,file=$code",
    '-drive', "if=pflash,format=raw,unit=1,file=$scratchVars",
    '-drive', "file=fat:rw:$esp,format=raw,if=virtio",
    '-display', 'none',
    # No network device. With one, BdsDxe tries PXE over IPv4 and then IPv6
    # before it reaches the built-in Shell, and the whole case times out in the
    # attempt: that is what the first T0 run showed.
    '-nic', 'none',
    '-serial', "file:$log",
    '-no-reboot'
  )

  Write-Host "== $Name : qemu $($qargs -join ' ')"
  $p = Start-Process -FilePath $Qemu -ArgumentList $qargs -PassThru -WindowStyle Hidden
  $done = $p.WaitForExit($TimeoutSeconds * 1000)
  if (-not $done) {
    Write-Host "$Name : timed out after $TimeoutSeconds s; stopping QEMU"
    try { Stop-Process -Id $p.Id -Force -Confirm:$false } catch {}
    $p.WaitForExit(5000) | Out-Null
  }

  $text = if (Test-Path $log) { Get-Content -Raw -Path $log } else { '' }
  if ($null -eq $text) { $text = '' }
  $tokens = @()
  foreach ($line in ($text -split "`r?`n")) {
    if ($line -match '^(M5L |M5L-|PROBE |M5G )') { $tokens += $line.TrimEnd() }
  }
  [pscustomobject]@{
    Case   = $Name
    Log    = $log
    Exited = $done
    Tokens = $tokens
  }
}

# ---------------------------------------------------------------- verdicts

function Find-Index {
  param([object[]]$T, [string]$Pattern, [int]$From)
  for ($i = $From; $i -lt $T.Count; $i++) { if ($T[$i] -match $Pattern) { return $i } }
  return -1
}

# The patterns in order, other tokens allowed between them. Returns the index
# after the last match and the first pattern that was not found.
function Test-Seq {
  param([object[]]$T, [string[]]$Patterns, [int]$From)
  $i = $From
  foreach ($p in $Patterns) {
    while ($i -lt $T.Count -and $T[$i] -notmatch $p) { $i++ }
    if ($i -ge $T.Count) { return @{ Next = -1; Missing = $p } }
    $i++
  }
  return @{ Next = $i; Missing = '' }
}

function Has-Token {
  param([object[]]$T, [string]$Pattern)
  return ((Find-Index $T $Pattern 0) -ge 0)
}

function New-Verdict {
  param([bool]$Pass, [string]$Why)
  return @{ Pass = $Pass; Why = $Why }
}

$probeRe = '^PROBE EL=2 X0=[0-9a-f]{16} X1=0{16} X2=0{16} X3=0{16} MAGIC=ok SCTLR_EL2=[0-9a-f]{16} DAIF=[0-9a-f]{16} PC=0000000080080000$'

# One J7a loader run up to `M5L W2 PASS`, starting at the next `M5L start
# mode=<Mode>` at or after From. Next is the index after `M5L W2 PASS`.
function Test-J7aPrelude {
  param([object[]]$T, [string]$Mode, [int]$From)
  $s = Find-Index $T "^M5L start mode=$Mode el=\d+ " $From
  if ($s -lt 0) { return @{ Next = -1; Why = "no M5L start mode=$Mode" } }
  if ($s + 2 -ge $T.Count -or $T[$s + 1] -ne 'M5L variant=j7a') {
    return @{ Next = -1; Why = "mode=${Mode}: M5L variant=j7a is not directly after the start line" }
  }
  if ($T[$s + 2] -notmatch '^M5L self w2=(yes|no) canary=none$') {
    return @{ Next = -1; Why = "mode=${Mode}: the self line is not 'M5L self w2=... canary=none' directly after the variant line" }
  }
  $pats = @(
    '^M5L fdt addr=[0-9a-f]+ size=[0-9a-f]+ crc32=[0-9a-f]+$',
    '^M5L con kind=',
    '^M5L resmem done$',
    '^M5L crc src=ok$',
    '^M5L crc dst=ok$',
    '^M5L canary c1 preclaim=ok$',
    '^M5L canary c2 preclaim=ok$',
    '^M5L canary c3 preclaim=ok$',
    '^M5L W2 PASS$'
  )
  $r = Test-Seq $T $pats ($s + 3)
  if ($r.Next -lt 0) { return @{ Next = -1; Why = "mode=${Mode}: missing $($r.Missing)" } }
  $w2map = $false
  for ($i = $s; $i -lt $r.Next; $i++) {
    if ($T[$i] -match '^M5L REFUSE') { return @{ Next = -1; Why = "mode=${Mode}: $($T[$i])" } }
    if ($T[$i] -match '^M5L map type=\S+ start=([0-9a-f]+) pages=([0-9a-f]+) attr=') {
      $st = [decimal][Convert]::ToUInt64($Matches[1], 16)
      $pg = [decimal][Convert]::ToUInt64($Matches[2], 16)
      if ($st -lt $W2_END -and ($st + $pg * 4096) -gt $W2_START) { $w2map = $true }
    }
  }
  if (-not $w2map) { return @{ Next = -1; Why = "mode=${Mode}: no M5L map line over window 2" } }
  return @{ Next = $r.Next; Why = '' }
}

function Test-J7aCheckPass {
  param([object[]]$T, [int]$From)
  $p = Test-J7aPrelude $T 'check' $From
  if ($p.Next -lt 0) { return $p }
  if ($p.Next -ge $T.Count -or $T[$p.Next] -ne 'M5L CHECK PASS') {
    return @{ Next = -1; Why = 'M5L CHECK PASS is not directly after M5L W2 PASS' }
  }
  return @{ Next = $p.Next + 1; Why = '' }
}

function Test-Refusal {
  param($R)
  $T = @($R.Tokens)
  if (-not (Has-Token $T '^M5L variant=j7a$')) { return New-Verdict $false 'no M5L variant=j7a' }
  $ref = @($T | Where-Object { $_ -match '^M5L REFUSE' })
  if ($ref.Count -eq 0) { return New-Verdict $false 'no named refusal' }
  if (Has-Token $T '^M5L CHECK PASS$') { return New-Verdict $false 'M5L CHECK PASS printed' }
  if (-not $R.Exited) { return New-Verdict $false 'no Shell prompt after the refusal (QEMU did not reach reset -s)' }
  return New-Verdict $true ("observed: " + ($ref -join ' | '))
}

$j7aVerdict = @{
  T0b = {
    param($R)
    $T = @($R.Tokens)
    $c = Test-J7aCheckPass $T 0
    if ($c.Next -lt 0) { return New-Verdict $false $c.Why }
    if (Has-Token $T '^M5L REFUSE') { return New-Verdict $false 'a refusal was printed' }
    if (-not $R.Exited) { return New-Verdict $false 'no Shell prompt after CHECK PASS' }
    return New-Verdict $true 'check prelude complete, CHECK PASS, Shell'
  }
  T0c = {
    param($R)
    $T = @($R.Tokens)
    $c = Test-J7aCheckPass $T 0
    if ($c.Next -lt 0) { return New-Verdict $false $c.Why }
    $g = Test-J7aPrelude $T 'go' $c.Next
    if ($g.Next -lt 0) { return New-Verdict $false $g.Why }
    if ($g.Next -ge $T.Count -or $T[$g.Next] -ne 'M5L GO') { return New-Verdict $false 'M5L GO is not directly after the go prelude' }
    $s = Test-Seq $T @('^M5L-EBS ok$', '^M5L-JUMP$', $probeRe) ($g.Next + 1)
    if ($s.Next -lt 0) { return New-Verdict $false "missing $($s.Missing)" }
    if (Has-Token $T '^M5L REFUSE') { return New-Verdict $false 'a refusal was printed' }
    if (-not $R.Exited) { return New-Verdict $false 'the probe did not power off' }
    return New-Verdict $true 'check and go preludes complete, EBS ok, JUMP, PROBE EL=2 at 80080000'
  }
  T0d = { param($R) Test-Refusal $R }
  T0h = { param($R) Test-Refusal $R }
  T0i = { param($R) Test-Refusal $R }
  T0j = { param($R) Test-Refusal $R }
  T0e = {
    param($R)
    $T = @($R.Tokens)
    if (-not (Has-Token $T '^M5L variant=j7a$')) { return New-Verdict $false 'no M5L variant=j7a' }
    $s = Test-Seq $T @('^M5L crc src=bad$', '^M5L REFUSE crc src$') 0
    if ($s.Next -lt 0) { return New-Verdict $false "missing $($s.Missing)" }
    if (Has-Token $T '^M5L CHECK PASS$') { return New-Verdict $false 'M5L CHECK PASS printed' }
    if (-not $R.Exited) { return New-Verdict $false 'no Shell prompt after the refusal' }
    return New-Verdict $true 'crc src=bad, REFUSE crc src, Shell'
  }
  T0fp = {
    param($R)
    $T = @($R.Tokens)
    $g = Test-J7aPrelude $T 'go' 0
    if ($g.Next -lt 0) { return New-Verdict $false $g.Why }
    if ($g.Next -ge $T.Count -or $T[$g.Next] -ne 'M5L REFUSE el=1') { return New-Verdict $false 'M5L REFUSE el=1 is not directly after the go prelude' }
    if (Has-Token $T '^M5L GO$') { return New-Verdict $false 'M5L GO printed at EL1' }
    $c = Test-J7aCheckPass $T ($g.Next + 1)
    if ($c.Next -lt 0) { return New-Verdict $false ("after the el=1 refusal: " + $c.Why) }
    if (-not $R.Exited) { return New-Verdict $false 'no Shell prompt after the check' }
    return New-Verdict $true 'REFUSE el=1, Shell, then three preclaim=ok and CHECK PASS (UM10)'
  }
}

$m5Verdict = @{
  T0b = {
    param($R)
    $T = @($R.Tokens)
    if (Has-Token $T '^M5L variant') { return New-Verdict $false 'a J7a line in an M5 run' }
    $s = Test-Seq $T @('^M5L start mode=check', '^M5L crc src=ok$', '^M5L crc dst=ok$', '^M5L CHECK PASS$') 0
    if ($s.Next -lt 0) { return New-Verdict $false "missing $($s.Missing)" }
    if (Has-Token $T '^M5L REFUSE') { return New-Verdict $false 'a refusal was printed' }
    if (-not $R.Exited) { return New-Verdict $false 'no Shell prompt' }
    return New-Verdict $true 'CHECK PASS, Shell'
  }
  T0c = {
    param($R)
    $T = @($R.Tokens)
    if (Has-Token $T '^M5L variant') { return New-Verdict $false 'a J7a line in an M5 run' }
    $s = Test-Seq $T @('^M5L start mode=check', '^M5L CHECK PASS$', '^M5L start mode=go', '^M5L GO$', '^M5L-EBS ok$', '^M5L-JUMP$', $probeRe) 0
    if ($s.Next -lt 0) { return New-Verdict $false "missing $($s.Missing)" }
    if (Has-Token $T '^M5L REFUSE') { return New-Verdict $false 'a refusal was printed' }
    if (-not $R.Exited) { return New-Verdict $false 'the probe did not power off' }
    return New-Verdict $true 'CHECK PASS, GO, EBS ok, JUMP, PROBE EL=2 at 80080000'
  }
  T0d = {
    param($R)
    $T = @($R.Tokens)
    if (-not (Has-Token $T '^M5L REFUSE window reason=type')) { return New-Verdict $false 'no M5L REFUSE window reason=type' }
    if (Has-Token $T '^M5L CHECK PASS$') { return New-Verdict $false 'M5L CHECK PASS printed' }
    if (-not $R.Exited) { return New-Verdict $false 'no Shell prompt' }
    return New-Verdict $true 'REFUSE window reason=type, Shell'
  }
  T0e = {
    param($R)
    $T = @($R.Tokens)
    $s = Test-Seq $T @('^M5L crc src=bad$', '^M5L REFUSE crc src$') 0
    if ($s.Next -lt 0) { return New-Verdict $false "missing $($s.Missing)" }
    if (-not $R.Exited) { return New-Verdict $false 'no Shell prompt' }
    return New-Verdict $true 'crc src=bad, REFUSE crc src, Shell'
  }
  T0f = {
    param($R)
    $T = @($R.Tokens)
    if (-not (Has-Token $T '^M5L REFUSE el=1$')) { return New-Verdict $false 'no M5L REFUSE el=1' }
    if (Has-Token $T '^M5L GO$') { return New-Verdict $false 'M5L GO printed at EL1' }
    if (-not $R.Exited) { return New-Verdict $false 'no Shell prompt' }
    return New-Verdict $true 'REFUSE el=1, Shell'
  }
}

function Test-ForceFirst {
  param($R)
  $T = @($R.Tokens)
  $g = Test-J7aPrelude $T 'go' 0
  if ($g.Next -lt 0) { return New-Verdict $false $g.Why }
  if ($g.Next + 1 -ge $T.Count -or $T[$g.Next] -ne 'M5L GO' -or $T[$g.Next + 1] -ne 'M5L REFUSE w2-final') {
    return New-Verdict $false 'M5L GO then M5L REFUSE w2-final are not directly after the go prelude'
  }
  if (Has-Token $T '^M5L-EBS') { return New-Verdict $false 'an M5L-EBS token after a first-try refusal' }
  $c = Test-J7aCheckPass $T ($g.Next + 2)
  if ($c.Next -lt 0) { return New-Verdict $false ("after w2-final: " + $c.Why) }
  if (-not $R.Exited) { return New-Verdict $false 'no Shell prompt after the check' }
  return New-Verdict $true 'GO, REFUSE w2-final, Shell, then three preclaim=ok and CHECK PASS'
}

function Test-ForceLater {
  param($R)
  $T = @($R.Tokens)
  $g = Test-J7aPrelude $T 'go' 0
  if ($g.Next -lt 0) { return New-Verdict $false $g.Why }
  if ($g.Next + 1 -ge $T.Count -or $T[$g.Next] -ne 'M5L GO' -or $T[$g.Next + 1] -ne 'M5L-EBS FAIL') {
    return New-Verdict $false 'M5L GO then M5L-EBS FAIL are not directly after the go prelude'
  }
  if ($T.Count -ne $g.Next + 2) { return New-Verdict $false ("tokens after M5L-EBS FAIL: " + ($T[($g.Next + 2)..($T.Count - 1)] -join ' | ')) }
  if (-not $R.Exited) { return New-Verdict $false 'no reset: QEMU did not exit' }
  return New-Verdict $true 'GO, EBS FAIL, reset, no Shell prompt (the later check never ran)'
}

# ---------------------------------------------------------------- the cases

$results = @()

function Add-Result {
  param($R, $V)
  $script:results += [pscustomobject]@{ Case = $R.Case; Log = $R.Log; Exited = $R.Exited; Tokens = $R.Tokens; Pass = $V.Pass; Why = $V.Why }
}

function Invoke-M5Set {
  param([string]$Dir, [string]$Prefix, [string[]]$Names)
  $loader = Resolve-Loader $Dir 'm5'
  $blob = Join-Path $Dir 'contract-probe.bin'
  foreach ($n in $Names) {
    $label = "$Prefix$n"
    $r = switch ($n) {
      'T0b' { Invoke-Case -Name $label -Loader $loader -BlobFile $blob -Memory '8G' -Commands 'M5LOAD.EFI check' }
      'T0c' { Invoke-Case -Name $label -Loader $loader -BlobFile $blob -Memory '8G' -Commands "M5LOAD.EFI check`r`nM5LOAD.EFI go" }
      'T0d' { Invoke-Case -Name $label -Loader $loader -BlobFile $blob -Memory '1536M' -Commands 'M5LOAD.EFI check' }
      'T0e' { Invoke-Case -Name $label -Loader $loader -BlobFile $blob -Memory '8G' -Commands 'M5LOAD.EFI check' -CorruptBlob }
      'T0f' { Invoke-Case -Name $label -Loader $loader -BlobFile $blob -Memory '8G' -Commands 'M5LOAD.EFI go' -NoVirt }
    }
    Add-Result $r (& $m5Verdict[$n] $r)
  }
}

if ($Variant -eq 'm5') {
  $order = if ($Case -eq 'all') { $m5Cases } else { @($Case) }
  Invoke-M5Set $LoaderDir '' $order
} else {
  $order = if ($Case -eq 'all') { $j7aCases } else { @($Case) }
  foreach ($n in $order) {
    switch ($n) {
      'T0k' {
        if (-not $SwitchOffDir) { throw 'T0k needs -SwitchOffDir (the switch-off T0 build)' }
        Invoke-M5Set $SwitchOffDir 'T0k-' $m5Cases
      }
      'T0l' {
        if (-not $ForceFirstDir -or -not $ForceLaterDir) { throw 'T0l needs -ForceFirstDir and -ForceLaterDir' }
        $lf = Resolve-Loader $ForceFirstDir 'j7a'
        $r = Invoke-Case -Name 'T0l-um6-first' -Loader $lf -BlobFile (Join-Path $ForceFirstDir 'contract-probe.bin') -Memory '8G' -Commands "M5LOAD.EFI go`r`nM5LOAD.EFI check"
        Add-Result $r (Test-ForceFirst $r)
        $ll = Resolve-Loader $ForceLaterDir 'j7a'
        $r = Invoke-Case -Name 'T0l-um6-later' -Loader $ll -BlobFile (Join-Path $ForceLaterDir 'contract-probe.bin') -Memory '8G' -Commands "M5LOAD.EFI go`r`nM5LOAD.EFI check"
        Add-Result $r (Test-ForceLater $r)
      }
      default {
        $loader = Resolve-Loader $LoaderDir 'j7a'
        $blob = Join-Path $LoaderDir 'contract-probe.bin'
        $r = switch ($n) {
          'T0b'  { Invoke-Case -Name 'T0b' -Loader $loader -BlobFile $blob -Memory '8G' -Commands 'M5LOAD.EFI check' }
          'T0c'  { Invoke-Case -Name 'T0c' -Loader $loader -BlobFile $blob -Memory '8G' -Commands "M5LOAD.EFI check`r`nM5LOAD.EFI go" }
          'T0d'  { Invoke-Case -Name 'T0d' -Loader $loader -BlobFile $blob -Memory '1536M' -Commands 'M5LOAD.EFI check' }
          'T0e'  { Invoke-Case -Name 'T0e' -Loader $loader -BlobFile $blob -Memory '8G' -Commands 'M5LOAD.EFI check' -CorruptBlob }
          'T0fp' { Invoke-Case -Name 'T0fp' -Loader $loader -BlobFile $blob -Memory '8G' -Commands "M5LOAD.EFI go`r`nM5LOAD.EFI check" -NoVirt }
          'T0h'  { Invoke-Case -Name 'T0h' -Loader $loader -BlobFile $blob -Memory '3G' -Commands 'M5LOAD.EFI check' }
          'T0i'  { Invoke-Case -Name 'T0i' -Loader $loader -BlobFile $blob -Memory '4G' -Commands 'M5LOAD.EFI check' }
          'T0j'  { Invoke-Case -Name 'T0j' -Loader $loader -BlobFile $blob -Memory '5280M' -Commands 'M5LOAD.EFI check' }
        }
        Add-Result $r (& $j7aVerdict[$n] $r)
      }
    }
  }
}

Write-Host ''
Write-Host "--- T0 summary, variant $Variant (expected tokens: m5-design 6.1; J7a: s1-design 15.13.4) ---"
$failed = 0
foreach ($r in $results) {
  $verdict = if ($r.Pass) { 'PASS' } else { 'FAIL'; $failed++ }
  Write-Host ("{0}: {1} exited={2} log={3}" -f $r.Case, $verdict, $r.Exited, $r.Log)
  Write-Host "    reading: $($r.Why)"
  foreach ($t in $r.Tokens) { Write-Host "    $t" }
  if (-not $r.Tokens) { Write-Host '    (no loader token: read the log in full)' }
}
Write-Host ''
Write-Host 'T0 says nothing about cache coherency after the copy (m5-design 6.1, R33): that is board-only.'
Write-Host 'No QNX byte ran here: the T0 build embeds the contract probe.'
Write-Host ("T0 RESULT {0} {1}/{2}" -f $(if ($failed) { 'FAIL' } else { 'PASS' }), ($results.Count - $failed), $results.Count)
if ($failed) { exit 1 }
exit 0
