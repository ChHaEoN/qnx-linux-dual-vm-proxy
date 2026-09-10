# M1b: the QNX host at EL2 with VHE on the Jetson Orin Nano

2026-09-10. The M1b design ([m1b-design.md](m1b-design.md), revision 2) was implemented, reviewed and then run on the
board as a ladder of images built from one startup and one smpcheck. Every run used M2's loop:

1. Stage the image and check its hash on the board.
2. Open the COM3 capture.
3. `kexec`.
4. Wait for L4T to come back with a new `boot_id`.
5. Read the black box from pstore.

**M1b is met.**
- R1 (`-Q enable,el2-host -P1`), R2 (`-P6`) and R2b (the identical `-P6` image) each met every criterion in the
  design's section 8.
- R0 first showed that the new startup left M2's `-Q disable` path unchanged.
- Every core that ran showed INTID 28, the EL2 virtual timer's interrupt, wired, which closes the plan's ranked
  unknown #3.

Curated capture of R2: [logs/sample-boot/orin-native-m1b-el2-host.log](../../../logs/sample-boot/orin-native-m1b-el2-host.log).

## Build

All images use one startup build and one smpcheck build:

| Input | Size | sha256 |
|---|---|---|
| `startup-t234-orin-nano` | 590,200 B | `90bf724c222b61f9791ad3bcaff60c6516be7180012333be9186a58d06d61896` |
| `smpcheck` | 33,136 B | `f8e2c3078f12ac8ef27f1c482e77bd98d2188293195721d8168892a605c666b0` |

`make-m1b-images.sh` built all eight images the design lists, including the contingencies that were never run.

- **What it checked:** that the M2 template and generator match git, that the six M2 buildfiles regenerate byte for
  byte, and that the six M2 kimgs still carry the sha256 prefixes in [m2-runs.md](m2-runs.md).
- **Derived buildfiles:** each M1b buildfile differs from its M2 source in exactly three lines: the `-Q` token and the
  two `display_msg` labels.
- **Pre-flight review:** before any board run, a separate review read the startup and smpcheck changes. It looked
  only for three things: silent-hang paths, a probe that could give a false verdict, and regressions on the
  `-Q disable` path. It found none.

## The runs

Times are UTC.

| Run | Image | `-Q` and `-P` | kimg sha256 prefix | Launch | Back after | Black box | Result |
|---|---|---|---|---|---|---|---|
| R0 | reg-p6 | `-Q disable -P6` | c391551a8e4b16bbc6f0e626 | 16:46:28 | 151 s | 19,384 B | `SMPCHECK RESULT PASS cpus=6/6`; M2's path unchanged |
| **R1** | **m1b-p1** | **`-Q enable,el2-host -P1`** | **cf0715ef7f0e447228d33655** | **16:49:55** | **148 s** | **7,936 B** | **cpu 0 `verdict=wired`; `PASS-DEGRADED cpus=1/6`, the expected shape at `-P1`** |
| **R2** | **m1b-p6** | **`-Q enable,el2-host -P6`** | **85970fe84cb5ed644e2cced6** | **16:53:14** | **148 s** | **23,031 B** | **cpus 0-5 `verdict=wired`; `SMPCHECK RESULT PASS cpus=6/6 secs=60 reasons=none`** |
| **R2b** | **m1b-p6** | **the same image** | **85970fe84cb5ed644e2cced6** | **16:56:27** | **150 s** | **23,031 B** | **as R2** |

- **Every run ended in the image's own `shutdown -S reboot`.** The PMC reported the reset as `MAINSWRST` (software
  reset), level L1.
- **No contingency was needed:** neither the el1-host images nor the `-P2`/`-P4` bisects.
- **Before R0, L4T was rebooted because it had been up for 5 h 26 min.**
  - The reboot hit an Oops in Linux's own shutdown path: `percpu_ref_get_many`, reached from a memcg slab free, at
    5 h 27 min of uptime.
  - The Oops became a panic, and the watchdog reset the board about three minutes later (PMC `BCCPLEXWDT`). pstore
    kept both records.
  - This is the second time Linux has faulted on its way down after hours of uptime. The first was M2's R0 attempt
    (`tcp_metrics_flush_all`, 2 h 25 min), in a different function.
  - Both Linux instances had been booted by a QNX warm reset. Whether that matters is not known.

## R0: the `-Q disable` regression

