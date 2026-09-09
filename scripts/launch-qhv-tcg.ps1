<#
.SYNOPSIS
  Boot the QHV host (and its auto-started QNX guest) under QEMU-TCG, capture the
  serial log. No KVM required: we emulate an EL2-capable CPU in software so QHV's
  el2-host / VHE comes up.

.DESCRIPTION
  Default behaviour is unchanged from the original script: one boot, capture for
  -CaptureSeconds, dump the serial log.

  -StopOnGuestBanner turns this into a *measurement* instead of a capture: the
  run ends the moment the guest banner appears and the elapsed launch->banner
  time is reported in milliseconds. With -Runs N it repeats that N times and
  writes a '<log>-times.txt' summary in the same 'run N: NNNNN ms' format the
  Phase-4 boot-time diff already uses.

  That measurement mode is the Windows half of the Phase-4 QHV twin diff. The
  Orin half is scripts/orin/launch-qhv-on-orin-tcg.sh, which measures the same
  marker the same way. The QEMU argument list below is duplicated there ON
  PURPOSE (two host OSes, no shared config format) -- if you change one, change
  the other, or the twin diff silently stops comparing like with like.

.NOTES
  Run after scripts\build-qhv.bat. This is intentionally TCG (pure emulation).
  On the Orin side TCG is a hard requirement -- QHV needs EL2 for its guest,
  i.e. nested virtualisation, which ARM KVM does not offer on A78AE -- so
  TCG-on-both is genuine symmetry here, unlike the plain qnx-safety-vm leg
  where Orin runs TCG only because KVM boot is blocked (docs/orin-port.md).
  See docs/findings.md (2026-06-11) and the curated log under logs/sample-boot/.

.EXAMPLE
  .\launch-qhv-tcg.ps1
  Original behaviour: one 185 s capture, prints the serial log.

.EXAMPLE
  .\launch-qhv-tcg.ps1 -Runs 5 -StopOnGuestBanner
  Five timed boots for the twin diff; writes qhv-guest-boot-times.txt.
#>
param(
  [int]$CaptureSeconds = 185,
  [string]$LogPath,
  [int]$Runs = 1,
  [switch]$StopOnGuestBanner,
  [switch]$WithRng
)

$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot  = Split-Path -Parent $scriptDir
$out       = Join-Path $repoRoot 'qhv\host\output'
if (-not $LogPath) { $LogPath = Join-Path $repoRoot 'qhv\qhv-guest-boot.log' }

