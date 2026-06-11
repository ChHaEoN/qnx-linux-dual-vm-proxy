<#
.SYNOPSIS
  Boot the QHV host (and its auto-started QNX guest) under QEMU-TCG, capture the
  serial log. No KVM required: we emulate an EL2-capable CPU in software so QHV's
  el2-host / VHE comes up.

.NOTES
  Run after scripts\build-qhv.bat. AWS non-metal Graviton has no /dev/kvm, so this
  is intentionally TCG (pure emulation): it validates the QHV *software* stack, not
  hardware timing. See docs/findings.md (2026-06-11) and the curated log under
  logs/sample-boot/.
#>
param(
  [int]$CaptureSeconds = 185,
  [string]$LogPath
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

$qargs = @(
  '-machine','virt,virtualization=on,gic-version=3',  # virtualization=on => emulated EL2 for QHV
  '-cpu','max','-accel','tcg','-smp','2','-m','2G',
  '-drive',"file=$diskF,if=none,id=drv0,format=raw",
  '-device','virtio-blk-device,drive=drv0',
  '-kernel',$ifsF,
  '-serial',"file:$LogPath",'-display','none','-no-reboot'
)

Remove-Item $LogPath -ErrorAction SilentlyContinue
Write-Host "Booting QHV host under QEMU-TCG; guest auto-starts via post_startup."
Write-Host "Capturing $CaptureSeconds s to $LogPath ..."
$p = Start-Process -FilePath $qemu -ArgumentList $qargs -PassThru -NoNewWindow
Start-Sleep -Seconds $CaptureSeconds
if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force }
Start-Sleep -Seconds 1

Write-Host "`n========== SERIAL LOG =========="
if (Test-Path $LogPath) {
  Get-Content $LogPath
  Write-Host "`n(Look for two banners: host 'qnx-qhv / QEMU_virt' then guest 'qnx-guest / ARMv8_Foundation_Model'.)"
} else {
  Write-Host "No serial log produced."
}
