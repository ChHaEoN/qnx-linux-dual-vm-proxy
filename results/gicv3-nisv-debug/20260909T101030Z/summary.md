# GICv3 / KVM_EXIT_ARM_NISV diagnostic — 20260909T101030Z

Read-only collection by `scripts/diagnose-gicv3-nisv.sh` (nothing booted, nothing privileged executed).
Scope: the qnx-safety-vm IFS hanging under `-enable-kvm` after `FOUND GICv3 ITS`. **Not** the QHV/TCG QEMU-6.2 virtual-timer hang — those logs are listed as excluded.
Results dir: `results/gicv3-nisv-debug/20260909T101030Z`. Arguments: `--esr 0x92000045 --boot-log logs/sample-boot/aws-a1-metal-kvm-nisv-repro.log`.

> **Provenance.** Everything below is the script's verbatim output **except** the parts marked *(hand)*: the section "Static verification added after the script run", the rewritten "Current diagnosis", "Ranked hypotheses", "Missing evidence" and "Exact next commands", the matrix rows tagged *(hand)*, and the four extra raw files. Those were added on 2026-09-09 by the Implementation agent after reading the generated file, using only local, unprivileged, read-only steps (objdump/nm/readelf on the SDP object, byte reads of the local ifs.bin, one `-snapshot` TCG control boot). No hardware was touched; the Orin and AWS were off-limits for this session.


## Environment

- platform: windows-gitbash (uname -s: MINGW64_NT-10.0-26200, uname -m: x86_64)
- bash: 5.3.9(1)-release
- generated (UTC): 20260909T101030Z
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

Boot-log classification (logs/sample-boot + --boot-log); hang signature = 'FOUND GICv3 ITS' with no later '** CPU n PE is not awake':

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
| aws-a1-metal-kvm-nisv-repro.log | in-topic | kvm | HANG-AFTER-ITS-DISCOVERY signature (no 'PE is not awake', no 'Startup complete') | no — symptom-only | QEMU_EXIT=124 |

*(hand)* The a1.metal row appears twice above because the file is both inside the default `--log-dir` and was passed again via `--boot-log`, exactly as the task specified; both rows classify the same file identically.

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

## Static verification added after the script run *(hand)*

All of this is **static, local and derived** — it strengthens the chain of evidence but adds no hardware observation. Proprietary
inputs (the SDP `startup-qemu-virt` object, the local `ifs.bin`) were read in place; only addresses, opcodes, a few mnemonics and
hashes are recorded here (raw/static-ifs-probe.txt, raw/sdp-startup-gic-writeback-sweep.txt). Full listings stay in the scratchpad.

**2a. The linked startup inside the sha256-identical IFS contains exactly one `str w3,[x0],#4`, at VA 0x40085978.**
`dumpifs` places `startup.*` at 0x400810a0 (size 0x2b048, entry 0x40081da8) with image base 0x40080000. A 4-byte-aligned scan of that
blob for opcode `b8004403` finds one hit; `ntoaarch64-objdump -D -b binary -m aarch64 --adjust-vma=0x40080000` around it reads:

*(listing withheld — the repo does not commit disassembly of the SDP-shipped binary; NCEULA / QDL v7 §4.6(c). Facts retained from the local window 0x40085958..0x40085984:)* the loop computes x0 = GICD base + 0x420 (gic_v3.h: `ARM_GICD_IPRIORITYn` = 0x400, reg_idx 8), loads w3 = 0xA0A0A0A0, then at **0x40085978** executes opcode **0xb8004403** = `str w3, [x0], #4` (post-indexed, writeback → ISV=0 by the ARM ARM rule), followed by a compare against the loop end and a branch back to 0x40085978.

This is opcode-identical on the four instructions findings.md (2026-09-08) quotes from the rebuilt `gic_v3.o` (1a54/1a58/1a68/1a70);
the full 9-word window matches the SDP-shipped `startup-qemu-virt` at .text 0x4160-0x4184 (derived this session, not stated in findings.md). (Two further `b8004403` words exist elsewhere in the 9.7 MB image, outside the startup blob,
in ordinary userland binaries — irrelevant to a fault taken inside startup.)

**2b. The SDP REL object maps onto the IFS at a constant +0x40081800, so the shipped-object findings transfer to the booted image.**
`nm` on `<sdp-root>/target/qnx/aarch64le/boot/sys/startup-qemu-virt` (ELF64 AArch64, Type REL): `_start` 0x5a8 -> 0x40081da8
(= the dumpifs entry; first word `b cstart` in both), `gic_v3_initialize` 0x4064 -> 0x40085864, the store 0x4178 -> 0x40085978
(= `gic_v3_initialize+0x114`), `vbar_default` 0xc000 -> 0x4008d800. The last equality means the VBAR_EL1 value transcribed from the
live monitor on 2026-07-28 is the linked address of startup's default vector table — the transcription is internally consistent.

