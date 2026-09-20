@echo off
REM ============================================================================
REM build-qnx-ifs-orin.bat -- rebuild qnx-safety-vm with the Phase-3 (Orin)
REM TCP echo server AND the Phase-3b cross-partition safety monitor staged in,
REM both auto-started, with a static vtnet0 IP.
REM
REM The two are staged side by side on purpose, not one replacing the other:
REM the echo endpoint (:7000) is what the KVM-concurrency liveness probe talks
REM to, and the safety monitor (:7100) interprets a claim from the Compute side
REM and answers with a verdict. Folding them together would make one
REM experiment's result depend on the other's code.
REM
REM Run on: the same Windows QNX SDP 8.0 build host as build-qnx-ifs.bat.
REM
REM This is build-qnx-ifs.bat's Phase-3 sibling: same underlying
REM qnx-safety-vm/ build tree and local/options (the cloud-twin baseline is
REM NOT re-derived from scratch here), but with two extra
REM local/snippets/*.custom files staged first, mirroring how build-qhv.bat
REM stages the Phase-2 qnx-echo-server/qnx-host-client pair into qhv/. The
REM staged snippets live in qnx-safety-vm/ (gitignored, mkqnximage-derived);
REM their committed source of truth is scripts/orin/qnx-safety-vm-post_start.custom
REM (ifs_files.custom has no committed twin -- it is one line with an
REM absolute, host-specific path, generated fresh every run, same as
REM build-qhv.bat does for its own ifs_files.custom/data_files.custom).
REM
REM Honest framing: rebuilding qnx-safety-vm for Phase 3 means the artifact
REM booted on Orin is no longer byte-identical to whatever was last scp'd to
REM the AWS Graviton runtime from this same build tree -- the NEW code
REM (ipc-test/qnx-server-net/) is in-scope/additive per Phase 3's plan, but
REM this is a real deviation from a strict "zero IFS changes" portability
REM claim. See docs/orin-port.md's 2026-07-28 status entry.
REM ============================================================================

setlocal EnableExtensions EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "REPO_ROOT=%%~fI"
set "REPO_ROOT_FWD=%REPO_ROOT:\=/%"

set "IPC_DIR=%REPO_ROOT%\ipc-test"
set "BUILD_DIR=%REPO_ROOT%\qnx-safety-vm"
set "SERVER_BIN_FWD=%REPO_ROOT_FWD%/ipc-test/qnx-server-net/qnx-echo-server-net"
set "MONITOR_BIN_FWD=%REPO_ROOT_FWD%/ipc-test/qnx-safety-monitor/qnx-safety-monitor"
REM Phase 3b (2026-09-20): the DDS-based cross-partition monitor. Unlike the two
REM above it is NOT built by ipc-test's make -- it links against a Cyclone DDS
REM static library cross-built separately (see the middleware notes), so it is
REM staged only if it is already present. A missing binary is not an error here.
set "DDSMON_BIN_FWD=%REPO_ROOT_FWD%/ipc-test/qnx-dds-monitor/qnx-dds-monitor"
REM The DDS monitor cannot use Cyclone's default interface selection: with br0
REM present it picks the wireless interface and then never discovers the
REM Compute side, with no error. The config is staged beside the binary and
REM post_start.custom points CYCLONEDDS_URI at it.
set "DDSCFG_FWD=%REPO_ROOT_FWD%/ipc-test/qnx-dds-monitor/cyclonedds-qnx.xml"

if "%QNX_INSTALL_ROOT%"=="" set "QNX_INSTALL_ROOT=%USERPROFILE%\qnx800"
if not exist "%QNX_INSTALL_ROOT%\qnxsdp-env.bat" (
  echo ERROR: QNX SDP env not found at "%QNX_INSTALL_ROOT%\qnxsdp-env.bat".
  exit /b 1
)
call "%QNX_INSTALL_ROOT%\qnxsdp-env.bat"

where mkqnximage >nul 2>&1 || (
  echo ERROR: mkqnximage not on PATH after sourcing qnxsdp-env.bat.
  exit /b 1
)

echo [1/4] Building ipc-test binaries (qnx-echo-server-net, qnx-safety-monitor, plus the Phase-2 pair) ...
pushd "%IPC_DIR%"
call make || (
  echo ERROR: ipc-test build failed. & popd & exit /b 1
)
popd
if not exist "%SERVER_BIN_FWD:/=\%" (
  echo ERROR: %SERVER_BIN_FWD% not found after ipc-test build. & exit /b 1
)
if not exist "%MONITOR_BIN_FWD:/=\%" (
  echo ERROR: %MONITOR_BIN_FWD% not found after ipc-test build. & exit /b 1
)

echo [2/4] Staging Phase-3 auto-start snippet + server binary reference ...
if not exist "%BUILD_DIR%\local\snippets" mkdir "%BUILD_DIR%\local\snippets"
copy /Y "%SCRIPT_DIR%orin\qnx-safety-vm-post_start.custom" "%BUILD_DIR%\local\snippets\post_start.custom" >nul || (
  echo ERROR: could not stage qnx-safety-vm-post_start.custom & exit /b 1
)
(
  echo [perms=555] qnx-echo-server-net=%SERVER_BIN_FWD%
  echo [perms=555] qnx-safety-monitor=%MONITOR_BIN_FWD%
) > "%BUILD_DIR%\local\snippets\ifs_files.custom" || (
  echo ERROR: could not stage ifs_files.custom & exit /b 1
)
REM Append the DDS monitor only when it has been cross-built. Staging a missing
REM path would be silently skipped by mkifs anyway ([+optional] semantics make
REM a zero exit code prove nothing), so the presence check is explicit.
if exist "%DDSMON_BIN_FWD:/=\%" (
  REM No space before >>: cmd writes everything between the text and the
  REM redirect into the file, which would append a trailing space to the path.
  echo [perms=555] qnx-dds-monitor=%DDSMON_BIN_FWD%>>"%BUILD_DIR%\local\snippets\ifs_files.custom"
  echo [perms=444] cyclonedds-qnx.xml=%DDSCFG_FWD%>>"%BUILD_DIR%\local\snippets\ifs_files.custom"
  echo   staged qnx-dds-monitor + cyclonedds-qnx.xml
) else (
  echo   NOTE: %DDSMON_BIN_FWD% absent -- building without the DDS monitor.
)

REM ---------------------------------------------------------------------------
REM KNOWN LIMITATION, read before trusting a rebuild from this script.
REM
REM Two things this script CANNOT do, both verified on 2026-09-20:
REM
REM 1. AUTO-START. The staged binaries land at /proc/boot/, but nothing starts
REM    them. post_start.custom lives in the system partition on disk-qemu, and
REM    the pinned disk this project boots contains no reference to either
REM    monitor. The working image starts them from a line inserted into the
REM    [+script] startup-script block of output/build/ifs.build, AFTER
REM    /proc/boot/startup.sh -- startup.sh is what brings up io-sock and the
REM    static vtnet0 address, so binding a socket before it fails. The
REM    local/snippets/ifs_start.custom hook is spliced in BEFORE startup.sh and
REM    therefore cannot host those lines. mkqnximage regenerates ifs.build from
REM    templates on every run, so that hand-inserted line is LOST each time.
REM
REM 2. THE STARTUP BINARY. mkqnximage takes startup-qemu-virt from the SDP --
REM    the shipped one, which hangs under KVM after 17 bytes ("FOUND GICv3
REM    ITS"). A KVM-bootable image needs our rebuilt startup first on
REM    MKFS_PATH.
REM
REM For a KVM-bootable image with the monitors started, use the IFS-only route
REM in ipc-test/qnx-dds-monitor/rebuild-ifs-with-dds.sh instead, which also
REM avoids regenerating disk-qemu.
REM ---------------------------------------------------------------------------

echo [3/4] Rebuilding qnx-safety-vm via build-qnx-ifs.bat ...
call "%SCRIPT_DIR%build-qnx-ifs.bat" || (
  echo ERROR: build-qnx-ifs.bat failed. & exit /b 1
)

echo [4/4] Regenerating SHA256SUMS for the rebuilt artifacts ...
where sha256sum >nul 2>&1
if errorlevel 1 (
  echo   NOTE: sha256sum not on PATH ^(ships with Git for Windows^) -- run it
  echo   manually from Git Bash before scp'ing to the Orin: cd qnx-safety-vm\output ^&^&
  echo   sha256sum ifs.bin disk-qemu disk-qemu.vmdk ^> SHA256SUMS
) else (
  pushd "%BUILD_DIR%\output"
  sha256sum ifs.bin disk-qemu disk-qemu.vmdk > SHA256SUMS
  popd
)

echo.
echo Orin Phase-3 IFS rebuild complete. Next:
echo   scp qnx-safety-vm\output\{ifs.bin,disk-qemu,disk-qemu.vmdk,SHA256SUMS} to the Orin
echo   sha256sum -c SHA256SUMS   (on the Orin)
echo   sudo scripts/orin/setup-bridge-orin.sh   (on the Orin, if not already up)
echo   scripts/orin/launch-qnx-on-orin-tcg.sh   (on the Orin)

endlocal
goto :eof
