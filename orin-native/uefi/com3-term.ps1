<#
.SYNOPSIS
  A two-way COM3 terminal for the M5 board session, with key forwarding
  disarmed by default.

.DESCRIPTION
  Phase 3b, results/orin-native-port/20260909T1100Z/m5-design.md §4.2 (the six
  requirements), decision D7, and §2 rule 6: "com3-term.ps1 sends nothing until
  the operator arms it, and disarms itself after the Enter that follows go. An
  autoboot after a reset must never meet a stray key."

  That rule is the whole point of this script. Every M0-M4 board run had the
  adapter's TX unconnected; M5 is the first session that can type into the
  board's UART, and a stray byte at the firmware's "Press ESC" prompt would stop
  autoboot and leave the board in a menu instead of L4T.

  DISARMING IS THE SAFE DIRECTION, AND THE TRACKER IS NOT TRUSTED.
  An adversarial review of the first version found the auto-disarm failing open:
  it tracked the typed line by appending the bytes it sent, so an arrow key's
  escape sequence entered the line as text, and a `go` recalled from Shell
  history or corrected with the arrows did not match - leaving forwarding ARMED
  through `go`, the image's reset and the firmware countdown, which is the exact
  state rule 6 exists to prevent. Now anything the tracker cannot model marks
  the line unreliable, and the next Enter disarms on either that flag or a `go`
  match. A benign straight-typed line (ver, map -r, ls, fs0:) still leaves the
  terminal armed, as §6.5 needs; every cursor-edited or recalled line costs one
  extra F12.

  The received side is byte-exact, like orin-native/m4/capture-com3-raw.ps1:
  every byte the port delivers is written to -Out unchanged, between that
  script's own header and end lines. `seconds=` has no meaning here, because a
  terminal session has no deadline, so it is written as 0. A read error writes
  the error end line that script uses, so a truncated capture never looks clean.

  Both logs are created, never overwritten: the procedure's retry path would
  otherwise destroy the previous attempt's record.

  COM3 is exclusive: stop any capture first. Launch from PowerShell, never from
  a Git Bash background job, which opens the port and receives nothing
  (m2-runs.md:135-137).

