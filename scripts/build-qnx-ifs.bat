@echo off
REM ============================================================================
REM build-qnx-ifs.bat -- build the QNX IFS for the Safety-proxy VM (Windows)
REM
REM Run on: x86_64 Windows host with QNX SDP 8.0 installed natively. Per the
REM 2026-05-07 amendment in ..\docs\findings.md this is the PRIMARY build
REM path; scripts\build-qnx-ifs.sh is the EC2 / Linux equivalent and stays
REM available as a fallback.
REM
REM Output:
REM   qnx-safety-vm\output\ifs.bin           <- kernel image fed to qemu -kernel
REM   qnx-safety-vm\output\disk-qemu.vmdk    <- persistent rootfs disk
REM
REM These artifacts are gitignored. Do not commit them -- the QNX NCEULA
REM forbids redistributing QNX-derived binaries. scp them to the Graviton
REM runtime host and discard the local copy when done.
REM
REM Reproducibility: this is a thin wrapper around mkqnximage, the same
REM front-end used by the .sh sibling. Behaviour MUST match the .sh script
REM until Phase 1 verifies cross-host build determinism.
REM ============================================================================

setlocal EnableExtensions EnableDelayedExpansion

REM ---- Sanity checks ---------------------------------------------------------

if "%QNX_INSTALL_ROOT%"=="" set "QNX_INSTALL_ROOT=%USERPROFILE%\qnx800"

if not exist "%QNX_INSTALL_ROOT%\qnxsdp-env.bat" (
  echo ERROR: QNX SDP environment script not found at:
  echo        "%QNX_INSTALL_ROOT%\qnxsdp-env.bat"
  echo.
  echo        Install QNX SDP 8.0 from the QNX Software Center, or set
  echo        QNX_INSTALL_ROOT to your install root before re-running.
  echo        See ..\docs\bsp-selection.md and scripts\README.md.
  exit /b 1
)

call "%QNX_INSTALL_ROOT%\qnxsdp-env.bat"
if errorlevel 1 (
  echo ERROR: failed to source "%QNX_INSTALL_ROOT%\qnxsdp-env.bat".
  exit /b 1
)

where mkqnximage >nul 2>&1
if errorlevel 1 (
  echo ERROR: mkqnximage is not on PATH after sourcing qnxsdp-env.bat.
  echo        Verify the SDP install includes the host tools and the
  echo        aarch64le target packages.
  exit /b 1
)

REM Build host must be x86_64 (SDP 8.0 host toolchain is x86_64-only).
REM PROCESSOR_ARCHITECTURE is the native arch even on WoW64.
if /I not "%PROCESSOR_ARCHITECTURE%"=="AMD64" (
  if /I not "%PROCESSOR_ARCHITEW6432%"=="AMD64" (
    echo ERROR: build host must be x86_64. Detected: %PROCESSOR_ARCHITECTURE%
    echo        QNX SDP 8.0 host toolchain does not support arm64 hosts.
    echo        See ..\docs\bsp-selection.md for context.
    exit /b 1
  )
)

REM ---- Build ----------------------------------------------------------------

set "build_dir=qnx-safety-vm"

echo [1/2] Preparing build directory: %build_dir%
if not exist "%build_dir%" mkdir "%build_dir%"
pushd "%build_dir%" || (
  echo ERROR: cannot enter %build_dir%
  exit /b 1
)

echo [2/2] Running mkqnximage --type=qemu --arch=aarch64le --build ...
call mkqnximage --type=qemu --arch=aarch64le --hostname=qnx-safety --build
if errorlevel 1 (
  echo ERROR: mkqnximage failed.
  popd
  exit /b 1
)

echo.
echo Build complete. Artifacts in %CD%\output\:
if exist output\ifs.bin        dir /b output\ifs.bin
if exist output\disk-qemu.vmdk dir /b output\disk-qemu.vmdk

popd

echo.
echo Next: scp these two files to the Graviton runtime host, then run
echo launch-qnx-vm.sh there. Do NOT commit them to git (they are gitignored,
echo but double-check).

endlocal
goto :eof