**2c. All 16 vector slots at 0x4008d800 are `b .` (0x14000000) — including +0x200 (Current EL, SP_ELx, Synchronous).** Read from the
IFS bytes at file offset 0xd800 + n*0x80 and cross-checked with objdump at +0x000 and +0x200. This upgrades the "+0x200 is `b .`" claim
from transcribed prose to a locally verified static fact about the image that hung. What remains unverified is dynamic: that VBAR_EL1
still held 0x4008d800 at the instant of the fault, and that the vCPU actually sits at 0x4008da00 afterwards.

**2d. The shipped startup has the same four writeback-form MMIO-candidate stores findings.md counted in the rebuilt `gic_v3.o`.**
Sweeping every gic-named function in the SDP object for `[xN], #imm` / `[xN, #imm]!` forms and discarding `[sp]` frame pushes leaves:
`gic_v3_initialize` 0x4178 `str w3,[x0],#4`, 0x41a0 `str wzr,[x0],#4`, 0x4200 `str x0,[x2],#8`; `gic_v3_gicc_init` 0x28c0 `str w1,[x0],#4`.
Count and forms match the source-level audit (GICD priority loop, GICD clear loop, 64-bit store, GICR priority loop). Whether the other
three target MMIO is taken from findings.md's reading of `gic_v3.c`, not re-derived here. The whole object has 418 writeback-form
accesses (339 stores) — overwhelmingly stack pushes; that number is **not** an MMIO count and must not be quoted as one. The callout-patch
and IPI helpers (`end_interrupt_*`, `gicd_patch`, `gicc_patch`, `end_sendipi_*`) also contain post-indexed forms; they were not analysed.

**2e. Static candidate for the never-recorded faulting PC: 0x40085978 (HYPOTHESIS until a traced `pc=` confirms it).** If the Orin
ftrace `kvm_guest_fault` line shows `pc=0x40085978`, static and dynamic evidence meet; if the first iteration faults, its IPA should be
GICD base + 0x420 (0x08000420 on the reference `virt` map). Neither value has ever been observed.

**2f. Tooling corrections.** `dumpifs -x -d <dir> ifs.bin` extracts `proc/boot/*` only — it does **not** write `startup.*` as a file
(checked this session; the printed section C in earlier runs assumed it does). Read the blob by file offset, or feed the script
`--elf qnx-safety-vm/output/ifs.bin --elf-base 0x40080000 --guest-pc <VA>` (raw-binary mode) or
`--elf <sdp-root>/target/qnx/aarch64le/boot/sys/startup-qemu-virt --elf-base 0x40081800 --guest-pc <VA>` (REL mode). Both recipes were
dry-run into the scratchpad with the static candidate and resolve to opcode 0xb8004403 / `gic_v3_initialize+0x114`; those outputs were
deliberately **not** copied into this results dir because the task allows `--elf/--guest-pc` in the results run only once a recorded
numeric PC exists.