.PARAMETER SelfTest
  Runs the encoder, the tracker and the go-line detector against a table of
  cases and exits. Needs no port, no console input and no board. Everything
  else in this script is untestable until the session itself.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File orin-native\uefi\com3-term.ps1 -SelfTest

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File orin-native\uefi\com3-term.ps1 `
    -Out results\orin-native-port\<utc>\m5\com3-m5-r1.log
#>

param(
  [string]$Port = 'COM3',
  [ValidateRange(1200, 4000000)][int]$Baud = 115200,
  [string]$Out,
  [string]$KeyLog,
  [switch]$SelfTest
)

$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------- pure parts
#
# Kept free of the port, the console and the filesystem so that -SelfTest can
# exercise them. The send path is the dangerous one: it is the only code that
# can put a byte on the board's UART.

# The only keys that may ever be sent (§4.2 requirement 4). Anything not listed
# here is ignored, not guessed at.
function Get-SendBytes {
  param([System.ConsoleKeyInfo]$Key)

  switch ($Key.Key) {
    ([System.ConsoleKey]::Escape)     { return , ([byte[]](0x1b)) }
    ([System.ConsoleKey]::UpArrow)    { return , ([byte[]](0x1b, 0x5b, 0x41)) }
    ([System.ConsoleKey]::DownArrow)  { return , ([byte[]](0x1b, 0x5b, 0x42)) }
    ([System.ConsoleKey]::RightArrow) { return , ([byte[]](0x1b, 0x5b, 0x43)) }
    ([System.ConsoleKey]::LeftArrow)  { return , ([byte[]](0x1b, 0x5b, 0x44)) }
    ([System.ConsoleKey]::Enter)      { return , ([byte[]](0x0d)) }
    ([System.ConsoleKey]::Backspace)  { return , ([byte[]](0x08)) }
  }

  # Printable ASCII as itself. Control characters are never forwarded, so a
  # stray Ctrl+something cannot reach the firmware.
  $c = [int]$Key.KeyChar
  if ($c -ge 0x20 -and $c -le 0x7e) { return , ([byte[]]($c)) }

  return $null
}

# The tracked line, and whether it can still be trusted. Returns a hashtable so
# the caller cannot forget the second half.
#   Line      what has been typed since the last Enter
#   Unknown   the tracker lost fidelity: an escape sequence was sent, or the
#             operator re-armed mid-line. The next Enter then disarms.
function Update-TypedLine {
  param([string]$Line, [bool]$Unknown, [byte[]]$Bytes)

  foreach ($b in $Bytes) {
    if ($b -eq 0x1b) {
      # An escape or an arrow. The firmware's own line editor moves the cursor
      # or recalls history, and this tracker cannot follow that, so it says so
      # instead of pretending: the next Enter disarms.
      $Unknown = $true
      return @{ Line = $Line; Unknown = $Unknown }
    }
    if ($b -eq 0x0d) { return @{ Line = ''; Unknown = $false } }
    if ($b -eq 0x08) {
      if ($Line.Length -gt 0) { $Line = $Line.Substring(0, $Line.Length - 1) }
      continue
    }
    if ($b -ge 0x20 -and $b -le 0x7e) { $Line += [char]$b }
  }
  return @{ Line = $Line; Unknown = $Unknown }
}

# Requirement 5: the Enter that ends a typed line reading "M5LOAD.EFI go".
# Case-insensitive, tolerant of surrounding and repeated spaces, of a leading
# device or path prefix, and of the Shell's ".EFI"-less shorthand - all of
# which the Shell accepts, so this must too.
function Test-GoLine {
  param([string]$Line)

  if ($null -eq $Line) { return $false }
  $s = $Line.Trim()
  if ($s.Length -eq 0) { return $false }
  $s = [System.Text.RegularExpressions.Regex]::Replace($s, '\s+', ' ')
  $s = $s.ToUpperInvariant()
  $s = [System.Text.RegularExpressions.Regex]::Replace($s, '^[A-Z0-9]+:', '')
  $i = $s.LastIndexOf('\')
  if ($i -ge 0) { $s = $s.Substring($i + 1) }
  return ($s -eq 'M5LOAD.EFI GO' -or $s -eq 'M5LOAD GO')
}

# Would this keypress end the session? Layout-independent: ']' is not on Oem6
# on several European layouts, where AltGr is Ctrl+Alt and the same keypress
# could otherwise reach the send path.
function Test-ExitKey {
  param([System.ConsoleKeyInfo]$Key)

  if ($Key.Key -eq [System.ConsoleKey]::F10) { return $true }
  if (($Key.Modifiers -band [System.ConsoleModifiers]::Control) -and
      -not ($Key.Modifiers -band [System.ConsoleModifiers]::Alt)) {
    if ($Key.Key -eq [System.ConsoleKey]::Oem6) { return $true }
    if ([int]$Key.KeyChar -eq 0x1d) { return $true }
    if ([int]$Key.KeyChar -eq 0x5d) { return $true }
  }
  return $false
}

# ---------------------------------------------------------------- self-test

function Invoke-SelfTest {
  $script:ran = 0
  $script:fail = 0

  function Key {
    param([string]$Char, [System.ConsoleKey]$K, [bool]$Ctrl = $false, [bool]$Alt = $false)
    $ch = if ($Char.Length -gt 0) { [char]$Char } else { [char]0 }
    return New-Object System.ConsoleKeyInfo $ch, $K, $false, $Alt, $Ctrl
  }

  function Expect {
    param([string]$Name, $Got, $Want)
    $script:ran++
    $g = if ($null -eq $Got) { '<none>' } else { ($Got | ForEach-Object { '{0:x2}' -f $_ }) -join ' ' }
    $w = if ($null -eq $Want) { '<none>' } else { ($Want | ForEach-Object { '{0:x2}' -f $_ }) -join ' ' }
    if ($g -eq $w) { Write-Host ("  ok    {0,-30} {1}" -f $Name, $g) }
    else { Write-Host ("  FAIL  {0,-30} got [{1}] want [{2}]" -f $Name, $g, $w); $script:fail++ }
  }

  function Check {
    param([string]$Name, $Got, $Want)
    $script:ran++
    if ("$Got" -eq "$Want") { Write-Host ("  ok    {0,-30} {1}" -f $Name, $Got) }
    else { Write-Host ("  FAIL  {0,-30} got [{1}] want [{2}]" -f $Name, $Got, $Want); $script:fail++ }
  }

  Write-Host 'encoder: only the listed keys may produce bytes'
  Expect 'Escape'         (Get-SendBytes (Key '' ([System.ConsoleKey]::Escape)))      @(0x1b)
  Expect 'UpArrow'        (Get-SendBytes (Key '' ([System.ConsoleKey]::UpArrow)))     @(0x1b, 0x5b, 0x41)
  Expect 'DownArrow'      (Get-SendBytes (Key '' ([System.ConsoleKey]::DownArrow)))   @(0x1b, 0x5b, 0x42)
  Expect 'RightArrow'     (Get-SendBytes (Key '' ([System.ConsoleKey]::RightArrow)))  @(0x1b, 0x5b, 0x43)
  Expect 'LeftArrow'      (Get-SendBytes (Key '' ([System.ConsoleKey]::LeftArrow)))   @(0x1b, 0x5b, 0x44)
  Expect 'Enter'          (Get-SendBytes (Key '' ([System.ConsoleKey]::Enter)))       @(0x0d)
  Expect 'Backspace'      (Get-SendBytes (Key '' ([System.ConsoleKey]::Backspace)))   @(0x08)
  Expect 'printable M'    (Get-SendBytes (Key 'M' ([System.ConsoleKey]::M)))          @(0x4d)
  Expect 'printable sp'   (Get-SendBytes (Key ' ' ([System.ConsoleKey]::Spacebar)))   @(0x20)
  Expect 'F12 never'      (Get-SendBytes (Key '' ([System.ConsoleKey]::F12)))         $null
  Expect 'F10 never'      (Get-SendBytes (Key '' ([System.ConsoleKey]::F10)))         $null
  Expect 'Tab ignored'    (Get-SendBytes (Key "`t" ([System.ConsoleKey]::Tab)))       $null
  Expect 'Ctrl+C ignored' (Get-SendBytes (Key ([char]3) ([System.ConsoleKey]::C) $true)) $null
  Expect 'Delete ignored' (Get-SendBytes (Key '' ([System.ConsoleKey]::Delete)))      $null

  Write-Host 'tracker: anything it cannot model marks the line unreliable'
  $t = Update-TypedLine -Line '' -Unknown $false -Bytes ([byte[]][char[]]'M5LOAD.EFI go')
  Check 'plain line' $t.Line 'M5LOAD.EFI go'
  Check 'plain line trusted' $t.Unknown $false
  $t = Update-TypedLine -Line 'M5LOAD.EFI gp' -Unknown $false -Bytes ([byte[]](0x08))
  $t = Update-TypedLine -Line $t.Line -Unknown $t.Unknown -Bytes ([byte[]][char[]]'o')
  Check 'backspace edits' $t.Line 'M5LOAD.EFI go'
  $t = Update-TypedLine -Line 'M5LOAD.EFI go' -Unknown $false -Bytes ([byte[]](0x1b, 0x5b, 0x44))
  Check 'left arrow -> unknown' $t.Unknown $true
  $t = Update-TypedLine -Line '' -Unknown $false -Bytes ([byte[]](0x1b, 0x5b, 0x41))
  Check 'history recall -> unknown' $t.Unknown $true
  $t = Update-TypedLine -Line '' -Unknown $false -Bytes ([byte[]](0x1b))
  Check 'escape -> unknown' $t.Unknown $true
  $t = Update-TypedLine -Line 'abc' -Unknown $true -Bytes ([byte[]](0x0d))
  Check 'enter clears line' $t.Line ''
  Check 'enter clears unknown' $t.Unknown $false

  Write-Host 'go-line detector: disarm on these, stay armed on those'
  foreach ($l in @('M5LOAD.EFI go', 'm5load.efi go', '  M5LOAD.EFI   go  ', 'fs0:M5LOAD.EFI go',
                   'FS0:\M5LOAD.EFI go', 'M5LOAD go', 'm5load GO')) {
    $script:ran++
    if (Test-GoLine $l) { Write-Host ("  ok    disarms on                 '{0}'" -f $l) }
    else { Write-Host ("  FAIL  should disarm on           '{0}'" -f $l); $script:fail++ }
  }
  foreach ($l in @('M5LOAD.EFI check', 'M5LOAD.EFI', 'go', '', 'M5LOAD.EFI go check', 'echo M5LOAD.EFI go')) {
    $script:ran++
    if (-not (Test-GoLine $l)) { Write-Host ("  ok    stays armed on             '{0}'" -f $l) }
    else { Write-Host ("  FAIL  should stay armed on       '{0}'" -f $l); $script:fail++ }
  }

  Write-Host 'exit key: layout-independent'
  Check 'Ctrl+Oem6 exits'   (Test-ExitKey (Key ']' ([System.ConsoleKey]::Oem6) $true)) $true
  Check 'Ctrl+0x1d exits'   (Test-ExitKey (Key ([char]0x1d) ([System.ConsoleKey]::Oem6) $true)) $true
  Check 'F10 exits'         (Test-ExitKey (Key '' ([System.ConsoleKey]::F10))) $true
  Check 'AltGr ] does not'  (Test-ExitKey (Key ']' ([System.ConsoleKey]::D9) $true $true)) $false
  Check 'plain ] does not'  (Test-ExitKey (Key ']' ([System.ConsoleKey]::Oem6))) $false

  Write-Host ''
  if ($script:fail -eq 0) { Write-Host ("SELFTEST PASS {0} checks" -f $script:ran); return 0 }
  Write-Host ("SELFTEST FAIL {0} of {1} checks" -f $script:fail, $script:ran)
  return 1
}