$qemu = @(
  "C:\Program Files\qemu\qemu-system-aarch64.exe",
  "C:\Program Files\qemu\qemu-system-aarch64w.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $qemu) { throw "qemu-system-aarch64 not found. Install QEMU (winget install SoftwareFreedomConservancy.QEMU)." }

$ifs  = Join-Path $out 'ifs.bin'
$disk = Join-Path $out 'disk-qemu'
foreach ($f in @($ifs,$disk)) { if (-not (Test-Path $f)) { throw "$f not found. Run scripts\build-qhv.bat first." } }

# forward slashes for qemu file= args
$ifsF  = $ifs  -replace '\\','/'
$diskF = $disk -replace '\\','/'

# Progress markers on the shared serial line, in the order they must appear.
#
# NOTE, because the obvious guess is wrong: the QHV *host* prints no banner of
# its own here. This script previously told the reader to look for a host
# banner "QNX qnx-qhv ... QEMU_virt", as does the curation header of
# logs/sample-boot/qhv-tcg-host-and-guest-boot.log -- but no such line exists
# in that log's body or in any run reproduced since. Only the guest prints a
# banner. All three markers below are genuinely emitted.
$markerHost  = '=== AUTO-START QNX GUEST UNDER QVM'   # host reached post_start
$markerQvm   = '=== launching qvm @g2.conf'           # hypervisor invoked
$markerGuest = 'QNX qnx-guest'                        # guest crossed EL2/EL1

# QEMU holds the serial log open while running, so a plain Get-Content can hit
# a sharing violation mid-boot. Open with FileShare.ReadWrite and tolerate
# transient failures by returning empty -- the caller just polls again.
function Read-LogSafe([string]$Path) {
  if (-not (Test-Path $Path)) { return '' }
  try {
    $fs = [System.IO.File]::Open($Path, 'Open', 'Read', 'ReadWrite')
    $sr = New-Object System.IO.StreamReader($fs)
    $text = $sr.ReadToEnd()
    $sr.Close(); $fs.Close()
    return $text
  } catch { return '' }
}

$summaryPath = [System.IO.Path]::ChangeExtension($LogPath, $null).TrimEnd('.') + '-times.txt'
# Stamp provenance into the data itself -- see the matching comment in
# scripts/orin/launch-qhv-on-orin-tcg.sh. Identical argument lists are not
# the same thing as identical QEMUs, and that difference silently invalidated
# the first cross-host attempt.
if ($StopOnGuestBanner) {
  $qemuVer = (& $qemu --version | Select-Object -First 1)
  $cpuName = (Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty Name)
  $provenance = @(
    "# host: Windows $([System.Environment]::OSVersion.Version) $env:PROCESSOR_ARCHITECTURE / $cpuName",
    "# qemu: $qemuVer",
    ("# devices: " + $(if ($WithRng) { "virtio-blk + virtio-net(slirp) + virtio-rng(builtin)" } else { "virtio-blk only (NO rng: entropy init fails and times out, ~+19 s)" })),
    "# disk: -snapshot (guest writes discarded; every run boots the copy-time bytes, so SHA256SUMS keeps holding)",
    "# marker: launch -> guest banner (QNX qnx-guest ... ARMv8_Foundation_Model)",
    "# NOTE: only comparable against a run whose 'qemu:' AND 'devices:' lines both match."
  )
  Set-Content -Path $summaryPath -Value $provenance -Encoding utf8
  Write-Host "qemu: $qemuVer"
}
$failures = 0

for ($run = 1; $run -le $Runs; $run++) {

  if ($Runs -gt 1) {
    $runLog = [System.IO.Path]::ChangeExtension($LogPath, $null).TrimEnd('.') + "$run.log"
  } else {
    $runLog = $LogPath
  }

  # -WithRng: virtio-net (slot filler, user-mode slirp) + virtio-rng in the
  # slot order mkqnximage's runimage assembles and the image's startup.sh
  # binds (rng = slot 3, mem=0xa003a00). Presenting it moved the guest-banner
  # time from ~49.2 s to 29.7 s on this host (2026-09-09): the entropy-less
  # boot spends ~19 s timing out. Runs with and without it are not
  # comparable, so the device set is stamped into the times file.
  $rngArgs = @()
  if ($WithRng) {
    $rngArgs = @('-netdev','user,id=n0','-device','virtio-net-device,netdev=n0',
                 '-object','rng-builtin,id=rng0','-device','virtio-rng-device,rng=rng0')
  }
  $qargs = @(
    '-machine','virt,virtualization=on,gic-version=3',  # virtualization=on => emulated EL2 for QHV
    '-cpu','max','-accel','tcg','-smp','2','-m','2G',
    '-snapshot',   # the raw disk mutates on every boot otherwise (rnd-seed, keys, logs); see the Orin launcher
    '-drive',"file=$diskF,if=none,id=drv0,format=raw",
    '-device','virtio-blk-device,drive=drv0'
  ) + $rngArgs + @(
    '-kernel',$ifsF,
    '-serial',"file:$($runLog -replace '\\','/')",'-display','none','-no-reboot'
  )

  Remove-Item $runLog -ErrorAction SilentlyContinue
  if ($StopOnGuestBanner) {
    Write-Host "[run $run/$Runs] Booting QHV host; stopping at the guest banner (ceiling ${CaptureSeconds}s) ..."
  } else {
    Write-Host "Booting QHV host under QEMU-TCG; guest auto-starts via post_startup."
    Write-Host "Capturing $CaptureSeconds s to $runLog ..."
  }

  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  $p  = Start-Process -FilePath $qemu -ArgumentList $qargs -PassThru -NoNewWindow

  $elapsedMs = $null; $tHost = $null; $tQvm = $null; $tSc = $null
  if ($StopOnGuestBanner) {
    $deadline = (Get-Date).AddSeconds($CaptureSeconds)
    while ((Get-Date) -lt $deadline) {
      # Per-marker wall times -- see the matching comment in the Orin launcher:
      # fixed timeouts common to both hosts dilute the headline ratio.
      $txt = Read-LogSafe $runLog
      $nowMs = [int]$sw.Elapsed.TotalMilliseconds
      if ($null -eq $tHost -and $txt -match [regex]::Escape($markerHost)) { $tHost = $nowMs }
      if ($null -eq $tQvm  -and $txt -match [regex]::Escape($markerQvm))  { $tQvm  = $nowMs }
      if ($null -eq $tSc   -and $txt -match 'Startup complete')           { $tSc   = $nowMs }
      if ($txt -match [regex]::Escape($markerGuest)) {
        $elapsedMs = $nowMs
        break
      }
      if ($p.HasExited) { break }   # QEMU died early; the log will never grow
      Start-Sleep -Milliseconds 100
    }
  } else {
    Start-Sleep -Seconds $CaptureSeconds
  }

  if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force }
  Start-Sleep -Seconds 1

  $logText   = Read-LogSafe $runLog
  $hostSeen  = 'no'; if ($logText -match [regex]::Escape($markerHost))  { $hostSeen  = 'yes' }
  $qvmSeen   = 'no'; if ($logText -match [regex]::Escape($markerQvm))   { $qvmSeen   = 'yes' }
  $guestSeen = 'no'; if ($logText -match [regex]::Escape($markerGuest)) { $guestSeen = 'yes' }

  if ($StopOnGuestBanner) {
    if ($null -ne $elapsedMs) {
      $line = "run ${run}: $elapsedMs ms"
      $ifup = ([regex]::Matches($logText, 'if_up: tries exhausted')).Count
      $seg  = "#   segments run ${run}: host_post_start=$(if ($null -ne $tHost) { $tHost } else { '?' }) qvm_launched=$(if ($null -ne $tQvm) { $tQvm } else { '?' }) guest_startup_complete=$(if ($null -ne $tSc) { $tSc } else { '?' }) guest_banner=$elapsedMs (ms from launch); if_up_exhausted=$ifup"
      Add-Content -Path $summaryPath -Value $seg -Encoding utf8
      Write-Host $seg
    } else {
      $failures++
      $line = "run ${run}: TIMEOUT after ${CaptureSeconds}s (host=$hostSeen qvm=$qvmSeen guest=$guestSeen)"
    }
    Write-Host $line
    Add-Content -Path $summaryPath -Value $line -Encoding utf8
    Write-Host "         host=$hostSeen  qvm=$qvmSeen  guest=$guestSeen  log=$runLog"
  }
}

