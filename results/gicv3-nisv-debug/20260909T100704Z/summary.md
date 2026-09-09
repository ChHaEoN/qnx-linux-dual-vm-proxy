# GICv3 / KVM_EXIT_ARM_NISV diagnostic — 20260909T100704Z

Read-only collection by `scripts/diagnose-gicv3-nisv.sh` (nothing booted, nothing privileged executed).
Scope: the qnx-safety-vm IFS hanging under `-enable-kvm` after `FOUND GICv3 ITS`. **Not** the QHV/TCG QEMU-6.2 virtual-timer hang — those logs are listed as excluded.
Results dir: `results/gicv3-nisv-debug/20260909T100704Z`. Arguments: `--esr 0x92000045`.

## Environment

- platform: windows-gitbash (uname -s: MINGW64_NT-10.0-26200, uname -m: x86_64)
- bash: 5.3.9(1)-release
- generated (UTC): 20260909T100704Z
- os-release: not present (non-Linux host)
- /dev/kvm: not applicable on windows-gitbash
- running qemu process lines: 0 (raw/qemu-processes.txt)
- QEMU binaries:
  - /c/Program Files/qemu/qemu-system-aarch64.exe :: QEMU emulator version 11.0.50 (v11.0.0-12631-g54e84cdc7a) :: accel: tcg 

Tools detected:

| tool | path |
|---|---|
| aarch64 objdump | /c/Users/<user>/qnx800/host/win64/x86_64/usr/bin/ntoaarch64-objdump |
| aarch64 nm | /c/Users/<user>/qnx800/host/win64/x86_64/usr/bin/ntoaarch64-nm |
| aarch64 addr2line | /c/Users/<user>/qnx800/host/win64/x86_64/usr/bin/ntoaarch64-addr2line |
| aarch64 readelf | /c/Users/<user>/qnx800/host/win64/x86_64/usr/bin/ntoaarch64-readelf |
| dumpifs | /c/Users/<user>/qnx800/host/win64/x86_64/usr/bin/dumpifs |
| dtc | not found |
| fdtdump | not found |
| fdtget | not found |
| python | /c/Users/<user>/AppData/Local/Programs/Python/Python312/python |
| socat | not found |
| git | /mingw64/bin/git |
| sha256sum | /usr/bin/sha256sum |
| timeout | /usr/bin/timeout |

## Repository revision

- HEAD: 93cd778386569a80954a1993f54aa6f9af848f3f (branch main), describe 93cd778
- working tree and last commits: raw/git-state.txt
- local ifs.bin sha256: 92868b2f116f17c06d26585b9618682076913d17491bdeb22c4a0392d43dd745
- hash recorded for the hung KVM boots (a1.metal log header): 92868b2f116f17c06d26585b9618682076913d17491bdeb22c4a0392d43dd745

## Evidence found

Key-term hits in docs/, scripts/, logs/, README/CLAUDE/AGENTS (raw/repo-evidence-grep.txt):

| term | matching lines |
|---|---|
| `KVM_EXIT_ARM_NISV` | 12 |
| `kvm_guest_fault` | 1 |
| `0x92000045` | 1 |
| `ISV=0` | 2 |
| `VBAR_EL1` | 1 |
| `str w3` | 5 |
| `IPRIORITY` | 3 |
| `0x420` | 6 |
| `b8004403` | 1 |
| `fno-auto-inc-dec` | 3 |
| `gic_v3.c` | 7 |
| `FOUND GICv3 ITS` | 33 |
| `a1.metal` | 29 |
| `PE is not awake` | 54 |

Boot-log classification (logs/sample-boot); hang signature = 'FOUND GICv3 ITS' with no later '** CPU n PE is not awake':

