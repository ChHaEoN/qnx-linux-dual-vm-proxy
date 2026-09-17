<#
.SYNOPSIS
  Run one S1-F TCG rehearsal attempt: boot an S1 rehearsal QHV host under
  QEMU-TCG, watch its serial file, then run parse-s1.py on it. Both are bounded,
  and neither can outlive this script.

.DESCRIPTION
  Implements results/orin-native-port/20260909T1100Z/s1-design.md §4.2's
  launch-s1tcg.ps1 row and the PC side of §6.2-§6.4 (revision 2; the owner took
  D1-D19 as recommended), derived from orin-native/m4/launch-m4tcg.ps1 with only
  the design's changes:
    - the same QEMU argument list, changing only -smp 2 to -smp 4 (D5: the
      configuration pins _cpu-1 to _cpu-3), the two image paths and the serial
      file; stamped smp=4 not-a-twin-leg
    - -Mode dryrun|boot|hold|q2 names the host script mode the image was built
      with (build-s1tcg-image.ps1 -Mode); a mismatch with the image's
      s1tcg.params is refused. It also selects parse-s1.py's step: dryrun T1,
      boot T2, hold T3, q2 T3-q2; -Variant j1 (dryrun) adds --diag j1, step T-J1
      (revision 3, §15.5 B8.5: memcanary-w's self-test; never a pass run)
    - refuses to start while any qemu-system-aarch64 process exists (one QEMU at a
      time); stops QEMU in finally and confirms it gone with a bounded re-check
    - writes qhv/s1tcg/attempt<N>/serial-raw.log (QEMU -serial file: is
      byte-exact) and qhv/s1tcg/attempt<N>/launch.log (§2 rule 10: TCG raw files
      under qhv/s1tcg/attempt<N>/)
    - then runs, bounded by -ParserSeconds, parse-s1.py run --profile tcg
      --mode <mode> with --conf (the staged configuration), --image and --initrd
      (the PC payload the image was built from), writing parse-s1.txt and the
      decoded s1-fdt.dtb into qhv/s1tcg/attempt<N>/
    - canonical hashes after; survivors=none after QEMU and the parser
    - no elapsed times and no stream sizes are logged (§2 rule 8, Q7): the
      watcher keeps its clock for its bounds only
  Every TCG result is emulated and never a board result (§10). LAUNCH_EXIT=0 means
  QEMU ended by itself or after the end grace, the parser gave a verdict and
  nothing survived; the verdict itself is parse-s1.txt's (LAUNCH_VERDICT).

  -CheckOnly runs steps 1, 2 and 4 (paths, image sums, params and payload
  re-hash, no QEMU running, canonical hashes, PC memory) and prints the QEMU
  argument list; it creates no attempt directory, starts no process and writes
  no file.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File orin-native\s1\launch-s1tcg.ps1 -Attempt 1 -Variant lin -Mode dryrun -Tag t1a -QemuPath E:\qemu-versions\qemu-11.1.0\qemu-system-aarch64.exe
#>
param(
  [Parameter(Mandatory = $true)][ValidateRange(1, 9999)][int]$Attempt,
  [ValidateSet('lin','hold','q2','d1','d2','j1')][string]$Variant = 'lin',
  [Parameter(Mandatory = $true)][ValidateSet('dryrun','boot','hold','q2')][string]$Mode,
  [Parameter(Mandatory = $true)][ValidatePattern('^[a-z0-9]{1,16}$')][string]$Tag,
  [string]$QemuPath,
  [ValidateRange(60, 86400)][int]$WallSeconds = 7200,
  [ValidateRange(1, 3600)][int]$EndGraceSeconds = 90,
  [ValidateRange(10, 5000)][int]$PollMs = 50,
  [ValidateRange(0, 1024)][double]$MinFreeGB = 4,
  [ValidateRange(60, 86400)][int]$ParserSeconds = 600,
  [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'

$GuestIfsPin  = '434647a7cabfe5a1b503fab6c6309894aceccd03d74bb3882ea81caff22a83bd'
$GuestDiskPin = '55571618524e6cbc7a691b8109734783b479261a2f97206b71fa75f07ee31477'

# build-s1tcg-image.ps1's variant table; the image directory names the mode when a variant has more than one.
$VariantModes = @{ 'lin' = @('boot', 'dryrun'); 'hold' = @('hold'); 'q2' = @('q2'); 'd1' = @('boot', 'dryrun'); 'd2' = @('boot'); 'j1' = @('dryrun') }
if ($VariantModes[$Variant] -notcontains $Mode) {
  Write-Host "REFUSED: -Variant $Variant is built with -Mode $($VariantModes[$Variant] -join '|'), not $Mode"
  exit 1
}

$scriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot   = [System.IO.Path]::GetFullPath((Join-Path $scriptDir '..\..')).TrimEnd('\')
$canonHost  = Join-Path $repoRoot 'qhv\host'
$canonGuest = Join-Path $repoRoot 'qhv\guest'
$runRoot    = Join-Path $repoRoot 'qhv\s1tcg'
$vName      = $Variant
if ($VariantModes[$Variant].Count -gt 1) { $vName = "$Variant-$Mode" }
$vName      = "$vName-$Tag"
$imageDir   = Join-Path $runRoot "host-$vName\output"
$stageDir   = Join-Path $runRoot "stage-$vName"
$paramsFile = Join-Path $stageDir 's1tcg.params'
$attemptDir = Join-Path $runRoot "attempt$Attempt"
$serialLog  = Join-Path $attemptDir 'serial-raw.log'
$launchLog  = Join-Path $attemptDir 'launch.log'
$parser     = Join-Path $scriptDir 'parse-s1.py'
$utf8NoBom  = New-Object System.Text.UTF8Encoding $false

# ---------------------------------------------------------------- helpers (as launch-m4tcg.ps1)

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
  throw 'S1TCG-REFUSED'
}

function Get-Sha256([string]$Path) { return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant() }
function Get-NormPath([string]$Path) { return ([System.IO.Path]::GetFullPath($Path) -replace '/','\').TrimEnd('\') }

function Test-Under([string]$Path, [string]$Base) {
  $a = Get-NormPath $Path
  $b = Get-NormPath $Base
  return ($a -ieq $b) -or $a.StartsWith($b + '\', [System.StringComparison]::OrdinalIgnoreCase)
}

function Test-Alive([int]$Id) {
  try { $p = Get-Process -Id $Id -ErrorAction Stop } catch { return $false }
  try { if ($p.HasExited) { return $false } } catch { }
  return $true
}

function Wait-Gone([int]$Id, [int]$Seconds) {
  $gw = [System.Diagnostics.Stopwatch]::StartNew()
  while ($gw.Elapsed.TotalSeconds -lt $Seconds) {
    if (-not (Test-Alive $Id)) { return $true }
    Start-Sleep -Milliseconds 100
  }
  return (-not (Test-Alive $Id))
}

function Get-FreeGB {
  $os = Get-CimInstance -ClassName Win32_OperatingSystem
  return [math]::Round(([double]$os.FreePhysicalMemory) / 1MB, 2)
}

function Test-Canonical([string]$When) {
  $ok = $true
  $sums = Join-Path $canonHost 'output\SHA256SUMS'
  if (-not (Test-Path -LiteralPath $sums)) { LL "canonical_$When qhv/host/output/SHA256SUMS missing"; return $false }
  $n = 0
  foreach ($line in [System.IO.File]::ReadAllLines($sums)) {
    $m = [regex]::Match($line, '^([0-9a-fA-F]{64}) [ *]?(\S+)\s*$')
    if (-not $m.Success) { continue }
    $got = Get-Sha256 (Join-Path $canonHost ('output\' + $m.Groups[2].Value))
    $state = 'ok'
    if ($got -ne $m.Groups[1].Value.ToLowerInvariant()) { $state = 'CHANGED'; $ok = $false }
    LL "canonical_$When qhv/host/output/$($m.Groups[2].Value) sha256=$got $state"
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

function Test-VariantSums([string]$When) {
  $sums = Join-Path $imageDir 'S1TCG-SHA256SUMS'
  if (-not (Test-Path -LiteralPath $sums)) { LL "image_$When S1TCG-SHA256SUMS missing"; return $false }
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
  if ($n -ne 2) { LL "image_$When S1TCG-SHA256SUMS lists $n files, expected 2"; $ok = $false }
  return $ok
}

function Read-Params([string]$Path) {
  $h = @{}
  foreach ($line in [System.IO.File]::ReadAllLines($Path)) {
    if ($line -match '^\s*(#|$)') { continue }
    $k = $line.IndexOf('=')
    if ($k -lt 1) { continue }
    $h[$line.Substring(0, $k)] = $line.Substring($k + 1)
  }
  return $h
}

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

# ---------------------------------------------------------------- serial watcher

$script:sw        = $null
$script:offset    = [long]0
$script:carry     = ''
$script:seen      = @{}
$script:endSeenMs = $null
$latin1 = [System.Text.Encoding]::GetEncoding(28591)

function Set-Mark([string]$Name) {
  if ($script:seen.ContainsKey($Name)) { return }
  $script:seen[$Name] = $true
  LL "MARK $Name"
}

function Test-SerialLine([string]$Raw) {
  $l = $Raw.Trim("`r")
  $m = [regex]::Match($l, '^S1 STATE (\S+)')
  if ($m.Success) { Set-Mark ('state:' + $m.Groups[1].Value) }
  $m = [regex]::Match($l, '^S1 (CONFIG|DRYRUN|GATE mem ok|HOLD start|HOLD end|FAIL)(\s|$)')
  if ($m.Success) { Set-Mark ($m.Groups[1].Value.ToLowerInvariant() -replace ' ', '_') }
  $m = [regex]::Match($l, '^S1 (BEGIN|END) name=(\S+)')
  if ($m.Success) { Set-Mark ('export_' + $m.Groups[1].Value.ToLowerInvariant() + ':' + $m.Groups[2].Value) }
  $m = [regex]::Match($l, '^STAMP (\S+)')
  if ($m.Success) { Set-Mark ('stamp:' + $m.Groups[1].Value) }
  $m = [regex]::Match($l, '^S1 HB k=(\d+)')
  if ($m.Success) { Set-Mark ('hb:' + $m.Groups[1].Value) }
  if ($l.Contains('QNX qnx-guest')) { Set-Mark 'guest_banner' }
  # S1 FAIL_STATE prints twice: after the summary, and again after the pl011 and hvc0 exports and the capped
  # diagnostics. So it only marks; the end grace starts at the host script's last record, 'S1 STATE end',
  # which comes just before post_start's shutdown.
  $m = [regex]::Match($l, '^S1 FAIL_STATE (\S+)')
  if ($m.Success) { Set-Mark ('fail_state:' + $m.Groups[1].Value) }
  if ($l -ceq 'S1 STATE end') {
    if ($null -eq $script:endSeenMs) { $script:endSeenMs = [long]$script:sw.Elapsed.TotalMilliseconds }
  }
}

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
  # 1. Paths, the variant image, its parameters and payload; one QEMU at a time.
  if ((Test-Under $imageDir $canonHost) -or (Test-Under $imageDir $canonGuest)) { Refuse "image directory $imageDir is inside a canonical tree" }
  if (-not (Get-NormPath $imageDir).StartsWith((Get-NormPath $runRoot) + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
    Refuse "image directory $imageDir does not lie under qhv/s1tcg/"
  }
  if (-not (Test-VariantSums 'pre')) { Refuse 'the rehearsal image does not match its S1TCG-SHA256SUMS (build it first)' }
  if (-not (Test-Path -LiteralPath $paramsFile)) { Refuse "no $paramsFile (build-s1tcg-image.ps1 writes it)" }
  $prm = Read-Params $paramsFile
  foreach ($kv in @(@('profile', 'tcg'), @('variant', $Variant), @('mode', $Mode), @('tag', $Tag))) {
    if ($prm[$kv[0]] -ne $kv[1]) { Refuse "s1tcg.params $($kv[0])=$($prm[$kv[0]]), this launch wants $($kv[1]) (the mode is inside the image)" }
  }
  # The wall bound must outlast the host script's worst case (make-s1-images.sh's ksh_worst_s, copied into
  # s1tcg.params by the builder) plus 1800 s for the TCG host's boot and shutdown. The default is raised to that;
  # an explicit -WallSeconds below it is refused, since the kill would cut a valid run short.
  $kshWorst = 0
  if ("$($prm['ksh_worst_s'])" -match '^\d+$') { $kshWorst = [int]$prm['ksh_worst_s'] }
  if ($kshWorst -gt 0 -and $WallSeconds -lt ($kshWorst + 1800)) {
    if ($PSBoundParameters.ContainsKey('WallSeconds')) {
      Refuse "-WallSeconds $WallSeconds is below the host script's worst case ksh_worst_s=$kshWorst plus 1800 s ($($kshWorst + 1800))"
    }
    $WallSeconds = $kshWorst + 1800
  }
  if ($kshWorst -eq 0) { LL 'note: s1tcg.params carries no ksh_worst_s; the wall bound is -WallSeconds as given' }
  $payload = @{}
  foreach ($pk in @(@('image_src', 'image_sha256'), @('initrd_src', 'initrd_sha256'), @('conf', 'conf_sha256'))) {
    $rel = $prm[$pk[0]]
    if (-not $rel -or $rel -match '(^|/)\.\.(/|$)' -or $rel.Contains(':')) { Refuse "s1tcg.params $($pk[0]) is not a repository-relative path: '$rel'" }
    $p = Join-Path $repoRoot ($rel -replace '/','\')
    if (-not (Test-Path -LiteralPath $p)) { Refuse "$rel (s1tcg.params $($pk[0])) is missing" }
    $got = Get-Sha256 $p
    if ($got -ne $prm[$pk[1]]) { Refuse "$rel sha256=$got differs from s1tcg.params $($pk[1])=$($prm[$pk[1]]): the parser's pins would not be the image's" }
    LL "payload $rel sha256=$got ok"
    $payload[$pk[0]] = $p
  }
  $running = @(Get-Process -Name 'qemu-system-aarch64', 'qemu-system-aarch64w' -ErrorAction SilentlyContinue)
  if ($running.Count -gt 0) { Refuse "a qemu-system-aarch64 process is already running (pid $($running[0].Id)); one QEMU at a time" }

  # 2. Canonical checks before.
  if (-not (Test-Canonical 'pre')) { Refuse 'canonical_pre=MISMATCH' }
  LL 'canonical_pre=ok'

  # 3. Output.
  if (Test-Path -LiteralPath $attemptDir) { Refuse "qhv/s1tcg/attempt$Attempt exists; attempt numbers are never reused" }
  if (-not $CheckOnly) {
    New-Item -ItemType Directory -Path $attemptDir | Out-Null
    $script:launchReady = $true
    foreach ($l in $script:pending) { [System.IO.File]::AppendAllText($launchLog, $l + "`n", $utf8NoBom) }
    $script:pending.Clear()
  }

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
  LL ('launch_utc=' + (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'))
  LL "attempt=$Attempt variant=$Variant mode=$Mode tag=$Tag image_dir=qhv/s1tcg/host-$vName/output diagnostic=$($prm['diagnostic'])"
  if ($CheckOnly) {
    LL "qemu_path=$qemu (version not read under -CheckOnly: nothing is started)"
  } else {
    $qemuVer = (@(& $qemu --version))[0]
    LL "qemu_version=$qemuVer"
  }
  LL 'devices: virtio-blk + virtio-net(slirp) + virtio-rng(builtin)'
  LL 'disk: -snapshot'
  LL 'smp=4 not-a-twin-leg (s1-design.md D5; the twin launchers keep -smp 2)'
  LL "poll_ms=$PollMs wall_s=$WallSeconds end_grace_s=$EndGraceSeconds parser_s=$ParserSeconds"
  LL 'image=rebuilt-host guest=byte-identical (a rehearsal host; emulated; never a board result)'
  LL "params_sha256=$(Get-Sha256 $paramsFile) conf_sha256=$($prm['conf_sha256']) ksh_sha256=$($prm['ksh_sha256']) ksh_source=$($prm['ksh_source'])"

  # 6. The QEMU command: launch-m4tcg.ps1's list, -smp 2 -> 4, image paths and serial file changed.
  $ifsF    = (Join-Path $imageDir 'ifs.bin') -replace '\\','/'
  $diskF   = (Join-Path $imageDir 'disk-qemu') -replace '\\','/'
  $serialF = $serialLog -replace '\\','/'
  $qargs = @(
    '-machine','virt,virtualization=on,gic-version=3',
    '-cpu','max','-accel','tcg','-smp','4','-m','2G',
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
  if ($CheckOnly) {
    LL "CHECK_ONLY_OK attempt=$Attempt variant=$Variant mode=$Mode tag=$Tag (no attempt directory, no process started, no file written)"
    $exitCode = 0
    throw 'S1TCG-CHECKONLY-DONE'
  }

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
    $qGone = Wait-Gone $qemuProc.Id 15
    $qExit = 'none'
    if ($qemuProc.HasExited) { try { $qExit = "$($qemuProc.ExitCode)" } catch { $qExit = 'none' } }
    Read-SerialTail $true
    LL "QEMU_STOPPED how=$qemuHow exit=$qExit alive_after=$(if ($qGone) { 'no' } else { 'yes' }) fail_state_seen=$(if ($null -ne $script:endSeenMs) { 'yes' } else { 'no' })"
  }

  # 9. After the run.
  if (-not (Test-Canonical 'post')) {
    LL 'canonical_post=CHANGED: something wrote to the canonical images. Stopping everything; tell the owner.'
    throw 'S1TCG-CANONICAL-CHANGED'
  }
  LL 'canonical_post=ok'
  if (-not (Test-VariantSums 'post')) { LL 'image_post=MISMATCH (recorded; -snapshot should have kept it)' }
  LL "pc_free_gb_post=$(Get-FreeGB)"

  # 10. The parser, bounded the way QEMU is.
  $py = (Get-Command python -ErrorAction Stop).Source
  $pargs = @(
    ('"' + ($parser -replace '\\','/') + '"'), 'run',
    ('"' + $serialF + '"'),
    '--profile', 'tcg',
    '--mode', $Mode,
    '--out-dir', ('"' + ($attemptDir -replace '\\','/') + '"'),
    '--conf', ('"' + ($payload['conf'] -replace '\\','/') + '"'),
    '--image', ('"' + ($payload['image_src'] -replace '\\','/') + '"'),
    '--initrd', ('"' + ($payload['initrd_src'] -replace '\\','/') + '"')
  )
  # §15.5 B8.5: the j1 variant is T-J1, parse-s1.py's --diag j1 on the TCG dryrun (no --arm or --fill-factor).
  if ($Variant -eq 'j1') { $pargs += @('--diag', 'j1') }
  LL ('parser_cmd=python ' + ($pargs -join ' '))
  $parserHow = 'interrupted'
  $parserProc = Start-Process -FilePath $py -ArgumentList $pargs -PassThru -NoNewWindow `
                  -RedirectStandardOutput (Join-Path $attemptDir 'parser-stdout.log') `
                  -RedirectStandardError (Join-Path $attemptDir 'parser-stderr.log')
  $null = $parserProc.Handle
  LL ("PARSER_PID=$($parserProc.Id) bound_s=$ParserSeconds")
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
    $pAlive = $false
    foreach ($id in @($parserProc.Id) + @($parserDesc)) { if (-not (Wait-Gone $id 15)) { $pAlive = $true } }
    $pExitText = 'none'
    if ($parserProc.HasExited -and $parserHow -eq 'exited') { try { $parserExit = $parserProc.ExitCode; $pExitText = "$parserExit" } catch { } }
    LL "PARSER_STOPPED how=$parserHow exit=$pExitText descendants_killed=$killedDesc alive_after=$(if ($pAlive) { 'yes' } else { 'no' })"
  }

  # 11. Final.
  $survivors = @()
  if (Test-Alive $qemuProc.Id) { $survivors += "qemu:$($qemuProc.Id)" }
  if (Test-Alive $parserProc.Id) { $survivors += "parser:$($parserProc.Id)" }
  foreach ($d in $parserDesc) { if (Test-Alive $d) { $survivors += "parser-descendant:$d" } }
  $moreQemu = @(Get-Process -Name 'qemu-system-aarch64', 'qemu-system-aarch64w' -ErrorAction SilentlyContinue)
  foreach ($q in $moreQemu) { $survivors += "qemu-other:$($q.Id)" }
  LL "survivors=$(if ($survivors.Count -gt 0) { $survivors -join ',' } else { 'none' })"
  $verdictLine = ''
  $ptxt = Join-Path $attemptDir 'parse-s1.txt'
  if (Test-Path -LiteralPath $ptxt) {
    $vl = Select-String -LiteralPath $ptxt -Pattern '^S1PC verdict=' | Select-Object -First 1
    if ($vl) { $verdictLine = $vl.Line }
  }
  LL "LAUNCH_VERDICT=$(if ($verdictLine) { $verdictLine } else { 'none' })"
  foreach ($f in @(Get-ChildItem -LiteralPath $attemptDir -File)) { LL "FILE qhv/s1tcg/attempt$Attempt/$($f.Name)" }
  if (($qemuHow -eq 'exited' -or $qemuHow -eq 'end-grace-kill') -and $parserHow -eq 'exited' -and $parserExit -eq 0 -and $survivors.Count -eq 0) {
    $exitCode = 0
  }
  LL "LAUNCH_EXIT=$exitCode"
} catch {
  $msg = "$_"
  if ($msg -eq 'S1TCG-CHECKONLY-DONE') {
    $exitCode = 0
  } else {
    if ($msg -ne 'S1TCG-REFUSED' -and $msg -ne 'S1TCG-CANONICAL-CHANGED') { LL "ERROR: $msg" }
    $exitCode = 1
  }
} finally {
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