if ($StopOnGuestBanner) {
  Write-Host "`n========== SUMMARY =========="
  Get-Content $summaryPath
  Write-Host ""
  Write-Host "All three markers must read yes for a run to count, and they fail"
  Write-Host "differently: host=no means QHV never reached post_start; qvm=no means the"
  Write-Host "hypervisor was never invoked; guest=no with the other two yes means qvm ran"
  Write-Host "but nothing came up across the EL2/EL1 boundary. Only the last of those is"
  Write-Host "the interesting failure, and none of them is the same as a timeout."
  Write-Host ""
  Write-Host "Orin counterpart:  ./launch-qhv-on-orin-tcg.sh $Runs"
  Write-Host "Summary written to $summaryPath"
  if ($failures -gt 0) {
    Write-Warning "$failures/$Runs run(s) did not reach the guest banner."
  }
} else {
  Write-Host "`n========== SERIAL LOG =========="
  if (Test-Path $LogPath) {
    Get-Content $LogPath
    Write-Host "`n(Expect: host reaches '=== AUTO-START QNX GUEST UNDER QVM', qvm is launched, then the guest banner 'QNX qnx-guest ... ARMv8_Foundation_Model'. The host itself prints no banner -- see the marker note above.)"
  } else {
    Write-Host "No serial log produced."
  }
}
