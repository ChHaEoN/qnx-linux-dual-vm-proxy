# skills/bsp-porting — Generic BSP porting paradigm

> **Phase 0 study notes** — the porting workflow this project actually
> follows in Phase 1. Worked examples land in `paradigm.md` and (later)
> in ~~`docs/findings/phase-1-bringup.md`~~ **`logs/sample-boot/` and
> `docs/findings.md` (2026-09-19: the old path never existed)**.

---

## When to use

- Bringing up an OS on a new SoC, board, or virtual machine target
- Diagnosing why early bring-up is stuck (MMU, UART, timer, IRQ, DMA)
- Reviewing an existing BSP to spot weak coverage areas

## Why

Without a paradigm, BSP porting drifts into *whack-a-mole*. The four-stage
workflow (discovery → bring-up → drivers → validation) gives a checklist
to triage where you are, what's the next "first thing that should boot,"
and how to know when each stage is actually done.

## Scope (in vs. out)

**In scope:**
- aarch64 virt-machine target (QEMU)
- QNX SDP and Linux as the two OSes ported
- UART-first bring-up, then timer/IRQ, then virtio devices

**Out of scope:**
- Real-silicon bring-up (no JTAG, no logic analyzer access here)
- DSP / GPU / NPU bring-up
- BL1/BL2/BL31 ARM Trusted Firmware customization

## Files

- `paradigm.md` — step-by-step workflow + common pitfalls. **Not written yet**
  (2026-09-19: this section listed it as if it existed; the directory holds only
  this README). The workflow it would describe is exercised for real in
  `orin-native/startup/qemu-virt/` — a board written from scratch against the
  device tree QEMU generates.

## Key references (study only)

- ARM® Architecture Reference Manual (ARMv8-A) — register map, exception levels
- QNX BSP Developer's Guide (BlackBerry QNX docs) — board-support architecture
- *Linux kernel arch/arm64/* — DTS conventions, defconfig structure
- Brendan Gregg's "boot performance" talks — for validation phase
- *Bootlin* embedded Linux training materials — workflow framing

---

## Study notes

~~The paradigm is in `paradigm.md`. This README is the index.~~
**2026-09-19: `paradigm.md` is not written; the directory holds only this
README. The workflow is exercised for real in
`orin-native/startup/qemu-virt/` (see Files, above).**

## Applied to this project

In Phase 1, bring-up follows the four stages literally:

1. **Discovery** — confirm QEMU virt machine memory map, exception levels,
   GIC version; gather DTBs from QEMU `-machine virt -dumpdtb`
2. **Bring-up** — UART (PL011) printable from earliest possible point;
   timer (arch generic timer) drives a heartbeat
3. **Drivers** — virtio-net, virtio-console, virtio-blk
4. **Validation** — boot logs in ~~`docs/findings/phase-1-bringup.md`~~
   **`logs/sample-boot/`, findings in `docs/findings.md` (2026-09-19: the old
   path never existed)**,
   timing measurements via `dmesg` timestamps and host-side `qemu` traces
