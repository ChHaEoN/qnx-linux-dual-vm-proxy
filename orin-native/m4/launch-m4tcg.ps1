<#
.SYNOPSIS
  Run one M4 TCG rehearsal attempt: boot a rehearsal QHV host under QEMU-TCG,
  watch its serial file, then run parse-m4.py on it. Both are bounded, and
  neither can outlive this script.

.DESCRIPTION
  Implements results/orin-native-port/20260909T1100Z/m4-design.md §11.3
  (revision 2), derived from orin-native/m4dry/launch-m4dry-tcg.ps1 (steps 1-11)
  with only the design's changes:
    - the same QEMU argument list (its -WithRng list; only the two image paths and
      the serial file changed), -WallSeconds default 7200, -MinFreeGB 4
    - refuses to start while any qemu-system-aarch64 process exists (one QEMU at a
      time); stops QEMU in finally and confirms it gone with a bounded re-check
    - writes qhv/m4tcg/attempt<N>/serial-raw.log (QEMU -serial file: is byte-exact)
      and results/orin-native-port/20260910T2307Z/m4-tcg/attempt<N>-launch.log
    - then runs, bounded by -ParserSeconds, parse-m4.py run --com3-format
      qemu-serial --rehearsal, writing under qhv/m4tcg/attempt<N>/out only
    - canonical hashes after; survivors=none after QEMU and the parser
  Every TCG figure is emulated and never an M4 number (§11.1, §12.1 item 14).
  Order: r0, then k512, then k16 (§11.3).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File orin-native\m4\launch-m4tcg.ps1 -Attempt 1 -Variant r0
#>
param(
  [Parameter(Mandatory = $true)][ValidateRange(1, 9999)][int]$Attempt,
  [ValidateSet('r0','k512','k16')][string]$Variant = 'r0',
  [ValidatePattern('^[a-z0-9]{0,16}$')][string]$Tag = '',
  [string]$QemuPath,
  [ValidateRange(60, 86400)][int]$WallSeconds = 7200,
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
$canonHost  = Join-Path $repoRoot 'qhv\host'
$canonGuest = Join-Path $repoRoot 'qhv\guest'
$runRoot    = Join-Path $repoRoot 'qhv\m4tcg'
$vName      = $Variant
if ($Tag) { $vName = "$Variant-$Tag" }
$imageDir   = Join-Path $runRoot "host-$vName\output"
$stageDir   = Join-Path $runRoot "stage-$vName"
$paramsFile = Join-Path $stageDir 'm4tcg.params'
$attemptDir = Join-Path $runRoot "attempt$Attempt"
$serialLog  = Join-Path $attemptDir 'serial-raw.log'
$parseOut   = Join-Path $attemptDir 'out'
$outDir     = Join-Path $repoRoot 'results\orin-native-port\20260910T2307Z\m4-tcg'
$launchLog  = Join-Path $outDir "attempt$Attempt-launch.log"
$parser     = Join-Path $scriptDir 'parse-m4.py'
$utf8NoBom  = New-Object System.Text.UTF8Encoding $false

# ---------------------------------------------------------------- helpers (as launch-m4dry-tcg.ps1)

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
  throw 'M4TCG-REFUSED'
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
  $sums = Join-Path $imageDir 'M4TCG-SHA256SUMS'
  if (-not (Test-Path -LiteralPath $sums)) { LL "image_$When M4TCG-SHA256SUMS missing"; return $false }
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
  if ($n -ne 2) { LL "image_$When M4TCG-SHA256SUMS lists $n files, expected 2"; $ok = $false }
  return $ok
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
  $ms = [long]$script:sw.Elapsed.TotalMilliseconds
  $script:seen[$Name] = $ms
  LL "MARK $Name pc_ms=$ms"
}