| file | topic | accel | classification | ESR/exit-reason tokens (non-comment lines) | QEMU_EXIT |
|---|---|---|---|---|---|
| aws-a1-metal-kvm-nisv-repro.log | in-topic | kvm | HANG-AFTER-ITS-DISCOVERY signature (no 'PE is not awake', no 'Startup complete') | no — symptom-only | QEMU_EXIT=124 |
| orin-qhv-tcg-q111-boot-blk-only.log | EXCLUDED (QHV/TCG leg, different defect) | tcg | boots (Startup complete) | no — symptom-only | — |
| orin-qhv-tcg-q111-boot-rng-slot3.log | EXCLUDED (QHV/TCG leg, different defect) | tcg | boots (Startup complete) | no — symptom-only | — |
| orin-qhv-tcg-q111-nohypvirt-control.log | EXCLUDED (QHV/TCG leg, different defect) | tcg (from filename) | partial (past ITS discovery and PE wake; no 'Startup complete' in capture) | no — symptom-only | — |
| orin-qhv-tcg-q111-rng-snapshot-boot1.log | EXCLUDED (QHV/TCG leg, different defect) | tcg (from filename) | boots (Startup complete) | no — symptom-only | — |
| orin-qhv-tcg-q62-INVALID-rng-in-slot2.log | EXCLUDED (QHV/TCG leg, different defect) | tcg | partial (past ITS discovery and PE wake; no 'Startup complete' in capture) | no — symptom-only | — |
| orin-qhv-tcg-q62-a57-control.log | EXCLUDED (QHV/TCG leg, different defect) | tcg (from filename) | partial (past ITS discovery and PE wake; no 'Startup complete' in capture) | no — symptom-only | — |
| orin-qhv-tcg-q62-hang-blk-only.log | EXCLUDED (QHV/TCG leg, different defect) | tcg | partial (past ITS discovery and PE wake; no 'Startup complete' in capture) | no — symptom-only | — |
| orin-qhv-tcg-q62-hang-rng-slot3.log | EXCLUDED (QHV/TCG leg, different defect) | tcg | partial (past ITS discovery and PE wake; no 'Startup complete' in capture) | no — symptom-only | — |
| orin-tcg-qnx-boot-timed1.log | in-topic | tcg (from filename) | boots (Startup complete) | no — symptom-only | — |
| orin-tcg-qnx-boot1.log | in-topic | tcg | boots (Startup complete) | no — symptom-only | — |
| orin-tcg-qnx-ipc-boot1.log | in-topic | tcg | boots (Startup complete) | no — symptom-only | — |
| orin-tcg-qnx-ipc-client1.log | in-topic | tcg (from filename) | no startup markers | no — symptom-only | — |
| orin-tcg-qnx-network1.log | in-topic | tcg | boots (Startup complete) | no — symptom-only | — |
| qhv-tcg-host-and-guest-boot.log | EXCLUDED (QHV/TCG leg, different defect) | tcg | boots (Startup complete) | no — symptom-only | — |
| qhv-tcg-ipc-benchmark.log | EXCLUDED (QHV/TCG leg, different defect) | tcg (from filename) | boots (Startup complete) | no — symptom-only | — |
| qhv-tcg-rq2-hyp-shm-host-probe.log | EXCLUDED (QHV/TCG leg, different defect) | tcg (from filename) | boots (Startup complete) | no — symptom-only | — |
| qhv-tcg-rq2-shmem-roundtrip-attempt1-bus-error.log | EXCLUDED (QHV/TCG leg, different defect) | tcg (from filename) | boots (Startup complete) | no — symptom-only | — |
| qhv-tcg-rq2-shmem-roundtrip-success.log | EXCLUDED (QHV/TCG leg, different defect) | tcg (from filename) | boots (Startup complete) | no — symptom-only | — |
| qhv-tcg-sentinel-recovery-committed15-5-check.log | EXCLUDED (QHV/TCG leg, different defect) | tcg (from filename) | boots (Startup complete) | no — symptom-only | — |
| qhv-tcg-sentinel-recovery-diag300-run1.log | EXCLUDED (QHV/TCG leg, different defect) | tcg (from filename) | boots (Startup complete) | no — symptom-only | — |
| qhv-tcg-sentinel-recovery-diag300-run2.log | EXCLUDED (QHV/TCG leg, different defect) | tcg (from filename) | boots (Startup complete) | no — symptom-only | — |
| qhv-tcg-sentinel-recovery-diag300-run3.log | EXCLUDED (QHV/TCG leg, different defect) | tcg (from filename) | boots (Startup complete) | no — symptom-only | — |
| windows-qhv-tcg-boot-timed1.log | EXCLUDED (QHV/TCG leg, different defect) | tcg | boots (Startup complete) | no — symptom-only | — |
| windows-qhv-tcg-q62-cell.log | EXCLUDED (QHV/TCG leg, different defect) | tcg (from filename) | partial (past ITS discovery and PE wake; no 'Startup complete' in capture) | no — symptom-only | — |
| windows-tcg-qnx-boot-timed1.log | in-topic | tcg (from filename) | boots (Startup complete) | no — symptom-only | — |

