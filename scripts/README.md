# Scripts — workflow

This folder holds the bring-up scripts. They are split between the
**build host** (x86_64) and the **runtime host** (arm64 Graviton)
because QNX SDP 8.0 does not have an arm64 host toolchain — see
[../docs/bsp-selection.md](../docs/bsp-selection.md) for the full
rationale.

> **Cost discipline:** the runtime host (`c7g.large`) bills around
> $0.0725/hr on-demand (us-east-1, May 2026). The build host
> (`t3.medium`) bills around $0.0416/hr. Stop both instances when
> not actively using them; data egress for the IFS scp is
> negligible. There is no automated teardown — when you finish a
> session, run `aws ec2 stop-instances` (or terminate) yourself.

> **License:** the user must obtain their own QNX Everywhere license
> from <https://qnx.com/getqnx> and install QNX SDP 8.0 themselves.
> This repo does not — and per the NCEULA, cannot — ship any QNX
> SDK or QNX-derived binaries.

---

## Workflow

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
