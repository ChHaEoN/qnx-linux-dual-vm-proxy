# M3 design: the QNX Hypervisor host natively at EL2 on the Jetson Orin Nano, booting the byte-identical cloud-leg guest

Phase 3b. Architect pass, revision 2, 2026-09-10: revision 1 plus three reviews, with the outcomes in §12. This is a read-and-reason design: nothing in it has been built or run. It follows the structure and failure-handling rules of [m1b-design.md](m1b-design.md) and [m2-design.md](m2-design.md). Both ladders passed with no failure signature ([m1b-runs.md](m1b-runs.md), [m2-runs.md](m2-runs.md)).

**Path prefixes used below**
- `lib/` = `C:/Users/<user>/AppData/Local/Temp/orin-native-port-bsp/src/hardware/startup/lib/` (Apache-2.0)
- `board/` = `orin-native/startup/t234-orin-nano/`; `startup/` = `orin-native/startup/`; `tools/` = `orin-native/tools/`; `shim/` = `orin-native/shim/`; `qhvconf/` = `orin-native/qhv/`
- `qhvg/` = `qhv/guest/output/build/`; `qhvh/` = `qhv/host/output/build/`. These are local, git-ignored, QNX-generated **text** build files (.gitignore:16); only text was read.
- `sdp/` = `C:/Users/<user>/qnx800/target/qnx/aarch64le/` (file sizes only); `sdpinc/` = `C:/Users/<user>/qnx800/target/qnx/usr/include/`
- `logs/` = `logs/sample-boot/`; `m1blog` = `logs/sample-boot/orin-native-m1b-el2-host.log`; `plan` = `docs/orin-native-port-plan.md`
- Reader reports: GUEST_CONFIG, NATIVE_QVM_HOST, MEASUREMENT, BOARD_PROCEDURE. All four arrived; none was null.

**Evidence classes:** VERIFIED (read in source, a build file or a log, or computed on this PC; cited), VENDOR_CLAIM (QNX or Arm documentation; URL given), HYPOTHESIS, UNKNOWN.

**Licence status:** every log these runs produce is evaluation output under NC QDL v7 4.6(i). Keep it private until the supervising professor has been consulted.
- No QNX-shipped binary is disassembled or inspected anywhere in this design. The guest IFS, the guest disk image, qvm, the vdevs and the libraries are handled only as opaque files: sizes, sha256 and md5 hashes, copies into our own IFS, and extraction of those same files back out of our own IFS to hash them.
- No QNX artefact goes to a tracked path. Images go to `shim/out/m3/`, which is git-ignored (.gitignore:83).

**QNX documentation cited** (all VENDOR_CLAIM, QNX SDP 8.0, fetched 2026-09-10; base `https://www.qnx.com/developers/docs/8.0/`):
- **hypervisor:** [pl011] `com.qnx.doc.hypervisor.user/topic/vdev_ref/vdev_pl011.html`; [unsupported] `…/vm/unsupported.html`; [cpu] `…/vm/cpu.html`; [ram] `…/vm/ram.html`; [logger] `…/vm/logger.html`; [vdev] `…/vm/vdev.html`; [errcodes] `…/debug/errcodes.html`; [qvm-check] `…/utils/qvm-check.html`; [shmem] `…/vdev_ref/vdev_shmem.html`
- **utilities:** [waitfor] `com.qnx.doc.neutrino.utilities/topic/w/waitfor.html`; [if_up] `…/i/if_up.html`; [devb-loopback] `…/d/devb-loopback.html`; [io-blk] `…/i/io-blk.so.html`; [pipe] `…/p/pipe.html`; [devc-pty] `…/d/devc-pty.html`; [mkifs] `…/m/mkifs.html`; [dumpifs] `…/d/dumpifs.html`; [slay] `…/s/slay.html`; [startup_options] `…/s/startup_options.html`
- **building:** [callout_reset] `com.qnx.doc.neutrino.building/topic/callouts/callout_reset.html`

---

## 0. Summary

M3 runs the QNX Hypervisor host (`qvm`) natively on the board. It uses the M1b startup build (sha256 `90bf724c…61896`) with no code change, at `-Q enable,el2-host`. The host boots the cloud-leg guest IFS (sha256 `968029316b940f53580228f44e393877e032e251d78f3c752600cae726a7cf4f`), attached to its unmodified disk image (sha256 `cf5b06d0b3cb524201c71440fdda42a18d2636d45938acd8ec95cfa21314216b`). The host takes a `ClockCycles()` reading when qvm is launched and another when the guest banner arrives, then runs the Phase-2 IPC pair over the virtio-console pty.

**What changes against the plan's M3 (plan:364-379), and why:**

1. **The guest disk goes back in.** `qhvconf/g2-noblk.conf` rests on "the banner does not need a disk" (:9-14), and that premise is false (§1 C1, VERIFIED from the build files):
   - The banner is the output of `uname -a`, which exists only as `/system/bin/uname` on the disk (qhvg/system.build:197). The IFS's toybox links do not include it (qhvg/ifs.build:72-80).
   - The hostname `qnx-guest` is set from `/data` (qhvg/data.build:72-73, qhvg/start_net.sh:10-12).
   - The echo server is launched only by `/system/etc/startup/post_startup.sh` (qhvg/system.build:35).
   - Without the disk, the guest can print `Startup complete` but never `QNX qnx-guest`, and the IPC pair cannot run.
2. **The guest configuration is the one the timed TCG series actually ran, with one host-side substitution.** That configuration is the build-tree text (qhvh/post_startup.sh:50): pl011, virtio-console, virtio-blk and an inert shmem vdev. The only change is the load path, `/proc/boot/guest-ifs.bin`. The virtio-blk `hostdev /dev/qvmdisk0` stays unchanged, because devb-loopback keeps its `prefix=qvmdisk` (§3.3).
3. **The disk rides raw in the IFS.** At boot it is copied to `/dev/shmem`, checked with `cmp`, and served by `devb-loopback` with the cloud host's own command line (qhvh/post_startup.sh:48); only the backing path differs. Every boot therefore starts from the same pristine bytes, the native equivalent of QEMU's `-snapshot` (§3.4).
4. **The banner is read from qvm's stdout, not from `/dev/ttyp0`.** It travels on the guest pl011, which the configuration binds to qvm's stdout (`hostdev >-`); `/dev/ttyp0` is the IPC channel.
   - qvm's stdio goes to pty pair 1. A revised `stamp` reads the master, stamps nine guest markers into a `/dev/shmem` file, and writes nothing to the console while the timed window is open.
   - No pipe is used, and the configuration text is untouched (§3.8, §4.1).
5. **Every wait is bounded, and every path ends in a warm reset.**
   - The host logic is a ksh state machine. Each wait is our own bounded `bwait` (new, `tools/bwait.c`).
   - A 900 s guard, started as the IFS script's first program, calls `sysmgr_reboot()` if anything outlives it.
   - The script ends in `shutdown -S reboot`.
   - `-A` joins the startup line (owner decision O3). It turns a host-kernel abnormal termination into a PSCI reset, where today the reboot callout would spin with interrupts masked (lib/aarch64/callout_reboot_psci.S:42-58, VERIFIED).
6. **Nothing in startup changes.** Memory is estimated at about 111 MiB of headroom inside `-m992M` (§3.5, HYPOTHESIS). R0 measures it before any qvm run. A startup change (a second RAM window) is specified only as a last contingency.
7. **Measurement choices.**
   - **Placement:** the host runs at `-P4`: cluster 0 only, one cpufreq policy, the vCPU floating inside it (owner decision O2).
   - **Frequency:** "clock not verified" unless measured. The record carries the Linux governor pin, the pre-kexec sysfs readings, and a QNX busy-rate proxy taken before and after (§4.3).

**Run ladder** (§6):

| Step | Image | Purpose |
|---|---|---|
| P0 | none (no reboot) | Board pre-flight reads; `kexec -s -l` / `kexec -u` acceptance of the ~169 MB kimg |
| P1 | none (no kexec) | DMA quiesce rehearsal and checklist 11c. Only if O4 is adopted |
| R0 | `m3-r0` (harness) | Tests the whole M3 image except qvm: big-kimg landing, `-P4` el2-host, memory, disk copy, devb-loopback, qvm-check. Fake guest text through the pty tests the stamps, waiters, kill path and black-box budget |
| R1 | `m3-r1` (boot) | First qvm launch: the guest boots with its disk to the banner. No IPC |
| R2 | `m3-r2` (full) | Qualification run Q: banner plus IPC. Not counted |
| T1-T5 | `m3-r2` (the same kimg) | The five timed runs |

**What a pass settles:**
- On this silicon and firmware, the QNX 8.0 hypervisor host at EL2 (VHE, `el2-host`) arms stage-2 translation and virtual interrupt and timer delivery well enough to boot the unmodified cloud-leg QNX guest to its banner, 5 times out of 5. That is plan unknown #5 (plan:444).
- The virtio-console IPC pair crosses the native partition boundary for its 15 timed iterations.
- It produces the first hardware-timed `qvm_launched → guest_banner` interval with its spread.
- It directly measures the guest's `if_up` retry burn on this host, which the TCG legs never measured (§1 C7).

**What the number is:** the interval from the host-clock reading taken in the process that then `execv`s qvm, to the host-clock reading taken when the last byte of `QNX qnx-guest` reaches the host reader. It is read at 32 ns resolution (31,250,000 cycles/s) and recorded with every field §4.6 lists.

**What it is not:**
- not a per-exit or world-switch latency (M4);
- not the twin's full launch-to-banner headline, which includes a host boot that is not comparable;
- not a host-only or one-variable diff against either TCG leg, because this is a third host bundle (plan §7 item 6);
- not a guest boot time, since several fixed guest timeouts sit inside it;
- not taken at a known CPU frequency.

---

## 1. Inputs and contradictions resolved

All four reader reports arrived. Every item this design rests on was re-read in the cited source, build file or log. Items that could not be checked keep the reader's class and say so.

| # | Contradiction or defect | Resolution | Evidence |
|---|---|---|---|
| C1 | **Does the banner need the disk?** `g2-noblk.conf:9-14`: no. Orchestrator finding 2 and NATIVE_QVM_HOST F3: the banner "probably still appears", only after a timeout. GUEST_CONFIG F2, MEASUREMENT M3-01 and BOARD_PROCEDURE F2: no banner at all. | **No banner without the disk.** The guest IFS script runs `startup.sh`, then `display_msg "Startup complete"` and `uname -a` (qhvg/ifs.build:57-61), with PATH `/proc/boot:/system/bin` (:20). The IFS toybox links are only cat, chmod, dd, echo, ln, ls, rm and grep (:72-80). `uname` is a toybox hlink on the system partition (qhvg/system.build:197). Without `/dev/hd0` (a 5.0 s default `waitfor` [waitfor], qhvg/startup.sh:27), `mount_fs.sh` fails and startup.sh exits 1 at :31-34. What the IFS script prints when `uname` cannot be found is UNKNOWN. The hostname comes from `/data` (qhvg/data.build:72-73; qhvg/start_net.sh:10-12). The echo server is started only from the disk (qhvg/system.build:35; qhvg/post_startup.sh:23-32). **M3 carries the disk.** `g2-noblk.conf` becomes diagnostic image D2 only, with marker `Startup complete`. | Build files as cited. VERIFIED. Runtime text UNKNOWN |
| C2 | **Which configuration is "the cloud leg's"?** The plan and `g2-noblk.conf:3-7` point to the committed `scripts/qhv/post_start.custom:33` (three vdevs). GUEST_CONFIG F1 and MEASUREMENT M3-02: the timed series ran a fourth vdev, `vdev shmem`. | **The timed series ran four vdevs.** The build-tree `qhvh/post_startup.sh:50` adds `vdev shmem / loc 0x1c0f0000 / intr gic:43 / allow phase2-rq2-probe`. That script's unique skip line (:44) appears in `logs/windows-qhv-tcg-boot-timed1.log:75` and `logs/orin-qhv-tcg-q111-rng-snapshot-boot1.log:21`. The guest never attaches to the shmem vdev: `gshm-probe` is not in its IFS (qhvg/ifs.build:164-169), and the log prints the skip line (`windows-qhv-tcg-boot-timed1.log:115`). Checklist 7 (plan:538) diffed against the committed file. **The M3 configuration is the as-run text** (§3.3). Using the three-vdev text instead is owner decision O1. | VERIFIED |
| C3 | BOARD_PROCEDURE rec 1 and MEASUREMENT rec 1: two host-side substitutions, the load path and the virtio-blk hostdev. | **One substitution.** `devb-loopback … prefix=qvmdisk` creates `/dev/qvmdisk0` on both legs, so `hostdev /dev/qvmdisk0` is unchanged. Only `load /data/hypervisor/guest/ifs.bin` becomes `load /proc/boot/guest-ifs.bin`. | qhvh/post_startup.sh:48-50. VERIFIED |
| C4 | The plan's M3 contradicts itself: the image is "minus virtio-blk" (plan:369), yet the pass needs "the IPC pair completes its 15 timed iterations" (plan:377-379). | Resolved by C1. The plan text is stale (Appendix A). | VERIFIED |
| C5 | **Where the banner travels.** `stamp.c:17,22` shows `stamp -s 'QNX qnx-guest' < /dev/ttyp0`. | **pl011 to qvm stdout, not the pty.** The guest prints `uname -a` before `reopen /dev/vcon1` (qhvg/ifs.build:61-63). The QNX-generated stock guest.conf binds the PL011 to qvm stdout with the comment "startup uses the PL011" (qhvh/data.build:113-116). On TCG the banner reached the serial capture while nothing held `/dev/ttyp0` open: `windows-qhv-tcg-boot-timed1.log:78-121` falls inside the host's `sleep 90`. **The stamp reads qvm's stdout** (§4.1). | VERIFIED |
| C6 | **How to get qvm's stdout to the stamp.** NATIVE_QVM_HOST: `ksh -c 'qvm … \| stamp'`, which needs the pipe manager and has an UNKNOWN buffering risk. GUEST_CONFIG: `hostdev >/dev/ptyp1`, which changes the configuration. BOARD_PROCEDURE: `on -t /dev/ttyp1 qvm`. | **A ksh subshell redirects stdio to `/dev/ttyp1`, and the revised stamp reads `/dev/ptyp1`.** The configuration keeps `hostdev >-` byte for byte, stdout is a tty, and no pipe is involved. qvm's output was not held back on TCG: `Startup complete` and the banner were timed within 0-110 ms of each other while qvm kept running (`logs/windows-qhv-tcg-q111-rng-snapshot-segments-boot-times-n5.txt:15-24`), with about 900 B of guest text before the banner. Whether that holds on a pty is still HYPOTHESIS; R0 and R1 test it. | [pl011] (hostdev forms, `batch` with no stated default); [devc-pty] (8 pairs by default). VERIFIED TCG observation |
| C7 | **How long the guest's `if_up -p -r 20 vtnet0` takes** (qhvg/start_net.sh:3). The docs: 20 walks of the interface list, 1000 ms apart by default, so about 19-20 s. `docs/findings.md:266-274`: it must be short, inferred from TCG ratios, "not measured directly". | **Unresolved; M3 measures it.** Stamps `g_net` (`---> Starting Networking`), `g_ifup` (`if_up: tries exhausted`) and `g_sshd` bracket the burn (§4.1). If the documented defaults hold, the TCG guest compute would be about 2.5 s on Windows against about 28.5 s on Orin (11×), while their host-boot ratio is 2.2× (`findings.md:259-264`). That tension is recorded, not resolved here. | [if_up]: `-r` "default is 5", `-m` "default is 1000 ms", `-p` waits "only until the specified interfaces are present". VENDOR_CLAIM vs VERIFIED arithmetic |
| C8 | MEASUREMENT M3-08: the guest's `/data` ships no ssh host keys, so they are generated every boot at a random duration. | **Refuted.** The guest `data.build:84-85` stages both host keys, `OPT_SSHD_PREGEN='yes'` (qhv/guest/local/options:89), and `startup.sh:51-58` skips `ssh-keygen` when the keys exist. | VERIFIED |
| C9 | `ipc-test/qnx-server/server.c:15-16` and `ipc-test/qnx-host-client/README.md:80` say `/dev/vcon1` is the guest's pl011 console. | **Wrong.** `/dev/vcon1` is `devc-virtio -e 0x20000000,42` with a login `ksh -l` on it (qhvg/startup.sh:16,18). The echo server's `/dev/vcon2` is a **second** `devc-virtio -E` on the same virtio-console (qhvg/post_startup.sh:24). Two drivers on one device is a concrete, untested candidate for the first-exchange stray bytes and the stall (HYPOTHESIS). The guest stays byte-identical, so M3 inherits this and records sentinel counts. | VERIFIED build files; cause HYPOTHESIS |
| C10 | **Host CPUs.** MEASUREMENT: `-P4`. BOARD_PROCEDURE: `-P6` with qvm under `on -R 0xf`. NATIVE_QVM_HOST: `-P6`, recording placement. | **`-P4` (owner decision O2).** At `-P6` the vCPU can land on the cluster-1 cores, which ran at a fixed 57.0-57.1 M it/s against 363-666 M on cluster 0 (m1b-runs.md:157-162; m2-runs.md:102-112). The 8.0 `cpu` page documents only `cluster` and `sched`, and whether qvm's vCPU inherits an `on -R` runmask is UNKNOWN. `-P4` removes cluster 1 from QNX with the configuration untouched. `m1b-p4` was built and never run (§6.6 C1). | [cpu]: "no restriction to a particular cluster". VERIFIED rates |
| C11 | `stamp.c` takes its reading only after forwarding the chunk (:117-133), supports one needle, and has no file output. | **Revised backward-compatibly** (§3.8). The reading is taken as soon as `read()` returns; up to 12 needles; output to files; `-x` exec. | VERIFIED |
| C12 | The plan's M3 image lists `tracelogger`/`traceprinter` (plan:366-367). | **Not in M3.** They belong to M4, which stays blocked on the K11 dry run (plan:94, :381-401). Leaving them out keeps the black box and the IFS smaller. | VERIFIED |
| C13 | The plan says the IPC client's "CSV row printed over the TCU" (plan:373). | **The client appends the CSV itself, and that fails without a filesystem.** It prints only the stdout summary (`client.c:390-420`); every cloud QHV run hit the same failure (`logs/qhv-tcg-ipc-benchmark.log:55`). The pass evidence is the stdout summary. The CSV row is transcribed off the board into a private path (§4.4). | VERIFIED |
| C14 | **RAM.** GUEST_CONFIG: widen, or set `blk cache=`. NATIVE_QVM_HOST: `blk cache=2m`. BOARD_PROCEDURE: it fits. | **Keep `-m992M` and the cloud's devb-loopback line (default cache).** The estimated headroom is about 111 MiB (§3.5); R0 measures before any qvm run. The fallback order is owner decision O7. | Arithmetic §3.5; [io-blk] cache default "2 MB plus 2% of system RAM" |
| C15 | Should the M3 startup line gain `-A`? BOARD_PROCEDURE: add it. The other readers are silent. | **Recommended (O3).** `A` is a common option (lib/public/startup.h:163) that sets `SYSTEM_PRIVATE_FLAG_ABNORMAL_REBOOT` (lib/init_system_private.c:229-230). The board's reboot callout is `reboot_psci_smc` (board/main.c:104-106). On an abnormal reboot without the flag it masks DAIF and spins (lib/aarch64/callout_reboot_psci.S:42-58). A normal `shutdown` or `sysmgr_reboot()` ignores the flag. No code changes; one startup token. | VERIFIED lib; [callout_reset], [startup_options] |
| C16 | BOARD_PROCEDURE: bound commands with toybox `timeout`. | **Replaced by our own `bwait -k`** (§3.8), whose kill and exit behaviour is VERIFIED by our source. The QNX page leaves `timeout`'s expiry exit code undocumented (BOARD_PROCEDURE S1). | Our source to be written |
| C17 | **Where the ~169 MB kimg lands.** NATIVE_QVM_HOST K3: on the memblock free list (HYPOTHESIS). BOARD_PROCEDURE K1: below the kernel image (VERIFIED arithmetic). | **Both hold.** `image_size` is page-rounded with no cap (`shim/build-shim.sh:71-83`). The image ends near 0x8A17_5000, below `Kernel code 9b290000` (`raw/orin-iomem.txt:181`). Whether the whole span is free in memblock is HYPOTHESIS. A wrong landing prints `BAD-LANDING` and warm-resets (plan:154-156). | VERIFIED arithmetic; HYPOTHESIS placement |
| C18 | `shim/build-shim.sh:12` and plan:124 say `image_size` is "rounded to 2 MiB". | **Page rounding** (`build-shim.sh:71-83`). The comments are stale (Appendix A). | VERIFIED |
| C19 | Plan M3: "`-Wdisable` or a `wdtkick` kicker". | **`-Wkeep`, as M1b ran it.** WDT0 does not fire after the kexec hand-over (m0-hang-watchdog.md:9-10), so `-W` has no effect either way. | VERIFIED |
| C20 | Does qvm need `/dev/random` on the host? | **No.** In `logs/windows-qhv-tcg-boot-timed1.log` the host ran with no rng (:2-3), `random` failed with `Unable to access /dev/random` (:60-62), and qvm still booted the guest to its banner (:121). The M3 host starts no `random`. | VERIFIED |
| C21 | **When the IPC client starts.** MEASUREMENT: as soon as the banner and echo-server stamps fire. The cloud leg: `sleep 90` after launching qvm. | **At qvm launch + 90 s, as on the cloud leg (owner decision O6).** The cloud's `waitfor /dev/ttyp0 10` is satisfied at once, because `devc-pty` is already running (qhvh/startup.sh:43), then `sleep 90` (post_start.custom:37-39). | VERIFIED |
| C22 | Which guest-disk bytes should M3 boot? GUEST_CONFIG F8: the TCG series booted a copy already mutated by earlier snapshot-less boots. | **The pristine `cf5b06d0…`, restored every boot.** `disk-qemu` changed after its build (mtime 2026-09-09 00:57; `results/qhv-images-SHA256SUMS.txt:6-8` records the earlier `c71b9499…` pin). The embedded guest disk probably changed with it (HYPOTHESIS). Reading it would mean opening the host disk image, so it is not done. O8. | VERIFIED mtimes and pins |
| C23 | NATIVE_QVM_HOST P1: the cloud's procnto `-mr -d 0777 -u 0777` (qhvh/ifs.build:22). | **Keep M1b's `procnto-smp-instr -v`.** No hypervisor page names those options; they only set ASLR and `/proc` file masks. Recorded as a host-bundle difference. | VENDOR_CLAIM (NATIVE_QVM_HOST P1 citations) |

