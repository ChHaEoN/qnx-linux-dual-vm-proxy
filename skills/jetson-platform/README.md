# skills/jetson-platform

> Study notes only — not certification evidence, not professional advice.

Paradigm references for the NVIDIA Jetson family, with focus on
Jetson Orin Nano (the project's HW-twin host).

## Scope of this folder

- L4T / JetPack 6 layout: kernel, device tree, root filesystem, NVIDIA
  proprietary userspace stack
- SDK Manager flashing flow (host-side)
- Tegra device-tree customisation entry points (where to add custom
  peripherals)
- How **Jetson differs from DRIVE Orin** — same Tegra silicon family,
  different SKU, different software stack, different target market.
  Crucial honest-framing point: Jetson Orin Nano ≠ DRIVE Orin, even
  though they share the A78AE CCPLEX core family.

## Out of scope

- Cuda / cuDNN / TensorRT application development (project does not
  exercise the GPU)
- DeepStream / Isaac (NVIDIA application SDKs)
- Snapdragon Cockpit equivalents — see [skills/qualcomm-cockpit/](../qualcomm-cockpit/) (Phase 7)

## Where this skill is exercised in the repo

- [docs/orin-port.md](../../docs/orin-port.md) — Phase 3 bring-up
  checklist that uses this paradigm
- `scripts/orin/bootstrap-orin-l4t.sh` — concrete L4T setup
- [docs/architecture.md](../../docs/architecture.md) §"Hardware
  twin — Jetson Orin Nano Dev Kit"

## Honest gap

Jetson Orin Nano is **not** the same as DRIVE Orin. The shared CCPLEX
A78AE core family validates *core-level* portability claims; it does
NOT validate:

- Tegra Industrial / Automotive-class peripherals
- DRIVE OS-specific software stack (NVIDIA Hypervisor partitioning)
- FSI lockstep, Safety Cluster R52
- Production SecureBoot fuse provisioning chain

These belong to DRIVE platforms behind commercial NVIDIA agreements;
no portfolio project running on consumer Jetson hardware can claim
parity.