Documented facts carried by the repo (prose unless a log is cited):

- observed on Orin Nano (ftrace, transcribed, no raw file): `kvm_guest_fault hsr=0x92000045`, `kvm_userspace_exit reason KVM_EXIT_ARM_NISV (28)` — docs/orin-port.md risk register
- observed on Orin Nano (QEMU monitor, transcribed): `VBAR_EL1=0x4008d800`; vector slot +0x200 disassembles to `b .` — same row
- observed in a committed log: a1.metal KVM boot prints only `FOUND GICv3 ITS` for 60 s, QEMU_EXIT=124 — logs/sample-boot/aws-a1-metal-kvm-nisv-repro.log (n=1, no ESR/exit data)
- observed in committed logs: the same ifs.bin boots to 'Startup complete' under TCG on the Orin and on Windows
- observed at compile level (2026-09-08): BSP gic_v3.c builds to `str w3,[x0],#4` at GICD+0x420 (opcode b8004403); `-fno-auto-inc-dec` removes all 4 writeback MMIO stores in that object — docs/findings.md
- derived, not recorded anywhere before this script: ESR field decode (below) and the expected IPA GICD+0x420

## Registers

ESR decoder self-test on the repo's documented value (this is a decode of prose, not a fresh capture):

- value: 0x92000045
- EC [31:26] = 0x24 — Data Abort from a lower EL
- IL [25] = 1 (32-bit instruction)
- ISS [24:0] = 0x0000045
- Data Abort ISS:
  - ISV [24] = 0 — instruction syndrome NOT VALID: SAS/SSE/SRT/SF/AR are RES0 and are NOT decoded here
  - VNCR [13] = 0, bits [12:11] = 0 (RES0 for this DFSC), FnV [10] = 0 (FAR valid), EA [9] = 0, CM [8] = 0, S1PTW [7] = 0
  - WnR [6] = 1 (write)
  - DFSC [5:0] = 0x05 — Translation fault, level 1
  - reading: ISV=0 means the hardware did not describe the access (this is what the KVM API calls a 'NISV' Data Abort). ISV=0 by itself does NOT prove the IPA is GIC MMIO — that needs HPFAR/IPA (see Candidate IPA) or the disassembled instruction.

Supplied --esr 0x92000045:

- value: 0x92000045
- EC [31:26] = 0x24 — Data Abort from a lower EL
- IL [25] = 1 (32-bit instruction)
- ISS [24:0] = 0x0000045
- Data Abort ISS:
  - ISV [24] = 0 — instruction syndrome NOT VALID: SAS/SSE/SRT/SF/AR are RES0 and are NOT decoded here
  - VNCR [13] = 0, bits [12:11] = 0 (RES0 for this DFSC), FnV [10] = 0 (FAR valid), EA [9] = 0, CM [8] = 0, S1PTW [7] = 0
  - WnR [6] = 1 (write)
  - DFSC [5:0] = 0x05 — Translation fault, level 1
  - reading: ISV=0 means the hardware did not describe the access (this is what the KVM API calls a 'NISV' Data Abort). ISV=0 by itself does NOT prove the IPA is GIC MMIO — that needs HPFAR/IPA (see Candidate IPA) or the disassembled instruction.

- guest PC: not supplied (the repo never recorded the numeric PC)
- FAR_EL2/HXFAR: not supplied; HPFAR_EL2: not supplied; IPA: not supplied
- VBAR_EL1 = 0x4008d800 — documented (docs/orin-port.md), read live on 2026-07-28, no dump file; the post-hang PC was never read, so 'parked at VBAR+0x200' is an inference

## Candidate IPA