**Reader items rejected or changed:** C1 (NATIVE_QVM_HOST F3), C6 (the pipe and `hostdev >/dev/ptyp1` routes), C3 (both "two substitution" recommendations), C8 (MEASUREMENT M3-08), C14 (the `blk cache=` settings), C16 (toybox `timeout`), NATIVE_QVM_HOST rec 1 (conf = committed text; now O1), NATIVE_QVM_HOST rec 5 (`smpcheck -z 90` grace; replaced by a launch-relative timer). **Applied, with citations re-read:** GUEST_CONFIG F1-F18, NATIVE_QVM_HOST F1-F2, F4-F6, S1-S8, H1-H9, R1-R7, K1-K4, MEASUREMENT M3-02-M3-07, M3-09-M3-20, BOARD_PROCEDURE F1, F3, P1-P5, K1-K4, S2-S11, G1-G2.

---

## 2. Design rules

1. **Every wait is bounded, and every path ends in a warm reset.**
   - No `waitfor` and no unbounded foreground command anywhere; m2.build.in:88-98 gives the rules learned so far.
   - The IFS script's first program is a 900 s guard (`bwait -g 900`). Every wait in the ksh state machine is a `bwait` with a bound, and every child that could block is run under `bwait -k`.
   - The script ends in `smpcheck -z 3` then `shutdown -S reboot`, which warm-reset the board in every M1/M2/M1b run.
   - With `-A` (O3), a host-kernel abnormal termination also resets.
   - Only a lock-up with interrupts masked, or a hang before the IFS script starts, needs a power cycle. Those are residual, as in M1b.
2. **One variable per rung.**
   - R0 → R1: the qvm launch replaces the fake emitter, and nothing else changes.
   - R1 → R2: the IPC run is switched on.
   - R2 and T1-T5 are the same kimg.
   - All M3 images share one startup build, one smpcheck build and one build each of stamp, bwait and the client. The generator fails if any of them changes during a build (§5.3).
   - The Linux-side pre-kexec procedure is identical for every rung and every run (§6.4).
3. **The guest is byte-identical, and that is checked at four points:**
   - on the PC, sha256 of `qhv/guest/output/{ifs.bin,disk-qvm}` against the pins;
   - after mkifs, the same files extracted from our own IFS and hashed again;
   - on the board before kexec, sha256 of the kimg that carries them;
   - on the board at run time, md5 of `/proc/boot/guest-ifs.bin` and `/proc/boot/disk-qvm` before launch and after teardown (toybox has md5sum but no sha256sum; qhvh/system.build:161, :180).

   The guest's configuration differs from the TCG as-run text only in its load path (§3.3). The guest disk is the pristine image, restored every boot (§3.4).
4. **The M1b startup is unchanged.**
   - The generator refuses any startup binary other than sha256 `90bf724c222b61f9791ad3bcaff60c6516be7180012333be9186a58d06d61896`, and any smpcheck other than `f8e2c3078f12ac8ef27f1c482e77bd98d2188293195721d8168892a605c666b0` (both VERIFIED today; m1b-runs.md:27-28).
   - The shim is not edited. Only its `image_size` changes with the payload, which is `build-shim.sh`'s normal job.
   - Against M1b, the startup *line* changes in `-P6` → `-P4` (O2) and gains `-A` (O3). A RAM-widening startup change is admissible only under §6.6 M-fallback, after R0 or R1 shows a shortage, and it has its own verification (§6.6).
5. **M1b's and M2's records stay untouched.**
   - The M3 generator writes only under `shim/out/m3/`, never calls `make-m1b-images.sh` or `make-m2-images.sh`, and checks the kimgs those runs used, read-only, against their recorded sha256 prefixes.
   - No file under `results/` from an earlier milestone, and no `logs/` file, is edited.
6. **Nothing prints to the console while the timed window is open.**
   - The window runs from the `qvm_launch` reading until the banner waiter returns.
   - The TCU console callout busy-polls every character in the writer's own context (board/aarch64/callout_debug_tcu.S:131-136). Guest text, stamps and waiter results go to `/dev/shmem` files and are printed after the window closes.
7. **Records first, diagnostics after.** The black box keeps only the first 65,520 B and does not wrap (callout_debug_tcu.S:122-124; board/t234_startup.h:118-119). STAMP and IPC lines are printed as soon as they exist and again in a closing summary; capped diagnostics come last.
8. **Each run answers its own unknowns.** Printed each run:
   - the configuration and hashes;
   - FreeMem at five points;
   - the qvm-check result, qvm's exit code and qvm's thread placement;
   - all nine guest-marker stamps, the IPC summary and sentinel counts;
   - the pre- and post-run busy rates;
   - capped guest text and slog output.

### Timeline of one run: fault and hang coverage

| Phase | Where | Fault | Hang |
|---|---|---|---|
| Linux pre-kexec: governor, quiesce, `kexec -s -l`, `systemctl kexec` | L4T | A Linux oops in its own shutdown: `panic_on_oops=1` → the watchdog resets (PMC `BCCPLEXWDT`), and pstore keeps the Oops (m2-runs.md:126-133) | Watchdog-recovered while Linux still runs, as above |
| Relocation, then the shim | EL2, MMU off | The shim's vectors print `EXC …` and reset. A wrong placement prints `BAD-LANDING` and resets | Unbounded (residual, as in M0-M1b) |
| Startup (the M1b build) at `-P4` | EL2, E2H/TGE | The board EL2 vectors from `board_init` print and reset. The INTID 28 probe `STOP` is a named crash (m1b-design §2) | The M1b bounds (15 s AP start, 5 s park) |
| procnto → the IFS script before `bwait -g` | EL2&0 | procnto's own handling; with `-A`, an abnormal termination resets | Unbounded (residual); COM3 is the evidence |
| The IFS script and the ksh state machine | user space | A process fault: the script continues, and the missing lines name it | Each state's `bwait` bound, plus the 900 s guard (`sysmgr_reboot`). Commands run outside `bwait` (devb-loopback, `pidin`, `slay`, the short prints) are bounded only by the guard (§3.7, caveat 1) |
| qvm running the guest | host EL2 plus guest EL1 | A qvm exit is recorded as `rc=N` (§3.7). A host kernel crash resets with `-A` and spins without it | The banner bound (240 s), then teardown, then reset; the guard behind it |
| IPC | user space | Client exit code | `bwait -k 240` SIGKILL; the guard behind it |
| Teardown and reset | user space | — | The slay bounds; if `shutdown -S reboot` never resets, the guard fires at 900 s from start |
| Interrupts masked on every core | kernel | — | Nothing resets: power cycle, black box lost, COM3 holds the tail (m1b-design.md:715). Residual |

---

## 3. The host image

### 3.1 File list with provenance

All files land in `/proc/boot`, the whole of PATH and LD_LIBRARY_PATH in the bootstrap block (m1b-p6.build:17). qvm finds a vdev by searching LD_LIBRARY_PATH and adding the `vdev-` prefix and `.so` suffix ([vdev]).

**Kept from M1b** (m1b-p6.build:52-68, unchanged): the `/usr/lib/ldqnx-64.so.2` link, `libc.so.6`, `libgcc_s.so.1`, `libsecpol.so.1` (devc-pty needs it; m2.build.in:179-182), `ldqnx-64.so.2`, `tcu-cat`, `smpcheck`, `ksh`, `pidin`, `on`, `slay`, `waitfor`, `shutdown`, `devc-pty`. The revised `stamp` replaces M1's build.

**Added.** Sizes are SDP file sizes, `ls` only (VERIFIED).

| IFS name | Source | Bytes | Why | Provenance |
|---|---|---|---|---|
| `qvm` | sdp/sbin/qvm | 421,672 | The hypervisor | qhvh/system.build:359 |
| `qvm-check` | sdp/bin/qvm-check | 14,888 | Host check, once, before launch | qhvh/system.build:358; [qvm-check] |
| `vdev-pl011.so` | sdp/lib/dll | 14,456 | vdev in the configuration | qhvh/system.build:362 |
| `vdev-virtio-console.so` | sdp/lib/dll | 19,912 | vdev in the configuration | qhvh/system.build:369 |
| `vdev-virtio-blk.so` | sdp/lib/dll | 34,688 | vdev in the configuration | qhvh/system.build:368 |
| `vdev-shmem.so` | sdp/lib/dll | 35,160 | vdev in the as-run configuration (O1) | qhvh/system.build:367 |
| `libfdt.so.1`, with link `libfdt.so` | sdp/usr/lib/libfdt.so.1 | 46,536 | The host image carries both names | qhvh/system.build:245, :372 |
| `devb-loopback` | sdp/sbin | 25,128 | Guest disk backing | qhvh/post_startup.sh:48 |
| `io-blk.so`, `cam-disk.so`, `libcam.so.2` | sdp/lib/dll, lib | 339,560 / 23,992 / 120,248 | The block stack devb-loopback loads ("loads the standard block device DLLs", [devb-loopback]) | qhvh/ifs.build:136-138 |
| `slogger2`, `slog2info` | sdp/bin | 90,176 / 41,640 | qvm always sends internal errors to slog ([logger]) | qhvh/ifs.build:108, :101 |
| `libslog2.so.1` with link `libslog2.so`; `libslog2parse.so.1`; `libslog2shim.so.1`; `libjson.so.1` | sdp/lib | 28,376 / 46,344 / 18,328 / 52,064 | slog dependencies (which ones are needed: UNKNOWN) | qhvh/ifs.build:141-142, :151, :147, :150 |
| `pipe` | sdp/sbin | 35,008 | Parity with the cloud host's environment. The script does not depend on it (§3.7) | qhvh/startup.sh:41 |
| `toybox`, with links `cat cp cmp grep head md5sum tail wc` | sdp/usr/bin/toybox | 444,112 | Disk copy and checks, file prints | qhvh/ifs.build:72-80 (cat, grep); qhvh/system.build:131 (cmp), :133 (cp), :155 (head), :161 (md5sum), :186 (tail), :204 (wc) |
| Over-included: `libm.so.3`, `libqh.so.1`, `libregex.so.1`, `libjail.so.1`, `libfsnotify.so.1`, `libsocket.so.4` with link `libsocket.so` | sdp/lib | 301,192 / 97,872 / 71,056 / 26,272 / 60,896 / 334,048 | The dependencies of qvm, the vdevs, devb-loopback and slogger2 cannot be read from the binaries under the licence. Every library the cloud host IFS auto-links is carried. A missing one shows only on the board | qhvh/ifs.build:135, :158, :159, :152, :153, :144-145 |
| `qnx-host-client` | ipc-test/qnx-host-client/qnx-host-client (git-ignored build, .gitignore:35) | 18,704, sha256 `52cb4dca…a7eb` | IPC client. Its mtime (2026-07-28 21:37) predates the host image built from that path (22:55), so it is probably the binary the TCG host carried (HYPOTHESIS) | qhvh/data.build:82 |
| `guest-ifs.bin` `[+raw perms=0444]` | qhv/guest/output/ifs.bin | 9,783,916 | The guest. `+raw` stops mkifs treating the ELF as an executable, which it would otherwise strip ([mkifs]) | K11 (plan:94); qhvh/data.build:85 |
| `disk-qvm` `[+raw perms=0444]` | qhv/guest/output/disk-qvm | 153,432,576 (299,673 × 512; qhvg/disk.layout:1) | The guest disk | qhvh/data.build:86 |
| `g2.conf` | generated from `qhvconf/g2-m3.conf` (§3.3) | ~290 | The guest configuration, file name as on TCG, so qvm's `[g2.conf:N]` messages keep their form | qhvh/post_startup.sh:50 |
| `m3-host.ksh` | generated from `startup/m3-host.ksh.in` (§3.7) | ~7,000 | The host state machine | this design |
| `m3-fake-guest.txt` | `startup/m3-fake-guest.txt` (our text, §3.7) | ~300 | R0's stand-in stream; carried in every image so the file list is identical | this design |
| `bwait` | tools/bwait (new, §3.8) | ~20,000 (estimate) | Bounded waits, bounded runs, guard | this design |

**Deliberately absent:**
- `vpctl`, `vdev-virtio-net`, `mods-vdevpeer-net`, `vdev-pci-dummy`, `vdev-progress`, `vdev-ser8250`, `devr-virtio`, `io-usb-otg`: nothing in the configuration uses them.
- `random`: qvm does not need it (C20).
- `io-sock`.
- `fs-qnx6.so`: its absence guarantees the host can never mount the guest's partitions. io-blk enumerates partitions by default ([io-blk] `auto=partition`), but that is not a mount.
- `tracelogger` and `traceprinter` (C12).
- Every `.sym`.

### 3.2 Startup and kernel lines

```
startup-t234-orin-nano -vvv -P4 -Q enable,el2-host -m992M -Wkeep -A -Dtcu
PATH=/proc/boot LD_LIBRARY_PATH=/proc/boot
[+keeplinked] procnto-smp-instr -v
```

- **`-vvv`, `-Q enable,el2-host`, `-m992M`, `-Wkeep`, `-Dtcu`:** M1b's, character for character (m1b-p6.build:16).
- **`-P4`:** cluster 0 only (O2, C10). The `el2-host` path at `-P4` has never run; R0 is its first run (§9 R4).
- **`-A`:** O3, C15. If the owner declines it, the line is M1b's with `-P4`, and a host-kernel abnormal termination costs a power cycle.
- **procnto:** M1b's `-v` (C23).
- **Recorded host-bundle differences from TCG:**
  - The TCG host is `startup-qemu-virt -Q enable` with `procnto-smp-instr -mr -d 0777 -u 0777` (qhvh/ifs.build:17, :22), under QEMU TCG `-smp 2 -m 2G -cpu max` (`scripts/launch-qhv-tcg.ps1:151`; `scripts/orin/launch-qhv-on-orin-tcg.sh:165-171`).
  - It also runs mkqnximage's full service set (qhvh/startup.sh:9-69).

### 3.3 The guest configuration (`qhvconf/g2-m3.conf`)