if ($SelfTest) { exit (Invoke-SelfTest) }

# ---------------------------------------------------------------- session

if (-not $Out) { throw 'com3-term: -Out is required (the byte-exact received log)' }
$outPath = [System.IO.Path]::GetFullPath($Out)
if (-not $KeyLog) { $KeyLog = $outPath + '.keys.log' }
$keyPath = [System.IO.Path]::GetFullPath($KeyLog)

$ascii = New-Object System.Text.ASCIIEncoding
# Latin-1 for the screen: the Setup and Boot Manager menus are drawn with bytes
# above 0x7f, and ASCII would render every one of them as a question mark.
$screen = [System.Text.Encoding]::GetEncoding(28591)

# A real console is required before anything else happens: KeyAvailable throws
# when stdin is redirected or the launch is hidden, and finding that out after
# the port is open and the header is written would leave a well-formed log of a
# session that never ran.
try { $null = [Console]::KeyAvailable }
catch { throw "com3-term: no interactive console (KeyAvailable: $($_.Exception.Message)). Run it in a PowerShell window, not redirected." }

foreach ($p in @($outPath, $keyPath)) {
  if (Test-Path -LiteralPath $p) {
    throw "com3-term: $p exists. Records are never overwritten - use a new run id, as the M4 loop does."
  }
}