- no --hpfar/--far/--ipa supplied: no observed IPA. The repo never recorded one either (docs/orin-port.md quotes hsr and the exit reason only).
- derived expectation (hypothesis): GICD base + 0x420 = 0x8000420 using reference GICD base (unverified); the +0x420 comes from the documented disassembly (GICD_IPRIORITYRn, first loop iteration)

## MMIO range comparison

- QEMU 'virt' board memmap constants (hw/arm/virt.c) — assumed for -machine virt; verify against a dumpdtb from the SAME QEMU/KVM invocation before trusting
- DTB-derived ranges describe the DTB you passed; only a dumpdtb from the failing KVM invocation itself (same QEMU binary, -cpu host, -enable-kvm) describes the hung guest's view
- DTB: NOT RUN — --dtb not given (produce one with: qemu-system-aarch64 -machine virt,gic-version=3,dumpdtb=virt.dtb -cpu host -enable-kvm -smp 2 -m 1G -display none)
- monitor/QMP: NOT RUN — no --monitor-socket/--qmp-socket given; the exact read-only commands are printed under 'Exact next commands'

| label | base | end (incl.) | size | source |
|---|---|---|---|---|
| GICD | 0x8000000 | 0x800ffff | 0x10000 | reference |
| ITS | 0x8080000 | 0x809ffff | 0x20000 | reference |
| GICR0 | 0x80a0000 | 0x8ffffff | 0xf60000 | reference |

No observed IPA. Derived expectation (hypothesis, from static disassembly: GICD + 0x420 with reference GICD base (unverified)): 0x8000420 — by construction inside GICD, so this comparison is not evidence.

## Faulting instruction

- status: BLOCKED — --elf and/or --guest-pc not given — the repo records no numeric faulting PC, and the shipped startup is NCEULA (not committed)
- BLOCKED: no --elf/--guest-pc. Documented (prose, docs/orin-port.md + docs/findings.md 2026-09-08): `str w3,[x0],#4` at GICD+0x420 in gic_v3_initialize, opcode 0xb8004403 in the BSP-rebuilt gic_v3.o.
- classifier on the documented opcode 0xb8004403: ordinary load/store, immediate POST-INDEXED (writeback); writeback yes; expected ISV 0; base register updated after the access; imm9=4; ARM ARM excludes writeback forms from ISV=1; size=word (w-reg), opc=0 (store), Rt=3, Rn=0
- classifier on the -fno-auto-inc-dec replacement 0xb81fc003: ordinary load/store, unscaled immediate (LDUR/STUR); writeback no; expected ISV 1; single register, no writeback; imm9=-4; size=word (w-reg), opc=0 (store), Rt=3, Rn=0
- classification is by opcode encoding class only (ARM ARM 'Loads and stores' decode); 'expected ISV' restates the architectural rule — ISV=1 only for a single general-purpose-register load/store with no writeback that is not exclusive; pair, exclusive, atomic, SIMD&FP, memory-tag and writeback forms report ISV=0 — as an expectation, not an observation. PC-relative literal loads are not excluded by the rule but cannot target MMIO, and prefetch hints (PRFM/PRFUM) never fault, so both are marked n/a

## Test status matrix

