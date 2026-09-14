# S1-F design: a Linux guest without a GPU under native qvm on the Jetson Orin Nano

Phase 3b. Architect pass, revision 2, 2026-09-13 (revision 1 reviewed; outcomes in §13). This is a read-and-reason design: nothing in it has been built or run, and it creates no code, configuration or image. It follows the structure of [m5-design.md](m5-design.md) and [m3-design.md](m3-design.md). Its scope is the owner decision of 2026-09-11 (option B): S1-F is functional verification only, and every figure it would print is deferred to the post-freeze campaign (plan:400, :473).

**2026-09-13 (owner):** every owner decision in §11, D1-D19, was taken as recommended. Nothing has been built or run yet; the next step is D3's copy of the board's `Image` and `initrd`, then T0.

**2026-09-14:** T0 is implemented, built and gated on the PC, and every gate passed. Nothing has run under QEMU or on the board. The implementation decisions, deviations and gate verdicts are in §14; usage is in `orin-native/s1/README.md`.

**2026-09-14, revision 3 (owner, D8 option 1):** after B2 was not met on data, the writer is diagnosed first (§15, three adversarial reviews in §15.11). The J rungs' session record is §15.6.1, and the J6 watcher's implementation readings, fixed before its pre-registration, are §15.12. B2 stays NOT MET on data until §15.6's rule says otherwise.

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
- **2026-09-14 (owner, D8 option 1):** writer diagnosis first, §15; B2 stays NOT MET on data until §15.6's rule says otherwise.

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
   **2026-09-14 (owner, D8 option 1):** writer diagnosis first, §15; B2 stays NOT MET on data until §15.6's rule says otherwise. §15.4.3 adds the one dated exception to this rule, for the detached sequence's three files.
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
    **2026-09-14 (owner, D8 option 1):** writer diagnosis first, §15; B2 stays NOT MET on data until §15.6's rule says otherwise.
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
| B2 | §6.7 | B3 (after a fresh L4T boot) | §5.3: a defect is fixed and rerun; data is kill condition 1 and stops S1-F (D8). **2026-09-14 (owner, D8 option 1):** writer diagnosis first, §15; B2 stays NOT MET on data until §15.6's rule says otherwise |
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
| F16 | `S1 ALLOC … verify=bad` | Window-2 pages do not hold data | SR | Data: kill condition 1 (C1, D8); stop all board work; K5's hidden-user hypothesis. **2026-09-14 (owner, D8 option 1):** writer diagnosis first, §15; B2 stays NOT MET on data until §15.6's rule says otherwise |
| F17 | B1 black box differs | The option-off path changed startup | SR | Revise; T0 |
| F18 | TCG passed; board `S1 DRYRUN` logger error | Board host tree or registers | SR | Compare with T1's logger lines; `s1-d1` |
| F19 | Board `l_kernel` absent, qvm alive | Guest entry fault on A78AE | SR at teardown | `s1-d1` (`unsupported abort`) |
| F20 | `l_kernel`, then an `Unhandled`/`undefined instruction` oops | An unsupported register (D11) | SR | Record ESR text; D11; a configuration change reruns T1-T2 |
| F21 | `qvm.rc` before teardown, `l_panic` | Guest panic, `panic=-1` rebooted it | SR | Read the capped tail and COM3 stream |
| F22 | A heartbeat missing, qvm alive | Host script stalled or qvm hung | SR at guard | Record the last `S1 STATE` |
| F23 | `S1 CANARY … verify=bad` | A write into a watched range | SR | Item 4 not met; stop board work until explained (RT:246). **2026-09-14 (owner, D8 option 1):** writer diagnosis first, §15; B2 stays NOT MET on data until §15.6's rule says otherwise |
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
| R17 | No firmware or BPMP user of window 2 hides from `/proc/iomem` (K5) | HYPOTHESIS | B2, B4 canaries (one run each). **2026-09-14 (owner, D8 option 1):** writer diagnosis first, §15 (R51 refines this row); B2 stays NOT MET on data until §15.6's rule says otherwise |
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
| D8 | If B2 fails on data (§5.3) | stop S1-F and record kill condition 1 for the 11c candidate; commission a new range derivation from the three-boot `/proc/iomem` comparison, as a new design revision that reruns B1 and B2 | **Stop and record.** 11c found one candidate; another range is new design work, not a retry. A defect is fixed and rerun without a decision. No window-1-only continuation is offered: item 4's layout, B5 and freeze item 6 need window 2. **2026-09-14 (owner, D8 option 1):** writer diagnosis first, §15; B2 stays NOT MET on data until §15.6's rule says otherwise |
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
- **T1 or T2:** (**2026-09-14:** both have run under TCG, §14.10 and §14.11)
  - ~~Whether `/dev/shmem` accepts `mkdir` for `s1con`'s hit directory. A refusal would show as `S1 FAIL reader hvc0`.~~ **2026-09-14:** it does on the TCG host: T2 wrote `open.hit` (§14.11).
  - qvm's logger line format, and the wording and stream of its FDT-saved message; `logger_errors` may need tuning. **2026-09-14:** partly answered by T1 attempt 1. The FDT message reads `FDT saved to '<path>'`, and a configuration error prints `[file:line] message`; the export shows CRLF line ends. Both came from the dryrun's stdout and stderr taken together, so the stream is still unknown, and the logger's own format for `error`, `fatal` and `internal` is still unseen (§14.9). **2026-09-14:** the clean dryruns of T1 attempt 2, T2 and T3 printed `Exiting: dryrun complete` after the FDT message (§14.10, §14.11). The stream and the logger's own error format are still unknown.
  - ~~R13's 596 MiB gate under the TCG host's 1 GiB `OPT_RAM` with QEMU's `-m 2G`.~~ **2026-09-14:** answered under TCG for the `dryrun`, `boot` and `hold` modes (§14.11). The board's gates stay with B3 and B4.
  - Whether qvm accepts `unsupported <class> abort`, which `s1-d1` uses. **2026-09-14:** still open; no TCG run used `s1-d1`.
  - ~~**2026-09-14:** whether `s1con`'s open of the slave `/dev/ttyp3` returns before qvm holds the master. The readers still start before the launch; if a slave open waits for its master, T2 stops at `S1 FAIL reader hvc0` (§14.9).~~ **Addressed 2026-09-14 (§14.10):** `s1con` now starts right after qvm is launched, and its open wait is the first wait after the launch. Two things stay for T2:
    - whether a slave open waits for its master, is refused (`s1con: open /dev/ttyp3: …` and `S1 FAIL reader hvc0`), or returns early and ends `s1con` on its first read (`STAMP eof` or `STAMP read-error` in `s1con.stamps` before teardown, then `l_kernel` with no `i_start`, which reads as §5.3 stage 2 unless `s1con.stamps` is checked);
    - whether qvm reaches its hostdev inside the dryrun's bound after a launch.
    - **2026-09-14 (T2, TCG):** the order worked in this run. The open wait named `open.hit`, the needle waits returned, and `s1con.stamps` held no end of file before teardown. So neither a refusal nor the early-end race occurred in this TCG run. Neither point is answered: whether the open waited for the master is still unobservable, and the open wait's `bwait` line does not show when qvm reached its `hostdev` (§14.10). Both points stay open, and on the board the timing differs (§14.11).

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
- **2026-09-14, after T2 and T3 (§14.11):**
  - **The header's 2026-09-14 note:** "Nothing has run under QEMU or on the board". T1-T3 have since run under TCG; nothing has run on the board.
  - **§9's "Answered by" column:** it does not say that the TCG leg answered R1-R10, R12-R14, R29 and R31, or R22's text-size half. The board halves of R3, R6, R14 and R22 stay with B3.
  - **§6.3:** it does not say that `stamp` starts before the launch and `s1con` after it (§14.10).
  - **§14.10, "What this does not show":** T2 has since run with the new order under TCG, and the raw slave path and probe 1 are answered there. Whether the slave open waits for its master, and when qvm reaches its `hostdev` after a launch, stay unobservable; every item stays open on the board.

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

### 14.11 T2 and T3 under TCG (2026-09-14)

Both runs below are under QEMU TCG on the PC, from images built from commit `00c61db`. Nothing ran on the board. The records are private and git-ignored, and no figure, hash, size, address or duration from them is copied here.

**T2 passed clean (`-Mode boot`).**
- **Before the launch,** as in T1:
  - the memory gate passed, and so did md5 pre;
  - the dryrun exited 0 with no qvm diagnostic, and its FDT was byte-identical to T1's;
  - `memcanary --selftest` passed.
- **The launch.** `s1con` started after qvm, and `open.hit`, `i_ready.hit` and `shell_ok.hit` were all written. No `S1 FAIL reader hvc0` appeared. When qvm opened its `hostdev` is not observable, since the open wait's `bwait` line names `open.hit` only (§14.10). `s1con.stamps` held `STAMP eof` only at teardown. Neither a refusal nor §14.10's third outcome, an early end of file, occurred.
- **pl011 (the capped head).** The stock 5.15-tegra kernel reported qvm's machine model, earlycon on the pl011 vdev, PSCI found through the device tree, three CPUs brought up, the initramfs unpacked, `hvc0` enabled, and `Run /init`.
  - Lines taken as harmless: UEFI not found, a faked NUMA node, ACPI disabled, PSCI's `MIGRATE_INFO_TYPE` unknown, no cache hierarchy detected, and a jitterentropy initialisation failure. That last one is taken as an effect of the emulated host (HYPOTHESIS).
- **hvc0.** Our `/init` did the following, in order:
  - printed `S1-INIT start`;
  - mounted `/dev`, `/proc` and `/sys`;
  - reported the kernel release and the configured cmdline;
  - found CPUs 0-2 online;
  - printed `S1-INIT ready`.

  busybox `ash` then started, warning that job control is off, since it has no controlling tty. Probe 1's echo shows the literal `$((40+2))`, and the next line is `S1-SHELL-42-OK`: the shell's answer, not the echo.
- **Teardown** took the script's `term` path. md5 post was ok, and the log shows `S1 FAIL_STATE none`. `parse-s1.py run` gave L1-L5, `item1_t2=pass`, item 5 ok and `verdict=pass`.

**Plan pass item 1 is met under TCG** by T1 attempt 2 (§14.10) and T2, with one configuration: T2's `conf_sha256` equals attempt 2's.

**T3 passed clean (`-Mode hold`).** It is a rehearsal, not pass item 4.
- The same checks ran before the launch, with the `hold` mode's memory gate, and probe 1 was answered.
- The hold printed these lines, in order:
  - `S1 ALLOC hold … fill=ok`;
  - `S1 HOLD start`;
  - ten `S1 HB` lines, each with `qvm=alive rc=absent`;
  - `S1 HOLD end qvm=alive`.
- Probe 2 was written and answered, as `S1-END-43-OK` under the echoed `$((42+1))`. The allocation then gave `verify=ok`.
- The guest's `hvc0` shows the ten heartbeat lines, then probe 2's answer.
- Teardown matched T2's: md5 post ok and `S1 FAIL_STATE none`. `s1con` ended only at teardown, with both probe writes done.
- `parse-s1.py run` gave L1-L6, `t3=pass` and item 5 ok, and its `bb_text_bytes` estimate was under R22's limit.

**Risks answered, under TCG only (§9).** The board may still differ on every one.
- **R1:** qvm loads the EFI-stub arm64 `Image` with a bare `load`. It placed the initrd right after the header's image size (T1).
- **R2, R4:** `set fdt-dump-file … dryrun` works after `@conf`, and the cmdline reaches `/chosen/bootargs`. The guest's own cmdline matched (T1, T2).
- **R3:** the generated FDT carries every gating node, and 5.15 boots on it. B3 keeps the board half.
- **R5:** the gzip cpio passed unchanged and was unpacked.
- **R6:** 5.15-tegra boots on a generic tree with no Tegra nodes. B3 keeps the board half.
- **R7, R8:** earlycon works on qvm's pl011 vdev, and the virtio port became `hvc0`.
- **R9:** qvm accepts the master as `hostdev` (T1 attempt 2), and input reaches the guest through the raw slave (T2).
- **R10:** `$(( ))` works, which completes R10 after T0.
- **R12:** the `cpu cluster _cpu-N` lines are accepted under `-smp 4`, and three CPUs came online.
- **R13:** the memory gate passed in the `dryrun`, `boot` and `hold` modes on the TCG host.
- **R14:** `psci-supported auto` found PSCI on the TCG host's tree, and the secondaries started. B3 keeps the board's tree.
- **R29:** with no virtio-rng, the shell was not blocked.
- **R31:** both pl011 needle texts matched (L3, diagnosis only).
- **R22:** only T3's text-size half is answered. B3 keeps the black box itself.

