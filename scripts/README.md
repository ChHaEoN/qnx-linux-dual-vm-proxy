# Scripts — workflow

This folder holds the bring-up scripts. They are split between the
**build host** (x86_64) and the **runtime host** (arm64 Graviton)
because QNX SDP 8.0 does not have an arm64 host toolchain — see
[../docs/bsp-selection.md](../docs/bsp-selection.md) for the full
rationale.

As of the 2026-05-07 amendment in
[../docs/findings.md](../docs/findings.md), the primary build path
is a **local Windows PC** (QNX SDP 8.0 ships a Windows native
installer). The previous EC2 t3.medium walkthrough is retained as
an explicit fallback further down this page. Honest framing: the
Windows-host pivot removes ssh / X11 / browser-flow friction and EC2
billing for the build side, but it does **not** demonstrate
cross-host build determinism (Phase 1 will verify Windows-built vs.
EC2-built IFS equivalence) and it is **not** closer to a real DRIVE
OS customer build environment than EC2.

> **Cost discipline:** the runtime host (`c7g.large`) bills around
> $0.0725/hr on-demand (us-east-1, May 2026). The fallback build
> host (`t3.medium`) bills around $0.0416/hr; the primary path
> (local Windows) bills nothing. Stop the runtime instance when not
> actively using it; data egress for the IFS scp is negligible.
> There is no automated teardown — when you finish a session, run
> `aws ec2 stop-instances` (or terminate) yourself.

> **License:** the user must obtain their own QNX Everywhere license
> from <https://qnx.com/getqnx> and install QNX SDP 8.0 themselves.
> This repo does not — and per the NCEULA, cannot — ship any QNX
> SDK or QNX-derived binaries.

---

## Workflow — primary path (local Windows build host)

Use this path on a Windows 10 / 11 x86_64 machine. The runtime side
(steps 4–7) is unchanged from the fallback path — the only
difference is where `output\ifs.bin` is produced.

### 1. Install QNX SDP 8.0 (manual, license-bound)

On the Windows PC:

1. Visit <https://www.qnx.com/getqnx> and create a myQNX account.
2. Accept the QNX Everywhere NCEULA in your account.
3. Download the **QNX Software Center for Windows x86_64**.
4. Run the installer (`qnx-setup-*.exe`); sign in; install **QNX
   SDP 8.0** with the **aarch64le** target packages selected.
5. The default install root is `%USERPROFILE%\qnx800`.

### 2. Source the SDP environment

In a Cmd shell (or wrap in PowerShell with `cmd /c`):

```cmd
"%USERPROFILE%\qnx800\qnxsdp-env.bat"
where mkqnximage
where qcc
```

`mkqnximage` and `qcc` should resolve under `%USERPROFILE%\qnx800\host\...`.

### 3. Build the QNX IFS

From the repo root in the same Cmd shell:

```cmd
scripts\build-qnx-ifs.bat
```

Produces `qnx-safety-vm\output\ifs.bin` and
`qnx-safety-vm\output\disk-qemu.vmdk`. These are gitignored. **Do
not commit them** — the QNX NCEULA forbids redistributing
QNX-derived binaries.

### 4. scp the IFS to the runtime host

From the Windows PC (OpenSSH ships with Windows 10/11):

```cmd
scp qnx-safety-vm\output\ifs.bin           ubuntu@<runtime-host>:~/output/
scp qnx-safety-vm\output\disk-qemu.vmdk    ubuntu@<runtime-host>:~/output/
```

Then continue with **steps 4–7 of the fallback path below** (provision
runtime, set up bridge, launch VMs) — those steps are runtime-host
side and identical regardless of where the IFS was built.

---

## Workflow — fallback path (EC2 build host)

Use this path **only if** you do not have a local x86_64 Windows or
Linux machine available. It is the original Phase 0 workflow,
preserved verbatim except for the relabel.

### 1. Provision the build host (x86_64)

Launch a `t3.medium` Ubuntu 22.04 amd64 instance with at least 30 GB
EBS. SSH in and run:

```bash
./bootstrap-build-host.sh
```

This installs the prerequisites for the QNX Software Center
(openjdk-17-jre, unzip, build essentials). The QNX install itself is
manual — see step 2.

### 2. Install QNX SDP 8.0 (manual, license-bound)

On the build host:

1. Visit <https://www.qnx.com/getqnx> and create a myQNX account.
2. Accept the QNX Everywhere NCEULA in your account.
3. Download the QNX Software Center for Linux x86_64.
4. Run the installer; sign in; install **QNX SDP 8.0** with the
   **aarch64le** target packages selected.
5. After install, source the SDP environment in every shell where
   you intend to build:
   ```bash
   source ~/qnx800/qnxsdp-env.sh
   ```

### 3. Build the QNX IFS

```bash
./build-qnx-ifs.sh
```

Produces `qnx-safety-vm/output/ifs.bin` and
`qnx-safety-vm/output/disk-qemu.vmdk`. These are the artifacts you
will scp to the runtime host. **Do not commit them.**

### 4. Provision the runtime host (arm64 Graviton)

Launch a `c7g.large` Ubuntu 22.04 arm64 instance with at least 30 GB
EBS in a region that offers Graviton (e.g. `us-east-1`, `eu-central-1`).
SSH in and run:

```bash
./bootstrap-runtime-host.sh
```

This installs `qemu-system-arm`, bridge tooling, and verifies that
`/dev/kvm` is exposed. You may need to log out and back in for
`kvm` group membership to take effect.

### 5. scp the IFS to the runtime host

From the build host:

```bash
scp qnx-safety-vm/output/ifs.bin           ubuntu@<runtime-host>:~/output/
scp qnx-safety-vm/output/disk-qemu.vmdk    ubuntu@<runtime-host>:~/output/
```

### 6. Set up the host bridge (runtime host)

```bash
sudo ./setup-bridge.sh
```

Creates `br0` (192.168.100.1/24) plus tap devices `tap-qnx` and
`tap-linux` owned by the current user.

### 7. Launch the VMs (runtime host)

In one terminal:

```bash
./launch-qnx-vm.sh
```

In another:

```bash
./launch-linux-vm.sh
```

Each VM uses `-nographic -serial mon:stdio`, so you interact via the
SSH session that launched it.

---

## Idempotency notes

- `bootstrap-*.sh` scripts use `apt install` (idempotent on Debian/Ubuntu).
- `setup-bridge.sh` will fail loudly if `br0` already exists — there
  is a commented-out teardown stanza at the bottom for reference; do
  not uncomment it without understanding the consequences.
- `build-qnx-ifs.sh` writes into `qnx-safety-vm/output/`; rerun is
  destructive of any previous IFS build in that directory.
- `launch-*.sh` are foreground — Ctrl-A X (QEMU monitor) or Ctrl-C
  to terminate.