| test | status | detail |
|---|---|---|
| Host CPU inventory (lscpu) | **NOT RUN** | lscpu not on PATH (windows-gitbash) |
| qemu-system-aarch64 located | **PASS** | 1 binary/binaries, see raw/qemu-*-version.txt |
| KVM accelerator compiled into a local QEMU | **NOT APPLICABLE** | windows-gitbash: local QEMU builds are TCG-only; KVM needs a Linux arm64 host |
| /dev/kvm present and accessible | **NOT APPLICABLE** | windows-gitbash has no /dev/kvm; KVM reproduction needs the Orin or an arm64 metal instance |
| Host dmesg KVM/GIC excerpt | **NOT APPLICABLE** | no Linux kernel log on windows-gitbash |
| Host journalctl -k KVM/GIC excerpt | **NOT APPLICABLE** | no journald on windows-gitbash |
| Running QEMU /proc inspection (--qemu-pid) | **NOT RUN** | --qemu-pid not given; 0 qemu process line(s) listed in raw/qemu-processes.txt |
| Git repository state captured | **PASS** | HEAD 93cd77838656 (93cd778) |
| Local ifs.bin sha256 == hash recorded for the hung KVM boots | **PASS** | 92868b2f116f17c0... matches the a1.metal log header (same image that hung on Orin and a1.metal) |
| Repo evidence grep (key terms present) | **PASS** | 142 matching line(s) across 14 terms, raw/repo-evidence-grep.txt |
| a1.metal KVM serial log shows the hang signature | **PASS** | boot FAIL with 'FOUND GICv3 ITS' then silence, QEMU_EXIT=124 (timeout); NO ISV/exit-reason data in that log — NISV there is inferred |
| TCG control logs (in-topic) reach 'Startup complete' | **PASS** | 5 TCG log(s) boot the same IFS; isolates the hang to KVM acceleration |
| ESR decoder self-test (0x92000045 -> EC=0x24, IL=1, ISV=0, WnR=1, DFSC=0x05) | **PASS** | decoder reproduces the expected fields from the repo's documented hsr value |
| Supplied --esr decoded | **PASS** | EC=0x24 ISV=0 WnR=1 DFSC=0x5; value is identical to the one documented in docs/orin-port.md — unless you captured it yourself this is a re-decode of prose, not a new observation |
| Candidate IPA composed from --hpfar/--far | **NOT RUN** | no --hpfar/--far/--ipa given; the repo holds no recorded HPFAR/IPA to fall back on |
| DTB analysis (GIC/ITS/timer/PSCI/cpus nodes located) | **NOT RUN** | --dtb not given (produce one with: qemu-system-aarch64 -machine virt,gic-version=3,dumpdtb=virt.dtb -cpu host -enable-kvm -smp 2 -m 1G -display none) |
| QEMU monitor/QMP info capture (registers, mtree, qtree, cpus, irq) | **NOT RUN** | no --monitor-socket/--qmp-socket given; the exact read-only commands are printed under 'Exact next commands' |
| Observed IPA lies inside a GIC MMIO range | **NOT RUN** | no observed IPA (no --hpfar/--far/--ipa); only the derived expectation 0x8000420 is shown, which is circular and proves nothing |
| Opcode classifier self-test (b8004403 post-indexed store / b81fc003 unscaled store) | **PASS** | both encodings quoted in docs/findings.md classify as documented (writeback+ISV=0 vs no-writeback+ISV=1) |
| Faulting-instruction disassembly + opcode classification (--elf/--guest-pc) | **BLOCKED** | --elf and/or --guest-pc not given — the repo records no numeric faulting PC, and the shipped startup is NCEULA (not committed) |
| KVM boot reproduction of the IFS on this host | **NOT APPLICABLE** | no usable KVM on this host (not applicable on windows-gitbash) |
| ftrace capture of kvm_guest_fault / kvm_userspace_exit during a KVM boot | **BLOCKED** | needs a Linux/KVM host (Orin or arm64 metal) — not this one |
| TCG control boot of the same IFS on this host | **NOT RUN** | not executed by this script; existing TCG controls are classified above |
| KVM re-check with from-source QEMU 11.1.0 (--enable-kvm) on the Orin | **NOT RUN** | never performed; every NISV data point is QEMU 6.2.0 (scripts/orin/build-qemu-on-orin.sh built the binary) |
| KVM variants -smp 1 / gic-version=host / its=off logged with n>=1 each | **NOT RUN** | asserted in docs/orin-port.md without logs or counts; commands printed below |
| a1.metal (or c7g.metal) re-run with ftrace to classify that hang as NISV by data | **NOT RUN** | a1.metal log is symptom-only; c7g.metal blocked by the 32-vCPU quota |
| Boot of a startup rebuilt with -fno-auto-inc-dec under KVM | **BLOCKED** | startup-qemu-virt cannot be relinked (BSP ships boards/armv8_fm, not boards/qemu-virt) |

## Current diagnosis

**Facts (observed, with where):**