# Evaluation output under NC QDL v7 4.6(i). Warn, do not fail: the operator may
# have a good reason, but it must not pass unnoticed.
try {
  $d = Split-Path -Parent $outPath
  & git -C $d check-ignore -q (Split-Path -Leaf $outPath) 2>$null
  if ($LASTEXITCODE -ne 0) {
    Write-Host "[com3-term] WARNING: $outPath is not git-ignored. Board output is private under NC QDL v7 4.6(i)." -ForegroundColor Yellow
  }
} catch { }

$armed = $false
$typed = ''
$typedUnknown = $false
$exitCode = 0

# Both logs first, then the port: a path error must not leave COM3 locked, and
# COM3 is exclusive with nothing in the design to recover a stuck port.
$fs = [System.IO.File]::Open($outPath, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::Read)
$kw = New-Object System.IO.StreamWriter($keyPath, $false, $ascii)
$kw.AutoFlush = $true

function Write-Ascii {
  param([System.IO.FileStream]$Fs, [string]$Text)
  $b = $ascii.GetBytes($Text)
  $Fs.Write($b, 0, $b.Length)
  $Fs.Flush()
}

function Write-Key {
  param([string]$What, [byte[]]$Bytes)
  $hex = ''
  if ($Bytes) { $hex = ($Bytes | ForEach-Object { '{0:x2}' -f $_ }) -join ' ' }
  # A key-log failure must never end the session: the received record matters
  # more, and the operator is at the board.
  try { $kw.WriteLine('{0} {1} {2}' -f ([DateTimeOffset]::UtcNow.ToString('o')), $What, $hex) } catch { }
}

function Show-State {
  param([bool]$Armed)
  $state = if ($Armed) { 'ARMED - keys reach the board' } else { 'disarmed - nothing is sent' }
  try { $Host.UI.RawUI.WindowTitle = "com3-term $Port : $state" } catch { }
  Write-Host ''
  Write-Host ("[com3-term] {0}   (F12 arms/disarms, Ctrl+] or F10 exits)" -f $state) -ForegroundColor $(if ($Armed) { 'Red' } else { 'Green' })
}

