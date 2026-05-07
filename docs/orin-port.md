# Phase 3 — hardware-twin port to Jetson Orin Nano

> **Status:** plan only. Phase 3 starts after Phase 2 (cloud-twin
> IPC + benchmark) lands. This file is the bring-up checklist + risk
> register for that work.

---

## Goal

Run the **same QNX IFS** and the **same ipc-test/ source** that
worked on the cloud twin, on a Jetson Orin Nano Dev Kit, with no
code changes — only configuration deltas. Measurable proof point:
`qnx-server` on QEMU-on-Orin and `linux-client` natively on L4T
exchange messages over `br0`, and a 100k-iteration benchmark
produces a CSV in `results/hw/` with the same column schema as
`results/cloud/`.

---

## Hardware preconditions

| Item | Notes |
|---|---|
| Jetson Orin Nano Dev Kit | 8 GB SKU recommended; 6 GB SKU borderline for L4T + QEMU(QNX, 1 GB) + benchmark |
| microSD or NVMe | NVMe preferred for boot; ≥64 GB |
| USB-C PSU | Match the Dev Kit's bundled supply (do not undervolt — A78AE will throttle) |
| Ethernet | For initial JetPack flash + apt installs |
| Host machine for flashing | x86_64 Linux with NVIDIA SDK Manager (Phase 3 first task is to confirm whether this exists at hand or needs an EC2 throwaway instance) |

The user already runs an x86_64 EC2 build host for the cloud twin's
QNX IFS build — that same instance can run SDK Manager for the
initial Orin Nano flash, avoiding a separate Linux box.

---

## Bring-up checklist

### 0. Pre-flight

- [ ] Confirm JetPack 6.x is the right release (matches L4T r36.x; Ubuntu 22.04 base)
- [ ] Confirm SDK Manager runs on the cloud-twin x86_64 build host (or stand up a separate t3.medium for it)
- [ ] On the build host, retain the existing `output/ifs.bin` from Phase 1 — this is the artefact under test on Orin

### 1. Flash and first boot

- [ ] Flash JetPack 6.x to the Orin Nano via SDK Manager
- [ ] First boot: complete Ubuntu first-run, set hostname, install ssh
- [ ] Confirm `uname -a` reports A78AE / `aarch64`
- [ ] `lscpu` should show 6 × A78AE cores
- [ ] `free -h` should show ≥7 GB usable

### 2. Install QEMU + bridge tooling on L4T

- [ ] `sudo apt-get update`
- [ ] `sudo apt-get install -y qemu-system-arm qemu-utils bridge-utils iproute2 cloud-image-utils`
- [ ] Verify `qemu-system-aarch64 --version`
- [ ] Verify `/dev/kvm` exists (Orin Nano L4T should expose KVM out of the box; A78AE supports virt extensions)
- [ ] `sudo usermod -aG kvm $USER` and re-login

### 3. Set up bridge (Orin variant)

- [ ] `sudo scripts/orin/setup-bridge-orin.sh`
- [ ] Verify `br0` (192.168.100.1/24) and `tap-qnx` exist; on Orin the Linux client runs natively so no `tap-linux` is created
- [ ] Verify L4T native userspace can reach `192.168.100.1`

### 4. Transfer the cloud-twin IFS

- [ ] On the cloud-twin x86_64 build host: `sha256sum output/ifs.bin output/disk-qemu.vmdk > output/SHA256SUMS`
- [ ] `scp output/ifs.bin output/disk-qemu.vmdk output/SHA256SUMS orin:~/output/`
- [ ] On Orin: `sha256sum -c ~/output/SHA256SUMS` — must pass

### 5. Boot the QNX guest under QEMU on Orin

- [ ] `scripts/orin/launch-qnx-on-orin.sh`
- [ ] Capture full boot log to `logs/sample-boot/orin-qnx-bootN.log`
- [ ] Verify QNX prompt; `pidin sysinfo` reports correct cycles_per_sec
- [ ] Confirm QNX virtio-net comes up; static IP 192.168.100.10; ping 192.168.100.1 succeeds

### 6. Run the IPC test natively on L4T against the QEMU-QNX server

- [ ] Build `ipc-test/linux-client/` natively on L4T (gcc, no cross-compile needed)
- [ ] Run 1 000-iteration warm-up; record results
- [ ] Run 100 000-iteration measurement; emit CSV to `results/hw/orin-runN.csv`
- [ ] Compare CSV header / schema to `results/cloud/awsN.csv` — schema must match exactly

### 7. Twin diff sanity check

- [ ] `scripts/twin/diff-results.sh results/cloud/aws1.csv results/hw/orin1.csv` (Phase 4 script)
- [ ] No interpretation in Phase 3 — just confirm the diff runs cleanly and the numbers look "physically plausible" (P50 in tens-to-hundreds of µs, P99 within an order of magnitude of P50, no NaN / no negative deltas)

---

## Risk register (carried from `bsp-selection.md` F6)

| Risk | Mitigation if it bites | Effort |
|---|---|---|
| Same IFS does not boot under QEMU-on-Orin | Tweak QEMU args (mask A78AE-specific feature) | Low |
| Same IFS still does not boot | Rebuild IFS with explicit A78AE flags via mkqnximage options | Medium |
| Still does not boot | Switch HW twin to `joexue/qemu-virt` community BSP for source-level visibility | High |
| **QNX microkernel CPU-feature probe rejects A78AE silently** (MIDR/REVIDR allow-list mismatch — symptom: hang before any boot banner) | First failed boot, capture `qemu -d in_asm,int` trace to distinguish CPU-probe rejection from device-tree mismatch; if confirmed, escalate to "Same IFS still does not boot" branch (rebuild w/ A78AE flags) | Low (just the trace); diagnosis only |
| JetPack 6 ships QEMU without KVM enabled | Build `qemu-system-aarch64` from source on L4T with KVM enabled | Medium |
| Orin Nano 8 GB tight on RAM | Reduce QNX guest to 768 MB; benchmark RSS-headroom; if still tight, swap to larger Orin family (Orin NX 16 GB, $599) — narrative cost note | Low if QNX shrinks; doc only otherwise |
| `vhost-net` not enabled in L4T kernel | Live with userspace virtio (slower); document in twin-diff doc | Low |

---

## What success looks like

The Phase 3 deliverable is **not** a benchmark number. It is **proof
of code+artefact portability**: the same `output/ifs.bin` and the
same `ipc-test/` source produced a working IPC channel on a real
Tegra-class SoC with **only configuration changes**. The CSV
schemas matching is the load-bearing evidence — that is what makes
Phase 4's twin diff meaningful.

If we get there, the project's narrative becomes meaningfully
stronger: the cloud twin is a fast iteration sandbox, and the
hardware twin proves it ports to silicon. That is the customer-port
story DRIVE OS SE work actually consists of.