1. Under `-machine virt,gic-version=3 -cpu host -enable-kvm` the IFS prints `FOUND GICv3 ITS` and nothing else; the QEMU process stays alive. Orin Nano (prose, 2026-07-28) and a1.metal (committed log, 2026-07-29, n=1).
2. On the Orin the host ftrace showed `kvm_guest_fault hsr=0x92000045` and a `KVM_EXIT_ARM_NISV (28)` userspace exit (prose transcription). Decoded here: EC=0x24 Data Abort from a lower EL, ISV=0, WnR=1 (write), DFSC=0x05 stage-2 translation fault level 1 — i.e. a write to an IPA with no stage-2 mapping (what emulated MMIO looks like) whose syndrome the CPU did not describe.
3. The same ifs.bin (sha256 92868b2f116f17c0...) boots under TCG on the same Orin and on Windows (committed logs).
4. VBAR_EL1=0x4008d800 was read live; the +0x200 slot is `b .` (prose).
5. QNX's own BSP source compiles to `str w3,[x0],#4` (0xb8004403) at GICD+0x420, and `-fno-auto-inc-dec` removes that encoding class from the object (compile-level, docs/findings.md 2026-09-08).
6. vGIC creation succeeds on both hosts (bare `-kernel /dev/null` smoke tests clean, prose).

**Hypotheses (not yet shown by data):**

- that the faulting IPA is 0x08000420 (GICD_IPRIORITYR<8>) — no HPFAR/IPA was ever captured; the address is derived from static disassembly plus the virt board map
- that QEMU actually injected an external Data Abort and the guest is parked at VBAR_EL1+0x200 — inferred from strings in the QEMU binary and the vector slot content; no post-hang PC read
- that the a1.metal hang is the same NISV mechanism — same symptom, no ESR/exit-reason data there
- that removing the writeback store makes the guest boot under KVM — nothing rebuilt has been booted; startup-qemu-virt cannot be relinked
- that the '-smp 1 / gic-version=host / its=off' variants hang identically — asserted, no logs or counts

**What this run added:** decoder + classifier self-tests, log classification, image-hash check, tool inventory. It did not add hardware evidence (see matrix).

## Ranked hypotheses

Eight candidate explanations, ranked against the evidence above. The two the repo already established are marked CONFIRMED; a CONFIRMED status here means 'observed on Orin + reproduced at compile level', not 'closed'. This enumeration is the script's; the original author's wording was not available to it.

| # | hypothesis | status | evidence for / against |
|---|---|---|---|
| 1 | The GICD write is a writeback-form (post-indexed) store, so the CPU reports ESR.ISV=0 and KVM cannot decode it -> KVM_EXIT_ARM_NISV | **CONFIRMED (Orin)** | hsr=0x92000045 decodes to ISV=0/WnR=1; `str w3,[x0],#4` found by static disassembly and reproduced from BSP source; the KVM API documents this exact exit for non-ISV MMIO |
| 2 | The target is GIC distributor MMIO (GICD_IPRIORITYRn, GICD+0x420) emulated in-kernel by vgic-v3, so there is no decoder fallback | **CONFIRMED at instruction level; IPA unobserved** | offset 0x420 from disassembly + gic_v3.h (IPRIORITYn=0x400); no HPFAR/IPA capture exists — see 'Candidate IPA' |
| 3 | QEMU 6.2's kvm_arm_handle_dabt_nisv() injects a synthetic external Data Abort; QNX startup's EL1 vector at VBAR_EL1+0x200 is `b .` -> silent park | **SUPPORTED, partly inferred** | VBAR_EL1 read live and slot disassembled; injection inferred from binary strings; post-hang PC never read |
| 4 | Guest memory map / DTB mismatch (GICD base wrong, unmapped IPA) rather than an MMIO decode problem | **WEAKENED** | DFSC=0x05 is consistent with either; but the same IFS + same board map boots under TCG, and vGIC/ITS discovery succeeds first. A captured IPA would settle it |
| 5 | ITS involvement (its=on default, GITS programming) is the trigger | **WEAKENED (unlogged)** | faulting register is GICD not GITS; docs assert its=off hangs identically but no log/count exists |
| 6 | vGIC device-creation failure (AGX Orin VmCreateGIC Error(19) family) | **REFUTED on both hosts** | bare vGIC smoke tests clean; guest runs far enough to print ITS discovery |
| 7 | Tegra234 / Cortex-A78AE / VHE-specific silicon quirk | **WEAKENED (n=1)** | identical symptom on a1.metal (Annapurna A72, non-VHE host); single run, symptom-only |
| 8 | QEMU-version-specific bug (6.2.0) fixed by a newer QEMU on KVM | **UNTESTED, assessed unlikely** | upstream KVM backend injects by design (no decode fallback for KVM); the from-source 11.1.0 --enable-kvm re-check was never run; a1.metal QEMU version unrecorded |