**2g. TCG control boot, this box, today.** Windows QEMU 6.2.0 (v6.2.0-11889-g5b72bf03f5-dirty, TCG-only build; supplied explicitly as the extracted Weilnetz build recorded in docs/findings.md 2026-09-09 — it is NOT in the script's 'QEMU binaries' inventory, which lists only the 11.0.50 build) `-machine virt,gic-version=3 -accel tcg -cpu max -smp 2 -m 1G -snapshot` booted the sha256-identical ifs.bin (92868b2f...) to 'Startup complete' + the QNX banner (raw/windows-tcg-control-boot-q620-snapshot.log, raw/windows-tcg-control-run.txt); QEMU_EXIT=124 (killed by the 150 s wrapper as intended — QNX does not exit); disk-qemu unchanged thanks to -snapshot. CONTROL ONLY: TCG performs the MMIO write directly and never synthesises a Data Abort, so it cannot reproduce the KVM hang. Started 20260909T101332Z, ended 20260909T101602Z. Booted hashes are recorded in
raw/windows-tcg-control-run.txt. The `random: Could not initialize entropy` / `vtnet0 does not exist` lines in that log are the separate
virtio-rng slot-order issue (docs/orin-port.md row 141), not this defect. Side finding: the sha256 taken before and after the boot shows
the local `disk-qemu` at fd2ee67d… — identical to the a1.metal transfer-time hash — while `qnx-safety-vm/output/SHA256SUMS` (mtime
2026-07-28 10:34, older than the disk's last mutation at 18:37) still lists f3667fe3…; the sums file, not the disk, is the stale artefact.
So today's local pair (ifs.bin + disk-qemu) is byte-identical to what hung on a1.metal, and `-snapshot` kept it that way.

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
| Repo evidence grep (key terms present) | **PASS** | 142 matching line(s) across 14 terms (142 unique lines; the Evidence table's per-term counts overlap and sum to 158), raw/repo-evidence-grep.txt |
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
| TCG control boot of the same IFS on this host *(hand)* | **PASS** | Windows QEMU 6.2.0 (v6.2.0-11889-g5b72bf03f5-dirty, TCG-only build; supplied explicitly as the extracted Weilnetz build recorded in docs/findings.md 2026-09-09 — it is NOT in the script's 'QEMU binaries' inventory, which lists only the 11.0.50 build) `-machine virt,gic-version=3 -accel tcg -cpu max -smp 2 -m 1G -snapshot` booted the sha256-identical ifs.bin (92868b2f...) to 'Startup complete' + the QNX banner (raw/windows-tcg-control-boot-q620-snapshot.log, raw/windows-tcg-control-run.txt); QEMU_EXIT=124 (killed by the 150 s wrapper as intended — QNX does not exit); disk-qemu unchanged thanks to -snapshot. CONTROL ONLY: TCG performs the MMIO write directly and never synthesises a Data Abort, so it cannot reproduce the KVM hang |
| KVM re-check with from-source QEMU 11.1.0 (--enable-kvm) on the Orin | **NOT RUN** | never performed; every NISV data point is QEMU 6.2.0. The from-source binary was configured with --enable-kvm (scripts/orin/build-qemu-on-orin.sh); kvm accelerator presence in that binary is not yet confirmed (no `-accel help` output recorded) |
| KVM variants -smp 1 / gic-version=host / its=off logged with n>=1 each | **NOT RUN** | asserted in docs/orin-port.md without logs or counts; commands printed below |
| a1.metal (or c7g.metal) re-run with ftrace to classify that hang as NISV by data | **NOT RUN** | a1.metal log is symptom-only; c7g.metal blocked by the 32-vCPU quota |
| Boot of a startup rebuilt with -fno-auto-inc-dec under KVM | **BLOCKED** | startup-qemu-virt cannot be relinked (BSP ships boards/armv8_fm, not boards/qemu-virt) |
| *(hand)* Static: exactly one `b8004403` (`str w3,[x0],#4`) in the IFS startup blob, at VA 0x40085978 | **PASS** | aligned scan of file range 0x10a0..0x2c0e8 of the sha256-identical ifs.bin; objdump window in raw/static-ifs-probe.txt |
| *(hand)* Static: SDP `startup-qemu-virt` .text -> IFS mapping is a constant +0x40081800 (`_start`, `gic_v3_initialize`, store, `vbar_default` all consistent) | **PASS** | nm + dumpifs entry + byte comparison; raw/static-ifs-probe.txt |
| *(hand)* Static: documented VBAR_EL1 0x4008d800 == linked `vbar_default`; all 16 vector slots are `b .` (0x14000000), incl. +0x200 | **PASS** | read from IFS bytes; dynamic 'parked there' still unobserved |
| *(hand)* Static: shipped `gic_v3_initialize`/`gic_v3_gicc_init` non-stack writeback stores == 4, same forms as the rebuilt gic_v3.o | **PASS** | raw/sdp-startup-gic-writeback-sweep.txt; MMIO-ness of the other three taken from findings.md |
| *(hand)* `dumpifs -x` extracts `startup.*` as a file | **FAIL** | only proc/boot/* is written; the blob must be read by file offset (recipe corrected under 'Exact next commands') |
| *(hand)* `--elf/--elf-base/--guest-pc` recipe dry-run with the static candidate PC (scratchpad only) | **PASS** | REL mode (base 0x40081800) and raw-binary mode (base 0x40080000) both resolve 0x40085978 -> 0xb8004403, gic_v3_initialize+0x114; outputs not copied here |
| *(hand)* Traced faulting PC == static candidate 0x40085978 | **BLOCKED** | needs the Orin ftrace `pc=` (Orin in use by another experiment; AWS off-limits this session) |
| *(hand)* Traced fault IPA inside GICD (expected 0x08000420 on the reference map) | **BLOCKED** | needs HPFAR/ipa from the same trace plus a dumpdtb/mtree of the KVM invocation |
| *(hand)* Post-hang guest PC == 0x4008da00 (VBAR+0x200) and ESR_EL1 shows an injected external abort | **BLOCKED** | needs a monitor/gdbstub read on the Orin while hung |


## Current diagnosis *(hand)*

Observed facts first, each with its evidence class; hypotheses after, each with what would settle it. "NISV" is used only where
the data shows ISV=0 or a literal `KVM_EXIT_ARM_NISV`.

**Observed (data-backed, with where):**

1. **Orin Nano, KVM: hang after `FOUND GICv3 ITS`.** `qemu-system-aarch64 -machine virt,gic-version=3 -cpu host -enable-kvm -smp 2 -m 1G ...`
   (scripts/orin/launch-qnx-on-orin.sh, deliberately unfixed), QEMU 6.2.0 (Ubuntu 22.04 apt), L4T R36.4.7 / 5.15.148-tegra, KVM in VHE mode.
   Serial prints the ITS discovery banner and nothing else; the process stays alive. Evidence class: prose in docs/orin-port.md
   (risk-register row, 2026-07-28) — **no serial capture of any Orin KVM attempt is committed.**
2. **Orin Nano, host ftrace: `kvm_guest_fault hsr=0x92000045`, `kvm_userspace_exit reason KVM_EXIT_ARM_NISV (28)`.** Decoded by this
   script: EC=0x24 (Data Abort from a lower EL), IL=1, **ISV=0**, WnR=1 (write), FnV=0, DFSC=0x05 (stage-2 translation fault, level 1 —
   what an emulated-MMIO access looks like to KVM). This is the **only data-backed NISV in the repo** (hsr bit 24 clear + the literal exit
   reason). Evidence class: transcribed prose. docs/orin-port.md (row 140) asserts the traced fault sat at the exact PC identified by
   static disassembly, but no numeric `pc=`/`ipa=`/`hxfar=` value was ever written down; the raw trace_pipe output, the vCPU id
   and the exit count were not preserved.
3. **Faulting instruction = the post-indexed store at GICD+0x420.** Identified on 2026-07-28 by static disassembly of the extracted
   startup (listing not committed, NCEULA) and, this session, pinned in the sha256-identical image: exactly one `str w3,[x0],#4`
   (0xb8004403) in the startup blob, at VA 0x40085978, inside `add x0,x1,#0x420 / movk w3,#0xa0a0,lsl #16 / str w3,[x0],#4 / cmp / b.ne`
   — GICD_IPRIORITYR<8>, the first iteration of the SPI priority loop (gic_v3.h: ARM_GICD_IPRIORITYn = 0x400). Evidence class: static,
   local. docs/orin-port.md asserts the traced PC coincided with this statically identified instruction, but **no numeric PC was ever
   recorded**, so 0x40085978 stays a static candidate (H-D), not a recorded observation.
4. **VBAR_EL1 = 0x4008d800 (live monitor read, transcribed) and the +0x200 slot is `b .`.** This session: 0x4008d800 is the linked address of
   the SDP symbol `vbar_default`, and all 16 slots of that table in the IFS bytes are `b .`. Evidence class: one transcribed live value +
   static verification of the slot content. The post-hang PC was never read.
5. **a1.metal (Graviton1 / Annapurna, Cortex-A72, kernel 6.8.0-1061-aws, non-VHE "Hyp mode"): identical hang shape, n=1.** Same command
   shape (no net), same ifs.bin sha256 (92868b2f… — the local copy still matches) and same disk-qemu sha256 (fd2ee67d… — the local raw
   disk hashes to exactly that value today; it is the local `SHA256SUMS` file, written 2026-07-28 10:34 before the disk's last 18:37
   mutation, that is stale with f3667fe3…, not the disk), serial =
   `FOUND GICv3 ITS` for 60 s, QEMU_EXIT=124 (external timeout), stderr = only the SIGTERM line, bare vGIC smoke test clean on the same
   instance. Evidence class: committed log (logs/sample-boot/aws-a1-metal-kvm-nisv-repro.log). **No ESR, no ISV bit, no exit reason,
   no QEMU version recorded there** — a boot FAIL with matching symptom on a second vendor and core generation; the NISV classification
   for that host is inferred.
6. **TCG controls boot the same image.** Orin (QEMU 6.2.0 `-accel tcg -cpu max`, committed log), Windows (committed logs), and this
   session's `-snapshot` boot with the Windows QEMU 6.2.0 build (raw/windows-tcg-control-boot-q620-snapshot.log: `Startup complete`,
   both `PE is not awake` lines, QNX banner). Isolates the hang to KVM acceleration; TCG never synthesises a hardware Data-Abort ISS.
7. **BSP-source reproduction (compile level, 2026-09-08, docs/findings.md).** SDP 8.0 BSP_hyp-guest-arm_be-800 `gic_v3.c`, built unmodified
   with the SDP's own `qcc -Vgcc_ntoaarch64` (gcc 12.2.0), emits the same `add x0,x1,#0x420 / movk / str w3,[x0],#4 / b.ne` loop; the object
   holds four writeback MMIO stores (GICD priority, GICD clear, GICR priority in `gic_v3_gicc_init`, one 64-bit store); the BSP flags already
   carry `-fno-store-merging`. This session: the **shipped** `startup-qemu-virt` has the same four (2d above).
8. **`-fno-auto-inc-dec` removes all four at compile level.** Adding it to the BSP's own flags takes the writeback-store count 4 -> 0; the loop
   becomes `add x0,x0,#4 / stur w3,[x0,#-4] / b.ne` (0xb81fc003 — no writeback, expected ISV=1 by the same architectural rule). **Nothing
   rebuilt has been booted**; `startup-qemu-virt` cannot be relinked because the BSP ships `boards/armv8_fm/` but not `boards/qemu-virt/`.
9. **Pre-conditions hold on both hosts.** Orin: `/dev/kvm` usable, dmesg `VHE mode initialized successfully`, bare vGIC smoke test clean,
   `gic-version=2` refused by KVM. a1.metal: vGIC smoke test clean. The AGX-Orin `VmCreateGIC Error(19)` failure does not reproduce on the Nano.
10. **Asserted without logs or counts** (docs/orin-port.md): the hang is identical at `-smp 1`/`-smp 2`, `gic-version=3`/`host`, with/without `its=off`.

**Hypotheses (not yet shown by data — what would settle each):**

- **H-A. The fault IPA is 0x08000420 (GICD_IPRIORITYR<8> on the `virt` map).** Derived from the instruction + reference board constants;
  no HPFAR/IPA was ever captured, no dumpdtb or `info mtree` of the KVM invocation exists, and whether QNX startup reads the FDT or hardcodes
  GIC bases is unknown. Settled by the trace's `ipa=`/`hxfar=` plus a dumpdtb from the same QEMU/KVM invocation.
- **H-B. QEMU's `kvm_arm_handle_dabt_nisv()` injected an external Data Abort and the vCPU is parked at 0x4008da00 (`b .`).** Supported by:
  the slot content (static, verified), VBAR_EL1 (transcribed), the absence of any QEMU `error_report` on a1.metal's stderr — by a reading of
  upstream `target/arm/kvm.c`, injection via `KVM_CAP_ARM_INJECT_EXT_DABT` is silent whereas the no-capability path prints an error and fails
  the exit (reading of upstream source, not verified against the installed 6.2.0 binaries). Settled by a post-hang `info registers` /
  gdbstub read: PC == 0x4008da00, ESR_EL1 with an external-abort syndrome, ELR_EL1 == the faulting PC.
- **H-C. The a1.metal hang is the same NISV mechanism.** Symptom identity only, n=1. Settled by one ftrace-instrumented re-run there
  (or on c7g.metal, quota permitting).
- **H-D. The traced PC will be 0x40085978.** Static candidate (2a/2b). Settled by the trace `pc=` field.
- **H-E. Removing the writeback stores makes the guest boot under KVM.** Compile-level proof of the first link only; needs a bootable
  startup (QNX's `boards/qemu-virt` source or a dot-release) and a KVM boot.
- **H-F. The `-smp 1` / `gic-version=host` / `its=off` variants hang identically.** Asserted; one logged run each would settle it.
- **H-G. A newer QEMU on KVM does not help.** Analysis (the KVM backend injects by design; a decode fallback exists only as an HVF RFC);
  the from-source QEMU 11.1.0 on the Orin (configured with `--enable-kvm`; kvm accelerator presence in that binary not yet confirmed) has never been tried against this IFS.

**Bottom line.** The mechanism (writeback-form GICD store -> ISV=0 -> `KVM_EXIT_ARM_NISV` -> QEMU cannot emulate -> guest parks on a `b .`
vector) is established on the Orin by one data-backed observation plus a now three-way-consistent static chain (rebuilt object, shipped object,
booted image). What is still missing is entirely on the dynamic side: no committed raw capture, no PC/IPA/FAR, no post-hang state, no second
host with syndrome data, and no boot of a fixed startup. This run added static and control evidence only (see the matrix).

## Ranked hypotheses *(hand)*

The task author's own wording of the eight candidates was not found in the repo, the agent briefs or the scratchpad, so the eight the script
enumerates are kept verbatim and re-ranked against the evidence above (including this session's static and control results). "CONFIRMED"
means observed on the Orin and reproduced statically — not "closed": every dynamic value that would make it airtight is still missing.

| rank | # | hypothesis | status | for | against / what would refute |
|---|---|---|---|---|---|
| 1 | 1 | The GICD write is a writeback-form (post-indexed) store, so the CPU reports ESR.ISV=0 and KVM cannot decode it -> `KVM_EXIT_ARM_NISV` | **CONFIRMED (Orin, n=1 data point + static)** | hsr=0x92000045 decodes to ISV=0/WnR=1; literal exit reason 28; the sha256-identical image holds exactly one `str w3,[x0],#4` in startup, and the rebuilt and shipped objects agree; the KVM API documents this exit for non-ISV MMIO | a traced `pc=` != 0x40085978, or any hsr with ISV=1, would break the link between the trace and this instruction |
| 2 | 2 | The target is GIC distributor MMIO (GICD_IPRIORITYRn, GICD+0x420) emulated in-kernel by vgic-v3, so there is no decoder fallback | **CONFIRMED at instruction level; IPA unobserved** | `add x0,x1,#0x420` feeds the store; gic_v3.h IPRIORITYn=0x400; DFSC=0x05 is the stage-2 signature of emulated MMIO | an HPFAR/IPA outside 0x08000000-0x0800ffff (reference map) or a dumpdtb showing a different GICD base |
| 3 | 3 | QEMU 6.2's `kvm_arm_handle_dabt_nisv()` injects a synthetic external Data Abort; startup's EL1 vector at VBAR_EL1+0x200 is `b .` -> silent park | **SUPPORTED, injection still inferred** | VBAR_EL1 read live and equals linked `vbar_default`; all 16 slots `b .` (static, this session); silent stderr on a1.metal matches the capability-present path of upstream QEMU | post-hang PC not at 0x4008da00, or ESR_EL1 not an external abort; a `-d guest_errors` log or KVM events trace would show the injection directly |
| 4 | 7 | Tegra234 / Cortex-A78AE / VHE-specific silicon quirk | **WEAKENED (n=1 on the second host)** | — | identical symptom on a1.metal (Annapurna A72, non-VHE host); still symptom-only there, one run; a c7g.metal or ftrace-instrumented a1.metal run would finish this |
| 5 | 8 | QEMU-version-specific bug (6.2.0) fixed by a newer QEMU on KVM | **UNTESTED, assessed unlikely — but the cheapest remaining test** | a1.metal's QEMU version was never recorded, so 6.2.0 is not even certain there | upstream KVM backend injects by design (no decode fallback for KVM, only an HVF RFC); the from-source 11.1.0 `--enable-kvm` on the Orin has never been pointed at this IFS |
| 6 | 4 | Guest memory map / DTB mismatch (GICD base wrong, unmapped IPA) rather than an MMIO decode problem | **WEAKENED** | DFSC=0x05 alone is consistent with a plain unmapped IPA | the same image + board map boots under TCG on the same Orin; ITS discovery and CPU-interface bring-up succeed first; an IPA capture + dumpdtb would settle it outright |
| 7 | 5 | ITS involvement (`its=on` default, GITS programming) is the trigger | **WEAKENED (its=off run unlogged)** | `FOUND GICv3 ITS` is the last line, which invites the association | the faulting register is GICD, not GITS; the same banner is line 1 of every TCG boot; docs assert `its=off` hangs identically (no log/count) |
| 8 | 6 | vGIC device-creation failure (AGX Orin `VmCreateGIC Error(19)` family) | **REFUTED on both hosts** | community reports on AGX Orin only | bare vGIC smoke tests clean on Orin Nano and a1.metal; the guest runs far enough to discover the ITS and bring up ICC_* — creation is not where it dies |

Ordering rationale: 1-3 are the established mechanism in causal order; 4 and 5 are the two open alternatives that a single cheap hardware
run would each close (a1.metal/c7g.metal with ftrace; QEMU 11.1.0 on the Orin); 6 and 7 are alternatives the existing TCG control and the
instruction target already argue against; 8 is refuted by data on both hosts.

## Missing evidence *(hand)*

Genuinely absent from the repo and from this results dir (not merely "not passed to the script"):

- **Numeric faulting PC / ELR_EL2** — the `kvm_guest_fault` tracepoint prints `pc=` next to `hsr=`, but only hsr and the exit reason were
  transcribed as values. docs/orin-port.md asserts the traced PC coincided with the statically identified instruction, yet no numeric
  `pc=`/`ipa=`/`hxfar=` was ever recorded, so that match cannot be re-checked. The static candidate is 0x40085978
  (`gic_v3_initialize+0x114`); unconfirmed (H-D).
- **HPFAR_EL2 / fault IPA and FAR_EL2 (hxfar)** — same tracepoint, same omission. Expected 0x08000420 on the reference map; never observed.
- **The raw trace_pipe capture itself** — timestamps, vCPU id, number of NISV exits (one per vCPU? one only?), the surrounding
  `kvm_exit`/`kvm_mmio` lines, and even the exact 2026-07-28 enable/boot command lines.
- **Any serial log of an Orin KVM attempt** — commit c9202ce added only the TCG control; the a1.metal file is the sole KVM-hang serial capture
  and holds one line.
- **Post-hang guest state** — PC, ELR_EL1, ESR_EL1, FAR_EL1, SPSR_EL1, VBAR_EL1 read while parked (monitor `info registers` or gdbstub);
  VBAR_EL1 is a single transcribed value and the "parked at +0x200" claim is inferred.
- **A DTB of the failing invocation** (`-machine virt,...,dumpdtb=` with `-cpu host -enable-kvm`) and a QEMU `info mtree` — the GICD/GICR/ITS
  bases as the hung guest saw them; no `.dtb`/`.dts` exists anywhere in the repo or the SDP, and no local build can produce the KVM shape.
  Whether QNX startup consumes the FDT at all is not established.
- **Evidence of the external-abort injection** (a `-d guest_errors,unimp` log, `kvm_inject_*`/`kvm_set_guest_debug`-class trace lines, or the
  `KVM_CAP_ARM_INJECT_EXT_DABT` / `KVM_CAP_ARM_NISV_TO_USER` capability state on either host) — currently inferred from strings in the binary.
- **Syndrome data from a second host** — a1.metal has no ESR/ISV/exit-reason and no recorded QEMU version; c7g.metal was never launched
  (32-vCPU quota vs 64 needed).
- **Logged runs (n>=1 each) of the `-smp 1`, `gic-version=host` and `its=off` variants** — asserted in one sentence.
- **The QEMU 11.1.0 `--enable-kvm` re-check on the Orin** — binary built 2026-09-09, never run against this IFS; every NISV data point is 6.2.0.
- **A QNX-side fix and its boot** — a `startup-qemu-virt` built with `-fno-auto-inc-dec` (blocked on `boards/qemu-virt` source or an SDP
  dot-release), booted under KVM. Also a `libstartup.a`-wide MMIO-writeback audit: this session covered only the gic-named functions of the
  shipped startup; findings.md covered only `gic_v3.c`.
- **The live guest data value** (w3 = 0xA0A0A0A0 is known only statically from the `movk`).
- Run-level gaps of this results dir: `--hpfar/--ipa`, `--dtb`, `--monitor-socket/--qmp-socket` were not supplied (nothing exists to supply);
  `--elf/--guest-pc` was withheld by rule (no recorded PC).

## Exact next commands *(hand)*

Printed, **not executed**. Every line under A and B is privileged or needs KVM hardware and is **BLOCKED this session** (the Orin is in use
by another experiment; AWS is off-limits). Section C ran locally and is verified. Paths: `~/output` on the Orin holds
`ifs.bin`, `disk-qemu`, `SHA256SUMS` (scp'd from `qnx-safety-vm/output/`); keep `-snapshot` so the raw disk stops drifting from the recorded
hash. Replace `<...>` placeholders. Nothing here alters the main boot configuration (scripts/orin/launch-qnx-on-orin-tcg.sh).

```
### A. Orin Nano (L4T R36.4.7, QEMU 6.2.0) — fresh KVM capture with the raw evidence the repo lacks — BLOCKED / PRINT ONLY
# A0. environment stamp (unprivileged except dmesg)
uname -a; grep -m1 'CPU part' /proc/cpuinfo; qemu-system-aarch64 --version | head -1; dpkg -s qemu-system-arm 2>/dev/null | grep '^Version'
ls -l /dev/kvm; id
sudo dmesg | grep -iE 'kvm|vgic|gic|vhe|hyp mode|ipa size' > results/gicv3-nisv-debug/20260909T101030Z/raw/orin-dmesg-kvm.txt
# A1. DTB of the exact failing shape (-cpu host -enable-kvm) — this is the only way to get the KVM-shape DTB; no local build can
sudo qemu-system-aarch64 -machine virt,gic-version=3,dumpdtb=virt-kvm-gicv3.dtb -cpu host -enable-kvm -smp 2 -m 1G -display none
command -v dtc && dtc -I dtb -O dts virt-kvm-gicv3.dtb > results/gicv3-nisv-debug/20260909T101030Z/raw/orin-virt-kvm-gicv3.dts   # dtc may be absent on L4T: then just keep the .dtb and pass --dtb below
# A2. ftrace on the KVM events (root), then the boot with monitor + QMP sockets and a QEMU debug log
sudo mount -t debugfs none /sys/kernel/debug 2>/dev/null || true
T=/sys/kernel/debug/tracing
echo 0 | sudo tee $T/tracing_on; sudo sh -c "echo > $T/trace"
for e in kvm_guest_fault kvm_userspace_exit kvm_exit kvm_entry kvm_mmio kvm_irq_line; do echo 1 | sudo tee $T/events/kvm/$e/enable; done
echo 1 | sudo tee $T/tracing_on
sudo sh -c "cat $T/trace_pipe > results/gicv3-nisv-debug/20260909T101030Z/raw/orin-kvm-trace_pipe.txt" &
cd ~/output && sha256sum -c SHA256SUMS
sudo timeout 60 qemu-system-aarch64 -machine virt,gic-version=3 -cpu host -enable-kvm -smp 2 -m 1G -snapshot \
  -drive file=disk-qemu,if=none,id=drv0,format=raw -device virtio-blk-device,drive=drv0 \
  -kernel ifs.bin -nographic -serial file:boot-kvm.log -display none -no-reboot \
  -monitor unix:/tmp/qemu-mon.sock,server,nowait -qmp unix:/tmp/qemu-qmp.sock,server,nowait \
  -D qemu-kvm-debug.log -d guest_errors,unimp ; echo QEMU_EXIT=$?
# A3. while it is hung (before the 60 s fires) — read state without changing it; expect PC=0x4008da00 if H-B holds
for c in 'info registers -a' 'info mtree' 'info qtree' 'info cpus' 'info irq' 'info status'; do echo "$c" | sudo socat - UNIX-CONNECT:/tmp/qemu-mon.sock; done > results/gicv3-nisv-debug/20260909T101030Z/raw/orin-monitor.txt
#    or let the script do the read-only capture:
bash scripts/diagnose-gicv3-nisv.sh --monitor-socket /tmp/qemu-mon.sock --qmp-socket /tmp/qemu-qmp.sock --qemu-pid "$(pgrep -f 'qemu-system-aarch64.*ifs.bin')"
#    if 'info registers' does not print EL1 system registers under KVM, repeat the boot with '-s' and read them through the gdbstub
#    (QNX_HOST/QNX_TARGET exported): ntoaarch64-gdb -batch -ex 'target remote :1234' -ex 'info registers pc' -ex 'p/x $vbar_el1' -ex 'p/x $elr_el1' -ex 'p/x $esr_el1' -ex 'p/x $far_el1'   # register names unverified for QEMU 6.2's gdbstub
echo 0 | sudo tee $T/tracing_on; sudo sh -c "cat $T/trace > results/gicv3-nisv-debug/20260909T101030Z/raw/orin-kvm-trace-buffer.txt"
# A4. variants — ONE LOGGED RUN EACH (the repo currently has zero): copy boot-kvm.log + the trace file per variant
#    -smp 1        : replace '-smp 2' with '-smp 1'
#    its=off       : '-machine virt,gic-version=3,its=off'
#    gic host      : '-machine virt,gic-version=host'
# A5. QEMU 11.1.0 re-check (built --enable-kvm by scripts/orin/build-qemu-on-orin.sh; own prefix, distro 6.2.0 untouched)
QEMU_BIN=$HOME/qemu-v11.1.0/bin/qemu-system-aarch64; $QEMU_BIN --version | head -1; $QEMU_BIN -accel help      # must list kvm
#    then repeat A2/A3 with $QEMU_BIN in place of qemu-system-aarch64 (same arguments)
# A6. feed the capture back into the decoder (the trace line carries hsr= pc= ipa= hxfar= — copy all four)
bash scripts/diagnose-gicv3-nisv.sh --esr <hsr> --guest-pc <pc> --ipa <ipa> --far <hxfar> \
  --dtb virt-kvm-gicv3.dtb --boot-log boot-kvm.log \
  --elf qnx-safety-vm/output/ifs.bin --elf-base 0x40080000            # raw-binary mode; expect 0xb8004403 at pc if pc == 0x40085978

### B. Second host (a1.metal; c7g.metal needs the 64-vCPU quota) — BLOCKED / PRINT ONLY
#    identical to A0-A3 and A6; additionally record on that host, which the 2026-07-29 log did not:
qemu-system-aarch64 --version | head -1; dpkg -s qemu-system-arm 2>/dev/null | grep '^Version'; uname -r
#    keep the AWS instance id out of every file copied into results/ (the script redacts i-… ids; check anyway)

### C. Local Windows/Linux build host — static, unprivileged; RAN THIS SESSION (proprietary outputs stay in the scratchpad)
# C1. locate the store in the SDP relocatable object and disassemble the loop (offsets are .text offsets; +0x40081800 = IFS VA)
ntoaarch64-objdump -d --start-address=0x4160 --stop-address=0x4188 <sdp-root>/target/qnx/aarch64le/boot/sys/startup-qemu-virt
ntoaarch64-nm <sdp-root>/target/qnx/aarch64le/boot/sys/startup-qemu-virt | grep -E ' (_start|gic_v3_initialize|vbar_default)$'
# C2. the same instruction inside the booted image (raw-binary mode; dumpifs -x does NOT extract startup.* — do not rely on it)
ntoaarch64-objdump -D -b binary -m aarch64 --adjust-vma=0x40080000 --start-address=0x40085958 --stop-address=0x40085988 qnx-safety-vm/output/ifs.bin
ntoaarch64-objdump -D -b binary -m aarch64 --adjust-vma=0x40080000 --start-address=0x4008da00 --stop-address=0x4008da08 qnx-safety-vm/output/ifs.bin   # VBAR+0x200: 14000000 b .
# C3. script recipes (verified in the scratchpad; run into results/ only once a traced PC exists)
bash scripts/diagnose-gicv3-nisv.sh --elf qnx-safety-vm/output/ifs.bin --elf-base 0x40080000 --guest-pc <pc from trace>
bash scripts/diagnose-gicv3-nisv.sh --elf <sdp-root>/target/qnx/aarch64le/boot/sys/startup-qemu-virt --elf-base 0x40081800 --guest-pc <pc from trace>
# C4. TCG control of the identical IFS (done today with the Windows QEMU 6.2.0 build; -snapshot keeps disk-qemu unmodified)
timeout 150 <qemu-6.2.0>/qemu-system-aarch64 -machine virt,gic-version=3 -accel tcg -cpu max -smp 2 -m 1G -snapshot \
  -drive file=disk-qemu,if=none,id=drv0,format=raw -device virtio-blk-device,drive=drv0 -kernel ifs.bin -nographic \
  -serial file:boot-tcg-q620-snapshot.log -display none -no-reboot -monitor none
# C5. wider static audit still open: sweep libstartup.a (not just the shipped startup's gic-named functions)
ntoaarch64-objdump -d <sdp-root>/target/qnx/aarch64le/usr/lib/libstartup.a | grep -E '^\s+[0-9a-f]+:\s+[0-9a-f]+\s+st[a-z]*\s.*(\[x[0-9]+\], #|\]!)' | grep -v '\[sp' | wc -l

### D. QNX / BlackBerry filing — what to attach (no binaries, no full listings)
#  hsr=0x92000045 decode + the literal KVM_EXIT_ARM_NISV; the 9-instruction loop excerpt (2a) with the three-way match
#  (rebuilt gic_v3.o / shipped startup-qemu-virt / booted IFS at 0x40085978); the -fno-auto-inc-dec 4 -> 0 diff (docs/findings.md 2026-09-08);
#  the a1.metal cross-vendor log (instance id redacted); request: boards/qemu-virt source, or an SDP dot-release with the flag applied,
#  or a statement on writeback-form MMIO in startup. Attach the Orin raw capture from A once it exists — it is the piece the filing still lacks.
```

Raw files written (all redacted): raw/boot-log-classification.txt raw/esr-decode.txt raw/git-state.txt raw/host-cpuinfo.txt raw/host-uname.txt raw/image-hashes.txt raw/qemu-1-version.txt raw/qemu-processes.txt raw/repo-evidence-grep.txt  raw/static-ifs-probe.txt raw/sdp-startup-gic-writeback-sweep.txt raw/windows-tcg-control-boot-q620-snapshot.log raw/windows-tcg-control-run.txt *(hand-added; last four)*