function Test-SerialLine([string]$Raw) {
  $l = $Raw.Trim("`r")
  $m = [regex]::Match($l, '^M4 STATE (\S+)')
  if ($m.Success) {
    Set-Mark ('state:' + $m.Groups[1].Value)
    if ($m.Groups[1].Value -eq 'end' -and $null -eq $script:endSeenMs) { $script:endSeenMs = [long]$script:sw.Elapsed.TotalMilliseconds }
  }
  $m = [regex]::Match($l, '^=M4FLT= (BEGIN|END) name=(\S+)')
  if ($m.Success) { Set-Mark ('flt_' + $m.Groups[1].Value.ToLowerInvariant() + ':' + $m.Groups[2].Value) }
  if ($l.Contains('server: echo endpoint up')) { Set-Mark 'echo_up' }
  if ($l.Contains('QNX qnx-guest')) { Set-Mark 'guest_banner' }
  if ($l.StartsWith('samples=')) { Set-Mark 'samples' }
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
  # 1. Paths, the variant image and its parameters; one QEMU at a time.
  if ((Test-Under $imageDir $canonHost) -or (Test-Under $imageDir $canonGuest)) { Refuse "image directory $imageDir is inside a canonical tree" }
  if (-not (Get-NormPath $imageDir).StartsWith((Get-NormPath $runRoot) + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
    Refuse "image directory $imageDir does not lie under qhv/m4tcg/"
  }
  if (-not (Test-VariantSums 'pre')) { Refuse 'the rehearsal image does not match its M4TCG-SHA256SUMS (build it first)' }
  if (-not (Test-Path -LiteralPath $paramsFile)) { Refuse "no $paramsFile (build-m4tcg-image.ps1 writes it)" }
  $running = @(Get-Process -Name 'qemu-system-aarch64', 'qemu-system-aarch64w' -ErrorAction SilentlyContinue)
  if ($running.Count -gt 0) { Refuse "a qemu-system-aarch64 process is already running (pid $($running[0].Id)); one QEMU at a time" }

  # 2. Canonical checks before.
  if (-not (Test-Canonical 'pre')) { Refuse 'canonical_pre=MISMATCH' }
  LL 'canonical_pre=ok'

  # 3. Output.
  New-Item -ItemType Directory -Force -Path $outDir | Out-Null
  if (@(Get-ChildItem -LiteralPath $outDir -Filter "attempt$Attempt-*" -Force).Count -gt 0) { Refuse "results already hold attempt$Attempt-* files; attempt numbers are never reused" }
  if (Test-Path -LiteralPath $attemptDir) { Refuse "qhv/m4tcg/attempt$Attempt exists; attempt numbers are never reused" }
  New-Item -ItemType Directory -Path $attemptDir | Out-Null
  New-Item -ItemType Directory -Path $parseOut | Out-Null
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
  $qemuVer = (@(& $qemu --version))[0]
  LL ('launch_utc=' + (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'))
  LL "attempt=$Attempt variant=$Variant tag=$(if ($Tag) { $Tag } else { 'none' }) image_dir=qhv/m4tcg/host-$vName/output"
  LL "qemu_version=$qemuVer"
  LL 'devices: virtio-blk + virtio-net(slirp) + virtio-rng(builtin)'
  LL 'disk: -snapshot'
  LL "poll_ms=$PollMs wall_s=$WallSeconds end_grace_s=$EndGraceSeconds parser_s=$ParserSeconds"
  LL 'image=rebuilt-host guest=byte-identical (a rehearsal host; emulated; not an M4 number)'
  LL "params_sha256=$(Get-Sha256 $paramsFile)"

  # 6. The QEMU command: launch-m4dry-tcg.ps1's list, image paths and serial file changed.
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
  if (-not (Test-Canonical 'post')) {
    LL 'canonical_post=CHANGED: something wrote to the canonical images. Stopping everything; tell the owner.'
    throw 'M4TCG-CANONICAL-CHANGED'
  }
  LL 'canonical_post=ok'
  if (-not (Test-VariantSums 'post')) { LL 'image_post=MISMATCH (recorded; -snapshot should have kept it)' }
  LL "pc_free_gb_post=$(Get-FreeGB)"

  # 10. The parser, bounded the way QEMU is.
  $py = (Get-Command python -ErrorAction Stop).Source
  $pargs = @(
    ('"' + ($parser -replace '\\','/') + '"'), 'run',
    '--params', ('"' + ($paramsFile -replace '\\','/') + '"'),
    '--blackbox', 'none',
    '--com3', ('"' + $serialF + '"'),
    '--com3-format', 'qemu-serial',
    '--run-id', "tcg-$Variant-a$Attempt",
    '--out-dir', ('"' + ($parseOut -replace '\\','/') + '"'),
    '--csv', ('"' + ((Join-Path $parseOut 'rehearsal.csv') -replace '\\','/') + '"'),
    '--rehearsal'
  )
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
  $moreQemu = @(Get-Process -Name 'qemu-system-aarch64', 'qemu-system-aarch64w' -ErrorAction SilentlyContinue)
  foreach ($q in $moreQemu) { $survivors += "qemu-other:$($q.Id)" }
  LL "survivors=$(if ($survivors.Count -gt 0) { $survivors -join ',' } else { 'none' })"
  $verdictLine = ''
  $plog = Join-Path $parseOut "tcg-$Variant-a$Attempt-parse.log"
  if (Test-Path -LiteralPath $plog) {
    $vl = Select-String -LiteralPath $plog -Pattern '^M4PC run_verdict=' | Select-Object -First 1
    if ($vl) { $verdictLine = $vl.Line }
  }
  LL "parse_verdict=$(if ($verdictLine) { $verdictLine } else { 'none' })"
  foreach ($f in @(Get-ChildItem -LiteralPath $attemptDir -File)) { LL "FILE qhv/m4tcg/attempt$Attempt/$($f.Name) bytes=$($f.Length)" }
  if (($qemuHow -eq 'exited' -or $qemuHow -eq 'end-grace-kill') -and $parserHow -eq 'exited' -and $parserExit -eq 0 -and $survivors.Count -eq 0) {
    $exitCode = 0
  }
  LL "LAUNCH_EXIT=$exitCode"
} catch {
  $msg = "$_"
  if ($msg -ne 'M4TCG-REFUSED' -and $msg -ne 'M4TCG-CANONICAL-CHANGED') { LL "ERROR: $msg" }
  $exitCode = 1
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
