@echo off
REM ============================================================================
REM build-qhv.bat -- build a QNX Hypervisor (QHV) host that boots a QNX guest
REM
REM Run on: x86_64 Windows host with QNX SDP 8.0 installed natively, with the
REM aarch64le target packages AND target.hypervisor.core (qvm) installed.
REM
REM Two-stage mkqnximage build (per the QNX Hypervisor User's Guide):
REM   1. guest : mkqnximage --type=qvm  ...                 -> qhv\guest\output
REM   2. host  : mkqnximage --type=qemu --qvm=yes --guest=  -> qhv\host\output
REM The host image embeds qvm + the guest under /data/hypervisor/, and our
REM scripts\qhv\post_start.custom snippet auto-starts the guest under qvm and
REM then runs the qnx-host-client <-> qnx-echo-server IPC benchmark (Phase 2,
REM see ipc-test\qnx-host-client\README.md).
REM
REM Output (gitignored; NCEULA forbids redistributing QNX binaries):
REM   qhv\host\output\ifs.bin     <- QHV host kernel image (qemu -kernel)
REM   qhv\host\output\disk-qemu   <- host raw disk (embeds the guest)
REM
REM After building, launch with: powershell -File scripts\launch-qhv-tcg.ps1
REM ============================================================================

setlocal EnableExtensions EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "REPO_ROOT=%%~fI"

if "%QNX_INSTALL_ROOT%"=="" set "QNX_INSTALL_ROOT=%USERPROFILE%\qnx800"
if not exist "%QNX_INSTALL_ROOT%\qnxsdp-env.bat" (
  echo ERROR: QNX SDP env not found at "%QNX_INSTALL_ROOT%\qnxsdp-env.bat".
  echo        Install QNX SDP 8.0 or set QNX_INSTALL_ROOT. See scripts\README.md.
  exit /b 1
)
call "%QNX_INSTALL_ROOT%\qnxsdp-env.bat"

where mkqnximage >nul 2>&1 || (
  echo ERROR: mkqnximage not on PATH after sourcing qnxsdp-env.bat.
  exit /b 1
)
if not exist "%QNX_TARGET%\aarch64le\sbin\qvm" (
  echo ERROR: qvm not found at "%QNX_TARGET%\aarch64le\sbin\qvm".
  echo        Install the QHV host package via QNX Software Center:
  echo          qnxsoftwarecenter_clt.bat -installIU com.qnx.qnx800.target.hypervisor.core
  exit /b 1
)

set "GUEST_DIR=%REPO_ROOT%\qhv\guest"
set "HOST_DIR=%REPO_ROOT%\qhv\host"
set "IPC_DIR=%REPO_ROOT%\ipc-test"
REM mkqnximage --guest and buildfile source= entries need forward slashes
REM (mkqnximage is Perl-based / mkifs buildfile parser; backslashes are eaten)
set "GUEST_FWD=%GUEST_DIR:\=/%"
set "REPO_ROOT_FWD=%REPO_ROOT:\=/%"
set "GUEST_SERVER_BIN=%REPO_ROOT_FWD%/ipc-test/qnx-server/qnx-echo-server"
set "HOST_CLIENT_BIN=%REPO_ROOT_FWD%/ipc-test/qnx-host-client/qnx-host-client"

echo [1/5] Building ipc-test binaries (qnx-echo-server, qnx-host-client) ...
pushd "%IPC_DIR%"
call make || (
  echo ERROR: ipc-test build failed. & popd & exit /b 1
)
popd
if not exist "%GUEST_SERVER_BIN:/=\%" (
  echo ERROR: %GUEST_SERVER_BIN% not found after ipc-test build. & exit /b 1
)
if not exist "%HOST_CLIENT_BIN:/=\%" (
  echo ERROR: %HOST_CLIENT_BIN% not found after ipc-test build. & exit /b 1
)

echo [2/5] Staging guest auto-start snippet + server binary reference ...
if not exist "%GUEST_DIR%\local\snippets" mkdir "%GUEST_DIR%\local\snippets"
copy /Y "%SCRIPT_DIR%qhv\guest-post_start.custom" "%GUEST_DIR%\local\snippets\post_start.custom" >nul || (
  echo ERROR: could not stage guest-post_start.custom & exit /b 1
)
(
  echo [perms=555] qnx-echo-server=%GUEST_SERVER_BIN%
) > "%GUEST_DIR%\local\snippets\ifs_files.custom" || (
  echo ERROR: could not stage guest ifs_files.custom & exit /b 1
)

echo [3/5] Building qvm guest in %GUEST_DIR% ...
if not exist "%GUEST_DIR%" mkdir "%GUEST_DIR%"
pushd "%GUEST_DIR%"
call mkqnximage --type=qvm --arch=aarch64le --hostname=qnx-guest --build || (
  echo ERROR: guest build failed. & popd & exit /b 1
)
popd

echo [4/5] Staging host auto-start snippet + client binary reference ...
if not exist "%HOST_DIR%\local\snippets" mkdir "%HOST_DIR%\local\snippets"
copy /Y "%SCRIPT_DIR%qhv\post_start.custom" "%HOST_DIR%\local\snippets\post_start.custom" >nul || (
  echo ERROR: could not stage post_start.custom & exit /b 1
)
(
  echo [perms=555] hypervisor/qnx-host-client=%HOST_CLIENT_BIN%
) > "%HOST_DIR%\local\snippets\data_files.custom" || (
  echo ERROR: could not stage host data_files.custom & exit /b 1
)

echo [5/5] Building QHV host in %HOST_DIR% (qvm + guest) ...
pushd "%HOST_DIR%"
call mkqnximage --type=qemu --arch=aarch64le --hostname=qnx-qhv --qvm=yes --guest=%GUEST_FWD% --build || (
  echo ERROR: host build failed. & popd & exit /b 1
)
popd

echo.
echo QHV build complete. Host artifacts in %HOST_DIR%\output\:
if exist "%HOST_DIR%\output\ifs.bin"   dir /b "%HOST_DIR%\output\ifs.bin"
if exist "%HOST_DIR%\output\disk-qemu" dir /b "%HOST_DIR%\output\disk-qemu"
echo.
echo Next: powershell -ExecutionPolicy Bypass -File "%SCRIPT_DIR%launch-qhv-tcg.ps1"

endlocal
goto :eof