- **Three lines differ from M2's R4.** Normalised against M2's R4 black box (numbers and hex values masked), R0 differs
  in exactly these:
  - the corrected WDT0 wording;
  - smpcheck's new line `SMPCHECK census hyp qtime_intr=27 hypinfo_flags=0x0`;
  - smpcheck's new line `SMPCHECK census tick=ok ms=100 rc=0`.
- **Nothing el2-host-specific ran.** R0 printed `Hypervisor support disabled` as before, and no `hvtimer` or
  `el2-host` line.
- **Gate G1 passed.** 19,384 + 6 × 700 + 1,000 = 24,584 B, under 60,000 B, so the M1b images kept `-vvv`.

## What R1, R2 and R2b show, against the pass criteria

R2b's black box, normalised the same way, does not differ from R2's by a single line.

1. **VHE line.** `Enabling EL2 host hypervisor support (VHE)` appears once, and `Hypervisor support disabled` does not
   appear.
2. **Secondary entry (R2, R2b).** Cores 1 to 5 each printed `entry EL2` and their firmware register values.
3. **Per core, for every core started:**
   - `t234: cpu N up` with M2's MPIDR, redistributor frame, index and IPI value, and no `MISMATCH`;
   - `t234: cpu N el2-host EL2 HCR_EL2=0000030488000000`;
   - `t234: hvtimer cpu N verdict=wired reason=ok residue=00000000 qtime_intr=28`.
4. **Syspage.**
   - The qtime section carries `intr:28` and the hypinfo section carries `flags:0000000000000001`.
   - The cpuinfo flags are `c0f08c62` at `-P1` and `c0f08c7a` at `-P6`, the same values M2 printed at the same CPU
     counts.
5. **Hand-off.**
   - R2 and R2b printed `t234: all 6 cpus parked in smp_spin`.
   - Every run printed `System page at phys:` and then `Starting next program`, followed by
     `syspage::hypinfo::flags=0x00000001` from the kernel.
6. **Kernel and user space.** `T234 M1b -PN: procnto up` appeared, and `pidin info` listed N processors, twice.
7. **Census.**
   - `SMPCHECK census hyp qtime_intr=28 hypinfo_flags=0x1`;
   - `SMPCHECK census tick=ok ms=100 rc=0`, the kernel clock ticking on INTID 28;
   - the per-CPU rows, and `SMPCHECK CENSUS PASS`.
8. **Load.**
   - R2 and R2b: `SMPCHECK RESULT PASS cpus=6/6 secs=60 reasons=none`.
   - R1: `SMPCHECK RESULT PASS-DEGRADED cpus=1/6 secs=60 reasons=none`, the same shape as M2's `-P1` run.
   - Every worker's 100 ms timer check returned in 100 ms on the worker's own core.
9. **Reset.** `T234 M1b -PN: resetting so the log can be recovered` appeared. L4T answered with a new `boot_id`, the
   PMC reported `MAINSWRST`, and the black box was intact.
10. **Failure tokens.** None of the design's failure tokens appears in any of the three black boxes.

## The INTID 28 probe, as the black box records it

The probe printed the same four lines on every core in R1, R2 and R2b, 13 cores in all, apart from the core number:

```
t234: hvtimer cpu N ctx gicd_ctlr=00000012 sec=1 igroupr0=00000000 isen=00000001 isact=00000000 cfg1=00000000 prio26=000000a0 prio28=000000a0 cntvoff=0000000000000000 hpctl=00000000 hvctl=00000000
t234: hvtimer cpu N CNTHP ppi=26 pre=0 base=00000000 early=00000000 on=04000000 mask=00000000 off=00000000 istatus=1 t_ms=2 moved=04000000
t234: hvtimer cpu N CNTHV ppi=28 pre=0 base=00000000 early=00000000 on=10000000 mask=00000000 off=00000000 istatus=1 t_ms=2 moved=10000000
t234: hvtimer cpu N verdict=wired reason=ok residue=00000000 qtime_intr=28
```

- **Starting state.** Nothing was pending before either timer was armed (`base=00000000`). Both timers were off
  (`hpctl`, `hvctl`), and the virtual offset was 0.
- **The control worked.** Arming the EL2 physical timer (CNTHP) set pending bit 26 and no other bit, and masking the
  timer cleared it. The method therefore sees a level-sensitive PPI's pending state from Non-secure EL2, with the
  interrupt disabled and never taken. INTID 26 is the timer Linux uses at EL2.
