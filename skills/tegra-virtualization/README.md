# skills/tegra-virtualization

> Study notes only — not certification evidence, not professional advice.

Paradigm references for Tegra-class virtualisation: how DRIVE OS
partitions Orin / Thor, what the public NVIDIA Hypervisor docs say,
and what KVM-on-L4T can and cannot reproduce.

## Scope of this folder

- **NVIDIA Hypervisor** (Type-1, DRIVE OS) — public-doc summary:
  partition scheduler, vCPU pinning, vGPU partitioning, mailbox-based
  IPC primitives, certified RT path
- **Cortex-A78AE virtualisation extensions** — VHE, GIC virtualisation,
  Stage-2 translation; what enables KVM on the project's HW twin
- **KVM-on-L4T**: what works (basic guest), what is fragile (nested
  virt for QHV-on-QEMU experiments), and what is missing (no Type-1
  partition guarantees)
- **Honest delta to Type-1 partitioning** — the table this project
  leans on hard for honest framing

## Out of scope

- Real DRIVE OS kernel internals (not public)
- vGPU implementation details (commercial NVIDIA agreements only)
- Implementing a competing Type-1 hypervisor (this project's KVM-based
  proxy is not aiming to imitate that work)

## Where this skill is exercised in the repo

- [docs/drive-os-comparison.md](../../docs/drive-os-comparison.md) —
  Phase 4 verdict table leans on this paradigm
- [docs/architecture.md](../../docs/architecture.md) "What this is
  NOT" section
- [docs/security-model.md](../../docs/security-model.md) §3 (secure-
  boot framing across hypervisor layers)

## Honest gap

The project **does not** implement a hypervisor of any kind, certified
or otherwise. KVM-on-Linux is host-mediated; it provides isolation
between guest processes but it is **not** a Type-1 partitioner and
provides no certified mixed-criticality scheduling, no FuSa-relevant
fault containment, and no Tegra-specific peripherals. The folder's
purpose is to make the gap legible, not to close it.