$sp = $null
try {
  $sp = New-Object System.IO.Ports.SerialPort $Port, $Baud, ([System.IO.Ports.Parity]::None), 8, ([System.IO.Ports.StopBits]::One)
  $sp.Handshake = [System.IO.Ports.Handshake]::None
  $sp.DtrEnable = $true
  $sp.RtsEnable = $true
  $sp.ReadTimeout = 50
  $sp.ReadBufferSize = 1048576
  try { $sp.Open() }
  catch { throw ("com3-term: cannot open {0}: {1}. COM3 is exclusive - stop any capture first." -f $Port, $_.Exception.Message) }

  $now = [DateTimeOffset]::UtcNow
  Write-Ascii $fs ("--- raw capture started on $Port at $Baud, " + $now.ToString('o') + " epoch=" + $now.ToUnixTimeSeconds() + " seconds=0 ---`n")
  Write-Key 'session-start' $null
  Show-State $armed

  $total = [long]0
  $buf = New-Object byte[] 65536
  $readError = $null
  $draining = $false
  $drainIdle = 0

  while ($true) {
    $did = $false

    $n = 0
    try { $n = $sp.Read($buf, 0, $buf.Length) }
    catch [TimeoutException] { $n = 0 }
    catch {
      # Anything else ends the session, and says so in the log rather than
      # writing the clean end line a complete capture would have.
      $readError = $_.Exception.Message
      break
    }
    if ($n -gt 0) {
      $fs.Write($buf, 0, $n)
      $fs.Flush()
      $total += $n
      [Console]::Write($screen.GetString($buf, 0, $n))
      $did = $true
      $drainIdle = 0
    } elseif ($draining) {
      $drainIdle++
      if ($drainIdle -ge 2) { break }
    }

    if ($draining) { continue }

    if ([Console]::KeyAvailable) {
      $k = [Console]::ReadKey($true)
      $did = $true

      if (Test-ExitKey $k) {
        # Drain what the driver already holds before the end line: requirement
        # 1 is every received byte, including the ones in flight at exit.
        Write-Key 'session-exit' $null
        $draining = $true
        continue
      }

      if ($k.Key -eq [System.ConsoleKey]::F12) {
        $armed = -not $armed
        if ($armed) { Write-Key 'armed' $null } else { Write-Key 'disarmed' $null }
        # A line typed across an arm/disarm cannot be trusted either.
        $typed = ''
        $typedUnknown = $armed
        Show-State $armed
        continue
      }

      if (-not $armed) { Write-Key 'dropped-disarmed' $null; continue }

      $bytes = Get-SendBytes $k
      if ($null -eq $bytes) { Write-Key 'ignored-key' $null; continue }

      $sp.Write($bytes, 0, $bytes.Length)
      Write-Key 'sent' $bytes

      $wasGo = Test-GoLine $typed
      $wasUnknown = $typedUnknown
      $t = Update-TypedLine -Line $typed -Unknown $typedUnknown -Bytes $bytes
      $typed = $t.Line
      $typedUnknown = $t.Unknown

      # Requirement 5, in the safe direction: the Enter that ends a go line
      # disarms, and so does the Enter that ends a line the tracker could not
      # follow. Every divergence resolves toward disarmed.
      if ($bytes.Length -eq 1 -and $bytes[0] -eq 0x0d -and ($wasGo -or $wasUnknown)) {
        $armed = $false
        if ($wasGo) { Write-Key 'disarmed-after-go' $null } else { Write-Key 'disarmed-line-unknown' $null }
        Show-State $armed
      }
    }

    if (-not $did) { Start-Sleep -Milliseconds 5 }
  }

  if ($readError) {
    Write-Ascii $fs ("`n--- raw capture read error: " + $readError + " bytes=$total ---`n")
    Write-Key 'read-error' $null
    $exitCode = 1
  } else {
    Write-Ascii $fs ("`n--- raw capture ended " + [DateTimeOffset]::UtcNow.ToString('o') + " bytes=$total ---`n")
  }
  Write-Host ''
  Write-Host ("[com3-term] closed {0}. received {1} bytes -> {2}" -f $Port, $total, $outPath)
  Write-Host ("[com3-term] key log -> {0}" -f $keyPath)
} finally {
  if ($null -ne $sp) {
    try { $sp.Close() } catch { }
    try { $sp.Dispose() } catch { }
  }
  try { $fs.Dispose() } catch { }
  try { $kw.Dispose() } catch { }
}

exit $exitCode