- **The virtual timer drives INTID 28.** Arming the EL2 virtual timer (CNTHV) set bit 28 and no other bit
  (`moved=10000000`), and masking it cleared it. The timer's own ISTATUS bit was 1. Both conditions were met within
  2 ms.
- **The Secure-group case is ruled out.** The GIC reports two security states (`sec=1`), and both PPIs read priority
  `0xa0` from the Non-secure side. So neither is a Secure-group interrupt masquerading as unwired.

This closes ranked unknown #3 for this SKU and firmware, in the Non-secure view. The kernel side agrees: with
`qtime->intr = 28`, procnto's clock ticked (`tick=ok`) and every timed wait in the script returned.

## Unknowns the runs answered

- **INTID 28 is wired to the EL2 virtual timer on all six cores** (plan unknown #3; design R1). M3 can therefore run
  the VHE host, and no el1-host relabelling is needed.
- **A `CPU_ON` issued from EL2 with E2H set enters the secondary exactly like one issued from EL1** (design R12). All
  five secondaries, in both six-core runs, reported:
  - `HCR_EL2=0x80000000`, `SCTLR_EL2=0x30c50830` and `MDCR_EL2=0x6`;
  - `HSTR_EL2`, `ICH_HCR_EL2` and the three timer controls 0;
  - `CNTFRQ` already programmed.
- **procnto 8.0 runs at EL2 on this silicon without `AARCH64_CPU_FLAG_VHE`** (`-F0x10000`, design R7). It also runs
  with the EL2&0 MMU turned on by the library's EL1-named writes (R13), and user space's `ClockCycles()` did not trap
  (R18).
- **No FP/SIMD trap happened at EL2** in the startup's linked libc routines in these runs (R8).
- **`HCR_EL2` after `hyp_enable_el2_host` reads `0x0000030488000000`.**
  - That value is RW, TGE, E2H, API and APK.
  - The design predicted `0x00000304a8000000`, because `at_el2` writes HCD (bit 29) as well
    (lib/aarch64/_start_el1.S:152). HCD reads back clear.
  - That fits the Arm ARM defining HCR_EL2.HCD as RES0 when EL3 is implemented, with HVC then controlled by
    SCR_EL3.HCE. This is VENDOR_CLAIM; it was not checked further here.
  - The design's section 10 line "`HCR_EL2.HCD` stays set" is therefore wrong. What controls HVC for M3's guests is
    firmware's SCR_EL3, not startup.

## Observed, not a criterion: cluster 1 runs at the same fixed rate at EL2

smpcheck's busy-loop rate, in iterations per second, is informational only. CPU frequency is not controlled.

| Run | Host mode | Cluster 0, per core | Cluster 1, per core |
|---|---|---|---|
| R0 | `-Q disable` (EL1) | 666 million | 57.0 million |
| R1 | el2-host | 630 million (cpu 0 only) | not started |
| R2 | el2-host | 401 million | 57.1 million |
| R2b | el2-host | 363 million | 57.0 million |

- **The cluster-1 rate did not change with the exception level the kernel runs at.** It was 57.0-57.1 million in
  every M2 run from R3 on and in every M1b run.
- **That rules out the host mode as the cause, and nothing else.** The cause stays open.
- **It matters for M3.** A hardware-timed number taken on a cluster-1 core would carry this factor.

## Not shown

- **No hypervisor workload.** Nothing about qvm, a guest, stage-2 translation, a virtual GIC, guest timers, HVC or
  world switches. `VTTBR_EL2` stays 0. All of that is M3.
- **The INTID 28 result is narrow.** It holds only in the Non-secure view, on this SKU and on L4T R36.4.7 firmware,
  and only SGI/PPI bits 0-31 of each core's `GICR_ISPENDR0` were watched.
- **Which PPI served each secondary's kernel timer is inferred, not observed.** procnto was told 28, and the timed
  waits returned on each core.
- **The probe touched the EL2 timers.** It arms and disarms both on every core. It leaves both controls 0 and
  restores both compare values, but procnto inherits a system that ran it.
- **No timing or performance figure.** Tick lengths, `t_ms` and busy-loop rates are all uncontrolled.
- **Repeatability is thin:** two runs at `-P6` and one at `-P1`, with no soak.
- **Two windows remain unrecoverable if they hang:** before `board_init` on CPU0, and after procnto takes over the
  vectors.
- **Nothing here is publishable** before the supervising professor is consulted (NC QDL v7 4.6(i)).
