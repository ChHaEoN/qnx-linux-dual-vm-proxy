<#
.SYNOPSIS
  T0: rehearse M5LOAD.EFI under QEMU with edk2, on the PC, with no board.

.DESCRIPTION
  Phase 3b, results/orin-native-port/20260909T1100Z/m5-design.md §6.1 and §13
  decisions H and I. Each case runs the T0 build of the loader - which embeds
  the contract probe, never a QNX byte - from the firmware's own UEFI Shell.

  Cases:
    T0b  -m 8G, `check`                  -> M5L CHECK PASS, then the Shell
    T0c  -m 8G, `check` then `go`        -> M5L-EBS ok, M5L-JUMP, PROBE ...
    T0d  -m 1536M, `check`               -> M5L REFUSE window: observed
           reason=type, because at 1536M the firmware's runtime services sit
           inside the window
    T0e  a blob byte flipped, `check`    -> M5L REFUSE crc src
    T0f  virtualization=off, `go`        -> M5L REFUSE el=1

  A startup.nsh types the Shell commands. That file exists on the QEMU FAT
  drive only: the design forbids one on any filesystem the board can map
  (§7.4), and this script never writes outside its own output directory.

  Every log is a PC artefact. It still goes to a git-ignored path.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File orin-native\uefi\t0\run-t0.ps1
  powershell -NoProfile -ExecutionPolicy Bypass -File orin-native\uefi\t0\run-t0.ps1 -Case T0c -AcpiOn
#>

param(
  [ValidateSet('all', 'T0b', 'T0c', 'T0d', 'T0e', 'T0f')][string]$Case = 'all',
  [string]$Qemu = 'E:\qemu-versions\qemu-11.1.0\qemu-system-aarch64.exe',
  [ValidateRange(10, 600)][int]$TimeoutSeconds = 90,
  [switch]$AcpiOn,
  [string]$OutDir
)

$ErrorActionPreference = 'Stop'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$uefi = Split-Path -Parent $here
$root = Split-Path -Parent (Split-Path -Parent $uefi)
if (-not $OutDir) { $OutDir = Join-Path $uefi 'out\t0\run' }

$loader = Join-Path $uefi 'out\t0\M5LOAD.EFI'
if (-not (Test-Path $loader)) {
  throw "no T0 build at $loader - run: T0=1 KIMG=... KIMG_SHA256=... ./orin-native/uefi/build-m5-loader.sh"
}
if (-not (Test-Path $Qemu)) { throw "no QEMU at $Qemu" }

$share = Join-Path (Split-Path -Parent $Qemu) 'share'
$code = Join-Path $share 'edk2-aarch64-code.fd'
$vars = Join-Path $share 'edk2-arm-vars.fd'
foreach ($f in @($code, $vars)) { if (-not (Test-Path $f)) { throw "no firmware file at $f" } }

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

function New-Esp {
  param([string]$Name, [string]$Commands, [switch]$CorruptBlob)

  $esp = Join-Path $OutDir "esp-$Name"
  if (Test-Path $esp) { Remove-Item -Recurse -Force $esp }
  New-Item -ItemType Directory -Force -Path $esp | Out-Null
  Copy-Item $loader (Join-Path $esp 'M5LOAD.EFI')

  if ($CorruptBlob) {
    # T0e's negative control: flip one byte inside the embedded payload, so the
    # source CRC must refuse.
    #
    # Not the end of the file. The first attempt flipped 64 bytes from the end
    # and the loader answered CHECK PASS, correctly: the payload is padded to a
    # page and the CRC covers the payload's own length only (design 13 D), so
    # the flip landed in padding. The blob starts at RVA 0x6000, file offsets
    # equal RVAs, and the T0 payload is several hundred bytes, so 0x6100 is
    # inside it.
    $path = Join-Path $esp 'M5LOAD.EFI'
    $bytes = [System.IO.File]::ReadAllBytes($path)
    $i = 0x6100
    if ($i -ge $bytes.Length) { throw "T0e: offset $i is past the image ($($bytes.Length) bytes)" }
    $bytes[$i] = $bytes[$i] -bxor 0xFF
    [System.IO.File]::WriteAllBytes($path, $bytes)
  }

  # The Shell types these; QEMU only (§7.4).
  $nsh = "@echo -off`r`nfs0:`r`n$Commands`r`nreset -s`r`n"
  [System.IO.File]::WriteAllText((Join-Path $esp 'startup.nsh'), $nsh, [System.Text.ASCIIEncoding]::new())
  return $esp
}

function Invoke-Case {
  param([string]$Name, [string]$Memory, [string]$Commands, [switch]$NoVirt, [switch]$CorruptBlob)

  $esp = New-Esp -Name $Name -Commands $Commands -CorruptBlob:$CorruptBlob
  $log = Join-Path $OutDir "$Name.log"
  $scratchVars = Join-Path $OutDir "$Name-vars.fd"
  Copy-Item $vars $scratchVars -Force

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

$cases = @{
  T0b = { Invoke-Case -Name 'T0b' -Memory '8G' -Commands 'M5LOAD.EFI check' }
  T0c = { Invoke-Case -Name 'T0c' -Memory '8G' -Commands "M5LOAD.EFI check`r`nM5LOAD.EFI go" }
  T0d = { Invoke-Case -Name 'T0d' -Memory '1536M' -Commands 'M5LOAD.EFI check' }
  T0e = { Invoke-Case -Name 'T0e' -Memory '8G' -Commands 'M5LOAD.EFI check' -CorruptBlob }
  T0f = { Invoke-Case -Name 'T0f' -Memory '8G' -Commands "M5LOAD.EFI go" -NoVirt }
}

$order = if ($Case -eq 'all') { @('T0b', 'T0c', 'T0d', 'T0e', 'T0f') } else { @($Case) }
$results = @()
foreach ($name in $order) { $results += & $cases[$name] }

Write-Host ''
Write-Host '--- T0 summary (the verdict is m5-design 6.1: read every token against its expected line) ---'
foreach ($r in $results) {
  Write-Host ("{0}: exited={1} log={2}" -f $r.Case, $r.Exited, $r.Log)
  foreach ($t in $r.Tokens) { Write-Host "    $t" }
  if (-not $r.Tokens) { Write-Host '    (no loader token: read the log in full)' }
}
Write-Host ''
Write-Host 'T0 says nothing about cache coherency after the copy (m5-design 6.1, R33): that is board-only.'
Write-Host 'No QNX byte ran here: the T0 build embeds the contract probe.'