Committed text with a `#` comment header. The generator strips comment lines into `shim/out/m3/g2-m3.conf`, which goes into the IFS as `/proc/boot/g2.conf`. The stripped file must equal, byte for byte, the expansion of the `printf` argument at qhvh/post_startup.sh:50 with exactly one line substituted (generator step PO-E, §5.3).

```
system mkqnximage-guest
ram 0x80000000,512M
cpu
load /proc/boot/guest-ifs.bin
vdev pl011
 hostdev >-
 loc 0x1c090000
 intr gic:37
vdev virtio-console
 loc 0x20000000
 intr gic:42
 hostdev /dev/ptyp0
vdev virtio-blk
 loc 0x1c0d0000
 intr gic:41
 hostdev /dev/qvmdisk0
 name vblk0
vdev shmem
 loc 0x1c0f0000
 intr gic:43
 allow phase2-rq2-probe
```

**What the guest sees**, the same on every leg:
- one vCPU;
- 512 MiB at guest-physical 0x80000000;
- the vdevs in this order, at these addresses and interrupts;
- no net vdev and no rng vdev;
- no `unsupported` or `logger` lines, so the documented defaults apply: instruction `fail`, reference `ignore`, register `fail` ([unsupported]; logger `fatal,internal,error,warn,info stderr` [logger]).

Compared with the committed three-vdev text (`scripts/qhv/post_start.custom:33`), only the four shmem lines differ (O1). The shmem region is created only when the guest asks for a name matching `allow` ([shmem]), and this guest never does (C2). Its effect on the guest's view of the machine, for example a device-tree node, is UNKNOWN.

**Diagnostic variants** (committed text, generated the same way, never timed):
- **`g2-m3-diag.conf`:** `g2-m3.conf` with three lines added after line 1:
  - `logger fatal,internal,error,warn,info,debug stderr`
  - `unsupported instruction abort`
  - `unsupported register abort`

  `abort` "display[s] a message indicating the failure and guest state, then terminate[s]" qvm ([unsupported]). This is image D1.
- **`g2-noblk.conf`:** the existing file, stripped. It is `g2-m3.conf` without the virtio-blk and shmem stanzas. This is image D2; its marker is `Startup complete`, and no banner is expected (C1).

### 3.4 The guest disk

1. It is carried as `/proc/boot/disk-qvm`, `[+raw perms=0444]`: the pristine `qhv/guest/output/disk-qvm`, sha256 `cf5b06d0…216b`, md5 `cca9570326f42115f91e595d02e489d1` (VERIFIED today).
2. The state machine copies it to `/dev/shmem/disk-qvm` with toybox `cp` (bound 30 s), then `cmp`s it against the IFS copy (bound 30 s; any difference is `FAIL disk_copy`).
3. It runs `devb-loopback loopback blksz=512,prefix=qvmdisk,fd=/dev/shmem/disk-qvm`. That is the cloud host's line (qhvh/post_startup.sh:48) with only the backing path changed, and in particular with no `blk cache=`. devb-loopback returns to the shell by itself on TCG (post_start.custom:31-32 runs it in the foreground and continues), so it is called plainly, not under `bwait -k`, which would kill a daemon that had not detached.
4. It waits for `/dev/qvmdisk0` with `bwait -p … -t 10`, the cloud's 10 s bound (post_start.custom:32).

**Why this route:**
- **Why not `/proc/boot` directly.** The IFS is read-only. devb-loopback opens its backing file O_RDWR by default, and `ro` would present a read-only disk ([devb-loopback]). The guest mounts `/system` and `/data` read-write (qhvg/mount_fs.sh:48, :52).
- **Why a copy per boot.** It restores the same bytes every run, the native equivalent of `-snapshot` (`launch-qhv-tcg.ps1:152`). The TCG timed series booted identical bytes each run, but bytes already written by earlier boots (C22).
- **Why not `hostdev /dev/shmem/disk-qvm` in the vdev.** It would change the configuration text and remove the io-blk layer the cloud leg had.
- **Recorded host difference.** The backing store is RAM, not qnx6 on emulated virtio-blk. The io-blk cache default scales with RAM: about 21.8 MiB here against about 43 MiB on the 2 GiB TCG host.

### 3.5 Memory budget at `-m992M` (MiB)

| Item | MiB | Class | Source |
|---|---|---|---|
| Window | 992.0 | VERIFIED | board/init_raminfo.c:39-43, `-m992M` |
| Kernel, syspage, startup, early processes (M1b: 992 − 974 FreeMem with a 2.61 MiB IFS) | 15.4 | VERIFIED (±1 MiB rounding) | m1blog:305; `shim/out/m1b/m1b-p6.ifs` 2,740,292 B |
| IFS kept out of the allocator: `avoid_ram(full_imagefs_paddr, shdr->stored_size)`. The size is the M1b IFS plus about 2.81 MB of additions plus the guest pair | 161.0 | VERIFIED rule (lib/_main.c:141-142); size arithmetic from §3.1 | sum of §3.1 |
| slogger2, pipe, devb-loopback, bwait, stamp, ksh | 4 | HYPOTHESIS (budget) | — |
| `/dev/shmem/disk-qvm` | 146.3 | VERIFIED size | §3.4 |
| io-blk cache, 2 MB plus 2% of system RAM | 21.8 | VENDOR_CLAIM (basis: total or free RAM, UNKNOWN) | [io-blk] |
| Guest RAM | 512.0 | VERIFIED (configuration) | §3.3. Need not be contiguous in host-physical memory ([ram]) |
| qvm process: heap, vdev buffers, stage-2 tables | 16 | UNKNOWN (budget; 512 MiB at 4 KiB granularity is about 1 MiB of leaf tables) | — |
| slogger2 buffers | 4 | UNKNOWN (budget) | — |
| **Committed** | **880.5** | HYPOTHESIS | — |
| **Headroom** | **~111** | HYPOTHESIS | — |

**Gates, printed as `M3 MEM <tag> <free>MB/992MB`:**
- **G-MEM, from R0:** `M3 MEM disk` ≥ 600 MB proceeds to R1. 560-600 MB proceeds with a note. Below 560 MB is owner decision O7 before R1: 512 MiB of guest RAM plus the qvm and slog budgets, 32 MiB.
- **From R1:** `M3 MEM banner` is recorded. A qvm exit code of 64, "fatal error before the guest started (e.g., out of memory)" ([errcodes]), is the O7 branch.
- **Not needed:** the second RAM range (0xC2000000-0xFBFDFFFF, raw/orin-iomem.txt:184-185; its derivation is in NATIVE_QVM_HOST R6-R7). It enters only through §6.6 M-fallback.

### 3.6 The buildfile template (`startup/m3.build.in`)

**Markers:**
- `@RUNG@`: `r0`, `r1`, `r2`, `d1` or `d2`.
- `@P@`: `4`.
- `@CLIENT@`, `@GUEST_IFS@`, `@GUEST_DISK@`: absolute host paths.
- `@KSH@`, `@CONF@`, `@FAKE@`: generated files under `shim/out/m3/`.

As in M1b, comment lines are dropped from the generated buildfile, because mkifs does not compile them (m1b-design.md §2 rule 3). The IFS script has no pipes, no redirection and no `waitfor`. Every line is a single program, and the only background job is the guard.

```
[image=0x80082000]
[-compress]

[virtual=aarch64le,raw] .bootstrap = {
    startup-t234-orin-nano -vvv -P@P@ -Q enable,el2-host -m992M -Wkeep -A -Dtcu
    PATH=/proc/boot LD_LIBRARY_PATH=/proc/boot
    [+keeplinked] procnto-smp-instr -v
}

[+script] .script = {
    display_msg "T234 M3 @RUNG@ -P@P@: procnto up"
    procmgr_symlink ../../proc/boot/ldqnx-64.so.2 /usr/lib/ldqnx-64.so.2
    procmgr_symlink /proc/boot/ksh /bin/sh
    bwait -g 900 &
    slogger2
    pipe
    devc-pty
    pidin info
    smpcheck -i -n @P@
    ksh /proc/boot/m3-host.ksh
    display_msg "T234 M3 @RUNG@ -P@P@: resetting so the log can be recovered"
    smpcheck -z 3
    shutdown -S reboot
}

[type=link] /usr/lib/ldqnx-64.so.2=/proc/boot/ldqnx-64.so.2
ldqnx-64.so.2
[-autolink]
libc.so.6
libgcc_s.so.1
libsecpol.so.1
libm.so.3
libqh.so.1
libregex.so.1
libjail.so.1
libfsnotify.so.1
libsocket.so.4
[type=link] libsocket.so=libsocket.so.4
libfdt.so.1
[type=link] libfdt.so=libfdt.so.1
libcam.so.2
io-blk.so
cam-disk.so
libslog2.so.1
[type=link] libslog2.so=libslog2.so.1
libslog2parse.so.1
libslog2shim.so.1
libjson.so.1

/proc/boot/tcu-cat=tcu-cat
/proc/boot/stamp=stamp
/proc/boot/bwait=bwait
/proc/boot/smpcheck=smpcheck
[perms=0555] /proc/boot/qnx-host-client=@CLIENT@
[perms=0444] /proc/boot/m3-host.ksh=@KSH@
[perms=0444] /proc/boot/g2.conf=@CONF@
[perms=0444] /proc/boot/m3-fake-guest.txt=@FAKE@
[+raw perms=0444] /proc/boot/guest-ifs.bin=@GUEST_IFS@
[+raw perms=0444] /proc/boot/disk-qvm=@GUEST_DISK@

ksh
pidin
on
slay
waitfor
shutdown
devc-pty
slogger2
slog2info
pipe
qvm
qvm-check
vdev-pl011.so
vdev-virtio-console.so
vdev-virtio-blk.so
vdev-shmem.so
devb-loopback
toybox
[type=link] cat=toybox
[type=link] cp=toybox
[type=link] cmp=toybox
[type=link] grep=toybox
[type=link] head=toybox
[type=link] md5sum=toybox
[type=link] tail=toybox
[type=link] wc=toybox
```

**Notes on the template:**
- **Autolink.** `[-autolink]` with explicit links follows the QNX-generated host IFS (qhvh/ifs.build:130-159), so no automatic link can collide with an explicit one. Whether M1b's image carried automatic `.so` links is not needed: programs name sonames. The generator's dumpifs check confirms both names of every linked library (§5.3).
- **Order.** `slogger2`, `pipe` and `devc-pty` return by daemonising, as their unbracketed use on TCG shows (qhvh/startup.sh:10, :41, :43; m2.build.in:104). The guard starts before anything that could block. The census, including M1b's bounded tick check with `sysmgr_reboot` on a dead tick (m1b-design §3.10), proves CPU0's clock before any `bwait` relies on it.

### 3.7 The host state machine (`startup/m3-host.ksh.in`)

Run in the foreground by the IFS script, the IFS script waits for it. ksh output goes to the kernel console and so reaches the black box (M2: smpcheck output recovered from pstore, m2-runs.md:40-60).

**Markers:**
- `@RUNG@`, `@P@`;
- `@MODE@`: `harness` for R0, `boot` for R1, D1 and D2, `full` for R2 and T1-T5;
- `@CPUS@`: `0 1 2 3`;
- `@IPC_BOUND@`: 20 for harness, 240 otherwise;
- `@STARTUP_LINE@`, `@A@`;
- `@GUEST_SHA256@`, `@DISK_SHA256@`, `@CONF_SHA256@`, `@CLIENT_SHA256@`;
- `@GUEST_MD5@`, `@DISK_MD5@`, `@CONF_MD5@`.

The generator dies if any `@[A-Z0-9_]+@` survives substitution.

**Rules:**
- The script uses no pipe and no command substitution, so it works with or without the pipe manager ([pipe] does not say whether ksh needs it).
- Every wait is a `bwait`.
- Nothing is printed between the `qvm_launch` reading and the return of the banner wait.

```ksh
# m3-host.ksh: M3 host state machine, generated from m3-host.ksh.in; edit the template.
S=/dev/shmem
B=/proc/boot
RUNG=@RUNG@
MODE=@MODE@
P=@P@
CPUS="@CPUS@"
IPC_BOUND=@IPC_BOUND@
FAIL=
LAUNCHED=

say()   { echo "M3 $*"; }
state() { echo "M3 STATE $*"; }
hit()   { [ -e "$S/$1.hit" ]; }
mem() {
	pidin info > "$S/mem.$1" 2>&1
	while read -r l; do
		case "$l" in
		*FreeMem:*) f=${l#*FreeMem:}; say "MEM $1 ${f%% *}" ;;
		esac
	done < "$S/mem.$1"
}
rates() {
	for c in $CPUS; do
		smpcheck -b 3 -C "$c" -o "$S/${1}c${c}" &
	done
	smpcheck -c "$P" -p "$S/${1}c" -T 20
}
md5ok() {
	if grep -q "^$2 " "$1"; then say "CHECK $4 $3 ok"; else say "FAIL $4 $3"; FAIL=${FAIL:-$4}; fi
}

state config
say "CONFIG rung=$RUNG mode=$MODE startup='@STARTUP_LINE@' q=el2-host w=keep A=@A@ cpus=$P guest_sha256=@GUEST_SHA256@ disk_sha256=@DISK_SHA256@ conf_sha256=@CONF_SHA256@ client_sha256=@CLIENT_SHA256@ clock=unverified"

state preflight
bwait -p /dev/ptyp1 -t 10 || { say "FAIL preflight /dev/ptyp1"; FAIL=preflight; }
bwait -p /dev/ttyp0 -t 10 || { say "FAIL preflight /dev/ttyp0"; FAIL=preflight; }
bwait -p /dev/slog -t 5 || say "NOTE no /dev/slog"
bwait -p /dev/pipe -t 5 || say "NOTE no /dev/pipe"
mem boot

state rate_pre
rates r0

if [ -z "$FAIL" ]; then
	state integrity_pre
	bwait -k 30 -o "$S/md5.pre" -e "$S/md5.pre.err" -- "$B/md5sum" "$B/guest-ifs.bin" "$B/disk-qvm" "$B/g2.conf"
	cat "$S/md5.pre"
	md5ok "$S/md5.pre" @GUEST_MD5@ guest md5_pre
	md5ok "$S/md5.pre" @DISK_MD5@ disk md5_pre
	md5ok "$S/md5.pre" @CONF_MD5@ conf md5_pre
fi

if [ -z "$FAIL" ]; then
	state disk
	bwait -k 30 -o "$S/cp.out" -e "$S/cp.err" -- "$B/cp" "$B/disk-qvm" "$S/disk-qvm"
	if bwait -k 30 -o "$S/cmp.out" -e "$S/cmp.err" -- "$B/cmp" "$B/disk-qvm" "$S/disk-qvm"; then
		say "CHECK disk_copy ok"
	else
		say "FAIL disk_copy"; head -c 512 "$S/cp.err"; head -c 512 "$S/cmp.out"; FAIL=disk_copy
	fi
fi
if [ -z "$FAIL" ]; then
	devb-loopback loopback blksz=512,prefix=qvmdisk,fd=/dev/shmem/disk-qvm
	bwait -p /dev/qvmdisk0 -t 10 || { say "FAIL disk_dev"; FAIL=disk_dev; }
	mem disk
fi

if [ -z "$FAIL" ]; then
	state hostcheck
	bwait -k 10 -o "$S/qc.out" -e "$S/qc.err" -- "$B/qvm-check"
	head -c 1024 "$S/qc.out"; head -c 1024 "$S/qc.err"
fi

if [ -z "$FAIL" ]; then
	state window
	stamp -i /dev/ptyp1 -o "$S/m3.guest" -m 65536 -r "$S/m3.stamps" -h "$S" -s '---> Starting slogger2' -l g_first -s '---> Starting devb' -l g_devb -s '---> Starting Networking' -l g_net -s 'if_up: tries exhausted' -l g_ifup -s '---> Starting sshd' -l g_sshd -s '---> Starting misc' -l g_misc -s 'server: echo endpoint up' -l g_srv -s 'Startup complete' -l g_startup_complete -s 'QNX qnx-guest' -l banner &
	bwait -p "$S/open.hit" -t 5 || { say "FAIL reader"; FAIL=reader; }
fi
if [ -z "$FAIL" ]; then
	LAUNCHED=1
	bwait -s 90 -c "$S/grace.hit" &
	if [ "$MODE" = harness ]; then
		( stamp -n -q -l qvm_launch -r "$S/m3.stamps" -x "$B/cat" "$B/m3-fake-guest.txt" < /dev/null > /dev/ttyp1 2>&1; echo "rc=$?" > "$S/qvm.rc"; : > "$S/qvm_exit.hit" ) &
	else
		( stamp -n -q -l qvm_launch -r "$S/m3.stamps" -x "$B/qvm" "@$B/g2.conf" < /dev/null > /dev/ttyp1 2>&1; echo "rc=$?" > "$S/qvm.rc"; : > "$S/qvm_exit.hit" ) &
	fi
	bwait -p "$S/banner.hit" -p "$S/qvm_exit.hit" -t 240
	bwait -p "$S/banner.hit" -t 2 > "$S/banner.settle"
	state report
	cat "$S/m3.stamps"
	[ -e "$S/qvm.rc" ] && { say "QVM ended before teardown"; cat "$S/qvm.rc"; }
	mem banner
	pidin -p qvm -f abNli > "$S/pq.1" 2>&1; head -n 30 "$S/pq.1"
fi

if [ -n "$LAUNCHED" ] && hit banner && [ "$MODE" != boot ]; then
	state ipc
	bwait -p "$S/grace.hit" -t 100
	stamp -n -q -l ipc_start -r "$S/m3.stamps"
	bwait -k "$IPC_BOUND" -r "$S/ipc.bwait" -o "$S/ipc.out" -e "$S/ipc.err" -- "$B/qnx-host-client" 15 /dev/ttyp0 5
	stamp -n -q -l ipc_end -r "$S/m3.stamps"
	cat "$S/ipc.out"
	head -c 2048 "$S/ipc.err"
	pidin -p qvm -f abNli > "$S/pq.2" 2>&1; head -n 30 "$S/pq.2"
fi

state teardown
if [ -n "$LAUNCHED" ] && [ "$MODE" != harness ]; then
	slay -f -Q qvm
	bwait -p "$S/qvm_exit.hit" -t 15 || { slay -f -Q -s KILL qvm; bwait -p "$S/qvm_exit.hit" -t 5; }
fi
[ -e "$S/qvm.rc" ] && cat "$S/qvm.rc"
if [ -n "$LAUNCHED" ]; then
	bwait -p "$S/eof.hit" -t 5 || slay -f -Q stamp
	state integrity_post
	bwait -k 30 -o "$S/md5.post" -e "$S/md5.post.err" -- "$B/md5sum" "$B/guest-ifs.bin" "$B/disk-qvm"
	cat "$S/md5.post"
	md5ok "$S/md5.post" @GUEST_MD5@ guest md5_post
	md5ok "$S/md5.post" @DISK_MD5@ disk md5_post
fi

state rate_post
rates r1

state summary
[ -e "$S/m3.stamps" ] && cat "$S/m3.stamps"
[ -e "$S/ipc.out" ] && grep -E '^(samples=|P50=|sentinel_)' "$S/ipc.out"
[ -e "$S/ipc.bwait" ] && cat "$S/ipc.bwait"
say "FAIL_STATE ${FAIL:-none}"
if [ -e "$S/m3.guest" ]; then
	wc -c "$S/m3.guest"
	head -c 4096 "$S/m3.guest"
fi
if [ -n "$LAUNCHED" ] && ! hit banner; then
	state diag
	[ -e "$S/m3.guest" ] && tail -c 1024 "$S/m3.guest"
	bwait -k 15 -o "$S/slog.txt" -e "$S/slog.err" -- "$B/slog2info"
	head -c 6144 "$S/slog.txt"; tail -c 2048 "$S/slog.txt"
else
	bwait -k 15 -o "$S/slog.txt" -e "$S/slog.err" -- "$B/slog2info"
	head -c 2048 "$S/slog.txt"
fi
mem end
state end
```

