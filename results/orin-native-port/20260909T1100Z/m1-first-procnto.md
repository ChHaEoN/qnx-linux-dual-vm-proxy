# M1: the QNX kernel ran on the Jetson Orin Nano

2026-09-10, 09:41 local. The first native QNX image booted on the Jetson Orin Nano
Developer Kit, watched live over the J14 debug header. startup-t234-orin-nano
brought up the MMU, re-initialised the GICv3 that Linux had been using, set up the
system timer and the console callouts, built the system page, and handed over to
procnto — which printed:

```
T234 M1: procnto up
```

That line is produced by the QNX kernel itself, through the `display_char_tcu`
callout this port wrote, out of the Tegra Combined UART mailbox, onto J14 pin 4 and
into a USB-TTL adapter. **M1's central question — does QNX run on Tegra234 — is
answered yes.** User space then failed to start, on two buildfile errors that have
nothing to do with the kernel.

Full live capture:
[logs/sample-boot/orin-native-m1-first-procnto.log](../../../logs/sample-boot/orin-native-m1-first-procnto.log).

## What the capture shows, in order

**Linux leaving.** The kernel quiesced its IOMMUs (`arm-smmu ... disabling
translation`) and logged `kexec_core: Starting new kernel`.

**The shim**, reproducing the M0 register bank line for line — the same `EL=2`,
the same `HCR`, `MMFR1`, `CNTHPCTL=0x5` and `PC=0x80080000` — then `NORMALISED
TCUDROPS=0000000000000000` and `JUMP`. The hand-over is repeatable, not a one-off.

**startup-t234-orin-nano**, each line our board code or the library it drives:

| line | what it establishes |
|---|---|
| `t234: WDT0 CR=00710010 SR=00000010 ...` | `wdt.c` ran first, as designed |
| `Hypervisor support disabled` | `-Q disable` took effect; the drop to EL1 happened, and the board's own EL1 vectors were in place for it |
| `MMU: 16-bit ASID 48-bit PA TCR_EL1=...` | `init_mmu` succeeded on A78AE |
| `ARM GIC-?00 r0p4, arch v3.0 detected` | the GIC identified itself |
| `GICv3: itlines: 31, max INTID: 991` | 960 SPIs plus 32 private — exactly the geometry the board code assumed |
| `GICD @ 000000000f400000`, `GICR @ 000000000f440000` | the hard-coded bases are correct |
| `Add SPI entry 0 for vectors 32 -> 991 [SPI max: 960], Ok` | **the GIC re-initialised cleanly against a controller Linux had left enabled** — the single place the pre-flight review judged most likely to hang. The bounded register-write-pending wait never fired. |
| `cpu0: MIDR=410fd421 Cortex-A78ae r0p1` | the CPU, its revision, and its full cache topology |
| `cpu0: Core GICR SGI address: 0x0f450000` | the boot CPU's redistributor frame was found by affinity |
| `Loading IFS...done` | the image unpacked |

**The system page**, dumped in full: `qtime` at `CPS:0000000001dcd650` — 31.25 MHz,
32 ns per tick — on interrupt 27; the console callouts populated; one CPU of type
`410fd421`; the RAM range `0x80000000-0xbdffffff`; the device tree at
`0x270400000`; the GIC apertures; and the machine string
`'NVIDIA Jetson Orin Nano Developer Kit (Tegra234)'`.

**procnto**: `Starting next program`, then `T234 M1: procnto up`.

## What failed, and why

```
Unable to start "devc-pty" (2)
Unable to start "tcu-cat" (83)
Unable to start "pidin" (83)
Unable to access "/dev/ptyp0" (2)
Unable to start "shutdown" (83)
```

Both codes read straight out of the SDK's `errno.h`:

- **83 is `ELIBACC`, "can't access shared library".** The image carried the symlink
  `/usr/lib/ldqnx-64.so.2 -> /proc/boot/ldqnx-64.so.2` but not the file it points
  at, so every dynamically linked program — `tcu-cat`, `pidin`, `shutdown` — failed
  to find its interpreter. `dumpifs` on the image confirms the dangling link.
- **2 is `ENOENT`.** `devc-pty` had been placed at `/sbin/devc-pty` while the
  bootstrap sets `PATH=/proc/boot`, and there is no filesystem to search. With no
  `devc-pty`, `/dev/ptyp0` never appeared.

Because `shutdown` could not start either, the image did not reset itself as
designed, and the board stayed in QNX until the power was pulled. Nothing was lost
by that: this is exactly the case the serial console was added for, and the whole
run was captured live.

## What it settles

- **QNX runs natively on Tegra234**, entered by kexec from L4T, with no QEMU and no
  NVIDIA BSP.
- **The pre-flight fixes held.** No EL1 fault, no library assertion, and no spin in
  the GIC re-initialisation — so the evidence-preserving paths added after the
  pre-flight review were never needed on this run, but the one hazard they most
  guarded against did not occur either.
- **The J14 console works end to end** from startup through the kernel, which is
  the output channel every later milestone depends on.
- **The redistributor SGI frame address the `-t` probe needs** is now observed,
  `0x0f450000`, printed by the library itself — which removes the reason that probe
  was left unimplemented.

## What it does not show

User space has not run, so nothing above the kernel is demonstrated — no resource
manager, no shell, no process list. It ran on one CPU with `-Q disable`: SMP (M2)
and the hypervisor host at EL2 (M1b, M3) are untouched. No number exists, and this
is a functional result, which the licence treats as evaluation output until the
professor is consulted.
