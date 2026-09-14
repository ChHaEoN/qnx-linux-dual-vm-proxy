# S1-F design: a Linux guest without a GPU under native qvm on the Jetson Orin Nano

Phase 3b. Architect pass, revision 2, 2026-09-13 (revision 1 reviewed; outcomes in §13). This is a read-and-reason design: nothing in it has been built or run, and it creates no code, configuration or image. It follows the structure of [m5-design.md](m5-design.md) and [m3-design.md](m3-design.md). Its scope is the owner decision of 2026-09-11 (option B): S1-F is functional verification only, and every figure it would print is deferred to the post-freeze campaign (plan:400, :473).

**2026-09-13 (owner):** every owner decision in §11, D1-D19, was taken as recommended. Nothing has been built or run yet; the next step is D3's copy of the board's `Image` and `initrd`, then T0.

**2026-09-14:** T0 is implemented, built and gated on the PC, and every gate passed. Nothing has run under QEMU or on the board. The implementation decisions, deviations and gate verdicts are in §14; usage is in `orin-native/s1/README.md`.

**Path prefixes used below**
- `lib/` = `C:/Users/<user>/AppData/Local/Temp/orin-native-port-bsp/src/hardware/startup/lib/` (Apache-2.0)
- `board/` = `orin-native/startup/t234-orin-nano/`; `startup/` = `orin-native/startup/`; `tools/` = `orin-native/tools/`; `qhvc/` = `orin-native/qhv/`; `s1/` = `orin-native/s1/` ~~(proposed; it does not exist)~~ (**2026-09-14:** it exists, §14)
- `r/` = `results/orin-native-port/20260909T1100Z/`; `plan` = `docs/orin-native-port-plan.md`
- `RT` = the research track's `results/gpu-passthrough/20260910T1935Z/feasibility.md` on the unpushed branch `research/gpu-passthrough`, cited by line
- `QH` = `https://www.qnx.com/developers/docs/8.0/com.qnx.doc.hypervisor.user/topic/` (QNX Hypervisor 8.0 user guide). No hypervisor documentation is installed with the SDP on this PC (a search for it found only the mkqnximage qvm templates)
- `LX` = Linux v5.15 upstream (`https://docs.kernel.org/` and `https://raw.githubusercontent.com/torvalds/linux/v5.15/`); NVIDIA's 5.15.148-tegra fork was not read
- `BF` = the orchestrator's read-only board facts of 2026-09-13 (L4T release, `/boot/Image` header, kernel config, initrd contents, checklist 11c). The 11c record itself is in a git-ignored `s1/` run directory (plan:859)

**Evidence classes:** VERIFIED (read in our source, a build file, a record, or computed; cited), VENDOR_CLAIM (QNX, Linux, NVIDIA or Ubuntu documentation; URL given), HYPOTHESIS, UNKNOWN. The QH citations were read through a summarising fetch. This design paraphrases them; re-check the wording on qnx.com before quoting any of them.

**Licence status**
- Every board log and every qvm-generated device tree an S1 session produces is evaluation output under NC QDL v7 4.6(i). It stays private until the supervising professor has been consulted. This design quotes no figure from any run, M3 or later.
- No QNX-shipped binary was read, and none is proposed for reading. Hashing images and `.so` files follows existing practice (m3-design.md:894).
- The Linux `Image` (GPLv2), busybox (GPLv2) and glibc (LGPL-2.1) files S1 uses are private copies of the board's own files. They are never committed: they live under `out/` (`.gitignore:53`), inside host images under `/qhv/` (`:16`), or in `*.kimg` (`:95`). Private use carries no source obligation; a push would be distribution (VENDOR_CLAIM, https://www.gnu.org/licenses/gpl-faq.html).

---

## 0. Summary

**Objective.** Show that the stock L4T R36.4.7 kernel `Image`, with a small busybox initrd, boots to a working shell on `hvc0` as a qvm guest: first under the TCG QHV host on the PC, then natively on the board with the same configuration. Show that the host can claim a second RAM window, and that a ten-minute run ends with qvm alive and the host's memory canaries intact. Nothing is measured.

**Owner scope (2026-09-11, option B; plan:459-474)**
- **Required:** plan pass items 1-5 (§5.2).
- **Prerequisites:** M5-F (met 2026-09-13); the host boots with the second window as a second `add_ram` (plan:463); a TCG `dryrun` with the device tree dumped and no GPU overlay (plan:464). The GPU checks wait for the first GPU stage (plan:465).
- **Deferred to the campaign:** the CPU-only model baseline, any boot time, IPC statistics and any Linux-guest latency (plan:473).
- **Informs:** freeze gate items 2, 3, 4, 6, 7 and 10 (plan:480-485, :488). S1-F decides none of them (§5.5).

**Chosen path**
1. **Guest set for S1-F: Linux only, with a conditional two-guest rung** (D1). The Linux configuration is written once, so the rung that adds the unchanged M3 QNX guest (`B5`) reuses it byte for byte.
2. **Entry: kexec from L4T**, with M3's quiesce and governor pin (D6).
3. **RAM:** window 1 unchanged (`-m992M`). A new board option, off by default, adds window 2 (`0x1_0000_0000`, `0x8A00_0000` B = 2,208 MiB) as a second `add_ram`. It keeps the rest of 11c's candidate, `0x1_8A00_0000-0x2_49FF_FFFF` (3,072 MiB), out of every `add_ram` as the provisional GPU range (D18). With `canary` it takes three fixed 16 MiB ranges out of `sysram` with `alloc_ram`, registers each as a named asinfo entry, and fills each with a pattern, all inside startup (D7). The Linux guest's 512 MiB fits window 1 alone, so a launch does not depend on where qvm's allocation lands (§3.3).
4. **Payload in the host IFS** at M3's `[image=0x80082000]`: the board's uncompressed `Image`, a gzip newc initrd, and the configuration, at `/data/s1/...` on both hosts. The geometry gate passes unchanged for Linux only (§4.4).
5. **Console:** `console=hvc0` on a virtio-console whose host end is a pty. A new host tool, `s1con`, stamps the guest's output and injects two shell probes whose answers differ from their echo (§3.4). The kernel log also goes to a pl011 vdev through `earlycon`.
6. **Initrd:** busybox and its three libraries, copied from the stock L4T initrd, plus our own `/init` script (D2).
7. **CPUs:** host `-P4` as in M3; the guest gets three vCPUs pinned `cpu cluster _cpu-1`, `_cpu-2`, `_cpu-3`. The S1 TCG rehearsal launcher runs `-smp 4` so the same lines are valid there (D4, D5).
8. **Canaries:** startup fills the three ranges before procnto starts. A new read-only tool, `memcanary`, verifies them by name only (it takes no address) and refuses any range that is not a registered canary outside `sysram`. It also allocates and verifies more RAM than window 1 holds on the host-only rung, which forces pages from window 2, and holds a filled host allocation through the ten-minute run. M3's md5 checks of every payload file stay (§3.8).

**Why this path**
1. **It follows the owner's target and keeps pass item 3 open.** The owner's target has no QNX guest (plan:480; RT:342). The QNX guest pair is 163 MB of IFS that the Linux-only images do not carry, and it pushes the IFS past the generators' geometry gate (§4.4). Keeping one Linux configuration lets the two-guest rung run later with no new Linux bytes.
2. **Every board rung is one kexec round of a proven loop**, with M3's safeguards (the guard, `-A`, the uptime refusal, the landing check). M5's UEFI evidence covers `-P1` with no qvm (m5-design.md:768), and COM3 is receive-only again.
3. **The riskiest unknowns close on the PC.** qvm's handling of an arm64 `Image` and its generated FDT are undocumented (§1 C4, C5). T1's `dryrun` dump and T2's boot answer both before any board time, and they are kill condition 2's cheap test (RT:273).
4. **The startup change is verified the way m3-design pre-specified** (m3-design.md:1088-1092): option off by default, an option-off regression, then a host-only rung with the option on, before any Linux guest touches the board.
5. **"Unchanged" is literal.** The configuration's hash is the same on TCG and the board, with no allowed-line exception (C2). The `dryrun` and dump settings travel on the qvm command line, not in the file.

**Pass tiers for a board S1 run** (§5.1)

| Tier | Evidence | Needed for |
|---|---|---|
| L0 | shim `T234-SHIM EL=2`, `t234: WDT0 CR=`, the startup window, GPU-range and canary lines, `procnto up`, `S1 CONFIG` | B2-B5 (B1 has its own tokens, §6.6) |
| L1 | `S1 MEM` gate, `S1 ASINFO`, `S1 CANARY … verify=ok` at start, `S1 CHECK … md5_pre ok` | B2-B5 |
| L2 | `S1 DRYRUN` accepted, and the FDT export decodes on the PC | items 1, 2, 5 |
| L3 | `STAMP l_kernel` (the kernel's first line on the pl011 stream) | diagnosis only |
| L4 | `STAMP i_ready` (our `/init` on `hvc0`) | items 1, 2 |
| L5 | `STAMP shell_ok` (probe 1 answered) | items 1, 2 |
| L6 | ten heartbeats, `STAMP end_ok`, `S1 HOLD end qvm=alive`, `S1 CANARY … verify=ok`, `S1 ALLOC hold … verify=ok` | item 4 |
| L7 | teardown, `md5_post ok`, the image's own reset, `MAINSWRST`, a new `boot_id`, the bootloader slot unchanged | B2-B5 (B1, §6.6) |

**Session ladder** (§6.12)

| Step | Where | Purpose |
|---|---|---|
| T0 | PC | Startup change and symbol gate, generators, config gate, cpio builder, ksh check |
| T1 | PC, TCG | `dryrun` plus FDT dump: plan prerequisite (c), the first half of pass item 1 |
| T2 | PC, TCG | Boot to `hvc0`, probe answered: pass item 1 |
| T3 | PC, TCG | The ten-minute script path, rehearsed (not a pass item) |
| B0 | board, read-only; owner present | Pre-flight (§8), inputs re-hashed, staging, `p0` kexec acceptance, then a reboot to a fresh L4T |
| B1 | board | `s1-m1b-p6`: the new startup, option off; black box equal to M1b R2's |
| B2 | board | `s1-h1`: option on, no qvm; window 2 reflected, the canaries, the window-2 allocation |
| B3 | board | `s1-n1`: native `dryrun` and boot to an `hvc0` shell: pass item 2 |
| B4 | board | `s1-n2`: the ten-minute run: pass item 4 |
| B5 | board, only if D1 keeps the QNX guest | `s1-q2`: the QNX guest's banner and IPC beside Linux: pass item 3 |

**What a pass settles**
- qvm 8.0 boots the stock L4T 5.15 arm64 `Image` on this project's TCG QHV host and natively on the Orin Nano, with one configuration.
- The native host can claim window 2 as RAM; three fixed ranges were unchanged from startup to the end of one ten-minute run; and one filled host allocation held its data across that run.
- The generated FDTs for both hosts, their differences and the accepted pinning syntax are on record for the freeze.

**What it is not**
- Not a timing, a baseline or a latency of anything.
- No isolation claim. Stage-2 containment is qvm's design and no step tests it. DMA is uncontained: the GPU's DMA is CPU-physical with no SMMU in its path even under L4T (RT:54, R3), so the `rmmod` quiesce is its only control; the other masters are untranslated because Linux disables the SMMUs before kexec (RT:81, C7).
- Not that the guest's RAM came from window 2, and nothing about a guest larger than 512 MiB.
- Not repeatability, not a supported configuration, and nothing about the GPU.

---

## 1. Inputs and contradictions resolved

**Inputs:** plan S1-F, freeze gate and checklist 11c (plan:459-491, :856-868); RT §3 B5, B10, §5, §6; m3-design, m4-design, m5-design; `board/` sources; `lib/common_options.c`, `lib/_main.c`; `startup/` generators, templates and board loops; `qhvc/g2-m3.conf`; `tools/tcu-cat.c`; the TCG harnesses in `orin-native/m4/` and `orin-native/m4dry/`; `scripts/qhv/`; the QH pages for `load`, `cmdline`, `ram`, `cpu`, variables, `dryrun`, `vdev virtio-console`, `vdev pl011`, `vdev gic`, the AArch64 VM firmware and `unsupported`; LX `arm64/booting.html`, `kernel-parameters`, `init/main.c`, `drivers/base/Kconfig`; BF.

| # | Contradiction or open point | Resolution | Evidence |
|---|---|---|---|
| C1 | Kill condition 1: "no second window can be shown free after `rmmod`" (plan:472); prerequisite (b) likewise (plan:463) | **Stale since 11c.** The quiesce frees no RAM window, because the map is fixed at boot (plan:861). The live test is whether an unreserved System RAM range, stable across boots, can be claimed as a second `add_ram` with FreeMem reflecting it. That is B2 (§6.7). Reworded kill condition, against the one candidate 11c found: on B2, window 2 (inside `0x100000000-0x249ffffff`) holds data wrongly, that is `S1 ALLOC … verify=bad` or a window-2 canary `verify=bad`, with c1 in window 1 verifying in the same run. A startup or tool defect (F12, F13 with a crash message, F15, F28) is fixed and B2 rerun; it is not a kill verdict. Deriving another range is a new design revision, not a step of S1 (D8) | VERIFIED (plan:856-868) |
| C2 | Pass item 2, "the same configuration, unchanged", against M4's TCG builder, which rewrites the load path (`build-m4tcg-image.ps1:315`) | **Literal identity.** The Linux payload lives at `/data/s1/` on both hosts: TCG through `data_files.custom`, native as absolute IFS paths (§4.2). `dryrun` and `fdt-dump-file` are qvm command-line arguments, documented in that form (QH `vm/variables.html` example). The file's sha256 must match on every leg | VERIFIED (the M4 rewrite); design |
| C3 | Pass item 1: "`dryrun` accepts the configuration". qvm's exit status after a `dryrun` is undocumented (QH `vm/dryrun.html`) | **Accept means all of:** the documented `FDT saved to` line; a non-empty dump that decodes on the PC with magic `d00dfeed`; no qvm logger line at `error`, `fatal` or `internal`; qvm exited within its bound. ~~The exit code is recorded, not judged~~ **2026-09-14:** after T1 attempt 1, accept also needs exit code 0 and no qvm configuration diagnostic, that is no dryrun output line beginning `[file:line] `; the exit code is still recorded. Attempt 1's gate passed a dryrun that exited 64 with such a line (§14.9) | VENDOR_CLAIM (docs silent); design |
| C4 | Does qvm recognise an EFI-stub arm64 `Image` with a bare `load`? | **UNKNOWN.** QH `vm/load.html` says only that "ELF or Linux image format" files load where their contents say. T1 answers. Contingency: `guest load`. Never gzip the kernel: arm64 has no decompressor (LX `booting.html`), and qvm documents none | VENDOR_CLAIM; UNKNOWN |
| C5 | What FDT does qvm generate for a Linux guest (memory, PSCI method, timer PPIs, `/chosen` bootargs and initrd, virtio,mmio and pl011 nodes, `kaslr-seed`)? | **UNKNOWN; the docs list none of it** (QH `config/acpi_fdt.html`). T1 dumps it on TCG and B3 on the board, and the PC reads both (§6.2). `psci-supported auto` reads the host's tree (QH variables), so the two dumps are expected to differ (HYPOTHESIS) | UNKNOWN |
| C6 | Plan: "a small busybox initrd" (plan:460). No static busybox exists on the board, and installing `busybox-static` is a download (BF) | **Still busybox:** the initrd's dynamic busybox with `ld-linux-aarch64.so.1`, `libc.so.6` and `libresolv.so.2`, copied from the stock L4T initrd (§3.5, D2) | VERIFIED (BF) |
| C7 | The TCG leg's config gate would reject `cmdline`, `initrd`, `logger` and `set` (`scripts/qhv/g2.conf.allow`, its keyword list), yet its header said `post_start.custom` runs the validator, which the committed snippet does not do (RT reader check; §Appendix A; **2026-09-14:** the header comment is corrected, which moved its line numbers) | **S1 uses its own allow-list** (`s1/s1-conf.allow`) and gate, run on the PC at build time and in both generators. TCR-CFG-001's allow-list governs the QNX guest's configuration and is not edited (D13) | VERIFIED |
| C8 | RT's S1 runs Linux "beside the QNX guest" (RT:324) and gates S1 on G1-G3 with a GPU-overlay G2 (RT:320); the owner's target has no QNX guest (RT:342) | **The plan and owner rule:** the guest set is freeze item 2 (plan:480), and S1-F needs only a no-GPU `dryrun` first (plan:465). Linux only by default, B5 if D1 keeps the QNX guest | VERIFIED |
| C9 | M3's window-1 budget leaves about 111 MiB (m3-design.md:300-301, HYPOTHESIS) | **Holds for two guests, not for Linux only.** Without the QNX guest pair, its disk copy and the io-blk cache, the Linux-only budget leaves room for a 512 MiB guest in window 1 (§3.3, HYPOTHESIS). Two guests need window 2 | HYPOTHESIS (budget) |
| C10 | The generators cap the IFS end at `0x8C000000` (`startup/make-m3-images.sh:780-784`; `make-m4-images.sh:845`, `:924-928`) | **A budget rule, not a hardware limit:** it "leaves at least 800 MiB of the window" (m3-design.md:972). Linux only passes it. Two guests exceed it (§4.4), so B5 needs it re-derived (D14) | VERIFIED |
| C11 | `stamp` never writes to its input or changes termios (m3-design.md:692), and COM3 is receive-only (BF), but a shell needs input | **A new tool, `s1con`,** which ~~holds the pty master~~ holds one end of pty pair 3, stamps output as `stamp` does, and writes a probe line when a needle fires or a trigger file appears. ~~The virtio-console `hostdev` names the pty slave, so the slave's line discipline sits on qvm's side, as M3's pl011 stdout path already does (`startup/m3-host.ksh.in:97`, `:106`)~~ (§3.4). **2026-09-14:** §3.4's fallback was adopted after T1 attempt 1, where qvm could not open the slave (§14.9): `hostdev /dev/ptyp3`, the master, with `s1con -O -R` on the slave `/dev/ttyp3`. That is M3's IPC wiring: `hostdev /dev/ptyp0` (`qhvc/g2-m3.conf:38`) with the client on `/dev/ttyp0` (`startup/m3-host.ksh.in:53`, `:121`) | VERIFIED (M3 pattern); design |
| C12 | Pass item 4's "host memory canaries" have no instrument or definition (a repository search finds only plan:470 and m3-design's file checks, m3-design.md:1310, :1328) | **Designed here** (§3.8): reserved-range pattern canaries in both windows, the window-2 allocation check on B2, and M3's md5 checks | VERIFIED (absence) |
| C13 | The plan's §3.4 command lists three `rmmod` names (plan:182); M3's O4 and 11c used four | **Four:** `nvidia_drm nvidia_modeset nvidia nvgpu`, as 11c ran twice cleanly (plan:860) | VERIFIED |
| C14 | `m3-board.sh`'s default return bound is 1,200 s (`startup/m3-board.sh:41`) and M3's guard 900 s (`startup/m3.build.in:75`); a ten-minute hold fits neither | **Bounds follow M4's rule:** guard = ceil((ksh worst + 125 + 240) / 300) × 300; return bound = guard + 300 s (m4-design.md:1252, :1264, :1267), read from a per-image params file as `m4-board.sh` does (`startup/m4-board.sh:568-572`) | VERIFIED |
| C15 | Could `-r addr,size` on the startup line reserve the canaries with no binary change? | **No, and neither could `avoid_ram` in the board.** `-r` calls `avoid_ram` (`lib/common_options.c:135-143`). `avoid_ram` only appends to a list (`lib/ram.c:401-419`) that startup's own searches read (`:167`, `:217`). `add_sysram` hands procnto every `ram_list` entry and never reads that list (`:427-440`, called at `lib/init_system_private.c:319`). Only `alloc_ram` removes a range from `ram_list` (`:275-351`). So the board option takes each canary out with `alloc_ram` and registers it with `as_add_containing`, the pattern `fdt_asinfo` uses for the kexec tree (`lib/fdt_init.c:46-47`) and `reserve_ram` uses (`lib/ram.c:507-515`). `t234_init_raminfo` (`board/main.c:235`) runs before `init_system_private` (`:293`), so the ranges never reach `sysram` (§3.3) | VERIFIED (source) |
| C16 | Pass item 5 asks for "the device-tree hash" | **Two hashes:** the FDT qvm generates, dumped by `dryrun` in every run that has a guest (T1, T2, T3, B3, B4, B5; T2 and T3 run the `dryrun` and export before their launch, §6.3). B2 has no qvm and stamps `fdt=none`. The board's own kexec tree is recorded too, as the input to `psci-supported auto`. B1 is exempt from item 5 (§6.6) | design |

---

## 2. Design rules

