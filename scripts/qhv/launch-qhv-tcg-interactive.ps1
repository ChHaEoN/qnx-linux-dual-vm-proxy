<#
.SYNOPSIS
  Boot the QHV host under QEMU-TCG with its serial console exposed on a TCP
  port (instead of a plain log file), and inject a rotating sequence of
  shell commands into the live console while capturing the full transcript.

.DESCRIPTION
  launch-qhv-tcg.ps1 is capture-only (file-backed serial): fine for a clean
  pass/fail run, useless for catching the qvm/virtio-console stall
  (docs/findings.md, ipc-test/qnx-host-client/README.md) IN THE ACT, because
  the stalled qnx-host-client blocks post_startup.sh and the console never
  reaches an interactive shell. This script assumes a build where
  scripts/qhv/post_start.custom instead BACKGROUNDS the client run (so the
  login-less root shell comes up regardless of whether the client is still
  running or has stalled), then repeatedly sends diagnostic commands
  (default: alternating `pidin -p qvm` and a `cat` of the client's
  background log) at a fixed interval so at least some snapshots land
  during a stall, whenever one occurs.

.NOTES
  Needs QEMU for Windows and a QHV host image already built via
  scripts\build-qhv.bat with a BACKGROUNDING post_start.custom -- the
  committed default runs the client in the foreground by design (one clean
  pass/fail per boot) and will never reach a shell if it stalls.

  Security: the serial TCP listener is bound to 127.0.0.1 only. QEMU's
  `tcp:host:port` chardev binds the wildcard address (0.0.0.0, reachable
  from the rest of the LAN) if `host` is left empty -- this exposes an
  unauthenticated QNX root shell for as long as the listener is up, so do
  not remove the explicit 127.0.0.1 to "simplify" this.
#>
param(
  [int]$Port = 4555,
  [int]$CaptureSeconds = 300,
  [int]$ShellReadyDelaySeconds = 130,
  [int]$CommandIntervalSeconds = 2,
  [string[]]$Commands = @('qvm --help', 'pidin -p qvm', 'cat /data/hypervisor/client-diag.log'),
  [string]$LogPath
)

$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot  = Split-Path -Parent (Split-Path -Parent $scriptDir)
$out       = Join-Path $repoRoot 'qhv\host\output'
if (-not $LogPath) { $LogPath = Join-Path $repoRoot 'qhv\qhv-interactive-probe.log' }

$qemu = @(
  "C:\Program Files\qemu\qemu-system-aarch64.exe",
  "C:\Program Files\qemu\qemu-system-aarch64w.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $qemu) { throw "qemu-system-aarch64 not found. Install QEMU (winget install SoftwareFreedomConservancy.QEMU)." }

$ifs  = Join-Path $out 'ifs.bin'
$disk = Join-Path $out 'disk-qemu'
foreach ($f in @($ifs, $disk)) { if (-not (Test-Path $f)) { throw "$f not found. Run scripts\build-qhv.bat first." } }

$ifsF  = $ifs  -replace '\\', '/'
$diskF = $disk -replace '\\', '/'

$qargs = @(
  '-machine', 'virt,virtualization=on,gic-version=3',
  '-cpu', 'max', '-accel', 'tcg', '-smp', '2', '-m', '2G',
  '-drive', "file=$diskF,if=none,id=drv0,format=raw",
  '-device', 'virtio-blk-device,drive=drv0',
  '-kernel', $ifsF,
  '-serial', "tcp:127.0.0.1:$Port,server,nowait", '-display', 'none', '-no-reboot'
)

Remove-Item $LogPath -ErrorAction SilentlyContinue
Write-Host "Booting QHV host under QEMU-TCG; serial console on tcp::$Port; transcript -> $LogPath"
$p = Start-Process -FilePath $qemu -ArgumentList $qargs -PassThru -NoNewWindow

$client = $null
for ($i = 0; $i -lt 40; $i++) {
    try {
        $client = New-Object System.Net.Sockets.TcpClient('127.0.0.1', $Port)
        break
    } catch {
        Start-Sleep -Milliseconds 500
    }
}
if (-not $client) {
    if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force }
    throw "could not connect to tcp::$Port (qemu listener never came up)"
}
Write-Host "Connected to tcp::$Port."

$stream = $client.GetStream()
$logFs  = [System.IO.File]::Open($LogPath, 'Create')
$buf    = New-Object byte[] 8192
$sw     = [System.Diagnostics.Stopwatch]::StartNew()
$cmdIndex   = 0
$nextCmdAt  = $ShellReadyDelaySeconds

try {
    while ($sw.Elapsed.TotalSeconds -lt $CaptureSeconds) {
        if ($stream.DataAvailable) {
            $n = $stream.Read($buf, 0, $buf.Length)
            if ($n -gt 0) {
                $logFs.Write($buf, 0, $n)
                $logFs.Flush()
                [Console]::Out.Write([System.Text.Encoding]::ASCII.GetString($buf, 0, $n))
            }
        } else {
            Start-Sleep -Milliseconds 100
        }

        if ($Commands.Count -gt 0 -and $sw.Elapsed.TotalSeconds -ge $nextCmdAt) {
            $cmdText = $Commands[$cmdIndex % $Commands.Count]
            $bytes = [System.Text.Encoding]::ASCII.GetBytes("$cmdText`r`n")
            $stream.Write($bytes, 0, $bytes.Length)
            $stream.Flush()
            Write-Host "`n[PROBE @ $([int]$sw.Elapsed.TotalSeconds)s] SENT: $cmdText"
            $logBytes = [System.Text.Encoding]::ASCII.GetBytes("`n[PROBE @ $([int]$sw.Elapsed.TotalSeconds)s SENT: $cmdText]`n")
            $logFs.Write($logBytes, 0, $logBytes.Length)
            $cmdIndex++
            $nextCmdAt += $CommandIntervalSeconds
        }
    }
} finally {
    $logFs.Close()
    $client.Close()
    if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force }
}

Write-Host "`nDone. Full transcript in $LogPath"
