<#
.SYNOPSIS
  Run one attempt of the Phase 3b checklist 7b dry run: boot a variant QHV host
  image under QEMU-TCG, watch its serial file, then run the PC parser. Both are
  bounded, and neither can outlive this script.

.DESCRIPTION
  Implements results/orin-native-port/20260909T1100Z/m4-dryrun-design.md,
  section 5.6 (revision 2), with the attempt-1 fixes of section 13: -Tag selects
  a tagged build (host-<variant>-<tag>), the k512 ring variant, and a bounded
  re-check behind every alive_after= (D-e). scripts/launch-qhv-tcg.ps1 is neither changed nor
  called: its default behaviour feeds the Phase-4 twin diff. The QEMU argument
  list below is that script's -WithRng list with only the two image paths and
  the serial file changed.

  The image runs the whole dry run by itself (orin-native/m4dry/m4dry-host.ksh.in)
  and ends with 'shutdown -S reboot', which ends QEMU under -no-reboot. This
  script only watches the serial file and stamps first sightings with a PC
  stopwatch. QEMU's PID is recorded as soon as it starts; the run is bounded by
  -WallSeconds and by -EndGraceSeconds after 'M4D STATE end'; a finally block
  stops QEMU whatever happened, Ctrl+C included. The parser is started, bounded
  and stopped the same way, its descendant processes included.

  Steps, numbered as the design's section 5.6:
    1. paths: the variant image directory, refused per 4.3 step 1; M4DRY-SHA256SUMS
    2. canonical checks before
    3. output: refuse an existing attempt; create qhv/m4dry/attempt<N>/
    4. PC free memory, refused below -MinFreeGB
    5. provenance into attempt<N>-launch.log; redacted copy of the build log
    6. the QEMU command
    7. start QEMU, record its PID at once
    8. poll the serial file incrementally, write MARK lines; finally: stop QEMU
    9. canonical checks after, M4DRY-SHA256SUMS again, free memory again
   10. the parser, bounded by -ParserSeconds; finally: stop it and its descendants
   11. confirm nothing survived; list the files written

  Writes (only *.log into results/, which .gitignore covers):
    results/orin-native-port/20260910T2307Z/m4-dryrun/attempt<N>-launch.log
    results/orin-native-port/20260910T2307Z/m4-dryrun/attempt<N>-build.log
    qhv/m4dry/attempt<N>/serial-raw.log, parser-stdout.log, parser-stderr.log
  and, through the parser, attempt<N>-serial.log and attempt<N>-parse.log.
  Every figure is evaluation output under NC QDL v7 4.6(i). The Windows user
  name is written as <user> in everything under results/.

  Exit 0 when QEMU ended by itself or at the end grace and the parser exited 0;
  1 otherwise.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File orin-native\m4dry\launch-m4dry-tcg.ps1 -Attempt 1

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File orin-native\m4dry\launch-m4dry-tcg.ps1 -Attempt 2 -Variant k64 -Tag r3
  Boots qhv/m4dry/host-k64-r3/output, built with build-m4dry-image.ps1 -Variant k64 -Tag r3.
#>
param(
  [Parameter(Mandatory = $true)][ValidateRange(1, 9999)][int]$Attempt,
  [ValidateSet('plan','k64','k512','vtwfe')][string]$Variant = 'plan',
  [ValidatePattern('^[a-z0-9]{0,16}$')][string]$Tag = '',
  [string]$QemuPath,
  [ValidateRange(60, 86400)][int]$WallSeconds = 5500,
  [ValidateRange(1, 3600)][int]$EndGraceSeconds = 90,
  [ValidateRange(10, 5000)][int]$PollMs = 50,
  [ValidateRange(0, 1024)][double]$MinFreeGB = 4,
  [ValidateRange(60, 86400)][int]$ParserSeconds = 2400
)

$ErrorActionPreference = 'Stop'

$GuestIfsPin  = '968029316b940f53580228f44e393877e032e251d78f3c752600cae726a7cf4f'
$GuestDiskPin = 'cf5b06d0b3cb524201c71440fdda42a18d2636d45938acd8ec95cfa21314216b'

$scriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot   = [System.IO.Path]::GetFullPath((Join-Path $scriptDir '..\..')).TrimEnd('\')
$repoFwd    = $repoRoot -replace '\\','/'
$canonHost  = Join-Path $repoRoot 'qhv\host'
$canonGuest = Join-Path $repoRoot 'qhv\guest'
$runRoot    = Join-Path $repoRoot 'qhv\m4dry'
# -Tag names a separate build of the variant (design section 13), so a rebuilt
# image never needs an earlier attempt's directory renamed or removed.
$vName      = $Variant
if ($Tag) { $vName = "$Variant-$Tag" }
$imageDir   = Join-Path $runRoot "host-$vName\output"
$buildLog   = Join-Path $runRoot "build-$vName.log"
$attemptDir = Join-Path $runRoot "attempt$Attempt"
$serialLog  = Join-Path $attemptDir 'serial-raw.log'
$outDir     = Join-Path $repoRoot 'results\orin-native-port\20260910T2307Z\m4-dryrun'
$launchLog  = Join-Path $outDir "attempt$Attempt-launch.log"
$buildCopy  = Join-Path $outDir "attempt$Attempt-build.log"
$parser     = Join-Path $scriptDir 'parse-m4dry.py'
if ($env:QNX_INSTALL_ROOT) { $sdpRoot = $env:QNX_INSTALL_ROOT } else { $sdpRoot = Join-Path $env:USERPROFILE 'qnx800' }
$hostTp     = Join-Path $sdpRoot 'host\win64\x86_64\usr\bin\traceprinter.exe'
$utf8NoBom  = New-Object System.Text.UTF8Encoding $false

# ---------------------------------------------------------------- helpers

$redactNames = New-Object System.Collections.Generic.List[string]
if ($env:USERNAME) { $redactNames.Add($env:USERNAME) }
if ($env:USERPROFILE) {
  $leaf = Split-Path -Leaf $env:USERPROFILE
  if ($leaf -and -not $redactNames.Contains($leaf)) { $redactNames.Add($leaf) }
}

function Redact([string]$Text) {
  if ($null -eq $Text) { return '' }
  foreach ($n in $redactNames) {
    if ($n.Length -ge 3) {
      $Text = [regex]::Replace($Text, [regex]::Escape($n), '<user>', [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
    }
  }
  return $Text
}

$script:launchReady = $false
$script:pending = New-Object System.Collections.Generic.List[string]

# One line to the console and, once the attempt is claimed, to the launch log.
function LL([string]$Line) {
  $t = Redact $Line
  Write-Host $t
  if (-not $script:launchReady) { $script:pending.Add($t); return }
  for ($i = 0; $i -lt 40; $i++) {
    try { [System.IO.File]::AppendAllText($launchLog, $t + "`n", $utf8NoBom); return } catch { Start-Sleep -Milliseconds 50 }
  }
  Write-Warning "could not append to the launch log: $t"
}

function Refuse([string]$Why) {
  LL "REFUSED: $Why"
  throw 'M4DRY-REFUSED'
}

function Get-Sha256([string]$Path) {
  return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Get-NormPath([string]$Path) {
  return ([System.IO.Path]::GetFullPath($Path) -replace '/','\').TrimEnd('\')
}

function Test-Under([string]$Path, [string]$Base) {
  $a = Get-NormPath $Path
  $b = Get-NormPath $Base
  return ($a -ieq $b) -or $a.StartsWith($b + '\', [System.StringComparison]::OrdinalIgnoreCase)
}

# Alive means listed and not exited. A process that has just exited can stay
# listed for a moment while Windows tears it down; attempt 1 logged
# alive_after=yes straight after QEMU exited, then survivors=none (section 13 D-e).
function Test-Alive([int]$Id) {
  try { $p = Get-Process -Id $Id -ErrorAction Stop } catch { return $false }
  try { if ($p.HasExited) { return $false } } catch { }
  return $true
}

# Bounded re-check: milliseconds until the process is no longer alive, or -1
# when it is still alive after $Seconds.
function Wait-Gone([int]$Id, [int]$Seconds) {
  $gw = [System.Diagnostics.Stopwatch]::StartNew()
  while ($gw.Elapsed.TotalSeconds -lt $Seconds) {
    if (-not (Test-Alive $Id)) { return [long]$gw.Elapsed.TotalMilliseconds }
    Start-Sleep -Milliseconds 100
  }
  if (-not (Test-Alive $Id)) { return [long]$gw.Elapsed.TotalMilliseconds }
  return -1
}

function Get-FreeGB {
  $os = Get-CimInstance -ClassName Win32_OperatingSystem
  return [math]::Round(([double]$os.FreePhysicalMemory) / 1MB, 2)
}

# Design 4.3 steps 2 and 3. Returns $true when every canonical hash holds.
function Test-Canonical([string]$When) {
  $ok = $true
  $sums = Join-Path $canonHost 'output\SHA256SUMS'
  if (-not (Test-Path -LiteralPath $sums)) { LL "canonical_$When qhv/host/output/SHA256SUMS missing"; return $false }
  $n = 0
  foreach ($line in [System.IO.File]::ReadAllLines($sums)) {
    $m = [regex]::Match($line, '^([0-9a-fA-F]{64}) [ *]?(\S+)\s*$')
    if (-not $m.Success) { continue }
    $want = $m.Groups[1].Value.ToLowerInvariant()
    $name = $m.Groups[2].Value
    $got  = Get-Sha256 (Join-Path $canonHost ('output\' + $name))
    $state = 'ok'
    if ($got -ne $want) { $state = 'CHANGED'; $ok = $false }
    LL "canonical_$When qhv/host/output/$name sha256=$got $state"
    $n++
  }
  if ($n -ne 2) { LL "canonical_$When SHA256SUMS lists $n files, expected 2"; $ok = $false }
  foreach ($pin in @(@('ifs.bin', $GuestIfsPin), @('disk-qvm', $GuestDiskPin))) {
    $got = Get-Sha256 (Join-Path $canonGuest ('output\' + $pin[0]))
    $state = 'ok'
    if ($got -ne $pin[1]) { $state = 'CHANGED'; $ok = $false }
    LL "canonical_$When qhv/guest/output/$($pin[0]) sha256=$got $state"
  }
  return $ok
}

# The variant image against its own M4DRY-SHA256SUMS.
function Test-VariantSums([string]$When) {
  $sums = Join-Path $imageDir 'M4DRY-SHA256SUMS'
  if (-not (Test-Path -LiteralPath $sums)) { LL "image_$When M4DRY-SHA256SUMS missing"; return $false }
  $ok = $true
  $n = 0
  foreach ($line in [System.IO.File]::ReadAllLines($sums)) {
    $m = [regex]::Match($line, '^([0-9a-fA-F]{64}) [ *]?(\S+)\s*$')
    if (-not $m.Success) { continue }
    $got = Get-Sha256 (Join-Path $imageDir $m.Groups[2].Value)
    $state = 'ok'
    if ($got -ne $m.Groups[1].Value.ToLowerInvariant()) { $state = 'MISMATCH'; $ok = $false }
    LL "image_$When $($m.Groups[2].Value) sha256=$got $state"
    $n++
  }
  if ($n -ne 2) { LL "image_$When M4DRY-SHA256SUMS lists $n files, expected 2"; $ok = $false }
  return $ok
}

# Every descendant of a process, found recursively through ParentProcessId.
# On Windows, stopping a parent does not stop its children.
function Get-DescendantIds([int]$RootId) {
  $children = @{}
  foreach ($pr in @(Get-CimInstance -ClassName Win32_Process)) {
    $pp = [int]$pr.ParentProcessId
    if (-not $children.ContainsKey($pp)) { $children[$pp] = New-Object System.Collections.Generic.List[int] }
    $children[$pp].Add([int]$pr.ProcessId)
  }
  $seen = New-Object System.Collections.Generic.HashSet[int]
  $queue = New-Object System.Collections.Generic.Queue[int]
  $result = New-Object System.Collections.Generic.List[int]
  $queue.Enqueue($RootId)
  while ($queue.Count -gt 0) {
    $cur = $queue.Dequeue()
    if (-not $children.ContainsKey($cur)) { continue }
    foreach ($c in $children[$cur]) {
      if ($c -ne $RootId -and $c -ne 0 -and $seen.Add($c)) { $result.Add($c); $queue.Enqueue($c) }
    }
  }
  return ,$result
}

# ---------------------------------------------------------------- serial watcher state

$script:sw        = $null
$script:offset    = [long]0
$script:carry     = ''
$script:seen      = @{}
$script:endSeenMs = $null
$latin1 = [System.Text.Encoding]::GetEncoding(28591)

function Set-Mark([string]$Name) {
  if ($script:seen.ContainsKey($Name)) { return }
  $ms = [long]$script:sw.Elapsed.TotalMilliseconds
  $script:seen[$Name] = $ms
  LL "MARK $Name pc_ms=$ms"
}

function Test-SerialLine([string]$Raw) {
  $l = $Raw.Trim("`r")
  if ($l.IndexOf(' ') -lt 0) { return }          # base64 and bare lines carry no mark
  $m = [regex]::Match($l, 'M4D STATE (\S+)')
  if ($m.Success) {
    Set-Mark ('state:' + $m.Groups[1].Value)
    if ($m.Groups[1].Value -eq 'end' -and $null -eq $script:endSeenMs) { $script:endSeenMs = [long]$script:sw.Elapsed.TotalMilliseconds }
  }
  if ($l.Contains('M4D KEV BEGIN')) {
    $k = [regex]::Match($l, 'name=(\S+)'); if ($k.Success) { Set-Mark ('kev_begin:' + $k.Groups[1].Value) }
  }
  if ($l.Contains('M4D KEV END')) {
    $k = [regex]::Match($l, 'name=(\S+)'); if ($k.Success) { Set-Mark ('kev_end:' + $k.Groups[1].Value) }
  }
  if ($l.Contains('CLK EXT start')) { Set-Mark 'clk_ext_start' }
  if ($l.Contains('CLK EXT end')) { Set-Mark 'clk_ext_end' }
  if ($l.Contains('=== launching qvm @g2.conf')) { Set-Mark 'qvm_launch' }
  # echo_up: the guest echo server announcing /dev/vcon2 (ipc-test/qnx-server/server.c:61),
  # the endpoint the client's /dev/ttyp0 reaches; the parser's ipc_after_guest_ready needs it.
  if ($l.Contains('server: echo endpoint up')) { Set-Mark 'echo_up' }
  if ($l.Contains('QNX qnx-guest')) { Set-Mark 'guest_banner' }
  if ($l.StartsWith('samples=')) { Set-Mark 'samples' }
}

# Read only the bytes appended since the last call; carry a partial last line.
function Read-SerialTail([bool]$Final) {
  if (-not (Test-Path -LiteralPath $serialLog)) { return }
  try {
    $fs = [System.IO.File]::Open($serialLog, 'Open', 'Read', 'ReadWrite')
    try {
      while ($fs.Length -gt $script:offset) {
        $null = $fs.Seek($script:offset, 'Begin')
        $want = [int][math]::Min($fs.Length - $script:offset, 4MB)
        $buf = New-Object byte[] $want
        $got = $fs.Read($buf, 0, $want)
        if ($got -le 0) { break }
        $script:offset += $got
        $parts = ($script:carry + $latin1.GetString($buf, 0, $got)).Split("`n")
        $script:carry = $parts[$parts.Length - 1]
        for ($i = 0; $i -lt $parts.Length - 1; $i++) { Test-SerialLine $parts[$i] }
      }
    } finally { $fs.Close() }
  } catch { return }
  if ($Final -and $script:carry.Length -gt 0) { Test-SerialLine $script:carry; $script:carry = '' }
}

# ---------------------------------------------------------------- main

$exitCode   = 1
$qemuProc   = $null
$qemuHow    = 'not-started'
$parserProc = $null
$parserHow  = 'not-started'
$parserExit = $null
$parserDesc = New-Object System.Collections.Generic.List[int]
try {
  # 1. Paths.
  if ((Test-Under $imageDir $canonHost) -or (Test-Under $imageDir $canonGuest)) { Refuse "image directory $imageDir is inside a canonical tree" }
  if (-not (Get-NormPath $imageDir).StartsWith((Get-NormPath $runRoot) + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
    Refuse "image directory $imageDir does not lie under qhv/m4dry/"
  }
  if (-not (Test-VariantSums 'pre')) { Refuse 'the variant image does not match its M4DRY-SHA256SUMS (build it first)' }

  # 2. Canonical checks before.
  if (-not (Test-Canonical 'pre')) { Refuse 'canonical_pre=MISMATCH: the canonical baseline is not the one the design assumes' }
  LL 'canonical_pre=ok'

  # 3. Output.
  New-Item -ItemType Directory -Force -Path $outDir | Out-Null
  if (@(Get-ChildItem -LiteralPath $outDir -Filter "attempt$Attempt-*" -Force).Count -gt 0) { Refuse "results already hold attempt$Attempt-* files; attempt numbers are never reused" }
  if (Test-Path -LiteralPath $attemptDir) { Refuse "qhv/m4dry/attempt$Attempt exists; attempt numbers are never reused" }
  New-Item -ItemType Directory -Path $attemptDir | Out-Null
  $script:launchReady = $true
  foreach ($l in $script:pending) { [System.IO.File]::AppendAllText($launchLog, $l + "`n", $utf8NoBom) }
  $script:pending.Clear()

  # 4. PC memory.
  $freeGb = Get-FreeGB
  LL "pc_free_gb_pre=$freeGb min_free_gb=$MinFreeGB"
  if ($freeGb -lt $MinFreeGB) { Refuse "free physical memory $freeGb GB is below -MinFreeGB $MinFreeGB" }

  # 5. Provenance.
  if ($QemuPath) {
    if (-not (Test-Path -LiteralPath $QemuPath)) { Refuse "-QemuPath '$QemuPath' does not exist" }
    $qemu = $QemuPath
  } else {
    $qemu = @('C:\Program Files\qemu\qemu-system-aarch64.exe', 'C:\Program Files\qemu\qemu-system-aarch64w.exe') |
      Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $qemu) { Refuse 'qemu-system-aarch64 not found; install QEMU or pass -QemuPath' }
  }
  # Capture the whole output and index it; see launch-qhv-tcg.ps1 on why not Select-Object -First 1.
  $qemuVer = (@(& $qemu --version))[0]
  $cpuName = (Get-CimInstance -ClassName Win32_Processor | Select-Object -First 1 -ExpandProperty Name)
  LL ('launch_utc=' + (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'))
  LL "attempt=$Attempt variant=$Variant tag=$(if ($Tag) { $Tag } else { 'none' }) image_dir=qhv/m4dry/host-$vName/output"
  LL "host=Windows $([System.Environment]::OSVersion.Version) $env:PROCESSOR_ARCHITECTURE / $cpuName"
  LL "qemu_version=$qemuVer"
  LL "qemu_path=$qemu"
  LL 'devices: virtio-blk + virtio-net(slirp) + virtio-rng(builtin)'
  LL 'disk: -snapshot'
  LL "poll_ms=$PollMs wall_s=$WallSeconds end_grace_s=$EndGraceSeconds parser_s=$ParserSeconds"
  LL 'image=rebuilt-host guest=byte-identical (not the canonical host image; not a twin-diff input)'
  if (Test-Path -LiteralPath $buildLog) {
    [System.IO.File]::WriteAllText($buildCopy, (Redact ([System.IO.File]::ReadAllText($buildLog))), $utf8NoBom)
    LL "build_log_copy=results/orin-native-port/20260910T2307Z/m4-dryrun/attempt$Attempt-build.log"
  } else {
    LL 'build_log_copy=none (no qhv/m4dry build log found)'
  }

  # 6. The QEMU command: launch-qhv-tcg.ps1's -WithRng list, image paths and serial file changed.
  $ifsF    = (Join-Path $imageDir 'ifs.bin') -replace '\\','/'
  $diskF   = (Join-Path $imageDir 'disk-qemu') -replace '\\','/'
  $serialF = $serialLog -replace '\\','/'
  $qargs = @(
    '-machine','virt,virtualization=on,gic-version=3',
    '-cpu','max','-accel','tcg','-smp','2','-m','2G',
    '-snapshot',
    '-drive',"file=$diskF,if=none,id=drv0,format=raw",
    '-device','virtio-blk-device,drive=drv0',
    '-netdev','user,id=n0','-device','virtio-net-device,netdev=n0',
    '-object','rng-builtin,id=rng0','-device','virtio-rng-device,rng=rng0',
    '-kernel',$ifsF,
    '-serial',"file:$serialF",'-display','none','-no-reboot'
  )
  foreach ($a in $qargs) { if ($a.Contains(' ')) { Refuse "a QEMU argument contains a space and would be split: '$a'" } }
  LL ('qemu_args=' + ($qargs -join ' '))

  # 7. Start QEMU.
  $script:sw = [System.Diagnostics.Stopwatch]::StartNew()
  $qemuProc = Start-Process -FilePath $qemu -ArgumentList $qargs -PassThru -NoNewWindow
  $null = $qemuProc.Handle
  LL ("QEMU_PID=$($qemuProc.Id) started_utc=" + (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'))

  # 8. Poll.
  $qemuHow = 'interrupted'
  try {
    while ($true) {
      Read-SerialTail $false
      if ($qemuProc.HasExited) { $qemuHow = 'exited'; break }
      if ($null -ne $script:endSeenMs -and ($script:sw.Elapsed.TotalMilliseconds - $script:endSeenMs) -ge ($EndGraceSeconds * 1000)) { $qemuHow = 'end-grace-kill'; break }
      if ($script:sw.Elapsed.TotalMilliseconds -ge ($WallSeconds * 1000)) { $qemuHow = 'wall-kill'; break }
      Start-Sleep -Milliseconds $PollMs
    }
  } finally {
    if (-not $qemuProc.HasExited) {
      try { Stop-Process -Id $qemuProc.Id -Force -ErrorAction Stop } catch { }
      try { Wait-Process -Id $qemuProc.Id -Timeout 15 -ErrorAction Stop } catch { }
    }
    $qGoneMs = Wait-Gone $qemuProc.Id 15
    $qExit = 'none'
    if ($qemuProc.HasExited) { try { $qExit = "$($qemuProc.ExitCode)" } catch { $qExit = 'none' } }
    Read-SerialTail $true
    LL "QEMU_STOPPED how=$qemuHow exit=$qExit alive_after=$(if ($qGoneMs -lt 0) { 'yes' } else { 'no' }) gone_wait_ms=$qGoneMs pc_ms=$([long]$script:sw.Elapsed.TotalMilliseconds) serial_bytes=$($script:offset)"
  }

  # 9. After the run.
  $canonPost = Test-Canonical 'post'
  if (-not $canonPost) {
    LL 'canonical_post=CHANGED: something wrote to the canonical images. Stopping everything; tell the owner.'
    throw 'M4DRY-CANONICAL-CHANGED'
  }
  LL 'canonical_post=ok'
  if (-not (Test-VariantSums 'post')) { LL 'image_post=MISMATCH (recorded; -snapshot should have kept it)' }
  LL "pc_free_gb_post=$(Get-FreeGB)"

  # 10. The parser, bounded the way QEMU is.
  $py = (Get-Command python -ErrorAction Stop).Source
  LL "python=$py"
  $pargs = @(
    ('"' + ($parser -replace '\\','/') + '"'),
    '--attempt', "$Attempt",
    '--serial', ('"' + $serialF + '"'),
    '--launch', ('"' + ($launchLog -replace '\\','/') + '"'),
    '--run-dir', ('"' + ($attemptDir -replace '\\','/') + '"'),
    '--out-dir', ('"' + ($outDir -replace '\\','/') + '"'),
    '--traceprinter', ('"' + ($hostTp -replace '\\','/') + '"')
  )
  LL ('parser_cmd=python ' + ($pargs -join ' '))
  $parserHow = 'interrupted'
  $parserProc = Start-Process -FilePath $py -ArgumentList $pargs -PassThru -NoNewWindow `
                  -RedirectStandardOutput (Join-Path $attemptDir 'parser-stdout.log') `
                  -RedirectStandardError (Join-Path $attemptDir 'parser-stderr.log')
  $null = $parserProc.Handle
  LL ("PARSER_PID=$($parserProc.Id) started_utc=" + (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') + " bound_s=$ParserSeconds")
  $psw = [System.Diagnostics.Stopwatch]::StartNew()
  try {
    while ($true) {
      if ($parserProc.HasExited) { $parserHow = 'exited'; break }
      if ($psw.Elapsed.TotalSeconds -ge $ParserSeconds) { $parserHow = 'timeout-kill'; break }
      Start-Sleep -Seconds 1
    }
  } finally {
    foreach ($d in (Get-DescendantIds $parserProc.Id)) { $parserDesc.Add($d) }
    $killedDesc = 0
    foreach ($id in @($parserProc.Id) + @($parserDesc)) {
      if (Test-Alive $id) {
        try {
          Stop-Process -Id $id -Force -ErrorAction Stop
          if ($id -ne $parserProc.Id) { $killedDesc++ }
        } catch { }
      }
    }
    foreach ($id in @($parserProc.Id) + @($parserDesc)) { try { Wait-Process -Id $id -Timeout 15 -ErrorAction Stop } catch { } }
    $pAlive = $false
    foreach ($id in @($parserProc.Id) + @($parserDesc)) { if ((Wait-Gone $id 15) -lt 0) { $pAlive = $true } }
    $pExitText = 'none'
    if ($parserProc.HasExited -and $parserHow -eq 'exited') { try { $parserExit = $parserProc.ExitCode; $pExitText = "$parserExit" } catch { } }
    LL "PARSER_STOPPED how=$parserHow exit=$pExitText descendants_killed=$killedDesc alive_after=$(if ($pAlive) { 'yes' } else { 'no' })"
  }

  # 11. Final.
  $survivors = @()
  if (Test-Alive $qemuProc.Id) { $survivors += "qemu:$($qemuProc.Id)" }
  if (Test-Alive $parserProc.Id) { $survivors += "parser:$($parserProc.Id)" }
  foreach ($d in $parserDesc) { if (Test-Alive $d) { $survivors += "parser-descendant:$d" } }
  LL "survivors=$(if ($survivors.Count -gt 0) { $survivors -join ',' } else { 'none' })"
  foreach ($f in @(Get-ChildItem -LiteralPath $outDir -Filter "attempt$Attempt-*" -File)) {
    $flag = ''
    if (-not $f.Name.EndsWith('.log')) { $flag = ' NOT-A-LOG' }
    LL "FILE results/orin-native-port/20260910T2307Z/m4-dryrun/$($f.Name) bytes=$($f.Length)$flag"
  }
  foreach ($f in @(Get-ChildItem -LiteralPath $attemptDir -File)) {
    LL "FILE qhv/m4dry/attempt$Attempt/$($f.Name) bytes=$($f.Length)"
  }
  if (($qemuHow -eq 'exited' -or $qemuHow -eq 'end-grace-kill') -and $parserHow -eq 'exited' -and $parserExit -eq 0 -and $survivors.Count -eq 0) {
    $exitCode = 0
  }
  LL "LAUNCH_EXIT=$exitCode"
} catch {
  $msg = "$_"
  if ($msg -ne 'M4DRY-REFUSED' -and $msg -ne 'M4DRY-CANONICAL-CHANGED') { LL "ERROR: $msg" }
  $exitCode = 1
} finally {
  # Belt and braces: nothing this script started may outlive it.
  if ($null -ne $qemuProc -and (Test-Alive $qemuProc.Id)) {
    try { Stop-Process -Id $qemuProc.Id -Force -ErrorAction Stop } catch { }
    Write-Warning "stopped QEMU pid $($qemuProc.Id) in the outer finally"
  }
  if ($null -ne $parserProc) {
    foreach ($id in @($parserProc.Id) + @($parserDesc)) {
      if (Test-Alive $id) { try { Stop-Process -Id $id -Force -ErrorAction Stop } catch { } }
    }
  }
}
exit $exitCode