**States and bounds:**

| # | State | Action | Bound | Evidence line | On failure |
|---|---|---|---|---|---|
| S0 | config | Baked configuration line | none | `M3 CONFIG …` | — |
| S1 | preflight | Device nodes; FreeMem | 10+10+5+5 s; `pidin info`: none | `BWAIT path …`, `M3 MEM boot` | `FAIL preflight`: skip S3-S8 |
| S2 | rate_pre | 3 s busy worker on each of cpus 0-3, started in the background | 20 s: the collector returns at its `-T 20` deadline whatever the workers do (smpcheck.c:1161, :1174) | `SMPCHECK done cpu=i … rate=` ×4 | Recorded only |
| S3 | integrity_pre | md5 of the guest IFS, the disk and the configuration in `/proc/boot` against baked values | 30+5 s | `M3 CHECK md5_pre …` | `FAIL md5_pre`: no launch |
| S4 | disk | `cp`, `cmp`, devb-loopback, `/dev/qvmdisk0`, FreeMem | `cp` 30+5 s, `cmp` 30+5 s, `/dev/qvmdisk0` 10 s; devb-loopback and `pidin`: none (R7) | `M3 CHECK disk_copy ok`, `M3 MEM disk` | `FAIL disk_copy` or `FAIL disk_dev`: no launch |
| S5 | hostcheck | `qvm-check` | 10+5 s | `BWAIT run prog=qvm-check rc=N …` | Recorded; launch continues |
| S6 | window | Reader, then the 90 s grace timer, then launch (reading, then `execv`); silent until the banner wait returns | reader 5 s; banner 240 s (the Orin TCG launcher's per-run ceiling, `launch-qhv-on-orin-tcg.sh:60`); settle 2 s | `BWAIT path hit=/dev/shmem/banner.hit …` | Timeout or early qvm exit: S7 prints what exists, then diag |
| S7 | report | STAMP lines; FreeMem; qvm threads | prints; `pidin`: none | `STAMP …`, `M3 MEM banner`, pidin rows | — |
| S8 | ipc | Wait for launch + 90 s, then the client | grace 100 s (0 s once launch + 90 s has passed); client 240+5 s (20+5 s in harness) | the client's four stdout lines; `BWAIT run prog=qnx-host-client …` | Recorded (§7) |
| S9 | teardown | SIGTERM qvm, then SIGKILL; reader EOF, else slay | 15+5+5 s; `slay`: none | `rc=N` | Recorded |
| S10 | integrity_post | md5 of the IFS copies again | 30+5 s | `M3 CHECK md5_post …` | Recorded: corruption during the run |
| S11 | rate_post | As S2 | 20 s, as S2 | `SMPCHECK done …` ×4 | Recorded |
| S12 | summary, diag | Re-print the records; capped guest text (4 KB); slog (2 KB, or 8 KB on diag) | slog2info 15+5 s; `pidin`: none | `M3 STATE end` | — |

**Reading the Bound column.**
- `N+5 s` is a `bwait -k N`: at its deadline it sends SIGKILL, then polls for up to 5 s more (§3.8.2).
- A `bwait -p` can overrun by one 50 ms poll, and a collector by one 200 ms poll (smpcheck.c:112): under 2 s over a whole run.
- "none" marks a command run outside `bwait`. Only the 900 s guard bounds it.

**Worst case.** Full mode is the longest. Every term is a Bound entry above (VERIFIED arithmetic):

| Term | Seconds | Derivation |
|---|---|---|
| S1 | 30 | 10+10+5+5 |
| S2 | 20 | collector `-T 20` |
| S3 | 35 | 30+5 |
| S4 | 80 | (30+5) + (30+5) + 10 |
| S5 | 15 | 10+5 |
| S6 | 247 | reader 5 + banner 240 + settle 2 |
| S8 | 245 | grace 0 + client 240+5 |
| S9 | 25 | 15+5+5 |
| S10 | 35 | 30+5 |
| S11 | 20 | as S2 |
| S12 | 20 | slog2info 15+5 |
| **ksh total** | **772** | |

- **Why grace is 0 and settle is 2.** The grace timer starts before the launch, so the banner wait and the grace wait together never exceed max(90, banner) s. IPC runs only if `banner.hit` exists by the end of the 2 s settle. The longest path is therefore a banner-wait timeout at 240 s, a banner inside the settle, and a client killed at 240 s: 240 + 2 + 0 + 245. A missing banner skips IPC.
- **Outside the ksh, inside the guard's window.** The guard starts first (§3.6).
  - Before the ksh: slogger2, pipe, devc-pty, `pidin info`, and the census, whose only wait is its tick check of at most 2 s (smpcheck.c:109, :479-480).
  - After the ksh: `smpcheck -z 3` (3 s, smpcheck.c:1354-1355), then `shutdown`.
  - That leaves 900 − 772 − 3 = 125 s for those steps, the prints and the poll overruns.
- **Caveat 1: commands outside `bwait`.** 772 s assumes that each of them returns promptly:
  - devb-loopback (R7, VERIFIED on TCG only);
  - the six `pidin` calls and up to three `slay` calls;
  - the two `stamp -n` writes;
  - the short `cat`, `grep`, `head`, `tail` and `wc` prints of `/dev/shmem` files.

  If one of them stalls, the run's real ceiling is the 900 s guard, not 772 s plus margin.
- **Caveat 2: a dead grace timer.** If `bwait -s 90` never ran, the grace wait runs to its own 100 s bound. The total is then 872 s, with about 25 s left, and the guard may fire first. That resets the board and keeps the black box.
- **Neither caveat applies to a passing run.**
  - In a run that meets §8, the waits §8 depends on return on their hits, and the QNX side takes about 200 s (§6.5).
  - A dead grace timer there only delays the client, which `ipc_start` records.
  - §6.5 step 6 already sizes its give-up threshold from the 900 s guard, not from this sum.

**`startup/m3-fake-guest.txt`** is our own text. `cat` writes it into `/dev/ttyp1` in R0 only:

```
M3 HARNESS: the lines below are fake guest markers written by cat, not a guest
---> Starting slogger2
---> Starting devb
---> Starting Networking
if_up: tries exhausted
---> Starting sshd
---> Starting misc
server: echo endpoint up (HARNESS FAKE)
Startup complete
QNX qnx-guest HARNESS-FAKE not-a-guest
```

The fake banner cannot match §8's banner pattern (`QNX qnx-guest 8[.]0[.]0 .*ARMv8_Foundation_Model aarch64le`).

### 3.8 Tool changes (ours, Apache-2.0)

#### 3.8.1 `tools/stamp.c`, revised and backward-compatible

```
stamp -n [-q] [-l LABEL] [-r FILE] [-x PROG [ARG...]]
stamp [-i INPUT] [-o FILE] [-m BYTES] [-r FILE] [-h DIR] -s TEXT [-l LABEL] [-s TEXT -l LABEL]...
```

**Readings.**
- `cps = SYSPAGE_ENTRY(qtime)->cycles_per_sec`; `0` exits 1, as today (stamp.c:83-87).
- A reading is `t = ClockCycles()`, then `mono = clock_gettime(CLOCK_MONOTONIC)`, then `cpu = SchedGetCpuNum()` (used by smpcheck.c:887).
- Line format, one line per event: `STAMP <label> cycles=<u64> cps=<u64> cpu=<n> mono_ns=<u64> bytes=<u64>`. The fields after `cps=` are appended, so an existing `cycles=`/`cps=` parser still works. `bytes` is the stream offset at the end of the chunk that fired, and 0 for `-n`.

**`-n`.**
- Take the reading.
- With `-r FILE`, append the line with one `write(2)` (`O_WRONLY|O_CREAT|O_APPEND`, 0644).
- Unless `-q`, print it to stdout and flush.
- With `-x PROG`, which must be the last option (option parsing stops there), `execv(PROG, {PROG, remaining args})` follows immediately. The reading is therefore the last thing before qvm's image starts, in the same pid, with the caller's stdio.
- If the exec fails: `STAMP exec-failed errno=<n> prog=<PROG>` goes to the `-r` file and stderr, and the exit status is 127.

**Stream mode.**
1. The input is `open(INPUT, O_RDWR)` for `-i`, which suits a pty master and is never written, or stdin otherwise. With `-h DIR`, create `DIR/open.hit` once the input is open.
2. The forward target is `-o FILE` (`O_WRONLY|O_CREAT|O_TRUNC`) or stdout. `-m BYTES` caps what is stored: 65,536 by default with `-o`, unlimited to stdout. Bytes past the cap are still read and matched.
3. Needles:
   - Up to 12 `-s/-l` pairs, each `-s` paired with the next `-l`, each firing once.
   - A lone `-s` without `-l` keeps the old default label `mark`. Two or more `-s` without their `-l` is a usage error (exit 2).
   - Needles are 1-256 bytes, as today.
4. The loop, `n = read(in, buf, 4096)`:
   - On `n > 0`:
     1. Take the reading **before any other work**.
     2. Forward the chunk.
     3. Scan window = kept tail + chunk. For every unfired needle found: write its STAMP line (to the `-r` file with one `write`, and to stdout when there is no `-o`); then, with `-h`, create `DIR/<label>.hit`, *after* the line exists; then mark it fired. Every needle first found in one chunk carries that chunk's reading.
     4. Keep the last (longest needle − 1) bytes as the new tail.
   - `EINTR`: retry.
   - `n == 0` (EOF): write `STAMP eof cycles=… bytes=<total>`, create `DIR/eof.hit`, exit 0 if every needle fired and 1 otherwise.
   - `n < 0` otherwise: write `STAMP read-error errno=<n>`, create `DIR/eof.hit`, exit 1.
5. **Never:** exit before EOF or error, close the input early, write to the input, or change termios. Closing the master while qvm still writes to the slave has an UNKNOWN effect on qvm. A failed forward `write` is counted, and the count is printed with the `eof` line.

**Header.** The usage examples at stamp.c:16-22 are corrected: the banner is read from qvm's stdout, never from `/dev/ttyp0` (C5).

#### 3.8.2 NEW `tools/bwait.c`

```
bwait -p PATH [-p PATH]... -t SECS
bwait -k SECS [-r FILE] [-o OUT] [-e ERR] -- PROG [ARG...]
bwait -s SECS -c PATH
bwait -g SECS
```

- **Clock.** Every deadline is `ClockCycles()` against the syspage `cycles_per_sec`. Sleeps are `nanosleep`, re-checked against the counter. The census has already proven CPU0's tick in the same boot (§3.6).
- **`-p`.**
  - Poll `stat()` on each path every 50 ms. The first path that exists wins: `BWAIT path hit=<path> ms=<elapsed>`, exit 0.
  - At the deadline: `BWAIT path timeout secs=<S> ms=<elapsed> first=<first path>`, exit 1.
  - Prints exactly one line, at the end.
- **`-k`.**
  - `posix_spawn` PROG with stdin `/dev/null` and stdout/stderr to OUT/ERR (`O_WRONLY|O_CREAT|O_TRUNC`, default `/dev/null`).
  - Poll `waitpid(WNOHANG)` every 50 ms. At the deadline, `kill(SIGKILL)` and poll for up to 5 s more.
  - One line, to stdout and appended to FILE: `BWAIT run prog=<basename> rc=<exit status or -1> sig=<n or 0> killed=<0|1> ms=<elapsed>`.
  - Exit status: the child's status if it exited, 124 if killed, 125 on spawn failure (`BWAIT run prog=<basename> spawn-failed errno=<n>`).
- **`-s`.** Silent. Sleep until the deadline, create PATH (`O_CREAT`), exit 0.
- **`-g`.**
  - Set its own scheduling to `SCHED_RR` priority 50 and print `BWAIT guard armed secs=<S> prio=<50|err<n>>`.
  - At the deadline, print `BWAIT guard deadline=<S> expired: sysmgr_reboot`, then `sysmgr_reboot()` (sdpinc/sys/sysmgr.h:38, as smpcheck uses; a normal shutdown, unaffected by `-A` [startup_options]).
  - If that returns: `BWAIT guard sysmgr_reboot returned errno=<n>`, then `posix_spawn /proc/boot/shutdown -S reboot`. After 30 s: `BWAIT guard still alive`, exit 1.
- **Usage and exit 2** on any malformed command line. Build `-Wall -Wextra -Werror` like the other tools (tools/Makefile:8-9).

### 3.9 Other file changes

- **`tools/Makefile`:** `TOOLS := tcu-cat stamp smpcheck bwait`. **`.gitignore`:** add `orin-native/tools/bwait` next to :89-91.
- **New, committed text:** `startup/m3.build.in`, `startup/m3-host.ksh.in`, `startup/m3-fake-guest.txt`, `startup/make-m3-images.sh` (§5), `qhvconf/g2-m3.conf`, `qhvconf/g2-m3-diag.conf`.
- **`qhvconf/g2-noblk.conf`:** header comment only. Replace the premise at :9-14 with "diagnostic image D2 only: without the disk the guest cannot print its banner or start the echo server (m3-design.md §1 C1)". The qvm-visible lines stay unchanged.
- **`scripts/qhv/extract-ipc-result.sh`:** an optional third argument `notes`, defaulting to today's `tcg-qvm-virtio-console;transcribed-from-serial-log:<file>` (:52), so existing callers are unaffected.
- **Not changed:** anything under `board/`, the library patch, `shim/`, `tools/smpcheck.c`, `tools/tcu-cat.c`, `ipc-test/`, `scripts/qhv/post_start.custom`, `m2.build.in`, `make-m2-images.sh`, `make-m1b-images.sh`, and any earlier record.

---

## 4. Measurement

### 4.1 The stamps, and why they match the TCG markers

Every reading is the host's `ClockCycles()` at 31,250,000 cycles/s (32 ns). The census confirms the value on the board (`SMPCHECK census cps=31250000`, m1blog:313), and it is printed in every STAMP line. The TCG QNX hosts reported `cps=1000000000` (`logs/qhv-tcg-ipc-benchmark.log:50`).

| Label | Taken when | Source of the text | TCG counterpart |
|---|---|---|---|
| `qvm_launch` | In the launching process, immediately before `execv(qvm)` (§3.8.1 `-x`) | — | `=== launching qvm @g2.conf`, echoed just before `qvm … &` (qhvh/post_startup.sh:51-52), seen by the first 100 ms poll (`launch-qhv-tcg.ps1:88, :173-187`; `launch-qhv-on-orin-tcg.sh:102, :184-199`) |
| `g_first` | `---> Starting slogger2` | qhvg/startup.sh:9, the first guest line | not stamped |
| `g_devb` | `---> Starting devb` | qhvg/startup.sh:25 | not stamped |
| `g_net` | `---> Starting Networking` | qhvg/startup.sh:46 | not stamped (the host prints the same text before qvm starts) |
| `g_ifup` | `if_up: tries exhausted` | the message from qhvg/start_net.sh:3 (`windows-qhv-tcg-boot-timed1.log:97`) | counted (`if_up_exhausted=1`), not timed |
| `g_sshd` | `---> Starting sshd` | qhvg/startup.sh:50 | not stamped |
| `g_misc` | `---> Starting misc` | qhvg/startup.sh:63 | not stamped |
| `g_srv` | `server: echo endpoint up` | ipc-test/qnx-server/server.c:61-62 | not stamped |
| `g_startup_complete` | `Startup complete` | qhvg/ifs.build:60 | `guest_startup_complete` (the `Startup complete` poll) |
| `banner` | `QNX qnx-guest` | qhvg/ifs.build:61 (`uname -a`) | `guest_banner` (the `QNX qnx-guest` poll) |
| `eof` | the reader's input ended | — | — |
| `ipc_start`, `ipc_end` | around the client run | — | — |

None of the needles occurs in the guest stream before its own line: `windows-qhv-tcg-boot-timed1.log:79-121` contains no `qnx-guest` before the banner. The reader sees only qvm's stdio, never host lines.

**The quantity.** The headline is `banner − qvm_launch`. The only comparable TCG quantity is each leg's `guest_banner − qvm_launched` segment, computed here from the segment lines (VERIFIED arithmetic):

| TCG leg (rng, `-snapshot`, disk `95849168…`) | Runs (ms) | Median | Range |
|---|---|---|---|
| Windows, QEMU 11.1.0 (`windows-qhv-tcg-q111-rng-snapshot-segments-boot-times-n5.txt:15-24`) | 22,556 / 22,526 / 22,633 / 22,669 / 22,613 | 22,613 | 143 |
| Windows, QEMU 11.0.50 (`windows-qhv-tcg-rng-snapshot-segments-boot-times-n5.txt:16-25`) | 22,541 / 22,520 / 22,460 / 22,514 / 22,507 | 22,514 | 81 |
| Orin, QEMU 11.1.0 (`orin-qhv-tcg-q111-rng-snapshot-segments-boot-times-n5.txt:14-23`) | 48,452 / 48,264 / 48,727 / 48,854 / 47,623 | 48,452 | 1,231 |

**Resolution and latency.**
- Each TCG end is quantised by a 100 ms poll, so a TCG segment carries up to ±100 ms. Both TCG markers crossed the same emulated serial path, so their path latency largely cancels (HYPOTHESIS).
- Natively, the `qvm_launch` reading has no I/O in front of it. The `banner` reading includes the path from the guest's pl011 write, through qvm's pl011 vdev and the pty, to the reader's `read()` returning. That latency is UNKNOWN and expected to be far below 100 ms (HYPOTHESIS).
- The pl011 `batch` option is not set, and its default is not documented ([pl011]). Batching shows as several needles sharing one `cycles=` and one `bytes=`.
- **Cross-checks per run:** `mono_ns` deltas against cycle deltas, and the `cpu=` of every line. The cores should read one counter: M1b printed `cntvoff=0000000000000000` on every core (m1b-runs.md:111), and with E2H and TGE set the host's virtual count ignores `CNTVOFF_EL2` (VENDOR_CLAIM, Arm ARM).

**Segments computed on the PC**, in cycles and ms, and reported beside the headline:

| Segment | Contains | Fixed waits inside |
|---|---|---|
| `g_first − qvm_launch` | qvm start: configuration, vdev loading, 512 MiB of guest RAM, loading the 9.3 MiB guest ELF from `/proc/boot`; guest startup and kernel up to startup.sh's first echo | none known |
| `g_devb − g_first` | slogger2, the first `devc-virtio`, `ksh -l` on vcon1, fsevmgr | the `waitfor /dev/slog` default of 5 s, only if it times out ([waitfor]) |
| `g_net − g_devb` | devb-virtio, mounts, random, pipe, devc-pty, dumper | the `waitfor /dev/hd0`, `/dev/random` and `/dev/pipe` defaults (5 s each), only if they time out |
| `g_ifup − g_net` | io-sock start, then `if_up -p -r 20 vtnet0` walking an interface that never appears | **the if_up burn**: 20 walks, 1,000 ms apart by default, about 19-20 s by the docs ([if_up]), against "short" in findings.md (C7) |
| `g_sshd − g_ifup` | ifconfig, setconf hostname, sysctl, setfacl, `dhcpcd -b` | none known |
| `g_misc − g_sshd` | host-key checks (keys present, C8), sshd, qconn | none known |
| `g_startup_complete − g_misc` | mqueue; then post_startup.sh: the second `devc-virtio`, `waitfor /dev/vcon2 10`, the echo server started in the background, `sleep 1`, the RQ-2 skip, `io-usb-otg` in the foreground, `pidin arg \| wc -l` | `waitfor /dev/vcon2 10`, only if it times out (qhvg/post_startup.sh:25); **`sleep 1`** (:41) |
| `banner − g_startup_complete` | `uname -a` | none |
| `ipc_end − ipc_start` | the whole client run | client pacing, `usleep(20000)` per iteration (client.c:317) |

**`g_srv` is an offset, not a segment** (revision 2):
- **Why.** The guest starts the echo server in the background (qhvg/post_startup.sh:29), and nothing waits for its readiness line.
  - post_startup.sh runs on through `sleep 1` and returns, as startup.sh's last step (qhvg/startup.sh:69).
  - The IFS script then prints `Startup complete` and runs `uname -a` (qhvg/ifs.build:57-61).
  - The server prints its line only after its `open` and `cio_set_raw` (ipc-test/qnx-server/server.c:51-62).

  VERIFIED from the build files and source.
- **What TCG showed.** Twelve captures in `logs/` start this server.
  - In 11 of them, its line came before `Process count` and `Startup complete` (for example `windows-qhv-tcg-boot-timed1.log:111, :117, :119`).
  - In `qhv-tcg-rq2-shmem-roundtrip-attempt1-bus-error.log`, it came only after the post-`sleep 1` echo (:49-51), interleaved byte by byte with `gshm-probe`'s output. The needle occurs nowhere in that file. The run's client still printed `samples=15` and `sentinel_recoveries=0`, and exited 0 (:61, :64, :66). VERIFIED.
  - That guest staged `gshm-probe`; the 968029 guest does not (C2). Its concurrent console writers are the post_startup.sh shell, `io-usb-otg` and the background daemons.
- **The chain needles held.** All seven chain needles and the banner were intact, and in chain order, in all 12 captures. VERIFIED by line numbers:
  - the six `--->` and `if_up` lines at their last occurrence before the guest-only `=== starting devc-virtio` line (the host prints several of the same `--->` lines);
  - `Startup complete` directly before the banner line.
- **Recorded, not gated.** When `g_srv` exists, the run note records `g_srv − g_misc`, `g_srv − g_startup_complete` and `ipc_start − g_srv`, all signed; otherwise it records `g_srv absent`. None of them is a pass criterion (§8 item 6, R37).

The write-up must say whether the headline is dominated by the fixed waits. If the if_up burn really is about 19-20 s natively, any native-to-TCG ratio of the whole segment is meaningless (§10).

### 4.2 CPU placement

- **Choice (O2): `-P4`.** Label every run: `host=-P4: cluster 0 only (cpus 0-3, one cpufreq policy); cluster 1 not started; vCPU floating within cluster 0 (cpu line bare)`.
  - The configuration's `cpu` line stays bare, so there is no `cluster` option ([cpu]).
  - qvm is not run under `on -R`.
  - The reader, the waiters, the ksh and the guard float over the same four cores.
- **Evidence.** `pidin -p qvm -f abNli` is printed after the banner (S7) and after IPC (S8), recording pid, tid, name, last CPU and runmask for each qvm thread. The format codes are as M2 used them (m2.build.in:130-135).
- **Not chosen:**
  - `-P6` with the vCPU pinned to a cluster: that changes both the startup line and the configuration, and still leaves the I/O threads floating.
  - `-P6` unpinned: that mixes two clock domains, with cluster 1 at 57 M it/s (m1b-runs.md:157-162).
  - A `-P6` diagnostic run with `cpu cluster` on cluster 1 could measure the cluster-1 factor on a real guest boot. It is outside M3.

### 4.3 CPU frequency: what is done and what is recorded

**Before every kexec (Linux, §6.4 step 4).**
1. Set `scaling_governor` to `performance` on `policy0` and `policy4`. This is runtime state only, and the warm reset restores `schedutil`.
2. Just before `systemctl kexec`, record for each policy: `affected_cpus`, `scaling_governor`, `scaling_cur_freq`, `cpuinfo_cur_freq` (sudo), `scaling_min_freq`, `scaling_max_freq`.
3. Once per session, also record `scaling_available_frequencies`, every `thermal_zone*/type` and `temp`, and `nvpmodel -q` (read-only).

**Why the Linux reading is not the frequency.** Just before M2's R4, `schedutil` had cluster 0 at 1,267,200 kHz (m2-runs.md:116-118), yet cluster 0 then ran the busy loop at 477 M it/s. Every cluster-0 rate recorded so far divides by a frequency on the 115.2 + k × 76.8 MHz grid at 0.4955-0.4975 M it/s per MHz, and the cluster-1 rate at 115.2 MHz gives 0.4952:
- 363 ↔ 729.6
- 401 ↔ 806.4
- 439 ↔ 883.2
- 477 ↔ 960.0
- 630 ↔ 1,267.2
- 666 ↔ 1,344.0

The rates are m2-runs.md:106-112 and m1b-runs.md:159-162; the fit is HYPOTHESIS. Under that fit, R4 ran at about 960 MHz, not 1,267. So something changed the frequency between the read and QNX, and the pre-kexec reading cannot fill a MHz field (VERIFIED mismatch, HYPOTHESIS cause).

**On QNX, every run.** S2 and S11 run a 3 s busy worker on each of cpus 0-3 (`smpcheck -b 3`) and print their `rate=`. The prediction, HYPOTHESIS: if the `performance` pin at `scaling_max_freq` = 1,344,000 kHz survives the kexec path, cpus 0-3 read about 666 M it/s; about 363 M would mean Linux dropped to its minimum on the way out.

**The field, exactly:**
`cpu_mhz: clock not verified [qnx rate pre c0..c3=<M,M,M,M> post=<M,M,M,M>; linux pre-kexec policy0 gov=<g> cur=<kHz> hw=<kHz> min=<kHz> max=<kHz>; policy4 gov=<g> cur=<kHz> hw=<kHz>; thermal=<zone:mC,…>; nvpmodel=<mode>]`

Flag a run if any core's |post − pre| / pre exceeds 2 %. A MHz value may be written only if it was measured on QNX in that run; that needs a PMCCNTR calibration, which is a startup change (O10, not recommended for M3).

### 4.4 The IPC run

- **Command:** `qnx-host-client 15 /dev/ttyp0 5`, the committed arguments (post_start.custom:52; client.c:184-206). It runs under `bwait -k 240` at qvm launch + 90 s (C21, O6), after the banner stamp.
- **stdout (the pass evidence):**
  - `samples=<n> payload=48 cps=31250000`
  - `P50=<ns> ns  P99=<ns> ns  Max=<ns> ns` (two spaces)
  - the sanity line
  - `sentinel_recoveries=<r> sentinel_bounces=<b> …` (client.c:390-399)
- **stderr:** `client: link up …`, `client: progress 0/20`, any recovery lines, and the harmless CSV `note` (client.c:268-269, :289-291, :417-419).
- **Bounds (VERIFIED from source):**
  - Read timeout 10 s (client.c:56, :72-73); up to 5 sentinel rounds, each ending at its first timed-out read (:63-64, :131-138); so a dead link ends in about 61 s including the 1 s priming drain (:249-265).
  - The write loop has no timeout (common/console_io.h:139-153). Hence the outer 240 s kill.
- **Completion rule:** `rc=0 killed=0` and `samples + sentinel_recoveries = 15`. Clean when `sentinel_recoveries=0`, completed-with-recovery otherwise. This is the cloud leg's precedent: its committed 15/5 regression run recovered one stall and still counted as a clean run with real P50/P99/Max (ipc-test/qnx-host-client/README.md:189).
- **Reading the numbers:**
  - Nearest rank at n=15 makes P50 `sorted[7]` and **P99 `sorted[14]` = Max** (client.c:84-95).
  - Native RTT is quantised to 32 ns and is not comparable in absolute terms with TCG's emulation-dominated 2.0-2.3 ms (`qhv-tcg-ipc-benchmark.log:53`).
  - **No same-image baseline exists.** The 968029 guest has never run the client: every IPC capture predates its 2026-07-28 22:55 build, and every later TCG run used `-StopOnGuestBanner` (GUEST_CONFIG F9, mtimes VERIFIED). A zero-board-cost TCG run could provide one (O9).
- **Transcription, off the board:**
  1. Strip CR from the black box.
  2. Run `scripts/qhv/extract-ipc-result.sh <run black box> results/orin-native-port/<ts>/m3/orin-native-ipc.csv 'orin-native-el2host-p4-qvm-virtio-console;clock=unverified;transcribed-from-blackbox:<file>'` (notes argument, §3.9).
  3. Never write to `results/cloud/` or `results/hw/`: the output is evaluation data under 4.6(i).

### 4.5 Black-box budget and gates

The cap is 65,520 B, head kept (callout_debug_tcu.S:122-124). M1b sizes: `-P1` 7,936 B; `-P6` 23,031 B, about 3,019 B per extra core including about 420 B of busy-worker lines (m1b-runs.md:46-49).

| Part | Typical (B) | Capped worst (B) | Class |
|---|---|---|---|
| Shim, startup, syspage, census, two `pidin info` at `-P4`: 7,936 + 3 × ~2,600, less M1b's workers | ~14,700 | ~14,700 | HYPOTHESIS (from VERIFIED sizes) |
| Guard, CONFIG, STATE, BWAIT, MEM lines | ~2,100 | ~2,300 | estimate |
| Two rate probes (4 `done` lines and a RESULT line each) | ~2,300 | ~2,300 | M1b line length (m1blog:372-377) |
| md5 and CHECK lines, twice | ~800 | ~800 | estimate |
| qvm-check output | ~100 | ~2,000 | cap |
| STAMP lines (12 × ~110), printed twice | ~2,600 | ~2,600 | estimate |
| `pidin -p qvm -f abNli`, twice, 30 lines each | ~1,500 | ~4,200 | cap |
| IPC stdout, stderr, re-print | ~700 | ~2,600 | cap |
| Guest stream (about 900 B before the banner on TCG, `windows-qhv-tcg-boot-timed1.log:79-121`; CRs possible) | ~1,600 | ~4,100 | cap |
| slog2info | ~500 | ~2,050 (diag: ~8,200 plus a 1,024 guest tail) | cap |
| **Total** | **~27,000** | **~38,000 (diag ~45,000)** | HYPOTHESIS |

- **G1 (on R0's black box).** If R0's size is 60,000 B or more (m1b-design.md:727 used the same threshold), rebuild **every later image** at `-vv` before R1, and record that as a startup-line deviation.
- **G2 (on Q's black box).** The same threshold, before T1. The verbosity never changes between Q and T5.
- **COM3 is a mandatory co-record** on every run, started from PowerShell (m2-runs.md:135-137). It is the only record of a hang and of anything past the cap. STAMP and IPC lines must match byte for byte between the two records, CR-stripped; otherwise the run note flags the difference. Drops are silent on both sides (callout_debug_tcu.S:131-136; board/hw_sertcu.c:107).

### 4.6 Per-run record (the run note)

1. **Identity:** run id and rung; UTC launch time; L4T `boot_id` before and after; uptime at kexec; PMC `reset_reason`; COM3 file name.
2. **Images:**
   - the kimg sha256 (checked on the board before kexec) and the IFS sha256;
   - the startup line as the IFS carries it (generator step 13);
   - the `-Q` mode, the `-W` policy recorded as `-Wkeep (no effect: WDT0 does not fire after kexec)`, `-A` yes or no, `-P4`;
   - the startup, smpcheck, stamp, bwait and client sha256 values;
   - the kexec syscall (`-s`).
3. **Guest:**
   - guest IFS sha256 `968029…7cf4f`, disk sha256 `cf5b06d0…216b`, and the board md5 results before and after;
   - the configuration name and sha256, with a note that its diff against qhvh/post_startup.sh:50 is the load line only;
   - the TCG series' guest disk marked "bytes written by earlier TCG boots, not hashed" (C22).
4. **Host:** qvm and vdev `.so` sha256 values, from the generator table; FreeMem at `boot`, `disk`, `banner`, `end`; the qvm-check line; `rc=` of qvm.
5. **Linux side:** quiesce steps and their results (§6.4); governor and frequency lines; the `cpu_mhz` field (§4.3).
6. **Stamps:**
   - every STAMP line raw, with `cps=31250000` checked in all of them;
   - the headline and each §4.1 segment, in cycles and in ms;
   - the three signed `g_srv` offsets, or `g_srv absent` with the guest text around `=== starting qnx-echo-server` (§4.1).
7. **Placement:** both `pidin -p qvm` listings; in boot mode (R1, D1, D2) only S7's exists (§3.7).
8. **IPC:** the four stdout lines verbatim; the `BWAIT run` line; the completion class.
9. **Records:** black-box bytes and sha256; COM3 bytes; the consistency verdict; any deviation.
10. Every file private, tagged "evaluation output, NC QDL v7 4.6(i), unpublished".

### 4.7 Reporting rules

- Give all five T values, the median and the min-max range, and the same for every segment. No mean ± SD, no confidence interval, no outlier removal. Q is reported separately and never folded in.
- Compare only with the TCG `qvm_launched → guest_banner` medians in §4.1. Always state the ±100 ms TCG resolution, the bundle differences (§3.2, §3.4, §4.1) and the if_up burn beside the headline.
- Read the spread as repeatability of this bundle on one board, under uncontrolled DVFS, thermal state and kexec residue.

---

## 5. Images and generator

### 5.1 Images

All images use one startup build, one smpcheck build, one build each of stamp and bwait, one client and one buildfile template. Every image carries the same file set (§3.1). They differ only in `@RUNG@`, `@MODE@`, `@IPC_BOUND@` and the configuration.

| Image | Startup line (exact) | Configuration | Mode | Role |
|---|---|---|---|---|
| `m3-r0` | `startup-t234-orin-nano -vvv -P4 -Q enable,el2-host -m992M -Wkeep -A -Dtcu` | `g2-m3.conf` (present, not used) | harness, IPC bound 20 s | **R0** |
| `m3-r1` | same | `g2-m3.conf` | boot | **R1** |
| `m3-r2` | same | `g2-m3.conf` | full, IPC bound 240 s | **R2 (Q) and T1-T5** |
| `m3-d1` | same | `g2-m3-diag.conf` | boot | Diagnostic D1 (§6.6) |
| `m3-d2` | same | `g2-noblk.conf`, stripped | boot | Diagnostic D2 (§6.6); marker `Startup complete` |

- Without `-A` (O3 declined), every line drops `-A`, and the images are named `m3n-*`.
- The contingency images `m3-*-p6`, `-P6` with the same payload, are built only on demand (§6.6 C2).
- The gzip'd-disk images `m3z-*` (O7) are built only on demand.
- **Size:** each kimg is about 168.8 MB (8,192 B plus an IFS of about 168,765,000 B); estimate from §3.1, and the generator prints the real value. Five images need about 850 MB under `shim/out/m3/`.

### 5.2 `startup/make-m3-images.sh`: steps and checks

Usage: `BSP=… QNX_BASE=… ./make-m3-images.sh [--generate-only] [image …]`, with the environment handling, `die`, `STEP` and ERR trap of make-m1b-images.sh:90-92, :452-500. It stops at the first failure with `FAIL: <step>`.

1. **Output guard.** `OUT="$SHIM/out/m3"`. Die if `OUT`, resolved, is `out/m1b` or `out/m2` or lies under either (as `guard_output`). Never call make-m1b-images.sh or make-m2-images.sh.
2. **Snapshot** `git status --porcelain` (A).
3. **PO-A: earlier generators and board code unchanged.** `git diff --quiet -- orin-native/startup/m2.build.in orin-native/startup/make-m2-images.sh orin-native/startup/make-m1b-images.sh orin-native/startup/t234-orin-nano`.
4. **PO-B: input pins.** Die unless each matches:
   - `sha256(startup-t234-orin-nano)` = `90bf724c222b61f9791ad3bcaff60c6516be7180012333be9186a58d06d61896`;
   - `sha256(tools/smpcheck)` = `f8e2c3078f12ac8ef27f1c482e77bd98d2188293195721d8168892a605c666b0`;
   - `sha256(ipc-test/qnx-host-client/qnx-host-client)` = `52cb4dcad5a3632f88092289ef68668cc1fc604f150f3e2f8b9f31dc82caa7eb`.

   All three are VERIFIED today. Record the stamp and bwait sha256 values (new builds).
5. **PO-C: the kimgs M1b and M2 ran are still in place** (read-only; checked only if the file exists). The first 24 hex digits of each sha256 must match:

   | kimg | sha256 prefix | Record |
   |---|---|---|
   | `out/m1b/reg-p6.kimg` | `c391551a8e4b16bbc6f0e626` | m1b-runs.md:46-49 |
   | `out/m1b/m1b-p1.kimg` | `cf0715ef7f0e447228d33655` | m1b-runs.md:46-49 |
   | `out/m1b/m1b-p6.kimg` | `85970fe84cb5ed644e2cced6` | m1b-runs.md:46-49; recomputed today |
   | `out/m2/m2-p6.kimg` | `5cae65e821edcdb9c2355310` | m2-runs.md:28 |
6. **PO-D: guest pair.**
   - `sha256(qhv/guest/output/ifs.bin)` = `968029316b940f53580228f44e393877e032e251d78f3c752600cae726a7cf4f`.
   - `sha256(qhv/guest/output/disk-qvm)` = `cf5b06d0b3cb524201c71440fdda42a18d2636d45938acd8ec95cfa21314216b`.
   - Die otherwise. Compute md5 values for baking; today they are `0e3a2e9bcf4ccf99d4f9ce49a35c55d2` and `cca9570326f42115f91e595d02e489d1`.
7. **PO-E: configuration gate.**
   1. Take the one line of qhvh/post_startup.sh that begins `printf 'system mkqnximage-guest` (die unless exactly one).
   2. Extract the single-quoted argument and expand `\n`.
   3. Replace exactly one line, `load /data/hypervisor/guest/ifs.bin`, with `load /proc/boot/guest-ifs.bin` (die unless exactly one).
   4. `cmp` the result against `qhvconf/g2-m3.conf` with comment lines stripped, written to `$OUT/g2-m3.conf`.
   5. Diagnostic variants. The stripped `g2-m3-diag.conf` must equal it with exactly the three §3.3 lines inserted after line 1. The stripped `g2-noblk.conf` must equal it without the five virtio-blk lines and the four shmem lines.
   6. Print, for the record, the diff of `g2-m3.conf` against the expansion of the committed `scripts/qhv/post_start.custom:33`. It should show the load line and the four shmem lines.
8. **Generate** `$OUT/<img>.ksh` from `m3-host.ksh.in` and `$OUT/<img>.build` from `m3.build.in`. Die on any leftover `@[A-Z0-9_]+@`. `--generate-only` stops here and needs no SDP.
9. **SDP and inputs.** `setup_sdp`, with `MKIFS_PATH` = board build directory then tools, as make-m1b-images.sh:477-487; SDP files resolve under `QNX_TARGET`. Then `check_inputs`, extended with `bwait`.
10. **mkifs**, as make-m1b-images.sh:537-557.
11. **dumpifs `-vv` checks:**
    - `compress=0`;
    - the script holds exactly two `display_msg` lines labelled `T234 M3 <rung> -P4`, one `bwait -g 900 &`, one `smpcheck -i -n 4`, one `ksh /proc/boot/m3-host.ksh` and one `shutdown -S reboot`;
    - every §3.1 name is listed exactly once, including both names of each linked library;
    - `vpctl`, `vdev-virtio-net.so`, `fs-qnx6.so`, `random`, `io-sock`, `tracelogger` and `traceprinter` are absent, as is any `.sym`.
12. **Geometry.** From the startup-header lines (format as `m1b-p6.dumpifs.txt:2-12`): `image_paddr=0x80082fa0`, and `image_paddr + stored_size ≤ 0x8C000000`, which leaves at least 800 MiB of the window.
13. **Startup arguments**, as make-m1b-images.sh:599-650: `-P4` exactly once; `-Q` exactly once with the value `enable,el2-host`; `-A` exactly once (or absent for `m3n-*`); argv equal to the buildfile's line.
14. **Byte identity inside our IFS.**
    1. `dumpifs -x -b -d $OUT/xtr-<img> $OUT/<img>.ifs <the listed names of guest-ifs.bin, disk-qvm, g2.conf, m3-host.ksh>` ([dumpifs]).
    2. sha256 each extracted file. They must equal `968029…`, `cf5b06d0…`, the generated configuration and the generated ksh.
    3. Delete `$OUT/xtr-<img>` afterwards, so no extra copies persist.
15. **Wrap**, as make-m1b-images.sh:652-675: `build-shim.sh jump` produces a kimg of 8,192 B plus exactly this IFS, and build-shim.sh's header check passes with `image_size` page-rounded (build-shim.sh:71-83, :108-131).
16. **Stability.** The startup, smpcheck, stamp, bwait and client sha256 values are unchanged at the end.
17. **Tracked-path guard.** `git check-ignore -q` succeeds for every file written, and `git status --porcelain` equals snapshot A. The generator writes nothing outside `$OUT`.
18. **Table.** Image, mode, configuration, IFS bytes and sha256, kimg bytes and sha256; then the startup, smpcheck, stamp, bwait and client sha256; the guest and disk sha256 and md5; the ksh and configuration sha256; and the qvm and vdev sha256 values from the SDP. Hashes only, never contents.

**Output directory:** `orin-native/shim/out/m3/`, git-ignored (.gitignore:83). Nothing from it is ever copied to a tracked path.

---

## 6. Run ladder and procedure

### 6.1 Build (PC)

1. **Do not rebuild the startup.** The M1b build at `bsp-le/startup-t234-orin-nano` must hash to `90bf724c…` (generator PO-B). If it is missing, rebuild it from the committed board code with `BSP=C:/Users/<user>/AppData/Local/Temp/orin-native-port-bsp QNX_BASE=/c/Users/<user>/qnx800 ./orin-native/startup/build-board.sh`; PO-B must still pass.
2. `make -C orin-native/tools` in the SDP environment. This builds `stamp` and `bwait`; smpcheck must keep `f8e2c307…`.
3. `./orin-native/startup/make-m3-images.sh` with the same `BSP` and `QNX_BASE` builds the five images of §5.1. Record its table (§5.2 step 18) in the run note.

### 6.2 Staging (once per kimg, never per run)

1. **Board:** `df -h ~` must show at least 600 MB free.
2. **Transfer** with the resumable, checksum-gated pattern of `scripts/twin/sync-qhv.sh` (`copy_one`, :82-108): remote size, then prefix sha256, then append or resend, over `scp -C`.
   - A QNX disk image compressed to about 40 % under `gzip -1` (sync-qhv.sh:92-93).
   - The board once dropped off the network at 66 % of a 322 MB transfer (docs/orin-port.md:147).
   - Record the time and MB/s of the first transfer.
3. **Board:** `sha256sum ~/<img>.kimg` must equal the generator's value.

### 6.3 P0: pre-flight (board; no reboot, nothing persistent)

1. **Frequency:** read `affected_cpus`, `scaling_available_frequencies`, `scaling_min_freq`, `scaling_max_freq` and `scaling_governor` from `/sys/devices/system/cpu/cpufreq/policy0/` and `policy4/`; record `nvpmodel -q` and every thermal zone. This settles the frequency grid of §4.3.
2. **Modules and memory:** record `lsmod`, and `sudo -n cat /proc/iomem`, keeping the 80000000-ffffffff lines to compare with raw/orin-iomem.txt:180-186.
3. **Dynamic debug:** `sudo -n test -e /sys/kernel/debug/dynamic_debug/control && echo dyndbg=yes`.
4. **Acceptance test of the ~169 MB kimg:** `sudo -n kexec -s -l ~/m3-r0.kimg; echo rc=$?; cat /sys/kernel/kexec_loaded; sudo -n kexec -u; cat /sys/kernel/kexec_loaded`. Pass is `rc=0`, then `1`, then `0`. The M0 test ran the same sequence on the shim alone (m0-kexec-acceptance.md:12-21).
5. **Placement, only if `dyndbg=yes`:**
   1. `echo 'file kexec_image.c +p' | sudo -n tee /sys/kernel/debug/dynamic_debug/control`
   2. Repeat step 4.
   3. `sudo -n dmesg | grep 'Loaded kernel at'`, expecting `0x80080000`. The pr_debug line is from upstream v5.15 `arch/arm64/kernel/kexec_image.c` (VENDOR_CLAIM, NATIVE_QVM_HOST K4); NVIDIA's fork is unread.
   4. Turn it off again with `-p`.

   Any other address predicts `BAD-LANDING`: go to K1 before R0.

**Gate:** step 4 passes.

### 6.4 P1: quiesce rehearsal (only if O4 is adopted; no kexec)

1. `systemctl get-default`, then `sudo -n systemctl isolate multi-user.target`.
2. `for m in nvidia_drm nvidia_modeset nvidia nvgpu; do sudo -n timeout 30 rmmod $m; echo rmmod $m rc=$?; done`, then `lsmod | grep -E '^(nvidia_drm|nvidia_modeset|nvidia|nvgpu) '`.
   - The plan names `nvidia_drm nvidia_modeset nvgpu` (plan:169). `nvidia` is in the board's loaded-module list and sits between them.
3. `sudo -n dmesg | tail -n 100 | grep -iE 'smmu|tegra-mc|emem|nvgpu|nvidia|oops|bug'`.
4. `sudo -n cat /proc/iomem > iomem-postrmmod-<utc>.txt`; diff its 80000000-ffffffff lines against P0. Also run `sudo -n dmesg | grep -iE 'software IO TLB|swiotlb|cma'`. This closes checklist 11c (plan:553-554).
5. `sudo -n reboot`, and wait for a new `boot_id`.

**Gate and outcomes:**
- All four `rc=0`, no Oops, no SMMU or EMEM lines: the quiesce steps join §6.5 step 4 for every run.
- An `rmmod` fails: record it, and O4 falls back to no quiesce (as M0-M1b), with "not quiesced" in every run note.
- An Oops: the watchdog recovers it (m2-runs.md:126-133). Record it, and the owner decides.

### 6.5 Each run (one kimg): M1b's loop plus three steps

1. **PC:** stop any previous COM3 capture (the port is exclusive). Start a new one **from PowerShell** at 115200 8N1 into `com3-<img>-<utc>.log`, and keep it running until L4T is back (m2-runs.md:135-137).
2. **Board:**
   - `sha256sum ~/<img>.kimg` equals the PC value;
   - record `boot_id` and `uptime`;
   - if uptime is about 2 h or more, reboot L4T first. Linux oopsed in its own shutdown twice after hours of uptime (m2-runs.md:126-133; m1b-runs.md:54-58); the threshold is a HYPOTHESIS.
3. **Board (O5):**
   1. `for p in policy0 policy4; do echo performance | sudo -n tee /sys/devices/system/cpu/cpufreq/$p/scaling_governor >/dev/null; done; sleep 2`
   2. Record the §4.3 fields.
4. **Board (O4):** P1 steps 1-3 and the `/proc/iomem` read, identical on every run, with every `rc` recorded.
5. **Board:** `sudo -n kexec -s -l ~/<img>.kimg && cat /sys/kernel/kexec_loaded && sudo -n systemctl kexec`.
6. **PC:** poll ssh with `-o ServerAliveInterval=3 -o ServerAliveCountMax=2` under `timeout`, until it answers **and** `boot_id` has changed. Give up 20 minutes after the kexec: the 900 s guard, plus Linux shutdown and relocation of about 169 MB (duration UNKNOWN), plus an L4T boot of about 80 s (m1-first-procnto.md, "about 80 s after the launch").
7. **Board after the return:**
   - `sudo -n cat /sys/fs/pstore/console-ramoops-0 > ~/<img>-<utc>-blackbox.log`, and record its size.
   - `cat /sys/devices/platform/bus@0/c360000.pmc/reset_reason`: `MAINSWRST` is the image's own reset, `BCCPLEXWDT` the watchdog.
   - Check for `T234-SHIM` and for new `dmesg-ramoops-*` records. No shim text plus a new Oops means Linux died before the jump: retry from a fresh boot and do not judge the image.
8. **Copy** the black box and the COM3 log to `results/orin-native-port/<utc>/m3/` (private).
9. **No return within the bound:** read COM3 first (with nothing resetting, the TCU drains fully), then power-cycle, and record that the black box was lost.
10. **Run note** as §4.6, with a verdict against §8.

**Typical duration:**
- the Linux shutdown and relocation: UNKNOWN, about 30-60 s estimated;
- the QNX side, about 200 s: census and rates about 7 s; integrity and disk about 10 s; the window about 25-60 s; the grace until launch + 90 s; IPC about 3 s; teardown, integrity and rates about 12 s; prints about 10 s;
- L4T, about 80 s.

That is roughly 5-6 minutes per run, and the required ladder (R0, R1, R2, T1-T5) is eight runs.

**Validity rule, fixed before the first run:**
- A run that never reached QNX is retried with the same kimg and recorded as a host-side failure. That covers no `T234-SHIM`, a Linux oops in its shutdown, and `BAD-LANDING` (on the latter, stop and take K1).
- A run in which QNX started counts. A failed T-run is never replaced. Fewer than five banners from T1-T5 is an M3 fail (plan:377-379).

### 6.6 Order and gates

| Run | Image | Pass means | Then | On fail |
|---|---|---|---|---|
| **P0** | — | §6.3 step 4 accepts the kimg | P1 (O4) or R0 | §7 kexec rows; K1 |
| **P1** | — | §6.4 gate | R0 | O4 fallback, recorded |
| **R0** | `m3-r0` | **Landing and startup:** no `BAD-LANDING`. M1b §8 criteria 1 and 3-7 for N=4: the VHE line; four `el2-host HCR_EL2` lines and four `hvtimer … verdict=wired`; `t234: all 4 cpus parked in smp_spin`; `SMPCHECK census tick=ok`, `SMPCHECK CENSUS PASS`.<br>**Script:** `T234 M3 r0 -P4: procnto up`; `BWAIT guard armed secs=900`; `M3 STATE` in order through `end` with `FAIL_STATE none`; three `CHECK md5_pre … ok`; `CHECK disk_copy ok`; `BWAIT path hit=/dev/qvmdisk0`; **G-MEM** on `M3 MEM disk`; a `BWAIT run prog=qvm-check` line (any `rc`, recorded).<br>**Stamps:** `qvm_launch`, all nine fake-guest labels in non-decreasing `cycles=`, and `eof`; `BWAIT run prog=qnx-host-client` with `rc≠0` or `killed=1` (no guest, as expected); two `CHECK md5_post … ok`; eight `rate=` lines.<br>**Gates:** **G1**; `MAINSWRST` | R1 | Stopped before `procnto up` or at the census: C1. A tool, ksh or buildfile error: fix, rebuild every image, rerun R0. G-MEM: O7. `BAD-LANDING`: K1 |
| **R1** | `m3-r1` | §8 items 1-7 and 9-12, as adapted for R1 after item 12 (boot mode, no IPC). qvm launches, the real banner is stamped, qvm is alive until teardown, and `md5_post` passes. The echo server's line is recorded, present or not (§4.1). A `server: open(/dev/vcon2)` or `cio_set_raw` error in the guest text takes the §7 echo-server row before R2 | R2 | §7. A silent or partial guest with qvm alive: D1. A disk-path failure: D2. qvm refuses to start: fix per the qvm rows. The `-P4` host itself: C1 then C2 |
| **R2 (Q)** | `m3-r2` | All §8 criteria (items 1-12), plus **G2** | T1 | §7; fix and rerun Q. Q never counts |
| **T1-T5** | `m3-r2`, the same kimg as Q | All §8 criteria on each run | **M3 met** when all five pass | Per the validity rule: record and stop; M3 fails at fewer than 5 banners |

**Contingencies** (run only on their branch):

| Id | Image | When | Pass means | Record as |
|---|---|---|---|---|
| C1 | `m1b-p4`, existing and never run; kimg sha256 `0816e5f7ecbf820d99a39c24de5bef2e6b96c3df18e19b1a40de34dc8fc268cb` (VERIFIED today) | R0 fails before `procnto up` or in the census | M1b §8 at N=4 | Passes: the M3 payload is the cause (size, landing, memory, script). Fails: the `-P4` el2-host path itself; go to C2 |
| C2 | `m3-r0-p6`, then `m3-r1-p6` (built on demand) | `-P4` unusable | As R0/R1 at N=6 | Placement becomes "`-P6`, vCPU unpinned, last CPU recorded". Owner decision before any T-run |
| D1 | `m3-d1` | R1: qvm alive with no guest output, or output that stops with no qvm message | qvm prints the unsupported instruction or register and the guest state, then exits ([unsupported] `abort`) | Diagnostic, never timed. The finding answers plan §8 #5 |
| D2 | `m3-d2` | R1 fails in the disk path: `No system file system`, `Unable to access /dev/hd0`, or a virtio-blk message | `g_startup_complete` stamped; no banner expected (C1) | Diagnostic: separates qvm, guest kernel, virtual GIC and timer from the disk path |
| K1 | the same kimg through `sudo -n kexec -c -l ~/<img>.kimg -i` | `BAD-LANDING` on the `-s` path, or P0 step 5 shows another address | The shim's landing check passes | "kexec_load path, purgatory checks skipped (`-i`)". The DTB then lands right after the image, inside the window (m0-kexec-acceptance.md:45-51), where startup's `avoid_ram` covers it (board/main.c:247-249) |
| M1 (O7) | `m3z-*` (the disk carried gzip'd, gunzipped into `/dev/shmem`), or a RAM-window startup change | G-MEM fails, or qvm `rc=64` | As R0 with the gzip'd disk | See O7 and the verification below |

**If a RAM-window startup change is ever chosen** (O7, second option), none of it is designed or needed now:
1. A new board option, off by default, adds one `add_ram` range derived from P1's post-rmmod `/proc/iomem`. It never includes 0xBE000000-0xC1FFFFFF or the reserved `fbfe0000-fffdffff` child (raw/orin-iomem.txt:184-185; board/init_raminfo.c:45-58).
2. The build-board.sh symbol gate passes.
3. With the option off, `m1b-p6` is rebuilt with the new startup and run once. Its black box, normalised as M1b's R0 normalised against M2's R4, must equal M1b R2's, apart from the startup-size-dependent addresses.
4. Only then does R0 run again with the option on. Every M3 number from then on carries the new startup sha256, and the change is recorded as a startup deviation.

---

## 7. Failure-signature table

Each row is keyed on the last distinctive line in the black box, `/dev/shmem`-derived prints included, or on COM3. M1b §7 rows still apply to startup and the kernel unchanged; they are referenced, not repeated.

**Linux side and kexec**

| Observable | Meaning | Next step |
|---|---|---|
| P0 `kexec -s -l` `rc≠0` (EINVAL, ENOMEM, EFBIG) | `kexec_file_load` rejected the image | Check build-shim's header check and board free memory; try the K1 acceptance with `-c … -i`; record |
| No `T234-SHIM` in the black box, a new `dmesg-ramoops` Oops, PMC `BCCPLEXWDT` | Linux died in its own shutdown before the jump | Retry from a fresh L4T; not a run (validity rule) |
| An `rmmod` with `rc≠0`, or an Oops during step 4 | Quiesce failed | Record; keep every run identical; O4 fallback |
| `BAD-LANDING pc=… expect=…`, then a reset | The ~169 MB image was not placed at 0x80080000 (C17) | K1 |
| Black box ends at `JUMP`, or any M1b §7 startup or kernel row | Startup and the kernel as in M1b | M1b §7; then C1 |

**The IFS script and host tools**

| Observable | Meaning | Next step |
|---|---|---|
| `Unable to start "<tool>" (83)` | A shared library that tool needs is missing (ELIBACC; format at m1-first-procnto.md:56-62) | Add the library from the qhvh lists; rebuild; rerun from R0 |
| No `BWAIT guard armed` line | This run is unguarded | Finish, then fix before the next run |
| `SMPCHECK census tick=dead …` | CPU0's clock is dead (M1b row) | M1b §7 |
| `M3 FAIL preflight /dev/ptyp1` or `/dev/ttyp0` | devc-pty is not up | Look for `Unable to start "devc-pty"` (libsecpol, m2.build.in:179-182) |
| `M3 NOTE no /dev/slog` | slogger2 did not start | Continue; qvm internal errors will be missing from slog. Fix before Q |
| A `ksh:` error line (syntax, `not found`) | Template or link-list error | Fix `m3-host.ksh.in` or the toybox links; rebuild; rerun R0 |
| `M3 FAIL md5_pre guest`, `disk` or `conf` | The IFS in RAM differs from what the PC built, although the kimg sha256 matched before kexec: corruption between the kexec load and the launch (relocation or DMA, plan §8 #6) | Stop. Record. Adopt quiesce (O4). No timed run until explained |
| `M3 FAIL disk_copy`, with `cp.err` showing ENOSPC or ENOMEM | Not enough RAM for the copy | O7 |
| `M3 FAIL disk_copy`, with `cmp` reporting a difference | The shmem copy was corrupted | As the `md5_pre` row |
| `M3 FAIL disk_dev` | No `/dev/qvmdisk0`: devb-loopback failed, most likely io-blk.so, cam-disk.so or libcam.so.2 (UNKNOWN dependencies) | Read the lines before it; fix the list; rerun R0 |
| `M3 MEM disk` below 560 MB | Budget broken (§3.5) | O7 before R1 |
| `BWAIT run prog=qvm-check rc=1` or `rc=2` | "Not set up" or "inconclusive" ([qvm-check]) | Record `qc.out`. Continue: R1 shows whether qvm runs anyway |
| `BWAIT guard deadline=900 expired: sysmgr_reboot` | A command outside `bwait` stalled (devb-loopback, `pidin`, `slay`; §3.7 caveat 1), a bound is missing, or the grace timer died in a run already near its bounds (§3.7 caveat 2) | The last `M3 STATE` names the step; fix before the next run |

**qvm start and the guest**

| Observable | Meaning | Next step |
|---|---|---|
| `rc=127` with `STAMP exec-failed errno=…` in the stamps file | qvm could not be executed (path, permissions, interpreter) | Check the image list |
| Guest stream holds a runtime-linker failure (text containing `Could not load library`, exact text HYPOTHESIS) and a non-zero `rc=` | A library qvm needs is missing | Add from the qhvh lists; rebuild |
| `[g2.conf:<n>] …` in the guest stream and `rc=65` | Fatal configuration error at line n ([errcodes]), e.g. a vdev not found or a hostdev refused (the form of `logs/qhv-tcg-host-and-guest-boot.log:60`) | Check the vdev `.so` names, `/dev/ptyp0`, `/dev/qvmdisk0` |
| `rc=64` | Fatal before the guest started, e.g. out of memory ([errcodes]) | `M3 MEM`; O7 |
| `rc=96`, `5`, `6` or `7` | Fatal after the guest started; unsupported operation; vdev error; unexpected ([errcodes]) | Record guest text and slog; D1 |
| Only `qvm_launch` stamped, empty guest stream, `BWAIT path timeout secs=240`, no `rc=`, `M3 STATE diag` | qvm is alive, but no guest console byte ever arrived: stage-2 entry, guest vector or timer, or pl011 emulation (plan §8 #5) | slog, the pidin listing (a vCPU thread's state and CPU); D1 |
| Guest text stops, and the last stamp names the phase: before `g_first`, or between `g_first` and `g_devb` | Guest kernel or early driver stall: interrupt or virtual-timer delivery under qvm (EL1 virtual timer INTID 27; GIC maintenance interrupt INTID 25, UNKNOWN whether used) | D1 |
| `Unable to access /dev/hd0`, `No system file system, giving up.` | virtio-blk path (vdev, loopback, IRQ 41) | Check the `md5_pre` and `disk_copy` lines; D2 |
| `Startup complete` with no `QNX qnx-guest` | `uname` not runnable: `/system` not mounted (C1) | As the previous row |
| `Unable to access /dev/random` in guest text | The guest's `random`, which has no `-l` source (qhvg/startup.sh:39-40), was not up within 5 s. Never seen on TCG | Record. It adds up to 5 s inside `g_net − g_devb`; not an M3 failure if the banner follows |
| `g_ifup − g_net` far beyond about 20 s, or no `g_ifup` | io-sock or if_up behaves differently natively | Record; the headline is still valid if the banner follows |
| Guest kernel shutdown or exception text in the guest stream | The default `register fail` or `instruction fail` delivered an exception ([unsupported]) | D1 (`abort` names the register) |
| STAMP lines with identical `cycles=` and `bytes=` for two labels | The markers arrived in one chunk (pl011 batching or pty chunking) | Not a failure. The later label's time is an upper bound shared with the earlier one; record |
| A STAMP with `cps≠31250000` | Wrong image or syspage | Invalid run; check the image |

**Echo server and IPC**

| Observable | Meaning | Next step |
|---|---|---|
| Banner present, no `g_srv`, and the guest text holds `server: open(/dev/vcon2): …`, `server: cio_set_raw(…)`, or no vcon2 | The second `devc-virtio` failed natively (C9) | IPC will fail; record; owner decision before the next rung (R2 after R1, T1 after Q) |
| Banner present, no `g_srv`, and no server error line; the readiness line is absent or interleaved with another guest line | The server's unsynchronised print was broken or not yet written (§4.1; seen once on TCG) | Not a failure: §8 item 8 decides. Record the guest text around `=== starting qnx-echo-server` |
| `g_srv` stamped after `g_startup_complete`, after `banner`, or after `ipc_start` | The background server reached its print late (R37) | Not a failure. Record the signed offsets (§4.6). If it came after `ipc_start`, read it alongside the client's first-exchange lines |
| `client: open(/dev/ttyp0): …` or `cio_set_raw` error | Problem with pty pair 0 | As the preflight row |
| `client: iter N: read timeout; sentinel-kick round` then `recovered real echo`, and `rc=0` | The known stall occurred and was recovered | Completed with recovery (§4.4); record the counts |
| `client: unrecoverable stall at iter N` or `sentinel-recovery exhausted`, `rc=1` | The link stalled beyond recovery | IPC criterion fails for this run |
| `BWAIT run prog=qnx-host-client … killed=1` | The client outlived 240 s, most likely in its unbounded write | IPC fails; record |
| `client: echo seq mismatch at iter N` with both frame dumps | Alignment corruption (client.c:357-370) | IPC fails; record the bytes |

**Teardown, reset and records**

| Observable | Meaning | Next step |
|---|---|---|
| Two `BWAIT path timeout` lines after `slay` (qvm will not exit on SIGTERM or SIGKILL) | qvm is stuck in the kernel | Record; `shutdown` or the guard resets |
| `M3 STATE end` and the resetting banner, then no reset until `BWAIT guard deadline=900 expired` | `shutdown -S reboot` did not reach PSCI with qvm or devb-loopback present | Record; the guard's reset keeps the black box |
| No reset even after that | Kernel-level hang | Power cycle; COM3 only; residual |
| `M3 FAIL md5_post …` | IFS bytes in RAM changed during the run | Flag the run's numbers as suspect; record; O4 |
| A kernel `Shutdown[…]` dump on COM3 or in the black box, then a warm reset | Host kernel abnormal termination, reset through `-A` (C15) | Record the dump; D1. Without `-A`: spin, power cycle, COM3 only |
| COM3 silent, no reset | Interrupts masked on every core | Power cycle; the black box is lost; residual |
| Black box of 65,500 B or more | The cap was hit; head only | The tail comes from COM3; rebuild at `-vv` per G1 or G2 |
| STAMP or IPC lines differ between the black box and COM3 | A TCU drop or capture loss (both are silent) | The black box is the record of the numbers; flag in the run note |

---

## 8. Pass criteria (observable in the black box, cross-checked on COM3)

**Every counted run T1-T5, and Q (R2), passes when all of the following appear, and nothing from item 12 does.**

1. **Landing and startup (M1b's criteria at N=4):**
   - `T234-SHIM EL=2`, then `JUMP`;
   - `Enabling EL2 host hypervisor support (VHE)`;
   - for N = 0..3, `t234: cpu N el2-host EL2 HCR_EL2=…` with bits 34 and 27 set, and `t234: hvtimer cpu N verdict=wired`;
   - `t234: all 4 cpus parked in smp_spin`, then `Starting next program`.
2. **User space and the guard:**
   - `T234 M3 r2 -P4: procnto up`;
   - `BWAIT guard armed secs=900`;
   - `SMPCHECK census hyp qtime_intr=28 hypinfo_flags=0x1`, `SMPCHECK census tick=ok`, `SMPCHECK CENSUS PASS`.
3. **The image records its own fields, as the plan requires** (plan:377-378):
   `M3 CONFIG rung=r2 mode=full startup='startup-t234-orin-nano -vvv -P4 -Q enable,el2-host -m992M -Wkeep -A -Dtcu' q=el2-host w=keep A=1 cpus=4 guest_sha256=968029316b940f53580228f44e393877e032e251d78f3c752600cae726a7cf4f disk_sha256=cf5b06d0b3cb524201c71440fdda42a18d2636d45938acd8ec95cfa21314216b conf_sha256=<generated> client_sha256=52cb4dcad5a3632f88092289ef68668cc1fc604f150f3e2f8b9f31dc82caa7eb clock=unverified`
   - That covers the startup options, `-Q` mode, guest sha256 and `-W` policy.
   - The CPU MHz field is `clock=unverified` here, plus the §4.3 field in the run note.
4. **Integrity and disk:** `M3 CHECK md5_pre guest ok`, `M3 CHECK md5_pre disk ok`, `M3 CHECK md5_pre conf ok`, `M3 CHECK disk_copy ok`, `BWAIT path hit=/dev/qvmdisk0`.
5. **The number:**
   - `STAMP qvm_launch cycles=<a> cps=31250000 cpu=<c> …` and `STAMP banner cycles=<b> cps=31250000 cpu=<c> …` with b > a;
   - the guest stream printed in S12 contains a line matching `QNX qnx-guest 8[.]0[.]0 .*ARMv8_Foundation_Model aarch64le`, the TCG banner (`windows-qhv-tcg-boot-timed1.log:121`).
6. **Guest phases:** `g_first`, `g_devb`, `g_net`, `g_ifup`, `g_sshd`, `g_misc`, `g_startup_complete` stamped with non-decreasing `cycles=` in that order, each at or below `banner`.
   - **Why the order is safe to check.** The guest fixes it: each of these lines comes from a foreground step of one script chain (qhvg/ifs.build:57-61; qhvg/startup.sh:9-69; qhvg/start_net.sh:3). Needles first found in the same chunk share that chunk's reading (§3.8.1). The chain held in all 12 TCG captures (§4.1).
   - A missing `g_ifup`, `g_sshd` or `g_misc` is recorded as an anomaly with the guest text. The headline stands, provided criterion 5 holds.
   - **`g_srv` is recorded, never gated** (revision 2). This covers both its presence and its order.
     - The guest starts the server in the background and never waits for its line.
     - One TCG run lost the line to interleaving while its IPC completed cleanly (§4.1, R37).
     - In Q and T1-T5, item 8 is the evidence that the server was up.
     - The offsets, or `g_srv absent`, go in the run note (§4.6).
7. **qvm alive through IPC:**
   - no `rc=` line and no `QVM ended before teardown` before `M3 STATE teardown`;
   - `M3 MEM banner <n>MB/992MB` recorded;
   - both `pidin -p qvm -f abNli` listings present.
8. **IPC:**
   - `samples=<n> payload=48 cps=31250000`;
   - `P50=<x> ns  P99=<y> ns  Max=<z> ns`;
   - `sentinel_recoveries=<r> sentinel_bounces=<s> …`, with **n + r = 15**;
   - `BWAIT run prog=qnx-host-client rc=0 sig=0 killed=0 ms=<m>`.

   Clean when r = 0, completed with recovery otherwise (§4.4).
9. **After the run:** `M3 CHECK md5_post guest ok`, `M3 CHECK md5_post disk ok`.
10. **Rates:** four `SMPCHECK done cpu=i … rate=` lines before and four after. Recorded; a run with any core above 2 % drift is flagged, not failed.
11. **End and reset:**
    - `M3 FAIL_STATE none`, `M3 STATE end`, `T234 M3 r2 -P4: resetting so the log can be recovered`;
    - L4T answers with a new `boot_id`, PMC `reset_reason` `MAINSWRST`;
    - the black box is intact and under 60,000 B;
    - every STAMP and IPC line is identical on COM3, CR-stripped.
12. **None of these tokens:**
    - M1b §8 item 10's full list (`t234: EL1`, `t234: EL2`, `hvtimer STOP`, `ASSERT`, `start failure`, `start timeout`, `tick=dead`, `CENSUS FAIL`, …);
    - `M3 FAIL`, `BWAIT guard deadline`, `STAMP exec-failed`, `STAMP read-error`, `Unable to start`, `[g2.conf:`, `Could not load library`;
    - `unrecoverable stall`, `sentinel-recovery exhausted`, `echo seq mismatch`, `killed=1`;
    - `No system file system`, `Unable to access /dev/hd0`, `BAD-LANDING`, `Shutdown[`.

**R1** passes on items 1-7 and 9-12, with `mode=boot` and `rung=r1` in items 3 and 11. Item 8 does not apply. Item 7 needs only the S7 `pidin -p qvm` listing, because boot mode skips S8, which prints the second (§3.7).
**R0** passes on its §6.6 row.

**M3 is met** when Q passed and **T1, T2, T3, T4 and T5 each pass** with the identical kimg. That is the banner on 5 of 5, every field present, and the IPC pair completing its 15 timed iterations.

**M3 is not met** if any T-run lacks a criterion; the record names which. Fewer than five banners is the plan's own fail (plan:379). Report exactly which criteria each run met, and never substitute a run.

---

## 9. Risks: every HYPOTHESIS or UNKNOWN the design rests on, and the run that answers it

| # | Assumption | Class | Answered by |
|---|---|---|---|
| R1 | `kexec_file_load` places the ~169 MB kimg at 0x80080000, the span being free in memblock | HYPOTHESIS (upstream v5.15 walk, NATIVE_QVM_HOST K3; placement VERIFIED only for 2.7 MB images) | P0 step 5 if dynamic debug exists; R0 (no `BAD-LANDING`); K1 otherwise |
| R2 | Linux shutdown and relocation of ~169 MB finish in reasonable time | UNKNOWN | R0 return time |
| R3 | M3 fits `-m992M` with ~111 MiB of headroom | HYPOTHESIS (§3.5) | R0 `M3 MEM disk` (G-MEM); R1 `M3 MEM banner`, no `rc=64` |
| R4 | `-P4` under el2-host boots: a subset of M1b R2's six cores, never run as such | HYPOTHESIS | R0; C1 |
| R5 | `[+raw]` keeps the guest IFS and disk byte-identical inside our IFS | VENDOR_CLAIM ([mkifs]) | Generator step 14 (VERIFIED at build time) |
| R6 | Runtime libraries needed by qvm, the vdevs, devb-loopback, slogger2 and our tools are in the image | UNKNOWN (not readable under the licence) | R0 (devb-loopback, slogger2, tools); R1 (qvm, vdevs) |
| R7 | devb-loopback returns to the shell, as on TCG | VERIFIED on TCG (post_start.custom:31-32); native HYPOTHESIS | R0. If not, only the 900 s guard bounds it |
| R8 | QNX 8 ksh supports the §3.7 constructs: functions, `read -r`, `${x#…}` and `${x%%…}`, subshell redirection, `&`, `!`, `\|\|` groups | HYPOTHESIS | R0 |
| R9 | toybox `cp`, `cmp`, `md5sum`, `head -c`, `tail -c`, `wc -c`, `grep -q` and `grep -E` behave as standard toybox | VENDOR_CLAIM (applets listed in the QNX-generated build, qhvh/system.build:131-204) | R0 |
| R10 | devc-pty provides pair 1, and a master `read` returns EOF once the slave's writers close | VENDOR_CLAIM (8 pairs, [devc-pty]); EOF UNKNOWN | R0 (`STAMP eof` after `cat` exits); R1 teardown |
| R11 | qvm's pl011 output to a tty stdout arrives without batching | HYPOTHESIS (TCG observation, C6) | R1: distinct `cycles=` and `bytes=` per label |
| R12 | The reader's latency is small against the interval | HYPOTHESIS | R1/Q: `banner − g_startup_complete` (one `uname`) against TCG's 0-110 ms; the `mono_ns` cross-check |
| R13 | Host `ClockCycles()` reads one counter on every core while qvm programs guest offsets | VENDOR_CLAIM (Arm ARM, E2H and TGE); `cntvoff` 0 at M1b (m1b-runs.md:111) | `cpu=` and `mono_ns` on every STAMP line |
| R14 | qvm arms stage-2, the virtual GIC (list registers, maintenance INTID 25) and the guest's EL1 virtual timer (INTID 27, which ticked natively under `-Q disable`, m1b-runs.md R0) on A78AE under our startup | HYPOTHESIS / UNKNOWN (plan §8 #5) | R1; D1 |
| R15 | Every A78AE system register the guest touches is handled, given the default `register fail` | UNKNOWN ([unsupported]) | R1; D1 |
| R16 | The shmem vdev is inert for this guest | HYPOTHESIS (C2) | Not tested; O1 |
| R17 | The guest's `random`, with no `-l` source, is up within 5 s natively | HYPOTHESIS | R1 guest text |
| R18 | The if_up burn is about 19-20 s by the documented defaults, or short as findings.md infers | CONFLICT (C7) | R1: `g_ifup − g_net` |
| R19 | The guest's foreground `io-usb-otg` returns promptly | HYPOTHESIS | R1: `g_startup_complete − g_misc`, less its `sleep 1` |
| R20 | The two `devc-virtio` instances on one virtio-console cause the stray bytes or stalls | HYPOTHESIS (C9) | Sentinel counts in Q and T1-T5; not settled by M3 |
| R21 | No stale DMA writer corrupts the window after kexec | HYPOTHESIS (plan §8 #6) | `md5_pre`, `disk_copy` and `md5_post` every run; P1 |
| R22 | rmmod of the four NVIDIA modules succeeds without an Oops | UNKNOWN | P1 |
| R23 | The `performance` pin survives the kexec path on cluster 0; the 76.8 MHz grid fit | HYPOTHESIS (§4.3) | P0 step 1 (grid); R0 rate lines (~666 M it/s predicted) |
| R24 | With `-A`, a host-kernel abnormal termination resets | VERIFIED (library) plus VENDOR_CLAIM ([callout_reset]) | Only on a crash |
| R25 | `sysmgr_reboot()` from the guard resets, even with qvm wedged | UNKNOWN | Only on expiry |
| R26 | `shutdown -S reboot` resets with devb-loopback running and qvm stopped | HYPOTHESIS | R0 (devb-loopback running); R1 |
| R27 | qvm exits on SIGTERM from `slay` | VENDOR_CLAIM (slay sends SIGTERM by default, [slay]); qvm's reaction UNKNOWN | R1 teardown `rc=` |
| R28 | The IPC client binary is the one the TCG host carried | HYPOTHESIS (mtime, §3.1) | Not checkable without opening disk-qemu; hash recorded |
| R29 | The native qvm and vdev files equal the TCG host's copies (same SDP install) | HYPOTHESIS | Not checkable under the licence; hashes recorded |
| R30 | Black-box budget of about 27 KB typical, under 45 KB worst | HYPOTHESIS (§4.5) | G1 (R0), G2 (Q) |
| R31 | The Wi-Fi transfer of ~169 MB completes | UNKNOWN (one earlier drop) | §6.2 |
| R32 | The guard at `SCHED_RR` priority 50 runs on time under a busy vCPU | HYPOTHESIS | Only on expiry |
| R33 | The 2 h uptime precaution avoids Linux's shutdown Oops | HYPOTHESIS (two events) | §6.5 step 7 check on every run |
| R34 | Pristine against TCG-mutated guest-disk state does not change timing | UNKNOWN | Not tested (O8) |
| R35 | io-blk's default cache stays within budget | VENDOR_CLAIM ([io-blk]) | R0/R1 MEM lines |
| R36 | The IPC outer bound of 240 s is enough for a run that recovers | VERIFIED arithmetic (§4.4: ≥10 s per stall; about 61 s for a dead link) | Q, T1-T5 `ms=` |
| R37 | The echo server's readiness line reaches the host intact, before `Startup complete` | HYPOTHESIS. It held in 11 of 12 TCG captures. The guest does not synchronise it (qhvg/post_startup.sh:29), and `qhv-tcg-rq2-shmem-roundtrip-attempt1-bus-error.log:49-51` lost it to interleaving (§4.1) | Recorded in R1, Q and T1-T5 as the §4.6 offsets; gates nothing (§8 item 6) |

---

## 10. Must not be claimed from a pass

**What the number is not**
- **Not a per-exit, world-switch or trap latency.** That is M4, still blocked on the K11 dry run (plan:94).
- **Not the twin's launch-to-banner headline.** The native host boot is not comparable to the emulated one.
- **Not a host-only or one-variable diff against either TCG leg,** and not a hardware-over-TCG speedup. The bundle differences include:
  - EL2 VHE on A78AE silicon against QEMU-emulated EL2;
  - four physical cores against two emulated;
  - kexec entry;
  - a minimal host service set against mkqnximage's full set;
  - the host's procnto options;
  - a pty and file console path against the emulated serial console;
  - a RAM-backed disk against qnx6 on emulated virtio-blk;
  - an io-blk cache of about 21.8 MiB against about 43 MiB;
  - a pristine against a TCG-mutated guest disk;
  - no host rng.

  See plan §7 item 6.
- **Not a guest boot time,** not a property of QNX or qvm in general. The interval contains the guest's fixed waits (the if_up burn, `sleep 1`) and a guest configuration with no net or rng vdev.
- **Not at a controlled or known CPU frequency.** Rates are a proxy, and the field says `clock not verified`.
- **Not statistically significant at n=5.** And P99 is not a tail at n=15: it is the maximum by construction.

**What the IPC result is not**
- **Not a transport benchmark.** It is 15 timed iterations per run over a pty and virtio-console, quantised to 32 ns.
- **Not a verdict that the ~1-2 % stall is or is not a TCG artefact.** Only the sentinel counts are evidence, and five runs of 15 iterations cannot settle a hazard of that size.

**What the host is not**
- **Not a supported QNX Hypervisor platform,** and not NVIDIA DRIVE OS, the NVIDIA hypervisor stack, QNX OS for Safety or any ASIL or isolation property.
- **Not general.** Nothing beyond this SKU, L4T R36.4.7 firmware, SDP 8.0.4 build, one board and one guest.
- **Not proven free of stale DMA.** The md5 and `cmp` canaries detect corruption of the checked files only.
- **Not proof that qvm needs nothing more** for other guests: Linux, multiple vCPUs, virtio-net, pass-through, SMMU.
- **Not identical to the TCG host's qvm, vdevs or client,** unverified (R28, R29); **not identical guest-disk bytes** to the TCG series (C22).
- **Not a firmware boot.** kexec residue is inherited (plan §7 item 1).

**Recovery and publication**
- **Not "every failure is recoverable".** A hang before the IFS script, or with interrupts masked, still costs a power cycle and the black box.
- **Not publishable** before the supervising professor is consulted (NC QDL v7 4.6(i)).

---

## 11. Owner decisions

| # | Decision | Options | Recommendation and reason |
|---|---|---|---|
| O1 | Guest configuration | (a) the as-run four-vdev text with the load path substituted; (b) the committed three-vdev text | **(a).** It is what every timed TCG `qvm_launched → guest_banner` segment ran (C2), and the shmem vdev is inert for this guest. If (b): record "differs from every timed TCG segment by the shmem vdev" |
| O2 | Host CPUs | (a) `-P4`, cluster 0 only; (b) `-P6` with qvm under `on -R 0xf`; (c) `-P6` unpinned, placement recorded | **(a).** One cpufreq policy, no cluster-1 factor, configuration untouched. (b) depends on UNKNOWN vCPU runmask inheritance ([cpu] documents only `cluster` and `sched`); (c) mixes a roughly 8-12× slower cluster into the spread (C10) |
| O3 | `-A` on the startup line | (a) add it to every M3 image; (b) keep M1b's option set | **(a).** A host-kernel abnormal termination under qvm is a new failure class at M3. Without `-A` the reboot callout spins with interrupts masked (lib/aarch64/callout_reboot_psci.S:42-58), which costs a power cycle and the black box. The normal path ignores the flag ([startup_options]) |
| O4 | DMA quiesce before every kexec | (a) `isolate multi-user.target` plus rmmod of `nvidia_drm nvidia_modeset nvidia nvgpu`, identical every run, after the P1 rehearsal; (b) the M0-M1b hand-over unchanged | **(a).** M3 is the first run that fills most of the window (plan:169, K5; forum precedent in research-kexec-tcu.md). The md5 canaries detect corruption but do not prevent it. If P1 shows rmmod failing: (b), recorded on every run |
| O5 | Governor | (a) `performance` on both policies before kexec; (b) `schedutil` as in M1b | **(a).** Run-to-run consistency, runtime-only; the QNX rate proxy tells whether it held (§4.3) |
| O6 | When the IPC client starts | (a) at qvm launch + 90 s, as the cloud leg; (b) right after the banner | **(a).** It reproduces the cloud's host policy (post_start.custom:37-52) and the guest's settled state. It costs about 60 s per run |
| O7 | Memory fallback if G-MEM fails or qvm exits 64 | (a) carry the pristine disk gzip'd, `gunzip` it into `/dev/shmem` at boot, and check the result by md5 (needs a toybox `gunzip` link, qhvh/system.build lists it); (b) a second RAM window, a startup change verified as §6.6 | **(a) first.** No startup change, and a QNX disk image measured about 40 % under `gzip -1` (sync-qhv.sh:92-93). Please confirm that compressing the QNX-generated disk image, a byte transformation like copying it into an IFS and not an inspection, is within the licence stance. **(b)** only if (a) still does not fit |
| O8 | Guest disk bytes | (a) the pristine `cf5b06d0…`, restored every boot; (b) reproduce the TCG series' mutated copy | **(a).** (b) would mean opening the TCG host disk image, which the licence rule forbids; the difference is recorded (C22) |
| O9 | Zero-board-cost TCG IPC baseline | (a) one Windows-TCG boot of the pinned image pair with `-snapshot` and without `-StopOnGuestBanner`; (b) none | **(a), not blocking M3.** The 968029 guest has never run the client on any leg (§4.4), so a native IPC anomaly would otherwise have no same-image comparison. `-snapshot` keeps the pinned disk bytes (results/qhv-images-SHA256SUMS.txt:1-3) |
| O10 | CPU MHz | (a) `clock not verified` plus the busy-rate proxy; (b) a startup PMCCNTR calibration | **(a) for M3.** (b) is a startup change, a new startup sha256 for every image, against rule 4. It belongs with M4's calibration (plan:391) |

---

## Appendix A. Stale text to correct later (list only; the orchestrator edits docs and other records)

**`docs/orin-native-port-plan.md`**
- **M3 (plan:364-379).**
  - "a `g2.conf` that is the cloud-leg config minus virtio-blk" (C1, C4).
  - `tracelogger`/`traceprinter` in the image list (C12).
  - "its CSV row printed over the TCU" (C13).
  - "`-Wdisable` or a `wdtkick` kicker" (C19).
- **Checklist 7 (plan:538).** "differs in exactly the two intended ways": it was diffed against the committed script, not the as-run build tree (C2), and its premise is wrong (C1).
- **§3.2 (plan:124).** "`image_size` = file size rounded to 2 MiB" (C18).
- **K11 (plan:94).** Add the guest disk's sha256 `cf5b06d0…216b`: byte identity of the guest includes its disk (C1).

**Other files**
- **`orin-native/shim/build-shim.sh:12`.** "rounded up to 2 MiB" (C18).
- **`orin-native/qhv/g2-noblk.conf:9-14`.** "the banner does not need a disk" (C1; §3.9).
- **`orin-native/tools/stamp.c:16-22`.** `/dev/ttyp0` usage examples (C5; §3.8.1).
- **`ipc-test/qnx-server/server.c:15-16` and `ipc-test/qnx-host-client/README.md:80`.** `/dev/vcon1` is not the guest's pl011 console (C9).
- **`orin-native/startup/m2.build.in:208-209`.** "cat, ls, echo and cksum are ksh built-ins in QNX 8": unverified, and the QNX-generated guest IFS links `cat` to toybox (qhvg/ifs.build:73).
- **`docs/findings.md:266-274`.** "the `if_up` burn is short": conflicts with the documented defaults (C7). Update after R1 measures it.
- **`scripts/qhv/extract-ipc-result.sh:52`.** TCG-only notes (§3.9).

---

## 12. Review outcomes (revision 2)

Three reviews read revision 1, and all three approved it with changes: one major issue and three minor ones. Each row was checked before its disposition was chosen, against:
- the design's own script and bounds;
- `orin-native/tools/smpcheck.c`;
- the guest build files and `ipc-test/qnx-server/server.c`;
- the plan;
- the TCG serial captures in `logs/sample-boot/`.

What did not change:
- No image, generator step, `bwait` bound, gate or rung.
- The host script, which is identical to revision 1's.
- The pass criteria, except §8 item 6 and the two R1 lines.

| # | Review | Severity | Issue | Disposition | Why |
|---|---|---|---|---|---|
| V1 | Review 1 | minor | The §3.7 worst-case terms do not derive from the States table: S2 and S11 are 23 s against "collector 20 s", and S12 is 20 s against 15 s. The banner-plus-IPC block should be 240 + 2 + 240 = 482 s, because the grace wait resolves at once. The corrected total is about 747 s. | **Applied, with a different total.** The 482 s block and the 747 s total are **rejected**. | **The issue holds.** Revision 1's sum could not be traced to the table. S2 and S11 are 20 s: the `rates` workers are started with `&` (§3.7), and the collector returns at its `-T 20` deadline whatever they do (smpcheck.c:1161, :1174). The grace term is 0, as the review says; revision 1 already carried no grace term.<br>**The 245 s term is right.** At its deadline `bwait -k` sends SIGKILL, then polls for up to 5 s more (§3.8.2). So the client costs 240 + 5, and S12's 20 is slog2info's 15 + 5. Revision 1 added that 5 s to those two terms but not to the other four `-k` bounds (S3, S4 twice, S5, S10).<br>**Counted consistently, the sum is 772 s,** against revision 1's written 755 (its terms add to 753) and the review's 747. The Bound column now shows every +5, the settle and the unbounded commands, and a term table derives 772 from it. The margin under the guard is 128 s, or 125 s after `smpcheck -z 3`, against revision 1's 145 s. |
| V2 | Review 2 | minor | The worst case omits devb-loopback, which runs outside `bwait` and is bounded only by the guard (R7). | **Applied, widened.** | **VERIFIED:** devb-loopback is called plainly (§3.7 script; §3.4 item 3), and R7 already said only the guard bounds it.<br>**Widened:** the same holds for the six `pidin` calls, up to three `slay` calls, the two `stamp -n` writes and the short prints, so caveat 1 names them all.<br>**Found while recomputing V1:** if the grace timer never ran, the grace wait runs to its own 100 s bound, for 872 s in all (caveat 2).<br>The §2 timeline row and the §7 guard row now say the same. §6.5 step 6 already sized its 20-minute give-up from the 900 s guard, so no procedure changed. |
| V3 | Review 3 | major | §8 item 6 requires `g_srv` and orders it before `g_startup_complete` and `banner`, but the guest starts the server in the background with no synchronisation. A run that delivers the banner and the 15 IPC iterations could fail item 6 and, under "a failed T-run is never replaced", cost the milestone. The plan requires no such order. | **Applied, going beyond the review's first option:** `g_srv` is recorded and never gated, for presence and order alike. | **VERIFIED:**<br>1. The server is started with `&` (qhvg/post_startup.sh:29).<br>2. post_startup.sh is startup.sh's last, synchronous step (qhvg/startup.sh:69).<br>3. The IFS script prints `Startup complete` and runs `uname -a` as soon as that returns (qhvg/ifs.build:57-61).<br>4. The server prints its line only after `open` and `cio_set_raw` (server.c:51-62).<br>5. The plan's pass list names only the banner, the fields and the 15 iterations (plan:377-379).<br>**The evidence goes further than the review.** In 11 of the 12 TCG captures that start this server, its line came before `Process count` and `Startup complete`. In `logs/sample-boot/qhv-tcg-rq2-shmem-roundtrip-attempt1-bus-error.log` it arrived after the post-`sleep 1` echo (:49-51), interleaved byte by byte with `gshm-probe`, so the needle occurs nowhere in the file. That run's client still printed `samples=15` and `sentinel_recoveries=0`, and exited 0 (:61, :64, :66). Revision 1 would have failed that run on presence alone, so moving `g_srv` out of the order check would not have been enough.<br>**What stays checked.** The seven chain needles keep their order check, because the guest fixes their order, and the chain held in all 12 captures (§4.1). §4.1's two `g_srv` segments became one chain segment plus recorded offsets, and R37 records the race. |
| V4 | Review 3 | minor | The worst-case sum uses 23 s for S2 and S11 against the table's 20 s. | **Applied** (with V1) | Same evidence as V1: the 3 s busy workers run beside the collector and do not extend its deadline, so each term is 20 s. |
| S1 | verification (self-found while applying V3) | minor | §6.6's R1 row said "§8 items 1-9 and 12 (boot mode, no IPC)". That contradicts §8's "items 1-7 and 9-12" and includes the IPC item. §8 item 7 also required both `pidin -p qvm` listings, but boot mode skips S8, which prints the second. | **Applied** | The script enters S8 only when `$MODE` is not `boot` (§3.7). §6.6 now cites §8's list, and the §8 R1 line says item 7 needs only the S7 listing. |

**Edited, by row:**
- **V1 and V4:** the §3.7 States-and-bounds table (the Bound column, plus a legend) and the worst-case paragraph, which is now a term table with its reasoning.
- **V2:** the §3.7 worst case (caveats 1 and 2); the §2 timeline row for the IFS script; the §7 guard row.
- **V3:**
  - the §4.1 segment table, where the two `g_srv` rows merged into `g_startup_complete − g_misc`, plus a paragraph on `g_srv`;
  - §4.6 item 6 and the §6.6 R1 row;
  - the §7 echo-server rows: one reworded, two added;
  - §8 item 6; §9 R19 and the new R37.
- **S1:** the §6.6 R1 row and the §8 R1 line.
- **Also:** the header.