## Missing evidence

- raw ftrace output (trace_pipe) from the Orin: numeric PC, IPA/HPFAR, HXFAR, vCPU id, exit count — only hsr and the exit reason were transcribed
- any serial log of an Orin KVM attempt (only the TCG control was committed)
- QEMU monitor dump file (VBAR_EL1 is a transcribed value); post-hang PC/ELR_EL1/ESR_EL1 read to confirm the park at VBAR+0x200
- command lines, logs and counts for the -smp 1 / gic-version=host / its=off variants
- DTB (dumpdtb) and 'info mtree' from the failing KVM invocation; whether QNX startup reads the FDT at all
- an ESR/exit-reason capture on a1.metal (or any second host) — currently symptom-only; QEMU version there
- KVM re-check with the from-source QEMU 11.1.0 on the Orin; c7g.metal run (quota-blocked)
- a bootable startup rebuilt with -fno-auto-inc-dec (needs the qemu-virt board source from QNX); an audit of libstartup.a beyond gic_v3.c
- guest-side data value at the fault (w3=0xA0A0A0A0 known only from the rebuilt object)
- this run: no --hpfar/--ipa supplied (no IPA comparison possible)
- this run: no --elf/--guest-pc supplied (no live disassembly)
- this run: no --dtb supplied (reference board constants used, unverified)

## Exact next commands

Printed, not executed. Anything with sudo is privileged. The Orin is in use by another experiment at the time of writing — do not run the Orin block until it is free. Replace <...> placeholders.

