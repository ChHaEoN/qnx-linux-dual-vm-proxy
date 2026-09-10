# startup/ — the `startup-t234-orin-nano` board directory

Written, building, and run on the board. M1 (one core), M2 (six cores at EL1) and M1b (six cores as the hypervisor
host at EL2) all passed on 2026-09-10; the records are under `results/orin-native-port/20260909T1100Z/`.

`build-board.sh` stages `t234-orin-nano/` into an extracted QNX BSP tree, builds
it against the startup library there, and runs a symbol gate on the result. On
this host it produces a 590,200 B linked startup (at M1b) with no warnings and passes every
check. That is the whole of the claim: it compiles, it links, and the symbols
that have to be there are there.

```bash
BSP=/path/to/extracted/BSP_hyp-guest-arm_be-800_... ./build-board.sh
```

## What is here

| file | what it does |
|---|---|
| `t234-orin-nano/main.c` | the call order, and the board's own `-m`, `-W` and `-t`. `-D`, `-P` and `-Q` belong to the library's common set and must not be redefined — the plan originally proposed `-D` and `-T`, both already taken. |
| `t234-orin-nano/init_raminfo.c` | the RAM range, stated rather than discovered. There is no `/memory` node in the firmware device tree and kexec adds none. |
| `t234-orin-nano/aarch64/init_intrinfo.c` | GICv3 by explicit region size. Short, because the library registers the interrupt entries itself. |
| `t234-orin-nano/board_smp.c`, `psci_cpu_id.c` | six cores over PSCI, with the affinity mapping this SKU actually has. |
| `t234-orin-nano/hw_sertcu.c`, `aarch64/callout_debug_tcu.S` | the Tegra Combined UART as startup's console and as procnto's, one patcher per mailbox. |
| `t234-orin-nano/wdt.c` | read and report both watchdogs always; disable only when asked. |
| `t234-orin-nano/aarch64/hvtimer.c` | the INTID 28 probe, run on every core under `-Q enable,el2-host` before procnto depends on it. |
| `make-m1b-images.sh` | the M1b images, derived from M2's buildfiles by changing only `-Q` and the two labels, with M2's record re-checked on every build. |
| `m1.build` | the M1 image. Never built with the real startup. |
| `m1-placeholder.build` | the layout check that verified the image base, using a shipped startup as a stand-in. |

## Three things that would have cost a board session each

The board directory is small, and most of what it took to write was finding out
which of the obvious ways to do things is wrong here.

**The redistributor frames are not contiguous.** `gic_v3_set_paddr` looks like
the natural call and is a wrapper that derives the frame limit from the CPU
count. This SKU is floor-swept: four cores in frames 0-3, two in frames 6 and 7.
A limit of six never reaches frame 7. Passing the region size explicitly gives
sixteen. The failure would have been an assertion during interrupt setup, on a
board with no console yet.

**The PSCI CPU ids are not the indices.** The library's default mapping returns
the linear index, which is right on most machines and wrong here for the same
floor-sweeping reason. Asking firmware to start "CPU 4" asks it to start an
affinity that does not exist. The board override wins by ordinary archive
behaviour, which is why the build script counts the definitions rather than
assuming.

**`hypervisor_init` goes first.** Not by convention: secondaries compare their
hypervisor flags against ones CPU 0 records in that call, and enabling VHE
redirects EL1 register accesses to EL2, so anything configured earlier is not
carried across. The library enforces both with a crash.

All three came out of reading the Apache-2.0 library source before writing
against it, which is recorded in
[board-dir-source-reads.md](../../results/orin-native-port/20260909T1100Z/board-dir-source-reads.md).

## The INTID 28 probe

Under `-Q enable,el2-host` the library gives procnto its clock on INTID 28, the EL2
virtual timer's interrupt, without checking that anything wired it. The Tegra234
device tree does not list it. `aarch64/hvtimer.c` checks on every core before
procnto depends on it:

1. It arms the EL2 physical timer (INTID 26, which Linux uses) as a control.
2. It arms the EL2 virtual timer.
3. It watches the redistributor's pending bits throughout, never taking an interrupt.

Anything but `wired` stops the run by name with a warm reset, which keeps the
black box. `-t continue` or `-t off` overrides that. On the board it said `wired` on
all six cores (M1b).

An earlier version of this file planned to learn the answer from whether the host
comes up and its timeouts work. That would have cost a power cycle, and the log
with it, if the interrupt were not wired: a host with a dead clock still reaches
user space and then stalls at its first timed wait.

Our code here is Apache-2.0, matching the BSP templates it is modelled on. No
QNX-shipped file is copied in, and the built startup is an output, not an
artefact this repository keeps.