1. **Stock Linux bytes.** The kernel is `/boot/Image` from the board, sha256-pinned on the PC after an owner-run copy (D3). The initrd's busybox and libraries are byte copies from `/boot/initrd`. Nothing is recompiled, patched or gzipped except the initrd cpio itself.
2. **One configuration.** `s1/s1-linux.conf`, sha256-pinned, is staged byte for byte in every image of every leg: T1-T3, B3, B4, B5. Any change to it after T2 passes reruns T1 and T2 first.
3. **TCG before board.** No board rung runs before T1-T3 pass. A board-only diagnostic may differ from the configuration (§7, `s1-d1`), but it is never a pass run.
4. **The startup change is verified in order** (m3-design.md:1088-1092): the option is off by default; `build-board.sh`'s symbol gate passes (`startup/build-board.sh:119-184`); B1 shows that option off changes nothing; B2 runs option on with no qvm. Every later record carries the new startup sha256.
5. **Board safety as in M3 and M4.** kexec only; no write to QSPI, the ESP, a UEFI variable or the rootfs; nothing persistent on L4T apart from staged kimgs in the home directory. The one possible exception is I-b's board-side build, and only if the owner approves it under D2 (§3.5). Never claim `0x40000000`, `0xBE000000-0xC1FFFFFF`, the swiotlb child, the CMA pool at `0x2_4A00_0000`, ramoops at `0x2_725F_0000`, the black box (`board/init_raminfo.c:45-58`; `board/t234_startup.h:116-119`) or the provisional GPU range `0x1_8A00_0000-0x2_49FF_FFFF` (D18).
6. **Every path ends in a reset.** The image resets itself after the host script. The guard `bwait -g` resets on expiry, and `-A` turns an abnormal kernel end into a PSCI reset (`startup/m3.build.in:35-45`, `:75`). A hang with interrupts masked, or a busy guest with no fan, costs a power cycle, so **the owner is at the plug for every board rung** (m4-design.md:1328-1330, :1396; D15 confirms the schedule only).
6a. **Power is cut by the class of the last COM3 line, never by the clock alone** (M5's rule 5, m5-design.md:130-134).
   - **Last output is startup, QNX, qvm or guest text, and no firmware banner followed:** the L4T boot option had already started before kexec, so a cut after the §7.2 F25a wait is allowed.
   - **A firmware banner appeared after the image's reset, and L4T has not answered:** that boot is unvalidated, and slot failover counts unvalidated boots with an UNKNOWN threshold (m5-design.md:132). Power is cut only under M5's exception, word for word: no new COM3 byte for 10 minutes, the last output not a menu or prompt, no ssh in that time; one cut, record the last line, press nothing, let L4T boot to a validated state. If that boot also stops, board work stops and the owner decides. Never a second cut.
   - **No capture running, so the class cannot be read:** treated as the second case.
   - `nvbootctrl dump-slots-info` is read before the first rung and after every return (§6.11, §8 item 13).
7. **Host scripts are pipe-free,** with every wait a `bwait` bound (`startup/m3-host.ksh.in:11-15`), checked by `parse-m4.py kshcheck` (m4-design.md:1459). Nothing prints to the console between a launch and its needle wait, because the TCU callout busy-polls in the writer's context.
8. **Records, not measurements.** FreeMem is read only to gate against design constants. Every bound in §6 is a wait bound, not a result. No duration, rate or FreeMem value is reported.
9. **No QNX binary committed or read.** Host IFS, kimg and `.sym` stay under `out/` or `/qhv/`. Linux binaries likewise (Licence status).
10. **Records are git-ignored and redacted.** Board records go under `results/orin-native-port/<utc>/s1/` (`.gitignore:62` ignores every file type there), TCG raw files under `qhv/s1tcg/attempt<N>/` (`.gitignore:16`), never in `logs/sample-boot/` (`:66` un-ignores logs there). `<user>`, the board hostname, addresses and the key name are redacted. **Record files:** each TCG step's parser verdict is `qhv/s1tcg/attempt<N>/parse-s1.txt`; each board step's is `<rec>/<step>/parse-s1.txt`; the run note is `r/s1-runs.md` on the local branch `m3-results-unpublished` only. Pass verdicts, the S1-F met line and any kill-condition verdict are written in the run note, citing those files.
11. **Earlier records and generators stay untouched.** M3 and M4 generators, templates, images and records are read only. S1 gets its own generator (§4.2).
12. **The Linux guest gets no GPU, pass-through, SMMU vdev, network or block device.** Its only vdevs are pl011 and virtio-console, plus the implicit GIC (QH `vdev_ref/vdev_gic.html`).

### Timeline of one board S1 run: fault and hang coverage

| Phase | Where | Fault | Hang |
|---|---|---|---|
| Quiesce, kexec | L4T | the harness stops with L4T running (exit 3, `m3-board.sh:58-60`) | the stuck-shutdown rule (`m3-board.sh:42-47`) |
| Shim, startup, procnto | EL2 | M3's coverage: `BAD-LANDING`, vectors, named crashes | unbounded before the guard: power cycle |
| Startup canary fill (B2-B5), inside `t234_init_raminfo` | EL2, startup | an overlap with the image, the FDT, the shim page, the black box or the GPU range is a named crash and a reset, before any write (§3.3, F31) | the guard is not yet armed: power cycle, as for all of startup |
| Host script to launch | EL2&0 | `-A` resets on an abnormal kernel end | the guard |
| `dryrun`, launch, needle waits | qvm | qvm exits: `qvm.rc` recorded, script continues to teardown | `bwait` bounds, then the guard |
| Hold (B4) | qvm, guest | a guest panic reboots it through PSCI `SYSTEM_RESET`, which ends qvm (`panic=-1`; QH `start/guest_stop.html`); T1 gates on the PSCI node that needs. Without it the guest prints `Reboot failed -- System halted` and spins, which `l_rbfail` turns into an immediate teardown (F29) | heartbeat bounds, then the guard |
| Teardown, exports | host | `slay -f -Q`, then SIGKILL (`m3-host.ksh.in:128-133`) | `bwait` and `tcu-cat -a -T` bounds |
| Reset to L4T | firmware | — | autoboot; return bound, then power cycle |

---

## 3. The path

### 3.1 Guest set for S1-F

| Option | What | For | Against | Verdict |
|---|---|---|---|---|
| **G-L** | Linux only | The owner's target (RT:342). IFS about 52 MB, geometry gate unchanged. Window 1 alone can host the guest. One qvm on four cores | Pass item 3 untested until the guest set is decided | **Chosen as the default (D1)** |
| G-QL | QNX guest plus Linux, from the first board rung | RT's S1 as written (RT:324). Item 3 in the same runs | IFS past the gate (C10); a larger kimg with an untested landing; window 2 required before any Linux boot; no two-VM precedent on any leg | Folded into G-L as rung B5 |
| G-both | G-L, then B5 only if D1 keeps the QNX guest | Items 1, 2, 4, 5 pass without prejudging freeze item 2 | One extra rung if the QNX guest stays | **This is G-L as specified** |

**Why.** Pass item 3 is conditional on v1's guest set (plan:469), which the owner fixes at the freeze (plan:480). G-L tests every other item with the fewest moving parts. The Linux configuration pins the guest to cores 1-3, and the M3 QNX guest's bare `cpu` line floats (`qhvc/g2-m3.conf:29`), so B5 needs no change to either configuration.

### 3.2 Entry path

| Option | For | Against | Verdict |
|---|---|---|---|
| **kexec from L4T** | The loop M3 and M4 ran; 11c's window evidence is Linux's view of this path (plan:859-866); no wiring change | Inherits Linux state; needs the quiesce and governor pin | **Chosen (D6)** |
| UEFI through a rebuilt `M5LOAD.EFI` | No Linux residue | Proven only at `-P1` with no qvm (m5-design.md:768); a loader rebuild reruns T0 (m5-design D11); the TX wire must be refitted (BF); firmware allocations inside window 2 were never checked (m5-design.md:163 checks only the kimg's range) | Deferred to the freeze and campaign |

### 3.3 RAM layout

**Facts.** RAM is stated, not discovered: one `add_ram(0x80000000, size)` (`board/init_raminfo.c:36-43`). The image is kept out of procnto's `sysram` by `alloc_ram`: `add_ram` allocates the image RAM (`lib/ram.c:377-379`) and the board allocates `shdr->ram_paddr` again (`board/main.c:251`). `lib/_main.c:141-143` only calls `avoid_ram`, and an `avoid_ram` range still reaches `sysram`, because `add_sysram` never reads the avoid list (`lib/ram.c:427-440`; C15). qvm's `ram` line takes a guest-physical start and length, and the documentation names no way to choose the host memory behind it (QH `vm/ram.html`, VENDOR_CLAIM).

| Option | What | For | Against | Verdict |
|---|---|---|---|---|
| R-1 | Window 1 only | No startup change | Leaves plan prerequisite (b) and freeze item 6 unanswered; B5 impossible | Rejected |
| **R-2** | A new board option adds window 2 after window 1, keeps the GPU range out, and takes three canary ranges out of `sysram` and fills them | Answers prerequisite (b); one startup change covers the canaries (C15); the watched interval starts before procnto | New startup pin, B1 regression | **Chosen (D7)** |
| R-3 | Carry `Image` and initrd as separate kexec segments outside the IFS | Frees window 1 | Startup must `avoid_ram` the segment and a host tool must expose it as a file; kexec acceptance untested (RT:235) | Contingency for B5 only (D14) |

**The option.** `-b <list>`, parsed like `-t` (`board/main.c:178-186`): recorded during `getopt`, checked after `select_debug`, so a typo crashes with a message. The letter `b` is outside the common strings `Q:E:X:Uu:` and `ACc:D:F:f:I:i:K:M:N:o:P:R:S:Tvr:j:ZH` (`lib/public/aarch64/cpu_startup.h:55`; `lib/public/startup.h:163`) and the board's `m:W:t:` (`board/main.c:161`).
- `-b` absent: nothing changes, and nothing new is printed.
- `-b w2`: after window 1, `add_ram(0x100000000, 0x8A000000)`, then `kprintf("t234: ram w2 base=0x100000000 size=0x8a000000\n")` and `kprintf("t234: gpu range base=0x18a000000 size=0xc0000000 not added\n")`. Nothing is called for the GPU range: it is simply never added.
- `-b w2,canary`: also, in `t234_init_raminfo` after both `add_ram` calls (so before `init_system_private`'s `add_sysram`, `board/main.c:235`, `:293`), for each canary in order:
  1. **Refuse before any write:** crash with `t234: canary cN overlaps <image|fdt|shim|blackbox|gpu>` if the range overlaps `[shdr->ram_paddr, +shdr->ram_size)`, `[boot_regs[0], +fdt_size)`, the shim page, the black box, or the GPU range, or if it is not wholly inside window 1 or window 2. kexec places the tree 2 MiB-aligned just above the image (r/research-kexec-tcu.md:416-419, :475-476), far below `c1`, so this is a guard, not an expected branch.
  2. `alloc_ram(base, 0x1000000, 1)`, which removes the range from `ram_list` (`lib/ram.c:275-316`).
  3. `as_add_containing(base, base + 0xFFFFFF, AS_ATTR_RAM, "s1canary", "ram")`, as `fdt_asinfo` does (`lib/fdt_init.c:46-47`).
  4. `startup_io_map(0x1000000, base)`, write each 8-byte word as `splitmix64(base + offset)`, `startup_io_unmap` (the mapping call the black box uses above 4 GiB, `board/hw_sertcu.c:72`; `lib/public/startup.h:539-540`).
  5. `kprintf("t234: canary cN base=… size=0x1000000 filled\n")`.
- No canary ends exactly where another `ram_list` entry starts: `alloc_ram`'s overlap test would then also match that entry (`lib/ram.c:297-299`). The constants below satisfy this (VERIFIED arithmetic); the generator's constant check (§6.1) keeps it so.
- The constants go in `board/t234_startup.h`, next to `T234_RAM_BASE`. Window 2 ends at `0x1_89FF_FFFF`; the GPU range ends at `0x2_49FF_FFFF`, below CMA at `0x2_4A00_0000`, ramoops at `0x2_725F_0000` and the black box at `0x2_7277_0000` (VERIFIED arithmetic; plan:864, `t234_startup.h:116`). `0x8A000000 + 0xC0000000 = 0x14A000000`, the whole 11c candidate.
- **The window size is provisional for freeze item 6** (D18). Any resize changes the startup binary, so it reruns B1 and B2.

**Canary ranges** (design constants, 16 MiB each):

| Name | Range | Why here |
|---|---|---|
| `c1` | `0xBD000000-0xBDFFFFFF` | The top of window 1, far above the IFS end (§4.4) |
| `c2` | `0x1_0000_0000-0x1_00FF_FFFF` | The bottom of window 2, the first page above 4 GiB |
| `c3` | `0x1_8900_0000-0x1_89FF_FFFF` | The top of window 2, the last 16 MiB below the GPU range |

The GPU range itself is not watched: nothing S1 runs maps or writes it, and a fourth canary there would be a GPU check, which the owner left to the first GPU stage (plan:465).

**Linux-only budget in window 1** (MiB; design, HYPOTHESIS apart from marked rows):

| Item | MiB | Source |
|---|---|---|
| Window 1 | 992 | VERIFIED (`init_raminfo.c:39-43`, `-m992M`) |
| Canary `c1` | 16 | design |
| Kernel, syspage, startup, early processes | 15.4 | m3-design.md:292 (M1b) |
| IFS: M3's non-guest payload, `Image`, initrd, S1 tools and text | about 52 | §4.4 |
| slogger2, pipe, devc-pty, bwait, stamp, s1con, ksh | 4 | budget, as m3-design.md:294 |
| qvm process and slog buffers | 20 | budget, as m3-design.md:298-299 |
| Guest RAM | 512 | the configuration |
| **Committed** | **about 619** | |
| **Headroom** | **about 370** | before window 2 |

No disk copy and no io-blk cache: the Linux guest has no block device. Because 512 MiB fits window 1 with margin, a launch never depends on qvm drawing from window 2. Window 2 as usable RAM is shown instead by B2's allocation check (§3.8). The budget is HYPOTHESIS (R34), answered by L1's memory gate on T1 and B3. With `-b w2` on B3 and B4, qvm may place guest RAM in either window; where it went is recorded only if a host-side view with physical addresses exists (Q14, `S1 GUESTRAM`), and otherwise stated as unknown (§5.5, §10).

**Guest-physical layout:** `ram 0x80000000,512M`. The `Image` header's flags `0xa` (bit 3 set) allow any 2 MiB-aligned base (BF; LX `booting.html`). The initrd then lies within the 1 GiB-aligned window the protocol requires (LX `booting.html`). `linux-fdt-free` stays at its default, and the dump shows where the FDT went.

### 3.4 Console and shell evidence

| Option | What | For | Against | Verdict |
|---|---|---|---|---|
| C-a | `/init` prints markers, then `exec sh`; no input | No new tool | "A shell" never reads a line: the evidence is init's script | Rejected as the pass rule (D9) |
| **C-b** | C-a plus host-injected probes through `s1con` | An interactive shell proven from output alone, with COM3 receive-only | A new tool; the pty input path is untested | **Chosen** |
| C-c | virtio-console `hostdev >-` to qvm stdout | No pty | Not a documented form for virtio-console (QH vdev page lists `<`, `>`, both, `>"|cmd"`); output only | Rejected |

**Wiring** (Linux guest; pairs 0-1 stay the QNX guest's, as in M3):
- pl011: `hostdev >-`; qvm's stdout and stderr are redirected to `/dev/ttyp2`; `stamp -i /dev/ptyp2` reads the kernel log and qvm's logger (the M3 pattern, `m3-host.ksh.in:97`, `:106`).
- virtio-console: `hostdev /dev/ptyp3`, the master, held by qvm; `s1con -O -R` opens the slave `/dev/ttyp3` read-write and sets it raw (**2026-09-14**, C11's fallback, §14.9). ~~`hostdev /dev/ttyp3`, the slave; `s1con` opens master `/dev/ptyp3` read-write.~~
  - ~~Why the slave: bytes the host writes to the master reach qvm as input. The slave's echo, if on, returns them to the master, where `s1con` sees its own probe text, which cannot match a needle. Guest output passes the slave's output processing to the master. So no termios change is needed. HYPOTHESIS until T2.~~ **Correction 2026-09-14:** T1 attempt 1 refuted this on qvm's side. With the slave as `hostdev` and nothing holding the master during the dryrun, qvm printed `Unable to open '/dev/ttyp3': Interrupted function call` and exited 64 (§14.9). The fallback below is adopted. It is also M3's precedent: qvm holds the master `/dev/ptyp0`, and the host client opens the slave `/dev/ttyp0` (`qhvc/g2-m3.conf:38`; `startup/m3-host.ksh.in:53`, `:121`).
  - Fallback (~~if qvm rejects a slave or input stalls in canonical mode~~ **adopted 2026-09-14, before T2; T1 runs again as attempt 2**): `hostdev /dev/ptyp3` with `s1con -R` on `/dev/ttyp3`, which sets raw mode, as `qnx-host-client` does for IPC (m3-design.md:845). ~~That changes the configuration, so it is decided at T2, before any pass run.~~ It changes the configuration's sha256, and no pass run had used the old one (§14.9).
  - **Reader order (2026-09-14, after T1 attempt 2, §14.10):** `stamp` still opens the master `/dev/ptyp2` before the launch. `s1con` now starts right after qvm is launched in the background, and its `open.hit` is the first wait after the launch. The reason is that a slave open is expected to wait for its master (HYPOTHESIS, §14.9), and qvm opens `/dev/ptyp3` only once it is running. The dryrun before the launch needs no reader.
- `devc-pty` provides eight pairs by default (`m3.build.in:78`; m3-design.md:91).

**Needles** (all our text except the kernel's):

| Stream | Needle | Label |
|---|---|---|
| pl011 | `Booting Linux on physical CPU` | `l_kernel` (HYPOTHESIS: the arm64 5.15 banner text) |
| pl011 | `Run /init as init process` | `l_run_init` (HYPOTHESIS: 5.15 `init/main.c` wording) |
| pl011 | `Kernel panic` | `l_panic` |
| pl011 | `Reboot failed -- System halted` | `l_rbfail` (LX v5.15 `arch/arm64/kernel/process.c` `machine_restart()`: printed when no restart handler resets, then `while (1);` with interrupts off). Its `bwait` hit triggers teardown at once (F29) |
| hvc0 | `S1-INIT start` | `i_start` |
| hvc0 | `S1-INIT ready` | `i_ready` |
| hvc0 | `S1-SHELL-42-OK` | `shell_ok` |
| hvc0 | `S1-HB` | `hb` |
| hvc0 | `S1-END-43-OK` | `end_ok` |

**Probes.** On `i_ready`, after a 2 s settle, `s1con` writes `echo S1-SHELL-$((40+2))-OK` and a newline. The echoed command cannot contain `S1-SHELL-42-OK`; only the shell's arithmetic produces it. At the end of the hold, the host creates a trigger file and `s1con` writes `echo S1-END-$((42+1))-OK`. busybox ash supports `$(( ))` (HYPOTHESIS for Ubuntu's reduced build; T2 answers).

**Kernel command line** (the configuration's only source: `CONFIG_CMDLINE` is empty, BF):
`console=hvc0 earlycon=pl011,0x1c090000 keep_bootcon nokaslr rdinit=/init panic=-1 cma=16M loglevel=7`
- `earlycon=pl011,0x1c090000`: the only output before virtio-console probes. `HVC_DCC` is not built (BF). QNX's own ARM Linux example uses this address (QH `start/qvm_start.html`).
- `keep_bootcon`: keeps the kernel log on the pl011 after `hvc0` registers (LX kernel-parameters).
- `console=hvc0` last, so `/dev/console` is the virtio port (QH vdev page). No `console=ttyAMA0`: the AMBA PL011 driver needs an `apb_pclk` clock the generated node may lack (LX v5.15 `drivers/amba/bus.c`).
- `nokaslr`: deterministic whether or not qvm writes a `kaslr-seed` (LX v5.15 `arch/arm64/kernel/kaslr.c`).
- `panic=-1`: a guest panic reboots it at once, which ends qvm by design (QH `start/guest_stop.html`). On arm64 that reboot needs a restart handler; in a qvm guest loaded directly (no EFI runtime) that is PSCI `SYSTEM_RESET`, so T1 gates on a PSCI node (§6.2). If the reboot still fails, the guest prints `Reboot failed -- System halted` and spins a vCPU with qvm alive (LX v5.15 `machine_restart()`); `l_rbfail` catches that and tears qvm down (F29).
- `cma=16M`: `CONFIG_CMA_SIZE_*` is not in BF; a large built-in default in a 512 MiB guest is avoided. Ignored if CMA is not built.

**Black-box budget.** The host prints capped heads only: pl011 log 2,048 B, `hvc0` log 2,048 B, a 1,024 B tail of each on failure (M4's cap, m4-design.md:1308-1324). The full streams go to COM3 by `tcu-cat -f`, which writes the mailbox directly and never enters the black box (`tools/tcu-cat.c:8-21`; the callout mirrors, `board/aarch64/callout_debug_tcu.S:110-140`). The cap stays 65,520 B, with M3's rebuild-at-`-vv` rule at 60,000 B (m3-design.md:859-879).

### 3.5 Initrd

| Option | What | Proves | Against | Verdict |
|---|---|---|---|---|
| **I-a** | New gzip newc cpio: busybox, `ld-linux-aarch64.so.1`, `libc.so.6`, `libresolv.so.2` byte-copied from `/boot/initrd`; `/lib` usrmerge links as in the source; applet links `sh mount echo cat uname sleep`; `dev/console` (c 5 1); our `/init` | Stock kernel to a dynamically linked busybox shell | Wrong interpreter path fails like a missing `/init`; Ubuntu's initramfs busybox may lack applets | **Chosen (D2)** |
| I-b | Static `/init` built with the board's `gcc -static` | Userspace entry without a loader | `libc.a` presence UNKNOWN; no shell by itself; writes to L4T's rootfs | Diagnostic fallback, **only on the owner's approval under D2**. Built in `mktemp -d /tmp/s1ib.XXXXXX`; only the binary and the compiler's version line are copied to `s1/out/l4t/`; the directory is removed with `rm -rf` and `ls -d` must then fail. That is the one exception to §2 rule 5 |
| I-c | The stock 37 MB L4T initrd with `rdinit=/bin/sh` | No build step | `/bin/sh` identity UNKNOWN; no mounts or markers; a changed cmdline | TCG diagnostic `s1-d2` only |
| — | `apt install busybox-static` | — | A download | Only if I-a and I-b both fail (D16) |

**`/init`** (our source, `s1/init.sh`, MIT):
1. `mount -t devtmpfs devtmpfs /dev` (`DEVTMPFS_MOUNT` does not apply to an initramfs, LX `drivers/base/Kconfig`), then `proc` and `sysfs`.
2. Print `S1-INIT start`, `uname -r`, `/proc/cmdline`, the online CPU list and the `MemTotal` line, each prefixed `S1-INIT `.
3. Start a background heartbeat: every 60 s print `S1-HB`, at most 12 times.
4. Print `S1-INIT ready`, then `exec sh` on `/dev/console`. It never reboots, halts or exits.

**The cpio writer** is our own stdlib Python (`s1/mkcpio.py`), so device nodes need no root on Windows. Its manifest pins every input's sha256; the output's sha256 is the pinned initrd.

### 3.6 CPU placement

- **Host:** `-P4`, cluster 0 only, as M3 (owner decision O2; `m3.build.in:36-37`). Cluster 1 stays out until freeze item 4 explains its low rate (plan:482).
- **Guest:** three vCPUs, `cpu cluster _cpu-1`, `cpu cluster _cpu-2`, `cpu cluster _cpu-3`: the owner target's sketch restricted to cluster 0 (RT:356-359). A GICv3 vdev caps a guest at eight vCPUs (QH `vm/cpu.html`).
- **Syntax:** QH `vm/cpu.html` shows `cpu cluster _cpu-2` in its examples; the system clusters `_all` and `_cpu-N` come from startup (VENDOR_CLAIM, QNX startup options page). Acceptance by this qvm is UNKNOWN until T1. Fallback: three bare `cpu` lines (floating), recorded.
- **TCG:** `-smp 4` in the S1 rehearsal launcher only, so `_cpu-3` exists there (D5). Stamped `smp=4 not-a-twin-leg`.
- **PSCI:** secondary vCPUs and the guest's panic reboot both need a PSCI node in the generated FDT. **It is a T1 gating row** (§6.2), checked again in B3's dump: without it a guest panic spins instead of ending qvm (§3.4). A node that is present but whose `CPU_ON` fails leaves fewer online CPUs; that is recorded as a finding for freeze item 4, not a failure of items 1-2 (§5.3).

### 3.7 The Linux guest configuration (design text; the file is `s1/s1-linux.conf`)

```
system s1-linux
logger error,fatal,internal,warn,info stderr
ram 0x80000000,512M
cpu cluster _cpu-1
cpu cluster _cpu-2
cpu cluster _cpu-3
load /data/s1/Image
initrd load /data/s1/initrd.cpio.gz
cmdline "console=hvc0 earlycon=pl011,0x1c090000 keep_bootcon nokaslr rdinit=/init panic=-1 cma=16M loglevel=7"
vdev pl011
 hostdev >-
 loc 0x1c090000
 intr gic:37
vdev virtio-console
 loc 0x20000000
 intr gic:42
 hostdev /dev/ptyp3
```

**2026-09-14:** the last line was ` hostdev /dev/ttyp3`, the slave, until T1 attempt 1; C11's fallback made it the master (§3.4, §14.9). No other line changed, and `cmdline_sha256` is unchanged.

- **Addresses and interrupts** reuse M3's proven plan (`qhvc/g2-m3.conf:31-38`), away from the GICv3 defaults at `0x2f000000` and `0x2f100000` (QH `vdev_gic.html`). Each qvm is its own VM, so the same guest-physical addresses beside the QNX guest are expected to work (HYPOTHESIS; B5 answers).
- **MMIO transports** (`loc` plus `intr`): the PCI default would add an undocumented host-bridge dependency (QH virtio-console page).
- **`unsupported`: qvm's defaults** (instruction fail, register fail, reference ignore; QH `vm/unsupported.html`), as M3's configuration used. A board-only unsupported register then shows as a guest fault, not a silent all-ones read (D11).
- **`logger` without `debug` and `verbose`,** to keep the stream small. The TCG-only diagnostic `s1-d1` adds them.
- **The gate** (`s1/s1-conf.allow`): keywords `system logger ram cpu cluster load initrd cmdline vdev hostdev loc intr`; vdev types `pl011 virtio-console`. It also fails on any `pass`, `smmu`, `fdt load`, `virtio-net`, `virtio-blk` or `shmem`. The one conditional exception is a non-GPU `fdt load` overlay that D19 approves by its sha256; the gate then accepts exactly that line and that hash, and the overlay file is pinned like the configuration.

### 3.8 Memory canaries (pass item 4)

**Who writes what.** Startup is the only writer of the canary ranges (§3.3). `tools/memcanary.c`, our code, never writes physical memory. Every result prints as a verdict line, never a count unless it fails.
- **Compiled table:** the three names and their (base, size) pairs, equal to `board/t234_startup.h`'s constants (the generator checks both against one source, §6.1). There is no `-p` or `-s` for a physical range; any other name is refused.
- `memcanary asinfo`: walks the syspage `asinfo` section (`SYSPAGE_ENTRY(asinfo)`, VENDOR_CLAIM, QNX `syspage` documentation) and prints `S1 ASINFO sysram_w1=yes|no sysram_w2=yes|no s1canary=<n> canary_in_sysram=no|yes gpu_in_sysram=no|yes`. The window and GPU constants come from the same table.
- `memcanary verify -n c1|c2|c3`: refuses (`refuse=no-entry` or `refuse=in-sysram`) unless an `s1canary` asinfo entry equals the compiled range and no `sysram` entry overlaps it; then maps it `PROT_READ` with `mmap_device_memory` and checks every word against `splitmix64(base + offset)`. Prints `S1 CANARY c1 verify=ok`, or `verify=bad first_off=… words=…` (diagnostic).
- `memcanary alloc -s MIB`: anonymous `mmap`, touch, fill (`splitmix64` of the virtual offset and a per-run seed), verify, unmap, in one call. Prints `S1 ALLOC mib=<MIB> fill=ok verify=ok`, or `map=fail errno=…` (F28).
- `memcanary hold -s MIB -f TRIGGER -T SECS -o FILE`: as `alloc`, but after the fill it writes `S1 ALLOC hold mib=<MIB> fill=ok` to FILE and keeps the mapping until TRIGGER exists (1 s polls, at most SECS), then verifies, unmaps and appends `verify=ok|bad|timeout`. The host script starts it in the background, as M3 starts `smpcheck` (`m3-host.ksh.in:40`), and waits on its done file with a `bwait` bound.
- `--selftest`: the pattern; the name table; a refused unknown name; a refused name whose simulated asinfo has no entry or a `sysram` overlap; and a refused attempt to name the black box `0x272770000`, which has no table entry by construction.

**When**
- The canaries are filled by startup on every `-b w2,canary` boot, before `hypervisor_init`, `init_smp`, `init_mmu` and procnto (`board/main.c:235-293`). The watched interval therefore starts before the host script and qvm exist.
- `verify c1-c3` runs at the start of the host script (L1), after the hold and before teardown, and again after teardown.
- `alloc -s 1536` runs on B2 only. Window 1's `sysram` is under 992 MiB, so at least 544 MiB of pages come from window 2 (VERIFIED arithmetic), with no figure read.
- `hold` runs in the hold modes: `-s 64` on T3 and `-s 256` on B4, started after `shell_ok` and triggered after `S1 HOLD end`. Both sizes fit the L1 gates (§5.1).
- Under TCG, `asinfo` and `verify` are never called: the TCG host has no `s1canary` entry, so `verify` would refuse anyway. The generator's profile check fails a TCG script that calls them.

**Plus M3's file checks:** md5 of `/data/s1/Image`, `/data/s1/initrd.cpio.gz` and `/data/s1/s1-linux.conf` before launch and after teardown (`m3-host.ksh.in:61-68`, `:136-141`).

**Can detect:** a write into any of the three fixed ranges, by anyone (qvm, a guest escaping stage 2, an untranslated DMA master, firmware, a stray allocation that reached them), between startup's fill and the last verify; a range that reached `sysram`; corruption of the checked payload files; window-2 pages that do not hold data (B2); a change to one host allocation's data during the hold.

**Cannot detect:** writes elsewhere in host-allocated memory or guest RAM; reads; a write restored before the verify; **writes before startup's fill**, that is from the quiesce, Linux's shutdown, kexec and the shim; DMA outside the watched ranges. DMA is uncontained: the GPU's is CPU-physical with no SMMU even under L4T, with the quiesce as its only control (RT:54), and the other masters are untranslated after kexec (RT:81).

**Not adopted: RT B6's GPU BAR0 read in B2** (RT:245). It is a GPU check, which the owner left to the first GPU stage (plan:465), and its expected failure is an SError at EL2, likely class PP. It stays listed for that stage (§5.4).

### 3.9 The host image against M3's

- **Kept:** the shim; `[image=0x80082000]`, `[-compress]`; `-vvv -P4 -Q enable,el2-host -m992M -Wkeep -A -Dtcu`; procnto `-v`; the script order: census, guard, slogger2, pipe, devc-pty, `pidin info`, ksh, reset (`m3.build.in:70-84`); the library set; `qvm`, `qvm-check`, `vdev-pl011.so`, `vdev-virtio-console.so`.
- **Added:** `-b w2,canary` on the startup line (every image except B1); `s1con`, `memcanary`; toybox links `base64`, `od` (the SDP's toybox provides `base64`: `qhv/host/output/build/system.build:121`); the payload under `/data/s1/`.
- **Removed for Linux only:** the guest pair, `devb-loopback`, `io-blk.so`, `cam-disk.so`, `vdev-virtio-blk.so`, `vdev-shmem.so`, `qnx-host-client`. B5 restores them.

---

## 4. Image, configuration and code deltas

### 4.1 Unchanged and pinned

| Artefact | Pin | Status |
|---|---|---|
| startup build (M1b-M4) | `90bf724c…61896` | the pre-change pin (`startup/make-m3-images.sh:96`; `make-m4-images.sh:92`); retained as the B1 reference |
| shim `orin-native/shim/t234-shim.S` and `build-shim.sh` | as m5-design.md §4.1 | unchanged |
| QNX guest IFS and disk (B5 only) | `968029…7cf4f`, `cf5b06…4216b` | `qhvc/g2-m3.conf:23-26` |
| `qhvc/g2-m3.conf` (B5 only) | its current sha256 | unchanged |
| M3 and M4 generators, templates, board loops, images, records | — | read only |
| `/boot/Image` from the board | sha256 recorded at D3's copy | 43,090,432 B (BF) |
| stock `/boot/initrd` | sha256 recorded at D3's copy | the source of I-a's files |

### 4.2 New files (proposed; this design creates none)

**`orin-native/s1/`** (MIT). Outputs go to `s1/out/`, ignored by `.gitignore:53`.

| File | Role |
|---|---|
| `s1-linux.conf` | The configuration (§3.7) |
| `s1-conf.allow` | Its allow-list (§3.7) |
| `init.sh` | `/init` (§3.5) |
| `mkcpio.py` | newc writer; manifest of pinned inputs; `--selftest` |
| `initrd.manifest` | Source member, archive path, mode and sha256 of each file; the `dev/console` node; the symlinks |
| `parse-s1.py` | `conf` gate; `fdt` reader (stdlib, D12); `run` parser for TCG serial logs and board COM3 plus black box (tiers, pass items, export decode and md5); `kshcheck` importing `orin-native/m4/parse-m4.py`'s implementation, so the rule cannot drift; `--selftest` |
| `build-s1tcg-image.ps1` | Derived from `orin-native/m4/build-m4tcg-image.ps1`: root `qhv/s1tcg/`, canonical and guest pins before and after, a new `-Tag` per build, bounded mkqnximage, text checks, `<ROOT>-SHA256SUMS` (m4-design.md:1450-1459). Stages `data_files.custom` lines `s1/Image`, `s1/initrd.cpio.gz`, `s1/s1-linux.conf`; `system_files.custom` lines for `s1con`, `memcanary`, `bwait`, `stamp`, `s1-host.ksh`. Variants `lin`, `hold`, `q2`, `d1`, `d2` |
| `post_start-s1tcg.custom` | `ksh /system/bin/s1-host.ksh`, then `shutdown -S reboot` |
| `launch-s1tcg.ps1` | Derived from `orin-native/m4/launch-m4tcg.ps1`, changing only `-smp 2` to `-smp 4` (its :306), the image paths and the serial file |
| `README.md` | Usage, the privacy and licence rules, the Never list of §7.3 |
| `out/l4t/` | Board copies of `Image` and `initrd` (D3); ignored |

**`orin-native/startup/`**

| File | Role |
|---|---|
| `s1.build.in` | From `m3.build.in`: startup line with `@B_OPT@`; payload at `/data/s1/`; tools; `[+raw]` for `Image` and initrd; `@GUEST_PAIR@` block for `q2` only |
| `s1-host.ksh.in` | The host state machine, modes `host`, `boot`, `hold`, `q2`, with a TCG profile and a board profile (§6) |
| `make-s1-images.sh` | From `make-m4-images.sh`: new `PIN_STARTUP`; `STARTUP_WANT` per image; the config gate; pins of `Image`, initrd, configuration and `init.sh`; extraction of each payload file from the IFS by `dumpifs`, re-hashed; the geometry gate (§4.4); bound table, guard and `return_bound_s` into `<img>.params`; the constant check (the window, GPU-range and canary constants in `t234_startup.h` equal `memcanary.c`'s table; no canary overlaps another, the GPU range or a window edge that starts another entry); the profile check (a TCG script never calls `memcanary asinfo` or `verify`, and a board script calls `verify` only with `c1`, `c2`, `c3`); images `s1-m1b-p6`, `s1-h1`, `s1-n1`, `s1-n2`, `s1-d1`, and `s1-q2` only after D1 keeps the QNX guest and D14's limit is in the gate (§6.1 step 7) |
| `s1-board.sh` | From `m4-board.sh`: `stage`, `p0`, `p1`, `run`, `extract`; params-driven return bound and COM3 gates A and B (`m4-board.sh:801-802`, `:882-883`) |

**`orin-native/tools/`:** `s1con.c` (from `stamp.c`: `-i DEV -o FILE -m CAP -r STAMPS -h DIR` as `stamp`, plus `-O` open read-write, `-w LABEL=TEXT` write after a needle, `-t FILE=TEXT` write when a file appears, `-R` raw termios, `-d SECS` settle before a write); `memcanary.c` (§3.8: modes `asinfo`, `verify`, `alloc`, `hold`, `--selftest`; no physical write); Makefile targets. `stamp.c` is not edited, so its instrument hash stays.

### 4.3 Existing files touched

| File | Change |
|---|---|
| `board/init_raminfo.c` | The `-b` window 2 after window 1; with `canary`, the refusal checks, `alloc_ram`, `as_add_containing` and the startup fill (§3.3). The comment at :27-29 is updated to 11c's result: the window comes from the cross-boot comparison, not from a post-quiesce change |
| `board/main.c` | `case 'b'` in `getopt` (:161), checked after `select_debug` (:193) |
| `board/t234_startup.h` | `T234_RAM2_BASE`, `T234_RAM2_SIZE`, `T234_GPU_BASE`, `T234_GPU_SIZE`, three canary bases and one size |
| `startup/build-board.sh` | No change required: the gate must pass as it stands |
| `orin-native/tools/Makefile` | Two targets, `s1con` and `memcanary`, added to `TOOLS` |
| `.gitignore` | `orin-native/tools/s1con` and `orin-native/tools/memcanary`, beside the existing tool lines (`.gitignore:96-103`), in the same change as the Makefile targets. The Makefile builds in place (`%: %.c`), so `out/` does not cover them |

Every other output path is already ignored (§2 rule 10). T0 step 6 checks the two new lines.

### 4.4 Sizes (design estimates only; the generators print the real ones)

| Item | Bytes | Class |
|---|---|---|
| M3 IFS | about 168,765,000 | design estimate (m3-design.md:930) |
| less the guest pair | 9,783,916 + 153,432,576 | VERIFIED (pins' files) |
| M3's non-guest payload | about 5,548,500 | arithmetic on the estimate |
| `Image` | 43,090,432 | VERIFIED (BF) |
| initrd (I-a, gzip) | about 2-4 MB | HYPOTHESIS |
| S1 tools and text | under 0.5 MB | HYPOTHESIS |
| **Linux-only IFS** | **about 52 MB**, ending near `0x8350_0000` | HYPOTHESIS |
| Geometry cap | `0x8C000000 − 0x80082fa0` = 200,790,112 | VERIFIED arithmetic |
| **Two-guest IFS** | **about 215 MB: over the cap by about 14 MB** | HYPOTHESIS |

**Landing.** kexec places an Image-header payload at the lowest free 2 MiB-aligned hole (r/research-kexec-tcu.md:397-420). Checklist 12 showed segment 0 at `0x80080000` (plan:872; m0-kexec-acceptance.md), and M3's `p0` gate applies unchanged. An S1 kimg is expected to land there too (HYPOTHESIS: Linux's KASLR image can sit in window 1). `p0`'s dynamic-debug check and the shim's `BAD-LANDING` stay, with K1 as the contingency (m3-design.md:1085).

### 4.5 The two-guest delta (B5, only if D1 keeps the QNX guest)

- **Payload:** M3's guest pair, `devb-loopback` stack, `qnx-host-client`, `qhvc/g2-m3.conf` unchanged at `/proc/boot/`.
- **Geometry (D14):** re-derive the `0x8C000000` limit from "window 1 must keep at least the two-guest budget's non-guest share", because window 2 now carries guest RAM. The p0 landing check is re-run for the larger kimg. Alternatives: M3's gzip'd disk contingency `m3z` (m3-design.md:1086), or R-3's separate segment.
- **Host script:** M3's QNX sequence (stamp on `ptyp1`, banner, grace, IPC over `ttyp0`, `m3-host.ksh.in:95-126`) runs after the Linux guest's `shell_ok`, then both are torn down.
- **Gate:** FreeMem at least 1,255 MiB (512 + 512 + 146.3 + 20 + 64, rounded up) before either launch (design constants; §5.1's table).

---

## 5. Tiers, pass and fail

### 5.1 Tier tokens (board)

**L0 (B2-B5).** In COM3 and the black box, in order: `T234-SHIM EL=2` with `PC=0000000080080000`; `t234: WDT0 CR=`; `t234: ram w2 base=0x100000000 size=0x8a000000`; `t234: gpu range base=0x18a000000 size=0xc0000000 not added`; three `t234: canary cN … filled` lines; `T234 S1 <rung> -P4: procnto up`; `BWAIT guard armed secs=<guard>`; `S1 CONFIG …` with every §5.2 item-5 field. None of `BAD-LANDING`, `EXC `, `EL!=2`, `t234: canary … overlaps`. **B1** is exempt from L0 and L7 and has its own tokens (§6.6).

**L1.** `S1 MEM boot <free>` and `S1 GATE mem ok` against the mode's constant below; `S1 ASINFO sysram_w1=yes sysram_w2=yes s1canary=3 canary_in_sysram=no gpu_in_sysram=no`; `S1 CANARY c1|c2|c3 verify=ok`; `S1 CHECK image|initrd|conf md5_pre ok` (not on B2); `S1 STATE hostcheck` with `qvm-check`'s capped output (not on B2).

**Memory gate constants** (MiB; checked before the first launch; `pidin info` prints FreeMem in the same unit as `-m992M`, since its total equals `T234_RAM_SIZE` in MiB, `t234_startup.h:102` — HYPOTHESIS on the TCG host, R13):

| Mode | Steps | Gate | Derivation |
|---|---|---|---|
| `host` | B2 | none; `reflected` instead: FreeMem above 992 | window 1 is 992 MiB in total, so only window 2 can exceed it |
| `dryrun` | T1 | 596 | as `boot`, so T1 answers R13 early |
| `boot` | T2, B3 | 596 | 512 guest + 20 qvm + 64 margin (§3.3) |
| `hold` | T3 | 660 | `boot` + 64 `hold` allocation |
| `hold` | B4 | 852 | `boot` + 256 `hold` allocation |
| `q2` | B5 | 1,255 | 512 + 512 + 146.3 + 20 + 64, rounded up (§4.5) |

**L2.** `S1 DRYRUN rc=0 saved=yes fdt_bytes=… fdt_md5=… logger_errors=0` (**2026-09-14:** ~~`rc=<n>`~~ `rc=0`, and the `qvmlog` export holds no line beginning `[file:line] `; C3, §14.9); then after teardown, `S1 BEGIN name=fdt …`, the base64 block through `tcu-cat`, `S1 END name=fdt`. The PC decodes it, checks md5 and magic, and computes its sha256.

**L3 (diagnosis only).** `STAMP l_kernel`. Its needle text is HYPOTHESIS (R31); its absence alone never fails an item.

**L4-L5.** `STAMP i_start`, `STAMP i_ready`, `STAMP shell_ok`, each from the stamp files printed after the wait. The `i_ready` wait is timed from the launch, not from `l_kernel`. Not `STAMP l_panic` or `STAMP l_rbfail`, and no `qvm.rc` before teardown.

**L6 (hold modes).** `S1 HOLD start secs=600`; `S1 ALLOC hold mib=<n> fill=ok`; ten `S1 HB k=<1..10> qvm=alive rc=absent` lines; `S1 MEM hb10 <free>`; `STAMP end_ok`; `S1 HOLD end qvm=alive`; `S1 ALLOC hold mib=<n> verify=ok`; on the board, `S1 CANARY c1|c2|c3 verify=ok` before and after teardown.

**L7 (B2-B5).** `S1 CHECK … md5_post ok` (not on B2); `S1 FAIL_STATE none`; `T234 S1 <rung> -P4: resetting so the log can be recovered`; the firmware banner; on L4T, a new `boot_id`, PMC `reset_reason` `MAINSWRST`, `nvbootctrl dump-slots-info` equal to the session's first reading, and `s1-board.sh consistency` agreeing between COM3 and the black box.

**B2 (`host` mode) adds:** `S1 W2 reflected=yes` (FreeMem at boot above 992 MiB; a comparison with a design constant, the value itself not reported); the `S1 ASINFO` line above, which is B2's structural evidence that both windows are `sysram` and the canaries and GPU range are not; `pidin syspage=asinfo` capped to 4,096 B as a supplementary record (its view name is HYPOTHESIS, R19, Q3); `S1 ALLOC mib=1536 fill=ok verify=ok`.

**B3 and B4 add, if Q14 finds a view:** `S1 GUESTRAM w1=yes|no w2=yes|no` from a capped host-side mapping view of qvm. Otherwise `S1 GUESTRAM unknown`.

**TCG (T1-T3)** uses the same `S1` and `STAMP` lines on the serial log, with `startup=tcg-profile`, `windows=tcg -m 2G`, `smp=4`, no L0 or L7, no `S1 ASINFO` or `S1 CANARY` lines, and `alloc`/`hold` allocations only. **T3's required tokens:** `S1 GATE mem ok`, `S1 DRYRUN … saved=yes` (**2026-09-14:** with `rc=0`, `logger_errors=0` and no qvm diagnostic, as L2), `STAMP shell_ok`, `S1 HOLD start secs=600`, `S1 ALLOC hold mib=64 fill=ok`, ten `S1 HB k=<1..10> qvm=alive rc=absent`, `STAMP end_ok`, `S1 HOLD end qvm=alive`, `S1 ALLOC hold mib=64 verify=ok`, `S1 CHECK … md5_post ok`, and the parser's `bb_text_bytes` estimate of the board profile's black-box text under 60,000 B (R22).

### 5.2 Pass: plan items 1-5 mapped to evidence

| Item | Plan text (plan:467-471) | Evidence | Judge |
|---|---|---|---|
| 1 | Under TCG, `dryrun` accepts the configuration, and the guest boots to a shell on `hvc0` | T1: L2 per C3, plus the FDT checklist (§6.2). T2: L4 and L5 | `parse-s1.py run` on T1's and T2's serial logs |
| 2 | The same configuration, unchanged, reaches a shell on `hvc0` under native qvm | B3: L0, L1, L2, L4, L5 and L7 (L3 is diagnosis only); `conf_sha256` in B3's `S1 CONFIG` equals T2's; board md5 equals the PC's | `parse-s1.py run` on COM3 and the black box |
| 3 | If v1 keeps the QNX guest, its banner prints and the IPC pair completes | B5: `STAMP banner`, the client's completion lines, both beside L5 for Linux; completion only | as M3's criteria, not its figures |
| 4 | A ten-minute run ends with qvm alive and canaries intact | B4: L6 and L7: every heartbeat `qvm=alive`, `S1 HOLD end qvm=alive`, all three canaries `verify=ok` (fixed ranges outside the allocator, watched from startup), the `hold` allocation `verify=ok` (host-allocated memory, one 256 MiB mapping), `md5_post ok`. Recorded, and required under D10: `end_ok` | `parse-s1.py run` |
| 5 | Every run stamped: kernel, initrd, device-tree and configuration hashes, CPU pinning, RAM windows | Applies to T1-T3 and B2-B5; B1 is exempt (§6.6). `S1 CONFIG` in each of those runs: `image_sha256`, `initrd_sha256`, `conf_sha256`, `cmdline_sha256`, `init_sha256`, tool sha256s, `startup_sha256`, `startup_line`, `cpu_lines`, `ram_line`, `windows`, `canaries`, `guest_set`, `hold_s`, `guard_s`. Target side: md5 of the same files. The FDT sha256 from each run's own L2 decode (T1, T2, T3, B3, B4, B5; B2 stamps `fdt=none`), `gpu_range`, and the kexec tree's sha256 from `p0` | the PC parser refuses a run note without them |

**S1-F is met** when items 1, 2, 4 and 5 hold, B2 has passed (plan prerequisite (b)), and item 3 is settled by one of these, in this order:
1. **The owner settles freeze item 2 before B4's record closes** (D1). If v1 keeps no QNX guest, item 3 is not applicable. If it keeps one, B5 runs and must pass.
2. **If freeze item 2 is still open then,** the record reads "S1-F met provisionally (Linux only); item 3 pending freeze item 2". That provisional line satisfies freeze gate item 1 only if the freeze then chooses Linux only. If the freeze keeps the QNX guest, B5 runs and passes before v1 is frozen, and the line becomes "S1-F met (QNX plus Linux)". Appendix A lists plan:479 so the freeze text can say so.

**Record wording:** "S1-F met (Linux only; item 3 not applicable, freeze item 2 = Linux only)"; "S1-F met provisionally (Linux only); item 3 pending freeze item 2"; or "S1-F met (QNX plus Linux)". Written in `r/s1-runs.md` (§2 rule 10).

### 5.3 Fail and partial outcomes

- **T1 rejects, or the FDT lacks a gating node:** read the logger lines. A configuration fix reruns T1. A missing node may be supplied only by a non-GPU overlay that D19 approves. If no configuration helps, kill condition 2's first stage under D17: one support request, with what D17 allows to be sent; S1-F waits.
- **T2 staged, in order** (each points at a different owner):
  1. no `l_kernel` (the kernel never entered: load format or entry). Try `guest load`, then `s1-d1`;
  2. `l_kernel`, no `i_start` (FDT, interrupt, virtio-mmio or initrd problem). `s1-d2` (I-c) separates the initrd;
  3. `i_start`, no `i_ready` (busybox or a library path);
  4. `i_ready`, no `shell_ok` (the input path: ~~C11's fallback~~ **2026-09-14:** C11's fallback is already in use, so this stage points at the raw slave path and the shell itself, §14.9).
  Only stages 1-2 with a valid FDT point at qvm itself.
- **TCG passes, the board fails:** a board-only difference (the host tree, A78AE registers, PSCI detection, the GIC). `s1-d1` on the board (`unsupported … abort`, `logger … verbose`) is a diagnostic, never a pass run.
  - **Terminal rule:** after `s1-d1`, at most one configuration fix goes through T1, T2 and B3 again. If B3 still fails, board work on S1 stops with "board-only failure; kill condition 2 pending D17" in `r/s1-runs.md`, citing `<rec>/B3/parse-s1.txt` and `<rec>/d1/parse-s1.txt`. D17's request and time box follow; the owner alone declares "QNX support cannot fix it", which records kill condition 2.
- **Fewer online CPUs than vCPUs** (a PSCI node present, but `CPU_ON` failing): items 1-2 still pass; recorded as a finding for freeze item 4. A missing PSCI node fails T1 (§6.2).
- **B1's black box differs** beyond startup-size-dependent addresses: stop; the startup change is revised before any other rung.
- **B2 fails.** Two kinds, kept apart:
  - **A defect** (F12 option typo, F13 crash with a message, F14 `reflected=no` with `S1 ASINFO` showing no window-2 entry, F15 map refusal, F28 `alloc` map failure, a canary `overlaps` crash): fix startup or the tool; T0; rerun B1 if startup changed, then B2. No kill verdict.
  - **Data** (`S1 ALLOC … verify=bad`, or `c2` or `c3` `verify=bad` while `c1` verifies): kill condition 1 for the 11c candidate (C1), recorded in `r/s1-runs.md` citing `<rec>/B2/parse-s1.txt`. S1-F stops (D8). There is no window-1-only continuation: item 4's layout, B5 and freeze item 6 all need window 2.
  - F13 as silence with no message cannot be classed from COM3; it is treated as a defect once, and a second silent F13 is recorded as data for D8.
- **B4 ends early** (`qvm.rc`, `l_panic`, a heartbeat missing, the guard fires): item 4 not met. **A canary `verify=bad`:** item 4 not met; stop board work until the source is found (RT:246).
- **Retries.** A run that never reached `procnto up` for a harness reason (capture not running, a stuck shutdown) is repeated on the same image. A run that reached the host script is recorded as it happened, never replaced.

### 5.4 Deferred to the campaign

- The CPU-only small-model baseline in the guest (plan:392, :473).
- Linux or QNX guest boot time; IPC statistics; Linux-guest latency.
- The Linux guest under UEFI entry; `-P6`; guest RAM drawn from window 2 by construction (a guest larger than window 1).
- Sizing rungs on v1 (plan:416).
- To the first GPU stage, not the campaign: RT B6's GPU BAR0 read (§3.8) and any watch of the GPU range.

### 5.5 What S1 hands the freeze

Facts only.
- **Item 2:** whether B5 ran and passed.
- **Item 3:** kexec used; the UEFI path untested with qvm.
- **Item 4:** whether `_cpu-N` clusters were accepted; online CPUs in the guest on both legs.
- **Item 6:** window 2's range (provisional, D18); the GPU range kept out of every `add_ram`, shown by `gpu_in_sysram=no`; the canary ranges; B2's result; where guest RAM went, or "unknown" (Q14).
- **Item 7:** the Linux device set (pl011, virtio-console, no rng); whether any fixed guest wait appeared in the kernel log.
- **Item 10:** the Linux configuration pins `_cpu-1` to `_cpu-3`, so every v1 TCG twin leg that boots it needs at least four emulated CPUs (the existing launchers use `-smp 2`: `launch-m4tcg.ps1:306`, `scripts/launch-qhv-tcg.ps1:151`), or v1 needs a different pinning.
- **Manifest:** the `Image`, initrd, configuration and both FDT sha256s; the startup sha256 and line.

---

## 6. Procedure

**Conventions.** `PC$` is Git Bash; `PS>` is PowerShell; `L4T$` is the board over ssh with `ServerAliveInterval=3` under `timeout`. `<rec>` is `results/orin-native-port/<utc>/s1/`. Every bound is a wait bound set for this procedure.

### 6.1 T0: build and gates (PC, no QEMU)

1. **Inputs (after D3).** `s1/out/l4t/Image` and `initrd` hash as recorded on the board. `od` reads `MZ` at 0, `ARMd` at `0x38`, `text_offset` 0, `image_size` `0x029b0000`, flags `0xa` (our reading of a Linux header; not a QNX binary).
2. **Initrd.** `mkcpio.py --selftest`, then build from `initrd.manifest`. The output's sha256 is pinned.
3. **Configuration.** `parse-s1.py conf s1/s1-linux.conf` passes the allow-list.
4. **Startup.** Build with the `-b` change; `build-board.sh`'s symbol gate passes; record the new startup sha256 as `PIN_STARTUP_S1`.
5. **Generators.** `make-s1-images.sh --generate-only` (in a worktree with copied ignored inputs, per the M4 precedent), then a full build of `s1-m1b-p6`, `s1-h1`, `s1-n1`, `s1-n2` and `s1-d1`: every gate passes, including the constant and profile checks; `kshcheck --selftest` and `kshcheck` on each generated script; each `.params` has `guard_s` and `return_bound_s`.
6. **Tools.** `make -C orin-native/tools s1con memcanary` in the SDP environment, bounded; `memcanary --selftest` passes on the TCG host in T1's image. Then `git check-ignore orin-native/tools/s1con orin-native/tools/memcanary` must print both paths, and `git status --porcelain orin-native/tools` must list no binary.
7. **Only if D1 keeps the QNX guest** (before T3's optional `q2` rehearsal and before B0 stages `s1-q2`): compute D14's limit, "window 1 keeps the two-guest budget's non-guest share", from §3.3's table with the QNX rows restored; write it into the generator's geometry gate with its derivation as a comment; then build `s1-q2`, which must pass it.

### 6.2 T1: `dryrun` and FDT dump (TCG)

1. `PS> build-s1tcg-image.ps1 -Variant lin -Tag <t>`; canonical `qhv/host` and `qhv/guest` sums unchanged before and after.
2. `PS> launch-s1tcg.ps1 -Variant lin -Mode dryrun -QemuPath E:/qemu-versions/qemu-11.1.0/qemu-system-aarch64.exe`. One QEMU at a time; `-snapshot`; bounded.
3. The script: preflight, `mem`, md5 pre, `qvm-check`, then `bwait -k 60 -o … -e … -- qvm @/data/s1/s1-linux.conf set fdt-dump-file /dev/shmem/s1-fdt.dtb dryrun`, then the base64 export (m4dry's framing, `orin-native/m4dry/m4dry-host.ksh.in:112-126`, pipe-free), then `shutdown`.
4. `PC$ parse-s1.py run` decodes `qhv/s1tcg/attempt<N>/s1-fdt.dtb`, checks md5 and magic, and `parse-s1.py fdt` lists the checklist.
   - **Gating:** a memory node covering `0x80000000`/512 MiB; a GICv3 node; an `arm,armv8-timer` node with interrupts; a `virtio,mmio` node at `0x20000000` with interrupts; `/chosen/bootargs` equal to the configuration's cmdline; `linux,initrd-start` and `-end` inside guest RAM; a PSCI node (`compatible` containing `arm,psci`) with a `method` (the guest's panic reboot and its secondaries depend on it, §3.4, §3.6).
   - **Recorded:** the PSCI method value and version compatible; `cpu` nodes and enable-method; a pl011 node at `0x1c090000` and its clocks; `stdout-path`; `kaslr-seed`; the `interrupts` cells for `gic:37` and `gic:42` (which settles INTID against SPI numbering).
5. **T1 passes** on C3 plus every gating row. **2026-09-14:** C3 now also needs `rc=0` and no qvm `[file:line]` diagnostic (§14.9).

### 6.3 T2: boot to a shell (TCG)

`-Mode boot`: T1's steps in full (`mem` gate 596, md5 pre, `qvm-check`, the `dryrun` with `fdt-dump-file`, the export), then launch qvm with stdout on `/dev/ttyp2`, `stamp` on `/dev/ptyp2` (needles including `l_panic` and `l_rbfail`), ~~`s1con -O` on `/dev/ptyp3`~~ `s1con -O -R` on `/dev/ttyp3` (2026-09-14, C11's fallback, §14.9) with probe 1. Bounds (nested TCG, UNKNOWN speed, so generous), all from the launch: `l_kernel` 900 s (diagnosis only), `i_ready` 1,800 s, `shell_ok` 120 s after `i_ready`. Teardown, md5 post, the capped heads, the full streams, `shutdown`. **T2 passes** on L2, L4 and L5, with the same configuration sha256 as T1 and its own FDT sha256.

### 6.4 T3: the hold path (TCG)

`-Mode hold`: T2, then after `shell_ok` `memcanary hold -s 64` in the background, a 600 s hold with ten heartbeats, the trigger for the `hold` verify and probe 2, then teardown. It rehearses the script, the heartbeat loop, both trigger files and teardown. It is not pass item 4. **T3 passes** on the token list in §5.1 (TCG). **Optional, only after T0 step 7:** `-Variant q2`, rehearsing B5's order with the canonical QNX guest.

### 6.5 B0: pre-flight, staging and `p0` (board; owner present)

1. §8 in full.
2. `s1-board.sh stage <img>` for `s1-m1b-p6`, `s1-h1`, `s1-n1`, `s1-n2` (and `s1-q2` only after T0 step 7): resumable, sha256-gated.
3. `s1-board.sh p0 <img>` for each: `kexec -s -l`, `/sys/kernel/kexec_loaded`, the dynamic-debug landing line at `0x80080000`, `kexec -u`. Records the kexec tree's sha256.
4. **Fresh L4T before any quiesce:** `s1-board.sh reboot`, then wait for a new `boot_id`. Staging and `p0` ran on the old boot; the isolate and `rmmod` run only on a freshly booted L4T (M3's retry lesson). The same applies before B3 in the second session.
5. PowerShell COM3 capture started with the lifetime M4 requires (m4-design.md:1268).

### 6.6 B1: option-off regression (`s1-m1b-p6`)

M1b's `m1b-p6` buildfile, byte for byte, with the new startup and no `-b`. `s1-board.sh run` with the quiesce and governor pin. B1 is exempt from L0, L7 and pass item 5: it runs no S1 host script, so it prints no `S1` line. **B1's tokens:** `T234-SHIM EL=2` with `PC=0000000080080000`; `t234: WDT0 CR=`; M1b's `T234 m1b-p6 -P6: procnto up` (the generator's form, `make-m1b-images.sh:420`) and M1b R2's other markers; none of `t234: ram w2`, `t234: gpu range`, `t234: canary`, `BAD-LANDING`, `EXC `, `EL!=2`; M1b's reset line; on L4T a new `boot_id`, `MAINSWRST` and the bootloader slot unchanged. **Pass:** those tokens, and the normalised black box equals M1b R2's apart from startup-size-dependent addresses (m3-design.md:1091). The run note stamps only the startup sha256 and the kimg sha256.

### 6.7 B2: the host with window 2 (`s1-h1`, no qvm)

Startup line `… -m992M -Wkeep -A -b w2,canary -Dtcu`. Script mode `host`: preflight; `mem boot` and `S1 W2 reflected`; `memcanary asinfo`; `pidin syspage=asinfo` capped; `memcanary verify` c1-c3; `alloc -s 1536`; `bwait -s 60`; `verify` c1-c3; `mem end`; reset. **Pass:** L0 (including the three startup `filled` lines), `reflected=yes`, `S1 ASINFO sysram_w1=yes sysram_w2=yes s1canary=3 canary_in_sysram=no gpu_in_sysram=no`, all six `verify=ok`, `S1 ALLOC mib=1536 … verify=ok`, L7. The GPU BAR0 read of RT B6 is not folded in (§3.8). This closes plan:868 and K5's claim-side half; the hidden-firmware-user half stays HYPOTHESIS beyond one run.

### 6.8 B3: native boot (`s1-n1`)

Mode `boot`, the board profile of T2: L1 (`mem` gate 596, `S1 ASINFO`, canary verify), native `dryrun` and export in L2, launch, L3-L5, `S1 GUESTRAM` (Q14), teardown, verify, exports through `tcu-cat -a 50 -T <send> -s -f`, reset. Bounds, all from the launch: `l_kernel` 240 s (diagnosis only), `i_ready` 480 s, `shell_ok` 60 s after `i_ready`. `l_rbfail` or `l_panic` ends the waits at once. **Pass item 2** per §5.2.

### 6.9 B4: the ten-minute run (`s1-n2`)

Mode `hold`: B3 plus the hold, with the `mem` gate at 852. After `shell_ok`, start `memcanary hold -s 256` in the background and wait for its `fill=ok` (60 s bound); `S1 HOLD start`; ten times: `bwait -s 60`, `pidin -p qvm -f abNli` into a file, check `qvm.rc` absent, print `S1 HB k=…`. Then `mem hb10`, trigger probe 2, wait `end_ok` 60 s, `S1 HOLD end`, trigger the `hold` verify and wait for its done file (120 s bound), canary verify, teardown (`slay -f -Q qvm` sends qvm's power-button signal; SIGKILL after 15 s; which one ended qvm is recorded), verify again, md5 post, exports, reset. The guest is idle apart from the heartbeat, so the load is light, but the owner stays at the plug.

### 6.10 B5: two guests (`s1-q2`, only if D1)

Mode `q2`: FreeMem gate (§4.5); Linux to `shell_ok`; then M3's QNX sequence to `banner` and the IPC client's completion; `S1 BOTH alive`; teardown of both; M3's md5 and `cmp` checks plus S1's. **Pass item 3:** completion only.

### 6.11 Return and records

`s1-board.sh run` fetches the black box, `reset_reason`, pstore listing and new `dmesg-ramoops` records, and `sudo -n nvbootctrl dump-slots-info`, compared with the session's first reading (a difference is F30); copies COM3; runs `extract` and `consistency`. The PC runs `parse-s1.py run` into `<rec>/<step>/parse-s1.txt`. The run note, `r/s1-runs.md` on the local branch only, holds: the date and UTC of each kexec; L4T release; every sha256 of §5.2 item 5; the image and params names; the tiers reached; the pass verdicts; `reset_reason`; the recovery class of any failure; deviations. No durations.

### 6.12 Order, gates and bounds

| Step | Pass means | Then | On fail |
|---|---|---|---|
| T0 | every gate | T1 | fix; rerun |
| T1 | C3 plus gating FDT rows | T2 | §5.3; QNX support if no configuration helps |
| T2 | L2, L4, L5 | T3 | §5.3 stages |
| T3 | §5.1's T3 token list | B0 | fix the script; rerun T3 |
| B0 | §8; `p0` for each image; a fresh `boot_id` | B1 | stop |
| B1 | §6.6's tokens and the normalised black box equal | B2 | revise the startup change; T0 |
| B2 | §6.7 | B3 (after a fresh L4T boot) | §5.3: a defect is fixed and rerun; data is kill condition 1 and stops S1-F (D8) |
| B3 | item 2 | B4 | §5.3; `s1-d1` diagnostic; its terminal rule (D17) |
| B4 | item 4 | B5 or record | §7 |
| B5 | item 3 | record | §7 |

**Guard and return bounds** (design estimates from M4's rule, C14; the generator computes the exact values from its bound table):

| Image | ksh worst case, main terms | Guard | Return bound |
|---|---|---|---|
| `s1-m1b-p6` | M1b's | M1b's | 1,200 s (`m3-board.sh:41`) |
| `s1-h1` | preflight 30, canaries 210, `alloc` 125, hold 60, asinfo and slog 35 | 900 s | 1,200 s |
| `s1-n1` | preflight 30, canaries 210, md5 130, `qvm-check` 15, `dryrun` 65, export prep 45, needle waits 540, teardown 30, sends 92, slog 20 | 1,800 s | 2,100 s |
| `s1-n2` | `s1-n1` plus hold 600, probe 2 60, `hold` fill and verify 180 | 2,400 s | 2,700 s |
| `s1-q2` | `s1-n1` plus M3's QNX window and IPC | 2,400 s | 2,700 s |

B1-B5 fit two attended sessions: B0-B2, then B3-B5. A session stops at the first failed gate. Every rung starts under both of the harness's uptime limits, carried over from `m4-board.sh`: 7,200 s for any kexec run (`:51`, `:829`) and 1,800 s when the run includes the quiesce (`:52`, `:833`). Every S1 board rung includes the quiesce, so `s1-board.sh reboot` and a new `boot_id` precede each rung whose L4T uptime is over the second limit. Overriding either limit is forbidden (§7.3).

---

## 7. Recoverability and failure signatures

### 7.1 Guarantees and residuals

**By construction, S1 cannot:** write QSPI, the BCT, the ESP, NVRAM or a boot variable; change which OS boots by default; give a GPU, SMMU or any passthrough to the guest; claim CMA, ramoops, the black box, the GPU range or the ranges `init_raminfo.c:45-58` names; write physical memory from user space (`memcanary` has no write mode and addresses only its three compiled names, each checked against the syspage, §3.8); or fill a canary that overlaps the image, the kexec tree, the shim page, the black box or the GPU range (startup refuses first, §3.3).

**Residual, as in M3 and M4:** after kexec, a hang with interrupts masked, or a guard that never fires, costs a power cycle and that run's black box. WDT0 does not fire after kexec (plan:879). Whether a switchable plug exists is UNKNOWN (plan:886), so the owner cuts power by hand. Nothing drives the fan (m4-design.md:1328).

**Recovery classes:** SR (the image or guard resets; L4T returns); SR-bb (as SR, and the black box is the record); PP (power cycle; COM3 is the only record; allowed only under §2 rule 6a); X (reflash): designed out.

**Designed out: the paths to a reflash, and the rule that prevents each**
- Bootloader slot failover from unvalidated boots: §2 rule 6a, §7.3, and the `nvbootctrl` reading after every return (F30).
- A write to QSPI, the ESP or a boot variable: §2 rule 5; no S1 step makes one.

### 7.2 Failure-signature table

**PC**

| # | Observable | Meaning | Next step |
|---|---|---|---|
| F1 | T0 geometry gate fails | IFS over the cap | Check the initrd size; Linux only must pass |
| F2 | `S1 DRYRUN saved=no`, a logger `error` naming `load` | `Image` not recognised (C4) | `guest load`; then QNX support |
| F3 | Logger error naming `cluster` | `_cpu-N` not accepted | Bare `cpu` lines; re-pin; rerun T1 |
| F4 | Logger error naming `hostdev /dev/ttyp3` | slave rejected | C11 fallback; rerun T1. **2026-09-14:** seen in T1 attempt 1 as `[/data/s1/s1-linux.conf:14] Unable to open '/dev/ttyp3': Interrupted function call`, and the fallback is adopted (§14.9). The same form naming `/dev/ptyp3` leaves no fallback in this design |
| F5 | FDT decodes, a gating row missing | Generated tree unusable as-is | Record; a non-GPU `fdt load` overlay only under D19, which changes the configuration and reruns T1; otherwise D17 |
| F6 | T2: no `l_kernel` by its bound | Kernel not entered | §5.3 stage 1 |
| F7 | `l_kernel`, then `Kernel panic … VFS` or `No working init found` | Initrd not found, or `/init` or its interpreter missing | `s1-d2`; check the manifest's symlinks |
| F8 | `i_ready`, no `shell_ok`, the probe echo visible | Shell not reading, or `$(( ))` absent | Check applets; ~~C11 fallback~~ (in use since 2026-09-14, §14.9) |
| F9 | `i_ready`, no `shell_ok`, no echo | Input not reaching the guest | ~~C11 fallback~~ **2026-09-14:** the fallback is already in use (§14.9); read `s1con`'s write records and any raw-mode error line |

**Board**

| # | Observable | Meaning | Class | Next step |
|---|---|---|---|---|
| F10 | No `T234-SHIM` by the return bound | Hang before the shim, or capture not running | PP under §2 rule 6a: with a running capture and no firmware banner, F25a; with no capture, F25b's rule | M3's rows |
| F11 | `BAD-LANDING` | kimg not at `0x80080000` | SR | K1 (`M3_KEXEC=c` equivalent) |
| F12 | `t234: -b… is not` crash | Option typo | SR | Fix the generator's argv check |
| F13 | Crash or silence right after `t234: ram w2`, `t234: gpu range` or a `t234: canary` line | The allocator, `startup_io_map`, syspage or MMU setup rejects RAM above 4 GiB, or the fill faulted | SR or PP (rule 6a) | Stop B2; §5.3's defect path. Record the last line |
| F14 | `S1 W2 reflected=no`, or `S1 ASINFO sysram_w2=no` | Window 2 not in the allocator | SR | A defect: read the asinfo record; fix; rerun B2 |
| F15 | `S1 CANARY … refuse=…`, or a `verify` map error | A canary reached `sysram`, has no entry, or `mmap_device_memory` refuses the range | SR | A defect: revise startup or the tool (for example `mmap64` with `MAP_PHYS`); rerun B1 if startup changed, then B2 |
| F16 | `S1 ALLOC … verify=bad` | Window-2 pages do not hold data | SR | Data: kill condition 1 (C1, D8); stop all board work; K5's hidden-user hypothesis |
| F17 | B1 black box differs | The option-off path changed startup | SR | Revise; T0 |
| F18 | TCG passed; board `S1 DRYRUN` logger error | Board host tree or registers | SR | Compare with T1's logger lines; `s1-d1` |
| F19 | Board `l_kernel` absent, qvm alive | Guest entry fault on A78AE | SR at teardown | `s1-d1` (`unsupported abort`) |
| F20 | `l_kernel`, then an `Unhandled`/`undefined instruction` oops | An unsupported register (D11) | SR | Record ESR text; D11; a configuration change reruns T1-T2 |
| F21 | `qvm.rc` before teardown, `l_panic` | Guest panic, `panic=-1` rebooted it | SR | Read the capped tail and COM3 stream |
| F22 | A heartbeat missing, qvm alive | Host script stalled or qvm hung | SR at guard | Record the last `S1 STATE` |
| F23 | `S1 CANARY … verify=bad` | A write into a watched range | SR | Item 4 not met; stop board work until explained (RT:246) |
| F24 | `BWAIT guard deadline … expired` | A bound missing | SR-bb | Fix before the next run |
| F25a | Not back by the return bound; COM3 not growing for 5 minutes; its last output is startup, QNX, qvm or guest text, with no firmware banner after the image's reset | Hang in the image, possibly busy vCPUs and no fan. L4T's boot option had started before kexec | PP | Read COM3 and record the last line; pull power; let L4T boot; reboot once more before any next run |
| F25b | A firmware banner appeared after the image's reset, and L4T has not answered by the return bound; or no capture was running | A stop in the firmware or before a validated boot | PP only under M5's exception (§2 rule 6a): 10 minutes with no COM3 byte, last output not a menu or prompt, no ssh; one cut; hands-off boot | If that boot also stops, board work stops and the owner decides. Never a second cut |
| F26 | B5: Linux `shell_ok`, no QNX `banner` | Two VMs on four cores, or memory | SR | Record FreeMem gate lines; owner |
| F27 | L4T back with a new `dmesg-ramoops` | Linux Oops in its shutdown | — | Record; M3's uptime rule |
| F28 | `S1 ALLOC … map=fail errno=…` (`alloc` or `hold`) | The allocation could not be made: ENOMEM, a per-process limit, or a tool defect | SR | Diagnose before D8: compare with the `S1 MEM` gate line and the `S1 ASINFO` line. Not kill condition 1 unless asinfo and FreeMem show window 2 present and the map still fails after a tool fix |
| F29 | `STAMP l_rbfail` | The guest panicked and its reboot failed: no restart handler, so a vCPU spins with qvm alive | SR (the script tears down at once) | Check the dump's PSCI node and method; item 2 or 4 not met for that run |
| F30 | `nvbootctrl` reads another current or active bootloader slot, or a changed status | Boot-chain failover | **X**, designed out by §2 rule 6a | Stop all board work. Follow NVIDIA's A/B documentation; reflash only as the last resort (m5-design.md F33) |
| F31 | `t234: canary cN overlaps …`, then a reset | A constant or the landing moved: a canary would cover the image, the tree, the shim, the black box or the GPU range | SR | No write happened. Fix the constant or the image; T0; rerun B1 if startup changed |

### 7.3 Never

- Load a `pass` line, a `smmu` vdev or any GPU node in an S1 configuration; or an `fdt` overlay, except a non-GPU overlay D19 has approved by hash.
- Add a range to `add_ram` other than windows 1 and 2; widen window 2 into the GPU range, CMA or above; or resize it without rerunning B1 and B2.
- Add a physical write mode or an address argument to `memcanary`, or call `memcanary asinfo` or `verify` in a TCG script.
- Cut power between the image's reset and a validated L4T boot, except under M5's exception (§2 rule 6a); cut power a second time under that exception.
- Override `s1-board.sh`'s uptime limits (7,200 s; 1,800 s with the quiesce), or run a quiesce on an L4T that was not freshly booted.
- Run a board S1 rung without the owner at the plug, or while the owner is away (the unattended-run rule).
- Read GPU MMIO from the host in any S1 image (§3.8, plan:465).
- Install a package on the board, or download a kernel source tree, as a step of S1 (D16).
- Commit `Image`, the initrd, a host IFS, a kimg, a `.sym` or a dumped FDT.

---

## 8. Pre-flight checklist (B0)

**PC**
1. T0-T3 passed; their record names go in the run note.
2. `s1/out/l4t/Image` and `initrd` sha256 equal the values recorded at D3's copy; `s1-linux.conf` sha256 equals T2's.
3. Every image's `.params` exists; `kshcheck` passes on each generated script.
4. No other workflow uses the board or COM3; no QEMU is running.

**Board, read-only**
5. `/etc/nv_tegra_release` reads R36, REVISION 4.7; `sha256sum /boot/Image /boot/initrd` equal item 2's.
6. `/proc/iomem`: `100000000-25e20dfff` System RAM and CMA at `24a000000` as in 11c; no reservation inside `0x100000000-0x249ffffff`. Any change: stop.
7. `od -An -tx1 /proc/device-tree/reserved-memory/ramoops_carveout/reg` gives `0x2_725F_0000`, `0x200000`.
8. Uptime under both harness limits: 7,200 s for a kexec run and 1,800 s with the quiesce (`m4-board.sh:51-52`, `:829-834`); every S1 rung uses the quiesce, so the second governs, and B0 step 4 reboots after staging. `/etc/default/kexec` still `LOAD_KEXEC=false`.
9. The read-only kernel-config items of D3, if not yet read: `CONFIG_CMA`, `CONFIG_CMA_SIZE_MBYTES`, `CONFIG_ACPI`, `CONFIG_PANIC_TIMEOUT`, `CONFIG_INITRAMFS_SOURCE`.

**Bench and session**
10. COM3 wiring as M0-M4: RX on J14 pin 4, GND on pin 7, no TX (BF).
11. DC power within reach; the owner present from B0 to the last return (D15).
12. `<rec>` exists under an ignored `s1/` directory; `git check-ignore` passes for a test name in it, and for `orin-native/tools/s1con` and `orin-native/tools/memcanary`.
13. `sudo -n nvbootctrl dump-slots-info` is recorded before the first rung: the current and active bootloader slot and its status. Every return is compared with it (§6.11, F30). A "Capsule update status" value equal to this reading is the board's steady state (m5-design.md:978).

---

## 9. Risks: every HYPOTHESIS or UNKNOWN the design rests on

| # | Assumption | Class | Answered by |
|---|---|---|---|
| R1 | qvm recognises the EFI-stub arm64 `Image` with a bare `load` | UNKNOWN (QH `vm/load.html` generic) | T1 |
| R2 | `set fdt-dump-file … dryrun` works after `@conf` on the command line | VENDOR_CLAIM (variables page example) | T1 |
| R3 | The generated FDT has memory, GIC, timer, virtio-mmio, `/chosen` bootargs and initrd nodes usable by 5.15 | UNKNOWN | T1, B3 |
| R4 | `cmdline` reaches `/chosen/bootargs` | VENDOR_CLAIM (`fdt-cmdline-policy` text) | T1 |
| R5 | `initrd load` passes a gzip cpio unchanged, and 5.15 unpacks it | HYPOTHESIS (`RD_GZIP=y`, BF) | T2 |
| R6 | The L4T 5.15-tegra kernel boots on a generic tree with no Tegra nodes | HYPOTHESIS (upstream apbmisc bails on non-Tegra; NVIDIA's fork not read) | T2, B3 |
| R7 | `earlycon=pl011,0x1c090000` works on qvm's pl011 vdev | HYPOTHESIS (QNX's own example uses it) | T2 |
| R8 | The virtio port becomes `hvc0` | HYPOTHESIS (`HVC_DCC` not built; hvc index not read in source) | T2 |
| R9 | ~~qvm accepts a pty slave as virtio-console `hostdev`~~ **2026-09-14:** qvm accepts the pty master `/dev/ptyp3` as virtio-console `hostdev` (it could not open the slave in T1 attempt 1, §14.9), and input reaches the guest through the raw slave | UNKNOWN | T1 attempt 2 (the dryrun), T2 |
| R10 | Ubuntu's initramfs busybox has `sh`, `mount`, `echo`, `sleep`, `uname` and `$(( ))` | HYPOTHESIS | T0 (applet list from the manifest build), T2 |
| R11 | The initrd's `/lib` usrmerge links can be reproduced from the source cpio | HYPOTHESIS | T0 |
| R12 | `cpu cluster _cpu-N` is accepted, and `_cpu-3` exists under `-smp 4` on TCG | UNKNOWN / VENDOR_CLAIM | T1 |
| R13 | `startup-qemu-virt` gives the TCG host enough RAM for a 512 MiB Linux guest | HYPOTHESIS (QEMU `-m 2G`; OPT_RAM 1G, qhv/host/local/options) | T1's `mem` gate |
| R14 | `psci-supported auto` finds PSCI on both host trees, so secondaries start | HYPOTHESIS | T1, B3 |
| R15 | A78AE exposes no system register a 5.15 guest touches that qvm's `register fail` default turns into an oops | UNKNOWN | B3 |
| R16 | `add_ram` above 4 GiB works in startup, syspage, `init_mmu` and procnto on this board | UNKNOWN (plan:868) | B2 |
| R17 | No firmware or BPMP user of window 2 hides from `/proc/iomem` (K5) | HYPOTHESIS | B2, B4 canaries (one run each) |
| R18 | `mmap_device_memory` maps 16 MiB of an `s1canary` range outside `sysram` read-only, including above 4 GiB | HYPOTHESIS | B2 |
| R19 | `pidin syspage=asinfo` prints the sysram entries | HYPOTHESIS (view name unread, Q3); supplementary only, `S1 ASINFO` is the gate | B2 |
| R20 | The smaller kimg lands at `0x80080000` | HYPOTHESIS (M3's larger one did) | B0 `p0`, B3 |
| R21 | A native Linux boot to `i_ready` stays inside 480 s of bounds | HYPOTHESIS (design bound) | B3 |
| R22 | The black box stays under 60,000 B with the capped heads | HYPOTHESIS (m3-design.md:859-879) | T3 (text size), B3 |
| R23 | `tcu-cat` sends the full streams inside the send bounds | HYPOTHESIS (M4 precedent) | B3 |
| R24 | Guest idle during the hold keeps heat within limits with no fan | HYPOTHESIS | B4, owner present |
| R25 | Two qvm instances on four cores let the QNX guest's banner and IPC complete | UNKNOWN (no two-VM precedent) | B5 |
| R26 | A re-derived geometry limit leaves window 1 enough for the host in B5 | HYPOTHESIS | B5 FreeMem gate |
| R27 | The qvm-generated FDT is our evaluation output, not a QNX-shipped binary, so decoding it is allowed | HYPOTHESIS (licence reading) | D12, owner |
| R28 | The TCG FDT differs from the board's, so it cannot stand in for it | HYPOTHESIS | T1 against B3 |
| R29 | No virtio-rng leaves the initrd shell unblocked | HYPOTHESIS | T2 |
| R30 | The `data_files.custom` data partition grows to hold `Image` and initrd | HYPOTHESIS (`OPT_PART_SIZES=full`) | T1's build text checks |
| R31 | The pl011 needles' texts, `Booting Linux on physical CPU` and `Run /init as init process`, match 5.15-tegra's output, and earlycon delivers them | HYPOTHESIS | T2 (their absence fails nothing; L3 is diagnosis only) |
| R32 | `Reboot failed -- System halted` is the text 5.15-tegra prints when a restart fails | VENDOR_CLAIM (LX v5.15 `machine_restart()`); NVIDIA's fork not read | desk only; no step provokes a panic |
| R33 | QNX support is reachable under the NC QDL evaluation licence, and sending it run output is compatible with 4.6(i) | UNKNOWN | D17 |
| R34 | The Linux-only window-1 budget (§3.3, C9) leaves 596 MiB free before launch | HYPOTHESIS | L1's gate on T1 (TCG), B3 |
| R35 | The same guest-physical addresses work in the Linux and QNX configurations side by side | HYPOTHESIS (§3.7) | B5 |
| R36 | The Linux-only IFS is about 52 MB and passes the unchanged geometry gate | HYPOTHESIS (§4.4) | T0's geometry gate |
| R37 | One QNX process can map and touch 1,536 MiB of anonymous memory | HYPOTHESIS | B2 (F28 separates it from window 2) |
| R38 | `alloc_ram` plus an `s1canary` asinfo entry keeps procnto and qvm off the canaries; no component allocates from a named RAM entry other than `sysram` | HYPOTHESIS (source read for startup; procnto not read) | B2 `S1 ASINFO` and verify; B4 verify |
| R39 | `startup_io_map` of 16 MiB above 4 GiB works before `init_mmu`, as the black box's 64 KiB map does | HYPOTHESIS (`hw_sertcu.c:72` precedent) | B2 (F13) |
| R40 | Syspage `asinfo` is readable from user space with the documented `SYSPAGE_ENTRY` macros | VENDOR_CLAIM (QNX `syspage` documentation) | T0 (`memcanary asinfo` on the TCG host, output only; no verify), B2 |
| R41 | A host-side view shows the physical pages behind qvm's guest RAM | UNKNOWN | Q14 |
| R42 | The PSCI node qvm generates on both hosts makes `SYSTEM_RESET` end qvm | HYPOTHESIS (QH `start/guest_stop.html`) | T1 node gate; a reset is not provoked |

---

## 10. Must not be claimed from a pass

- **No timing,** latency, rate, boot time, IPC statistic or CPU-model performance, and no FreeMem value.
- **No isolation claim.** Stage-2 containment is qvm's design and was not tested. Not SMMU containment, not DMA isolation (the GPU's DMA is CPU-physical with no SMMU even under L4T, RT:54; the other masters are untranslated after kexec, RT:81), and not freedom from interference between guests or between a guest and host processes.
- **Not that the guest's RAM came from window 2,** unless `S1 GUESTRAM` shows it, and nothing about a guest larger than 512 MiB or at the owner target's size.
- **Not full memory integrity.** The canaries watch three 16 MiB ranges from startup on, one host allocation during the hold, and the payload files, for one run. Nothing before startup's fill is watched.
- **Not that the quiesce frees RAM** (plan:861), and not that window 2 has no hidden user beyond the runs made.
- **Not that a TCG pass predicts a native pass,** or that TCG exercised A78AE, board PSCI, the second window or physical pinning (m4-design.md:1436-1442).
- **Not repeatability** beyond the runs made; not a supported configuration of QNX or NVIDIA; not certified, not any ASIL or ISO 26262 property; not equivalence to DRIVE OS.
- **Not a GPU result,** and nothing about S2-S5.
- **Not publishable** before the 4.6(i) consultation.

---

## 11. Owner decisions

**2026-09-13 (owner): all nineteen taken as recommended.** In particular:
- D10 tightens plan item 4 to require `end_ok`.
- D12 accepts R27's reading: the dumped FDT is our private evaluation output.
- D15 confirms presence and the two-session split.
- D17 routes any QNX support request through the supervising professor first.
- D2's I-b and D16's downloads still need the owner's approval at the time they would be used, as their recommendations say.

| # | Decision | Options | Recommendation and reason |
|---|---|---|---|
| D1 | Guest set for S1-F, and when freeze item 2 is settled | Linux only; QNX plus Linux; Linux only now, B5 if v1 keeps the QNX guest. Timing: settle freeze item 2 before B4's record closes, or record S1-F as provisionally met and settle it at the freeze (§5.2) | **The third, and settle freeze item 2 before B4 closes if the owner can.** It tests items 1, 2, 4 and 5 without prejudging item 2, and B5 reuses the same Linux bytes. Settling early avoids a provisional met line. The owner's target has no QNX guest (RT:342) |
| D2 | Initrd, and I-b's board-side build | I-a copied busybox and libraries; I-b static init built on the board; I-c stock initrd; `busybox-static` download | **I-a.** No download, stock bytes, and a real shell. I-c stays a TCG diagnostic. **I-b only with the owner's explicit approval at the time,** because it writes to L4T's rootfs (§3.5 names the directory and the removal check). The download only if I-a and I-b both fail |
| D3 | Inputs from the board | an owner-run `scp` of `/boot/Image` and `/boot/initrd`, plus the §8 item 9 config reads and `ls /usr/lib/aarch64-linux-gnu/libc.a`; or the R36.4.4 BSP's `kernel/Image` on the PC | **The board copies.** The plan names the R36.4.7 `Image` (plan:460); the local BSP is R36.4.4 |
| D4 | Guest CPUs | 3 vCPUs pinned to cores 1-3 at `-P4`; 2 vCPUs; 1 bare vCPU; `-P6` with cluster 1 | **3 pinned at `-P4`.** It matches the owner's target within cluster 0; cluster 1 waits for freeze item 4. Fallback: bare lines if `_cpu-N` fails |
| D5 | TCG rehearsal launcher | `-smp 4` in `launch-s1tcg.ps1` only, stamped; keep `-smp 2` with bare `cpu` lines | **`-smp 4`, S1-only.** It keeps the configuration byte-identical; the twin launchers stay untouched (freeze item 10) |
| D6 | Entry path for S1-F | kexec; UEFI | **kexec.** The proven loop; UEFI needs a TX refit, a loader rebuild and an unchecked window-2 map |
| D7 | Second window and canaries | a `-b w2,canary` board option that uses `alloc_ram`, an asinfo entry and a startup fill; `-r` startup tokens; window 1 only | **`-b`.** `-r` and `avoid_ram` leave a range in `sysram` (C15), so only `alloc_ram` in the board keeps the canaries from procnto; filling in startup starts the watch before procnto and removes every physical write from user space |
| D8 | If B2 fails on data (§5.3) | stop S1-F and record kill condition 1 for the 11c candidate; commission a new range derivation from the three-boot `/proc/iomem` comparison, as a new design revision that reruns B1 and B2 | **Stop and record.** 11c found one candidate; another range is new design work, not a retry. A defect is fixed and rerun without a decision. No window-1-only continuation is offered: item 4's layout, B5 and freeze item 6 need window 2 |
| D9 | Shell rule | host-injected probe required; scripted `/init` output enough | **Probe required.** A shell that never read a line is init's script |
| D10 | Item 4 liveness | require `end_ok` too; qvm alive only (plan text) | **Require `end_ok`.** qvm alive does not mean the guest is alive. This tightens the plan's item and needs the owner's approval |
| D11 | `unsupported` policy | qvm's defaults; the SDP template's `ignore` | **Defaults.** A fault is visible; `ignore` could hide a real problem. A board-only fault reruns T1-T2 with any change |
| D12 | FDT decoding and its licence status | our stdlib reader; install `dtc` (a download) | **The stdlib reader.** Also confirm R27: the dump is private evaluation output, decoded as our own data |
| D13 | Configuration gate | a new S1 allow-list; extend TCR-CFG-001's `g2.conf.allow` | **A new allow-list.** The QNX guest's gate stays as reviewed; S1's keywords are a separate surface |
| D14 | B5 geometry, if D1 keeps the QNX guest | re-derive the limit; gzip'd disk; separate kexec segment | **Re-derive.** Every guest byte stays pinned; `p0` re-checks the landing |
| D15 | Presence and schedule (a confirmation; §2 rule 6 already requires presence) | confirm the owner at the plug from B0 to the last return; confirm the two-session split (B0-B2, B3-B5) and a start time that leaves each session's return bounds inside the owner's day | **Confirm both.** No recovery without a power cut (m4-design.md:1396) |
| D16 | Optional downloads | QNX Hypervisor 8.0 Known Issues (Download Center); Jetson Linux R36.4.7 public_sources only if T2 stalls before `l_kernel` with a valid FDT; `busybox-static` per D2 | **None up front.** Each only on its named trigger |
| D17 | Kill condition 2: QNX support | whether a support channel is used at all under the evaluation licence; what may be sent (the configuration and our own source only; or also logger lines and the dumped FDT, which are 4.6(i) evaluation output); the time box; who declares "cannot fix" | **One request, with the configuration, our own source and the exact logger lines, after the supervising professor agrees that sending evaluation output to the licensor is not publication; a 10-working-day time box from the first reply; the owner alone declares "cannot fix", recorded in `r/s1-runs.md` as kill condition 2.** It closes the plan's kill condition with a named end instead of an open wait. If no channel exists (R33), the owner declares at once |
| D18 | Window 2 size and the GPU range kept out (plan:463, freeze item 6) | window 2 = `0x100000000`/2,208 MiB with the GPU range `0x18A000000`/3,072 MiB kept out; the whole 5,280 MiB candidate as window 2 and no named GPU range; a smaller GPU range | **The first, provisional for freeze item 6.** The plan requires a GPU range out of every `add_ram`; 3,072 MiB is the research track's upper bound (RT:353), so the freeze can only grow window 2. Window 2 still holds the target's 2,048 MiB guest (RT:352). Any resize reruns B1 and B2 |
| D19 | A non-GPU FDT overlay, if T1's generated tree lacks a gating node | forbid, and go to D17; allow one overlay adding only the missing non-GPU node, approved by its sha256, on both legs | **Allow under approval.** An overlay that supplies a PSCI, timer or memory node is ordinary guest configuration, not scope growth; it stays in the pinned configuration on both legs, so item 2's identity holds. GPU nodes stay forbidden (plan:464) |

---

## 12. Open questions, ranked by cost

**Desk, no QEMU**

| # | Question | Closes by |
|---|---|---|
| Q1 | The exact Ubuntu busybox applet list, and the `/lib` link layout inside `/boot/initrd` | T0's manifest build from the copied initrd |
| Q2 | Whether mkqnximage has an `ifs_files.custom` for the host, as the guest build uses one (`scripts/build-qhv.bat:77`) | `mkqnximage --help` text; only needed if `/data/s1` fails R30 |
| Q3 | `pidin` view names for the syspage `asinfo` section | QNX `pidin` documentation |
| Q4 | QNX Hypervisor 8.0 Known Issues for Linux guests | D16 |
| Q14 | A QNX host view (`pidin mapinfo`, `/proc/<pid>` mappings, or a qvm option) that shows the physical addresses behind qvm's guest RAM; if one exists, B3 and B4 print `S1 GUESTRAM` from it | QNX `pidin` and QH documentation |
| Q15 | The documented `SYSPAGE_ENTRY(asinfo)` walk and the `asinfo` string-table access `memcanary` needs | QNX `syspage` documentation (R40) |

**PC, TCG**

| # | Question | Closes by |
|---|---|---|
| Q5 | R1, R2, R3, R4, R12, R13, R14: the `dryrun` and the dump | T1 |
| Q6 | R5-R10, R29: the boot and the probe | T2 |
| Q7 | Nested-TCG Linux boot bounds and the stream sizes | T2, T3 (never reported) |
| Q8 | `gic:N` numbering: INTID or SPI index | T1's `interrupts` cells |

**Board, read-only**

| # | Question | Closes by |
|---|---|---|
| Q9 | `CONFIG_CMA_SIZE_MBYTES`, `CONFIG_ACPI`, `CONFIG_PANIC_TIMEOUT`, `CONFIG_INITRAMFS_SOURCE`; `libc.a` presence | D3, §8 item 9 |

**Board runs**

| # | Question | Closes by |
|---|---|---|
| Q10 | R16-R19: RAM above 4 GiB, the mapping tool, the asinfo view | B2 |
| Q11 | R15, R20, R21, R22, R28: the native boot | B3 |
| Q12 | R24, R17 over a longer window | B4 |
| Q13 | R25, R26 | B5 |

---

## Appendix A. Stale text to correct later (list only; the orchestrator edits docs and other records)

**`docs/orin-native-port-plan.md`**
- **plan:472, kill condition 1:** "no second window can be shown free after `rmmod`". 11c showed the quiesce frees no window (C1).
- **plan:463, prerequisite (b):** "after the `rmmod` quiesce, `/proc/iomem` shows a second RAM window free". The same point; its own 2026-09-13 note already says so.
- **plan:182:** three `rmmod` names; the procedure uses four (C13).
- **plan:470, item 4:** "memory canaries" has no definition in the plan; §3.8 is one.
- **plan:479, freeze gate item 1:** "S1-F have passed" should allow the provisional met line of §5.2 when freeze item 2 chooses Linux only, and require B5 before the freeze otherwise.
- **plan:463, prerequisite (b):** "A GPU range stays out of every `add_ram`" names no range; D18 proposes one.

**Other files**
- **`CLAUDE.md:69-70`:** VM1, the Linux Compute proxy, "Phase 3 / Orin only (L4T native)". S1 adds a Linux guest under native qvm, and v1's TCG legs would carry it (plan:339-340, :519).
- **`docs/digital-twin-design.md:46`, `:52`:** "no Linux guest on the cloud leg" is right for A1 and stale for v1's TCG legs.
- **`scripts/qhv/g2.conf.allow:5`:** says `post_start.custom` runs the validator before qvm; the committed snippet does not (C7). **2026-09-14:** corrected, comment only.
- **`board/init_raminfo.c:27-29`:** the widening rule names a post-quiesce `/proc/iomem` read; it is edited with the `-b` change (§4.3).
- **`orin-native/shim/build-shim.sh:12`:** its "2 MiB" comment is stale (r/research-kexec-tcu.md:397-420).
- **RT (branch `research/gpu-passthrough`):** §7 option A frames the target as a QNX safety guest plus a Linux guest, against its own §6.0; "Before S1: run G1-G3" and the GPU-overlay G2 (RT:320) against the owner's no-GPU `dryrun` (plan:465); B5's range `0x100000000-0x25e20dfff` (RT:235) includes the CMA pool, where 11c's usable span ends at `0x249ffffff`; C18 cites plan:268 (now :285); C50 cites `CLAUDE.md:185` and plan:65 (now `CLAUDE.md:209`, plan:75-76).
- **`r/m5-design.md:380`:** cites plan:441 for the entry-path item (now plan:481).
- **`r/m3-design.md:1024`:** cites plan:169 for the `rmmod` list (now plan:182).

---

## 13. Review outcomes (revision 2)

Three review lenses read revision 1: technical, safety and completeness. They raised 30 findings: one blocker, 13 major and 16 minor. Each was checked before its disposition was chosen, against revision 1's own text and:
- the startup library, read locally: `lib/ram.c` (`avoid_ram`, `alloc_ram`, `add_ram`, `add_sysram`, `reserve_ram`), `lib/_main.c:120-158`, `lib/init_system_private.c:305`, `:319`, `lib/common_options.c:135-143`, `lib/fdt_init.c:44-49`, `lib/public/startup.h:539-540`;
- our own source: `board/main.c:140-310`, `board/init_raminfo.c`, `board/t234_startup.h:96-124`, `board/hw_sertcu.c:55-83`, `startup/m4-board.sh:51-52`, `:829-834`, `startup/m3-host.ksh.in:40`, `startup/make-m1b-images.sh:420`, `orin-native/tools/Makefile`, `orin-native/m4/launch-m4tcg.ps1:306`, `scripts/launch-qhv-tcg.ps1:151`, `.gitignore`;
- `qhv/host/local/options:73`; plan:455-491, :852-887; m5-design.md §2 rule 5, §7.1-§7.3 and §13; m4-design.md:1380-1396; r/research-kexec-tcu.md:416-419, :475-476; RT:48-89, :228-257, :336-365;
- LX v5.15 `arch/arm64/kernel/process.c` `machine_restart()`, as quoted by the technical review; not re-fetched here.

No board was contacted, nothing was downloaded, and no QNX-shipped binary was read.

**What did not change**
- The guest set default (Linux only, B5 conditional), kexec entry, the configuration text of §3.7, the console wiring and probes, initrd I-a, and the CPU placement.
- Window 1, `c1` and `c2`.
- The session ladder's steps and their order, apart from a reboot at the end of B0. The guard and return bounds, apart from new terms in `s1-n2`'s worst case.
- Every hard rule of the task: no board contact, no download, no QNX binary read or committed, no figure from M3 on.

| # | Review | Severity | Issue | Disposition | Why |
|---|---|---|---|---|---|
| V1 | technical | blocker | `avoid_ram` does not keep the canaries away from procnto: they reach `sysram`, and `memcanary fill` would overwrite pages the host could own | **Applied, and widened** by V8 and V9: `alloc_ram` plus an `s1canary` asinfo entry in `t234_init_raminfo`, and startup now does the fill | **VERIFIED.** `avoid_ram` only appends to the avoid list (`lib/ram.c:401-419`). Only `find_top_ram_aligned_limit` and `find_ram_in_range` read that list (`:167`, `:217`). `add_sysram` walks `ram_list` alone (`:436-439`), and only `alloc_ram` edits `ram_list` (`:294-316`). `t234_init_raminfo` (`main.c:235`) runs before `init_system_private` (`:293`, which calls `add_sysram` at `init_system_private.c:319`).<br>**The registration pattern is the library's own:** `fdt_asinfo` does `as_add_containing` then `alloc_ram` for the kexec tree (`fdt_init.c:46-47`).<br>**Found while checking:** `alloc_ram`'s overlap test also matches a `ram_list` entry that starts exactly at the range's end (`ram.c:297-299`). No constant does that; §3.3 and the generator's constant check now keep it so.<br>C15 and D7's reasons are rewritten: order was never the issue. |
| V2 | technical | minor | §3.3 cited `lib/_main.c:141-143` for keeping the IFS out of the allocator; that line is an `avoid_ram` | **Applied** | **VERIFIED:** `_main.c:142` is `avoid_ram(full_imagefs_paddr, …)`. The mechanism is `add_ram`'s `alloc_ram` of the image (`ram.c:377-379`) and `board/main.c:251`. §3.3 now also says an avoided range still reaches `sysram`. |
| V3 | technical | minor | `panic=-1` needs a restart handler; with no PSCI node the guest prints `Reboot failed -- System halted` and spins with qvm alive | **Applied, both fixes:** a PSCI node is a T1 gating row, and `l_rbfail` triggers teardown (F29) | Revision 1's §3.6 accepted a tree with no PSCI node, and §6.2 listed the node as Recorded only, so the no-fan spin was reachable. The needle costs nothing and also covers a node present but not working (R42). The upstream text is VENDOR_CLAIM and NVIDIA's fork was not read (R32). A missing node now fails T1 instead of being "a finding". |
| V4 | technical | minor | T2 "fill the `alloc` canary" and T3 "`alloc` verify" had no tool mode and no size; the TCG host may have 1 GiB | **Applied:** a `hold` mode; T2 has no allocation; T3 holds 64 MiB, B4 holds 256 MiB | **VERIFIED:** revision 1's `alloc` mapped, filled, verified and unmapped in one call. `OPT_RAM='1G'` (`qhv/host/local/options:73`), while the launcher passes `-m 2G` (`launch-m4tcg.ps1:306`), so R13 stays open. 64 MiB fits either case after the 512 MiB guest. The sizes also feed the gate table (V28) and item 4 (V22). |
| V5 | technical | minor | B1 runs M1b's buildfile with no S1 script, so it cannot print L0's or L7's tokens | **Applied** with V18: B1 is exempt from L0, L7 and item 5, and has its own token list | **VERIFIED:** M1b's generator prints `T234 $label -P$n: procnto up` (`make-m1b-images.sh:420`), with no `S1` lines. |
| V6 | safety | major | `s1con` and `memcanary` would be built in place as unignored QNX binaries in a public repo | **Applied:** §4.3 now specifies the two `.gitignore` lines, and T0 step 6 and §8 item 12 gate on `git check-ignore` | **VERIFIED:** the Makefile builds in place (`%: %.c`); `.gitignore:96-103` lists each built tool by name, with no wildcard. This design does not edit `.gitignore`; the implementation change must add the lines together with the Makefile targets. |
| V7 | safety | major | F25 allowed a power cut after 5 minutes whatever the last line was, and S1 had no rule against slot failover after the firmware banner | **Applied as proposed:** §2 rule 6a, F25a and F25b, F10 under rule 6a, F30, §7.1's designed-out list, §7.3, §8 item 13, and `nvbootctrl` after every return | **VERIFIED:** m5-design.md:132-133 makes unvalidated boots zero-tolerance, with one exception. F25 was copied from m4-design.md:1388, which predates that rule. Every S1 rung returns through a firmware boot, so M5's rule applies. A cut in the image's own hang is still allowed, because L4T's boot option started before kexec. |
| V8 | safety | major | `memcanary` would write any physical address and size its command line gave | **Applied, going further than proposed:** `memcanary` has no physical write mode at all. It addresses only three compiled names, checks each against the syspage, and has a self-test that the black box is refused | Once startup fills the canaries (V9), the tool needs no write, which removes the hazard instead of guarding it. The refusal of `refuse=no-entry` or `refuse=in-sysram` also shows that V1's fix took effect. §7.1's guarantee now covers the tool. |
| V9 | safety | major | The DMA residual was attributed to the SMMUs alone; the GPU is CPU-physical with no SMMU; the fill came late; guest RAM placement was unrecorded; RT B6 was neither adopted nor declined | **Applied with changes.** The residual is restated (§0, §3.8, §10). The fill moved into startup, not the shim. Writes before the fill are in "Cannot detect" and §10. `S1 GUESTRAM` is printed if Q14 finds a view, and "unknown" is recorded otherwise. **RT B6's BAR0 read is declined** | **VERIFIED:** RT:54 (R3) and RT C2 and C3 show no IOMMU in the GPU's path.<br>**Why startup and not the shim:** the shim is pinned and unchanged since M0 (§4.1). Startup already maps above 4 GiB (`hw_sertcu.c:72`) and knows the image and tree extents, so it can refuse before writing (F31).<br>**Why B6 is declined:** it is a GPU check, which the owner deferred to the first GPU stage (plan:465), and its expected failure is an SError at EL2, likely a power cut. It is listed for that stage (§5.4). |
| V10 | safety | minor | B0's staging and `p0` run on the same L4T boot as B1's quiesce, and §8 named one uptime limit | **Applied as proposed** | **VERIFIED:** `m4-board.sh:829-834` has 7,200 s and a separate 1,800 s with the quiesce. The harness lesson is to run isolate and `rmmod` only on a fresh boot. B0 step 4 now reboots; §6.12 and §7.3 forbid overrides. |
| V11 | safety | minor | I-b's board-side compile writes to L4T's rootfs with no rule or owner decision | **Applied:** D2 needs the owner's approval at the time; §3.5 names the directory, the copied files and the removal check; §2 rule 5 names it as the one exception | Rule 5 allowed only staged kimgs. |
| V12 | safety | minor | §4.4 cited an M3 run outcome from the unpublished record in a design that will be public | **Applied** | The landing address is public from checklist 12 (plan:872, m0-kexec-acceptance.md). |
| V13 | completeness | major | The met rule was circular: D1 deferred the guest set to the freeze, and the freeze needs S1-F met | **Applied, both options in order:** settle freeze item 2 before B4 closes (D1), otherwise a provisional met line, with B5 required before the freeze if item 2 keeps the QNX guest | **VERIFIED** against plan:479-480. The provisional wording keeps the rung closable without prejudging item 2. Appendix A adds plan:479. |
| V14 | completeness | major | D8 offered a window-1 continuation that §5.2 forbade and no image supported | **Applied: that option is dropped,** and §5.3 now separates a defect (fix, rerun) from data (kill condition 1, stop) | Window 2 is needed for B4's layout as specified, B5 and freeze item 6. A window-1-only pass would need new images and would inform nothing the freeze needs. |
| V15 | completeness | major | Kill condition 1 depended on "no other range passes B2", but no other range was defined | **Applied:** restated against the one 11c candidate (C1). Another range is a new design revision under D8 | **VERIFIED:** 11c names one candidate (plan:866). |
| V16 | completeness | major | Kill condition 2's "QNX support cannot fix it" had no step, time box or owner, and a board-only failure had no terminal state | **Applied:** D17 (channel, what may be sent, time box, who declares), R33, and §5.3's terminal rule after `s1-d1` with named record files | Whether evaluation output may go to the licensor is a 4.6(i) question, so D17 routes it through the professor. The design does not assume a channel exists. |
| V17 | completeness | major | Item 5 needed an FDT hash for every run, but T2 and T3 never dumped one, and the board and TCG profiles of `boot` disagreed | **Applied:** T2 and T3 run the `dryrun` and export before launch; item 5 covers T1-T3 and B2-B5, with B2 stamped `fdt=none` and B1 exempt | Running the `dryrun` in each run is cheap and makes the two profiles of `boot` match, instead of inferring T2's tree from T1's. |
| V18 | completeness | minor | L0 said "every board rung", which B1 cannot meet | **Applied** with V5 | Same fix. |
| V19 | completeness | major | L3 was "diagnosis" but item 2 required it; its needle is a HYPOTHESIS with no risk row; the board waits chained from `l_kernel` | **Applied as proposed:** item 2 now needs L0, L1, L2, L4, L5 and L7; waits run from the launch; R31 added | A wrong banner text would otherwise have failed item 2 on a guest that reached a shell. TCG and board rules for the same outcome now match. |
| V20 | completeness | major | "A GPU range stays out of every `add_ram`" (plan:463) was vacuous: window 2 took the whole candidate | **Applied with changes:** a named, provisional GPU range of 3,072 MiB at the top of the candidate; window 2 is 2,208 MiB; `c3` moves to window 2's new top; D18 lets the owner choose; a resize reruns B1 and B2 | The plan requires a range, and choosing it now avoids changing the startup that B1 and B2 verify. 3,072 MiB is RT §6.0's upper bound (RT:353), so the freeze can only grow window 2. The 2,208 MiB window still holds the target's 2,048 MiB guest (RT:352). `S1 ASINFO gpu_in_sysram=no` is the evidence. |
| V21 | completeness | major | §10 left stage-2 isolation claimable and did not bar claims about window-2 guest RAM or a larger guest | **Applied as proposed** (§0, §10) | No rung tests containment. |
| V22 | completeness | minor | Item 4's "host memory canaries" watched only ranges outside the allocator | **Applied:** B4 holds a 256 MiB filled host allocation through the hold, and item 4 names both kinds | Now one piece of host-allocated memory is watched too. It is still one mapping, so §10 keeps "not full memory integrity". |
| V23 | completeness | minor | F5 sent an overlay to the owner, but no decision existed and the Never list and gate forbade it | **Applied:** D19; the gate and the Never line allow only a non-GPU overlay approved by hash | This keeps plan:464's no-GPU rule and item 2's identity. |
| V24 | completeness | minor | D15 offered "unattended allowed", which rule 6 and §7.3 already forbade | **Applied:** D15 is now a confirmation of presence and schedule | — |
| V25 | completeness | minor | T0 built and gated `s1-q2`, which is over the geometry cap with no derived limit | **Applied:** `s1-q2` is built only after D1 keeps the QNX guest, and T0 step 7 computes D14's limit first | — |
| V26 | completeness | minor | No record file was named for the run note or the step verdicts | **Applied:** §2 rule 10 names `r/s1-runs.md` (local branch only) and each step's `parse-s1.txt` | As M3's and M4's named records. |
| V27 | completeness | minor | §9 lacked rows for several HYPOTHESIS claims; R19's class disagreed with §5.1 | **Applied:** R34-R37, F28 for an allocation failure diagnosed before D8, and R19 is now HYPOTHESIS | While checking, R38-R42 were added for the revision's own new assumptions (the named asinfo entry, `startup_io_map` of 16 MiB, the syspage walk, the guest-RAM view, the PSCI reset). |
| V28 | completeness | minor | The per-mode FreeMem gate constants were never stated; B2 mixed MB and MiB | **Applied:** §5.1's table in MiB, with the unit reasoning | The unit follows from `pidin info`'s total equalling `T234_RAM_SIZE` in MiB. It is HYPOTHESIS on the TCG host. B5's constant now includes qvm's 20 MiB, and §4.5 matches. |
| V29 | completeness | minor | The handover omitted freeze item 10, although the pinning needs at least four emulated CPUs | **Applied** (§0, §5.5) | **VERIFIED:** both existing TCG launchers pass `-smp 2` (`launch-m4tcg.ps1:306`, `scripts/launch-qhv-tcg.ps1:151`). |
| V30 | completeness | minor | T3's pass criterion named no tokens | **Applied as proposed**, with R22's black-box text estimate | — |

**Edited, by row**
- **V1:** §0 "Chosen path" item 3; §1 C15; §3.3 R-2 row, the option bullets and the constants; §4.3 `init_raminfo.c` row; §5.1 L0; §7.2 F13, F15; §9 R38, R39; §11 D7; the timeline (a new row).
- **V2:** §3.3 "Facts".
- **V3:** the timeline Hold row; §3.4 the needle table and the `panic=-1` bullet; §3.6 PSCI; §5.3 fewer online CPUs; §6.2 Gating; §7.2 F29; §9 R32, R42.
- **V4:** §3.8 `hold` mode and "When"; §6.3; §6.4; §6.9.
- **V5 and V18:** §0 tier table; §5.1 L0 and L7; §5.2 item 5; §6.6; §6.12 B1 row.
- **V6:** §4.3 table and closing line; §6.1 step 6; §8 item 12.
- **V7:** §2 rule 6a; §5.1 L7; §6.11; §7.1 recovery classes and the designed-out list; §7.2 F10, F25a, F25b, F30; §7.3; §8 item 13.
- **V8:** §0 "Chosen path" item 8; §3.8 (rewritten); §4.2 `make-s1-images.sh` checks and the tools line; §7.1 guarantees; §7.3; §9 R18, R40; §12 Q15.
- **V9:** §0 "What it is not"; §3.3 fill steps and the closing paragraph; §3.8 "Cannot detect" and "Not adopted"; §5.1 `S1 GUESTRAM`; §5.4; §5.5 item 6; §6.7; §6.8; §7.2 F31; §7.3; §9 R41; §10; §12 Q14.
- **V10:** §6.5 step 4; §6.12 closing paragraph; §7.3; §8 item 8; the §0 ladder B0 row.
- **V11:** §2 rule 5; §3.5 I-b; §11 D2.
- **V12:** §4.4 "Landing".
- **V13:** §5.2 met rule and record wording; §11 D1; Appendix A (plan:479).
- **V14 and V15:** §1 C1; §5.3 B2; §6.12 B2 row; §7.2 F14, F16; §11 D8.
- **V16:** §5.3 T1 and board-only paths; §6.12 B3 row; §7.2 F5; §9 R33; §11 D17.
- **V17:** §1 C16; §5.2 item 5; §6.3.
- **V19:** §0 tier table L3; §5.1 L3-L5; §5.2 item 2; §6.3 and §6.8 bounds; §9 R31.
- **V20:** §0 "Chosen path" item 3; §2 rule 5; §3.3; §5.1 L0; §5.5 item 6; §7.3; §11 D18; Appendix A (plan:463).
- **V21:** §0 "What it is not"; §10.
- **V22:** §0 "What a pass settles"; §0 tier table L6; §5.1 L6; §5.2 item 4; §6.9; §6.12 `s1-n2` bound terms.
- **V23:** §3.7 gate; §5.3 T1; §7.2 F5; §7.3; §11 D19.
- **V24:** §2 rule 6; §11 D15.
- **V25:** §4.2 images; §6.1 steps 5 and 7; §6.4; §6.5 step 2.
- **V26:** §2 rule 10; §6.11.
- **V27:** §7.2 F28; §9 R19, R34-R37.
- **V28:** §4.5 gate; §5.1 gate table and B2's unit.
- **V29:** §0 "Informs"; §5.5 item 10.
- **V30:** §5.1 TCG paragraph; §6.4; §6.12 T3 row.
- **Also:** the header; §4.2 README row (the Never list is §7.3).

---

## 14. Implementation decisions (T0, 2026-09-14)

These record what T0's implementation chose where §3-§6 left the choice open, and every place it departs from the text above. They are adopted by default, as §11's decisions are, and the owner can overturn any of them. **VERIFIED** marks a choice a build, a self-test or a gate showed on the PC. Nothing has run under QEMU or on the board, so no entry carries a figure from a run.

**Sources.** Part 1 is the committed headers of `orin-native/s1/` (`mkcpio.py`, `initrd.manifest`, `init.sh`, `s1-linux.conf`, `s1-conf.allow`, `parse-s1.py`), of `tools/s1con.c` and `tools/memcanary.c`, and the `-b` change in `board/`. Part 2 is `startup/s1.build.in`, `startup/s1-host.ksh.in`, `startup/make-s1-images.sh`, `startup/s1-board.sh`, `s1/build-s1tcg-image.ps1`, `s1/launch-s1tcg.ps1` and `s1/post_start-s1tcg.custom`, with their reviews and the integration gate. Usage is in `orin-native/s1/README.md`.

### 14.1 Inputs, the initrd and the configuration

**A. `python`, never `python3`.** On this PC `python3` is a Microsoft Store alias. Every S1 script calls `python` (3.12); the generator falls back to `py`.

**B. Two initrd pins, and a zlib dependency.** `mkcpio.py` is standard library only and writes a deterministic newc archive: sorted paths, inodes 1..N, zero times and owners, gzip level 9 with no name and mtime 0. The manifest pins both layers:
- the gzip file, `44e81ea6…495ab6`;
- the cpio stream inside it, `3bf6a987…87d65fe`.

The cpio bytes depend only on the inputs. The gzip bytes also depend on the zlib build (the pin was taken with Python 3.12's zlib 1.3.1), so a mismatch in the gzip pin alone is reported as exactly that. `init.sh` is pinned in the manifest (`2736648f…4d443e`), so an edit to `/init` changes three pins: `init.sh`'s, the initrd's, and every generator's copy of it. **VERIFIED:** `mkcpio.py --selftest` passed 25 of 25; the build printed `pin=ok`; independent sha256s of the file and of its decompressed stream agree.

**C. R11, answered at T0.** The source initrd reaches the interpreter through `lib -> usr/lib` and `usr/lib/ld-linux-aarch64.so.1 -> aarch64-linux-gnu/ld-linux-aarch64.so.1`, and the shebang through `bin -> usr/bin`. All three links are reproduced, and `build` refuses unless the source holds each at the same path with the same target.
- `sbin` is left out, because nothing lives there.
- The source has no `ld.so.cache`, and none ships.
- `dev/console` (c 5 1, 0600) is ours; the source's `dev/` is empty.
- The interpreter and `DT_NEEDED` entries were read from the ELF headers of the GPL and LGPL files, never executed.

**VERIFIED** by the build's link checks.

**D. R10, answered at T0 for the applets; `$(( ))` stays T2's.** The manifest's `busybox` line finds busybox's applet name table and requires `sh ash mount echo cat uname sleep` in it. Every applet link points at busybox: the source's `sh` is dash, and its `echo`, `cat`, `mount` and `sleep` are separate binaries, none of them copied. `+math` requires the three error texts of busybox's `shell/math.c`, which is built only with `FEATURE_SH_MATH`. That is an inference from strings of a GPL binary; T2's probe 1 is the real test. **VERIFIED:** checked on every build.

**E. `/init`, and a heartbeat with no counter.** `/init` mounts devtmpfs, proc and sysfs itself; a failed mount is reported, not fatal. It prints `S1-INIT start`, then `S1-INIT ready`, and runs a background heartbeat that prints `S1-HB` every 60 s, twelve times at most, **with no counter**. `/init` uses no `$(( ))` and no `[ ]`, so it cannot depend on what probe 1 tests.
- The ten heartbeats that item 4 counts are the host script's own `S1 HB k=N qvm=alive rc=absent` lines (§5.1 L6), not the guest's.
- No redirection names `/dev/null`. A redirection that could fail runs in a subshell, because a failed redirection ends the shell, and init ending panics the kernel.

**F. The configuration and its cmdline pin.** `s1-linux.conf` carries no comments, so the gate reads the bytes every leg stages (§2 rule 2).
- Its sha256 is ~~`2d639f67…44bc8b9`~~ `85d51359…61196e31` since 2026-09-14, when the virtio-console `hostdev` became the master (§14.9).
- `cmdline_sha256` is the sha256 of the cmdline string between its quotes, `da47f63e…4f337638`.

**VERIFIED:** `parse-s1.py conf` gives `gate=pass rejects=0 allow_errors=0`, and `parse-s1.py --selftest` compares the file with §3.7's text byte for byte.

### 14.2 The contracts between the units

**G. `parse-s1.py` is the token contract.** Its module docstring and its `--selftest` synthetic logs define every `S1`, `STAMP` and `BWAIT` line and every export block, and the host script emits exactly those. Where the parser and this design disagree, the parser wins unless it is clearly a bug; review found none.
- **`S1 CONFIG`** carries every item-5 field (§5.2 item 5): `image_sha256 initrd_sha256 conf_sha256 cmdline_sha256 init_sha256 s1con_sha256 memcanary_sha256 stamp_sha256 bwait_sha256 startup_sha256 startup_line cpu_lines ram_line windows canaries guest_set hold_s guard_s gpu_range`, plus `tcucat_sha256`.
  - The TCG profile gives the board-only fields placeholders (`startup_sha256=tcg-profile`, `canaries=none`, `gpu_range=none`, `guard_s=none`) and adds `smp=4 not-a-twin-leg`. The board profile adds `cpus=4 q=el2-host A=1`.
  - Host mode adds `fdt=none`. The diagnostics add `diag=` and `base_conf_sha256=`.
- **Exports** are framed `S1 BEGIN name=<n> bytes=<n> md5=<hex> enc=base64`, then base64 lines, then `S1 END name=<n>`.
- **Other records:**
  - `S1 STATE <name>`, where the names are `hostcheck`, `selftest`, `dryrun`, `export`, `readers`, `launch`, `canary_hold`, `teardown` and `end`.
  - `S1 FAIL_STATE` (printed twice), and `S1 TEARDOWN by=early|term|kill`.
  - The host heartbeat `S1 HB k=N qvm=alive rc=absent`.
  - `memcanary`'s own `S1 ALLOC`, `S1 ASINFO` and `S1 CANARY` lines.
- **Run options:**
  - `conf FILE [--allow] [--overlay]`
  - `fdt DTB [--conf]`
  - `run LOG --profile tcg|board --mode dryrun|boot|hold|host|q2 [--blackbox] [--out-dir DIR|none] [--conf] [--ref-conf-sha256] [--reset-reason] [--kexec-tree-sha256] [--image] [--initrd]`
  - `kshcheck FILE|--selftest`, which is `parse-m4.py`'s implementation, imported
  - `--selftest`
- **`run`'s exit codes:** 0 a verdict was given, pass or fail; 3 the verdict is refused because item-5 stamps are missing; 1 an input error; 2 a refused output path or a usage error. No FreeMem value and no duration is printed (§2 rule 8).

**VERIFIED:** `--selftest` passed 124 cases. The generator's review ran every generated script under bash, with stub tools, through `parse-s1.py run`: every TCG and board mode gave `pass`, and a negative B3 run (no `S1-INIT ready`) gave `fail failed=L4,L5` with teardown and exports still done. That harness is scratch tooling and is not committed.

**H. The startup's `-b` option and its refusal tokens.**
- **`-b w2`** adds window 2 after window 1, and prints `t234: ram w2 base=… size=…` and `t234: gpu range base=… size=… not added`.
- **`-b w2,canary`** also, for c1-c3 in order: takes each out of `ram_list` with `alloc_ram`, names it `s1canary` with `as_add_containing`, fills it, and prints `t234: canary cN base=… size=… filled`.
- **Any other value** crashes with `t234: -b<value> is not w2 or w2,canary` (F12).
- **Absent `-b`,** the control flow is unchanged and nothing new prints, which is B1's premise.
- **The containment refusal** prints `t234: canary cN overlaps image|fdt|shim|blackbox|gpu`, and also **`t234: canary cN overlaps unclaimed`** when a canary lies partly outside both windows, for example because `-m` shrank window 1. F31's list lacks that last token. Every refusal comes before the range is allocated or written.
- **The constants are also checked at compile time** with `_Static_assert`: window order, the GPU range as the rest of 11c's candidate, each canary inside its window, and c2 and c3 not touching.
- **The addresses in these lines are formatted unpadded by the board code,** because `kprintf` pads every hex conversion and the parsers match the text.

**VERIFIED:** the build and `build-board.sh`'s symbol gate pass. No refusal path has run.

**I. The S1 startup lives apart from the shared BSP output.** `PIN_STARTUP_S1` (`78153305…3a11103f`) is kept at `orin-native/s1/out/startup/startup-t234-orin-nano`, which is git-ignored.
- The shared BSP output path keeps the M1b-M4 build (`90bf724c…61896`), because `make-m1b-images.sh` through `make-m4-images.sh` read it. An S1 build is never left there.
- A rebuild copies its result to `s1/out/startup/` and restores the shared path, verifying both hashes.
- `make-s1-images.sh` resolves the startup only from S1's directory: its `MKIFS_PATH` is that directory plus `tools/`. When `BSP` is set, the generator checks the shared path against the M1b-M4 pin and never writes it.

**VERIFIED:** both hashes were checked before and after every T0 build. No rebuild was needed, because the board source matches HEAD and no source file is newer than the binary.

**J. `memcanary`'s markers and macro names.** `hold -s MIB -f TRIGGER -T SECS -o FILE` truncates FILE, removes `FILE.fill` and `FILE.done`, and prints nothing on the console (§2 rule 7). It creates `FILE.fill` after the fill line and `FILE.done` after the final line, so a `bwait -p` on a marker never races its line. The host script uses `/dev/shmem/hold.out`, with the trigger `/dev/shmem/hold.go`.
- **`memcanary.c`'s macros:** `S1_W1_BASE`, `S1_W1_SIZE`, `S1_W2_BASE`, `S1_W2_SIZE`, `S1_GPU_BASE`, `S1_GPU_SIZE`, `S1_CANARY_SIZE`, `S1_CANARY_C1_BASE`, `S1_CANARY_C2_BASE`, `S1_CANARY_C3_BASE`.
- **The startup header's macros:** `T234_RAM_BASE`, `T234_RAM_SIZE`, `T234_RAM2_BASE`, `T234_RAM2_SIZE`, `T234_GPU_BASE`, `T234_GPU_SIZE`, `T234_CANARY1_BASE` to `T234_CANARY3_BASE`, `T234_CANARY_SIZE`.
- The generator's constant check maps the two name sets onto each other, onto this design's values and onto `parse-s1.py`'s.
- `--selftest` prints `MEMCANARY SELFTEST PASS <n> checks`.

**VERIFIED:** the constant check passed, including the overlap and edge rules.

**K. `s1con`'s hit-directory rule.** `s1con` keeps `stamp`'s hit names, `DIR/open.hit` and `DIR/eof.hit`. So `stamp` and `s1con` get different `-h` directories (`/dev/shmem` and `/dev/shmem/con`) and different `-r` files (`s1.stamps` and `s1con.stamps`); otherwise one tool's hit would satisfy a wait meant for the other.
- `s1con` does not create DIR; the host script runs `mkdir -p` (a toybox link, M).
- `-O` (read-write) is required with `-w` or `-t`. Without it the device is opened read-only.
- `write` and `poll-error` are reserved labels.
- Both binaries are git-ignored by name.

Whether `/dev/shmem` accepts a subdirectory is still open (§14.7).

### 14.3 The generator and the host script

**L. The output root.** `make-s1-images.sh` writes to `--out DIR`, else `$S1_OUT`, else `orin-native/shim/out/s1`. That default is also `s1-board.sh`'s `S1_KIMG_DIR`. The unit was first briefed with `orin-native/startup/out/s1`, and review found the two defaults disagreed.
- **The guard:** the root must resolve inside the repository, be git-ignored, and lie outside `shim/out/m1b` to `shim/out/m4`, `orin-native/s1/out` and `qhv`. A test run therefore cannot overwrite a real output, the `make-m4-images.sh --generate-only` pitfall. This replaces §6.1 step 5's worktree.
- A build into another root needs `S1_KIMG_DIR` set to it on the harness's side. `--tcg` writes `<out>/tcg/s1tcg-<variant>/`.
- `build-shim.sh` still writes `orin-native/shim/out/t234-qnx.kimg`, as in M4, and the generator copies it to `<out>/<img>.kimg`.

**VERIFIED:** each refusal case stopped with a named FAIL before any write: `s1-q2` without `--q2-limit`, a root outside the repository, a root that is not ignored, a root inside `shim/out/m4`, and a limit of `0xBE000000`.

**M. The images and `.params`.**
- **Startup line:** `s1-h1`, `s1-n1`, `s1-n2` and `s1-d1` share `startup-t234-orin-nano -vvv -P4 -Q enable,el2-host -m992M -Wkeep -A -b w2,canary -Dtcu`, and the script labels `T234 S1 <image> -P4: procnto up` and `T234 S1 <image> -P4: resetting so the log can be recovered`.
- **Modes:** `s1-m1b-p6` b1, `s1-h1` host, `s1-n1` boot, `s1-n2` hold, `s1-d1` boot, `s1-q2` q2. These match `s1-board.sh`'s step table.
- **Payload:** `/data/s1/Image`, `/data/s1/initrd.cpio.gz` and `/data/s1/s1-linux.conf` (C2).
- **Toybox links:** two more than §3.9's `base64` and `od`, namely `mkdir` (K) and `rm`. On the TCG host `rm` is added, because the canonical image lacks it; `grep` and `mkdir` come from the canonical build files.
- **`.params` keys, in order:** `image rung mode profile p b_opt diag conf conf_sha256 cmdline_sha256 image_sha256 initrd_sha256 init_sha256 s1con_sha256 memcanary_sha256 stamp_sha256 bwait_sha256 tcucat_sha256 smpcheck_sha256 startup_sha256 startup_line mem_gate_mib hold_mib hold_s geometry_limit bounds ksh_worst_s guard_s return_bound_s capture_s build_sha256 ksh_sha256 kimg_sha256 transport q2_limit`. `kimg_sha256` is `-` until the full build wraps the image.
- **Bounds follow C14:**
  - `guard_s = ceil((ksh_worst_s + 125 + 240) / 300) × 300`
  - `return_bound_s = guard_s + 300`
  - `capture_s = return_bound_s + 3000`
  - `s1-m1b-p6` has `guard_s=none` and M1b's 1,200 s return bound.
- **Geometry:** the gate accepts `image_paddr` anywhere in the page at `0x80082000`, where M3 and M4 required exactly `0x80082fa0`, because S1's startup is a different build. The end is capped at `0x8C000000` (or `--q2-limit`) and at c1. The built images have `image_paddr=0x80082fa0`.
- **Tools** are pinned at their current builds: `s1con`, `memcanary`, `stamp`, `bwait`, `tcu-cat`, and M1b's `smpcheck`.

**N. B1 is proven by a pin, and its label is `T234 M1b -P6`.** `s1-m1b-p6.build` is proven byte for byte equal to M1b's `m1b-p6.build` (`6063a5b9…58e1d8bf`), with M2's re-expansion pin also checked, instead of re-running M1b's one-variable gate. The IFS also carries today's `tcu-cat` and `stamp`, which M2's script never calls. Because the buildfile is M1b's, the image prints `T234 M1b -P6: procnto up` and `T234 M1b -P6: resetting so the log can be recovered`, not §6.6's `T234 m1b-p6 -P6`. **VERIFIED** in the generator's `dumpifs` script check and in M1b's curated capture in `logs/sample-boot/`; `s1-board.sh`'s B1 tokens were corrected at integration.

**O. Guard and return bounds come out above §6.12's estimates.** The generator's bound table counts:
- each `bwait -k` plus `bwait`'s 5 s kill grace;
- four exports, each with `wc`, `md5sum`, `base64` and two `tcu-cat` marker lines;
- three canary verify sets on `s1-n2`.

| Image | Guard / return (generator) | §6.12's estimate | `capture_s` |
|---|---|---|---|
| `s1-m1b-p6` | none / 1,200 s | M1b's / 1,200 s | 4,200 s |
| `s1-h1` | 900 / 1,200 s | 900 / 1,200 s | 4,200 s |
| `s1-n1` | 2,100 / 2,400 s | 1,800 / 2,100 s | 5,400 s |
| `s1-n2` | ~~3,000 / 3,300 s~~ 3,300 / 3,600 s | 2,400 / 2,700 s | ~~6,300 s~~ 6,600 s |
| `s1-d1` | 2,100 / 2,400 s | — | 5,400 s |

**2026-09-14 (§14.10):** the hvc0 open wait now follows the launch under the dryrun's bound, in place of the reader bound it had before the launch. That adds 55 s to every board guest mode's `ksh_worst_s`, since the pl011 reader keeps its bound: `s1-n1` and `s1-d1` go from 1,670 to 1,725 s, and `s1-n2` from 2,615 to 2,670 s. `s1-n1` and `s1-d1` keep their guards. `s1-n2` crosses a 300 s step and moves to 3,300 / 3,600 s, with capture 6,600 s. The unbuilt `s1-q2` computes to the same 3,300 / 3,600 s. These come from the edited bound-table functions; the rebuild's `.params` are authoritative.

Accepting these bounds, or tightening the table toward §6.12, is an owner decision (§14.7).

**P. The host script's records and order.**
- **Four exports:** `fdt`, `qvmlog` (the dryrun's stdout and stderr), `pl011` and `hvc0`. All are base64, because pty output carries CR.
  - On TCG they go over the console.
  - On the board the BEGIN, body and END lines go by `tcu-cat -m`, `-f`, `-m`, so they never enter the black box. The console carries one `S1 EXPORT name=<n> bytes=… md5=… enc=base64 rc=…` record per stream.
- **TCG exports `fdt` and `qvmlog` before the launch** (C16, V17, §6.3), right after `S1 DRYRUN` and with its own `S1 STATE export`; `pl011` and `hvc0` follow teardown. The board exports all four after teardown (§5.1 L2, §6.8). Review caught the first version exporting after teardown on TCG as well.
- **`logger_errors` is a heuristic,** because qvm's logger format has not been read. It counts dryrun output lines that contain `error`, `fatal` or `internal` as a whole word (case-insensitive), leaving out lines that contain `logger`. A `saved=` other than `yes` stops the run before launch. A nonzero count lets the boot go on and sets `FAIL_STATE dryrun_logger_errors`. **2026-09-14:** it also counts every line that begins with qvm's configuration-diagnostic form `[file:line] `, whatever its words, each line once, because T1 attempt 1's diagnostic named none of the three words. The PC counts the same lines again from the `qvmlog` export, and requires `rc=0` (§14.9).
- **`l_kernel` is a checkpoint, not a stop** (240 s on the board, 900 s on TCG). At its bound the wait goes on to `i_ready` if `l_kernel` or `i_start` was seen. ~~The chained waits' `-t` bounds sum to the `i_ready` bound plus 10 s from the launch, and background timer files are a second limit.~~ **2026-09-14 (§14.10):**
  - The chain now starts with the hvc0 open wait, under the dryrun's bound.
  - The timer files, started at the launch, hold `l_kernel` and `i_ready` to their bounds from the launch; a slow open does not move them.
  - The `-t` bounds are backstops and never end a wait before its timer. The generator refuses a table where one would, or where the open wait could outlast `l_kernel`'s timer.
  - If the timers failed, the backstops' sum from the launch would be the open wait's bound plus the `i_ready` bound plus 10 s.

  Shortening `l_kernel`'s `-t` by the open wait instead would end that checkpoint early whenever `s1con` opens quickly.
- **F29 tears down at once.**
  - The hold and q2 blocks start only when `l_rbfail.hit`, `l_panic.hit` and `qvm_exit.hit` are all absent, and their waits also end on `l_rbfail.hit`.
  - After the heartbeat loop, `l_rbfail` skips the hold verify (printing `S1 NOTE hold_verify skipped reason=l_rbfail`) and the board's hold canary set.
  - q2 re-checks all three before its second qvm.
  - Teardown still writes `hold.go`, and the post-teardown canary verify still runs.

  Review caught this. The bounds are unchanged, because the change only removes waits.
- **A missed needle does not set `FAIL_STATE`** (`i_ready`, `shell_ok`): the parser's tiers catch it, as they caught M3's banner.
- **Heartbeat `qvm=alive`** means `qvm.rc` and `qvm_exit.hit` are both absent. `pidin`'s output goes only to a file (§2 rule 7).
- **Paths on the target:**
  - `stamp` hits in `/dev/shmem`, `s1con` hits in `/dev/shmem/con`.
  - Probe 2's trigger `/dev/shmem/probe2.go`; the FDT dump `/dev/shmem/s1-fdt.dtb`.
  - pl011 through qvm's stdout on `/dev/ttyp2`, read at `/dev/ptyp2`.
  - virtio-console: ~~on the slave `/dev/ttyp3`, whose master `/dev/ptyp3` is held by `s1con -O`~~ **2026-09-14:** qvm holds the master `/dev/ptyp3`, `s1con -O -R` holds the slave `/dev/ttyp3`, and preflight checks `/dev/ttyp3` (§14.9).

**Q. The TCG script calls `memcanary --selftest` only (§3.8 against R40).** R40's "answered by" column names `memcanary asinfo` on the TCG host at T0, but §3.8 and §7.3 forbid `asinfo` and `verify` in any TCG script, and §7.3 wins, so R40 is answered at B2.
- The generator's profile check refuses `asinfo` or `verify` in a TCG script, requires exactly one `memcanary --selftest` in the TCG profile, and refuses a self-test in a board script.
- The self-test was added at the integration gate: §6.1 step 6 asks for it in T1's image, and no unit ran it. A failure sets `FAIL_STATE=memcanary_selftest` without stopping the dryrun.
- `parse-s1.py` does not judge the self-test yet, so T1's review reads `MEMCANARY SELFTEST PASS` in the serial log.

**VERIFIED:** the profile check passed on every generated script. The board scripts regenerated byte-identical to those inside the built kimgs, because the explanation sits in `##` template lines.

**R. The diagnostics differ by leg.**
- **Board `s1-d1`** stages a separate `/data/s1/s1-d1.conf` with the logger widened and `unsupported instruction|register|reference abort` lines added (§5.3, F19). The gate rejects it on those three lines only. It prints its own `conf_sha256`, so `parse-s1.py`'s configuration identity check fails by construction. That is expected: it is never a pass run.
- **TCG `d1`** widens only the logger line.
- **TCG `d2`** changes only `rdinit=/bin/sh` and stages the stock L4T initrd.

Both TCG diagnostics are staged under the pinned names, so the parser's md5 line paths stay valid, and both are stamped `diagnostic=yes`.

**S. `s1-q2` is implemented but not built.** The `--q2-limit` gate (`0x8C000000 < limit ≤ 0xBD000000`), the guest pins, PO-E, the `@Q2@` buildfile and script blocks and M3's sequence all exist. They were exercised only by `--generate-only` and `--tcg` with a stand-in limit, and those outputs were removed. D14's limit is still owed (T0 step 7).

### 14.4 The TCG builder and launcher

**T. The build takes `-Mode`.** The mode is compiled into the host script inside the IFS, so it is chosen at build time, and the launcher's `-Mode` must equal the image's `s1tcg.params`.
- `lin` and `d1` have two modes, so they refuse a build without `-Mode`. `hold`, `q2` and `d2` default to their only mode.
- T1 and T2 are therefore separate images, `host-lin-dryrun-<tag>` and `host-lin-boot-<tag>`.
- §6.2 step 1 omits `-Mode`; step 2 omits `-Attempt` and `-Tag`, and both are required.
- **T1 is:** `build-s1tcg-image.ps1 -Variant lin -Mode dryrun -Tag <t>`, then `launch-s1tcg.ps1 -Attempt <N> -Variant lin -Mode dryrun -Tag <t> -QemuPath <QEMU 11.1.0's qemu-system-aarch64.exe>`.

**U. The TCG host script comes from the generator.** `-HostScript` defaults to `orin-native/shim/out/s1/tcg/s1tcg-<variant>[-<mode>]/s1-host.ksh`. The builder's own template substitution was removed, because it could not resolve the `@BOARD@`, `@TCG@`, `@DIAG@` and `@Q2@` line prefixes.
- **The builder checks:**
  - exactly one `MODE=`, `PROFILE=tcg` and `RUNG=tcg-<Variant>` line;
  - no surviving `@MARKER@`;
  - no `memcanary asinfo` or `verify`;
  - every item-5 stamp value it computed is present;
  - `kshcheck` passes;
  - the generator's `s1tcg.params` agrees on the mode, `ksh_sha256`, and every payload and tool sha256.
- `-Tag` is mandatory and must be new: a non-empty host or stage directory is refused, by `-CheckOnly` too.
- `-CheckOnly` runs the canonical, input-pin, configuration-gate and presence checks, with no copy, make or mkqnximage.
- `-Grace` is kept so no command line breaks, but it is inert: the q2 grace is the generator's bound table.
- Every variant keeps the canonical QNX guest pair in the TCG host's data partition, as the M4 builder does. §3.9's removal of that pair applies to board images only.
- `tcu-cat` is not staged on TCG.

**V. The launcher's end rule, wall bound and records.**
- **QEMU:** `-smp 4`, stamped `smp=4 not-a-twin-leg` (D5); `-snapshot`; one QEMU at a time.
- **End rule:** the end grace starts at `S1 STATE end`, not at the first `S1 FAIL_STATE`, because the script prints `FAIL_STATE` twice and the TCG pl011 and hvc0 exports follow the first.
- **Wall bound:** with no `-WallSeconds`, the wall is `ksh_worst_s + 1,800 s`, taken from the image's params, and an explicit value below that is refused. The old 7,200 s default was below the TCG hold script's worst case.
- **Records:** `qhv/s1tcg/attempt<N>/serial-raw.log`, `launch.log`, `parse-s1.txt`, `s1-fdt.dtb` and the parser's stdout and stderr logs. No elapsed time and no stream size is logged (§2 rule 8, Q7).
- **Result:** `LAUNCH_EXIT=0` means QEMU ended, the parser gave a verdict and no process survived. `LAUNCH_VERDICT` carries the parser's verdict line.

### 14.5 The board harness

**W. What `p0` and `run` gate.**
- **The kexec tree's sha256** is the sha256 of `/sys/firmware/fdt`, the blob `kexec_file_load` starts from. kexec rewrites `/chosen` in its own copy on every load, so the tree actually handed over cannot be read from user space. The source is stamped in both `p0` and `run`. Whether this meaning is acceptable for §5.2 item 5 is open (§14.7).
- **`p0`** reads and gates §8 items 5-9 and 13, all read-only:
  - the release, and the `/boot` pins;
  - the ramoops reg, and `LOAD_KEXEC=false`;
  - `/proc/iomem`: the top-level line `100000000-25e20dfff : System RAM`, and no other entry starting inside `0x100000000-0x249ffffff`. The CMA line is recorded, not gated;
  - the kernel configuration items, recorded;
  - `nvbootctrl`.

  `p0` also requires the dynamic-debug landing line, and exits 1 on any miss. D3's `/boot` pins are constants in the script.
- **Before any board contact,** `run` checks the PC inputs for every guest mode: `s1-linux.conf` against its pin and the gate; `S1_REF_CONF_SHA256` equal to that pin; and `out/l4t/Image`, `out/l4t/initrd` and `out/initrd.cpio.gz` against theirs. It always passes `--image` and `--initrd` to the parser.
- **The fresh-boot rule** is enforced through `used-boot-ids.log` in the record directory. Across record directories, the 1,800 s uptime limit is the remaining guard.
- **Fixed settings:** the quiesce and the governor pin always run. Setting `S1_MAX_UPTIME_S`, `S1_QUIESCE_MAX_UPTIME_S`, `S1_QUIESCE` or `S1_GOVERNOR_PIN` is refused (§7.3). `reboot` and `p1` also read `nvbootctrl`, and exit 4 on a difference (F30).
- **No board-side copies are left:** the black box and ramoops copies on the board are deleted after a sha256-verified copy to the PC (§2 rule 5).

**X. One COM3 capture per run.** `parse-s1.py run` reads a whole log with first-match rules and has no offset option. Gate A therefore refuses a capture file that already holds a record line, and gate B re-checks just before kexec. Both gates also refuse a capture that is not running: `missing`, `noheader`, `ended` (a closing or read-error footer), `expired` (its header's deadline passed) or `released`. `released` is detected because the capture opens its file with read sharing only, so a write open fails while it runs. **VERIFIED** on this PC with a PowerShell stream opened the same way: denied while held, allowed after release, with size and modification time unchanged.

**Y. Power-cut advice (§2 rule 6a) fails toward no cut.** `advice BOARDLOG` allows a cut only when three things hold: the board log carries `NO RETURN within` (the return bound has passed), the capture is running, and the kexec offset is known.
- **F25a** also needs the last line after the offset to be one of: recognised image output; Linux's own shutdown text before the first record line (F10's hang before the shim); a base64 body line inside an open export; or no output at all. It also needs no image reset marker (`resetting so the log can be recovered`, `BWAIT guard deadline`) and no firmware banner.
- **Anything else is F25b:** 10 minutes of silence, and one cut.
- `parse-s1.py`'s firmware banner texts are a HYPOTHESIS, so they are only a second F25b trigger.
- **Growth test:** reading growth from the capture file's modification time rests on a HYPOTHESIS, that NTFS updates it on every write while the file is held. A 10 s size sample is taken as well.

Review caught the first version: it could advise F25a after the image's reset, or with a dead capture.

**Z. Records.**
- `S1_RECORD_DIR` is required for `stage`, `p0`, `p1` and `run`, and must be git-ignored.
- Each run goes to `<rec>/<step>/`, and a later attempt to `<step>-aN`. An attempt refused before the board changes moves to `<step>-refused-<utc>`, so `<step>/` stays free for the first real run.
- The parser reads the raw copies; the redaction runs after.
- `extract` masks every figure: `ms=`, `cycles=`, `cps=`, `mono_ns=` and the `S1 MEM` values.
- `consistency` checks that the black box's records occur as a subsequence of COM3's.
- `b1-compare` masks addresses. `parse-s1.py` has no B1 mode, so B1 is judged by the harness's tokens and `b1-compare`.
- The NO RETURN line prints the `advice` command with a repository-relative path.

**VERIFIED:** `redact-selftest` passed 13 checks and `harness-selftest` 57, on synthetic inputs. Offline `run` refusals used a documentation-range address that was never contacted.

### 14.6 T0 gate verdicts (2026-09-14, PC only)

No board was contacted, no QEMU was started, nothing was downloaded, and no QNX-shipped binary was read. `dumpifs` ran only on our own IFS, to extract our own payload, as the M3 and M4 generators do.

| Step | Verdict | Evidence |
|---|---|---|
| Reconcile the generator's TCG outputs with the builder | **PASS** after a fix | The builder could not render the template; it now takes the generator's rendering and cross-checks its params (U) |
| Reconcile `.params` with `s1-board.sh` | **PASS** after a fix | The B1 label (N); an offline `run` of all five images read each image's params and stopped at the capture check |
| Reconcile the host-script tokens with `parse-s1.py` and the launcher | **PASS** after two fixes | The end grace and the wall bound (V); the TCG self-test was added (Q) |
| T0 1, inputs | **PASS** | `Image` and `initrd` equal the D3 pins; `MZ` at 0, `ARMd` at `0x38`, `text_offset` 0, `image_size` `0x029b0000`, flags `0xa` |
| T0 2, initrd | **PASS** | `mkcpio.py --selftest` 25/25; the build matched both pins (B) |
| T0 3, configuration | **PASS** | `gate=pass` (F) |
| T0 4, startup | **PASS**, no rebuild | `PIN_STARTUP_S1` equal; the shared path held the M1b-M4 pin before and after every build; the symbol gate passed (I) |
| T0 5, generators | **PASS** | `--generate-only` into a scratch root, since removed. Then a full build of `s1-m1b-p6`, `s1-h1`, `s1-n1`, `s1-n2` and `s1-d1` into `orin-native/shim/out/s1`, where every step passed: PO-A, the pins, the constant check, the verbatim ranges, the profile check, `kshcheck` and its self-test with an injected pipe rejected, size, mkifs, `dumpifs`, geometry, the startup arguments read back from the IFS, the payload and host script extracted and re-hashed, the shim wrap, inputs unchanged, and every written file ignored. Each `.params` has `guard_s` and `return_bound_s` |
| T0 6, tools | **PASS** | `make` found `s1con` and `memcanary` up to date with their pins; both are ignored; `git status` shows no binary. The TCG self-test belongs to T1 (Q) |
| T0 7, D14's limit | not run | D1's QNX guest and D14 are outstanding (S) |
| T1's TCG image (`lin`, `dryrun`) | **PASS**, not launched | `BUILD_OK`. The canonical `qhv/host` and `qhv/guest` sums were unchanged before and after. R30 answered for the build: `data.build` names the `Image`, the initrd, the configuration and the guest pair, and mkqnximage succeeded |
| Final git state | **PASS** | Only the seven part-2 sources are untracked; every build output is ignored; no identifier appears in the sources; no leftover QEMU, mkqnximage or mkifs process |

**Also confirmed by the full build:**
- mkifs accepts the `/data/s1/` targets, and `dumpifs` lists them as `data/s1/<name>`.
- `dumpifs -x -b` extracts `Image`, `initrd.cpio.gz`, `s1-linux.conf`, `s1-host.ksh` and `s1-d1.conf` by basename, and each re-hashes to its pin.

**Provenance.** The board kimgs were built before the gate edited `s1-host.ksh.in` and `make-s1-images.sh`. The regenerated board scripts are byte-identical, and the buildfiles are equal once the output root is normalised, so the kimgs are still what the current sources produce. PO-A does not cover the part-2 files, though, so one rebuild from the committed tree before B0 is recommended.

### 14.7 Still open after T0

- **Owner:**
  - Accept O's bounds, or tighten the table.
  - Accept the TCG wall rule of V, which gives 4,840 s for `lin-dryrun`, ~~7,825 s~~ 8,395 s for `lin-boot` and ~~9,445 s~~ 10,015 s for `hold`. **2026-09-14:** the two guest modes moved by 570 s each, the TCG dryrun bound less the reader bound, when the hvc0 open wait moved after the launch (§14.10).
  - Accept `s1-n2`'s guard of 3,300 s (return 3,600 s), which is one 300 s step above O's first figure (§14.10).
  - D14's `--q2-limit`, if D1 keeps the QNX guest.
- **T1 or T2:**
  - Whether `/dev/shmem` accepts `mkdir` for `s1con`'s hit directory. A refusal would show as `S1 FAIL reader hvc0`.
  - qvm's logger line format, and the wording and stream of its FDT-saved message; `logger_errors` may need tuning. **2026-09-14:** partly answered by T1 attempt 1. The FDT message reads `FDT saved to '<path>'`, and a configuration error prints `[file:line] message`; the export shows CRLF line ends. Both came from the dryrun's stdout and stderr taken together, so the stream is still unknown, and the logger's own format for `error`, `fatal` and `internal` is still unseen (§14.9).
  - R13's 596 MiB gate under the TCG host's 1 GiB `OPT_RAM` with QEMU's `-m 2G`.
  - Whether qvm accepts `unsupported <class> abort`, which `s1-d1` uses.
  - ~~**2026-09-14:** whether `s1con`'s open of the slave `/dev/ttyp3` returns before qvm holds the master. The readers still start before the launch; if a slave open waits for its master, T2 stops at `S1 FAIL reader hvc0` (§14.9).~~ **Addressed 2026-09-14 (§14.10):** `s1con` now starts right after qvm is launched, and its open wait is the first wait after the launch. Two things stay for T2:
    - whether a slave open waits for its master, is refused (`s1con: open /dev/ttyp3: …` and `S1 FAIL reader hvc0`), or returns early and ends `s1con` on its first read (`STAMP eof` or `STAMP read-error` in `s1con.stamps` before teardown, then `l_kernel` with no `i_start`, which reads as §5.3 stage 2 unless `s1con.stamps` is checked);
    - whether qvm reaches its hostdev inside the dryrun's bound after a launch.

    A missing `/dev/shmem/con` still shows as `S1 FAIL reader hvc0`, now after the launch and followed by teardown. A qvm that exits before `s1con` opens prints no reader failure; it shows through `qvm.rc` and a missing L4, as before.
- **Board harness:**
  - Whether `/sys/firmware/fdt`'s sha256 is an acceptable kexec-tree stamp (W).
  - The `/etc/nv_tegra_release` format `p0` assumes: `R36` and `REVISION: 4.7` on its first line.
  - D3's `/boot` pins as constants in the script, or read from one pinned source.
  - A B1 mode in `parse-s1.py`.
- **Parser:** `parse-s1.py` does not yet judge the TCG `memcanary` self-test (Q).
- **Tooling:** whether the generator review's stub harness becomes a committed PC-side regression.

### 14.8 Stale text above, to correct later (list only)

- **§6.2 steps 1 and 2:** add `-Mode` to the build, and `-Attempt` and `-Tag` to the launch (T).
- **§6.6:** `T234 m1b-p6 -P6` should be `T234 M1b -P6` (N).
- **§7.2 F31:** add `unclaimed` to the overlap list (H).
- **§9:** R40's "answered by" should be B2, not T0's TCG `asinfo` (Q). R10 and R11 were answered at T0 (C, D), except that `$(( ))` stays with T2. R30 was answered for the build by T1's image build (§14.6).
- **§3.9 "Added":** the toybox links `mkdir` and `rm` (M).
- **§6.12:** the bound table's values (O).
- **§6.1 step 5:** the worktree is replaced by the configurable output root (L).
- **§4.2 rows:**
  - `build-s1tcg-image.ps1`: `-Mode` is required for `lin` and `d1`, and the host script comes from the generator (T, U).
  - `launch-s1tcg.ps1`: the end rule and the wall bound (V).
  - `s1-board.sh`: it also has `reboot`, `advice`, `consistency`, `b1-compare`, `redact-selftest` and `harness-selftest` (W-Z).
- **§13, "What did not change":** it names §3.7's configuration text and the console wiring, both changed on 2026-09-14 (§14.9). §13 records revision 2's review and is left as it was.

### 14.9 T1 attempt 1 and the change it caused (2026-09-14)

**What happened.** T1 ran once under TCG, as attempt 1, from the image `host-lin-dryrun-t1a`. Its record is private and git-ignored. `parse-s1.py run` gave `verdict=pass`: the configuration gate passed, the FDT was exported with every gating row present, and `memcanary --selftest` passed. The pass was not clean:
- bwait's line for qvm and `S1 DRYRUN` both carried `rc=64`, beside `saved=yes` and `logger_errors=0`.
- qvm's dryrun output, exported as `qvmlog`, was two lines: `FDT saved to '/dev/shmem/s1-fdt.dtb'`, then `[/data/s1/s1-linux.conf:14] Unable to open '/dev/ttyp3': Interrupted function call`. Line 14 is `vdev virtio-console`, which opens the block whose `hostdev /dev/ttyp3` named the slave.
- Nothing held the master `/dev/ptyp3` during the dryrun: the host script starts its readers only after the dryrun and its export.

**Why the gate passed anyway.** C3 recorded the exit code without judging it. The `logger_errors` heuristic counts only lines naming `error`, `fatal` or `internal`, and qvm's `[file:line] message` diagnostic named none of them.

**Reading (HYPOTHESIS).** Opening a pty slave waits until its master is open, and qvm's open was interrupted while it waited. This was not tested directly. M3 never opened a slave before its master: its pl011 path redirects to `/dev/ttyp1` only after `stamp` holds `/dev/ptyp1` (`startup/m3-host.ksh.in:97`, `:106`), and its IPC client opens `/dev/ttyp0` after qvm holds `/dev/ptyp0` (`qhvc/g2-m3.conf:38`; `startup/m3-host.ksh.in:53`, `:121`).

**What changed.** The orchestrator adopted C11's fallback before T2, under the owner's standing go-ahead for PC-side TCG work, and tightened T1's gate:
1. **Configuration.** Only the virtio-console `hostdev` changed, to the master `/dev/ptyp3` (§3.7). Its sha256 moved from `2d639f67…44bc8b9` to `85d51359…61196e31`. `cmdline_sha256` is unchanged (`da47f63e…4f337638`). Every pin moved with it: `make-s1-images.sh`, `s1-board.sh`, `build-s1tcg-image.ps1`, and the parser's copy of §3.7.
2. **Host script.** `s1con -i /dev/ttyp3 -O -R` holds the slave with raw termios, and preflight checks `/dev/ttyp3`. `logger_errors` also counts every dryrun output line that begins `[file:line] `, whatever its words, and each line counts once. Nothing else in the order changed: the dryrun still runs before the readers, and qvm opens the master itself, so its dryrun needs no reader. The pl011 wiring is unchanged, as in M3.
3. **Parser.** Every dryrun rule (T1's item 1, T2, T3's token rule and the board's L2) needs `rc=0`, `saved=yes`, `logger_errors=0`, a decoded `qvmlog` export, and no line of that export beginning `[file:line] `. The parser prints `dryrun_rc=` and `qvmlog_diagnostics=`, so the exit code is still recorded. Nine self-test cases were added: `rc=64` alone, a diagnostic with `rc=0`, attempt 1's shape, a missing `qvmlog` export, a diagnostic that is not at the line start, T3 with each failure, and B3 with a diagnostic.
4. **Board harness.** `extract` also lists a `S1 DRYRUN rc=` other than 0, and `[file:line]` lines, among its negative tokens.
5. **`s1con.c`.** Three comment lines changed: the virtio-console's host end is now the master of pair 3, and the tool's device and the probe-1 example are `/dev/ttyp3` with `-O -R`. The `-R` note already named the slave `/dev/ttyp3`. A scratch compile of the edited source reproduces the binary's pin, `ed4a5a0b…`, so no tool pin moved.

**VERIFIED on the PC:** `parse-s1.py --selftest` passes, and `conf` gives `gate=pass` on the new file. Re-read by the new parser with no outputs written, attempt 1's own log fails L2 on `dryrun_rc_not_0` and `dryrun_qvm_diagnostics`, and item 1 fails with it. The host script's new `logger_errors` lines pass `kshcheck` and count attempt 1's text as one line, but only under Git Bash's grep, not the target's.

**Rebuild.** The generator's PO-A gate refuses to build from sources that differ from git HEAD. The TCG profile, the five board images and a new TCG image (`-Tag t1b`) are therefore rebuilt, and their pins recorded, only once this change is committed.

**What T1 attempt 2 must show.**
- An image built from that rebuilt TCG profile, whose `S1 CONFIG` carries `conf_sha256=85d51359…`.
- `BWAIT run prog=qvm … rc=0 … killed=0`, and `S1 DRYRUN rc=0 saved=yes … logger_errors=0`.
- A decoded `qvmlog` export with no line beginning `[file:line] `.
- From `parse-s1.py run`: `dryrun_rc=0`, `qvmlog_diagnostics=0`, `tier_L2=ok`, every gating FDT row, `item1_t1=pass` and `verdict=pass`.
- `MEMCANARY SELFTEST PASS` in the serial log, as in attempt 1.

A diagnostic that names `/dev/ptyp3` instead leaves this design no console fallback (F4).

**Open before T2: the reader order.** The host script still starts `s1con` and waits for its `open.hit` (bound `READER_T`) before the launch. So `s1con` opens the slave `/dev/ttyp3` before qvm holds the master. If a slave open waits for its master, as this section's reading supposes, `s1con` cannot open in time, and T2 stops at `S1 FAIL reader hvc0` before any launch. The adoption kept the order as decided. T1 attempt 2 runs in dryrun mode, starts no reader, and cannot show this either way. The order is owed a decision before T2, and before any board rung that launches. The review of this change named two options. (a) Start `s1con` after the launch and fold its `open.hit` into the needle waits, which changes the bound table and the host script's silence rule. (b) Open with `O_NONBLOCK` and clear it once the open returns, which moves `s1con`'s pin. On (b), a slave whose master is not yet open may refuse the open or give end of file on its first read, which ends `s1con`, so (b) is not safe to adopt untested. It is UNVERIFIED for `devc-pty` either way. M3's order, where the slave is opened only after qvm holds the master, is the only one run so far. **Decided 2026-09-14: option (a), before T2 (§14.10).**

**What this does not show.** Nothing has run with the new wiring. qvm's acceptance of the master, the raw slave path and probe 1 stay untested until attempt 2 and T2. **2026-09-14:** attempt 2 answered qvm's acceptance of the master (§14.10).

### 14.10 T1 attempt 2 and the reader order (2026-09-14)

**T1 attempt 2 passed clean.** It ran under TCG from an image built from commit `8d28100`, where the virtio-console `hostdev` is the master `/dev/ptyp3`. Its record is private and git-ignored. Against attempt 1:
- qvm's dryrun exited 0 and printed `Exiting: dryrun complete`, with no `[file:line]` diagnostic;
- the dumped FDT was byte-identical to attempt 1's, and every gating row was present;
- `memcanary --selftest` passed again.

So qvm opens the master of a pty pair with nothing on the slave. The dryrun needs no reader, and the host script's order before the launch stays as it was.

**The slave side is still a HYPOTHESIS.** §14.9's reading was that a pty slave open waits until its master is open. Attempt 1 is consistent with that: qvm's open of the slave was interrupted, not refused. No run has opened the slave with the master held since.

**The problem it left.** Until this change, the host script started `s1con` on the slave `/dev/ttyp3` and waited for its `open.hit` in `S1 STATE readers`, before `S1 STATE launch`. qvm opens the master only after the launch. Under the reading, `s1con`'s open could not return in time, so T2, B3 and B4 would all have stopped at `S1 FAIL reader hvc0` without launching.

**What changed: §14.9's option (a).** Option (b), `O_NONBLOCK`, was not taken: it moves `s1con`'s pin and is unsafe untested (§14.9).
1. **Host script (`s1-host.ksh.in`, both profiles).** `S1 STATE readers` now starts only `stamp` on the pl011 master `/dev/ptyp2` and waits for its `open.hit` under the reader bound, as M3 did. Under `S1 STATE launch` the order is:
   - the two timer files;
   - qvm, in the background;
   - `s1con`, at once in the background, with the same arguments as before;
   - `bwait -p /dev/shmem/con/open.hit -p /dev/shmem/qvm_exit.hit`, bounded by the dryrun's bound `DRY_K` (60 s on the board, 600 s on TCG). This is the first wait after the launch.
2. **With `open.hit`,** the `l_kernel`, `i_ready` and `shell_ok` waits run exactly as before.
3. **Without it,** the script skips the needle waits. If qvm is still running, it also prints `S1 FAIL reader hvc0` and sets `FAIL_STATE reader`. If qvm exited first, the script prints no reader failure, since a qvm that has exited never opens `/dev/ptyp3`. That exit shows as it did before this change, through `qvm.rc` and a missing L4, and the open wait's `bwait` line names `/dev/shmem/qvm_exit.hit`.
   - `S1 STATE report` still prints.
   - The hold and q2 blocks need `shell_ok`, so they are skipped.
   - Teardown ends qvm, because `LAUNCHED` was set before the launch.
4. **The report now also shows the open wait's own `bwait` line.** A log therefore says whether `s1con` opened, the wait timed out, or qvm exited first. The parser reads no `BWAIT path` line, so no token changed.
5. **Unchanged:**
   - the token texts;
   - the dryrun and its TCG export, which still come before any reader;
   - the q2 block, whose `stamp` opens the master `/dev/ptyp1` before its launch and whose IPC client opens `/dev/ttyp0` after the banner. Neither is a slave opened before its master.

**Why no guest output is lost.** The guest's first `hvc0` line, `S1-INIT start`, can appear only after its kernel has booted and probed virtio-console. That is long after qvm opened its `hostdev`.

**Why the dryrun's bound and not the reader bound.** qvm opens its `hostdev` during its configuration pass. In `s1-linux.conf` the `ram`, `load` and `initrd load` lines come before `vdev virtio-console`, so the open may follow the loading of the `Image` and the initrd; that line order is a HYPOTHESIS for qvm's processing order. The dryrun does that same pass, and in attempt 2 it completed inside `DRY_K`. The reader bound (5 s on the board, 30 s on TCG) was sized for an open that returns at once, and nothing measured shows qvm reaching its `hostdev` that fast after a launch. A healthy run could fail on it. The wait ends at `open.hit`, so a good run pays nothing extra; only the worst case grows. Returning to the reader bound would change one marker in the template and one term of `ksh_worst`.

**Silence and bounds.**
- Between the launch and the needle waits' return, the console carries nothing except the failure line, and `s1con`'s own stderr if its open fails; both are failure paths.
- The timer files started at the launch hold `l_kernel` and `i_ready` to their bounds from the launch, whatever the open wait takes (§14.3 P).
- `bounds()` now refuses a table where `DRY_K` is not below `LK`, or where a chained `-t` would end its wait before its timer.
- `ksh_worst` counts the pl011 reader before the launch and, chained from it, `DRY_K` + `LK_WAIT` + `IR_REST` + `SHELL_T`.

**The new bounds (C14), computed from the edited functions.** The rebuild's `.params` and `s1tcg.params` are authoritative.

| Image or variant | `ksh_worst_s` | Guard / return | `capture_s` or TCG wall |
|---|---|---|---|
| `s1-h1` | 470 s (unchanged) | 900 / 1,200 s | 4,200 s |
| `s1-n1`, `s1-d1` | ~~1,670~~ 1,725 s | 2,100 / 2,400 s (unchanged) | 5,400 s |
| `s1-n2` | ~~2,615~~ 2,670 s | ~~3,000 / 3,300~~ 3,300 / 3,600 s | ~~6,300~~ 6,600 s |
| `s1-q2` (not built) | ~~2,615~~ 2,670 s | ~~3,000 / 3,300~~ 3,300 / 3,600 s | ~~6,300~~ 6,600 s |
| TCG `lin-dryrun` | 3,040 s (unchanged) | none | 4,840 s |
| TCG `lin-boot`, `d1-boot`, `d2` | ~~6,025~~ 6,595 s | none | ~~7,825~~ 8,395 s |
| TCG `hold` | ~~7,645~~ 8,215 s | none | ~~9,445~~ 10,015 s |
| TCG `q2` | ~~10,415~~ 10,985 s | none | ~~12,215~~ 12,785 s |

**VERIFIED on the PC (no rebuild; PO-A refuses sources that differ from HEAD):**
- `bash -n` passes on `make-s1-images.sh`.
- Every `@MARKER@` the template uses is one `gen_ksh` substitutes.
- A scratch rendering of the template drops the `##` lines and applies the profile prefixes with this table's values. It was made for the board and TCG profiles in `boot`, `hold`, `q2` and `dryrun` modes. Each rendering has no surviving marker and passes `kshcheck` and `bash -n`.
- `parse-s1.py --selftest` passes with no parser edit.

**What T2 must show.**
- **A clean dryrun before the launch.** Before `S1 STATE launch`: `S1 DRYRUN rc=0 saved=yes … logger_errors=0`, and the `fdt` and `qvmlog` exports. From `parse-s1.py run`: `dryrun_rc=0` and `qvmlog_diagnostics=0`.
- **`s1con`'s open after the launch.** After `S1 STATE launch`, no `S1 FAIL reader hvc0`. In `S1 STATE report`, the open wait's `bwait` line names `/dev/shmem/con/open.hit`, not `qvm_exit.hit` or a timeout. In that report's copy of `s1con.stamps`, before `S1 STATE teardown`, there is no `STAMP eof`, `STAMP read-error` or `STAMP poll-error` line. `open.hit` together with `STAMP i_start` shows that this order works. It does not show whether the open waited for the master: `s1con` starts at the same moment as qvm, so the `bwait` line looks the same either way.
- **The needles.** `STAMP i_start`, `STAMP i_ready` and `STAMP shell_ok` from `s1con`'s record; no `STAMP l_panic` or `STAMP l_rbfail`; no `rc=` line before `S1 STATE teardown`.
- **The streams.** After teardown, the `pl011` and `hvc0` exports, each decoding.
- **The verdict.** `S1 FAIL_STATE none`, and L2, L4 and L5 from the parser, the pass rule of §6.3.

A refusal instead of a wait would print `s1con: open /dev/ttyp3: …` with `S1 FAIL reader hvc0`. This script cannot observe when qvm holds the master, so that outcome would need a new design decision.

There is a third outcome. The open could return before qvm holds `/dev/ptyp3`, and the first read could then give end of file or an error (§14.9 named this for option (b); under option (a) the same race exists whenever `s1con`'s open runs before qvm reaches its `hostdev`). `s1con` would then write `open.hit` and end at once with `STAMP eof` or `STAMP read-error`. The host's open wait passes, and the needle waits run out with `l_kernel` but no `i_start`. §5.3's T2 staging would read that as stage 2 (an FDT, interrupt, virtio-mmio or initrd problem) unless `s1con.stamps` in `S1 STATE report` is read first. It is a reader-order fault, and it too would need a new design decision.

**What this does not show.** Nothing has run with the new order: no TCG boot and no board rung. Several things stay untested until T2, and then B3:
- the slave-open behaviour;
- whether qvm reaches its `hostdev` inside `DRY_K` after a launch;
- the raw slave path;
- probe 1.
