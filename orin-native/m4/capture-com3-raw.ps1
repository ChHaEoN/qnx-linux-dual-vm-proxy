<#
.SYNOPSIS
  Capture a serial port to a file byte for byte, with a header that says when
  the capture will end.

.DESCRIPTION
  Phase 3b, results/orin-native-port/20260909T1100Z/m4-design.md §6.1
  (revision 2). The M4 board run's COM3 co-record: every byte the port delivers
  is written unchanged, so the PC can recompute md5, POSIX cksum, byte and line
  counts of the listing blocks the board sends over the TCU.

  Why not the older capture.ps1 (untracked, as M2 and M3 ran it): it reads with
  ReadExisting() into a text StreamWriter, which decodes and re-encodes. That is
  safe for ASCII, not byte-exact.

  The file begins with one ASCII line and a LF:
    --- raw capture started on <Port> at <Baud>, <ISO 8601> epoch=<Unix seconds> seconds=<Seconds> ---
  epoch and seconds let orin-native/startup/m4-board.sh compute how long the
  capture has left (gates A and B, §7.2 item 3). The deadline below is taken
  from the same instant as epoch. Then every byte read until the deadline,
  unchanged and flushed after each read, and finally a LF and
    --- raw capture ended <ISO 8601> bytes=<n> ---
  and a LF. A capture stopped by force has no end line; the harness treats that
  as a capture that did not run to its deadline.

  Launch it from PowerShell, never from a Git Bash background job, which opens
  the port and receives nothing (m2-runs.md:135-137). The port is exclusive:
  stop any older capture first. It is stopped after m4-board.sh run returns, by
  hand or by m4-tloop.ps1; -Seconds is a safety net the harness's own wait
  cannot outlast (§3.3: capture_s = return_bound_s + 3000).

  Evaluation output under NC QDL v7 4.6(i): write it only to a git-ignored path
  (the harness's record directory, whose files end in .log).

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File orin-native\m4\capture-com3-raw.ps1 -Port COM3 -Seconds 6000 -Out results\orin-native-port\<utc>\m4\com3-m4-r0-r0.log
#>
param(
  [string]$Port = 'COM3',
  [ValidateRange(1200, 4000000)][int]$Baud = 115200,
  [ValidateRange(1, 172800)][int]$Seconds = 60,
  [Parameter(Mandatory = $true)][string]$Out
)

$ErrorActionPreference = 'Stop'
$ascii = New-Object System.Text.ASCIIEncoding

function Write-Ascii([System.IO.FileStream]$Fs, [string]$Text) {
  $b = $ascii.GetBytes($Text)
  $Fs.Write($b, 0, $b.Length)
  $Fs.Flush()
}

$outPath = [System.IO.Path]::GetFullPath($Out)
$sp = New-Object System.IO.Ports.SerialPort $Port, $Baud, ([System.IO.Ports.Parity]::None), 8, ([System.IO.Ports.StopBits]::One)
$sp.Handshake    = [System.IO.Ports.Handshake]::None
$sp.DtrEnable    = $true
$sp.RtsEnable    = $true
$sp.ReadTimeout  = 500
$sp.ReadBufferSize = 1048576

try {
  $sp.Open()
} catch {
  [System.IO.File]::WriteAllText($outPath, "FAILED to open ${Port}: $($_.Exception.Message)`n", $ascii)
  exit 1
}

# FileShare.Read, so the harness can copy the file while the capture runs.
$fs = [System.IO.File]::Open($outPath, [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write, [System.IO.FileShare]::Read)
$total = [long]0
$exitCode = 0
try {
  $now      = [DateTimeOffset]::UtcNow
  $epoch    = $now.ToUnixTimeSeconds()
  $deadline = $now.AddSeconds($Seconds)
  Write-Ascii $fs ("--- raw capture started on $Port at $Baud, " + $now.ToString('o') + " epoch=$epoch seconds=$Seconds ---`n")

  $buf = New-Object byte[] 65536
  while ([DateTimeOffset]::UtcNow -lt $deadline) {
    try {
      $n = $sp.BaseStream.Read($buf, 0, $buf.Length)
      if ($n -gt 0) {
        $fs.Write($buf, 0, $n)
        $fs.Flush()
        $total += $n
      }
    } catch [System.TimeoutException] {
      # nothing waiting within ReadTimeout; check the deadline and read again
    } catch [System.IO.IOException] {
      # .NET Framework can report a read timeout on the base stream this way
      if (-not $sp.IsOpen) { throw }
    }
  }
  Write-Ascii $fs ("`n--- raw capture ended " + [DateTimeOffset]::UtcNow.ToString('o') + " bytes=$total ---`n")
} catch {
  try { Write-Ascii $fs ("`n--- raw capture read error: " + $_.Exception.Message + " bytes=$total ---`n") } catch { }
  $exitCode = 1
} finally {
  try { $fs.Close() } catch { }
  try { $sp.Close() } catch { }
}
exit $exitCode