**Still open for the board.**
- **B0:** pre-flight, staging, `p0` and the kexec tree's sha256 (W).
- **B1:** the option-off startup regression.
- **B2:** window 2, the canaries, `S1 ASINFO` and the `alloc` path (R16-R19, R37-R40).
- **B3:** the native boot, pass item 2. It covers R3, R6 and R14 on the board's own tree, R15 (A78AE registers), R20, R21, R22's black box, R23, and R28 (the TCG FDT against the board's).
- **B4:** the ten-minute run, pass item 4: canaries, the end probe, and R24.
- **B5:** only if D1 keeps the QNX guest, pass item 3 (R25, R26, R35).
- **Item 5:** its stamps are owed by every board run.
- **The slave open.** T2 shows that the §14.10 order works under TCG. It still cannot show whether `s1con`'s open waited for the master, and the race §14.10 names could appear under the board's different timing.
- **`s1-d1`:** whether qvm accepts `unsupported <class> abort` is still untested, since no run used `s1-d1`.

**What this does not show (§10).** No timing of any kind. No isolation or containment. Nothing about A78AE, the board's PSCI, window 2 or physical pinning, and a TCG pass does not predict a native pass. No GPU result, and not publishable before the 4.6(i) consultation.

### 14.12 The first board session: B0, B1 and B2 (2026-09-14)

The owner was at the board, with the TX wire off. The images are the ones rebuilt from `00c61db` (§14.11). The records are private and git-ignored, and no figure, hash, size, address or duration from them is copied here.

**B0 met, after two harness fixes.** These are two deviations from §6.6's p0 as designed, both in the harness, neither a board finding.
- **Pre-flight and staging** passed for all four board images.
- **The first p0 was NOT MET** on two gates:
  - `item6_iomem` listed an entry inside the candidate window 2. It was the running L4T kernel's own image (`Kernel code`, `reserved`, `Kernel data`), placed there by KASLR. That is not a reservation, and it moves with every boot.
  - `landing` failed because the board's kernel has no dynamic debug, so the kexec landing line cannot be read.
- **The fixes (`e4b3e03`, after an adversarial review):**
  - `item6_iomem` now excludes only that exact triple: one `Kernel code` and one `Kernel data` at the same indent, with exactly one contiguous `reserved` between them. Anything else in the window still fails. Seven self-test cases were added.
  - `landing` is recorded as SKIPPED when dynamic debug is absent. The guard is the shim's own landing check (`BAD-LANDING`, then a PSCI reset before any QNX code), plus B1's tokens and `parse-s1.py`'s L0 for B2 and B3, which require the expected entry PC and no `BAD-LANDING`. B4 and B5 report L0 without gating on it.
- **The p0 rerun passed** on all four images.
- **The reboot to a fresh boot** hit the known long-uptime pattern: L4T oopsed in its shutdown path and came back through a watchdog reset. The bootloader slot state was unchanged.

**B1 met.**
- **Tokens (§6.6).** Present: the shim at EL2 with the expected PC, the startup's WDT0 line, `procnto up` and the image's reset line. Absent: every `-b` line (`ram w2`, `gpu range`, `canary`), `BAD-LANDING`, `EXC` and `EL!=2`.
- **The return.** The firmware banner followed the reset, the reset reason was a software main reset, and the bootloader slot and `nvbootctrl` matched the session's first reading.
- **b1-compare: a third deviation.** M1b R2's raw black box is not in the repository, so the reference is the curated R2 COM3 capture's section from the shim line to the reset line, with its trailing blanks and blank lines removed. After `b1_normalise`, five places differ, and nothing else:
  - the WDT0 control value read by the shim at hand-off. The firmware and L4T set it, not the image. That the preceding watchdog reset explains it is a HYPOTHESIS;
  - two syspage map entries, which depend on the startup's size (the S1 startup carries the `-b` code);
  - `smpcheck`'s sample counts, which are figures. After B2, `b1_normalise` masks them, trailing blanks and blank lines. On the unmodified inputs it now leaves only the other three kinds;
  - `pidin`'s thread total, one higher than R2's. Unexplained, and not a B1 token.

  None of these points at the option-off startup changing QNX's behaviour.
- **A harness defect found in B1's output (`60f830a`).** The privacy scan used `grep -c … || echo 0`. With no match that yields two zeros, so the sum failed. A copy with hits in another class was then recorded as clean and kept raw. The fix defaults each count instead, and three redaction self-test cases were added. B0's and B1's copies were rescanned by hand: no address, MAC or user name. The hostname class is rechecked with the board up.

**B2 NOT MET, on data: kill condition 1 for the 11c candidate (§5.3, F23, D8).** It ran on a fresh, unused boot inside the quiesce's uptime limit, after a clean quiesce (four modules removed, no Oops, no SMMU lines), with the privacy fix above in the harness.
- **What held.** Startup added window 2 and left the GPU range out. It filled all three canaries, and procnto came up. `S1 W2 reflected=yes`, and `S1 ASINFO` showed both windows in sysram, three canary entries, and neither a canary nor the GPU range in sysram. c1 and c3 verified at both checks, and the `alloc` path filled and verified.
- **What failed.** c2, the canary at the very start of window 2, gave `verify=bad` at both checks. The first mismatching word was its first word each time, but the number of mismatching words differed between the two checks. Something wrote the range after startup's fill and kept writing while QNX ran. `parse-s1.py` gave `verdict=fail` on L1, b2 and `canaries_all_ok`, with L0, L7 and item 5 ok.
- **The return was clean.** The image's own reset brought L4T back, and the bootloader slot and `nvbootctrl` matched the session's first reading.
- **Not the writer (VERIFIED):** procnto's allocator. The canary was out of `ram_list` before the fill, and `S1 ASINFO` shows it outside sysram.
- **Candidates (HYPOTHESIS, untested):**
  - an L4T device still doing DMA after the kexec, into buffers its kernel had placed at the low end of the RAM above 4 GiB: a network or USB controller's rings, say;
  - a firmware or coprocessor user that `/proc/iomem` does not show (K5, R17).

  memcanary prints only a count, not the mismatching words, so their content cannot yet tell these apart.
- **What follows, per the design.** S1-F stops, and B3 to B5 do not run. No window-1-only continuation is offered (V14). Under D8, the next step is a new design revision, owned by the owner's decision, which reruns B1 and B2: another range derived from the three-boot `/proc/iomem` comparison, a diagnosis of the writer first, or both. D8 names this record `r/s1-runs.md`. Because S1's figures stay private, the number-free record is this section, and the private run notes sit beside the B2 records.
  **2026-09-14 (owner, D8 option 1):** writer diagnosis first, §15; B2 stays NOT MET on data until §15.6's rule says otherwise.

**What this does not show.** B0 and B1 show that the harness, the staging and the option-off startup work on the board. B2 shows that 11c's window-2 candidate is not free after the quiesce, at its lowest canary. It does not show that the rest of window 2 is free, since two canaries of 16 MiB sample a range of more than 2 GiB, and the allocation checks its pages only for the moment it holds them. It shows nothing about a Linux guest on the board, and no timing.

## 15. Revision 3: writer diagnosis for B2's c2 canary (D8 option 1, 2026-09-14)

Phase 3b. **Revised 2026-09-14, after three adversarial reviews (safety, power, feasibility; outcomes in §15.11).** Proposed as a new **§15 of `results/orin-native-port/20260909T1100Z/s1-design.md`**. Older sections get dated one-line pointers, not rewrites (§15.8). Nothing in this revision has been built or run. It creates no code, configuration or image. It is a synthesis of four desk analyses (Linux-side mechanisms, a QNX-side read-only instrument, harness quiesce variants, design rules with classification) and three reviews. §15.10 records where the analyses disagreed; §15.11 records every review change and how conflicts between reviewers were resolved.

**Hard rules kept while writing.** No board contact, no download, no repository edit, no QNX-shipped binary read. Web use was limited to documentation pages, and those reads were the analyses'.

**Evidence classes** as in the header of s1-design.md: VERIFIED, VENDOR_CLAIM, HYPOTHESIS, UNKNOWN. Two additions:
- **"VERIFIED (private record)"** means read in a git-ignored run record. The text quotes no figure from it.
- **"reported VERIFIED"** means another analysis read it, and this draft did not re-read it.

**Number-free, and D29-gated.** This text contains:
- no count, offset or page-class figure from any run;
- no uptime, boot id or duration from a run;
- no IOMMU group, PCI address, DMA mask width or kernel-placed address read in a run;
- no MAC, IP, SSID, user name or hostname.

Addresses that appear are design constants already public in §3.3, or page-frame numbers derived from them. Durations that appear are design constants (wait bounds), never results. The run facts behind §15.2 are in `results/orin-native-port/20260914T045838Z/s1/B2/` and `.../s1/diag/` (git-ignored).

**Pushable only after D29.** Three kinds of wording in this text are reserved for the owner under D29 and are marked **[D29]** where they state a run fact: the direction of E2's count change, that the harness's ssh link is wireless, and which device classes the removal set holds. If D29 declines any of them, §15 is not pushed as written; the push carries the neutral substitutions in §15.8's table instead.

---

### 15.1 Purpose, the owner's decision, scope

**Decision (owner, 2026-09-14, D8 option 1).** B2 was not met on data: c2 gave `verify=bad` at both checks while c1 verified. By §5.3 that is kill condition 1 for the 11c candidate, and S1-F stopped. The owner chose to **find the writer first**:
- **A quiesce shortfall** is a harness defect. An example is a Linux device left doing DMA after kexec. It is fixed in the harness, and B1 and B2 are rerun.
- **A firmware or range-owned writer** confirms kill condition 1. A new range is then derived, in revision 4.

**Purpose of this revision**
1. Put the next board runs in order, cheapest and most discriminating first. Harness-only rungs on the staged `s1-h1` come first, so they can run in the owner's current session.
2. Pre-register the rule that classifies B2 before any diagnostic result exists (§15.6).
3. Specify one image-changing instrument that shows *what kind of* data sits in c2, without printing it, and that also watches the rest of sysram through a large timed hold (§15.4.8 J6).
4. Bound the diagnosis and name the decisions reserved for the owner.

**Scope**
- **In:** the c2 writer's class, B2's classification, and the harness fix if there is one. Also the exposure of window 1 and of earlier rungs, as a risk statement.
- **Out:**
  - S1-F progress: B3-B5 stay stopped;
  - any change to the startup binary, window 2's size or the canary constants (each reruns B1, so revision 4);
  - any change to the `s1-h1` image or its sources (the B2 rerun must be judged by §6.7 unchanged);
  - GPU pass-through;
  - any timing.

**Contradictions this revision resolves** (the §1 table continues)

| # | Conflict | Resolution |
|---|---|---|
| C17 | F16 and F23 say "stop board work until explained"; D8 option 1 needs board runs | The stop is lifted **only** for §15's J rungs, under D20. B3-B5 stay stopped |
| C18 | §5.3's defect list has no quiesce class, so c2 `verify=bad` is data whatever its cause | A pre-registered class Q (quiesce shortfall) with fixed evidence criteria (§15.6). It is adopted before J2 runs, so the rule cannot be fitted to a result |
| C19 | D8's text says a revision "reruns B1 and B2"; §5.3 says "rerun B1 if startup changed" | Owner ruling D26. Recommendation: rerun B1 after any harness fix, since the quiesce is part of B1's entry |
| C20 | §0 and §3.8 (RT:81) say the other masters are "untranslated because Linux disables the SMMUs". Under SMMUv2 bypass, a master restricted to 32-bit DMA addresses cannot address c2 | Kept as R46 (HYPOTHESIS). The consequence is drawn in §15.3: a c2 writer points first to a master with no SMMU, to firmware, or to QNX, and the exposure moves toward window 1 (§15.8). This is design reasoning about any 32-bit master, not a statement about which device on the board has which mask |
| C21 | §14.12 wrote that something "kept writing"; **[D29]** the second mismatch count was **lower** than the first, which a plain overwriter cannot produce | §15.2 E2 restates the observation. "Writer" becomes one hypothesis beside read instability (H3). Public wording of the direction is D29's |
| C22 | §3.8: memcanary prints only a count, so data cannot separate the hypotheses | A second read-only binary, built from the same source, with classes, counters and page bitmaps only (J6). `memcanary`, its pin and every existing kimg stay byte-identical |
| C23 | The private page-ownership snapshot comes from B2's return boot, not quiesced, not at kexec | J2 and J4 take the same reads on the boot that jumps, before and after the quiesce, over ssh. **No snapshot is taken at the jump:** pre-kexec page flags cannot predict where a device writes after kexec under bypass or a stale translation (R45), and a final snapshot would add block I/O on the jump boot (§15.11, power review) |
| C24 | B2's note called the nvgpu PMU timeouts "known quiesce noise", implying the `rmmod` causes them | **VERIFIED (text):** the public M1 capture, from a kexec without the module quiesce, shows the same two timeout lines and the pending-interrupt line just before the SMMU lines. So the error **lines** come with nvgpu's teardown on either path, not only with the `rmmod`. **Not shown:** that the GPU's state or the pages it held are the same after `rmmod` and after the shutdown path. The same lines do not imply the same state, so C24 does not show that a no-`rmmod nvgpu` arm is uninformative. J5 stays unrun for budget and fixed-setting reasons (§15.10 item 5) |

**Still forbidden.** §7.3 applies in full, and §2 rules 5, 6, 6a and 10 are unchanged except for the one dated rule-5 exception in §15.4.3 (the detached sequence's own three files). New Never items:
- No `rfkill` command at all (state is read from sysfs), no `nmcli`, `iw`, `ip addr` or other NetworkManager or wpa_supplicant state change, and no `systemctl enable|disable|mask`. Also no write under `/etc`, `/boot` or `/var/lib`, no kernel command-line change, and no `reboot -ff`. Reason: rfkill and NetworkManager radio state persist across boots (VENDOR_CLAIM, systemd-rfkill(8) and the NetworkManager rfkill page), so the next boot could come back without ssh while COM3 is receive-only.
- No write to a PCI sysfs `remove`, `rescan`, `reset`, `driver_override`, `new_id` or `power/control` file; no `dd` with `of=` on any `/sys` path; no PCI configuration write other than the one `setpci ... COMMAND=0000:0004` form of §15.4.3.
- No read of a netdev or Bluetooth `address` file, a USB `serial` attribute, `lsusb -v` or `hciconfig`.
- No dump of canary word values or bytes anywhere, unless D28 later approves a restricted form. No packet capture on L4T.
- No `/dev/mem` or `devmem` read on L4T.
- No MMIO read of SMMU, PCIe configuration or GPU registers from QNX: an unclocked block can raise an SError at EL2, which is a power-cut class.
- No change to the startup source, window or canary constants, `memcanary.c` without its macro, or the `s1-h1`, `s1-n1`, `s1-n2` or `s1-d1` sources inside revision 3.
- No diagnostic rung without the owner at the plug, no quiesce on a boot not freshly booted, and no override of the uptime limits, which the detached sequence also enforces at the moment it would issue (§15.4.3).

---

### 15.2 Evidence so far

| # | Fact | Class | Source |
|---|---|---|---|
| E1 | **B2:** startup added window 2 and kept the GPU range out. It filled c1, c2 and c3 before procnto. `S1 W2 reflected=yes`; `S1 ASINFO` showed both windows in sysram, three `s1canary` entries, and neither a canary nor the GPU range in sysram. c1 and c3 verified at both checks, and the window-2 allocation filled and verified. c2 gave `verify=bad` at both checks, with its **first word** the first mismatch both times | VERIFIED (private record, one run) | B2 `b2-note.log`, `parse-s1.txt`, COM3 |
| E2 | **The mismatch count changed between the checks. [D29] The second was lower.** `check_words` recounts from scratch on each call (`tools/memcanary.c`, `check_words`). So some words read back as exactly `splitmix64(base + offset)` again. A writer that only overwrites cannot do that. It needs a writer that restores earlier content (save, use, restore; a status bit set and later cleared; a copy written back) or a read path that does not return what is stored | VERIFIED (arithmetic on the tool's semantics, if both reads were faithful) | same |
| E3 | **Bad before any S1 memory user ran.** The host script order is `asinfo`, then the start verify, then `alloc`, then an unheld wait, then the end verify (`startup/s1-host.ksh.in`, host block). The procnto allocator is excluded by `canary_in_sysram=no`. The `alloc` checks its own pages only straight after its fill; it holds nothing during the wait, so B2 shows almost nothing about a live writer elsewhere in sysram | VERIFIED (source) | source; B2 |
| E4 | **Linux turned SMMU translation off before every kexec checked.** All three SMMU instances printed `disabling translation`, then `kexec_core: Starting new kernel`. Seen in B2, B1, every M3 and M4 COM3 capture checked, and the public M1 capture | VERIFIED (text only; register state after kexec never read) | COM3 captures; `logs/sample-boot/orin-native-m1-first-procnto.log` |
| E5 | **The same nvgpu teardown error lines appear with and without the module quiesce:** two `PMU wait timeout expired` lines and one pending-interrupt line. In B2 they fall during the quiesce; which step triggers them is UNKNOWN. In M1, which had no module quiesce, they fall just before the SMMU lines | VERIFIED (text) | same (C24) |
| E6 | rtcpu's ivc-bus children print `ivc channel driver missing` during shutdown. RCE's run state after kexec is UNKNOWN | VERIFIED (text) | same |
| E7 | **Zones on L4T:** ZONE_DMA covers window 1; ZONE_DMA32 is empty; **ZONE_Normal starts exactly at window 2's base, which is c2's base** | VERIFIED (one boot, private record) | `diag/d0-note.log` |
| E8 | **Page ownership on B2's return boot, not quiesced:** c1's pages all free; c2's pages mostly slab, with page tables, file cache and free pages; c3 page cache; the lowest part of ZONE_Normal dense with slab. It is not the state at B2's kexec, and it describes Linux's CPU-side ownership only | VERIFIED (one other boot; limits in C23 and R45) | `diag/d0-kpageflags.log` |
| E9 | **DMA-capable devices on that boot [D29]:** a wireless network function on an out-of-tree PCIe driver, behind an SMMU, Bus Master set, carrying the PC's ssh; a wired Ethernet function on an out-of-tree driver, no link; an NVMe drive; the Tegra xHCI with hubs and a Bluetooth radio. Coprocessor groups: BPMP, RCE, DCE, SPE, host1x contexts and display. Default IOMMU domain translated; `arm_smmu disable_bypass=Y`. Each device's DMA mask width is recorded privately and is not public text | VERIFIED (one boot) | `diag/d0-layout.log`, `d0-shutdown.log` |
| E10 | A kallsyms search for driver shutdown handlers is **inconclusive**: it also misses handlers that certainly exist | VERIFIED (limit) | same |
| E11 | **The GPU has no `iommus` property and is `dma-coherent`,** so its DMA is CPU-physical even under L4T | reported VERIFIED (live DT on the local research branch; RT C2, C3) | RT |
| E12 | **The instances are Arm SMMUv2 (MMU-500), and the live DT has no ITS or `msi-controller` node** | reported VERIFIED (research-tegra234.md; RT C4, C13) | same |
| E13 | **RCE's allocatable IOVA window,** from the `rce-reservation` node's `iommu-addresses`, overlaps the upper part of window 1, and c1 lies inside it. `camdbg_carveout`, the only node whose allocation range starts at window 2's base, is `disabled` | VERIFIED (live DT on the local research branch; addresses kept out of public text) | `raw/orin-live.dts` on `research/gpu-passthrough` |
| E14 | **`kexec -s` jumps with no purgatory,** and the shim line shows the kexec tree far from c2 | VERIFIED | `r/research-kexec-tcu.md`; B2 COM3 |
| E15 | **Under SMMUv2, `sCR0.CLIENTPD=1` makes every transaction bypass translation;** `USFCFG` applies only while CLIENTPD is 0 | VENDOR_CLAIM (Arm IHI 0062; OSDev summary) | analyses' reads |
| E16 | **Upstream's SMMUv2 shutdown path puts the SMMU into bypass on kexec,** and devices still doing DMA then write untranslated addresses | VENDOR_CLAIM (linux-arm-kernel thread, 2024-03); NVIDIA's 5.15 fork not read | same |
| E17 | **Linux clears PCI Bus Master in `pci_device_shutdown` during kexec** for devices in D0-D3hot | VENDOR_CLAIM (2012 patch text); fork not read | same |
| E18 | **systemd arms the Tegra hardware watchdog under L4T;** the known long-uptime shutdown Oops came back through a watchdog reset | reported VERIFIED (B2-session COM3); the return VERIFIED in §14.12 | B2 COM3; §14.12 |

**What this evidence does not show**
- **Which device, firmware or code wrote c2.**
- **Whether `CLIENTPD` was actually set after kexec,** or whether PCI Bus Master was actually cleared on this kernel.
- **Whether the result repeats:** there is one run.
- **What c2 held at B2's kexec,** or what the mismatching words contain.
- **Anything about the rest of window 2 or of window 1** beyond c1 and c3, including whether a writer landed in sysram during B2 (E3).

---

### 15.3 Hypotheses, ranked, and what separates them

**Constraints any explanation must meet**
- **K-a:** only c2 is bad; c1 and c3 are clean. (Only three 16 MiB windows were watched; K-a says nothing about the rest of sysram.)
- **K-b:** the first bad word is at c2's first word, twice.
- **K-c:** the count changed, so something was live after startup's fill.
- **K-d:** words returned to the pattern (E2).
- **K-e:** c2 was bad before any S1 memory user ran.
- **K-f:** c2 is outside sysram.
- **K-g:** under Linux the same pages hold live slab (weak, one other boot). A writer that is *always* active under Linux would regularly corrupt L4T.

**Pivot (HYPOTHESIS, strong, from E4 and E15-E17).** A translated master still active after kexec writes at its old IOVA used as a physical address.
- iommu-dma allocates PCI IOVAs below 32 bits first, top-down (HYPOTHESIS, from memory; Q16).
- If so, the removable PCIe masters land below 4 GiB, not at c2.
- Reaching c2 would need a Bus Master violation **and** translation still in force (or a stale translation, H4s).
- A GPU with no SMMU (E11), firmware, a coprocessor with physical access, or QNX need neither.

| Rank | Hypothesis | Fit | Prior | Discriminating observation |
|---|---|---|---|---|
| **H1** | **GPU residue.** The ga10b or one of its falcons keeps writing CPU-physical pages nvgpu used, after its teardown errors (E5) | K-a and K-b if an nvgpu page was at the low end of ZONE_Normal; K-c yes; K-d plausible (firmware working memory rewrites fields; HYPOTHESIS); K-g consistent, since writes after teardown never meet a live Linux owner for long | medium | **J4 bad** (removable masters excluded) **and** a UEFI-entry arm clean (J7a). Supporting only: J6 bitmaps show pointer-like or structured classes, and the J6 fill-rate row changes. The J2 and J4 page snapshots carry **no evidential weight** for H1 (R45) |
| **H2** | **A firmware or coprocessor user of window 2's base that `/proc/iomem` does not show** (refines K5, R17): BPMP or EMC work, secure side | K-b strong: the range starts at a region, zone and possibly die boundary. K-d fits save and restore well. **K-g against**, unless shutdown or the quiesce triggers it | medium-low | **J4 bad and J7a (UEFI) still bad.** Supporting: J6 shows `healed` words, pattern copies or periodic whole-page restores, `small32` ring-counter-like words, and no Linux-pointer classes |
| **H3** | **Read instability at the base of window 2:** retention or a marginal read after an EMC change. No writer | The only candidate that explains K-d without a writer. Against: the allocation verified over window 2, and Linux uses these pages | low | J6's F34 rule: oscillating re-reads (`osc`, A-B-A) above 0, `flip2` dominant, and no in-progress changes (`prog` 0) |
| **H4** | **A removable Linux DMA master** (wireless, Ethernet, NVMe with a host memory buffer, xHCI with its falcon) with translation still in force | Needs two failures (Bus Master, then bypass). K-d: network RX appends contradict it (HYPOTHESIS), but a descriptor ring whose device sets and later clears status or ownership bits in existing words, or an NVMe host memory buffer write-back, fits K-d (HYPOTHESIS) | low | **J4 clean** where J2 is bad. Supporting only: J6 positive signatures (§15.4.8; absence excludes nothing) |
| **H4s** | **Sub-hypothesis of H4: a stale translation.** A master keeps DMA through SMMU page tables that were Linux pages and became QNX sysram after kexec; QNX's use of those pages moves the write targets | Fits K-c; the change in c2's count straddling B2's allocation fill would fit a target move caused by the fill | low (needs R46 false) | J6's fill-rate row (label c against label b, §15.4.8), then J4 |
| **H5** | **QNX-side**, anchored at the window-2 `ram` entry base (R38's residual) | K-b strong, K-c yes, K-d weak; K-f excludes only the allocator | low | J6: page-table or kernel-address classes. Separated only by revision 4's base shift |
| — | **RCE under bypass** | Lands in its IOVA window (E13), not c2 | not a c2 candidate | Window-1 exposure (§15.8). c1 sits there and was clean once |
| X | procnto allocator; S1 `alloc`; startup's fill; kexec purgatory and segments; GIC LPI tables; SMMUv3 queues | K-f; K-e; not live (K-c); E14; E12 | **excluded** | — |

**What J4 can and cannot separate.** J4 (removal of the removable masters) tests H4 and H4s only. It gives **no evidence on H1, H2, H3 or H5**. It is kept as the first test arm because it needs no image, it is the only arm whose clean result is itself a harness fix, and its bad result is the precondition of every class except Q (§15.6). The decisive H1-versus-H2 test is J7a.

---

### 15.4 The diagnostic rung ladder

**Prefix `J`.** A repository search found no `J<n>` ids. The harness analysis's R0/W0/D1-D3 names would collide with the R and D tables.

**Default record directory:** the session's existing `<rec>` (`results/orin-native-port/20260914T045838Z/s1/`), so `used-boot-ids.log` keeps guarding the fresh-boot rule. Each rung goes to `<rec>/J<n>/`, an attempt to `J<n>-aN`, and a refusal to `J<n>-refused-<utc>`. **No J rung ever creates or writes a `B*` directory** (a harness self-test proves it), and B1's and B2's records are never touched.

| Rung | Where | Image | Needs a rebuild | Question | Today? |
|---|---|---|---|---|---|
| J0 | PC | — | no | desk reads; harness implementation and self-tests; pre-registration | before J1 |
| J1 | L4T only; no quiesce, no kexec; ends in a reboot | — | no | census: tools, topology, mounts; marker and transient-timer path to COM3; the trace | yes |
| J2 | kexec, issued by the detached sequence with an **empty** removal set, ssh kept up | `s1-h1` (staged) | no | **matched control:** does c2 go bad again under exactly J4's timing and issuing context? | yes |
| J2b | kexec, `cmd_run`'s B2 flow with no additions | `s1-h1` | no | **only if J2 is clean:** a pure B2 repeat, to separate intermittency from the J additions | in J4's slot, only after F33 |
| J3 | L4T only; quiesce, no kexec; ends through the fallback timer | — | no | **rehearsal** of the detached removal that drops ssh | yes, after F32 |
| J4 | kexec, issued by the detached sequence with the removal set | `s1-h1` | no | **test arm:** removable DMA masters removed before kexec | yes, after J3 met |
| J5 | kexec | `s1-h1` | no | *reserved:* no-`rmmod nvgpu` arm | only by D24 |
| J6 | kexec, in the arm §15.6 names | new `s1-j1` (startup unchanged) | yes | **watcher:** content classes, heal, oscillation and progress counts, page bitmaps, and a large timed hold over sysram | next session |
| J7 | — | — | — | reserved arms: UEFI entry, and the rest (§15.4.9) | revision 4 or a D-row |

**Boot chain for today.** Each quiesce is on a fresh, unused boot, and each start meets the start-margin rule of §15.4.3 (start uptime plus the rung's worst case under 1,800 s). **Before each rung's capture starts, the previous capture is stopped**, and each capture file name is used once (`<rec>/used-captures.log`).
1. J1 on the current boot, ending in the reboot that J2 needs anyway.
2. J2 on that fresh boot.
3. After J2:
   - **F32** (c2 bad at both checks): J3 on J2's return boot, then J4 on J3's return boot.
   - **F33** (c2 ok at both checks): J2b on J2's return boot, then stop and memo.
   - **F32a or F32b** (bad at one check only), **F39**, or a second F40: stop and memo; J6 first, next session.
4. If a start misses its margin, `s1-board.sh reboot` first. A reboot is not a diagnostic run.

#### 15.4.1 J0: desk and implementation (PC)

- **Q16 (documentation, mailing-list and patch-discussion pages only; no clone, archive, tree or per-file source download):**
  - what upstream v5.15's SMMUv2 shutdown and remove paths write to `sCR0`;
  - `pci_device_shutdown`'s Bus Master clear and its `kexec_in_progress` condition;
  - `device_shutdown()`'s `initcall_debug` print and its console level;
  - whether `initcall_debug` is writable at run time;
  - iommu-dma's 32-bit-first IOVA policy;
  - `setpci`'s `value:mask` semantics (setpci(8));
  - what `systemctl is-system-running` reports during a kexec shutdown (systemctl(1)).

  Each answer re-labels R46-R48, R56, R72-R74 (VERIFIED against upstream documentation only; the fork stays unread). Reading upstream function bodies through per-file web source views is **not** assumed to be allowed; it is D33's.
- **Q17:** is the staged `s1-h1.kimg` still what HEAD produces? Before J2, J2b, J4 and any B2 rerun, the harness checks that `s1-h1.params`' `kimg_sha256` is a real hash (not `-`) and equals the staged kimg's sha256. No rebuild is needed for J2-J4.
- **Implementation of §15.5 A** (harness-only), its self-tests, and a local commit before J1 with a number-free message. **The commit names no driver:** devices are resolved at run time from PCI class codes, driver links and J1's private set file (§15.4.2). **Pushing that commit, or any text naming the removal set or the wireless link, waits for D29.**
- **Pre-registration.** Before J2 runs, `<rec>/J-prereg.log` records:
  - the commit, `git diff --quiet HEAD` of the harness, `kpf-decode.py` and `parse-s1.py`, and their sha256;
  - §15.6's rule text hash;
  - J4's removal set and the fixed slot list, as §15.4.3 derives them from J1 (private set file hash);
  - the fill-rate factor for J6's row (§15.4.8);
  - the D-rows taken.

  Every J run note cites it, and every J board log records the same stamps (§15.5 A1).

#### 15.4.2 J1: census, marker path and trace rehearsal (L4T only)

- **Runs:** `s1-board.sh j1`, on any boot (it quiesces nothing), which it marks `by=j1`. It needs one COM3 capture started from PowerShell, whose file lies inside the git-ignored record directory, with life at least 1,800 s. A J1 boot is never used for a quiesce.
- **Reads (read-only unless marked):**
  1. **Tools:** `command -v systemd-run setpci dd sha256sum modprobe findmnt`; `systemd-run --version` (first line). Then one `dd iflag=skip_bytes,count_bytes` read of 64 entries of `/proc/kpageflags` at c1's page-frame offset, into tmpfs. This tests the snapshot primitive (R60). If `setpci` is absent, the Bus Master clear step is never run (§15.4.3).
  2. **Kernel config items:** `CONFIG_(DMA_API_DEBUG|PAGE_OWNER|IOMMU_DEBUGFS|KEXEC_FILE|PCI_IOV)`; `/proc/sys/kernel/printk`, `printk_devkmsg`, `panic`, `panic_on_oops`.
  3. **PCI topology:** `b_pci_state census` (§15.5 A1); each root port's child count; every `/sys/kernel/iommu_groups/*/type` whose value is not `DMA` or `DMA-FQ`, which adds to the untranslated set (record only).
  4. **Storage and mounts:** `findmnt -rn -o TARGET,SOURCE` for every mount; `/proc/swaps`; the block device's sysfs parent chain for `/`, `$HOME`, `/dev/shm`'s backing and the kimg directory `KD`. **Pre-registered rule:** any controller (xHCI, NVMe or PCIe function) with a mounted or swap-backed descendant leaves J4's set.
  5. **USB:** for every `/sys/bus/usb/devices/*`, only its `driver` link, `idVendor`, `idProduct` and `bInterfaceClass`; whether a HID keyboard interface is present (recovery, §15.7.3). No `serial`, no `address`.
  6. **Marker and timer path (under D20):** one `s1wq: j1 probe result=0` line written to `/dev/kmsg` at level 3, then a check that it reached COM3 (R57). Then one transient timer, `systemd-run --on-active=30s --collect`, whose only action writes `s1wq: j1 timer result=0` to `/dev/kmsg`; its line on COM3 shows that a transient timer fires and its marker arrives (part of R59; the quiesced case stays J3's).
  7. **Only under D23:** the GPU power-domain line from `/sys/kernel/debug/pm_genpd/pm_genpd_summary` and the EMC clock rate from debugfs (paths HYPOTHESIS, Q18; record only, never a gate, never GPU MMIO).
  8. **Only under D21, and the only other writes:** `echo 1 > /sys/module/kernel/parameters/initcall_debug` and `dmesg -n 7`, both runtime-only, set just before the harness's usual reboot. Then `wait_new_boot_id`.
- **Set file.** From reads 3-5, J1 writes the private `<rec>/J-set.conf`: for each member of J4's "max" set, its sysfs device path, driver name, root port and whether it stays in the set by the rules of §15.4.3 and item 4. Its hash goes into `J-prereg.log`. The committed harness reads it; it carries no driver name itself.
- **Records:** `<rec>/J1/j1-<utc>-{board,census,com3}.log`, `-kpf-probe.bin`. The privacy scan, with the SSID class (§15.5 A4), runs on every copied text.
- **Bounds:** reads 300 s; timer probe 120 s; reboot return bound 1,200 s, as `reboot`.
- **Precondition:** no other workflow on the board or COM3; `S1_REDACT_SSID` supplied privately by the owner.

| Observation | Conclusion | Next |
|---|---|---|
| `systemd-run` present; the `dd` probe returns 64 entries; both `s1wq: j1` markers on COM3 | detached sequence, snapshots and markers can run as designed | J2 |
| `systemd-run` absent, or either marker missing from COM3 (F42) | no detached sequence can be proven | J2b runs in J2's place (a pure B2 repeat); J3 and J4 wait (revision 4, or D25's Ethernet variant) |
| per-device `shutdown` lines from the trace on COM3 during the reboot, and the reboot's shutdown section of COM3 shorter than half of `S1_STUCK_S` | the trace works and its console cost is bounded | J2 and J4 both carry it (matched) |
| no trace lines (F38), or the trace's shutdown section at least half of `S1_STUCK_S` | observation defect, or too costly on the console | J2 and J4 both run without the trace; no rerun for the trace alone |
| a root port with more than one child, or a controller with a mounted or swap descendant | that device leaves J4's set, per the rules | recorded in `J-set.conf` and `J-prereg.log` |
| `$HOME` or `KD` resolves under a controller in the set | the sequence could remove its own storage | that controller leaves the set; if it is the wireless function, no J3 or J4 (memo) |
| a translated group that is not `DMA` or `DMA-FQ` (identity) | a new untranslated master exists | memo line; H4 widens; ladder unchanged |
| the reboot oopses and returns through the watchdog | the known long-uptime pattern (F27) | J2 on the fresh boot |

#### 15.4.3 The detached sequence (shared by J2, J3 and J4)

**Why detached, and why in both arms.** Removing the wireless function **[D29]** drops the PC's ssh, so in J4 `systemctl kexec` must be issued by a unit on the board, not over ssh. If only J4 were detached, a clean J4 could come from its longer dwell after the quiesce or from the issuing context rather than from the removal; H1 residue that fades with time (HYPOTHESIS) would then be wrongly credited to the removable masters. So **J2 runs the same generated sequence with an empty removal set**, and the removal is the only difference between the arms. J3 runs it with J4's set and no kexec.

**J4's removal set ("max").** Pre-registered from J1's set file before J2:
- the wireless function: interface down, driver unbind, module removal, Bus Master read back on the endpoint and its root port, cleared if still set;
- the xHCI platform device, unbound from its driver, which removes the hubs and the Bluetooth radio;
- the Ethernet function: unbind, then the Bus Master check on the endpoint and its root port;
- the NVMe function, **only if** J1 shows no mounted or swap-backed descendant and neither `$HOME` nor `KD` under it.

**Refusals.**
- A device whose root port has more than one child is not cleared at the root port.
- If J3 shows an xHCI, Ethernet or NVMe step failing, J4's set falls back to **wireless only**. That fallback is pre-registered, so it is not a new decision.
- The SD host, display, host1x, coprocessors and the GPU (already `rmmod`) are untouched. They are reported as **not excluded** by J4.

**Fixed slots.** The generator derives one slot list from the "max" set, and every arm uses the **same list and the same number of slots**:

| Slot | Action in J3 and J4 | In J2, and for members not in the set |
|---|---|---|
| 1 | wireless interface down (`ip link set dev <resolved> down`) | `result=skip` |
| 2 | wireless driver unbind | `result=skip` |
| 3 | wireless module removal (`modprobe -r <resolved>`) | `result=skip` |
| 4 | wireless Bus Master read, clear if set, read back (endpoint, then a single-child root port) | read only |
| 5 | xHCI unbind | `result=skip` |
| 6 | Ethernet unbind | `result=skip` |
| 7 | Ethernet Bus Master read, clear if set, read back | read only |
| 8 | NVMe unbind | `result=skip` |
| 9 | NVMe Bus Master read, clear if set, read back | read only |

Each slot runs its action under `timeout WQ_STEP_TIMEOUT_S`, prints `s1wq: slot<n> <step> result=<rc>`, runs the Oops and D-state check below, and then sleeps until the slot's fixed length `WQ_SLOT_S` has passed. So the dwell from the quiesce to the issue is the same in every arm.

**Bus Master clear, the only configuration write.** Only `setpci -s <BDF resolved from the driver link> COMMAND=0000:0004`, with a read-back of the Command register before and after. No `dd` fallback: if J1 found no `setpci`, the clear is not run, and a still-set required bit aborts with `abort reason=bme-not-cleared` (F44).

**Phase A: PC, synchronous over ssh.** Every ssh session has an explicit timeout equal to its own bound.
1. Stamps (§15.4.1), identity, uptime, fresh-boot and **start-margin** gates; `nvbootctrl`; governor pin; quiesce (bound 500 s, as `run`); gate B, including `oops_lines=0` from the quiesce, as `run` requires.
2. `b_kpf_snap prequiesce` (J2 and J4 only, taken before step 1's quiesce) and `b_kpf_snap postquiesce` and `b_pci_state postquiesce` after it: raw `/proc/kpageflags` and `/proc/kpagecount` slices for window 2's and c1's page frames plus a text header, written to a `mktemp -d /dev/shm/s1kpf.XXXXXX` directory, fetched by scp at once, sha256-verified on the PC, then removed from tmpfs. **No tar, no gzip, nothing on the rootfs.** A snapshot failure is recorded and never stops the rung.
3. `kexec -s -l`, `kexec_loaded=1` (J3 too, so memory state matches J4), `b_governor`.
4. **Generate** `<img>-<utc>-wq.sh` and `-wqfb.sh` with `printf %q` and `declare -f WQ_FUNCS` only (§15.5 A5), never a heredoc (heredocs eat backslashes). Gate both with `bash -n` and the allow-list gate (§15.5 A5). scp them to `$HOME` and compare sha256.
5. **Arm the fallback first:** `systemd-run --unit=s1wqfb-<utc> --on-active=<WQ_FALLBACK_S>s --timer-property=AccuracySec=1s --collect /bin/bash $HOME/…-wqfb.sh`.
6. **Start the sequence:** `systemd-run --unit=s1wq-<utc> --collect --no-block -p TimeoutStopSec=30 /bin/bash $HOME/…-wq.sh`, with `FINAL=kexec` (J2, J4) or `FINAL=none` (J3). Both `systemd-run` command lines pass the same allow-list gate before they are sent.
7. Record `run com3_log=<name> …`, `run com3_bytes_before_kexec=<bytes>` (J2, J4) or `j3 com3_bytes_before_arm=<bytes>` (J3), and `wq_armed armed_epoch=<s> wq_fallback_s=<s>` in the board log.

**Phase A failures.** A failure or timeout at any step after 3 reads `/sys/kernel/kexec_loaded` over ssh, runs `b_unload`, stops any armed unit, and exits 3 ("reboot before another attempt"). Units are never armed after a timeout.

**Phase B: board, detached.** Order, with nothing slow between the governor read and `systemctl kexec`:
1. A start delay `WQ_START_DELAY_S`, so the PC's ssh session closes cleanly. The PC polls **COM3 only** in every arm; in J2 it uses ssh only for the ARMED-failure stop.
2. `kexec_loaded` check (J2, J4); refuse if `$HOME` resolves under a set member.
3. `b_pci_state pre`.
4. Resolve each set member from its driver link and the set file, never from a fixed address; refuse on a mismatch (`abort reason=resolve`).
5. The fixed slots. **After each slot:** scan `dmesg` since the sequence began for `Oops|BUG:|Kernel panic|Unable to handle kernel|Internal error` (b_quiesce's pattern) and check that the slot's process is gone and no task of the sequence is in D-state. On any hit: `abort reason=oops` (F47).
6. `b_pci_state final` (per-read `timeout 10`, total under `WQ_FINAL_READS_S`).
7. Refuse, with `abort reason=bme-not-cleared`, if any required Bus Master bit is still set (J3, J4).
8. The Oops scan again.
9. The trace settings, under D21 and J1's go (both arms or neither).
10. `FINAL=none` (J3): mark `no final action`, then wait for the fallback.
11. `FINAL=kexec` (J2, J4):
    - read `/proc/uptime`; at or above 1,800 s: `abort reason=uptime` (F48). The constant is fixed in the script, not read from the environment, and 7,200 s is refused without exception;
    - read both cpufreq policies' governor; not `performance`: `abort reason=governor` (F48);
    - `b_freq final`;
    - mark `kexec issuing`, then `systemctl kexec`.
12. **After `systemctl kexec`:** a non-zero rc is the only "rejected" case: `abort reason=kexec-rejected`. On rc 0 the sequence waits `WQ_ISSUE_WAIT_S`; then, if `systemctl is-system-running` reads `stopping`, it marks `shutdown in progress` and exits without any action (R72); otherwise it marks `kexec did not happen`, runs `kexec -u` and reboots (exit 5).

**Abort path** (`abort reason=…`): `kexec -u`, `sync`, `systemctl reboot`. Exit 5.

**The fallback script:**
- if `systemctl is-system-running` reads `stopping`: marks `fallback idle shutdown in progress` and exits;
- otherwise marks `fallback firing`; appends a bounded `dmesg` tail to `wq.log`; runs `kexec -u`, `sync` and `systemctl reboot`;
- after a 120 s wait, if still running and not `stopping`, marks `fallback forcing` and runs `systemctl reboot --force` (exactly one `--force`, never two).

**Marker texts** are chosen so the existing parsers and `com3_class` never mistake them:
- the prefix `s1wq:`;
- `result=`, never `rc=`;
- none of `verify=bad refuse= FAIL MB1 Setup Press Select Continue Shell login`;
- no line ending in `$`, `#` or `>`.

**Design constants,** refused if set in the environment and printed in the board log:
- `WQ_START_DELAY_S` 15, `WQ_SLOT_S` 30, `WQ_STEP_TIMEOUT_S` 25, `WQ_SLOTS` fixed by the slot list, `WQ_FINAL_READS_S` 60, `WQ_ISSUE_WAIT_S` 180;
- `WQ_FALLBACK_S` = start delay + `WQ_SLOTS` × `WQ_SLOT_S` + `WQ_FINAL_READS_S` + `WQ_ISSUE_WAIT_S` + 120.

**Start margin.** The harness computes the rung's worst case from its own bounds (Phase A's gates, quiesce, snapshots, load and arming bounds, plus Phase B up to the issue, or to the fallback firing for J3), prints it in the board log, and refuses to start unless the start uptime plus that worst case is under 1,800 s. The issue-time uptime check in Phase B stays as the hard guard.

**Rule-5 exception (dated 2026-09-14, under D25).** `-wq.sh`, `-wqfb.sh` and `-wq.log` may persist in `$HOME` across one reboot. On every return path, including exit 3, exit 5 and after a cut, they are fetched with sha256 verification and removed with a `b_rmfiles`-style step (names matching `[A-Za-z0-9._-]`, never `*.kimg`); the next harness command after any failed or cut path removes any leftover first. Every removal, and any file left behind, is recorded in the board log. Nothing else of the sequence touches the rootfs.

#### 15.4.4 J2: the matched control arm (kexec, `s1-h1`), and J2b

**J2 runs:** `s1-board.sh jrun s1-h1 control`: §15.4.3 with an empty removal set and `FINAL=kexec`, ssh kept up.
- **Image:** `s1-h1` as staged, with Q17's check. Guard and return bound from `s1-h1.params`. `STEP=J2` is set after `resolve_kimg`, so `image_step`'s B2 mapping never reaches the record path.
- **Preconditions:**
  - J1 met (or its F42 row sends J2b instead);
  - a fresh unused boot meeting the start margin;
  - owner at the plug;
  - one new COM3 capture, started from PowerShell inside the record directory, never used before, with life at least the return bound + 2,180 s + `WQ_FALLBACK_S`;
  - `nvbootctrl` equal to the session's first reading;
  - D20, D21 (for the trace), D22 and D25 taken; `S1_REDACT_SSID` supplied.
- **PC progress:** `wait_wq`, as J4 (§15.4.6), with ssh used only for the ARMED stop.
- **Records:** B2's set under `J2/` (board, params, `iomem-postrmmod`, COM3 copy, black box, `nvbootctrl` pre and post), `parse-s1.txt` from `run --diag j2`, `-kpf-{prequiesce,postquiesce}.{flags,count}.bin` with header, sha256 and `-decode.txt`, `-pci-{postquiesce,pre,final}.log`, `-wq.sh`, `-wqfb.sh`, `-wq.log`, `-wq-com3-markers.txt`, `-trace.txt` (the COM3 shutdown lines extracted and redacted), `j-note.log`.
- **Verdict:** the parser's `run --diag j2` prints `step=J2` and `verdict=diagnostic complete|incomplete`, never `pass` and never a `b2=` field (§2 rule 3).

| Observation | Conclusion | Next |
|---|---|---|
| **F32:** c2 bad at both checks; c1 and c3 ok; L0, L7, `S1 ASINFO` as B2 | the observation repeats (two bad controls) | J3 |
| **F32a:** c2 bad at the start check, ok at the end check | corruption present before QNX's checks, and all bad words returned to the pattern before the end check (K-d at its extreme): a restoring writer or read instability | **stop kexec work today; memo;** J6 first, in the control arm |
| **F32b:** c2 ok at the start check, bad at the end check | onset after the start check, so the writer started after QNX came up | **stop kexec work today; memo;** J6 first, in the control arm (a J4 clean result could be an onset-timing artefact) |
| **F33:** c2 ok at both checks | B2 not reproduced under the J additions | J2b on the return boot, then stop (§15.6 class U) |
| **F39:** c1 or c3 bad | the corruption reaches beyond c2 | **stop; owner;** the exposure item is raised |
| **F40:** `refuse=`, `map=fail`, an `S1 ASINFO` difference, or no `procnto up` for a harness reason | a defect or harness fault | defect path; one harness retry on a fresh boot |
| **F43, F47, F48:** the sequence aborted (exit 5) | no kexec happened | one harness retry on a fresh boot; a second stops the day |
| the trace shows no `shutdown` line for a PCI function | its shutdown hook did not run, or the trace missed it | recorded; the J4 set is unchanged |
| `b_pci_state final` shows Bus Master set on a PCI member at the issue | recorded as `bme_at_issue_control`; a named input to F35's split (§15.4.6). It shows only the state **before** the shutdown, not whether the shutdown cleared it | recorded |

The page snapshots are a record only: they describe Linux's CPU-side page ownership near the jump and carry no evidential weight on H1 or on where a device writes (R45).

**J2b runs** (only after F33, or after J1's F42 row): `s1-board.sh jrun s1-h1 b2repeat`: `cmd_run`'s B2 flow over ssh with **no additions** (no snapshots, no trace, no detached sequence), on J2's fresh return boot. Records under `<rec>/J2b/`; `run --diag j2b`; never a `B2-aN` directory.

| Observation | Conclusion | Next |
|---|---|---|
| **F45:** J2b c2 bad | the J additions (dwell after the quiesce, the unit as issuer, the trace) change the writer's behaviour. A dwell effect would fit fading residue (HYPOTHESIS) | stop; memo; class U with this as a lead; D31 |
| **F46:** J2b c2 ok at both checks | intermittent: one bad in three runs of B2's image | stop; memo; class U; D31 decides J6 in the control arm, which watches for onset |
| F39, F40 | as J2 | as J2 |

#### 15.4.5 J3: rehearsal of the detached removal (L4T only)

**Runs:** `s1-board.sh j3`, only after F32. It needs D20, D22, D25 and a J1 that met. §15.4.3 with J4's set and `FINAL=none`; no prequiesce snapshot. It ends through the fallback timer, which proves that the fallback recovers a board with no network, without a power cut.

**Preconditions:**
- a fresh unused boot meeting the start margin (J2's return boot); owner present;
- one new COM3 capture inside the record directory, never used before, with life at least `WQ_FALLBACK_S` + 1,200 + 1,800 s;
- `S1_REDACT_SSID` supplied privately by the owner.

**Gates** (read over ssh on the return boot, which is fresh and not marked):
- COM3 holds every slot marker in order, and the fetched `wq.log` is consistent with it (R57);
- `wq.log` shows each set member's steps at `result=0`, no `abort reason=`, and Bus Master 0 on every required endpoint and root port. Whether the driver cleared Bus Master itself is recorded as `bme_after_unbind`, before any clear;
- `fallback firing`, then a reboot, then a new `boot_id` inside the reboot bound (R59);
- **after the return:**
  - `systemctl list-units --all 's1wq*'` is empty;
  - the wireless driver is bound and its interface up;
  - rfkill soft and hard read 0 from sysfs;
  - NetworkManager and wpa_supplicant are active;
  - the xHCI, Ethernet and NVMe drivers are bound. This shows the change was runtime-only (R58);
- `nvbootctrl` equals the first reading; no new `dmesg-ramoops`, or it is recorded (F27);
- the board-side sequence files are removed and the removal recorded.

**No black box, no parser.** J3 has no QNX run: `b_after`'s black-box copy and the parser are skipped. If the previous console is wanted, it is copied as `-l4t-console-ramoops.log`, scanned with the SSID class, and never passed as `--blackbox`.

**Records:** `<rec>/J3/`:
- board log, COM3 copy;
- `-wq.sh` and `-wqfb.sh` as sent, `-wq.log`, `-wq-com3-markers.txt`;
- `-pci-{postquiesce,pre,final}.log`;
- `-kpf-postquiesce.{flags,count}.bin` with header and decode;
- `nvbootctrl` pre and post.

| Observation | Conclusion | Next |
|---|---|---|
| every gate met | detached removal and fallback recovery work on this L4T | J4 on this return boot (after `reboot` if the start margin is missed) |
| no slot marker on COM3, but the unit is active over ssh (F42) | markers do not reach the console under the quiesce | PC stops both units, `kexec -u`, exit 3; reboot; **no J4 today**; class U for today |
| an xHCI, Ethernet or NVMe step fails or aborts, and the wireless steps pass | that device is unsafe to remove this way | J4 uses the pre-registered wireless-only set; recorded |
| a wireless step fails, `abort reason=oops`, or `bme-not-cleared` (F44, F47) | the removal cannot be shown | no J4; memo; class U for today |
| `fallback firing` absent after `WQ_FALLBACK_S` + 600 s, with no network (F42) | the fallback does not recover the board | §15.7.3 recovery; **no detached kexec variant** until revision 4 |
| wireless, Ethernet or xHCI not back after the return (F41) | persistent state was touched, or a driver did not reload | stop board work; §15.7.3 |

#### 15.4.6 J4: the test arm (kexec, `s1-h1`)

- **Runs:** `s1-board.sh jrun s1-h1 remove`: §15.4.3 with J4's set (or the wireless-only fallback) and `FINAL=kexec`. `STEP=J4` is set after `resolve_kimg`.
- **Only variable against J2:** the removal set. Timing (fixed slots), issuing context (the unit), snapshots and trace are matched.
- **Image, bounds, records and verdict:** as J2 (`run --diag j4`).
- **Preconditions:** J3 met; a fresh unused boot meeting the start margin; owner at the plug; one new COM3 capture inside the record directory; D24 (set) taken; `S1_REDACT_SSID` supplied.
- **PC progress (`wait_wq`, 10 s polls of COM3 after the offset):**

  | State | Evidence | Next |
  |---|---|---|
  | ARMED | no marker yet | if no `begin` by its bound while ssh still answers: stop both units, `kexec -u`, exit 3 |
  | PROGRESS | slot markers; ssh silence expected in J4 | keep polling COM3; ssh is no longer evidence |
  | ISSUED | `kexec issuing` | wait; a slow shutdown with growing COM3 is not a hang |
  | JUMPED | `kexec_core: Starting new kernel` or `T234-SHIM` | `wait_new_boot_id` from here, with the params' return bound |
  | ABORTED | `abort reason=`, `kexec did not happen` or `fallback firing` | wait for a new `boot_id`; exit 5, a harness-reason retry |
  | STALLED | no new marker by the slot bound, no jump | `advice` (§15.7.3); NO CUT until the fallback deadline has passed |

- **After a JUMPED return:**
  - fetch `wq.log`, checking sha256, then remove the board-side sequence files;
  - check that the `s1wq:` lines in `wq.log` are a subsequence of COM3's;
  - parser, privacy scan, `extract`, `consistency`.
- **After an ABORTED return (exit 5, F43, F47, F48):** as J3's "no black box, no parser" rule.

| Observation | Conclusion | Next |
|---|---|---|
| **F35:** c2 ok at both checks; c1 and c3 ok; L0 and L7 met; the sequence reached `kexec issuing` with Bus Master 0 on every required function | the removed set is implicated, **provisionally** (H4 or H4s, or its live driver state) | §15.6 class Q (provisional); memo; D27; J6 in the remove arm; then the B1 and B2 reruns |
| F35 **and** `bme_at_issue_control` shows Bus Master set on the PCI members in J2 | read as **Q-p:** the kexec shutdown's own Bus Master handling did not protect c2 in the control (E17 false on this fork, or too late; HYPOTHESIS, since no read follows the shutdown) | recorded in the memo |
| F35 **and** Bus Master already clear on the PCI members at the issue in J2 | read as **Q-x:** the non-PCI member (the xHCI and its falcon, R63) or driver state implicated | recorded; D27 considers bisecting toward the xHCI |
| **F36:** c2 bad at either check | the removable masters are excluded **as quiesced by this sequence**; nothing is shown about H1, H2, H3 or H5 | memo; J6 in the control arm; J7a decision |
| **F39** | as J2 | stop; owner |
| **F43, F47, F48:** ABORTED, exit 5 | no kexec happened; a harness-reason attempt | one retry on a fresh boot; a second stops the day |
| **F37:** COM3 ends in L4T text after `kexec issuing`, with no shim and no ssh | Linux hang in the detached shutdown | §15.7.3; the diagnosis ends for the day |

**False-Q risk, stated.** With one run per arm after two bad controls, a clean J4 under no real effect is not unlikely (a rule-of-succession estimate after two bad controls is about one in four). Q therefore stays provisional until the conditions of §15.6's "final" column hold.

#### 15.4.7 J5: no-`rmmod nvgpu` arm (reserved)

This is J2 with the fixed quiesce relaxed: nvgpu is left to its own shutdown path, as M1 and M1b entered.
- **Not in today's ladder,** for two reasons: it relaxes a fixed harness setting (§14.5 W), and the budget is spent on the arms that can classify. C24 does **not** show it would be uninformative: the same error lines do not imply the same GPU or page state (C24, §15.10 item 5).
- It runs only if D24 selects it, under a new one-line pre-registration, and counts against the revision's kexec budget.

#### 15.4.8 J6: the watcher (image change, startup unchanged)

**What it is.** A second read-only binary, `memcanary-w`. It is built from the same `memcanary.c` with `-DMEMCANARY_WATCH`, and the plain build hashes to `PIN_MEMCANARY` (the determinism gate, §15.5 B8.1, run in a scratch worktree before any commit). If the gate fails, the fallback is a separate `memcanary-w.c` sharing no edited token. **`PIN_MEMCANARY` never moves.**

The binary ships in the new image `s1-j1`:
- host mode, never a pass run;
- the startup line unchanged (`-b w2,canary`), so `PIN_STARTUP_S1` is unchanged and **B1 is not triggered**;
- B2's `alloc -s 1536` is **replaced** by the existing `memcanary hold` subcommand (the one B4 uses), sized as below.

**Tool: `memcanary-w watch -n c1|c2|c3 -l LABEL -i MS -c COUNT -T SECS -d /dev/shmem/j1<label>.bin`**

*Guards.* A compiled name only; `verify`'s refusals (`refuse=no-entry`, `refuse=in-sysram`, `map=fail errno=`); `mmap_device_memory(PROT_READ)`. Its only writes are two heap buffers (the `base` copy and `prev`) and one small file under `/dev/shmem/`.

*Refused arguments.*
- any hex or other address;
- a label outside `[a-z0-9]{1,8}`;
- `-i` outside 0-60,000;
- `-c` outside 1-100,000;
- `-T` outside 1-3,600;
- `-d` without the `/dev/shmem/j1` prefix, or containing `..`.

*Algorithm.*
1. **BASE:** one read of every word, kept as `base` and `prev`; a bad-word bitmap against the pattern.
2. **Snapshots** k = 1..COUNT until the deadline, sleeping `MS` between them. Where a word's read `A` differs from `prev`:
   - read it twice more at once, `B` and `C`;
   - count `osc` if `B != A` and `C == A` (the value returns to the first read: a marginal read);
   - count `prog` if `B != A` and `C != A` (A-B-B or A-B-C: a writer in progress);
   - count `stable` if `A == B == C`;
   - count `healed` if the last read equals the pattern;
   - update `prev` with the last read;
   - set the page's `changed` bit, and its `healed` bit when it healed.

   Nothing is printed inside the loop: the TCU callout busy-polls in the writer's context (§2 rule 7).
3. **FINL:** the final bad set against the pattern.
4. **Classification** of FINL's bad words (below), `munmap`, one file write, then the console lines.

*Exit codes.* 0 when complete; 1 on a refusal, map failure, no memory or I/O failure; 2 on usage or an unknown name.

*Word classes.* First match wins, so they sum to `bad`. Each rule is our reading of a public specification, from memory: HYPOTHESIS, and the self-test encodes that reading.
- `zero`; `ones`;
- `flip2`: popcount(word XOR pattern) ≤ 2, split into `flip2_same` (FINL's differing bit positions equal BASE's for that word) and `flip2_var`;
- `flip8`: 3-8;
- `pat_same`: the splitmix64 inverse lands on another 8-byte-aligned offset of the same canary;
- `pat_other`: the inverse lands in another canary;
- `hi_pat`: the upper 32 bits equal the pattern's, the lower differ (a 32-bit field written into the low half);
- `lo_pat`: the lower 32 bits equal the pattern's, the upper differ;
- `pte`: an ARMv8 VMSA table or page descriptor whose output address is in DRAM;
- `kva`: top 16 bits all ones;
- `ptr_self`: inside this canary;
- `ptr_ram`: inside DRAM;
- `u32page`: below 4 GiB, page-aligned, non-zero;
- `small32`: non-zero, below 2^32, not page-aligned (ring indices, counters, queue headers; HYPOTHESIS on such layouts);
- `other`.

*Stride histogram.* For FINL's bad words, a count per in-page offset modulo 64 in eight bins (a periodic record stride shows as one or two dominant bins). Counts only.

*Byte signatures,* counted independently over bad extents, **scanned at every byte offset**, counts only: `ascii_runs` of at least 16 printable bytes; `ipv4` (a valid header checksum); `beacon` (802.11 beacon frame control and broadcast address); `trb_evt` (xHCI event TRB shape). **They are positive-only:** after kexec the host driver is gone, whether a network function still decrypts is UNKNOWN, receive buffers start with vendor descriptors (HYPOTHESIS), and beacons may be filtered while associated. Their absence excludes nothing.

*Console lines* (each ≤ 255 B at maximum field widths, matched by the harness's existing `S1 ` prefix):
```
S1 CANARY <n> watch=base label=<l> bad=<n> pages=<n> first_off=0x<hex> last_off=0x<hex>
S1 CANARY <n> watch=time label=<l> snaps=<n> changed_snaps=<n> changed_words=<n> healed=<n> osc=<n> prog=<n> stable=<n> stop=count|deadline
S1 CANARY <n> watch=words label=<l> bad=<n> zero=<n> ones=<n> flip2_same=<n> flip2_var=<n> flip8=<n> pat_same=<n> pat_other=<n>
S1 CANARY <n> watch=words2 label=<l> hi_pat=<n> lo_pat=<n> pte=<n> kva=<n> ptr_self=<n> ptr_ram=<n> u32page=<n> small32=<n> other=<n>
S1 CANARY <n> watch=stride label=<l> b0=<n> b1=<n> b2=<n> b3=<n> b4=<n> b5=<n> b6=<n> b7=<n>
S1 CANARY <n> watch=bytes label=<l> ascii_runs=<n> ascii_bytes=<n> ipv4=<n> beacon=<n> trb_evt=<n>
S1 CANARY <n> watch=verdict label=<l> writer=none|static|stopped|ongoing heal=no|yes reads=stable|osc|prog content=<list>|unclassified
S1 CANARY <n> watch=fail label=<l> reason=nomem|dump-open|dump-write errno=<n>
```

*Export file* (content-free; offsets only, little-endian):
- a 64 B header: magic `S1J1PBMP`, version, name, label, base, page count, snapshots taken, interval;
- three bitmaps of one bit per 4 KiB page: `bad_final`, `changed_ever`, `healed_ever`;
- a 32 B tail of the counts.

It is sent **only through `xport`** (base64 between `S1 BEGIN` and `S1 END`), never as raw bytes and never into the black box. Raw bytes on COM3 would break `com3_last_kind`, parse-s1's body decode and the byte-exact redaction. **No word value, byte or pointer value leaves the target.** A value export is D28, reserved.

*The hold.* `memcanary hold -s @J1_HOLD_MIB@ -f /dev/shmem/j1hold.go -T @J1_HOLD_T@ -o /dev/shmem/j1hold.out`, started in the background after watch `b`, as B4 starts it:
- `@J1_HOLD_MIB@` is a generator design constant: windows 1 and 2's sysram sizes minus the canaries, minus a margin for procnto, the script, the watch buffers and the export files (margin in D27). No FreeMem value sizes it (§2 rule 8);
- it fills once, then waits through watches `c` and `d`; the script then touches the trigger and waits for the verify line;
- **what it shows:** by pigeonhole on the design sizes, an allocation that large must cover most of window 2 and much of window 1, so a writer landing anywhere in the held pages during the dwell makes the verify bad. **What it does not show:** where the bad words are (it prints one first offset in its own virtual allocation and a count), or which physical pages it covered (procnto's placement is HYPOTHESIS apart from the arithmetic, R75);
- a `map=fail` is F28: diagnostic incomplete, not a verdict.

*Host script (`s1-host.ksh.in`).* New `@J1@`-prefixed lines only, so every other image's generated script stays byte-identical:

| Step | Label | Target | Interval | Count | Deadline | Bound |
|---|---|---|---|---|---|---|
| after `canaries start` | `a` | c2 | 0 ms | 100,000 | 20 s | 60 s |
| next | `b` | c2 | 1,000 ms | 180 | 190 s | 230 s |
| then the hold starts; wait for its fill line | | | | | | fill bound |
| during the hold | `c` | c2 | 1,000 ms | 180 | 190 s | 230 s |
| during the hold | `d` | c1 | 1,000 ms | 60 | 70 s | 110 s |
| then touch the trigger; wait for the hold's verify line; `canaries end` as B2; then the `@BOARD@@J1@` export block; reset | | | | | | verify bound |

The export block is placed after `FAIL_STATE`, **outside** the `MODE != host` guard, and exports `j1a` to `j1d` by `xport` (so `export_filename` gives `s1-j1a.bin` and so on), following the existing record-first rule. These are wait bounds, not results. The generator computes the guard and return bound, which must stay under the 3,600 s guard cap, and a black-box text estimate for `s1-j1` (§15.5 B8.6).

**Run.**
- `s1-board.sh stage s1-j1`, `p0 s1-j1`, then `reboot`.
- On a fresh boot, `jrun s1-j1 control` or `jrun s1-j1 remove`: J2's or J4's harness arm (§15.4.3), with the same snapshots. Which arm runs is set by §15.6: after F35 the **remove** arm (J6r), which is a condition of Q becoming final; after F36, F32a, F32b or F46 the **control** arm (J6c). The other arm runs only by D27.

**Preconditions:** the §15.5 B8 gates and the TCG self-test passed; D27 taken; the usual board rules and §15.4.4's preconditions.

**Records:** `<rec>/J6r/` or `<rec>/J6c/`: J2's set plus `s1-j1a..d.bin`, the hold's lines, and `canwatch.txt`, the analyzer output with counts and classes only. The parser's `run --diag j1` verdict line reads `diagnostic complete` or `diagnostic incomplete failed=…`, never `pass`.

**2026-09-14 (implementation, before J6's pre-registration):** three reviews of the built watcher found that a one-off misread counted as a writer, that "whole pages healed" counted events rather than pages, and several readings this table leaves open. The engine, two classes and the rows' readings were amended; §15.12 records each as HYPOTHESIS, and the table below is read through §15.12.

| Observation | Conclusion | Next |
|---|---|---|
| **F34:** `osc` above 0 **and** `flip2` (same and var together) the majority class **and** `prog` 0 | H3, read instability | stop; memo; class K-r unless J4 was F35 (then U) |
| `prog` above 0, or `changed_words` above 0 with `stable` re-reads | a live writer (not read instability) | carried into K-w or E by J7a |
| `healed` above 0 with `pat_same` or `pat_other` dominant, or whole pages healed together | a restoring writer (H2 lean; a firmware save and restore, or a copy) | memo; D30 (J7a UEFI arm) |
| `small32`, `hi_pat` or `lo_pat` dominant, or one or two dominant stride bins | ring, counter or register-style records (H2 or H4 lean; which device is not shown) | memo; D30 |
| `ptr_ram` or `u32page` dominant, and bitmap pages coincide with page frames Linux held before the quiesce | CPU-side structures (H1 lean; weak, R45) | memo; D30 (J7a) |
| `pte` or `kva` dominant | QNX-shaped structures (H5 lean) | memo; revision 4 base shift |
| a positive signature above 0 after F36 | contradicts J4's exclusion **positively** | review J4's Bus Master evidence; memo |
| label `c`'s `changed_words` per snapshot differs from label `b`'s by more than the pre-registered factor | writer behaviour changed with the host allocation (H4s lean) | memo; H4s row |
| **F49:** the hold's verify bad | a writer reached sysram outside the canaries (or QNX-side) | stop; owner; exposure item raised; Q cannot become final |
| `writer=none` (c2 clean at every scan) | not reproduced in this run | memo; B2 stays data; in J6r, a condition for Q-final |
| `writer=static` | c2 was bad but did not change during the watches | memo; E2's live-writer inference is weakened, not withdrawn |
| a `c1` watch (label d) with `bad` above 0 | F39 | stop; exposure item |

#### 15.4.9 J7: reserved arms (not designed here)

| Arm | Separates | Why reserved |
|---|---|---|
| **J7a:** UEFI entry carrying the `s1-h1` or `s1-j1` payload (M5's path) | H1 from H2: no Linux residue at all | needs a TX refit, a loader rebuild and attended firmware menus, and firmware allocations in window 2 were never checked (§3.2). Owner decision D30, then its own short design |
| **J7b:** a read of each SMMU's `sCR0` (CLIENTPD) after kexec | settles R46 directly | a new MMIO read surface with SError-at-EL2 risk; on the new Never list. Revision 4 with its own design |
| **J7c:** more canaries inside window 2 (for example 16 MiB above c2, and at a candidate die boundary), and one inside window 1 below c1 | how far the writer reaches; die anchoring; window-1 exposure | startup constants change, so B1 reruns. Revision 4 |
| **J7d:** a restricted value export (pattern classes only; never `other`, `ascii`, `pte`, `kva` or any class that would carry QNX kernel structure or pointer content) | device or structure identity | privacy (§15.7.4) and the 4.6(c) stance (source and docs only, no analysis of QNX internals). D28 |
| **J7e:** window 2's base shifted with c2 at the new base | H5 | startup change. Revision 4 |

---

### 15.5 Implementation changes

### A. Harness-only (J1-J4 and J2b; no image, no pin moves)

1. **`orin-native/startup/s1-board.sh`**
   - **New subcommands:**
     - `j1`;
     - `j3`;
     - `jrun IMG control|remove|b2repeat`, which accepts `s1-h1` (and `s1-j1` with `control|remove` after B) and refuses any other image or arm;
     - `wq-status BOARDLOG`, which prints §15.4.6's state from COM3;
     - `kpf-decode FILE`.
   - **Existing subcommands:** `run`, `p0`, `p1`, `reboot` and `stage` are unchanged.
   - **Step and record path:** `jrun` sets `STEP=J2|J2b|J4|J6r|J6c` and `MODE=host` **after** `resolve_kimg`, so `image_step`'s B2 mapping for `s1-h1` never reaches `SD`; a self-test proves no `jrun` creates a `B*` directory.
   - **Stamps:** `j1`, `j3` and `jrun` record `s1-board.sh`'s sha256, `git rev-parse HEAD`, and `git diff --quiet HEAD` of the harness, `kpf-decode.py` and `parse-s1.py`, and refuse a dirty tree. Before `jrun s1-h1`, Q17's params-hash check.
   - **New board functions,** in `BOARD_FUNCS` (Phase A only):
     - `b_kpf_snap TAG`: `dd iflag=skip_bytes,count_bytes` of `/proc/kpageflags` and `/proc/kpagecount` for window 2's page frames and c1's, into a `mktemp -d /dev/shm/s1kpf.XXXXXX`; `zoneinfo` and `buddyinfo`; a text header with the page-frame ranges, uptime and `boot_id`; sha256 of each file. The PC fetches, verifies and runs `privacy_scan` on the header, then the board function removes the directory. No tar;
     - `b_pci_state TAG`: for each PCI function, one line with its driver, parent, `power_state`, `enable`, the Command register from `config` offset 4 and the Bus Master bit. Plus the xHCI binding, rfkill `soft` and `hard` from `/sys/class/rfkill/*/`, each netdev's `operstate`, and NetworkManager and wpa_supplicant `is-active`. **No MAC, IP or SSID is ever read**: no `address` file, `ip addr`, `nmcli`, `iw`;
     - `b_census` (J1's reads, including the mount chain and the set file);
     - `b_trace_on` (under D21);
     - `b_wq_gen` (PC-side generation helper).
   - **`WQ_FUNCS`** (the only functions `declare -f` emits into `wq.sh` and `wqfb.sh`; none quiesces, pins, or writes `dynamic_debug`): `b_wq_mark`, `b_wq_slot`, `b_wq_bme`, `b_wq_oops`, `b_wq_uptime`, `b_wq_governor_read`, `b_freq`, `b_pci_state`, `b_trace_on`, `b_wq_issue`, `b_wq_abort`, `b_wq_fallback`.
   - **Exit codes:** 0-4 as today; **5** = rebooted by the sequence's abort or fallback, no kexec, a harness-reason retry.
   - **Exit-5, F43, F47, F48 and F25w returns:** `b_after`'s black-box copy and the parser are skipped; an optional `-l4t-console-ramoops.log` copy is scanned with the SSID class and never passed as `--blackbox`.
   - **`advice` / `cmd_advice`:**
     - parse `(run|p1|reboot|jrun|j3) NO RETURN within`, `run com3_bytes_before_kexec=` and `j3 com3_bytes_before_arm=`, and `wq_armed armed_epoch= wq_fallback_s=`;
     - **for any board log with `wq_armed`, print NO CUT in every class (F25a, F25b, F25w) until `armed_epoch + WQ_FALLBACK_S + 1,200 s` has passed;**
     - after that: any of `fallback firing`, `fallback forcing`, `abort reason=`, `kexec did not happen`, `Restarting system` or `reboot:` after the offset classes **F25b**, with M5's exception word for word; `Starting new kernel`, a shim line or a record line after the offset leaves today's F25a and F25b logic unchanged; otherwise, `s1wq:` markers alone class **F25w** (§15.7.3).
   - **Gate A and gate B for `j1`, `j3` and `jrun`:**
     - capture life ≥ return bound + 2,180 + `WQ_FALLBACK_S` for `j3` and `jrun control|remove` (as B2 for `b2repeat`, 1,800 s for `j1`);
     - `S1_COM3_LOG` must resolve inside the git-ignored `S1_RECORD_DIR`;
     - refuse a capture name already in `<rec>/used-captures.log`, and refuse a capture that holds an `s1wq:` marker or any earlier rung's output (today's `com3_has_records` misses L4T-only rungs);
     - `S1_REDACT_SSID` must be set.
   - **Refused environment variables:** `S1_WQ_*` and every existing fixed setting.
2. **`orin-native/s1/kpf-decode.py`** (new, stdlib, `SPDX-License-Identifier: MIT` like its siblings, `--selftest`; corrected 2026-09-14 during implementation: `parse-s1.py`, `mkcpio.py` and the repository `LICENSE` are MIT, not Apache-2.0).
   - **Classes** from `/proc/kpageflags` bits: buddy, slab, pgtable, LRU anon or file, compound head or tail, nopage, reserved, other held (count ≥ 1 and none of the above), free or tail (VENDOR_CLAIM for bits 0-26, docs.kernel.org `pagemap`; bit 32 HYPOTHESIS).
   - **Outputs:** per-canary class counts, per-MiB classes for c1-c3, a map of window 2 in 16 MiB buckets, and `prequiesce` → `postquiesce` counts for c2's pages (held-to-free, free-to-held, held-to-held), labelled "record only".
   - **Refusals:** a size not a multiple of 8; an entry count different from the header; a missing header.
   - **Every decode prints:** "kpageflags describe Linux's CPU-side ownership only; they cannot name the device that holds a page or predict where a device writes after kexec".
3. **`orin-native/s1/parse-s1.py`:** `run --diag j2|j2b|j4` sets `step=J2|J2b|J4`, keeps B2's line rules, and prints `verdict=diagnostic complete|incomplete`, never `pass` and never `b2=`. Self-test: a J `parse-s1.txt` never contains `b2=pass` or `verdict=pass`.
4. **Redaction:**
   - `S1_REDACT_SSID`, supplied by the owner in the environment and never written to a record, is passed to awk through `ENVIRON` (not `-v`, which expands backslashes), refused if shorter than 3 bytes, and added **both** to `ident_hits` as its own class (`ssid=N`) **and** to `redact`, so a copy whose only identifier is the SSID is never kept raw;
   - it is mandatory for every J rung;
   - `redact-selftest` gains: a file holding only the SSID (must not be kept raw), a 1-2 byte SSID (refused), an SSID containing a backslash, a colon-form MAC in a `wq.log`, a hyphen-form MAC, and a second host address for the Ethernet recovery path.
5. **Allow-list gate** on the generated `wq.sh` and `wqfb.sh` and on both `systemd-run` command lines, on the PC, before scp. It replaces the draft's prose with an exact list; everything not listed is refused.
   - **Command words and argument forms allowed:** `cat` of sysfs and `/proc` read paths; `ip link set dev <resolved> down`; `modprobe -r <resolved>`; `setpci -s <BDF> COMMAND` (read) and `setpci -s <BDF> COMMAND=0000:0004`; `kexec -u`; `systemctl kexec`; `systemctl reboot`; exactly one `systemctl reboot --force`; `systemctl is-system-running`; `sync`; `sleep`; `timeout`; `dmesg` (read; `dmesg -n 7` only inside `b_trace_on`); `sha256sum`; `date`; `readlink`; `printf`; `grep`; `ps` (D-state check).
   - **Redirect targets allowed:** the fixed `$HOME/<img>-<utc>-wq.log`; `/dev/kmsg`; `/sys/bus/{pci,platform}/drivers/<resolved>/unbind`; `/sys/module/kernel/parameters/initcall_debug`.
   - **Refused explicitly (one self-test injection each):** `rfkill`, `nmcli`, `iw`, `ip addr`, `systemctl (enable|disable|mask|stop|isolate)`, any path under `/etc`, `/boot` or `/var/lib`, `apt`, `dpkg`, `extlinux`, `--force --force`, `-ff`, `/dev/mem`, `devmem`, `dd`, `of=` on `/sys`, `tar`, and writes to `remove`, `rescan`, `reset`, `driver_override`, `new_id` or `power/control`; `address`, `serial`, `lsusb`, `hciconfig`.
   - **Self-test:** the real generated scripts for all three arms pass; each injected form fails.
6. **`harness-selftest` additions** (synthetic only):
   - `wq_state` for ARMED, PROGRESS, ISSUED, JUMPED (both evidence forms), ABORTED (three forms) and STALLED;
   - `advice` on a J4 log: markers and 400 s of silence with no jump print NO CUT; F25a-looking Linux shutdown text before the fallback deadline prints NO CUT; after the deadline, a reset marker classes F25b and markers alone class F25w; F25a and F25b unchanged after a jump;
   - gate A and gate B: a reused capture name, a capture holding `s1wq:` markers or J1 text, a capture outside the record directory, a missing SSID, all refused;
   - generation, via `bash -n`, a `%q` round trip, and a fixed slot count equal across the three arms;
   - `jrun` refusals, the no-`B*`-directory case, and the start-margin refusal;
   - the exit-5 branch skips the black box and the parser;
   - `kpf-decode --selftest`.
7. **TCG:** none. These rungs are L4T only; everything is synthetic on the PC.

### B. Image-changing (J6 only; next session)

1. **`orin-native/tools/memcanary.c`:**
   - `#ifdef MEMCANARY_WATCH` blocks: the constants; `unmix64` and `inv64`; the classifiers; the engine over a `const uint64_t *` for self-tests (three reads, `osc`, `prog`, `stable`); the stride histogram; the bitmap export; the lines; `cmd_watch`; `cw_selftest`;
   - one `#ifdef` usage line and dispatch branches;
   - a header comment paragraph;
   - no existing token changes when the macro is off.
2. **`orin-native/tools/Makefile` and `.gitignore`:** target `memcanary-w: memcanary.c` with `-DMEMCANARY_WATCH`, and `orin-native/tools/memcanary-w` ignored in the same change. A copy of the pinned `memcanary` binary is kept outside the tree before any build, as for the startup pin.
3. **`orin-native/startup/s1.build.in`:** `@J1@/proc/boot/memcanary-w=memcanary-w`.
4. **`orin-native/startup/s1-host.ksh.in`:** the `@BOARD@@J1@` watch and hold steps and the host-mode export block of §15.4.8, and `@TCG@@J1@memcanary-w --selftest`.
5. **`orin-native/startup/make-s1-images.sh`:**
   - **`PO_A_PATHS`** gains `s1-host.ksh.in`, `s1.build.in`, `make-s1-images.sh`, `orin-native/tools/Makefile` and `parse-s1.py`, in the same commit as the other B changes;
   - **New targets:** image `s1-j1` (not in the default list, host mode, diag `j1`); TCG variant `j1` (dryrun mode).
   - **Generator plumbing:** the prefix regex gains `J1`; the new markers (`@J1_HOLD_MIB@`, `@J1_HOLD_T@`) are added to the substitution list; `bounds()`; `ksh_worst` terms.
   - **`PIN_MEMCANARY_W`,** checked only when `s1-j1` or `j1` is built.
   - **`check_dumpifs_s1`:** `memcanary-w` present only in `s1-j1`.
   - **`profile_check`** recognises `memcanary-w` explicitly (today's scanner would skip it as a longer word after `memcanary`). The board `j1` script may call only `watch` with a compiled name and the bounded flags, and `memcanary hold` only with `@J1_HOLD_MIB@`. The TCG `j1` script may call only `--selftest`, once. Every other script must not contain it.
   - **`constant_check`:** the DRAM bound constant equals `T234_RAM_BASE` + 8 GiB; `@J1_HOLD_MIB@` is below windows 1 and 2's sysram size minus the canaries.
   - **`profile_selftest`,** by injection:
     - `watch -n c4`;
     - an address argument;
     - a `-d` outside `/dev/shmem/j1`;
     - an interval out of range;
     - a `watch` in a TCG script;
     - `--selftest` in the board script;
     - `memcanary-w` in `s1-h1.ksh`;
     - a hold size other than `@J1_HOLD_MIB@` in `s1-j1.ksh`.
6. **`orin-native/s1/build-s1tcg-image.ps1`:** `-Variant j1` (dryrun), with `memcanary-w` added to the tool list **only for that variant**, so no T1-T3 variant's tool list, `files.list` or params changes.
7. **`orin-native/s1/parse-s1.py`:**
   - `watch` and `words2`/`stride` regexes, and the `cans` filter excluding `watch=` lines, so B2's `six_verify_*` semantics are unchanged;
   - diag steps `("board","host","j1")` → `J6r|J6c` and `("tcg","dryrun","j1")` → `T-J1`;
   - a `canwatch` subcommand that decodes the bitmaps, checks structure and cross-checks counts against the console lines. It also sets bitmap pages against `kpf-decode` output from the same boot, and computes the fill-rate row. It never prints a value;
   - `run --diag j1`.
8. **Gates before J6** (PC, then TCG):
   1. **Determinism, in a scratch worktree on an uncommitted copy of the edit:** HEAD's `memcanary.c` and the edited file without the macro, each rebuilt to a scratch name, hash to `PIN_MEMCANARY`. B versus B' (separate source) is decided **before** any commit to main.
   2. **No drift, with `--out` set to a scratch git-ignored directory (or in a worktree), never the default output root:** a regeneration of `s1-m1b-p6`, `s1-h1`, `s1-n1`, `s1-n2` and `s1-d1`, and of every TCG variant through `make-s1-images.sh` **and** `build-s1tcg-image.ps1` (T1-T3 `files.list` and params), is byte-identical to the as-built files. Afterwards, `s1-h1.params`' `kimg_sha256` still equals the staged kimg's sha256.
   3. **The build of `s1-j1` passes every existing gate:** PO-A (with the new paths), pins, constants, profile check and its self-test, `kshcheck`, geometry, startup arguments read back as `-b w2,canary`, dumpifs names, tracked-path guard.
   4. **`parse-s1.py --selftest`:** synthetic bitmaps accepted; each malformation refused by name; `run --diag j1` never gives `pass`; B2's synthetic log with an added `watch=` line still gives `b2=pass`; a J6 log with `S1 BEGIN`/`S1 END` frames still classifies as `record` or `export-body` in `com3_last_kind`; `canwatch` output contains no 16-hex-digit value token, dotted quad or MAC pattern.
   5. **TCG `T-J1`:** `memcanary-w --selftest` passes, covering:
      - the pattern and inverse round trips;
      - one crafted value per class, with precedence (including `hi_pat`, `lo_pat`, `small32`, `flip2_same` against `flip2_var`);
      - signature positives at non-aligned byte offsets, and negatives, with documentation-reserved addresses only;
      - engine changes, heals, `osc` (A-B-A), `prog` (A-B-B and A-B-C) and `stable` on a heap buffer;
      - stride histogram;
      - bitmap round trip;
      - line lengths at maximum field widths;
      - refusals, including an address string and the black box.

      It maps no physical memory, and no `asinfo`, `verify` or `watch` runs under TCG.
   6. **Black-box budget (R22):** a generator check that the worst-case black-box text of `s1-j1` (the watch lines at maximum widths for four watches, the hold lines, the `S1 EXPORT` records, the `pidin syspage=asinfo` cap, and the `show` heads of each `.b` and `.err`) stays under the 60,000 B rebuild threshold.
9. **Pins and images:**
   - **Unchanged:** `PIN_STARTUP_S1`, `PIN_MEMCANARY`, and every existing kimg, params file and TCG script.
   - **New, all git-ignored:** `PIN_MEMCANARY_W` and `s1-j1.{build,ksh,ifs,kimg,params}`.
   - **Order:** determinism decided (8.1), then commit (PO-A), then build; stage and `p0` `s1-j1` before J6.

---

### 15.6 Classification rules (pre-registered), budget, owner decisions

**Classes for B2**

| Class | Holds when | Then |
|---|---|---|
| **Q: quiesce shortfall** (provisional) | all of: (1) J2 is F32, so the control is bad twice (B2 and J2); (2) J4 is F35, clean at both checks with the same image, timing, issuing context and harness except the removal set; (3) no F39 or F49 in any J rung; (4) no J6 run is F34; (5) the fix is exactly J4's removal, runtime-only, within the new Never items. Sub-label Q-p or Q-x by §15.4.6's split | The removal becomes a fixed harness setting for B-runs, with its override refused. Self-tests and the privacy scan pass. **Q becomes final only when all of these hold:** (a) J6r (`s1-j1`, remove arm) shows `writer=none` on c2, c1 clean, and the hold verifies; (b) **B1 reruns** and passes (D26); (c) **B2 reruns** with the unchanged `s1-h1` on a fresh boot under the fix and passes, **judged by §6.7 unchanged**. If any fails, the attribution is withdrawn and B2 stays data |
| **K-r: kill condition 1 stands, read instability** | c2 bad in J2 (F32, F32a or F32b), J4 not F35, and a J6 run is F34 | Recorded as "no writer shown; c2's reads are unstable". Revision 4: a range that avoids the unstable region, with a read-stability check in its B2. Not a device or firmware verdict |
| **K-w: kill condition 1 stands, a writer without Linux** | J4 is F36, a J6c run shows a live writer (`prog` above 0, or changed words with stable re-reads), **and** J7a (UEFI) is bad | Recorded as "writer unidentified; not the removable masters; not stopped by a firmware entry". Revision 4 derives a new range, with J7c's canaries in its B2 and J7e to separate H5 |
| **E: entry-path** | J4 is F36, and J7a (UEFI) is clean | Linux-caused, not stopped by any quiesce the rules allow. **Not a range verdict:** moving the window does not contain Linux's DMA. Owner (D31): a wider quiesce search in revision 4, UEFI entry for S1 under freeze item 3, or stopping S1-F |
| **U: unresolved** | any of: F33 (with J2b's F45 or F46 recorded as its lead); F32a or F32b with no J6 result yet; J3 not met (F41, F42, F44, F47), so no J4; F35 with a J6 run F34; F36 with no J6c writer shown (`writer=none` or `static`) and J7a not run or declined; F36 with J6 not F34 and J7a declined; F49 unexplained; any immediate stop below | B2 stays data, and S1-F stays stopped. Owner decides (D31) |

**Records.** B2's `parse-s1.txt` and verdict line are never regenerated or replaced. Every class line is appended, dated, and cites the J records and `J-prereg.log`. Public text changes class only when Q is final, or when the owner accepts K-r, K-w or E (§15.8).

**Budget**
- **Today's session:** J1 and J3 (L4T only), J2, and one of J4 or J2b (kexec): **at most two kexec and two L4T-only diagnostic runs.**
  - One harness-reason retry per rung does not count: a run that never reached `procnto up`, an exit-5 abort, or a J1 or J3 that stopped before its quiesce or reads.
  - A second harness failure on any rung stops the day.
- **After J4, J2b, or at any stop, return to the owner** with a number-free classification memo and the private J notes.
- **Revision total:** at most **four kexec diagnostic runs** (J2; J4 or J2b; J6 in the arm §15.4.8 names; and J6 in the other arm, or J5, only by D24 or D27) and two L4T-only runs. Anything more is revision 4.
- **The B1 and B2 reruns under class Q** are S1 ladder work, not diagnostic budget.

**Immediate stops**
- F30;
- any power cut (never a second);
- `EXC`, an SError or a silent hang after kexec;
- F37, F39, F41, F49;
- two refusals for one cause;
- any need for a startup change, a `memcanary` change, an SMMU read or a value dump (scope stop, revision 4).

**Owner decisions**

| # | Decision | Recommendation | When |
|---|---|---|---|
| D20 | Accept revision 3: the J ledger, §15.6's rule, the budget, F16 and F23 lifted for J rungs only, and J1's marker and transient-timer probe | accept | before J1 |
| D21 | Runtime trace settings on L4T (`initcall_debug`, console level 7) in J1, and in J2 and J4 as a matched pair after J1's go; never in J2b | accept: runtime-only, they name which shutdown hooks ran, and the arms stay matched | before J1 |
| D22 | Read-only page-frame snapshots to tmpfs, PCI config reads, and one Bus Master clear per function through `setpci ... COMMAND=0000:0004` only (no `dd` fallback) | accept: config space, not GPU MMIO; firmware resets PCIe at every boot | before J2 |
| D23 | GPU power-domain and EMC rate reads from debugfs (record only, never a gate) | accept as a diagnostic record; they are not the GPU checks deferred to the first GPU stage (plan:465), but the owner rules | before J1 |
| D24 | J4's removal set: "max" or wireless only; J5 at all; and whether today's second kexec goes to J4 at all, given that J4 tests only H4 and H4s (§15.3) | "max", with wireless only as the pre-registered fallback; J4 today, because it needs no image and its clean result is itself a fix; J5 not run | before J2 |
| D25 | The detached sequence in both arms, exit 5, the rule-5 exception for its three files, the narrowed F25w and its one cut, the advice hold until the fallback deadline; the Ethernet-cable variant as a recovery path only | accept, with F25w's one cut only as in §15.7.3 | before J2 |
| D26 | Rerun B1 after a harness-only fix | yes | before any rerun |
| D27 | Build `s1-j1` (classes, counters, page bitmaps, the large hold; no values), including the hold's margin constant. Also: under class Q, keep "max" as the fix or bisect (Q-x points at the xHCI first); whether J6 also runs in the other arm | build it; keep "max" unless the freeze manifest needs the device named; the other arm only if the first J6 leaves the class U | at J4's or J2b's memo |
| D28 | A restricted value export (J7d), never `other`, `ascii`, `pte`, `kva` or any QNX-structure class | no, unless J6 leaves `content=unclassified` and the owner accepts §15.7.4's terms | after J6 |
| D29 | Public wording: the direction of E2's count change; whether public text may name the removable device set and that the harness's ssh link is wireless. **A precondition of pushing the J0 commit and of pushing §15 as written** | allow both; never an SSID, MAC, IP or mask width | before any push |
| D30 | J7a, the UEFI arm | decide at J6's memo | after J6 |
| D31 | Accept the class (Q, K-r, K-w, E, U) and what follows | at each memo | memo |
| D32 | Where the exposure item goes (§15.8) | record it now in the plan | before B3 |
| D33 | Whether Q16 may read upstream function bodies through per-file web source views (no clone, archive or tree) | allow per-file views of the named functions only, or answer Q16 from documentation and patch discussion alone | before J0's desk reads close |

**Taken 2026-09-14 (owner).**
- **D20-D23:** accepted as recommended.
- **D24:** the "max" set, with wireless only as the pre-registered fallback. J4 runs today; J5 is not run.
- **D25:** accepted, including F25w's single cut.
- **Today's plan:** J1-J4 run in the owner's session once §15.5 A is implemented, reviewed and self-tested.
- **Still open:** D26-D33, with D29 due before any push.

---

#### 15.6.1 Session record, 2026-09-14 (number-free)

- **J1 met.** The census resolved all four removal-set members, none holding a mounted filesystem, swap, `$HOME` or the kimg directory. A `/dev/kmsg` marker and a transient timer's marker both reached COM3 (R57 and R59, unquiesced). The page-flag probe worked (R60), and the runtime trace printed per-device shutdown lines on a reboot, within the go rule (R56 and R73, for a reboot). Result: `next=J2`, trace go.
- **J2 ran to its jump and back cleanly.** The start margin was met. The detached sequence ran all nine slots with no overrun, issued the kexec from its unit, and the image reset back to L4T. The bootloader slot state was unchanged, and the sequence files were removed.
- **J2's canaries:**
  - c1 verified at both checks;
  - c2 was bad at both checks, as in B2;
  - **c3, clean in B2, was bad at both checks with an unchanged count.**

  The parser gave `j_row=F39`. **F39 is an immediate stop (§15.6): J3 and J4 did not run,** and the exposure item is raised for the owner (D32).
- **Record-only observations (HYPOTHESIS, one run):**
  - at the jump, both failing canaries sat on pages Linux held (slab for c2; page cache that appeared during the quiesce for c3), while c1 sat on free pages;
  - the kexec shutdown trace shows shutdown hooks called for the PCI functions, their root ports, the PCIe controllers, the SD host, the xHCI and the coprocessor drivers. What each hook did is not shown.
- **Harness defect found:** the COM3 marker extractor misses a marker preceded by stray bytes on the same line. It is report-only, did not affect the verdict, and is fixed before the next J rung.
- **Class for today: U** (an immediate stop), pending the owner's D31. B2 stays NOT MET on data.
- **Owner decision, 2026-09-14 (D34, new): F39's immediate stop is waived for J3 and J4 only, today.**
  - **Scope.** The waiver covers F39 as seen in J2 and nothing else. Every other immediate stop stands, including a second F39 in J4 and any F41, F42, F47 or F49. The budget of two kexec runs today and four for the revision is unchanged.
  - **How J4 is read under it.** F39 stays data, and J2 is recorded as F39, not F32. §15.6's class Q needs "no F39 in any J rung", so **class Q cannot hold under this waiver.** A clean c2 in J4 is then recorded as "the removable masters implicated for c2 only, with an F39 in the control". A bad c3 in J4 is a second F39 and stops the day. Every J4 outcome is class U until the owner rules on it (D31).
- **Owner decision, 2026-09-14 (D32): the exposure item is recorded now** in the plan's freeze gate.
- **Harness correction before J3, with a dated amendment to the pre-registration.** It has two parts:
  - the COM3 marker matchers now drop stray non-ASCII bytes before a marker, the defect found in J2. Re-extracting J2's own capture finds every marker in order;
  - the J3 precondition accepts J2's F39 only under D34's waiver, and only when c2 was bad at both checks and c1 was ok at both.

  `J-prereg.log` gains an amendment line with the reason and the new harness hash. **The rule text, the removal set, the decisions and the parser are unchanged,** so nothing that decides a class moved after J2's result.
- **J3: every step and gate met, except one gate that the harness read wrongly.**
  - **What met.** The removal sequence ran all nine slots with no Oops or overrun. Bus Master read zero on every endpoint and single-child root port before the end. The fallback timer fired and brought back a board with no network, without a power cut (R59, quiesced). Every removed device came back on the next boot (R58).
  - **The defect.** The harness printed `NOT MET F41-xhci` because its return read did not pass the xHCI path, so the xHCI rebind check had no line to match. The same read shows the xHCI's buses bound to their driver, and a direct read confirmed it.
  - **The fix.** The return read passes the path, with a self-test.
  - **Owner decision (2026-09-14).** J3 is re-judged from its own records: the original line is kept, a dated re-judged line is appended, and J4 runs.
- **J4: F36.** The removal arm ran to its jump and back cleanly, with the "max" set.
  - **What ran.** Every slot succeeded. Bus Master read zero on every endpoint and single-child root port before the issue. Both the uptime and governor guards passed, and the image reset back to L4T.
  - **The canaries.** c2 was bad at both checks, and c1 and c3 verified at both. So **the removable DMA masters are excluded as c2's writer, as this sequence quiesced them.** Per §15.3, J4 gives no evidence on H1, H2, H3 or H5.
  - **Record-only observations (HYPOTHESIS):**
    - c2 now repeats across B2, J2 and J4. The first mismatch was the first word each time, and the second count was lower each time, although Linux's use of those pages differed by boot and by arm;
    - c3 was held by Linux at J4's jump and stayed clean, which contradicts reading J2's c3 hit as "held pages are hit".
  - **What follows (§15.6 after F36).**
    - The memo goes to the owner.
    - Next is J6 in the control arm (J6c: content classes, re-read and heal counts, page bitmaps, and a large hold over sysram).
    - After that comes the owner's D30 on J7a, the UEFI entry arm, which separates Linux residue from a writer anchored at window 2's base.
    - The class stays U. Under D34, class Q cannot hold.
  - **Budget.** Today's two kexec runs and two L4T-only runs are used.
- **Owner decisions after J4 (2026-09-14, "follow the recommendations"):**
  - **D27:** build `s1-j1` (§15.4.8, §15.5 B), with the hold margin set by the implementation and recorded before J6.
  - **D29:** allow the [D29] wording: the direction of the count change, the wireless link and the device classes. SSIDs, MACs, IPs and mask widths stay out. §15 is pushed as written.
  - **D31:** today's class is U.
  - **D30 (the UEFI arm):** decided at J6's memo.
  - **Next:** J6 in the control arm (J6c), with the owner at the board.
- **Owner decisions before J6c (2026-09-14):**
  - **D34 extended to J6c.** J2's F39 does not block J6c. Every other immediate stop stands, including an F39 inside J6c itself.
  - **The fill-rate factor is 4,** pre-registered by J6's first stage and fixed for the revision.
  - **The J6 stage's amendment is named `owner-D27`.**
  - **J6c runs in the owner's current session.**
- **J6c: F39 again, an immediate stop.**
  - **The first attempt** stopped in the harness before any board session (an unset variable). A crash review with a stubbed dry run followed, and the fixes were pushed before the second attempt.
  - **The second attempt** ran to its jump and back cleanly with the watcher image.
- **What J6c's watches showed (HYPOTHESIS where interpreted):**
  - **c2's corruption is not read instability.** Re-reads were stable: no oscillation, no reverted misreads, no bit-flip classes.
  - **The writer is not active during QNX's run.** A handful of words healed once at the start, and then c2 did not change through the later watches, before and during the large hold.
  - **The corrupted words are data-structure shaped** (zeros and pointer-like values dominate). The classes alone cannot say whose structures they are.
  - **At the jump,** most bad pages were pages Linux held as slab, but whole slab-dense parts of c2 were untouched.
  - **Window 1 was not written during the watches:** c1 was clean at every scan, and the large hold over sysram verified.
  - **c3 again carried a small static write,** at a different place from J2's.
- **What follows.** Three of the revision's four kexec runs are used. §15.6 stops here: the class stays U, and the owner decides. D30's UEFI-entry arm (J7a) is the test that separates a Linux-left writer from one anchored at the window-2 base.
- **Owner decision, 2026-09-14 (D30): J7a, UEFI entry.** A short J7a design is written and reviewed before anything is built. It has to settle the exceptions to §2 rule 5 (the ESP write), the TX refit, firmware use of window 2 (§3.2, never checked) and how its result is read under §15.6. No board step runs before the owner approves that design.

### 15.7 Claims, failure signatures, risks

#### 15.7.1 Claims (the §9 table continues)

| # | Claim | Class | Answered by |
|---|---|---|---|
| R43 | E1 as stated | VERIFIED (one run) | B2 |
| R44 | ZONE_Normal starts at c2's base; ZONE_DMA covers window 1 | VERIFIED (one boot) | D0 read |
| R45 | kpageflags snapshots describe Linux's CPU-side page ownership at the snapshot moments only; they cannot predict DMA targets after kexec under R46 or a stale translation, and a quiesce frees pages everywhere whether or not H1 holds | VERIFIED (limit, from the interface's definition) | — |
| R46 | `disabling translation` leaves the T234 SMMUs in bypass for attached masters | HYPOTHESIS (VENDOR_CLAIM upstream, E15-E16; fork unread) | Q16; only J7b proves it |
| R47 | The kexec shutdown clears PCI Bus Master on endpoints and root ports in D0-D3hot | HYPOTHESIS (VENDOR_CLAIM, E17) | Q16; J3 and J4 read it only before the issue |
| R48 | Under R46, 32-bit PCI IOVAs land below 4 GiB, which includes window 1 | HYPOTHESIS | Q16; exposure item |
| R49 | The GPU's DMA is CPU-physical with no SMMU | reported VERIFIED (E11) | — |
| R50 | H1: GPU residue writes after kexec | HYPOTHESIS | J4 plus J7a; J6 supporting |
| R51 | H2: a firmware user of window 2's base invisible to `/proc/iomem` (refines R17) | HYPOTHESIS | J7a; J6 |
| R52 | H3: c2's reads are not stable | HYPOTHESIS (motivated by E2) | J6's F34 rule |
| R53 | H4: a removable Linux master writes c2 | HYPOTHESIS | J4 |
| R54 | H5: a QNX-side writer at the window-2 base | HYPOTHESIS, low | J6 classes; revision 4 |
| R55 | c2's result repeats under B2's conditions | UNKNOWN | J2; J2b |
| R56 | `initcall_debug` is writable at run time, and `device_shutdown()` prints one line per device when it is set | HYPOTHESIS | Q16; J1 |
| R57 | A `/dev/kmsg` write at level 3 reaches COM3, from a login shell and from a transient unit | HYPOTHESIS | J1 (unquiesced); J3 (quiesced) |
| R58 | The unbinds and the module removal are runtime-only; every device returns on the next boot | HYPOTHESIS (out-of-tree drivers) | J3 |
| R59 | A `systemd-run` timer armed after `isolate multi-user` fires on the quiesced L4T; transient units vanish at reboot | HYPOTHESIS (systemd-run(1)) | J1 (timer fires, unquiesced); J3 |
| R60 | `dd` with `skip_bytes` reads `/proc/kpageflags` at an offset, and the needed tools are present | HYPOTHESIS | J1 |
| R61 | kpageflags bits 0-26 mean what the kernel documentation says; bit 32 is reserved | VENDOR_CLAIM (0-26); HYPOTHESIS (32) | `kpf-decode --selftest` |
| R62 | The L4T hardware watchdog resets a panicked or oopsed L4T inside the detached sequence | HYPOTHESIS (configured: reported VERIFIED, E18) | not provoked |
| R63 | Unbinding the xHCI stops the XUSB falcon | HYPOTHESIS | not shown by any J rung |
| R64 | `memcanary.c` without the macro recompiles byte-identically to `PIN_MEMCANARY` | HYPOTHESIS | B8.1 determinism gate |
| R65 | A long read-only `mmap_device_memory` watch of 16 MiB above 4 GiB works at EL2 within its bounds | HYPOTHESIS | J6 |
| R66 | The word classes and byte signatures match their public specifications | HYPOTHESIS | self-test encodes the reading |
| R67 | A UEFI entry leaves no Linux residue, and UEFI's allocations avoid c2 | HYPOTHESIS | J7a |
| R68 | RCE keeps writing inside its IOVA window after kexec, which overlaps window 1 | HYPOTHESIS (window VERIFIED from the DT, E13) | J7c's window-1 canary; exposure item |
| R69 | E2's inference: words returned to the pattern, so a restoring writer or unstable reads | VERIFIED arithmetic, given faithful reads (`memcanary --selftest`; c1 and c3 verified) | J6 separates the two |
| R70 | A hold sized near sysram covers most of window 2 and much of window 1 | VERIFIED arithmetic on the design sizes (pigeonhole); physical placement HYPOTHESIS | J6's hold |
| R71 | A third immediate read separates a marginal read (A-B-A) from a writer in progress (A-B-B, A-B-C) | HYPOTHESIS (a writer could also produce A-B-A by restoring within microseconds) | J6 |
| R72 | `systemctl is-system-running` reads `stopping` while a kexec shutdown is under way, and transient units are stopped by that shutdown | HYPOTHESIS (systemctl(1)) | Q16; J2 and J4 markers |
| R73 | The per-device shutdown print is at an informational level, so it reaches COM3 only with the console level raised | HYPOTHESIS | Q16; J1 |
| R74 | `setpci ... COMMAND=0000:0004` changes only bit 2 of the Command register | HYPOTHESIS (setpci(8), from memory) | Q16; J3's read-back |
| R75 | procnto places a large anonymous allocation across both windows | HYPOTHESIS (only the pigeonhole bound is arithmetic) | not shown |
| R76 | H4s: SMMU page tables that were Linux pages become QNX sysram after kexec, and QNX's use of them moves write targets | HYPOTHESIS | J6 fill-rate row; J4 |

**Desk questions:** Q16 and Q17 (§15.4.1); **Q18:** the debugfs paths for the GPU power domain and EMC rate on 5.15-tegra (documentation only), needed by D23.

#### 15.7.2 Failure signatures (the §7.2 table continues)

| # | Observable | Meaning | Class | Next |
|---|---|---|---|---|
| F32 | J2 or a J6 control: c2 bad at both checks, c1 and c3 ok | repeats | SR | §15.4 tables |
| F32a | J2: c2 bad at the start check, ok at the end check | a restoring writer or read instability, before QNX's checks | SR | stop kexec work; memo; J6c first |
| F32b | J2: c2 ok at the start check, bad at the end check | onset after the start check | SR | stop kexec work; memo; J6c first |
| F33 | J2: c2 ok at both checks | not reproduced under the J additions | SR | J2b; class U |
| F34 | J6: `osc` above 0, `flip2` dominant, `prog` 0 | read instability or a hardware class | SR | stop; memo; K-r (U after F35) |
| F35 | J4: c2 ok at both checks | removed set implicated | SR | class Q (provisional); Q-p or Q-x |
| F36 | J4: c2 bad | removable masters excluded as quiesced | SR | memo; J6c |
| F37 | detached run: COM3 ends in L4T text after `kexec issuing`, no shim, no ssh | Linux hang in the detached shutdown | PP only by §15.7.3 | the diagnosis ends for the day |
| F38 | no per-device trace on COM3, or the trace too slow | observation defect | — | continue without the trace in both arms |
| F39 | c1 or c3 bad in any J rung, or `watch=base bad` above 0 on c1 | the writer reaches beyond c2 | SR | stop; owner; exposure item raised |
| F40 | `refuse=`, `map=fail`, `S1 ASINFO` differs from B2, `watch=fail` | image, tool or harness defect | SR | §5.3 defect path; one retry |
| F41 | after any return, no ssh, or a removed driver not bound | persistent state touched, or a driver did not reload | — | stop board work; §15.7.3 item 8 |
| F42 | J1 or J3: markers not on COM3, or the fallback did not fire | the detached mechanism is unproven | — | no J3 or J4 until fixed |
| F43 | J2 or J4 ABORTED (exit 5) for `kexec-rejected`, `kexec did not happen` or `resolve` | no kexec happened | SR (L4T reboot) | one retry on a fresh boot |
| F44 | Bus Master still set after unbind and clear, or `setpci` absent when a clear is needed | the removal cannot be shown | — | the sequence aborts and reboots; memo |
| F45 | J2b: c2 bad | the J additions change the writer's behaviour | SR | stop; memo; class U with a lead |
| F46 | J2b: c2 ok at both checks | intermittent | SR | stop; memo; class U |
| F47 | `abort reason=oops`, or a D-state task in the sequence | an unbind or removal oopsed or hung | — (F27 recorded) | exit 5; no J4 if in J3; memo |
| F48 | `abort reason=uptime` or `abort reason=governor` | an issue-time guard refused the kexec | SR (L4T reboot) | one retry on a fresh boot with a larger start margin |
| F49 | J6: the hold's verify bad | a writer in sysram outside the canaries, or QNX-side | SR | stop; owner; exposure item; Q cannot become final |
| F25w | after the offset: `s1wq:` markers, and **none** of `fallback firing`, `fallback forcing`, `abort reason=`, `kexec did not happen`, `Restarting system`, `reboot:`, `Starting new kernel`, a shim line or a record line; the fallback deadline plus 1,200 s has passed | L4T is alive with no network, and its fallback did not act | — | §15.7.3 item 6. A reset marker after the offset means a firmware boot may have started: the capture is F25b, not F25w |

**2026-09-14 (implementation, before J6's pre-registration):** F34, F40 and F49 for J6 are read through §15.12: F34 counts reverts beside `osc`; a `watch=fail reason=nomem` on watch c or d is F40.

#### 15.7.3 Recovery when a detached sequence does not reach kexec

In order. The owner stays at the plug throughout. **For any board log with `wq_armed`, `advice` prints NO CUT in every class until `armed_epoch + WQ_FALLBACK_S + 1,200 s` has passed** (§15.5 A1).

1. **A precondition fails inside the sequence** (wrong driver, root port with more than one child, `kexec_loaded` 0, Bus Master still set, an Oops or D-state task, the issue-time uptime or governor guard): `abort reason=…`, then `kexec -u`, `sync`, `systemctl reboot`. Exit 5.
2. **`systemctl kexec` returns non-zero:** `abort reason=kexec-rejected`, then as item 1. Exit 5.
3. **`systemctl kexec` returns 0 but no jump follows:** after `WQ_ISSUE_WAIT_S` the sequence reads `systemctl is-system-running`. `stopping`: it only marks and exits, and the shutdown continues (item 5). Otherwise it marks `kexec did not happen`, then `kexec -u` and reboot. Exit 5.
4. **The sequence hangs** (for example an unbind in D-state that the per-slot check could not see in time): the fallback timer fires at `armed_epoch + WQ_FALLBACK_S`; unless the system is `stopping`, it runs `kexec -u`, reboot, then after 120 s one `reboot --force`. A reboot blocked by a D-state task may end through systemd's own shutdown timeouts (HYPOTHESIS).
5. **Oops or panic during an unbind, or the shutdown stuck after `kexec issuing`:** the watchdog systemd arms under L4T resets the board (R62), or the shutdown finishes slowly. A slow shutdown with growing COM3 is not a hang. pstore keeps any Oops record. This is F10 and F25a as today, held by the advice rule above until the fallback deadline.
6. **F25w** (markers only, no reset marker, no jump, no record line; the deadline has passed): `advice` prints **NO CUT** until all of these hold:
   - COM3 has been silent for 10 minutes, with no firmware banner and the last output not a menu or prompt;
   - no ssh answer in that time (in J4 this adds no evidence once the wireless function is removed; in J2 it does).

   Then, under D25, **one** cut is allowed: no reset marker followed the offset, so the running L4T is the boot that was validated at the rung's start (F25a's reasoning). Before that, the non-cut paths are:
   - wait for the fallback;
   - if J4's set left the Ethernet driver bound (the wireless-only set), the owner fits an Ethernet cable, finds the new address by scanning the /24, and runs `sudo systemctl reboot`;
   - if J1 found a USB keyboard and the xHCI was not unbound, a local login and reboot.
7. **Any reset marker after the offset** (`fallback firing`, `fallback forcing`, `abort reason=`, `kexec did not happen`, `Restarting system`, `reboot:`) followed by silence: a firmware boot may have started, so that boot is unvalidated. The capture is **F25b**, and M5's exception applies word for word (§2 rule 6a). **Never a second cut.**
8. **A return without the wireless function** (F41): the changes are runtime-only by design, so a second reboot is the first remedy, over the Ethernet cable if needed. No cut on this ground alone.

**After any failed or cut path:** the next harness command removes the board-side sequence files first and records the removal (§15.4.3's rule-5 exception).

#### 15.7.4 Risks

- **Privacy of captured data.**
  - This revision captures **no network frames** and exports **no canary values**.
  - The raw COM3 capture may still hold driver messages printed during the wireless removal and, with the console level raised, during the shutdown. mac80211-style deauthentication lines carry MACs, and a vendor driver may print the SSID or BSSID (HYPOTHESIS).
  - Mitigations: the raw capture must lie inside the git-ignored record directory and is never copied, quoted or scanned by hand; redacted copies only, with MAC (colon and hyphen forms), IP, user, hostname, key name and (new) SSID classes, the SSID counted in `ident_hits` so an SSID-only file is never kept raw; the privacy scan on every text copy, including `wq.log` and its `dmesg` tail; no tar archive, so no user or group name inside a binary record.
  - The `.bin` snapshots and bitmaps carry page flags and offsets, not content, but still count as run records.
  - If D28 is ever taken, a value export would carry base64 through the raw capture, where regex redaction cannot reach. It would therefore be limited to non-network, non-QNX-structure classes, decoded into a private directory, and never printed.
- **Perturbation.** The snapshots, the dwell, the unit as issuer and the trace change timing and page state on the kexec boot. J2 and J4 carry the same additions, so the removal set is the only difference between the arms; J2b is the only repeat without them. Synchronous console output from the trace lengthens the kexec shutdown (HYPOTHESIS); the J1 go rule bounds it, the advice idle clock counts only silence, and an F33 read with the trace on sends J2b, which runs without it.
- **What J4 tests.** Only H4 and H4s (§15.3). A clean J4 is read through the Q-p and Q-x split, never as "the quiesce defect of the whole class".
- **Moved writer.** Removing devices changes the slab and page-cache layout at the jump, so a live writer could land somewhere else and leave c2 clean while corrupting other memory (HYPOTHESIS). The canaries see only three 16 MiB windows; the large hold in J6r is the detector, which is why Q-final requires it.
- **Intermittency.** With n=1 per arm, an intermittent writer can fake class Q (§15.4.6's false-Q estimate). J2b, J6r and the B2 rerun are the further tests.
- **Linux shutdown Oops** on the reboot, abort and fallback paths is known after long uptimes (§14.12). Every J rung meets the start margin, and the sequence refuses to issue at or above the quiesce limit.
- **Board bookkeeping.** `used-boot-ids.log` must record `by=j1|j2|j2b|j3|j4|j6r|j6c`; `used-captures.log` records each capture once. A J2 or J3 return boot is fresh; a J1 boot is never used for a quiesce.
- **Params overwrite.** A generator regeneration with the default output root would rewrite `s1-h1.params` with `kimg_sha256=-` and break the staged kimg's identity; gate B8.2 runs only in a scratch output, and Q17's check refuses a J run or a B2 rerun if it happened.
- **Scope creep.** The tempting next reads (SMMU registers, GPU state, content dumps) are on the Never list or reserved, so they each come back to the owner.

---

### 15.8 Public text while this is open, and the exposure of earlier rungs

**Public text (number-free).** Number-free status lines are pushed, following the f33611d precedent (M5-F recorded as met, number-free). **Not pushed:** evaluation figures, J records, class memos and run notes, which stay git-ignored or on `m3-results-unpublished` until the 4.6(i) consultation.

- **`s1-design.md`:**
  - §15 as above, after D29 (or with the substitutions below);
  - the header gains a revision-3 line;
  - one dated pointer line each at §0's "What it is not", §5.3's B2 data bullet, §6.12's B2 row, F16, F23, R17, D8, §2 rule 5 (the dated exception) and §14.12's "What follows": "2026-09-14 (owner, D8 option 1): writer diagnosis first, §15; B2 stays NOT MET on data until §15.6's rule says otherwise".
- **Plan S1-F block:**
  - replace "Nothing of S1 has run on the board" (plan:484) and the ladder line (plan:402) with: "B0 and B1 met; B2 not met on data at the lowest window-2 canary; S1-F stopped; B3-B5 not run; the writer is under diagnosis (s1-design §15)";
  - the risk row for S1-F notes that the second window's ownership is now in question;
  - plan §8 unknown #6 gets a dated annotation (below).
- **`findings.md`:** a dated entry for B0-B2 and the decision, in the T1-T3 entry's format, with "What it does not show": no writer identified; nothing about the rest of window 2; no Linux guest on the board; no timing; no containment.
- **`CLAUDE.md` Phase 3b:** replace "Nothing of S1 has run on the board; B0-B5 are next" with the same status. Next-actions item 3 says S1-F is paused in writer diagnosis.
- **README:** no change on `main`. Any status phrase goes only to the PR #1 branch, and its merge stays the owner's.
- **Never in public text:**
  - a count, offset, page class figure, page-frame number observed in a run, uptime, boot id, IOMMU group, PCI address, DMA mask width or kernel-placed address;
  - a MAC, IP or SSID;
  - "quiesce defect", "fixed" or "reclassified" before class Q is final;
  - that the writer *is* a named device or firmware, except as labelled HYPOTHESIS;
  - anything softening "NOT MET, on data".

**Neutral substitutions if D29 declines**

| [D29] wording | Neutral public form |
|---|---|
| the second mismatch count was lower; words returned to the pattern (E2, C21, K-d, R69) | "the mismatch count differed between the checks"; the inference is withheld from public text |
| the harness's ssh link is wireless; removing the wireless function drops ssh | "the harness's network link"; "removing a device drops the harness's link" |
| the removal set's device classes (wireless, Ethernet, NVMe, xHCI) | "the removable DMA-capable devices" |
| E9's device list | "DMA-capable devices were listed privately" |

If D29 declines, §15 itself is pushed only as a pointer plus these neutral forms; the full text stays in the private record.

**Exposure of earlier rungs (a risk statement, not a reopening)**
- **Window 2** was never claimed before B2: M0-M5 and B1 had no `-b` (`board/init_raminfo.c`). A writer confined to c2's range could not have touched QNX memory in those rungs.
- **Window 1 is exposed in a way c2 does not cap:**
  - **GPU residue (H1)** can land on any page nvgpu held, including ZONE_DMA, which contains window 1.
  - **Under R46 and R48,** a still-active 32-bit PCI master's writes land below 4 GiB.
  - **RCE's IOVA window** overlaps the upper part of window 1 (R68).
  - **Every kexec rung** showed the SMMU disable (E4) and the GPU teardown error lines (E5): M1 and M1b without the module quiesce; M3, M4, 11c, B1 and B2 with it.
  - **M5-F** entered from UEFI with no Linux, so it is exposed only to firmware-class writers (UNKNOWN).
- **What limits the risk:**
  - c1 (top of window 1, inside RCE's window) was clean at both B2 checks, in one run;
  - M3's md5 and `cmp` checks passed for the files they covered;
  - no rung crashed in a way that points at memory corruption.

  None of this rules out writes into unused or rarely read pages. B1's unexplained thread-count difference is not evidence of this and is not linked to it.
- **Verdicts stand.** M0-M5's functional verdicts (booted, banner, IPC completed, startup reached) rest on no memory-integrity claim, and m5-design and plan:456 already disclaim DMA quiescence.
- **Where it goes (D32):**
  - freeze gate item 3 gains a sub-item: "DMA quiescence after kexec is shown for the claimed windows (s1-design §15's class), or v1 declares the exposure and the campaign carries a window-1 watch";
  - the v1 manifest's entry-path field gains "DMA quiescence: shown / not shown";
  - plan §8 unknown #6 is annotated with B2's observation and R48 and R68, and stays HYPOTHESIS;
  - a window-1 canary is a J7c and revision-4 item, because it is a startup change;
  - until then, no campaign record claims memory integrity or rests on a clean kexec entry.

---

### 15.9 What this revision does not show

- **Nothing here identifies the writer.** H1-H5 are HYPOTHESIS until J2, J4 and J6 run, and J7a where it is needed.
- **J4 excludes or implicates only the removable masters, as removed by this sequence.**
  - It says nothing about the GPU, the coprocessors, the SD host or display, and gives no evidence on H1, H2, H3 or H5.
  - A clean J4 is provisional until J6r's hold, a B1 rerun and a B2 rerun under the fix pass.
- **The page-frame snapshots show Linux's CPU-side page state at the snapshot moments, not at the jump, never which device owns a page, and nothing about where a device writes after kexec.**
- **J6 shows classes and page positions, not identity.**
  - It cannot see writes before startup's fill, or a write and restore faster than one scan; the hold sees writes in its pages but cannot locate them physically.
  - Its signatures are readings of public specifications, positive-only, with false positives above zero.
- **Whether the SMMUs were in bypass after kexec, and whether PCI Bus Master stayed clear through the shutdown, rest on log lines and upstream behaviour.** No register is read after the shutdown starts.
- **Nothing about the rest of window 2 or of window 1** beyond the canaries and, in J6, the hold's coverage arithmetic.
- **Nothing about a Linux guest on the board.**
- **No timing.**
- **No isolation or containment.**
- **Not repeatability beyond the runs made.**
- **No evaluation figure is publishable** before the 4.6(i) consultation; only number-free status lines are pushed (§15.8).

---

### 15.10 Where the four analyses disagreed, and what this draft chose

| # | Point | Options in the analyses | Chosen | Why |
|---|---|---|---|---|
| 1 | Rung names | harness: R0/W0/D1-D3/E0; design rules: J | **J** | R and D are existing table ids in this design; J is unused |
| 2 | Where the revision lives | a separate file; §15 of s1-design | **§15**, with implementation detail in its subsections | §5.3, F16, F23 and D8 are the rules being amended; two documents could disagree about B2's class |
| 3 | Ranking | QNX instrument: wireless under stale translation first; harness and design rules: wireless as the first A/B variable; Linux mechanisms: GPU first | **GPU (H1) above the removable masters (H4)**; firmware second; read instability and QNX low; H4s kept as a sub-hypothesis | E4 with E15-E17 (bypass sends 32-bit IOVAs below 4 GiB), E2 (a restoring writer does not fit RX appends, HYPOTHESIS) and E11 (the GPU has no SMMU). The QNX analysis's stale-translation case needs R46 to be false; it is kept as H4s with its own J6 row. J4 still comes first for cost reasons, with its limits stated (§15.3) |
| 4 | First test arm | wireless only (design rules); "max" (harness) | **"max"**, with wireless only as the pre-registered fallback | The priors weaken wireless alone, and the budget is small: one run excludes or implicates the whole removable class, and both outcomes classify. Bisecting only follows a clean result (D27), toward the xHCI first under Q-x |
| 5 | A GPU arm (Linux mechanisms: no `rmmod nvgpu` control, or a GPU-state gate) | run it; defer | **Reserved (J5)**; GPU state read as a record only (D23) | It relaxes a fixed setting, and the budget goes to arms that classify. C24 shows only that the same error **lines** appear on both paths; it does not show the same GPU or page state, so the arm is not shown to be uninformative (corrected after the power review). The decisive H1-versus-H2 test is J7a |
| 6 | Where the instrument's code lives | a new mode in `memcanary` (moves `PIN_MEMCANARY`); a second binary from the same source; a separate `canaryshape` source | **A second binary from the same source behind a determinism gate; separate source as the fallback** | Keeps `memcanary`'s pin and every existing kimg byte-identical, so a later B2 rerun changes one variable; reuses the refusal code B2 exercised |
| 7 | What leaves the target | QNX instrument: a private binary dump of values through `tcu-cat`; Linux mechanisms and design rules: counters and classes only | **Counters, classes and page bitmaps only, through `xport`; values reserved (D28)** | The owner's rule requires any capture of frames to be private **and** redacted. Base64 in the raw COM3 capture cannot be redacted by the harness's regexes. Classes answer the ranking's questions first |
| 8 | Signal classes | QNX instrument: pattern copies, pointers, signatures; Linux mechanisms: bit-flip histogram | **Both,** plus half-pattern, small-integer and stride classes, and a three-read `osc`/`prog` split | H3 needs the flip and oscillation classes; H2, H4 and H5 need the pattern, ring and structure classes |
| 9 | Rehearsal | three L4T boots (W0a, W0b, W0m) | **One rung (J3) with `FINAL=none` and J4's exact set**, after J1's cheap marker and timer probe | The fallback firing proves the stronger recovery claim with the same `systemctl reboot` the sequence would issue; rehearsing the exact set avoids a gap; it saves two boots of owner time |
| 10 | SMMU `sCR0` read | owner approval (Linux mechanisms); Never (design rules); flag only (QNX instrument) | **Out of revision 3; on the new Never list; J7b in revision 4** | An SError at EL2 is a power-cut class, and the read needs its own design |
| 11 | Extra canaries (window-2 grid, window-1 in RCE's window) | now (Linux mechanisms); later (others) | **Revision 4 (J7c)** and the freeze gate; J6's hold covers sysram in the meantime without a startup change | Any constant change reruns B1 and moves `PIN_STARTUP_S1` |
| 12 | Budget | three board rounds (design rules); open-ended (harness) | **Two kexec and two L4T-only runs today, then the owner; four kexec in total** | Keeps the owner's day bounded and the A/B pair intact |
| 13 | NVMe in the removal set | the harness assumed it holds the root filesystem and cannot be removed | **J1 decides from every mount, swap and the storage parent chain of `$HOME` and `KD`** | Where the root filesystem lives is UNKNOWN here; an unused drive is a removable master |
| 14 | The Ethernet-cable variant (harness E0, D2E) | a test arm | **Recovery path only (D25)** | An active Ethernet driver is a new confound, and "max" unbinds it anyway |
| 15 | B1 rerun after a harness-only fix | §5.3's "only if startup changed"; D8's "reruns B1 and B2" | **Rerun B1 (D26, recommended)** | D8's wording was accepted, and the quiesce is part of B1's entry |

---

### 15.11 Review outcomes

#### 15.11.1 Conflicts between reviewers, and how they were resolved

| # | Conflict | Resolution |
|---|---|---|
| X1 | Safety (major 1) wanted J2's snapshots and PCI reads moved out of `b_kexec_go`, or its ssh timeout raised; power (blocker 1) wanted J2 to become a null-set detached arm; power (major 7) wanted the final snapshot dropped | Power's blockers 1 and 7 were applied: J2 no longer issues through `b_kexec_go`, and no snapshot is taken at the jump. Safety's ordering rule was carried into the sequence: nothing slow between the governor read and `systemctl kexec`, and on a Phase A timeout `kexec_loaded` is read and `b_unload` runs before exit 3 |
| X2 | Power (blocker 1) puts a detached kexec (J2) before the fallback rehearsal (J3); safety's lens wants the detached path proven before a jump depends on it | J2 keeps ssh up, so the PC can stop the units and unload at any point before the issue; and J1 now proves the `/dev/kmsg` marker path and a transient timer firing before J2. J3 still proves the no-network fallback before J4, the only arm without ssh |
| X3 | Power (blocker 4) asked for J2b as "`cmd_run` unchanged"; feasibility (major 4) showed that `cmd_run` on `s1-h1` writes a `B2-aN` attempt and a pass-looking B2 parse | J2b is `jrun s1-h1 b2repeat`: `cmd_run`'s B2 flow with no additions, `STEP=J2b` set after `resolve_kimg`, and `run --diag j2b` |
| X4 | Safety (minor 12) and feasibility (minor 13) both flagged the trace's console cost. Safety offered "the default console level"; feasibility offered "drop the trace from J2 and J4 and rely on J1's reboot"; power's matched-arm change requires the arms to be equal | Trace in J2 and J4 as a matched pair or in neither, never in J2b, gated by J1's go rule (lines present, shutdown section under half of `S1_STUCK_S`). Safety's default-console-level option was rejected: the per-device print is informational (R73, HYPOTHESIS), so it would not reach COM3. Feasibility's J1-only option was rejected: a reboot is not a kexec shutdown (E17's condition), so J1 cannot show which hooks ran at kexec |
| X5 | Safety (major 4) and feasibility (major 8) described the same advice defect with different fixes (a hold on every class versus wiring F25w before F25a) | Both applied: offset keys parsed for J logs, NO CUT in every class until the fallback deadline plus 1,200 s, then F25w decided before F25a with safety's narrowed definition (major 5) |
| X6 | Safety (major 9) and feasibility (major 7) both asked for an exact allow-list, with different contents | Merged into one exact list (§15.5 A5), including `WQ_FUNCS`, `ip link set dev … down`, the redirect targets and both `systemd-run` lines. Safety's "`rfkill` except a read" became stricter: no `rfkill` command at all, state read from sysfs |
| X7 | Safety (minor 13) and feasibility (minor 10) both asked for rule-5 handling of the sequence's files | Merged: one dated rule-5 exception for three named files, removal on every return path, leftovers removed by the next command |
| X8 | Power (blocker 2) asked for the hold "in any B2 rerun that is to make Q final"; the revision's Never items forbid changing `s1-h1`, and class Q requires the B2 rerun to be judged by §6.7 unchanged | The hold goes into `s1-j1` only. Q-final requires a J6r run (remove arm, with the hold) **and** the unchanged B2 rerun |
| X9 | Safety (minor 15) wanted D29 before the J0 commit; feasibility (major 9) found D29 wording already in the draft | Driver names are resolved at run time, so the commit carries none; D29 gates any push of the commit or of §15 as written, and a substitution table gives neutral wording |
| X10 | Power (major 8) wanted `b_pci_state final` in J2 to decide whether E17 is false; safety's and the draft's own limits note that the read comes before the shutdown | The split was applied as Q-p and Q-x, with the limit stated: the read shows the Bus Master state before the shutdown only, so Q-p is an interpretation (HYPOTHESIS), not a proof that E17 is false |

#### 15.11.2 Every required change

| Reviewer | Severity | Issue | Applied or rejected | Why |
|---|---|---|---|---|
| safety | major | J2's snapshot work inside `b_kexec_go` can exceed the 300 s ssh timeout between load and issue | applied (adapted) | J2 and J4 issue from the detached sequence and no snapshot is taken at the jump (X1); the sequence keeps nothing slow between the governor read and `systemctl kexec`; a Phase A timeout reads `kexec_loaded` and runs `b_unload` before exit 3 |
| safety | major | uptime limits checked only at rung start; the detached dwell can push the issue past 1,800 s | applied | issue-time `abort reason=uptime` at 1,800 s (7,200 s without exception), fixed in the script; start margin = start uptime plus the printed worst case under 1,800 s |
| safety | major | one-capture rule: `com3_has_records` misses L4T-only rungs, so J1's or J3's capture could be reused | applied | `used-captures.log`, refusal of captures with `s1wq:` or earlier rung output, "stop the previous capture" in the boot chain, self-tests |
| safety | major | advice cannot parse J logs and may advise a cut before the fallback deadline | applied | offset and NO RETURN keys for `jrun` and `j3`; NO CUT in every class until `armed_epoch + WQ_FALLBACK_S + 1,200 s`; self-tests (X5) |
| safety | major | F25w allowed a cut after the fallback or an abort had already reset the board | applied | F25w requires no reset marker; any reset marker classes F25b under M5's exception word for word (§15.7.2, §15.7.3 item 7) |
| safety | major | the sequence did not abort on a kernel Oops during unbind or removal | applied | per-slot and pre-issue Oops and D-state scan with b_quiesce's pattern; `abort reason=oops` (F47), also in J3's gates |
| safety | major | `dd` config-space write fallback is an unmasked general write primitive | applied | only `setpci -s <BDF> COMMAND=0000:0004` with read-back; no fallback; `dd` and `of=` on `/sys` refused; `setpci` absent means F44 |
| safety | major | only NVMe had an in-use rule; other mounts, `$HOME` and `KD` could sit under a removed controller | applied | J1 records every mount, swaps and the parent chain of `/`, `$HOME`, `/dev/shm` and `KD`; a controller with a mounted or swap descendant leaves the set; the sequence refuses if `$HOME` resolves under a set member |
| safety | major | the forbidden-token gate's allow-list could not be both enforced and passed | applied | exact allow-list of command forms and redirect targets, one `systemctl reboot --force`, explicit refusals, self-test on the real scripts (X6) |
| safety | minor | governor pin checked in Phase A, minutes before a unit issues the kexec | applied | governor re-read just before `kexec issuing`; `abort reason=governor` |
| safety | minor | post-issue `kexec -u` and reboot could interrupt a slow kexec shutdown | applied | sequence and fallback check `systemctl is-system-running` and only mark and exit on `stopping`; non-zero rc is the only "rejected" case (R72) |
| safety | minor | console level 7 plus `initcall_debug` lengthens the kexec shutdown and makes J2 unlike B2 | applied in part; the default-console-level option rejected | slow shutdown with growing COM3 is not a hang; J1 go rule bounds the cost; matched arms; J2b repeats B2 without the trace. Default console level rejected because the per-device line would not reach COM3 (R73) (X4) |
| safety | minor | J3 and failed paths leave sequence files and tarballs on the rootfs | applied | no tarballs at all; three named files under a dated rule-5 exception, removed on every return path and by the next command after a failure (X7) |
| safety | minor | Q16 reads function bodies, which may exceed "documentation pages only" | applied | Q16 limited to documentation, mailing-list and patch pages; per-file source views are owner decision D33 |
| safety | minor | the J0 commit names drivers before D29, and the repo is public | applied in part; "precondition of the commit" rejected | drivers resolved at run time from class codes and J1's private set file, so the commit names none; D29 gates the **push**, not a local commit, because a local commit publishes nothing and PO-A needs commits before builds (X9) |
| power | blocker | J2 and J4 differed in dwell and issuing context, confounding the removal with fading GPU residue | applied | J2 is a null-set detached arm with the same fixed slots, start delay, unit, snapshots and trace; each slot padded to `WQ_SLOT_S` (adapted from "sleeps WQ_STEP_S", which would not equalise slots whose actions differ in length) |
| power | blocker | a clean c2 can hide a moved writer; nothing watches the rest of sysram; Q could become final on a blind B2 rerun | applied in part; "hold in the B2 rerun" rejected | large timed `memcanary hold` added to `s1-j1` and required (J6r) for Q-final; placement stated as HYPOTHESIS. Adding it to the B2 rerun was rejected: it would change `s1-h1`'s script (a revision-3 Never item) and the rerun would no longer be judged by §6.7 unchanged (X8) |
| power | major | outcome tables had gaps (mixed J2 checks, F35 with F34, J3 not met, J6 none or static, K through read instability) | applied | F32a and F32b rows with J6 first; U extended; K split into K-r and K-w with different revision-4 consequences |
| power | major | a clean J2 stopped the ladder uninformatively; false-Q risk unstated | applied (adapted) | J2b in J4's slot after F33, run as `jrun … b2repeat` rather than raw `cmd_run` (X3); F45 and F46; the false-Q estimate stated in §15.4.6 |
| power | major | F34 misclassified a fast live writer as read instability | applied | third read; `osc` (A-B-A) against `prog` (A-B-B, A-B-C) and `stable`; F34 = `osc` above 0 and `flip2` dominant and `prog` 0; `flip2_same` and `flip2_var` |
| power | major | classes could not separate rings, counters and 32-bit field writes; signatures used as negative evidence | applied | `hi_pat`, `lo_pat`, `small32`, stride histogram, signatures at every byte offset, stated positive-only; words line split to stay under 255 B |
| power | major | pre-kexec page flags cannot map to post-kexec DMA targets; the "supports H1" row had no weight; the final snapshot perturbs the jump boot | applied | final snapshot dropped from both arms; the H1-support row removed; R45 restated as a VERIFIED limit; snapshots kept as a record only |
| power | major | J4 tests the lowest-prior hypothesis, and F35's meaning was not split; C24's inference was a non sequitur | applied (with a stated limit) | Q-p and Q-x split pre-registered, with the limit that `pci final` precedes the shutdown (X10); §15.3 states J4 gives no evidence on H1, H2, H3, H5; C24 and §15.10 item 5 corrected; J5 unrun for budget and fixed-setting reasons; D24 asks the owner whether J4 runs today |
| power | minor | no row compared the change rate across B2-style allocation fill | applied | fill-rate row (label c against b, factor pre-registered in `J-prereg.log`); H4s added (R76) |
| power | minor | "network RX appends contradict K-d" treated as settled | applied | labelled HYPOTHESIS; status-bit set and clear in DMA rings added as a K-d-compatible H4 mechanism |
| feasibility | blocker | SSID added to `redact` but not `ident_hits`, so an SSID-only file is kept raw; optional on trace rungs; no length guard; `awk -v` backslash issue | applied | SSID class in `ident_hits` and `redact`, via `ENVIRON`, refused under 3 bytes, mandatory for every J rung, self-tests for SSID-only, short and backslash cases |
| feasibility | major | `tar czf` stores the board user name in binary records | applied | no tar: raw slices plus a text header in tmpfs, fetched, sha256-verified, header privacy-scanned, removed |
| feasibility | major | bitmaps sent as raw binary on COM3; host mode has no export path | applied | export only through `xport` in a new `@BOARD@@J1@` block after `FAIL_STATE`, outside the `MODE != host` guard; parse-s1 self-test for `com3_last_kind` |
| feasibility | major | J parses print `step=B2`, `b2=pass`; `image_step` would write a `B2-aN` directory | applied | `run --diag j2|j2b|j4` with `verdict=diagnostic …`; `STEP` set after `resolve_kimg`; self-tests for no `B*` directory and no `b2=pass` |
| feasibility | major | `PO_A_PATHS` misses the edited templates; gate 8.2 regeneration would overwrite `s1-h1.params` | applied | five paths added to `PO_A_PATHS`; gate 8.2 only with a scratch `--out` or a worktree; Q17 params-hash check before J2, J2b, J4 and the B2 rerun |
| feasibility | major | exit-5 and fallback returns would file the previous L4T console as a black box and parse it | applied | black-box copy and parser skipped on those returns; optional `-l4t-console-ramoops.log`, SSID-scanned, never `--blackbox` |
| feasibility | major | `declare -f` of `BOARD_FUNCS` would emit quiesce and pin functions; allow-list incomplete; `systemd-run` lines ungated | applied | `WQ_FUNCS` subset; exact redirect targets and commands; `remove`, `rescan`, `reset`, `driver_override`, `new_id`, `power/control` refused; both `systemd-run` lines gated (X6) |
| feasibility | major | advice reads only `run com3_bytes_before_kexec=`; F25a could advise a cut before the fallback | applied | `jrun` writes that key, `j3` writes its own parsed key; the hold on every class; self-test of markers plus 400 s silence (X5) |
| feasibility | major | the draft already contained D29-reserved wording and mask widths; §15.8 and §15.9 disagreed | applied in part; generic 32-bit reasoning kept | [D29] marks and a neutral substitution table; run-read mask widths removed from E9 and added to the Never list; §15.8 and §15.9 reconciled on the f33611d precedent. C20's and the pivot's reasoning about any 32-bit master is design reasoning, not a run fact, so it stays |
| feasibility | minor | sequence files and the fallback's `dmesg` tail persist on the rootfs against rule 5 | applied | dated rule-5 exception for three named files; removal on every return path (X7) |
| feasibility | minor | "no MAC read" rule too narrow; hyphen MAC form not redacted | applied | census restricted to `driver`, `idVendor`, `idProduct`, `bInterfaceClass`; `address`, `serial`, `lsusb`, `hciconfig` refused; hyphen-form MAC self-test |
| feasibility | minor | adding `memcanary-w` to the global TCG tool list changes every T variant | applied | added only for `-Variant j1`; gate 8.2 extended to T1-T3 `files.list` and params |
| feasibility | minor | the determinism gate after an edit on main could overwrite the pinned binary and force a revert | applied | gate 8.1 in a scratch worktree on an uncommitted copy; B versus B' decided before any commit; pinned binary copied outside the tree |
| feasibility | minor | trace perturbation of J2 not named; F33 reading with the trace on unspecified | applied in part; the "trace in J1 only" option rejected | risk named in §15.7.4; F33 sends J2b without the trace; J1 go rule. J1-only rejected because a reboot is not a kexec shutdown (X4) |
| feasibility | minor | J records cannot show which harness ran | applied | `s1-board.sh` sha256, `git rev-parse HEAD`, clean-tree check of harness, `kpf-decode.py`, `parse-s1.py`; refuse dirty |
| feasibility | minor | no black-box estimate for `s1-j1` | applied | gate B8.6: worst-case text under the 60,000 B threshold |
| feasibility | minor | `kpf-decode.py` declared MIT against Apache-2.0 siblings; D28 could export QNX structure content | applied, then corrected at implementation (the siblings are MIT) | MIT SPDX header, matching the siblings; D28 and J7d exclude `pte`, `kva` and any QNX-structure class; J6 stays counts |
| feasibility | minor | the raw COM3 capture path is unchecked and never redacted | applied | gate A refuses a capture outside the git-ignored record directory; raw capture never copied, quoted or scanned by hand |

---

### 15.12 J6 implementation readings, fixed before J6's pre-registration (2026-09-14)

Phase 3b. Written after the J6 image `s1-j1` was built and three reviews (safety, fidelity, regression) read the watcher, its parser and the harness against §15.4.8, §15.5 B and §15.6. Nothing here has run on the board. Each item is HYPOTHESIS unless marked. Each is fixed in committed code before the first `jrun s1-j1` appends J6's stage to `J-prereg.log`, so no J6 result exists that a reading could be fitted to. D27 left the hold margin and these readings to the implementation.

**A. Amendments to the watcher.** `PIN_MEMCANARY` does not move; `PIN_MEMCANARY_W` does, and T-J1 reruns.
1. **Reverts.** §15.4.8's three-read rule counted a one-off misread of a good word as a writer. A bad A, then B and C back at the word's last read, gave `prog`, a change, a heal and page bits. A misread at BASE or FINL had no re-read at all. Now a read that differs is read twice more at BASE, in every snapshot and at FINL. When B and C agree on the last read (at BASE: on any value other than A), A did not hold. It counts `revert`, and also `revert_flip2` when A differs from them in one or two bits. Nothing else is counted or marked, and the last read is not updated. A misread repeated in B or C still reads as `osc` or `prog`. **Not shown:** that a restore faster than two reads is never a revert; R71's caveat applies to `revert` as it does to `osc`.
2. **Whole pages.** "Whole pages healed together" is now `whole_heal`: a page whose every word healed in one snapshot counts once. The parser's earlier test, `healed` at least 512 per healed page, counted heal events, so one toggling word could meet it. A restore that straddles a scan is missed; the row is positive-only.
3. **A new line** follows `watch=time`: `S1 CANARY <n> watch=reread label=<l> revert=<n> revert_flip2=<n> whole_heal=<n>`. `reads=` gains `revert`: `prog` over `osc` over `revert` over `stable`. The export file is unchanged: 1,632 B, and its tail stays four counts.
4. **The dump file** must be exactly `/dev/shmem/j1<label>.bin` for the watch's own `-l`. A watch cannot create the hold's trigger or overwrite the hold's output or another label's file.
5. **Class precedence.** The 32-bit all-ones value is `small32` ahead of `pte` and the pointer rules, which would read it as a descriptor or a DRAM pointer.

**B. Readings the design text left open, as implemented.**
1. A-A-C counts as `prog`. Every change event is exactly one of `osc`, `prog` and `stable`, and the parser refuses a console whose three do not sum to `changed_words`.
2. `writer=ongoing` when FINL still differed after its re-reads, or when the last change fell in the last quarter of the snapshots; otherwise `stopped`. A change seen only at FINL is not in `changed_words` and sets no page bit.
3. `content=` lists every class other than `other` that holds at least a quarter of FINL's bad words, most first. It reads `unclassified` when none does and `none` when there is no bad word.
4. The export header also carries the requested count, the deadline and the stop reason.
5. **F34:** `prog` 0; `osc` or `revert` above 0; `flip2` (same and var together) dominant in the bad set when the set has words; and more than half the reverts `revert_flip2` when there are any. "Dominant" is read as elsewhere in the table, the largest class with ties included, not a strict majority.
6. **F34 and the live-writer row are exclusive.** F34 needs `prog` 0, and it takes precedence over "changed words with stable re-reads": an `osc` keeps a marginal read as the last read, and the next snapshot then re-reads the stored word as a stable change.
7. **`writer-none`** also needs no revert on c2's watches ("c2 clean at every scan").
8. **Ring-record's stride arm:** at least 8 bad words, with the two largest of the eight bins above half of them.
9. **Fill-rate:** `differs` when one rate exceeds the factor times the other and the larger has at least 8 change events. Below that floor the result is `below-floor`, which fires no row. A zero baseline is otherwise compared as it is.

**C. The hold's margin (D27).** `J1_HOLD_MIB` is windows 1 and 2's sysram, less the three canaries, less a 256 MiB margin. The margin's rows are design estimates, recorded in `make-s1-images.sh`: the IFS, procnto and the early processes, the script's tools, the two 16 MiB copies each of watches c and d, the hold's page tables, `/dev/shmem`, and slack. A short margin shows as the hold's `map=fail` (F28), or as `watch=fail reason=nomem` on watch c or d, which allocate after the fill (F40). Either is diagnostic incomplete for an image reason. Such a run reached `procnto up`, so under §15.6 it counts as J6's kexec run, not a harness-reason retry. A rerun at a smaller hold is a new image and a new stage, and needs the owner (D27).

**D. The harness.**
1. **J6's stage never re-emits J2's `prereg <file> sha256=` lines,** so the s1-h1 checks keep reading J2's registration and its dated amendments. The stage records its own hashes of the three tracked files and of `WQ_FUNCS`. When the harness differs from J2's registration, the stage opens with an amendment line in the D34 and J3 form (`by=`, `commit=`, `reason=`, old and new hashes), and the owner names it with `S1_J6_AMEND_BY`. A changed `WQ_FUNCS` also needs `S1_J6_WQ_CHANGED=yes`.
2. **An `s1-j1` run is checked against its own arm's stage,** the newest block that ends in its arm line, never the file's last lines. A stage that no longer matches the harness or the image may be superseded under `S1_J6_AMEND_BY`, and only while the arm has no board log.
3. **The stage is appended after gate A,** so a refused capture registers nothing.
4. **J6's precondition** also needs T-J1 met with the image's `memcanary-w` pin. When J2's row holds F39, it also needs the owner's `D34_J6=yes`, because D34 waived that stop for J3 and J4 only. The precondition line prints the kexec runs so far. §15.6's budget stays the owner's count, since harness-reason retries do not count.

**E. Generator and T-J1.** The profile check refuses any hold in `s1-j1` other than its own and the template's single B4 line. The black-box estimate counts nine lines a watch. T-J1's host script needs no FAIL form of either self-test line. The parser needs the watcher's PASS followed by memcanary's own PASS with the larger count, because a failure in memcanary's own checks inside `memcanary-w` changes only the second line.

**What this does not show:** that the readings are right. They are fixed before any J6 result, which is all a pre-registration can do. Whether `revert` separates read instability from a fast restoring writer is R71's open question, and J7a stays the decisive H1-versus-H2 arm.

### 15.13 J7a: the UEFI-entry arm (D30, 2026-09-14)

Phase 3b. **Proposed as §15.13 of `results/orin-native-port/20260909T1100Z/s1-design.md`.** It is the "short J7a design" D30 asks for (§15.6.1, last bullet). Nothing in it has been built or run. It creates no code, configuration or image, and no board step runs before the owner approves it (D35).

**How it was written.** It is a synthesis of four desk analyses, and §15.13.18 records where they disagreed and what was chosen:
- the UEFI path (M5's option A carrying `s1-j1`);
- firmware memory in window 2;
- harness and records;
- rules and classification.

The draft was then reviewed through three lenses (safety, power of the reading, feasibility). §15.13.20 records every required change and what happened to it.

**Hard rules kept while writing.** No board contact, no download, no repository edit, no QNX-shipped binary read.

**Evidence classes** are as in §15's header, including "VERIFIED (private record)" and "reported VERIFIED". "VERIFIED (source)" means this design, an analysis or a review read our own committed source. "Class only" means a private value was compared and only the comparison's outcome is written here.

**Number-free, as §15.** This text contains:
- no count, offset, page-class figure, register value, descriptor address or type seen in a run;
- no hash of a private record or of a build output;
- no uptime, boot id or duration from a run;
- no file size or free-space figure from a record or a build;
- no MAC, drive identifier, IP, SSID, user name or hostname.

Addresses are the design constants already public in §3.3 and m5-design §3.3. Durations, margins and thresholds are design constants. Run counts and the clean-run probabilities follow §15.4.6's precedent.

---

#### 15.13.1 Purpose, the owner's decision, the question

**Decision (owner, 2026-09-14, D30).** After J6c, the owner chose J7a. The design has to settle four things: the rule-5 exceptions (the ESP write), the TX refit, firmware use of window 2 (§3.2, never checked), and how the result is read under §15.6.

**The one question J7a answers.** Is c2's corruption caused by something Linux leaves behind at kexec, or by something anchored at c2's address (window 2's base, physical `0x1_0000_0000`)? Anchored means firmware, a coprocessor, the secure world, fixed-address hardware, or QNX itself.

**What a UEFI entry separates, and what it does not.** On a DC cold boot entered through the firmware's UEFI Shell, no Linux runs in the power cycle whose memory startup fills and watches:
- DRAM is repowered, and stays unpowered for a design wait long enough to argue decay (§15.13.6, R95);
- every device Linux drove is reset;
- nothing is left by Linux's shutdown, its SMMU handling, its kexec tree or its page layout.

The shim, startup, `memcanary-w`, the host script and the hold then run byte for byte as in J6c.

J7a therefore separates **"the writer needs the kexec path in this power cycle"** from **"it does not"**. It does not separate Linux residue from anchoring in general: a writer anchored at window 2's base whose activity depends on the L4T boot option, on PSCI history or on how long the board has run would also disappear under UEFI entry (§15.13.2 confounds, §15.13.17). A bad result says anchored-or-UEFI-reachable; its profile against J6c (§15.13.10.3) says which is more likely.

**§15.6's classes it decides** (amended in §15.13.10):
- **E:** J4 is F36, and J7a is clean;
- **K-w:** J4 is F36, a J6c run shows a live writer, and J7a is bad.

Both preconditions are already met (VERIFIED, private record): J4 is F36, and J6c's parser row carries the live-writer label.

**Scope.**
- **In:** one image under one new entry path; the firmware-memory check that must pass before any `go`; a read-only report of the firmware tree's reserved-memory nodes over the canaries; the loader rebuild; the harness, parser and privacy changes; the board procedure and its rules; the pre-registered reading; one desk read of WDT0's control register class (Q20) before D35.
- **Out:**
  - any change to startup, window 2, the canaries, `memcanary` or `memcanary-w`, or `s1-j1` (unless Q20's branch (b) and D47 say otherwise);
  - UEFI entry for S1-F itself (D6 is unchanged; freeze item 3 is not decided here);
  - option A' or B;
  - any SMMU, GPU or MMIO read by the loader;
  - any value export (D28);
  - any timing;
  - revision 4.

---

#### 15.13.2 What J7a tests, and what it does not

**What it tests.** The same watcher image, entered once through the firmware instead of Linux's kexec.
- **A bad c2** is positive evidence that the writer does not need Linux in the power cycle.
- **A clean c2** is negative evidence, and weak alone. c2 was bad in all four kexec runs (B2, J2, J4, J6c). Under a uniform prior over four exchangeable bad runs, **the chance of one clean run if entry has no effect** is about one in six, and of two clean runs about one in twenty. These are not false-E rates, and the runs are not strictly exchangeable: B2, J2 and J4 used `s1-h1`, J6c used `s1-j1`. Hence §15.13.10's asymmetric rule.

| Hypothesis (§15.3) | Under UEFI entry | What J7a can say |
|---|---|---|
| H1 GPU residue | the GPU is repowered and nvgpu never ran | bad excludes it; clean fits it, along with every other kexec-path state |
| H2 firmware, coprocessor or secure-world user of the address | still present: BPMP, SPE and RCE firmware start on both paths. E13's `camdbg_carveout`, a disabled node, is the only node in Linux's live tree whose allocation range starts at window 2's base | bad fits it; UM9 reports whether the firmware tree QNX receives declares a node over c2 |
| H3 read instability | still present | the J6 re-read rules re-test it (K-r(u)) |
| H4, H4s removable masters | already excluded by J4 as quiesced; under UEFI, not driven by Linux, and for J7a the Ethernet cable and board USB devices are removed (D46) | — |
| H5 QNX-side, anchored at window 2's `ram` entry | still present: startup, procnto and the host script are identical | bad fits it; J7e (revision 4) separates it from H2 |

**"Only the entry path changed" is false in detail.** These differ between J6c and J7a. They are confounds, recorded and not controlled:
- the tree at `x0` (the firmware's tree as published at Shell time, not Linux's kexec copy of the tree L4TLauncher's boot used);
- **the boot option:** kexec runs follow an L4TLauncher boot, which may make the firmware apply tree fixups or carve-outs and set coprocessor state; J7a boots the UEFI Shell;
- our loader and its cache and MMU sequence, instead of kexec's relocator;
- **PSCI history:** under kexec, Linux took the secondaries through `CPU_OFF` before the jump, and startup's `CPU_ON` then reached cores with that secure-side history; under UEFI, `CPU_ON` reaches never-started cores. J6c's corruption falls in the window after the fill that contains `init_smp` (VERIFIED (source): `main.c` calls `t234_init_raminfo`, then `hypervisor_init`, then `init_smp`);
- GIC, timer and WDT0 state as the firmware leaves them (WDT0's inherited control register differs, class only, §15.13.4);
- CPU frequency and EMC state set by the firmware, not the harness's pinned governor;
- **time since cold power-on and thermal state at the fill:** hours of L4T uptime under kexec, minutes under UEFI;
- which UEFI drivers ran (NVMe, SD, xHCI, possibly the network function) and whether they stopped DMA at `ExitBootServices` (R82);
- SMMU state as the firmware leaves it;
- the peripheral set (D46: the Ethernet cable and board USB devices removed for J7a; the M.2 wireless card stays, R96);
- DRAM history: a cold power cycle after an unpowered design wait, not a running L4T. It matters only if startup's fill did not land on some pages (§15.13.10.3, R95).

**What a J7a result does not show,** whatever it is (the full list is §15.13.17):
- the writer's identity;
- which kexec-path state causes E, or that E excludes an anchored writer that the kexec path switches on;
- DMA quiescence under UEFI outside the canaries and the hold's coverage;
- that UEFI entry is valid for S1-F;
- repeatability beyond the runs made.

---

#### 15.13.3 The firmware-memory check that must pass first

**The causal window.** Startup fills c1-c3 after `ExitBootServices`, the loader and the shim, and before procnto (VERIFIED (source): `startup/t234-orin-nano/main.c`, `t234_init_raminfo` before `hypervisor_init`; the fill loop in `init_raminfo.c`). The fill is write-only with the MMU off and has no read-back (VERIFIED (source): `init_raminfo.c`, the fill loop). J6c's private note puts the kexec-entry corruption in the same window: after the fill and before QNX's first check, then static. So:

| Stage | Can it write c2? | Does it matter to the canary result? |
|---|---|---|
| Firmware start, menus, Shell, `memmap` | yes, any firmware allocation | **No,** if the fill lands: the fill overwrites it |
| Loader up to `ExitBootServices` (image, pools, the target copy) | the firmware places them | **No,** for the same reason |
| After the exit: the loader's trampoline, then the shim | no RAM store in window 2 in either (VERIFIED (source): `uefi/m5load-head.S`, `shim/t234-shim.S`) | would matter, but none exists |
| Startup fill, then procnto and the host script | **any live owner:** firmware runtime code (only if called; nothing calls it, R83), the secure world, coprocessors, a firmware-started device still doing DMA, QNX | **Yes.** This is J7a's window |

So the check has one job: make sure no firmware-owned memory with a **live owner after `ExitBootServices`** lies over a canary or anywhere in window 2, and that the canaries stay free until the exit.

**The gap, as built.** M5's loader prints and judges only descriptors that overlap window 1, the black-box zone or the tree. It never looks at window 2, c2 or c3 (VERIFIED (source): `uefi/m5load.c`, the map step). That is §3.2's "never checked", confirmed in code.

**Indirect evidence so far, for the L4T boot option only.**
- L4T's Linux takes its RAM from the UEFI memory map (reported VERIFIED, `harvest-orin.md`).
- Its `/proc/iomem` has shown window 2 as plain System RAM on every boot compared, with no reservation but Linux's own image (VERIFIED (private record), `p0-iomemhi-*`, `diag/d0-note.log`; plan 11c).
- How arm64 Linux turns EFI types into iomem entries, and whether a Shell launch sees the same runtime and reserved layout, stay HYPOTHESIS (R80).

##### Treatment by memory type (the map at `check`, and the map passed to `ExitBootServices`)

`RT` means the `EFI_MEMORY_RUNTIME` attribute.

| Type over the range | Live owner after the exit | Over c1, c2 or c3 | Elsewhere in window 2 |
|---|---|---|---|
| ConventionalMemory | none | allowed, and pre-claimed by the loader (UM4) | allowed |
| LoaderData covering a canary whose UM4 claim returned success | ours; no store after the exit | **required form after UM4** | — |
| Other LoaderCode or LoaderData (the Shell's file buffer, our image, pools) | none; nothing runs from it after the shim | refused through the pre-claim: F54 if the loader's own `self` range overlaps, otherwise F51 | allowed; `M5L self w2=yes` is printed and recorded |
| BootServicesCode or BootServicesData | free by specification (VENDOR_CLAIM); **residual:** a firmware driver's DMA buffer if its device is not stopped (R82) | refused, through the pre-claim (F51) | allowed and printed; a J7a F49 cites them (§15.13.10.5) |
| RuntimeServices*, any descriptor with RT, Reserved, Unusable, ACPIMemoryNVS, MemoryMappedIO*, PalCode, PersistentMemory, UnacceptedMemory, unknown | the firmware, the secure world or hardware | **refused** (F50) | **refused** (F50) |
| ACPIReclaimMemory | none, but unexpected in DT mode | refused (F50) | refused (F50), as window 1's rule |
| Gap (no descriptor) | a carve-out the firmware withholds | refused (F50) | refused (F50) |

**Why "claim success" and not "exactly our claim".** The firmware merges adjacent descriptors of the same type, so the map cannot show that a LoaderData descriptor is exactly one claim. It does not need to: `AllocateAddress` succeeds only when every page was ConventionalMemory (R81), and pages already allocated cannot be allocated again. A canary whose claim returned success and whose covering descriptors are LoaderData is therefore ours until the exit.

##### UM1-UM10: loader requirements for J7a

The `UM` prefix is new. `L` would collide with the parser's L0/L1/L7 rules, and `W` with §14.5's fixed setting. Everything below sits behind the compile-time switch `M5L_J7A` (§15.13.4). `m5load-head.S` is not touched, so the trampoline, its tokens and gate item 9 are unchanged.

- **UM1. Constants.** Window 2 is `[0x1_0000_0000, 0x1_8A00_0000)`. c1, c2 and c3 are at `0xBD000000`, `0x1_0000_0000` and `0x1_8900_0000`, 16 MiB each (§3.3). A new **gate item 11** parses them from the loader source and requires equality with `board/t234_startup.h`'s `T234_RAM2_*` and `T234_CANARY*` defines.
- **UM2. Identity lines.** Step 1 prints, directly after the unchanged `M5L start …` line, a separate line `M5L variant=j7a`, then `M5L self w2=yes|no canary=none|c1|c2|c3` (from the `LoadedImage` range the start line already prints). The start line's grammar is identical in both builds. `self w2=yes` is informational: the loader's own pages in window 2 hold nothing that runs after the branch, and startup's claim reuses them. `self canary≠none` names the case F54 classifies.
- **UM3. The tree.** Step 2 adds `crc32=` to `M5L fdt addr=… size=…`, computed with `CalculateCrc32` over `totalsize`. This is item 5's tree stamp under UEFI entry. It refuses `M5L REFUSE fdt reason=w2` if `[fdt, fdt+totalsize)` overlaps window 2, and `reason=canary` if it overlaps c1.
  - **Why window 2 as a whole, not only the canaries.** Startup only calls `avoid_ram` on the tree (VERIFIED (source): `main.c`), and an `avoid_ram` range still reaches sysram (C15). A firmware tree inside window 2 would be handed to procnto, and `s1-j1`'s hold covers most of window 2.
  - VERIFIED (private record, once): M5's tree lay outside both windows.
- **UM4. Pre-claim of the canaries.** After step 5 reserves the target:
  - call `AllocatePages(AllocateAddress, EfiLoaderData, base, 0x1000 pages)` for each of c1, c2 and c3, in order;
  - on success, print `M5L canary cN preclaim=ok`;
  - on failure, print the status and every descriptor overlapping that canary, then `M5L REFUSE canary cN status=…`.

  What it gives (VENDOR_CLAIM, AllocateAddress semantics, R81): a claim succeeds only when every page is ConventionalMemory, and no UEFI allocation can land on a canary between the claim and the exit. A successful `preclaim=ok` is therefore itself the type record. It writes no page (HYPOTHESIS, Q19), and startup's fill follows anyway. It changes the firmware's volatile map only; nothing persists (D37). The claims are released under UM10.
- **UM5. Window-2 rule, at step 7.**
  - Print every descriptor overlapping window 2 in the existing `M5L map type=… start=… pages=… attr=…` form.
  - Sweep `[W2_START, W2_END)` with window 1's allowed types (Conventional, LoaderCode, LoaderData, BootServicesCode, BootServicesData). Any RT attribute, gap or other type refuses: `M5L REFUSE w2 reason=gap|type|rt at=…`.
  - **Canary rule:** each canary's claim returned success, and it is covered only by LoaderData. Otherwise `M5L REFUSE canary cN reason=type at=…`.
  - Print `M5L W2 PASS` before `M5L CHECK PASS`, so `check` and `go` still print the same prelude (m5-design §13 E).
- **UM6. Re-check on the exact map passed to `ExitBootServices`.** In step 10, between each `GetMemoryMap` and its `ExitBootServices`, run UM5's sweep and canary rule as a pure function over that buffer, with no boot-services call and no print. This keeps m5-design §3.3's "nothing between them".
  - **Retry discipline (UEFI's rule after a failed exit).** Under the switch, the final-map buffer is allocated once, before the first try, with the existing slack. After the first `ExitBootServices` call has returned, the loader calls no boot service other than `GetMemoryMap` and `ExitBootServices`, and no `ConOut` output. A `GetMemoryMap` that no longer fits the buffer on a later try ends in the MODE_EBS_FAIL path. (M5's switch-off loop calls `AllocatePool` on a retry; recorded in §15.13.19, not changed, because it would change the switch-off object.)
  - **Failure on the first try** (before any `ExitBootServices` call): skip the exit, release everything under UM10, print `M5L REFUSE w2-final`, return to the Shell. That is before the exit, so M5 rule 2 holds. Not counted (F53).
  - **Failure on a later try** (after a failed `ExitBootServices`): no return to the Shell, no free, no print. The loader calls `m5_tramp(…, MODE_EBS_FAIL)`, exactly as M5's loop does after four failed tries: DAIF masked, `M5L-EBS FAIL` on the TCU, PSCI reset (M5 rule 3). COM3 cannot tell this cause from four refused exits. Counted, class S (F55).
  - A printed `M5L-EBS ok` then certifies the rule on the final map.
  - There is no post-exit map print: the trampoline sequence is gate item 9, and whether the TCU is reachable with the MMU still on after the exit is UNKNOWN.
- **UM7. Loader wait bounds.** The Shell loads a file many times M5's size from SD before the loader prints anything, and the loader then CRCs, copies and re-CRCs the blob silently (VERIFIED (source): `m5load.c` steps 3-6). §15.13.6.1's `LOADER_EXPECT_S`, `LOADER_CUT_S` and `PROMPT_AFTER_S` apply identically to `check` and `go` (R78). This is a procedure bound, not a code change.
- **UM8. With the switch off, nothing changes.** The switch-off object of the edited file equals the switch-off object of HEAD's unedited file, byte for byte (§15.13.4 D0).
- **UM9. Reserved-memory report (informational, never a refusal).** At `check` and at `go`, after UM3 and before step 5, walk `/reserved-memory` in the `x0` tree read-only, with the tree parser `fdt_pick_console` already uses. For every child whose `reg`, `alloc-ranges` or `iommu-addresses` overlaps window 2, c1, c2 or c3, print one class-only line: `M5L resmem name=<node> status=okay|disabled|absent map=no-map|reusable|plain prop=reg|alloc-ranges|iommu-addresses over=c1|c2|c3|w2 base=yes|no` (`base=yes` when the range starts at window 2's base). No address or size is printed. A property whose length does not divide by its cells prints `form=unparsed`. Then `M5L resmem done`. The walk uses stack memory only, no stored pointer (gate item 6), no MMIO and no write. It bears on the reading (§15.13.10.3), never on `go`.
- **UM10. Release on every return to the Shell.** Every path that returns to the Shell releases the canary claims, the target and every pool it holds: all `check` exits, every refusal in `go` before the first `ExitBootServices` call (UM3-UM6, `el`), and the first-try `w2-final` refusal. The go path also frees step 7's pool before step 10 allocates the final-map buffer. The claims are held only on the path that reaches `ExitBootServices`. A `check` after any such return in the same Shell visit therefore reaches `preclaim=ok` again (T0f′, T0l).

##### From the UEFI Shell: optional, read-only, record only (D43)

- **`memmap`,** typed once before `M5LOAD.EFI check`.
  - It shows the firmware's full map at Shell time, including the runtime and reserved layout. That cross-checks R80 and informs revision 4.
  - It is **not a gate:** it predates the loader's image load, pools and claims.
  - Its paging behaviour is R90. If it pauses for a key, the operator arms F12 and ends it with `q`, and records the deviation.
  - It lists descriptors, not memory content, so the no-dump rule does not bear on it. The block is extracted into a private record and judged by nothing.
- **Never, in J7a:**
  - `dmem`, `mm`, or any memory-content read or write;
  - `setvar`, or `dmpstore` with any option;
  - `bcfg`;
  - `connect` or `disconnect` beyond m5-design F6's use;
  - `drivers`, which is not typed (low value, more keystrokes);
  - **any output redirection (`>`, `>>`),** which writes a file on a mapped filesystem such as the ESP.

##### What neither check can see

- A secure-world, BPMP, EMC or other coprocessor user of memory the firmware reports as free. That is H2 proper, and J7a measures it. UM9 names any node the firmware tree declares over it; a user that no node declares stays invisible.
- Whether the firmware tree's `/reserved-memory` at Shell time matches Linux's live tree (R94). The tree itself never leaves the board: the firmware may patch board identifiers into it (HYPOTHESIS).
- A firmware device doing DMA outside its reported buffers after the exit (R82).

##### A contradiction recorded, not resolved here

m5-design §3.3 step 7 allows the tree anywhere in window 1 "because startup reserves it (board/main.c:247-248)". Current `main.c` calls only `avoid_ram` for the tree, and C15 says such a range reaches sysram. UM3 makes J7a independent of this for window 2.
- **Not read here:** whether anything reads the tree after procnto starts.
- **A pre-existing condition:** the same holds for kexec's tree in window 1 on every kexec rung.
- Listed for the orchestrator (§15.13.19).

---

#### 15.13.4 The image and the loader

##### The payload: `s1-j1`, unchanged (D36)

- The embedded kimg is J6c's `s1-j1.kimg`. Its sha256 must equal the `kimg_sha256` registered in J6c's `prereg j6 params` line. That was VERIFIED by the UEFI-path analysis against J6c's params and stage logs and the file on the PC.
- Nothing in the image, the startup line (`-b w2,canary`, `-Wkeep`), `memcanary-w`, the hold size or the fill-rate factor changes. **From the shim on, every byte is J6c's.** The one pre-registered exception is Q20's branch (b) below, which needs D47 and a new image.
- **Why `s1-j1` and not `s1-h1`:**
  - it is one variable against J6c, the only run with content classes, onset, heal and re-read counts, page bitmaps and the hold;
  - it can answer "bad, but a different profile" (§15.13.10.3), including the page-set item P7;
  - its hold watches most of sysram with no Linux in the power cycle.

  `s1-h1` is not supported in J7a. It would need its own parse mode and would lose every profile item.
- **Geometry.** VERIFIED (arithmetic on `s1-j1.shim.txt` and the file size): `text_offset` is `0x80000`; `image_size` is a page multiple, not below the file length, and ends inside window 1, below c1 and below the generator's geometry cap. So `blob-consts.py` and the window-1 rule accept it.

**What an image built for kexec meets under UEFI entry**

| Item | kexec (J6c) | UEFI (M5 R1, `-P1`) | For J7a | Class |
|---|---|---|---|---|
| EL at the shim | 2 | 2 | none | VERIFIED |
| `x0` | Linux's kexec tree | the firmware's DT table (DT mode) | startup took its CPU list from it in M5; RAM is stated, not read from the tree; UM9 reports its reserved-memory nodes over the canaries | VERIFIED (M5 T3) |
| Secondary CPUs | offlined by Linux; M2 brought all six up | never started (EBBR); M5 started none | **new:** `CPU_ON` of cores 1-3 from never-started state, their redistributors, INTID 28 on each | HYPOTHESIS (R84) |
| WDT0 | configured by systemd; does not fire after kexec | M5's R1 capture carries a `t234: WDT0 CR=` token that **differs from J6c's** (class only). `wdt.c` prints its "did not fire after the kexec hand-over" text whenever CR is non-zero, so that line is no evidence under UEFI entry (VERIFIED (source): `wdt.c`). `s1-j1` runs `-Wkeep`, which leaves WDT0 as inherited, and its `guard_s` and `return_bound_s` are far longer than M5's run | **Q20 is answered at the desk before D35,** with a pre-registered branch (below) | UNKNOWN until Q20 (R85) |
| DMA masters | Linux's shutdown, quiesce, SMMU handling | repowered, then UEFI drivers ran | J7a's premise (R87), plus a new confound (R82), reduced by D46 | HYPOTHESIS |
| TCU drain | after Linux | after the firmware | long `xport` exports under UEFI are new | short text VERIFIED; volume HYPOTHESIS (R86) |
| Text before the shim on COM3 | L4T's shutdown | firmware, menus, Shell, `M5L` lines | none of it carries a parser record prefix | VERIFIED (M5 R1 capture, count only) |

**Q20's pre-registered branch (desk only, before D35).** The two private CR values are read against the public T234 watchdog register description, and the result is recorded as a number-free class: enable bit equal or different between the two entries, and whether the UEFI value means counting toward a reset.
- **(a) Not counting toward a reset under UEFI entry:** R85 is answered at the desk; `s1-j1` runs unchanged.
- **(b) Counting toward a reset with a period (all stages) shorter than `guard_s`:** `s1-j1` cannot run unchanged. The owner chooses (D47) between a `-Wdisable` variant, which is a new image with its own T-J1 and pins and a recorded break of the one-variable premise, and not running J7a.
- **(c) The documentation does not decide it:** R85 stays UNKNOWN. The owner accepts the risk at D35, and §15.13.10.5's WDT rule applies: a WDT-type reset is F62, counted, and the unchanged image is not retried (D42).

##### Loader source change (D37)

**`orin-native/uefi/m5load.c` changes inside `#ifdef M5L_J7A`, implementing UM1-UM10,** plus **one new header, `orin-native/uefi/m5load-rules.h`,** included only under `M5L_J7A`. The header holds only pure rule functions (the window-2 sweep, the canary rule, the tree-overlap rule, the reserved-memory range test) that take the map or tree bytes and constants as arguments. It defines no static data, stores no pointer (gate item 6: the two link bases must give identical files) and allocates nothing (`m5load.lds` refuses `.bss`), so the same functions compile for the host in T0u.

Nothing else changes: no new MMIO, no GIC, timers, clocks or CPUs; no file or variable write; nothing printed between any `GetMemoryMap` and its `ExitBootServices`. M5's "The loader never" list holds word for word.

**T0-only switches.** `M5L_T0_FORCE=um6-first|um6-later` makes UM6's function fail on the first try, or makes the first `ExitBootServices` fail once (a stale key) and UM6 fail on the retry. It exists only for T0l. **Gate item 12** refuses a board build that defines `M5L_T0_FORCE` or whose object differs from the J7a T0 build in anything but the blob and constants (with item 8).

**Build scripts:**
- `build-m5-loader.sh`:
  - `M5L_J7A=1` adds `-DM5L_J7A` and passes `--variant j7a` to the gate.
  - `T0=1 T0_PAD_LIKE=<kimg>` pads the contract probe to the kimg's file length and copies the kimg's `image_size` into the probe header. It reads only header bytes our shim wrote, so the T0 build embeds no QNX byte and matches the board build in every size field.
  - `T0_FORCE=…` is accepted only with `T0=1`.
- `m5-gate.py` adds gate items 11 (UM1) and 12 (no force switch in a board build) and makes item 8 variant-aware: it compares only builds of the same variant, and the J7a board build against the J7a T0 build.
- `t0/run-t0.ps1` gains the cases below.

**Where it is built.** In a git worktree of the J7a commit, never in the main checkout. `build-m5-loader.sh` writes a fixed `out/` beside itself, and in main that would overwrite M5's gated `M5LOAD.EFI` and `gate.txt`.
- The kimg is read read-only by absolute path from the main checkout.
- The worktree and its git-ignored `out/` are kept until J7a's record is written.
- The ESP file keeps the name `M5LOAD.EFI` and is identified by sha256. `com3-term.ps1`'s go detector matches `M5LOAD.EFI go` or `M5LOAD go`, after stripping a device or path prefix (VERIFIED (source): `Test-GoLine`), so the terminal needs no change.

**Order, on the PC:**
1. **D0a, the reference commit, before any edit.** M5's staged loader in `orin-native/uefi/out/` was written before commit `600996f` changed `m5load.c` (VERIFIED: file time against commit time). That change alters code (the tree refusal tokens, VERIFIED (source): `git diff 25d40e7 600996f`), none of which M5's pass printed. In two scratch worktrees, build with no switch against `m1b-p1.kimg` at `25d40e7` and at `600996f`. Record which one reproduces the staged loader's sha256 (M5's stage listing and `out/gate.txt` item 10), and pin that commit's `m5load.c` as the reference.
   - Expected (HYPOTHESIS): `25d40e7` reproduces it, and `600996f` does not, for the known source reason.
   - **If neither reproduces it:** stop and investigate toolchain or source drift before anything else. Owner acceptance under D37 comes only after that investigation, never in place of it.
2. **D0b, the switch leak test.** In a scratch worktree at HEAD: build with no switch from HEAD's unedited `m5load.c`, then from the edited, uncommitted file. The two objects must be byte-identical. A mismatch means the switch leaks, and the edit is fixed. HEAD's unedited build differs from the staged loader only by what D0a explained.
3. **Commit** (PO-A form): the loader source and header, the gate, the build switches, the T0 cases, and the harness, parser and privacy changes of §15.13.7. Number-free message, no driver or identifier. Reviewed before the session (D44).
4. **T0 builds:** `M5L_J7A=1 T0=1 T0_PAD_LIKE=<main checkout>/orin-native/shim/out/s1/s1-j1.kimg ./orin-native/uefi/build-m5-loader.sh`, and the two `T0_FORCE` variants in separate scratch output directories.
5. **Board build:** `M5L_J7A=1 KIMG=<main checkout>/orin-native/shim/out/s1/s1-j1.kimg KIMG_SHA256=<J6c's registered kimg_sha256> ./orin-native/uefi/build-m5-loader.sh`. Gate items 1-12 pass; item 7 pins the blob.
6. **Determinism of the J7a build:** clean `out/`, rebuild, same sha256.
7. **Pins, recorded privately** in J7a's pre-registration stage (§15.13.8): loader, blob and `gate.txt` sha256, the D0a reference commit, commit, T0 record name. Nothing carrying QNX bytes is committed (`*.efi`, `out/`, `*.kimg` are ignored).

##### T0 (QEMU 11.1.0 with edk2, `acpi=off`, as M5)

| Case | Setup | Expected (pre-registered) |
|---|---|---|
| T0a | gate | items 1-12 pass on the J7a board and T0 builds; item 8 shows blob and constants only; item 12 refuses a force build presented as a board build |
| T0b | `-m 8G`, padded probe, `check` | every M5 token, plus `M5L variant=j7a` directly after the start line, `M5L self w2=… canary=none`, `M5L fdt … crc32=`, `M5L resmem done`, window-2 `M5L map` lines, three `preclaim=ok`, `M5L W2 PASS`, `M5L CHECK PASS`, Shell prompt |
| T0c | as T0b, `go` | `M5L-EBS ok`, `M5L-JUMP`, `PROBE EL=2 … PC=80080000`. This covers the large load, the claim and copy, and the cache loop over the full `image_size` |
| T0d | `-m 1536M` | any named refusal, then the Shell prompt, recorded as observed (c1's pre-claim or M5's `window reason=type` are both correct); never `M5L CHECK PASS` |
| T0e | as M5 | as M5. Its locate-by-bytes must still find exactly one match with the padding |
| T0f′ | as M5's T0f (`virtualization=off`, `go`), then `check` in the same Shell | `M5L REFUSE el=1`, Shell prompt; then `M5L CHECK PASS` with three `preclaim=ok` (UM10 after a go refusal) |
| T0h | `-m 3G` (RAM ends at window 2's base) | **any named refusal, then the Shell prompt, recorded as observed** (a large loader may be placed over the target or c1 first); never `M5L CHECK PASS` |
| T0i | `-m 4G` (RAM ends inside window 2) | as T0h |
| T0j | `-m 5280M` (RAM ends at window 2's end) | as T0h |
| T0k | the switch-off loader against M5's T0 build | M5's T0 tokens, unchanged (regression) |
| T0l | the `T0_FORCE` builds, `go` | `um6-first`: `M5L GO`, `M5L REFUSE w2-final`, Shell prompt, then `check` reaches three `preclaim=ok` and `M5L CHECK PASS`. `um6-later`: `M5L GO`, `M5L-EBS FAIL`, a reset, no Shell prompt |
| T0u | PC unit test of `m5load-rules.h`, compiled for the host, on synthetic maps and trees | tree in window 2 or over c1, RT attribute in window 2, gap, BootServicesData over a canary, a canary claim that failed, a final map that fails, a reserved-memory node over c2 at window 2's base, a malformed property (`form=unparsed`): each gives its named result; a clean map passes. If the header cannot be host-compiled without changing the switch-off object, T0u becomes a reviewed reading and is recorded |

**T0 cannot show:** cache coherency for this image (R33, board only); the Tegra firmware's map or tree; `CPU_ON` from firmware state; WDT0; long exports; the Shell's load time from SD. **No TCG run is added:** `s1-j1` is unchanged and T-J1 met, and the S1 TCG legs cannot enter through edk2 on the T234 board.

---

#### 15.13.5 Dated exceptions (2026-09-14, D35; J7a board sessions only)

Each lapses when that session's close step (§15.13.6, C) is recorded. None carries over to a kexec rung.

| # | Rule | Exception for J7a | Bounds |
|---|---|---|---|
| X1 | §2 rule 5, "kexec only"; D6 | Entry through the UEFI Shell (`Boot0007`) and our loader, on a DC cold boot with no Linux in that power cycle. **D6 is unchanged:** J7a is a diagnostic entry, not S1-F's entry path, and §3.2's "deferred to the freeze" row stands | No `jrun`, quiesce, `kexec -l`, detached sequence or kpageflags snapshot on the L4T boot powered off before a run |
| X2 | Rule 5, "no write to the ESP" | **One file,** `\M5LOAD.EFI`, in the root of the SD card's ESP (L4T's `/boot/efi`). Staged by `b_esp_stage` (§15.13.7) and removed at every session's close (M5 D10). Never under `EFI/BOOT` or `EFI/UpdateCapsule`, never a `.nsh`, never on the NVMe ESP. The rootfs route was weighed and not chosen (§15.13.18 row 20, D45) | The ESP listing after every return is S0 plus that file at its staged hash; after close, S0. A short ESP refuses before any write (F65) |
| X3 | Rule 5, "no write to a UEFI variable" | **No exception: we write none.** The firmware's own per-boot writes are judged against the control delta (m5-design §5.2 item 4; only `MTC` changed in M5) | `efibootmgr -v` hash equal apart from `BootCurrent` |
| X4 | Rule 5, "nothing persistent on L4T apart from staged kimgs" | `~/M5LOAD.EFI` as a staging copy, removed right after the ESP copy is verified. M5's kept `~/m5-backup` is reused only if its hashes equal the live `extlinux.conf` and `BOOTAA64.efi`; otherwise `~/j7a-backup/` is written, hashed and kept like M5's | Every write and removal recorded |
| X5 | §8 item 10, "no TX" | Adapter TX on J14 pin 3 for the J7a session only. The owner fits it **with DC power removed** during the control cold boot (§15.13.6, J7a-ctl), after confirming the adapter's 3.3 V jumper. **No loopback test:** `com3-term.ps1 -SelfTest` plus the control boot replace m5-design §8 item 4, as in M5 §14.3 (D40). It is removed at close with the terminal still running | **No kexec rung runs while it is fitted.** The next kexec rung's precondition records the owner's statement that pin 3 is unwired |
| X6 | §2 rule 6a; §15.6's "any power cut" immediate stop | **A planned DC cut** before each cold boot, only after `j7a`'s poweroff watch prints READY. READY needs the kernel's power-down line with no firmware output after it, then 30 s of COM3 silence. Before a counted `go`, power stays off at least `DRAM_OFF_S` (§15.13.6.1). A planned cut is not a §15.6 power cut | A cut before READY is a recorded deviation (as m5-design §14.3), not a planned cut and not a run event. Every other cut is a §15.6 power cut |
| X7 | Rule 6a's first case ("the L4T boot option had started before kexec") | Under UEFI entry, the Shell launch validates the boot chain (m5-design R11, C11). After it, a cut is judged as rule 6a's first case once §15.13.9's holds have passed. Menus before the launch follow m5-design §2 rule 5 in full | §15.13.9 |

**M5 §7.4 "never leave TX on while the terminal is stopped" needs no exception.** One `com3-term.ps1` session runs for the whole board session: started before the TX wire goes on, stopped after it comes off. The harness cuts per-phase segments by recorded byte offsets (§15.13.7).

---

#### 15.13.6 The board procedure (owner at the plug from J7a-bench to C)

**Conventions** as m5-design §6 and §15.4. `PS>` is PowerShell on the PC and `PC$` is Git Bash. `<rec>` is the session's `results/orin-native-port/20260914T045838Z/s1/`, so `used-boot-ids.log`, `used-captures.log` and `nvbootctrl-first.log` carry over.

**Operator rules** (m5-design §14.4, and M5's observed terminal behaviour):
- the terminal window keeps focus for the whole hotkey window;
- F12 before every key or line; every Enter after an arm disarms the terminal (M5's private record), so every Shell line needs its own F12;
- read each line on screen before its Enter;
- never press F12 after the Enter on `go` or `reset`; read the terminal's state line and press F12 only if it reads ARMED, to disarm. **The one exception is SHELL-AFTER-GO** (below);
- press nothing during any autoboot or `startup.nsh` countdown;
- **never arm the terminal or type while L4T, its shutdown or a login prompt is on COM3;** type only the lines and keys of §15.13.7's key-log allowlist.

| Step | Where | Who does what | Gate |
|---|---|---|---|
| **J7a-P0** | PC | Q20's desk read and branch; §15.13.4's D0a, D0b, commit, builds, T0; §15.13.7's parser, harness and privacy self-tests and the count-only replay; `com3-term.ps1 -SelfTest` | all pass; pins in J7a's prereg stage |
| **J7a-bench** | bench; board untouched | **Owner:** confirm the adapter's voltage jumper at 3.3 V by eye, with no rewiring. Remove the Ethernet cable if fitted, and every USB device on the board's ports (D46); leave the adapter's RX on pin 4 and GND on pin 7 as they are. Record any display and the peripheral set | owner confirms each item |
| **J7a-pre** | PC, then L4T read-only | `PS>` start `com3-term.ps1 -Out <rec>\com3-j7a-<utc>.log` (key log beside it); forwarding stays disarmed. `PC$ s1-board.sh j7a pre s1-j1` | §15.13.7's preconditions |
| **J7a-stage** | L4T | `s1-board.sh j7a stage`: backups verified or written (X4), S0, `scp` to `~`, then `b_esp_stage` | ESP = S0 plus exactly that file at its hash; `BOOTAA64.efi` unchanged. F65 on any stage failure: J7a cannot run on this design (D45) |
| **J7a-ctl** (control cold boot and TX refit) | board | `s1-board.sh j7a ctl` issues `poweroff` and watches for READY. **On READY, the owner:** removes DC power; fits the adapter's TX onto J14 pin 3, counting from pin 1, with nothing on pins 8, 10 or 12; waits at least 10 s (design constant) with power off; restores DC power; presses nothing | firmware banner, countdown and `L4TLauncher:` with no menu text; L4T with a new `boot_id`; S1 and Δ(S0,S1); the file persists at its hash; `nvbootctrl` equal to the first reading. **This tests the refit (m5-design R7, R15) and a byte at COM3 activity before any attended menu.** Any menu text is F58; no board output after the refit is m5-design F36 (remove the wire, power cycle) |
| **J7a-go** (per counted run) | board | `s1-board.sh j7a go s1-j1`: gate A (offset-aware), J7a prereg stage, S2, `poweroff`, READY. **Owner:** DC off for at least `DRAM_OFF_S`, noting the wall-clock times of the cut and the restore; then on | READY printed; the harness records READY's epoch and the first post-cut firmware byte's epoch |
| | firmware | On `ESC   to enter Setup.`: F12, one ESC. Arrows to `Boot Manager`, Enter; to `UEFI Shell`, Enter (F12 before each). `Shell>` within 120 s of the first ESC is the operator target; a later prompt is a recorded deviation, as in M5 | a missed ESC (`L4TLauncher:` follows) ends the attempt, not counted (exit 6): let L4T boot, repeat from J7a-go |
| | Shell | Each line armed, read, then Enter: `map -r`, where FS5 must be SD partition 10 as in M5 (otherwise `reset`, stop, owner); `fs5:`; `ls M5LOAD.EFI`; `memmap` (D43); `M5LOAD.EFI check` | **T1′,** each loader token within `LOADER_EXPECT_S` of the Enter or the previous token, then the prompt within `PROMPT_AFTER_S`: every M5 token plus `M5L variant=j7a`, `M5L self … canary=none`, `fdt … crc32=`, the `resmem` lines ending `M5L resmem done`, window-2 map lines, three `preclaim=ok`, `M5L W2 PASS`, `M5L CHECK PASS`. **Any `M5L REFUSE`: type `reset`, no `go`, record, stop, owner** (F50-F52, F54) |
| | Shell | `M5LOAD.EFI go`. The terminal disarms itself; confirm its state line. **Nothing is pressed until L4T answers ssh, except in SHELL-AFTER-GO** | §15.13.6.1's bounds; the harness watches COM3 only |
| | Shell (only in SHELL-AFTER-GO) | **SHELL-AFTER-GO:** a Shell prompt after the Enter on `go` with no `M5L-EBS` token (a refusal in `go`, including `w2-final`). The operator reads the terminal state line, arms once with F12, types `reset`, presses Enter, confirms the state line reads disarmed, and presses nothing more. Recorded | not counted (F61, and F53 for the refusal); J7a-go is not repeated in this session (m5-design D11) |
| **J7a-return** | L4T | automatic inside `j7a go` (or `j7a return <boardlog>` if the watch was interrupted): `reset_reason`, black box, pstore, `nvbootctrl`, S3, the Δ gates, the key-log allowlist check, segment reads, parser, canwatch, privacy scan | §15.13.10's V5, V6; parser verdict |
| **J7a-2** | board | only as §15.13.11 allows; from J7a-go on the return boot (no second control boot) | as J7a-go |
| **C** (close) | bench, then L4T | **Owner:** removes the TX wire from pin 3 **with the terminal still running**; then stops `com3-term.ps1` (Ctrl+]). `s1-board.sh j7a clean` with `S1_J7A_TX_REMOVED=yes`. The owner may refit the Ethernet cable and USB devices after `clean` | ESP = S0 exactly; `~/M5LOAD.EFI` absent; `nvbootctrl` equal; `esp_clean=ok`. A read-back hash that differs is F66 |

A session that ends before a counted `go` still runs C. The next session restages from J7a-pre, with a new capture and a new control boot, because the TX refit is repeated.

##### 15.13.6.1 Wait bounds and design constants (not results)

**Constants.**
- `LOADER_EXPECT_S = 120 s`: the expected bound on any silent stretch while the loader runs, from the Enter on `check` or `go` to `M5L start`, and from each loader token to the next, up to `M5L CHECK PASS`, `M5L GO` or a refusal. Exceeding it is F63, recorded; it is not a cut and not F55.
- `LOADER_CUT_S = 300 s`: no byte at all for this long, from the Enter or the last loader token, before a completed loader run. This is the first point at which §15.13.9 allows a cut.
- `PROMPT_AFTER_S = 60 s`: from the last `M5L` line of a completed loader run (`M5L CHECK PASS` or a refusal) to the Shell prompt (m5-design F9 applies only after this).
- `DRAM_OFF_S = 300 s`: the minimum unpowered time before every counted `go`'s cold boot (R95). The control boot keeps its 10 s.
- `ESP_MARGIN = 4 MiB`: above the loader's size rounded up to the ESP's cluster size (§15.13.7).

**From the Enter after `go`:**

| Expect | Bound |
|---|---|
| `M5L start`, then `M5L variant=j7a` and every loader token up to `M5L GO` | `LOADER_EXPECT_S` per silent stretch |
| `M5L GO` counted (budget key) | 10 s after `M5L GO` with neither a refusal nor a Shell prompt, or at `M5L-EBS ok\|FAIL` |
| `M5L-EBS ok`, `M5L-JUMP` | 60 s after `M5L GO`: both print only after the head's cache loop over the full `image_size` and the MMU-off step (VERIFIED (source): `m5load-head.S` steps 12-14) |
| `T234-SHIM EL=2 …` with `PC=0000000080080000`, then `JUMP` | 10 s after `M5L-JUMP` |
| `t234: WDT0 CR=` | 20 s after the shim line |
| `t234: canary c3 … filled` | 60 s after the shim line |
| `T234 S1 s1-j1 -P4: procnto up` | 120 s after the shim line |
| the image's reset line | the params' `guard_s` from `procnto up` |
| a firmware banner | 60 s after the reset line |
| L4T answers ssh with a new `boot_id` | 600 s after the reset line, and never later than `go_epoch` + the params' `return_bound_s` + 600 s |

---

#### 15.13.7 Harness, parser and privacy changes (PC, before any board step)

##### Defects that block reuse of today's code

| # | Defect | Class | Change |
|---|---|---|---|
| P1 | `com3-term.ps1` writes `seconds=0` in its capture header, and `capture_state` reads `epoch + 0 <= now` as `expired`. Gate A would refuse every com3-term capture, and `advice` would class it `nocapture` | VERIFIED (source: `s1-board.sh` `capture_state`; `com3-term.ps1` header line) | For kind `j7a` only, `seconds=0` means "terminal, no deadline", and `running` rests on the write-open test. Gate A's life check is replaced by: `seconds=0` header, a key log beside it starting `session-start`, capture `running`. Self-tests |
| P2 | `parse-s1.py run` requires `--kexec-tree-sha256` for board runs, and for J6 `wq_kexec_issuing=yes` and `wq_reset_marker=no`; `J1_STEPS` accepts only `control` and `remove` | VERIFIED (source) | `--entry uefi` (below) |
| P3 | `build-m5-loader.sh` writes a fixed `out/` | VERIFIED (source) | built in a worktree (§15.13.4) |
| P4 | ESP space. m5-design §8 item 11's "room several times over" was written for a far smaller loader. By private arithmetic on M5's preflight, a J7a-sized loader fits the ESP once, not twice, and meets `ESP_MARGIN` (class only) | VERIFIED (private preflight, class only) | `b_esp_stage` as specified below; `j7a pre` refuses early on a short ESP (F65) |
| P5 | The firmware's boot-option descriptions carry a network MAC in unseparated hexadecimal form and a drive identifier. `IDENT_MAC` matches only colon, hyphen and `enx` forms, so the Boot Manager screens and `efibootmgr -v` would be kept with identifiers. The Boot Manager screens are drawn with CSI cursor moves, which can split a string | VERIFIED (source for `IDENT_MAC`; the forms and the CSI sequences seen in M5's private records, class only) | new `efi` class in `redact` and `ident_hits`, both on CSI-normalised text (below); `efibootmgr -v` recorded as a board-computed hash plus structure only |
| P6 | `com3_last_kind` knows no `M5L`, Shell or menu line and strips no CSI sequence, so a last line of `M5L-JUMP` reads `unrecognised` | reported VERIFIED | kinds `loader`, `shell`, `fw-menu`; strip `\x1b\[[0-9;?]*[A-Za-z]` first |
| P7 | `canwatch` with no kpf still lets the class-only cpu-side rows fire | reported VERIFIED | under `--entry uefi`: `kpf=not-applicable`; the Linux-page-coincidence arms are suppressed |
| P8 | M5's watch and judge helpers were never committed | VERIFIED (m5-design §14.6) | their fixed rules are ported into `s1-board.sh` with self-tests: READY only on the power-down line; ANOMALY on any firmware text after `poweroff`; the reset pattern allows a trailing non-alphanumeric; bracket expressions, never escaped parentheses through `awk -v`. They are **committed and reviewed before the session** (D44) |
| P9 | `j6_precondition` refuses after any row holding F39 | reported VERIFIED | a separate `j7a_precondition` |
| P10 | Gate A and gate B refuse a capture that already holds record lines (`com3_has_records`), and the parser reads one run per log with first-match rules. One capture per session means J7a-2's gate A would see J7a-1's records | VERIFIED (source: `s1-board.sh` `com3_has_records` and its callers) | Under kind `j7a`, gate A checks for record lines only in bytes after the end of the last segment recorded in `used-captures.log` for this capture (the whole file if none). Gate B is kexec-only and unchanged: no `j7a` phase calls it, and no kexec rung may use a J7a capture (§15.13.15). The parser and canwatch read only the current segment. Self-test: two runs in one capture |
| P11 | The draft's J7a-go carried the 7,200 s uptime gate, citing R31. R31 is the pl011-needle claim. The limit is `MAX_UPTIME_S`, the §6.12/§7.3 rule for Linux state at a kexec hand-over | VERIFIED (source: `s1-board.sh` `MAX_UPTIME_S` and its message; `s1-design.md` R31) | **Dropped for `j7a`:** the L4T instance is powered off and DRAM left unpowered for `DRAM_OFF_S` before the entered power cycle, so its uptime reaches nothing the run depends on. Kexec rungs keep the rule unchanged |
| P12 | `com3-term.ps1` stores sent bytes as hex (`Write-Key`), so text redaction masks nothing typed, and one terminal session spans L4T boots with a login prompt on COM3 | VERIFIED (source: `Write-Key`, the armed and sent handling) | key-log allowlist check (below); key-log copies are plain byte copies of an allowlist-checked log, labelled as such |
| P13 | A segment cut into the record directory before redaction leaves a raw copy there if the step is interrupted | design defect in the draft | raw ranges are read through a pipe (below); no raw segment file is ever written into the record directory |

##### `orin-native/startup/s1-board.sh`: new `j7a` subcommands

All share one attempt id `S1_J7A_ID` and one capture per session. The harness never opens COM3: it reads the file, which com3-term holds shared for reading.

| Subcommand | Does | Board contact |
|---|---|---|
| `j7a pre s1-j1` | PC gates: clean tree (harness, `parse-s1.py`, `kpf-decode.py`, `com3-term.ps1`, `build-m5-loader.sh`, `m5-gate.py`, `m5load-rules.h`); the loader's `gate.txt` items 1-12 PASS, and its blob pin equals the params' `kimg_sha256`; the D0a reference commit and the T0 record named; `com3-term.ps1 -SelfTest` hash; T-J1 met with the params' `memcanary_w_sha256`; conf gate without the kexec tree; the Q20 branch recorded; no QEMU or other COM3 user. Board, read-only: `bios_version` as M5's firmware; `efibootmgr` structure shows the UEFI Shell and NVMe entries and `BootOrder` starting with the SD entry; SecureBoot off; the ramoops carveout as `RAMOOPS_REG_HEX`; ESP free space against the loader size and `ESP_MARGIN` (F65 refuses here, before any write); backups (X4); no leftover `/boot/efi/M5LOAD.EFI` (if present, only `clean` may run); `nvbootctrl` equal to the first reading | ssh, read-only |
| `j7a stage` | backups, S0 (`b_efi_snap`, `b_slots`), `b_esp_stage` | ssh; writes X2 and X4 only |
| `j7a ctl` | gate A; `mark_boot <old> j7a-ctl`; offset `j7a com3_bytes_before_poweroff=`; `b_poweroff`; `j7a_wait_poweroff`; prints `READY: cut DC, fit TX (owner), restore`; `j7a_watch_fw ctl` (banner, countdown, `L4TLauncher:`, no menu or Shell text); `wait_new_boot_id`; S1; `j7a_state_gate s0 s1` | before and after only |
| `j7a go s1-j1` | gate A (offset-aware, P10); `j7a_prereg_append`; S2; `pstore_before`; `mark_boot <old> j7a`; poweroff and READY as `ctl`; prints `READY: cut DC for at least DRAM_OFF_S, note the times, restore`; records `j7a ready_epoch=` and `j7a first_fw_byte_epoch=`; `j7a_watch_go` (below); `wait_new_boot_id` bounded from `go`; return records | before the poweroff and after the reset only |
| `j7a return BOARDLOG` | re-enters go's return reads, idempotently | ssh |
| `j7a clean` | `b_esp_clean` (below); `~/M5LOAD.EFI` absent; `b_slots` | ssh; one removal |
| `j7a-status BOARDLOG` | prints the watch state from COM3 | none |
| `advice BOARDLOG` | gains the `j7a` keys and §15.13.9's classes | ssh `boot_id` read |

**`b_esp_stage`** (ssh, in order; any failure ends the step with F65):
1. Read the ESP's cluster size and free space just before the copy. Refuse, writing nothing, unless free space covers the loader's size rounded up to a cluster plus `ESP_MARGIN`.
2. `cp` `~/M5LOAD.EFI` to `/boot/efi/M5LOAD.EFI`, then `sync`.
3. Read back the sha256 and compare it with the staged hash.
4. On any `cp` or `sync` error or a hash mismatch: `rm -f /boot/efi/M5LOAD.EFI` (that exact path, never a wildcard), `sync`, and verify the ESP listing equals S0. If the removal fails or the listing still differs from S0, stop all board work: F57, owner.
5. On success: remove `~/M5LOAD.EFI`, record, and only then may `ctl` print READY. `stage` and `ctl` are ordered phases, so no planned cut can come before a verified write.

**`b_esp_clean`:**
- Read back the sha256. If it equals the staged hash: `rm /boot/efi/M5LOAD.EFI`, `sync`, listing equals S0, `esp_clean=ok`.
- If it differs: stop, record `esp_clean=hash-mismatch` (F66), delete nothing. The owner may authorise removing that one path by name, by setting `S1_J7A_ESP_REMOVE=/boot/efi/M5LOAD.EFI` (any other value or a wildcard is refused). Then `rm`, `sync`, listing equals S0.
- Any ESP file other than S0's and that path is F57.

**`j7a_watch_go` states,** each logged with its COM3 byte offset:
1. `FIRMWARE`, `HOTKEY`.
2. `MISSED` (`L4TLauncher:` before Shell text): exit 6 after a new `boot_id`, not counted.
3. `SHELL`: the 120 s operator target from the key log's first sent ESC is recorded, not enforced.
4. `MEMMAP`.
5. `T1` (in order) or `REFUSE`: exit 6, not counted, stop.
6. `GO` (the Enter on `go` seen in the key log).
7. `SLOWLOAD` (F63) when a silent stretch passes `LOADER_EXPECT_S`; the watch continues.
8. `SHELL-AFTER-GO` (F61): a Shell prompt after `GO` with no `M5L-EBS` token. It records any refusal (F53), expects the operator's `reset`, and ends with exit 6, not counted.
9. `COUNTED`: at `M5L-EBS ok` or `M5L-EBS FAIL`, or 10 s after `M5L GO` with neither a refusal nor a Shell prompt. It writes `j7a go_counted com3_bytes_at_go= go_epoch=`. **This line is the budget key.** A refusal after `M5L GO` and before `COUNTED` leaves the attempt uncounted.
10. `JUMP`, `SHIM`, `WDT0`, `FILLED`, `PROCNTO`, `RECORDS`, `EXPORT`.
11. `RESET` (`… resetting so the log can be recovered`), `BANNER`, `L4T`.

Negative tokens after `COUNTED`: `M5L-EXC`, `M5L-EBS FAIL`, `BAD-LANDING`, `EXC `, `EL!=2`, `kexec_core: Starting new kernel`, any `s1wq:`.

**Exit codes.** 0-5 keep their meanings. **6:** the attempt ended before a counted `go`. **7:** a counted `go` never reached `procnto up`, which is F55, counted.

**Environment.**
- Required as today: `ORIN_HOST`, `ORIN_KEY`, `S1_RECORD_DIR`, `S1_COM3_LOG` (Windows paths accepted), `S1_REDACT_SSID` (the return boot's L4T text passes through the capture).
- New: `S1_J7A_ID`, `S1_J7A_LOADER` (the worktree's built `M5LOAD.EFI`), `S1_J7A_TX_REMOVED=yes` (`clean` only), `S1_J7A_ESP_REMOVE` (`clean` after F66 only).
- Refused: any variable that would change a bound or a design constant.

**`j7a_precondition`** requires, in `J-waivers.conf`: `D30=yes`; `D34_J7A=yes` (J2's and J6c's rows hold F39); `D35=yes`; J4's row F36; J6c's row carrying the live-writer label; `D38=yes`; `D45=esp`; `D46=yes`; and, under Q20 branch (b), `D47` recorded. It prints `kexec_runs_before=` and `j7a_counted_before=`, and it refuses a third counted `go`, and any `go` after an F62 on the same image.

**Budget helpers.** `j_kexec_runs` is unchanged: it keys on `run com3_bytes_before_kexec=`, which J7a never writes. The new `j7a_counted_runs` counts `^j7a go_counted `.

**Offsets and segments.** Each phase writes its offsets. A segment is the capture's byte range `[offset before poweroff, end of return reads)`.
- The parser, canwatch and the privacy scan read that raw range through a pipe (`tail -c` and `head -c` into the tool's standard input), or through a `mktemp` file outside the record directory that an EXIT trap removes. No raw segment file is written into the record directory.
- The kept segment copy is written by piping the same range through `redact`. The raw range's byte offsets and sha256 are recorded; the raw bytes are not.
- `used-captures.log` records the capture once, with each segment id and its end offset; a segment is used once.

**Key-log allowlist check (`j7a_keylog_check`).** Run at every return and at close.
- It decodes every `sent` entry of the key log, applies Backspace (`08`), and reconstructs each line at its Enter.
- **Allowed key sends:** ESC `1b`; arrows `1b 5b 41` to `1b 5b 44`; Enter `0d`; Backspace `08`.
- **Allowed reconstructed lines:** `map -r`, `fs5:`, `ls M5LOAD.EFI`, `memmap`, `q`, `M5LOAD.EFI check`, `M5LOAD.EFI go`, `reset`, and the empty line (a menu Enter).
- Printable bytes that do not end in an allowed line, or any `sent` entry while the segment's last COM3 class is L4T text, are F64. The key log is then not copied into a J7a directory, the result is flagged, and the owner decides. Otherwise the copy is a plain byte copy, labelled "allowlist-checked, unredacted".
- F59 is any `armed` or `sent` entry after the Enter on `go` other than SHELL-AFTER-GO's single arm and `reset` line.

**Harness self-tests** (synthetic, plus in-place replay of M5's private P2, P3 and R1 captures under an environment variable, never copied or committed):
- a `seconds=0` capture;
- READY needs the power-down line; ANOMALY on firmware text;
- each watch state and negative token, with CSI and menu lines;
- a slow but valid `check` and `go` (silent stretches between `LOADER_EXPECT_S` and `LOADER_CUT_S`) are F63 only: neither a cut advice nor F55;
- SHELL-AFTER-GO after a `w2-final` refusal and after a pre-GO refusal: not counted, `reset` accepted, F59 not raised;
- `COUNTED` once only; `w2-final` stays uncounted; `M5L-EBS FAIL` counts;
- two runs in one capture: gate A passes for J7a-2 after J7a-1's segment is recorded, and fails when J7a-1's segment is not;
- the key-log allowlist: a clean log passes; a typed free-text line, a line typed while L4T text is last, and a stray printable byte each give F64;
- the `efi` redaction class, including a CSI-split MAC;
- `b_esp_stage` failures (short space, `cp` error, hash mismatch) leave the listing equal to S0; `b_esp_clean` with a mismatched hash deletes nothing without `S1_J7A_ESP_REMOVE`, and refuses a wildcard;
- an interrupted return leaves no raw segment file in the record directory or its temp location;
- the ESP listing compare;
- `j_kexec_runs` does not count J7a;
- no `B*` or `J6*` directory is created;
- a refused third `go`, and a refused `go` after F62.

##### `orin-native/s1/parse-s1.py`

- **`run … --entry kexec|uefi`,** default `kexec`. Under the default, a re-parse of B2's, J2's, J4's and J6c's own captures must print byte-identical output (R92).
- **`--arm uefi` with `--entry uefi` only:** `J1_STEPS[("board","host")]["uefi"] = "J7a"`. `--loader-sha256 HEX` is required under `--entry uefi`.
- **Under `--entry uefi`,** reading one segment only (P10):
  - **Item 5:** no `kexec_tree_sha256`; it records `entry=uefi`, `loader_sha256=`, and the presence of the `M5L fdt … crc32=` line (its figure goes to the private `parse-s1.txt` only).
  - **`wq_kexec_issuing` and `wq_reset_marker`** print `n/a-uefi` and leave `want`. `wq_markers=none` is required (no `s1wq:` anywhere).
  - **New required checks,** on the segment's last Shell visit:
    - `M5L start mode=check … el=2` and `M5L start mode=go … el=2`, each followed directly by `M5L variant=j7a`, then `M5L self w2=… canary=none`;
    - for both: `crc src=ok`, `crc dst=ok`, `M5L resmem done`, three `preclaim=ok`, `M5L W2 PASS`;
    - `M5L CHECK PASS`, and the go prelude matching the check prelude;
    - **exactly one counted `M5L GO`:** an `M5L GO` not followed by a refusal before `M5L-EBS`; then `M5L-EBS ok`, `M5L-JUMP`, the shim line with `PC=0000000080080000`, then `t234: WDT0`, in order;
    - zero negative tokens after the counted `M5L GO`. Text before it is unconstrained.
  - **`resmem` summary (private `parse-s1.txt`, class only):** `resmem_c2=none|<node names>` and `resmem_c2_base=yes|no`, from the go visit's lines.
  - **Unchanged:** L0, L1, L7 (the reset line and a firmware banner after it; `MAINSWRST`; the black box consistent with COM3), the canary checks, watches a-d, the hold, the exports, `memcanary_w_sha256`.
  - **The row** keeps J6's rules and adds `j7a=clean|bad|bad-partial|bad-unstable|revert-only|F39c1|F39c3|F49|F62|incomplete` by §15.13.10.1-2. It never prints `pass` or `b2=`.
- **`canwatch … --entry uefi --ref-j6c <J6c dir>`:** `kpf=not-applicable`; the coincidence rows suppressed; and `profile_vs_j6c=same|differs:<items>` plus `kw_sub=anchored|differs|partial` for bad runs only (§15.13.10.3). J6c's `parse-s1.txt`, `canwatch.txt` and c2's watch exports must match the sha256 registered in J7a's stage.
- **Self-tests:**
  - a synthetic UEFI capture is complete;
  - it is incomplete for each missing token (`M5L variant=j7a`, `M5L resmem done`, `M5L W2 PASS`, a `preclaim=ok`, `M5L-EBS ok`, the fdt stamp);
  - it is incomplete when `M5L-JUMP` follows the shim line, when two counted GOs appear, or on any negative token after GO;
  - an `M5L GO` followed by `M5L REFUSE w2-final`, then a later counted `M5L GO` in a new Shell visit of the same segment, parses the later one only;
  - a c2 `verify=bad` start check followed by a missing watch gives `bad-partial`;
  - P7's overlap on synthetic bitmaps at, above and below the threshold;
  - `--arm uefi` without `--entry uefi` is refused;
  - the output never contains `pass`, `b2=`, a 16-hex-digit value, a dotted quad or a MAC form.

##### Privacy

- **CSI normalisation first.** `redact` and `ident_hits` strip CSI and OSC sequences, and turn cursor-positioning sequences into line breaks, before matching. When an identifier is found only after normalisation, the redacted copy masks the whole screen region between the surrounding clear-screen or cursor-home sequences.
- **New `efi` class** in `redact` and `ident_hits`:
  - `MAC[:(]` followed by 12 hex digits, and EUI-64 hyphen groups;
  - the NVMe boot option's description text, masked whole wherever a boot-option line names an NVMe device, on COM3 and in any `efibootmgr` output.
- **`redact-selftest`** gains one synthetic of each, with documentation-reserved values, plus a MAC split by a cursor-positioning sequence.
- **Count-only replay** of the scan over M5's private P2, P3 and R1 captures, in place, including their menu segments: after redaction, zero `efi` hits remain. Counts only; the captures are not copied (R91).
- **`efibootmgr -v`** is recorded as a board-computed sha256 of its output minus `BootCurrent`, plus entry numbers, active flags and `BootOrder`. No descriptions.
- **`S1_REDACT_SSID`** stays mandatory.
- **The raw capture** stays inside the git-ignored record directory and is never copied, quoted or opened by hand. Only redacted segment copies and allowlist-checked key-log copies are kept in J7a directories.
- **`resmem` lines** carry node names and classes only; the node names are the firmware's, not identifiers, and still pass through `redact`.
- **Existing exposure, recorded:** M5's private records already hold `efibootmgr -v` and menu screens raw. They are git-ignored and never pushed; this design does not rewrite them.

---

#### 15.13.8 Records

**Pre-registration.** Before the first `go`, after gate A, `j7a_prereg_append` writes a `prereg stage=j7a` block to `<rec>/J-prereg.log`. It never re-emits J2's or J6's lines, and an amendment uses the D34 form. It holds:
- commit and a clean tree;
- `s1-board.sh`, `parse-s1.py`, `kpf-decode.py`, `com3-term.ps1` and `m5load-rules.h` sha256;
- `j7a image=s1-j1 entry=uefi arm=uefi`;
- `loader_sha256=`, `blob_sha256=` (equal to J6c's registered `kimg_sha256`), `gate_sha256=`, `d0_reference=`, `t0_record=`;
- this section's rule text sha256 (§15.13.6.1, §15.13.10 and §15.13.11 as approved), including P7's threshold and the design constants;
- J6c's `parse-s1.txt`, `canwatch.txt` and c2's watch exports sha256 (the reference profile);
- `fill_rate_factor=4`, unchanged;
- `q20_branch=a|b|c`;
- the peripheral set (D46), as class words;
- the D-rows taken.

**Directories** (§15.4's conventions; no `B*` or `J6*` directory is created or written):
- `<rec>/J7a-session-<utc>/`: `pre`, `stage`, `ctl` and `clean` board logs; S0 and S1 snapshots; the loader's `gate.txt` and build log copies; the params copy; the control segment copy (redacted); `-c-espfiles.log`.
- `<rec>/J7a-1/` and `<rec>/J7a-2/`, one per counted `go`: the go board log; S2 and S3 (and S4 if a warm control is needed); the redacted segment copy and the allowlist-checked key-log copy; `-memmap.txt` (the Shell block, if typed); `-resmem.txt` (the `M5L resmem` lines); `-nvbootctrl-{pre,post}.log`; `-blackbox.log` (and any new `dmesg-ramoops`); `-dram-off.log` (READY's epoch, the first firmware byte's epoch, and the owner's stated cut and restore times); `parse-s1.txt`, `canwatch.txt`, `s1-j1a..d.bin`; `-go-gate.log`; `j7a-note.log`, hand-written like `j6c-note.log`.
- `<rec>/J7a-nogo-<utc>/`: an attempt that ended before a counted `go` (missed ESC, refusal, SHELL-AFTER-GO, no READY, F65).

**Absent on purpose,** each with a line in the board log saying why:
- no `-kpf-*` ("kpf not-applicable: no Linux ran in the entered power cycle");
- no `-iomem-postrmmod`, `-pci-*`, `-wq*` or `-trace.txt`;
- no kexec tree;
- no raw segment file.

**Snapshot set** (`b_efi_snap`):
- `boot_id` and uptime;
- the `efibootmgr` hash and structure;
- efivars as `name sha256`;
- `find /boot/efi -type f -exec sha256sum {} +`;
- `extlinux.conf` and `BOOTAA64.efi` sha256;
- `bios_version`;
- `ls -l /sys/fs/pstore`;
- SecureBoot's state;
- ESP free space and cluster size;
- the ramoops carveout; `b_slots`.

**Return state gate** (`j7a_state_gate`, m5-design §5.2 items 3-5, as validity gates):
- efivars: no name added or removed; each changed name also changed in Δ(S0,S1);
- `efibootmgr` hash equal apart from `BootCurrent`;
- ESP = S0 plus the file at its hash;
- `extlinux.conf`, `BOOTAA64.efi` and `bios_version` equal;
- `nvbootctrl` equal to the first reading.

A name changed only in Δ(S2,S3) triggers a warm control (`s1-board.sh reboot`, S4, compare), as in m5-design §6.7.

**Run note** (`j7a-note.log`, private): as m5-design §6.10 and `j6c-note.log`. Every figure stays private until the 4.6(i) consultation.

---

#### 15.13.9 Power-cut and advice rules

`advice` gains the offset keys `j7a com3_bytes_before_poweroff=`, `j7a poweroff_ready com3_bytes_at_ready=`, `j7a go_enter`, `j7a go_counted com3_bytes_at_go= go_epoch=`, `j7a shell_after_go`, `j7a shim_seen`, `j7a reset_seen`, and `j7a NO RETURN within`. Offsets come only from a board log naming the same capture; otherwise NO CUT and the owner decides. It never advises a cut while ssh answers.

| Phase, by the last COM3 class after the offsets | Cut? |
|---|---|
| L4T running, before a run | only the planned cut after READY (X6) |
| `poweroff` issued, no power-down line yet | **NO CUT.** Firmware text after the offset means the board rebooted instead: let L4T boot; not counted (F60) |
| READY | the planned DC cycle (owner), unpowered for at least `DRAM_OFF_S` before a counted `go` |
| Power-on to the start of `Boot0007` (firmware, menus) | **Never,** except m5-design §2 rule 5's single cut for a firmware that has stopped (10 minutes with no byte, the last output not a menu or prompt, no ssh). A menu is left with `Continue` or a boot option |
| Shell launched (`check` or `go`), loader running, before a completed loader run: a silent stretch past `LOADER_EXPECT_S` | **NO CUT** (F63, recorded) |
| Shell launched, before a completed loader run: no byte for `LOADER_CUT_S` from the Enter or the last loader token, or an edk2 exception dump (m5-design F9b) | **one cut (class P):** the Shell launch validated the boot. Record the last line |
| A completed loader run (`M5L CHECK PASS` or a refusal) with no Shell prompt within `PROMPT_AFTER_S` (m5-design F9) | **one cut (class P).** Record the last line |
| SHELL-AFTER-GO | **NO CUT.** The operator arms once and types `reset` (F61) |
| `M5L GO` seen; no `M5L-EBS`, no refusal, no prompt | counted after 10 s; one cut only after `go_epoch` + 600 s with no new byte and no banner (the exit may have happened; m5-design F17, F20; X7) |
| Counted `go`, no `T234-SHIM` | one cut, only after `go_epoch` + 600 s with no new byte and no banner (m5-design F17, F20; X7) |
| Shim seen, no image reset line and no banner | **NO CUT until `go_epoch` + the params' `return_bound_s` has passed,** then one cut only after 10 minutes of COM3 silence with the last line not a menu or prompt. The watches and the hold are silent by design (§15.4.8), and **the hold's own dwell bound reaches 10 minutes**, so the silence rule is safe only because it waits for the return bound first. A later edit must never drop that wait |
| The image's reset line, a `BWAIT` guard deadline or a firmware banner after `go`; L4T not answering | m5-design §2 rule 5's exception and §2 rule 6a's second case, word for word. **Never a second cut** |
| No capture, or it ended | as the row above |

**After any cut other than the planned one:**
- record the last COM3 line;
- let L4T boot to a validated state before any other step;
- read `nvbootctrl` against the first reading (F30 or m5-design F33 stops all board work);
- it is a §15.6 immediate stop for J7a, and never a second cut.

**Self-tests** replay synthetic captures for each row, plus M5's private captures in place (READY, MISSED, SHELL, GO).

---

#### 15.13.10 Pre-registered reading

Fixed before J7a-1 and registered by hash. No J7a result exists, so the §15.6 amendments below cannot be fitted to one.

##### 15.13.10.1 Terms

**Complete run.** A counted `go` is complete (`verdict=diagnostic complete`, step J7a) when all of these hold:

| Gate | Evidence |
|---|---|
| V1 loader | T1′ in the same Shell visit; UM2-UM5 and UM9 lines with no refusal; `M5L GO`, `M5L-EBS ok`, `M5L-JUMP` |
| V2 entry | `T234-SHIM EL=2` with `PC=…80080000` and the big-endian DTB magic; `t234: WDT0`; `t234: ram w2`, `gpu range … not added`, three `canary … filled`, as B2 |
| V3 host | `procnto up` naming `s1-j1`; `S1 W2 reflected=yes`; `S1 ASINFO` equal to J6c's; `memcanary_w_sha256` equal to the pin |
| V4 watcher | J6c's complete-parse rules (`--diag j1`): six canary checks, watches a-d well formed and in order, the hold's fill and verify lines, exports a-d decoded; `wq_markers=none`; item 5 as §15.13.7 |
| V5 return | the image's reset; a firmware banner; autoboot with no key; L4T with a new `boot_id`; `reset_reason` `MAINSWRST`; black box consistent with COM3; the key-log allowlist check passes |
| V6 state | §15.13.8's return state gate. **A failure is F57, an immediate stop, whatever the canaries show** |

A counted run missing V3 or V4 for an image or tool reason is F56: incomplete, counted, with nothing resized at the board (§15.12 C). An F64 alone does not make a run incomplete; it is flagged for the owner.

**c2's state in one complete run,** over the two canary checks and c2's watches a-c:

| State | Holds when |
|---|---|
| **clean** | c2 `verify=ok` at both checks; every c2 watch base `bad` 0 and `writer=none`; no revert on c2's watches (§15.12 B7) |
| **bad** | c2 `verify=bad` at either check, **or** any c2 watch base `bad` above 0, **or** any c2 change event with stable re-reads. A transient write that later healed is still a write |
| **revert-only** | not bad, but a c2 revert or oscillation above 0: a misread with no write shown |

**c2 bad in a counted run that is not complete (one rule, pre-registered).** When c2's `canary … filled` line was printed and a parse-valid canary check prints c2 `verify=bad` before the run fails for any later reason (F49, F56, F62, a cut), the run reads **bad-partial**. It classifies as K-w with sub-label `partial` (§15.13.10.4), unless F34 holds on c2's printed watches (then bad-unstable). Profile items that need missing data print `n/a`. A run with no parse-valid c2 check reads nothing about c2.

There is **no map label.** UM4's pre-claim makes every complete run's c2 ConventionalMemory at the claim and ours until the exit. A map that is not free refuses before `go` (F50-F52, F54).

##### 15.13.10.2 One run

| Observation in a counted run | Run reading |
|---|---|
| complete; c2 clean; c1 clean; hold `verify=ok` | **clean** |
| complete; c2 bad | **bad**, with its profile (§15.13.10.3) |
| not complete; c2 bad at a printed check (§15.13.10.1) | **bad-partial** |
| complete; c2 revert-only | **neither:** an H3 lead under UEFI entry; the run counts |
| c2 bad **and** F34 on c2's watches (§15.12 B5) | **bad-unstable** (K-r(u)) |
| c1 bad at either check or in watch d | **F39c1: immediate stop** (c2's reading from the run still stands) |
| hold `verify=bad` or `timeout data=bad` | **F49: immediate stop** (c2's reading still stands); BootServices descriptors printed in window 1 or 2 are named in the reading |
| c3 bad | **F39c3:** recorded; it does not stop J7a-2 (D39) and never changes c2's reading |
| `reset_reason` not `MAINSWRST` after `procnto up` and before the image's reset line | **F62:** counted; c2's reading from printed checks stands under the partial rule |

##### 15.13.10.3 Profile against J6c (bad and bad-partial runs)

`canwatch` prints `profile_vs_j6c` and `kw_sub`. An item is **same** when:
- **P1 onset:** c2 is bad at watch a's base scan;
- **P2 anchor:** c2's first mismatch at the start check is its first word;
- **P3 reads:** F34 does not hold, and `reads=stable`;
- **P4 content:** the `content=` leading classes equal J6c's, and the flip and pattern-copy classes are zero;
- **P5 activity:** no c2 watch reads `ongoing`;
- **P6 direction:** the end-check count is not above the start-check count;
- **P7 page set:** from c2's watch-a export, compared with J6c's (count-only, printed privately as pages in common, only in J7a, only in J6c): the per-MiB presence vector (which of c2's sixteen MiBs hold at least one `bad_final` page) is identical, **and** the pages in common are at least half of J7a's `bad_final` set and at least half of J6c's. The same comparison is printed for `changed_ever` as a record, not a gate. The threshold is a design constant, deliberately loose: only J6c has bitmaps, so no kexec-run variability is known. J6c's private note records that its hit pages sit in some MiBs and are absent from others, including slab-dense ones; that pattern is what P7 compares.

**`kw_sub`** (pre-registered):
- **anchored:** P1, P2 and P7 are all same. P3-P6 may differ and are listed.
- **differs:** any of P1, P2 or P7 differs.
- **partial:** the run is bad-partial, or P1, P2 or P7 cannot be computed.

| Differs in | Reading (all HYPOTHESIS) |
|---|---|
| none (`same`) | the same lay-down, on the same pages, with no Linux in the power cycle. J6c's leading content includes `kva`, so Linux-specific structures are excluded **unless startup's fill did not land on those pages and pre-cut DRAM content survived `DRAM_OFF_S`** (R95; the fill has no read-back). Remanence plus a failed fill would also predict pages Linux held, so P7 same does not break that tie; only the unpowered wait argues against it. Among the remaining writers, QNX-side (H5) and a secure-world writer with high virtual addresses lead over non-secure firmware, which runs identity-mapped (m5-design C4). A `resmem` node over c2 (UM9) is named as the lead. J7e (base shift) is next in revision 4, not J7d |
| P4 only | the same kind of lay-down with different data: the data depends on the entry state, two writers, or (with `zero` or `ones` dominant) a fill that did not land after decayed DRAM (R95) |
| P2 | not tied to the base word; weakens H2's "user of window 2's base"; raises J7c's priority |
| P5 (`ongoing`) | a writer still active while QNX runs, stronger than J6c; the exposure item is raised |
| P1 (late onset) | onset after QNX came up: H5 or a timer-driven firmware writer leads; J7e first |
| P7 | a different page set: a different or entry-dependent writer, or UEFI-driver residue (R82). The anchored reading is not made from this run |
| positive byte signatures above 0 | recorded as a lead; an absence excludes nothing |

##### 15.13.10.4 Across runs, against §15.6

Preconditions met (VERIFIED, private record): J4 is F36; J6c's parser row carries `live-writer`.

| Class | Holds when | Sub-labels | Then |
|---|---|---|---|
| **K-w** | **any one counted J7a run reads bad or bad-partial** (not bad-unstable) | `anchored\|differs\|partial` (§15.13.10.3); `profile=same\|differs:<items>`; `intermittent` if another complete run was clean; `repeated` if two runs read bad | "Writer unidentified; not the removable masters; present with no Linux in the power cycle." Kill condition 1 stands for the 11c candidate. Only `anchored` adds "the corruption is anchored at the address" (HYPOTHESIS). Revision 4 as §15.6: a new range, J7c's canaries in its B2, J7e for H5. **After `anchored`, J7a stops.** After `differs` or `partial`, J7a-2 runs within the cap, if no immediate stop applies, to test for a repeat; then the owner decides |
| **K-r(u)** (sub-class of K-r) | a counted run reads bad-unstable | — | "c2's reads are unstable under UEFI entry; under kexec they were stable, with corrupted data." The range is unusable under both entries. Revision 4's B2 gets a read-stability check under both. Outranks K-w for the same run. J7a stops |
| **E** | **two complete counted J7a runs, both clean;** no F39c1, F49, F55, F57 or F62 in the counted runs; no F50 in any J7a attempt. A refused `check` (F51, F52, F54) or F53 or F61 in an earlier, uncounted attempt the owner chose to retry does not block E | `c3=clean\|hit` | "The writer needs the kexec entry path in this power cycle, in the broad sense: Linux's DMA, or a coprocessor, firmware, PSCI, clock or EMC state that Linux's run, its shutdown or the L4T boot option leaves, or the tree. The cause within that path is not identified." **E does not exclude a writer anchored at window 2's base whose activity depends on kexec-path or L4T-boot state; J7c and J7e keep their value under E.** Not a range verdict. B2 stays NOT MET on data. Owner (D31): a wider quiesce search in revision 4, UEFI entry for S1 under freeze item 3 (with its own B1 and B2 under that entry), or stopping S1-F |
| **K-o** (new) | a `check` refuses with F50 | `where=c1\|c2\|c3\|w2` | "Kill condition 1 stands on the firmware's own map at Shell time; no writer is shown." Recorded as contradicting 11c's `/proc/iomem` reading (plan §8 unknown #6, freeze item 6). Revision 4's range derivation includes a UEFI map read. Needs the owner's acceptance (D41) |
| **U** | anything else, including: one clean run and no second complete run; a revert-only run with the other clean or missing; F51, F52, F53, F54 or F61 twice for one cause; F55; F56 or F62 with no parse-valid c2 check; F39c1 or F49 with c2 not bad; F65; any immediate stop before a class holds | leads recorded | B2 stays data; S1-F stays stopped; owner (D31) |

**Precedence:**
1. An immediate stop ends J7a.
2. A reading made in the stopping run still classifies: c2 bad or bad-partial there still gives K-w, with the exposure item.
3. K-r(u) outranks K-w for the same run.
4. K-o needs no counted run.
5. A clean run then a bad run gives K-w/intermittent.
6. A first run reading K-w `anchored` or K-r(u) ends J7a. A first run reading K-w `differs` or `partial` allows J7a-2 (§15.13.11). If J7a-2 then reads bad with P1, P2 and P7 same **as J7a-1**, the label is `differs,repeated` (a UEFI-path lay-down of its own); bad with an anchored profile against J6c gives `anchored`; clean gives `intermittent`.

##### 15.13.10.5 Cases the analyses raised, read in advance

- **Firmware memory over c2 or window 2 at `check`.**
  - A runtime, reserved, MMIO, unusable, NVS or gap type gives F50, and K-o under D41.
  - A Loader* or BootServices* type over a canary, with `M5L self … canary=none`, gives F51: U with the lead "a Shell-time allocation over the canary, not the loader's own image (it may be the Shell's buffer for our file)". It is not a firmware-memory finding by itself. The owner decides whether a later session retries.
  - The loader's own image over the target or a canary (`M5L self … canary=cN`, or `REFUSE alloc`) gives F54: a loader-placement problem, revised offline and rerun through T0. Not U and not a firmware finding. Placement is probably deterministic (R79), so no retry happens without a revision.
  - Either way there is no `go`, and no tolerance is widened at the board (M5 D4).
- **The firmware tree over window 2 or c1:** F52, U with its lead.
- **A `resmem` node over c2 (UM9):** never a refusal. Under K-w `anchored` it is named as the lead; under E it is recorded and not excluded.
- **c3 bad:** F39c3. c3 carried a small static write in two of the four kexec runs, so under D39 it does not stop J7a-2 when E still needs that run. Under E, the class line gains `c3=hit`, and public text uses the `c3=hit` sentence (§15.13.16).
- **c1 bad:** F39c1 stays an immediate stop with no waiver. c1 was clean in every kexec run, so a hit with no Linux is a new window-1 exposure, and D32's freeze-gate sub-item is updated.
- **The hold fails (F49):** an immediate stop; the exposure item is raised ("a writer reached held sysram with no Linux in the power cycle", HYPOTHESIS). BootServices descriptors printed in either window are named as a possible UEFI-driver residue (R82). A hold `map=fail` or `watch=fail reason=nomem` is F56, not F49.
- **Startup or QNX fails before `procnto up` (F55):** counted, no canary reading, J7a ends for the session. It is an entry-path finding for freeze item 3 (`-P4` from firmware state, window 2, a large IFS). It includes `M5L-EBS FAIL`, whose two causes (the exit refused four times, or UM6 refusing a later map) COM3 cannot tell apart. Whether the second `go` is spent on a retry is D42.
- **A WDT-type reset (F62):** `reset_reason` not `MAINSWRST`, after `procnto up` and before the image's reset line. **Counted** (the exit was attempted). c2's reading from printed checks stands under the partial rule. The unchanged image is not retried (D42): the same inherited WDT0 would recur. Before `procnto up`, the same observation is F55.

##### 15.13.10.6 Dated appends to §15.6's rows (not edits in place)

- **K-w:** "2026-09-14 (D38, §15.13): J7a is bad when one counted J7a run reads c2 bad, or bad at a printed check of an incomplete run, under §15.13.10.1. Sub-labels: anchored, differs, partial, intermittent, repeated. Only `anchored` supports 'anchored at the address'. The J6c live-writer condition rests on an early heal with stable re-reads, so K-w's recorded sentence never says 'live' or 'ongoing' unless J7a's P5 differs."
- **E:** "2026-09-14 (D38, §15.13): J7a is clean only when two complete counted J7a runs read c2 clean, with no F39c1, F49, F55, F57 or F62 in them and no F50 in any J7a attempt. E means the writer needs the kexec entry path's state in the broad sense, including the L4T boot option, PSCI history and uptime; it does not exclude an anchored writer that this state switches on."
- **K-o and K-r(u):** added as in §15.13.10.4.
- **U:** adds "one clean J7a run without a second complete run; a revert-only J7a run; F51, F52, F53, F54 or F61 twice for one cause; F55; F56 or F62 with no c2 check; F65".
- **Immediate stops:** "any power cut" gains "other than a J7a planned cut after READY (X6)".

---

#### 15.13.11 Budget, order and stops

- **J7a's own cap: at most two counted `go`s in revision 3.** They are outside §15.6's four-kexec count, which stays at three used (D38). `j7a_precondition` refuses a third.
- **Counted:** a `COUNTED` line (§15.13.7): `M5L-EBS ok`, `M5L-EBS FAIL`, or `M5L GO` followed by 10 s with neither a refusal nor a prompt. F55, F56 and F62 are counted.
- **Not counted** (m5-design §5.3): a missed ESC; no READY or an ANOMALY; a file not found; a capture not running; any `check` refusal; any refusal in `go` before `COUNTED`, including a first-try `w2-final` (F53); SHELL-AFTER-GO (F61); F65; a session stopped before `go`. After an uncounted refusal in `go`, the session does not repeat J7a-go (m5-design D11): it runs C, and a later session may retry. **Two failures for one cause end J7a** (§15.6).
- **Order in a session:** bench, pre, stage, ctl (refit), J7a-1, return. Then J7a-2 only if J7a-1 was complete and clean, complete and revert-only, complete with F39c3 and c2 clean, or K-w `differs` or `partial` with no immediate stop. Then C.
  - J7a-2 may run in the same session on J7a-1's return boot, or in a later session that repeats pre, stage, ctl and C.
  - No separate check-only power cycle: `check` before `go` is not irreversible.
  - After F62, no J7a-2 on the unchanged image.
- **Stops:**
  - §15.6's immediate stops (with X6's exception);
  - F30 or m5-design F33;
  - F50, F51, F52, F54; F55; F62 for the unchanged image;
  - F57;
  - a K-w `anchored` or K-r(u) reading;
  - a second failure for one cause;
  - F65 (J7a cannot run on this design; D45);
  - any need for a loader change at the board, a firmware setting change, a value dump or an SMMU read (scope stop).
- **After J7a ends, at any stop, or after each counted run:** a number-free classification memo to the owner, with the private notes.

---

#### 15.13.12 Failure signatures (the §15.7.2 table continues)

| # | Observable | Meaning | Class | Next |
|---|---|---|---|---|
| F50 | `M5L REFUSE w2 reason=gap\|type\|rt`, or a canary pre-claim refusal whose descriptor over that canary is runtime, reserved, MMIO, unusable, NVS, ACPI reclaim or a gap | the firmware map does not show window 2 as free RAM at Shell time | M (`reset`) | no `go`; K-o lead (D41); J7a ends; revision-4 input |
| F51 | `M5L REFUSE canary cN status=…` with Loader* or BootServices* over it and `M5L self … canary=none` | a Shell-time allocation that is not the loader's image covers a canary | M | no `go`; U lead; J7a ends for the session; owner |
| F52 | `M5L REFUSE fdt reason=w2\|canary` | the firmware tree lies in window 2 or over c1 | M | no `go`; U lead; owner |
| F53 | a refusal in `go` after `check` passed in the same Shell visit: any `M5L REFUSE` in the go run, including `w2-final` on the first try | the map changed between `check` and the exit | M | SHELL-AFTER-GO (F61); not counted; no repeat in this session (D11); a second occurrence ends J7a |
| F54 | `M5L REFUSE alloc status=…`, or a canary pre-claim refusal, with `M5L self` over the target or that canary | the firmware placed the larger loader over the target or a canary | M | revise the loader offline (m5-design Q7); T0 again; not a firmware finding |
| F55 | a counted `go`, no `procnto up` (any of m5-design F17-F24, F26-F28, including `M5L-EBS FAIL` from four refused exits or a later-try UM6 refusal, or a reset whose `reset_reason` is not `MAINSWRST`) | the entry path fails for `s1-j1` under UEFI | S or P (§15.13.9) | counted; no reading; J7a ends for the session; D42; freeze item 3 finding |
| F56 | a counted run past `procnto up` with V3 or V4 missing | image, tool or harness reason | SR | incomplete; counted; nothing resized; c2 by the partial rule |
| F57 | the return state gate fails (ESP, a variable outside the control set, `nvbootctrl`, `extlinux.conf`, `BOOTAA64.efi`, `bios_version`), or an ESP removal fails to restore S0 | m5-design F31-F33 | M or X | immediate stop; F33 stops all board work |
| F58 | an autoboot stops in a menu, or menu text appears with no key sent (control boot or after the image's reset) | TX level or a stray key (m5-design C15, F3) | M (`Continue`) | no `go` until one validated L4T boot; fix the wire |
| F59 | the key log shows `armed` or `sent` after the Enter on `go`, other than SHELL-AFTER-GO's arm and `reset` | auto-disarm did not fire, or an operator error | — | the operator presses F12 only if the state line reads ARMED; deviation recorded |
| F60 | firmware text after the `poweroff` offset with no power-down line (ANOMALY) | L4T rebooted instead of powering off | S | let L4T boot; not counted; retry once |
| F61 | SHELL-AFTER-GO: a Shell prompt after the Enter on `go` with no `M5L-EBS` token | a refusal in `go` returned to the Shell (F53) | M (arm once, `reset`) | not counted; recorded; session runs C |
| F62 | `reset_reason` not `MAINSWRST`, after `procnto up` and before the image's reset line | a WDT-type or other unplanned reset during the run (R85) | S | counted; c2 by the partial rule; no retry of the unchanged image (D42); Q20 re-read |
| F63 | a loader silent stretch past `LOADER_EXPECT_S`, with a byte before `LOADER_CUT_S` | slow SD load or copy | — | recorded; wait; not a cut, not F55 |
| F64 | the key-log allowlist check fails | free text, or keys sent while L4T text was on COM3 | — | the key log is not copied; flagged; owner decides; the run's reading is unaffected |
| F65 | `j7a pre` or `b_esp_stage` finds the ESP short, or a `cp`, `sync` or read-back failure | the ESP route cannot carry the loader | M | the file removed and S0 verified; J7a cannot run on this design; D45 |
| F66 | `b_esp_clean` reads back a hash that differs from the staged hash | a different or damaged file at the staged path | M | nothing deleted; owner authorises removal of that one path by name; listing equals S0 |

---

#### 15.13.13 Claims, desk questions (the §15.7.1 table continues)

| # | Claim | Class | Answered by |
|---|---|---|---|
| R77 | The SDP toolchain embeds and links the larger kimg; gate item 6's two link bases stay identical; the build is deterministic; the switch-off object of the edited file equals HEAD's; D0a's reference commit reproduces M5's staged loader | HYPOTHESIS | D0a, D0b; the J7a determinism rebuild |
| R78 | edk2 loads the larger PE, claims and copies within `LOADER_EXPECT_S` per silent stretch (QEMU, then the board) | HYPOTHESIS | T0b, T0c; T1′; F63 otherwise |
| R79 | NVIDIA's firmware places the larger PE, the Shell's file buffer and the tree away from the target, window 2 and the canaries | HYPOTHESIS (M5's small loader and tree landed high, once; top-down allocation from memory) | `self=`, UM2, UM3, UM4 lines |
| R80 | At Shell time, the firmware map shows only free types over window 2, as L4T's iomem suggests | HYPOTHESIS (the type-to-iomem rule and the layout's independence from the boot option are unread) | UM5 lines; `memmap` |
| R81 | `AllocatePages(AllocateAddress)` succeeds only if every page is ConventionalMemory, blocks later allocations there until the exit, and writes no page | VENDOR_CLAIM (the rule) / HYPOTHESIS (no write, Q19) | T0h-T0j, T0l; UM4 lines |
| R82 | UEFI drivers stop device DMA at `ExitBootServices` | HYPOTHESIS (m5-design §3.5) | not shown; bounded at the canaries by UM4 only; surface reduced by D46 |
| R83 | After the exit, no non-secure firmware code runs unless runtime services are called, and neither the shim nor startup calls any | VENDOR_CLAIM (UEFI) + VERIFIED (source: `x0` only; startup takes no system table) | — |
| R84 | Startup at `-P4 -b w2,canary`, `CPU_ON` of cores 1-3 from never-started state with their redistributors and INTID 28, procnto and the large hold work under UEFI entry | HYPOTHESIS (M5 ran `-P1`; M2 ran after kexec) | J7a-1 (F55 otherwise) |
| R85 | WDT0 does not reset the board during a guard-length run after the firmware's exit | UNKNOWN (the inherited CR token differs from J6c's, class only; the "configured" text is no evidence under UEFI) | Q20's desk read before D35; `reset_reason` (F62) |
| R86 | The SPE drains long `xport` exports after the firmware's exit, and com3-term's capture keeps them byte-exact | HYPOTHESIS (M5 used it for short text) | V4's export decode; `TCUDROPS` |
| R87 | A DC cold boot with at least `DRAM_OFF_S` unpowered leaves no Linux device or DMA state; coprocessor firmware re-initialises on both paths | HYPOTHESIS; the premise of E (refines R67) | not testable by J7a |
| R88 | Firmware CPU frequency, EMC and clock state, the boot option, PSCI history and uptime neither create nor suppress the c2 writer | UNKNOWN (confounds) | not separable |
| R89 | The Shell launch validates the boot chain, so rule 6a's first case transfers after it (X7) | VERIFIED handler (m5-design R11); the transfer is design | `nvbootctrl` after each return |
| R90 | This Shell's `memmap` prints the full map without paging | HYPOTHESIS | the optional line |
| R91 | The `efi` class, on CSI-normalised text, masks the Boot Manager screens' and `efibootmgr`'s identifiers | HYPOTHESIS | `redact-selftest`; count-only replay over P2, P3, R1 |
| R92 | `--entry uefi` and the `j7a` harness leave every kexec parse and command byte-identical | HYPOTHESIS | PC re-parse of B2, J2, J4, J6c; `harness-selftest` |
| R93 | The firmware tree lies outside window 2 on every Shell-path boot | VERIFIED once (M5); HYPOTHESIS per boot | UM3 |
| R94 | The firmware tree's `/reserved-memory` at Shell time matches Linux's live tree over window 2 and the canaries (E13) | HYPOTHESIS (L4TLauncher's boot may apply a different tree or overlays) | UM9 lines, against E13 at the desk |
| R95 | DRAM left unpowered for `DRAM_OFF_S` keeps no usable pre-cut content, so a fill that did not land could not reproduce Linux structures | HYPOTHESIS (published DRAM remanence at room temperature; not measured on this LPDDR5) | not testable by J7a; recorded off time |
| R96 | Removing the Ethernet cable and board USB devices reduces R82's surface; the M.2 wireless card, which carries ssh, stays and may be driven by the firmware | HYPOTHESIS | not testable by J7a; peripheral record |

**Desk questions.**
- **Q19:** does NVIDIA's r36.4.4 edk2 zero or otherwise touch pages on `AllocatePages(AllocateAddress)` under its memory-protection settings? Documentation only. No reading depends on it, since the fill follows; it bears only on "the loader writes no canary page".
- **Q20 (now before D35):** the public T234 watchdog register description: which WDT0 control bits mean enabled and counting toward a reset, and how the period and expiry stages read? Applied to the two private CR values, class only, it selects §15.13.4's branch. No register read is added.

---

#### 15.13.14 Owner decisions

| # | Decision | Recommendation | When |
|---|---|---|---|
| D35 | Accept §15.13: exceptions X1-X7, the Never items (§15.13.15), the gates, the design constants, the reading, the budget, the power table | accept | before any board step |
| D36 | Image | `s1-j1`, J6c's kimg unchanged (unless Q20 branch (b), then D47) | before building |
| D37 | Loader: the `M5L_J7A` build with UM1-UM10 (including the pre-claim, a volatile firmware-map change, and the read-only reserved-memory report), `m5load-rules.h`, the T0-only force switches and gate item 12; the ESP name `M5LOAD.EFI`; built in a worktree; D0a's reference commit and D0b's leak test; T0 rerun. A D0a mismatch is investigated first; acceptance of unexplained drift, with T0 as the only evidence, comes only after that | accept. Not recommended: a blob-only rebuild with the Shell's `memmap` as the only window-2 check | before building |
| D38 | Run cap and deciding rule: at most two counted `go`s, outside the kexec count; K-w on one bad or bad-partial counted run, with `anchored`, `differs` and `partial` sub-labels and J7a-2 after `differs` or `partial`; E on two complete clean counted runs; P7's threshold; the dated appends to §15.6 | accept, before any J7a result | before building (the parser implements it) |
| D39 | D34 extended to J7a (`D34_J7A`), so J2's and J6c's F39 do not block it; inside J7a, F39c3 does not stop J7a-2, and F39c1 stays an immediate stop | accept | before the session |
| D40 | Wiring: no loopback test (self-test plus the control boot, a recorded deviation from m5-design §8 item 4 as in M5 §14.3); the TX refit with DC power removed during the control boot; one terminal session per board session; TX removed at close with the terminal running | accept | before the session |
| D41 | K-o: does a non-free firmware type in window 2 at Shell time confirm kill condition 1 without a run? | yes, recorded as a map fact contradicting 11c, not as a writer | before the session |
| D42 | Retries: after F55, is J7a's second `go` spent on a retry of the same image? After F62? | after F55: no automatic retry, decided at the memo. After F62: no retry of the unchanged image (pre-registered) | before the session |
| D43 | Type the Shell's `memmap` once before `check` (record only) | yes | before the session |
| D44 | Commit and review the J7a loader, helpers, parser and privacy changes before the session (unlike m5-design §14.6); public wording as §15.13.16; whether the profile sub-labels appear in public text | commit and review; sub-labels stay private until D31 | before building is committed |
| D45 | Loader location: the SD ESP root (X2), or `~` on the APP rootfs through the Shell's filesystem mapping (§15.13.18 row 20). If `j7a pre` finds the ESP short (F65), J7a cannot run on this design; the rootfs route comes only through a reviewed amendment, never at the board | the ESP | before building the harness |
| D46 | Peripherals and DRAM wait: remove the Ethernet cable and board USB devices for J7a sessions; `DRAM_OFF_S` unpowered before each counted `go` | accept | before the session |
| D47 | Only under Q20 branch (b): a `-Wdisable` variant of `s1-j1` (new image, its own T-J1 and pins, the one-variable premise broken and recorded), or not running J7a | decide at the Q20 memo | before building |

---

**Taken 2026-09-14 (owner).**
- **D35, D36, D39, D41, D42, D43 and D44:** accepted as recommended.
- **D37:** the full `M5L_J7A` loader. **D45:** the SD card's ESP.
- **D38:** at most two counted `go` runs, and the deciding rule as written.
- **D40 and D46:** the wiring, peripheral and power steps as written.
- **D47:** open until Q20's desk read.
- **Next:** implementation on the PC, commit and review before any board step.

---

#### 15.13.15 Never (J7a additions; §7.3, §15.1's items and m5-design §7.4 apply in full)

- `go` any payload other than the pinned `s1-j1` blob; run a second `go` in one Shell visit; repeat J7a-go in a session after an uncounted refusal in `go`; `go` without T1′ in the same Shell visit.
- Type `dmem`, `mm`, `setvar`, `dmpstore`, `bcfg`, any output redirection, or any Shell script.
- Arm the terminal or type anything while L4T, its shutdown or a login prompt is on COM3; type any line or key outside §15.13.7's allowlist.
- Change any firmware setting to make a run work (DT/ACPI mode, boot order, timeout, Device Manager). A refusal ends the attempt; any loader change reruns T0 (M5 D4, D11).
- Widen a loader rule, a design constant, or accept a refusal, at the board.
- Let the loader write window 2, a canary or the GPU range (checked statically by review, and by T0u's rules).
- Stage the loader anywhere but the SD ESP root, or remove any ESP file other than the staged path, or use a wildcard in an ESP removal.
- Run a kexec rung, `jrun`, `capture-com3-raw.ps1` or any J1-J6 command while the TX wire is fitted, or use a J7a capture for any kexec rung.
- Jumper the adapter's TX to its RX while the RX is on the board.
- Fit or remove the TX wire while the terminal is stopped. The fit happens with DC power removed.
- Restore DC power before `DRAM_OFF_S` has passed ahead of a counted `go`.
- Send a key after `go` until L4T answers ssh, except SHELL-AFTER-GO's single arm and `reset`.
- Open an ssh session to the board between the planned cut and the image's reset.
- Copy, quote or open the raw capture by hand; write a raw segment file into the record directory; keep an `efibootmgr -v` output or a menu screen unredacted.
- Commit any `.efi`, the loader's `out/`, a kimg, a capture, a key log or a snapshot.

---

#### 15.13.16 Public text

- **Before J7a runs.** Number-free status only: "B2 not met on data; writer diagnosis continues; a UEFI-entry arm (J7a) is designed and awaits the owner's approval." §15.4.9's J7a row gains "designed in §15.13".
- **After D31, one class sentence, verbatim or close:**
  - **K-w:** "The corruption at the lowest window-2 canary also appears when the same watcher image is entered from UEFI, with no Linux in that power cycle. Kill condition 1 stands for this range. The writer is not identified."
  - **E, c3 clean:** "The corruption did not appear in two UEFI-entry runs of the same watcher image. It needs the kexec entry path's state; the cause within that path is not identified, and a writer at that address that this state switches on is not excluded. This is not a range verdict, and B2 stays not met."
  - **E, c3 hit:** "The corruption at the lowest window-2 canary did not appear in two UEFI-entry runs of the same watcher image; a small write at another window-2 canary did, so the entry path does not explain every hit. The cause is not identified. This is not a range verdict, and B2 stays not met."
  - **K-o:** "The firmware's own memory map does not show the second window as free RAM at the UEFI Shell. Kill condition 1 stands on that map; no writer is shown."
  - **K-r(u):** "The lowest window-2 canary reads back unstably under UEFI entry. The range is not usable under either entry; no writer is shown."
  - **U:** "Unresolved."
- **Never in public text:**
  - any count, offset, address, descriptor type, reserved-memory node or register value read in a run;
  - `self=`, `ctr=`, the tree's address, size or CRC;
  - a hash of a private record or build output; a `boot_id`; a duration; a free-space or file-size figure;
  - the loader or kimg bytes, a capture, a key log or a snapshot;
  - a MAC or drive identifier;
  - the K-w sub-labels, before D31 allows them (D44);
  - "firmware bug", "NVIDIA firmware writes", "QNX writes", "UEFI entry is clean", "kexec is broken" or "fixed", except a named cause labelled HYPOTHESIS;
  - anything softening "NOT MET, on data".
- **May be stated** (§15.4.6 precedent): run counts, and the clean-run probabilities worded as "the chance of one or two clean runs if entry has no effect, under a uniform prior over four exchangeable bad runs", with the caveat that those runs used two images.
- **Licence:** no figure before the 4.6(i) consultation; no QNX binary or `.efi` committed.

---

#### 15.13.17 What J7a does not show

- **The writer's identity.** K-w covers H2 (a firmware, secure-world or coprocessor user of the address), H5 (QNX-side), a fixed-address hardware writer, and UEFI-driver residue outside its reported buffers (R82). Only `anchored` makes the address reading, and even then J7e and J7c are still needed. A UM9 node over c2 is a lead, not an identification.
- **Which kexec-path state causes E.** GPU residue (H1), coprocessor or BPMP/EMC activity triggered by Linux's run or shutdown, the L4T boot option, PSCI `CPU_OFF` history, uptime and thermal state, clock or frequency state, and the kexec tree against the firmware tree are not separated. **E does not exclude an address-anchored writer that one of these switches on.** Nor does E show that any allowed quiesce could fix it.
- **That startup's fill landed on every canary page.** The fill has no read-back; a bad reading with Linux-like content leans on `DRAM_OFF_S` (R95), not on a check.
- **That only the entry path changed** (§15.13.2's confounds).
- **DMA quiescence under UEFI** outside the three canaries and the hold's pigeonhole coverage (R70, R75, R82), or with the Ethernet cable and USB devices fitted.
- **Anything about firmware memory after `ExitBootServices`** beyond the final map's types at the exit (UM6), and any reserved-memory user the tree does not declare.
- **That UEFI entry is valid for S1-F.** `s1-j1` is a host-mode diagnostic with no qvm. Freeze item 3 is not decided, and B2 stays NOT MET on data under every outcome.
- **Repeatability** beyond the runs made. Two clean runs bound the risk of a false E and do not remove it. One bad run shows a writer without Linux in that run, not its rate.
- **The window-1 exposure under kexec.** J7a watches window 1 with no Linux only.
- **Timing, isolation, containment,** anything about the GPU or a Linux guest.
- **No evaluation figure is publishable** before the 4.6(i) consultation.

---

#### 15.13.18 Where the four analyses disagreed, and what this design chose

| # | Point | Options in the analyses and reviews | Chosen | Why |
|---|---|---|---|---|
| 1 | Window-2 check | blob-only rebuild; blob plus the Shell's `memmap` read by a human; a loader rule behind a switch; that rule plus a canary pre-claim, a final-map re-check and a self refusal | **The switch, with the window-2 rule, the tree rule and CRC, the pre-claim, the final-map re-check, the reserved-memory report and release on every return (UM1-UM10)** | Machine-enforced at the moment of `go`; the pre-claim turns "free when checked" into "free and ours until the exit"; the re-check certifies the final map at no boot-services call; the switch-off object is unchanged |
| 2 | A canary held by Loader* or BootServices* at Shell time | refuse (firmware); proceed with a map label `l` or `f` (rules) | **Refuse: F51, or F54 when it is our own image** | A bad c2 under a firmware allocation cannot separate UEFI-driver residue from an anchored writer at that canary. The refusal costs no `go`, the case is unlikely (R79), and the descriptor is itself a lead. **This does not stop a live device writing a free canary after the exit (R82);** that residual is handled by the profile gate (`anchored` needs P1, P2 and P7 same) and D46, not by the refusal |
| 3 | The loader's own image in window 2 | refuse (firmware); informational (UEFI path) | **Informational, `M5L self w2=`; over a canary, F54** | Nothing runs from it after the branch, and startup's claim reuses it; over a canary the pre-claim refuses, and F54 names it as a loader problem, not a firmware finding |
| 4 | The tree rule | overlap with a canary only (rules); overlap with window 2 (UEFI path, firmware) | **Window 2 as a whole, plus c1** | `avoid_ram` does not keep the tree out of sysram (C15, `main.c` VERIFIED), and the hold covers most of window 2 |
| 5 | Image | `s1-j1` (all); harness support for `s1-h1` too | **`s1-j1` only** | One variable against J6c; the profile items need the watcher; less harness surface |
| 6 | The ESP file name | keep it; rename and change the terminal's detector | **Keep `M5LOAD.EFI`, identified by sha256** | No terminal change and no new pin; the self-test already covers the name |
| 7 | Deciding rule | §15.6's single J7a result each way; K-w on one bad and E on two clean (rules); K-w's anchored reading tied to the profile (power review) | **Asymmetric, amended before any J7a result (D38), with `anchored`, `differs` and `partial`** | A bad run is positive evidence that Linux is not needed; only a matching page set and anchor support "anchored at the address". One clean run has about a one-in-six chance if entry has no effect, two about one in twenty |
| 8 | What counts a run | reaching `M5L GO` (harness); reaching `procnto up` (rules) | **The exit attempted: `M5L-EBS ok\|FAIL`, or `M5L GO` with neither a refusal nor a prompt for 10 s. F55 and F62 are counted** | The exit is the irreversible step; a first-try `w2-final` returns to the Shell and is not; counting F55 and F62 prevents open-ended retries |
| 9 | Budget | the owner rules (UEFI path); outside the kexec count (rules) | **Outside the kexec count, with J7a's own cap of two, by D38** | J7a is not a kexec run; the cap keeps the revision bounded |
| 10 | Control cold boot | keep (UEFI path, harness); optional (rules) | **Keep, and merge it with the TX refit on an unpowered board** | It tests autoboot with the new wire before any attended menu, gives the variable control, and avoids fitting a wire to a live header |
| 11 | Terminal sessions | one per power cycle, switched while L4T is up (harness) | **One per board session, with per-phase segments by byte offset, offset-aware gate A** | M5 §7.4 then needs no exception; fewer operator actions |
| 12 | The Shell's `memmap` | required (harness); optional (firmware); forbidden as a memory read (rules) | **Optional, record only (D43); `dmem` and `mm` never** | `memmap` lists descriptors, not content; it predates the loader's allocations, so it cannot be a gate |
| 13 | Cut hold after the shim | 10 minutes of silence (UEFI path); `return_bound_s` plus 300 s of silence (harness); `return_bound_s` plus 600 s and 10 minutes of silence (rules) | **`go` + `return_bound_s`, then 10 minutes of silence** | The watches and the hold are silent by design, and the hold's dwell bound itself reaches 10 minutes, so the silence rule is safe only after the return bound, which covers the run |
| 14 | New classes | none (UEFI path, harness); K-o and K-r(u) (rules) | **Both, K-o by D41** | A non-free Shell-time map in window 2 and unstable reads under UEFI are both pre-registerable outcomes the existing classes cannot name |
| 15 | Harness shape | separate `j7a-*` commands (UEFI path); one `j7a` command with phases (harness) | **One `j7a` command with phases and exit codes 6 and 7** | Resumable phases sharing one attempt id; clean budget and advice keys |
| 16 | Loader wait bounds | 10 s (M5); 120 s for `check` only (draft); one bound for both launches, measured per silent stretch (reviews) | **`LOADER_EXPECT_S` per silent stretch for `check` and `go`, `LOADER_CUT_S` before any cut, `PROMPT_AFTER_S` only after a completed loader run** | The Shell's load and the loader's copy are silent for both launches; a slow valid load must never draw a cut |
| 17 | `efibootmgr -v` in records | raw, as M5 (UEFI path); hash plus structure (harness) | **Hash plus structure** | Its descriptions carry identifiers the regex classes cannot all name (P5) |
| 18 | Build location | an output-directory override (harness); a worktree (UEFI path) | **A worktree, kept until J7a's record is written** | No build-script change beyond the switches; M5's gated output untouched |
| 19 | Extra prints (GPU range summary, `/reserved-memory` walk, the Shell's `drivers`) | optional (firmware); reserved-memory walk required (power review) | **The reserved-memory walk as UM9, informational; the GPU summary and `drivers` not in J7a** | E13 puts `camdbg_carveout`'s allocation range at window 2's base, exactly c2's base, and a disabled or allocation-range node is invisible to the EFI map. The walk reuses the tree parser, reads nothing but the tree, and never refuses |
| 20 | Where the loader is loaded from | the SD ESP root (draft); `~` on the APP rootfs, which M5's Shell mapped as a filesystem (safety review) | **The ESP (D45)** | (1) M5 VERIFIED the Shell loading our PE from FS5 on this firmware; FS4 was mapped and never listed or loaded from (VERIFIED (private record)). (2) The typed path under `~` would carry the user name, echoed on COM3 and hex-encoded in the key log, which text redaction cannot mask and the allowlist would have to contain; a neutral directory outside `~` is a rootfs write rule 5 forbids. (3) Whether the Shell's ext4 driver is strictly read-only, including journal handling, is unread (HYPOTHESIS); a driver write would be a worse rule-5 breach than one ESP file with a verified hash and removal. (4) The ESP holds the file once with `ESP_MARGIN` (class only), and `b_esp_stage` now handles partial writes. Residual ESP risks: a near-full FAT ESP during the session, and a write before planned cuts, bounded by `sync`, read-back and ordered phases. If F65 ever holds, the rootfs route is the recorded alternative, by a reviewed amendment |
| 21 | Loopback test before the refit | on the bench with TX jumpered to RX (draft); detach RX and GND, loopback, refit three pins (safety option a); self-test plus control boot as M5 (safety option b) | **Option (b)** | Jumpering TX to RX while RX is on J14 contends with the board's TCU TX; option (a) adds a three-pin rewiring with its own F36 risk. M5's self-test, control boot and P3 typed input covered the key logic, autoboot with the wire, and framing in use |
| 22 | A refusal in `go` | one more `check` and `go` in the same Shell visit (draft F53); `reset` and a new session (reviews, m5-design D11) | **SHELL-AFTER-GO: arm once, `reset`; not counted; no repeat in the session** | The terminal disarms after each Enter; the retry contradicted M5 §5.3 and D11; and a later-try refusal must never return to the Shell at all (UM6) |

---

#### 15.13.19 Pointers to add later (list only; the orchestrator edits)

- §15.4.9's J7a row: "designed in §15.13 (D35-D47)".
- §15.6's K-w, E and U rows, and its immediate stops: §15.13.10.6's dated appends. K-o and K-r(u) added.
- §2 rule 5 and rule 6a, and §8 item 10: one dated J7a pointer line each (X1-X7).
- §3.2's UEFI row: "used diagnostically by J7a; D6 unchanged".
- R67: refined by R80-R82, R87 and R95.
- m5-design §3.3 step 7's "startup reserves it (board/main.c:247-248)": current `main.c` only calls `avoid_ram` for the tree (§15.13.3's contradiction). m5-design §8 item 11's "room several times over" does not hold for a J7a-sized loader.
- m5-design §6.6 and its gate record: **the loader staged in M5 was built before commit `600996f`**, which changed `m5load.c`'s tree refusal tokens (VERIFIED: file time against commit time, and the diff). M5's pass printed none of them, so the record stands, but "the committed source is the staged loader" needs a dated note once D0a names the reference.
- m5-design §3.3 step 10: M5's retry loop calls `AllocatePool` after a failed `ExitBootServices`, which UEFI's rule does not allow. It never ran in M5 (the first exit succeeded). UM6 avoids it under the switch; the switch-off loop is unchanged.
- m5-design's `wdt.c` text "did not fire after the kexec hand-over" is printed under any entry; its wording is entry-specific.
- `com3-term.ps1`'s header on straight-typed lines, and m5-design §14.8's other stale items: still open.
- The plan's freeze gate item 3 and §8 unknown #6: the class line after D31.

---

#### 15.13.20 Review outcomes

Three reviews read the draft: safety (RS), power of the reading (RP), feasibility (RF). Every required change is listed with what happened to it.

##### 15.13.20.1 Conflicts between reviewers, and how they were resolved

| # | Conflict | Resolution |
|---|---|---|
| K1 | RS6 asks to weigh loading from the rootfs; RF8 asks that a short ESP means J7a cannot run, with no other location | Both honoured: the rootfs route is weighed (§15.13.18 row 20) and not chosen; at the board there is no other location (F65); the rootfs route stays reachable only through a reviewed amendment (D45) |
| K2 | RS1 asks for a new TCU token (`M5L-W2FINAL FAIL`) on a later-try re-check failure; the draft and RF keep `m5load-head.S` and gate item 9 unchanged | The later-try failure takes the existing MODE_EBS_FAIL path (`M5L-EBS FAIL`, reset), counted S under F55. The new token is rejected: it needs a new trampoline mode in the head. COM3 cannot tell the two causes apart, and the record says so |
| K3 | RS4 asks for one bound of at least 120 s and an F9 rule only after a completed run; RF1 asks for bounds per silent stretch and an F9 silence rule at least that bound | `LOADER_EXPECT_S` per silent stretch (expectation, never a cut), `LOADER_CUT_S` of no byte before a completed run (the first cut point), `PROMPT_AFTER_S` only after a completed run. This satisfies both |
| K4 | RS2 offers "drop the retry, or a dated exception to D11"; RF2 offers "drop the retry, or an explicit re-arm rule" | The retry is dropped. RS3's SHELL-AFTER-GO supplies the only re-arm: one F12 and `reset` |
| K5 | RS12 pre-registers the count of a WDT-type reset; RF3 requires a desk read before D35 that may change the image | Combined: Q20 before D35 with branches (a)-(c); F62 counted in every branch; no retry of the unchanged image (D42); branch (b) goes to D47 |
| K6 | RP1 lets J7a-2 run after a bad first run whose profile differs; the draft stopped at any bad first run, and RS left the stop rules alone | J7a-2 runs after `differs` or `partial` within the cap, and never after an immediate stop; `anchored` and K-r(u) still end J7a |
| K7 | RS11 asks for redaction that handles CSI in key-log-adjacent screens; RF4 shows key-log copies cannot be redacted at all | COM3 segments are redacted on CSI-normalised text; key logs are protected by the allowlist check instead, and their copies are labelled unredacted |

##### 15.13.20.2 Every required change

| ID | Sev. | Change asked | Outcome | Where |
|---|---|---|---|---|
| RS1 | blocker | UM6's return to the Shell only before the first `ExitBootServices`; a later-try failure resets; class and count defined; F53 and COUNTED rewritten; T0 case | **Applied, except the new TCU token** (rejected: it needs a new mode in `m5load-head.S`, which gate item 9 pins; K2). Also added the retry discipline: the buffer is allocated once, and only `GetMemoryMap` and `ExitBootServices` are called after a failed exit | UM6; F53, F55; §15.13.7 COUNTED; T0l |
| RS2 | major | every refusal in `go` frees claims, target and pool; drop the same-visit retry or justify it; T0 case | **Applied** (retry dropped) | UM4, UM10; F53; §15.13.11; T0f′, T0l |
| RS3 | major | SHELL-AFTER-GO state, rule, power row, self-test | **Applied** | §15.13.6; §15.13.7 states; §15.13.9; F61; §15.13.15 |
| RS4 | major | one loader-silence bound of at least 120 s; 60 s rule only after a completed run; re-derive `M5L GO`'s bound | **Applied** (K3) | UM7; §15.13.6.1; §15.13.9; F63 |
| RS5 | major | no TX-to-RX jumper while RX is on the board: option (a) or (b) | **Applied, option (b)** | X5; J7a-bench; D40; §15.13.15; §15.13.18 row 21 |
| RS6 | major | a row weighing the rootfs route; record why if the ESP stays | **Applied as analysis; the route is not adopted** (K1) | §15.13.18 row 20; D45 |
| RS7 | major | `b_esp_stage` with margin, removal on failure and S0 check; `clean` with a mismatched hash stops, the owner authorises removal by name; self-tests | **Applied** | §15.13.7 `b_esp_stage`, `b_esp_clean`; F65, F66 |
| RS8 | minor | E's exclusion applies to counted runs, not to a retried earlier refusal | **Applied** | §15.13.10.4 E; §15.13.10.6 |
| RS9 | minor | correct the "no watch bound reaches 10 minutes" rationale | **Applied** | §15.13.9 shim row; §15.13.18 row 13 |
| RS10 | minor | T0h-T0j as "any named refusal, never CHECK PASS" | **Applied** (T0d as well) | T0 table |
| RS11 | minor | CSI normalisation in `redact` and `ident_hits`; region masking; replay over menu segments; synthetic CSI-split MAC | **Applied;** the replay also covers M5's P2 | §15.13.7 Privacy; R91 |
| RS12 | minor | pre-register whether a non-MAINSWRST reset after `procnto up` counts | **Applied** (counted, F62; K5) | §15.13.10.2, .5; F62; D42 |
| RP1 | major | tie the anchored reading to the profile; K-w(differs) allows J7a-2; remove Ethernet and USB devices | **Applied, with one adjustment:** the adapter is on the PC, so the board's USB ports are emptied; the M.2 wireless card stays because it carries ssh (D29) and is not removable, recorded as R96 | §15.13.10.3-4; §15.13.11; D46; R96 |
| RP2 | major | P7 page-set overlap with a pre-registered threshold; hash J6c's exports | **Applied** | §15.13.10.3 P7; §15.13.8 prereg; parser self-tests |
| RP3 | major | UM9, a read-only reserved-memory walk, informational; R94; name `camdbg_carveout` | **Applied** | UM9; §15.13.2 H2 row; R94; §15.13.18 row 19 |
| RP4 | major | add boot option, PSCI history, uptime and thermal confounds; E does not exclude an anchored writer; rephrase §15.13.1 | **Applied** | §15.13.1; §15.13.2; §15.13.10.4 E; §15.13.17 |
| RP5 | major | DC-off wait of minutes, recorded; "fill not landed" as an alternative reading; P7 same does not break that tie | **Applied** (`DRAM_OFF_S`, R95) | §15.13.6, .6.1; §15.13.10.3; §15.13.17; R95 |
| RP6 | minor | one rule for c2 bad at a printed check in an incomplete counted run | **Applied** (`bad-partial`, K-w `partial`) | §15.13.10.1-4 |
| RP7 | minor | an E sentence for `c3=hit` | **Applied** | §15.13.16 |
| RP8 | minor | reword the "false-E estimate" | **Applied** | §15.13.2; §15.13.16; §15.13.18 row 7 |
| RF1 | blocker | one load bound for both launches, per silent stretch; F9 silence at least that bound; self-tests | **Applied** (K3) | UM7; §15.13.6.1; §15.13.9; harness self-tests |
| RF2 | blocker | every return frees claims, target and pool; drop the retry or add a re-arm rule; the parser counts only a GO not followed by `w2-final`; T0 case | **Applied** (retry dropped; K4) | UM10; F53, F61; parser counted-GO rule; T0l |
| RF3 | major | Q20's desk read of the CR values before D35; a pre-registered branch; R85 depends on it | **Applied** (K5) | §15.13.4 WDT0 row and branch; R85; Q20; D47 |
| RF4 | major | Never: typing while L4T is on COM3; a key-log allowlist check; plain copies; self-test | **Applied** | operator rules; §15.13.7 P12 and allowlist; F59, F64; §15.13.15 |
| RF5 | major | offset-aware gate A and gate B; parser on the segment only; drop or re-cite the uptime gate | **Applied for gate A, the parser and the uptime gate (dropped). Gate B is unchanged,** because no `j7a` phase calls it and no kexec rung may use a J7a capture | P10, P11; §15.13.15 |
| RF6 | major | rebuild at `600996f^` and `600996f` to find D0's reference | **Applied** (`600996f^` is `25d40e7`, VERIFIED) | §15.13.4 D0a, D0b; §15.13.19 |
| RF7 | major | split F51 from the loader's own image over a canary; say what "exactly our claim" is checked against | **Applied** (`self … canary=` line; F54 extended; claim success replaces "exactly") | UM2, UM4, UM5; F51, F54; §15.13.10.5 |
| RF8 | major | a fixed margin constant; `j7a pre` refuses early; pre-registered outcome; ordered stage and cut | **Applied** (`ESP_MARGIN`; F65; K1) | §15.13.6.1; P4; `b_esp_stage` |
| RF9 | minor | one place for `variant=j7a`, consistent everywhere | **Applied with the other form:** a separate line directly after the start line, so the start line's grammar stays identical in both builds and the check and go preludes stay equal | UM2; parser; T0b |
| RF10 | minor | allow one pure header for the rules, or make T0u a reviewed reading; name the pointer and `.bss` constraints | **Applied** (`m5load-rules.h`) | §15.13.4 loader source change; T0u |
| RF11 | minor | no raw segment in the record directory, even briefly; record range and hash; self-test | **Applied** (pipe or an outside `mktemp` with an EXIT trap) | §15.13.7 P13, offsets and segments; self-tests |

**Rejected outright:** none. **Rejected in part:** RS1's new token (K2); RS6's route, kept as analysis (K1); RF5's gate-B change (not reached by any J7a phase); RP1's "every USB device except the adapter", adjusted to the board's ports with the wireless card recorded; RF9's suggested placement on the start line.