```
### A. Orin Nano (L4T), fresh KVM capture with raw evidence — privileged, PRINT ONLY
# 0. environment stamp
uname -a; grep -m1 'CPU part' /proc/cpuinfo; qemu-system-aarch64 --version | head -1; dpkg -s qemu-system-arm 2>/dev/null | grep '^Version'
sudo dmesg | grep -iE 'kvm|vgic|gic|vhe|hyp mode|ipa size' > results/gicv3-nisv-debug/20260909T100704Z/raw/orin-dmesg-kvm.txt
ls -l /dev/kvm; id
# 1. DTB + memory tree of the exact failing invocation (KVM shape, -cpu host)
sudo qemu-system-aarch64 -machine virt,gic-version=3,dumpdtb=virt-kvm-gicv3.dtb -cpu host -enable-kvm -smp 2 -m 1G -display none
dtc -I dtb -O dts virt-kvm-gicv3.dtb > results/gicv3-nisv-debug/20260909T100704Z/raw/orin-virt-kvm-gicv3.dts     # or pass --dtb virt-kvm-gicv3.dtb to this script
# 2. ftrace on the KVM events (root), then boot with monitor + QMP sockets and a QEMU log
sudo mount -t debugfs none /sys/kernel/debug 2>/dev/null || true
T=/sys/kernel/debug/tracing
echo 0 | sudo tee $T/tracing_on; sudo sh -c "echo > $T/trace"
for e in kvm_guest_fault kvm_userspace_exit kvm_exit kvm_mmio kvm_irq_line; do echo 1 | sudo tee $T/events/kvm/$e/enable; done
echo 1 | sudo tee $T/tracing_on
sudo sh -c "cat $T/trace_pipe > results/gicv3-nisv-debug/20260909T100704Z/raw/orin-kvm-trace_pipe.txt" &
cd ~/output && sha256sum -c SHA256SUMS
sudo timeout 60 qemu-system-aarch64 -machine virt,gic-version=3 -cpu host -enable-kvm -smp 2 -m 1G -snapshot \
  -drive file=disk-qemu,if=none,id=drv0,format=raw -device virtio-blk-device,drive=drv0 \
  -kernel ifs.bin -nographic -serial file:boot-kvm.log -display none -no-reboot \
  -monitor unix:/tmp/qemu-mon.sock,server,nowait -qmp unix:/tmp/qemu-qmp.sock,server,nowait \
  -D qemu-kvm-debug.log -d guest_errors,unimp ; echo QEMU_EXIT=$?
# 3. while it is hung (before the timeout fires), read state without changing it
for c in 'info registers -a' 'info mtree' 'info qtree' 'info cpus' 'info irq' 'info status'; do echo "$c" | sudo socat - UNIX-CONNECT:/tmp/qemu-mon.sock; done > results/gicv3-nisv-debug/20260909T100704Z/raw/orin-monitor.txt
#    (or: bash scripts/diagnose-gicv3-nisv.sh --monitor-socket /tmp/qemu-mon.sock --qmp-socket /tmp/qemu-qmp.sock --qemu-pid $(pgrep -f 'qemu-system-aarch64.*ifs.bin'))
echo 0 | sudo tee $T/tracing_on
# 4. variants, one log each (n>=1 recorded per variant, which the repo currently lacks)
#    -smp 1        : replace '-smp 2' with '-smp 1'
#    its=off       : '-machine virt,gic-version=3,its=off'
#    gic host      : '-machine virt,gic-version=host'
#    QEMU 11.1.0   : QEMU_BIN=$HOME/qemu-v11.1.0/bin/qemu-system-aarch64 (built --enable-kvm by scripts/orin/build-qemu-on-orin.sh; check '$QEMU_BIN -accel help' lists kvm)
# 5. feed the capture back:
bash scripts/diagnose-gicv3-nisv.sh --esr <hsr from trace> --far <hxfar> --hpfar <hpfar or --ipa ipa> --guest-pc <pc> \
  --dtb virt-kvm-gicv3.dtb --boot-log boot-kvm.log --monitor-socket /tmp/qemu-mon.sock

### B. Second host (a1.metal / c7g.metal) — same as A; adds ESR/exit data the a1.metal log lacks
#    c7g.metal needs a 64-vCPU quota (currently 32). Record 'qemu-system-aarch64 --version' this time.

### C. Local Windows / Linux build host — static, unprivileged (proprietary outputs stay out of results/)
# extract the linked startup from the IFS into a scratch dir (NCEULA: never into the repo)
dumpifs -x -d <scratch> qnx-safety-vm/output/ifs.bin
# SDP relocatable startup: locate the store and disassemble around it
ntoaarch64-objdump -d --start-address=0x4168 --stop-address=0x4188 <sdp>/target/qnx/aarch64le/boot/sys/startup-qemu-virt
bash scripts/diagnose-gicv3-nisv.sh --elf <sdp>/target/qnx/aarch64le/boot/sys/startup-qemu-virt --guest-pc 0x4178 --out-root <scratch>/results
# linked blob at the IFS load address (0x400810a0 per dumpifs) once a traced PC exists:
bash scripts/diagnose-gicv3-nisv.sh --elf <scratch>/startup.* --elf-base 0x400810a0 --guest-pc <pc from trace>
# whole-library sweep for writeback MMIO stores (extends the gic_v3.c-only audit)
ntoaarch64-objdump -d <sdp>/target/qnx/aarch64le/usr/lib/libstartup.a | grep -E '(str|ldr)[a-z]* +[wx][0-9]+, \[x[0-9]+\], #' | wc -l

### D. QNX / BlackBerry filing — what to attach (no binaries)
#  hsr=0x92000045 decode, KVM_EXIT_ARM_NISV, gic_v3.c disassembly excerpt + -fno-auto-inc-dec diff (docs/findings.md 2026-09-08),
#  a1.metal cross-vendor log, request for boards/qemu-virt source or an SDP dot-release with the flag applied.
```

Raw files written (all redacted): raw/boot-log-classification.txt raw/esr-decode.txt raw/git-state.txt raw/host-cpuinfo.txt raw/host-uname.txt raw/image-hashes.txt raw/qemu-1-version.txt raw/qemu-processes.txt raw/repo-evidence-grep.txt 
