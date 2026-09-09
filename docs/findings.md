# Findings Log — append-only, newest at top

A running record of empirical findings, surprises, and decisions that
came out of actually running the toolchain. Phase 0 entries point to
their detailed write-ups; Phase 1+ entries will land here directly.

Format: one entry per finding, dated, one-paragraph max plus links.

---

## 2026-09-09 — QHV leg on the Orin: the hang was QEMU 6.2, not the host; the leg now boots on real ARM silicon — and a review found what the previous day's write-up got wrong

Two threads, kept together because the second corrects the first. An
adversarial review of the repo (map + consistency audit + eight refutation
attempts, two lenses per claim) was run against the previous day's path, and
the experiments it demanded were then executed. This entry supersedes the
"Orin half blocked on hardware" ending of the entry below and the
"cause not yet established" state of §1a in
[digital-twin-design.md](digital-twin-design.md).

**What actually happened on the Orin (2026-09-08 evening).** The board came
back, dropped off the network entirely mid-transfer (no ping, no SSH on the
/24; power-cycled; journald here is volatile so the cause is unrecorded), the
transfer was made resumable and completed with `sha256sum -c` passing, and
the leg was run. The QHV host booted — GICv3 ITS, slogger2, PCI, devb-virtio,
file systems — and stopped after `random: Could not initialize entropy.
[random.c(406)]`. **419 bytes at 300 s, 600 s and after 12 minutes**, process
alive: a hang. Curated:
[orin-qhv-tcg-q62-hang-blk-only.log](../logs/sample-boot/orin-qhv-tcg-q62-hang-blk-only.log).

**What the review found wrong, in order of consequence:**

1. *"Entropy starvation ruled out"* — **false.** The rng device had been
   added as the second `-device`; the image probes it at the third slot
   (`0xa003a00`, the 2026-07-28 finding below), and the test's own log still
   said `Unable to use devr-virtio.so`. Kept as
   [orin-qhv-tcg-q62-INVALID-rng-in-slot2.log](../logs/sample-boot/orin-qhv-tcg-q62-INVALID-rng-in-slot2.log).
2. *"A genuine one-variable comparison"* — **overclaimed.** The QEMU binary
   was never controlled (Windows 11.0.50 fork build vs. Orin stock 6.2.0),
   and even at equal release the build (compiler, flags, libraries) and the
   TCG backend (`tcg/i386` vs. `tcg/aarch64`) travel with the host. §1a now
   defines "host" as that bundle and stamps every controllable part.
3. *"QEMU 6.2's EL2 emulation is insufficient for QHV"* — **wrong mechanism.**
   The QHV host *is* the EL2 kernel and it boots eight-odd userspace
   services under 6.2 before stalling. What never arrives is `waitfor
   /dev/random`'s 5-second timeout message. The refined hypothesis —
   timeouts at EL2/VHE never fire — was then confirmed (below).
4. The authoritative log (this file) and CLAUDE.md still said the Orin half
   had never been run; §1a contradicted itself between adjacent paragraphs;
   the June curated log's header, `scripts/qhv/README.md` and §1a all told
   the reader to look for a **host banner that does not exist**; AGENTS.md
   still said "KVM enabled on A78AE; QEMU runs the QNX guest on bare arm64
   silicon". All corrected in this commit.
5. `disk-qemu` is a writable raw disk booted without `-snapshot`: it mutates
   on every run (rnd-seed, keys, logs), so `sha256sum -c` fails after the
   first boot and "byte-identical" held only at copy time. Both launchers
   now pass `-snapshot` and stamp it. Also found: the shipped `disk-qemu`
   carries the RQ-2 diagnostic `post_startup.sh` (`vdev shmem`,
   `hyp-shm-roundtrip` hook) that the committed `scripts/qhv/post_start.custom`
   does not — the 2026-07-28 claim that the build trees were regenerated
   from clean sources does not hold for the disk. Both hosts boot the same
   bytes, so the twin diff is unaffected; **the measured image is not yet
   reproducible from the repo**, and regenerating it will change every
   number, so that is a deliberate later step, not a quiet one.

**Experiments the review demanded, and their results:**

- Windows, rng correctly in slot 3 (`-netdev user,id=n0 -device
  virtio-net-device,netdev=n0 -object rng-builtin,id=rng0 -device
  virtio-rng-device,rng=rng0`): entropy init succeeds and launch → guest
  banner drops from ~49.2 s to **29.3 s** (n=5: 28,951 / 29,352 / 29,324 /
  29,311 / 29,333 ms; median 29,324, spread 401). The earlier Windows n=5
  therefore contained ~19–20 s of entropy-timeout artefact per run.
  [windows-qhv-tcg-rng-slot3-boot-times-n5.txt](../logs/sample-boot/windows-qhv-tcg-rng-slot3-boot-times-n5.txt).
- Orin, QEMU 6.2 + rng in slot 3: entropy succeeds, hang **moves** to
  `---> Starting Networking` (314 bytes at 240 s). Not entropy.
  [orin-qhv-tcg-q62-hang-rng-slot3.log](../logs/sample-boot/orin-qhv-tcg-q62-hang-rng-slot3.log).
- Orin, **QEMU v11.1.0 built from source** (`build-qemu-on-orin.sh`; ~9 min
  at `-j4`; needed `python3-venv` and `python3-tomli` on Ubuntu 22.04 beyond
  the obvious): **guest banner at ~78 s without rng, ~63 s with** — the
  hypervisor and its guest on real ARM silicon for the first time.
  [orin-qhv-tcg-q111-boot-blk-only.log](../logs/sample-boot/orin-qhv-tcg-q111-boot-blk-only.log),
  [orin-qhv-tcg-q111-boot-rng-slot3.log](../logs/sample-boot/orin-qhv-tcg-q111-boot-rng-slot3.log).
- Attributed cause, hypothesised from upstream history and **not observed**
  (no register dump, no reverted-wiring build): `v6.2.0`'s `hw/arm/virt.c` has **no
  `GTIMER_HYPVIRT` wiring** — the NS EL2 virtual-timer IRQ was connected in
  QEMU 9.0 (`1ec896fe7c`); `target/arm` gained `5709038aa8` "Don't apply
  CNTVOFF_EL2 for EL2_VIRT timer" in 10.0. A VHE hypervisor's `CNTV_*` is
  `CNTHV_*`. Not bisected: a `-machine virt-8.2` run on QEMU 11 still boots,
  but that compat flag only hides the IRQ from the device tree (per the
  source comment, for an old EDK2 bug) and leaves the wiring — so it was not
  a valid discriminator. Distinguishing 9.0's from 10.0's fix would need
  those builds; not needed here.
- **Non-VHE control (2026-09-09), supporting the host-side mechanism:** the
  same image under the same QEMU 6.2 on the same board with `-cpu cortex-a57`
  (ARMv8.0: EL2 but no VHE) gets *past* the hang point — `waitfor`'s timeout
  fires, networking and post_start run, `qvm` is launched
  ([orin-qhv-tcg-q62-a57-control.log](../logs/sample-boot/orin-qhv-tcg-q62-a57-control.log)).
  Without VHE the host cannot use the E2H timer redirection, which is exactly
  the path an unwired EL2 virtual-timer IRQ would break. The guest then aborts
  with `PE does not support PAUTH feature` — Cortex-A57 lacks Pointer
  Authentication, which the guest's `startup-armv8_fm` requires — a
  CPU-feature mismatch unrelated to timers. One run; it supports the
  mechanism for the host hang, it does not observe register state.
- **Reverted-wiring build (2026-09-09), decisive:** QEMU 11.1.0 rebuilt on
  the Orin with the single change of leaving the NS EL2 virtual-timer output
  unconnected to the GIC
  ([patch](../scripts/orin/patches/qemu-v11.1.0-unwire-ns-el2-virt-timer-irq.patch))
  **hangs at the same point as 6.2**; unpatched 11.1.0 boots the same image
  on the same board. One wire, one variable, opposite outcome
  ([orin-qhv-tcg-q111-nohypvirt-control.log](../logs/sample-boot/orin-qhv-tcg-q111-nohypvirt-control.log)).
  The mechanism is verified, not attributed: a VHE hypervisor host's
  timeouts ride on the EL2 *virtual* timer interrupt, which `virt` did not
  wire before QEMU 9.0 (`1ec896fe7c`).

**State of the leg now.** Orin column measured with the stamped instrument
(`WITH_RNG=1 ./launch-qhv-on-orin-tcg.sh 5`; QEMU 11.1.0 selected and
stamped; rng in slot 3; `-snapshot`; `sha256sum -c` passed before and after
the series): **n=5 = 63,676, 63,045, 63,107, 62,007, 62,673 ms, median 63,045, mean 62,901.6, spread 1,669 ms (2.6%)**.
[orin-qhv-tcg-q111-rng-snapshot-boot-times-n5.txt](../logs/sample-boot/orin-qhv-tcg-q111-rng-snapshot-boot-times-n5.txt),
[orin-qhv-tcg-q111-rng-snapshot-boot1.log](../logs/sample-boot/orin-qhv-tcg-q111-rng-snapshot-boot1.log).
Windows re-measured under the same device set and disk mode with the
timestamped instrument (still the 11.0.50 fork build): **n=5 = 28,734, 28,723, 28,688, 28,720, 28,692 ms, median
28,720, spread 46 ms** —
[windows-qhv-tcg-rng-snapshot-segments-boot-times-n5.txt](../logs/sample-boot/windows-qhv-tcg-rng-snapshot-segments-boot-times-n5.txt).
Headline ratio Orin/Windows ≈ 2.20×. **Read the segments before quoting that
ratio**: both guests burn a fixed `if_up -p -r 20 vtnet0` retry loop (no net
vdev in `g2.conf`), which sits inside the `qvm_launched → guest_startup_complete`
segment on both hosts and is host-independent; the review that demanded the
timestamps estimated it could halve the apparent ratio. The Orin series was then
re-run with the segment stamps (same configuration; the disk had to be
re-synced first because a snapshot-less probe had mutated it — the
pre-run `sha256sum -c` gate refused to measure until it was): **n=5 = 62,058, 62,031, 62,736, 62,524, 61,505 ms,
median 62,058, spread 1,231 ms** —
[orin-qhv-tcg-q111-rng-snapshot-segments-boot-times-n5.txt](../logs/sample-boot/orin-qhv-tcg-q111-rng-snapshot-segments-boot-times-n5.txt).

**Segment view (medians, ms from launch):**

| Segment | Windows (11.0.50) | Orin (11.1.0) | ratio |
|---|---|---|---|
| launch → host post_start | 6,093 | 13,430 | 2.20× |
| host post_start → qvm launched | 110 | 337 | — |
| qvm launched → guest banner | 22,514 | 48,452 | 2.15× |
| **launch → guest banner (headline)** | **28,720** | **62,058** | **2.16×** |

The review that demanded these timestamps expected the guest's fixed
`if_up -p -r 20` retry burn (no net vdev) to add ~20 s to *both* hosts and
so dilute the headline ratio by half or more. **The segments say otherwise:**
the host-boot segment — which, with net and rng presented, contains no
fixed wait at all — shows the same ~2.2× as the guest segment and the
headline. Had a 20 s host-independent constant been sitting inside the guest
segment, its compute-bound ratio would have been ~11×, not ~2.2×. So the
`if_up` burn is short (its retry interval was not measured directly) and the
headline ratio is *not* timeout-dominated. **This is still not a twin diff** — the Windows QEMU is a different build of a different
(development) version — but it is now a pair of series whose stamps
match on device set and disk mode, measured by the same instrument, on
the same bytes, with the fixed waits visible instead of buried. Windows column: needs
re-measuring under the same three stamps, and moving its QEMU to the
official 11.1.0 release is the remaining alignment, with the honest caveat
that "same release" is not "same build". Image pair at re-sync (copy-time SHA-256, before any `-snapshot`-less
boot):

```
b2d875057f25a4cbda69966e553629d445cfa44af62cf4c5e121442c9782300a ifs.bin
95849168b06e3c5d8e744db8bb8fdf39efd01d77f1b60d33060650292d7192a3 disk-qemu
```

**Version × host matrix completed, and the Windows column release-aligned
(2026-09-09, later the same day).** Two Weilnetz Windows builds were fetched
from the site qemu.org's download page points to, SHA-512-verified against
their sidecars, and *extracted* with 7-Zip into `E:\qemu-versions\` (no
installer executed, no PATH change; the winget 11.0.50 is untouched);
`launch-qhv-tcg.ps1 -QemuPath` drives them with the same stamped instrument.

| | QEMU 6.2.0 | QEMU 11.x |
|---|---|---|
| Windows x86_64 | **HANG** — stops after `random: Could not initialize entropy` exactly as on the Orin; `waitfor`'s timeout never fires (406 bytes at 300 s) | boots (11.0.50: 28,720 ms; 11.1.0: 28,829 ms) |
| Orin A78AE | **HANG** (distro 6.2.0; both with and without rng) | boots (11.1.0 from source: 62,058 ms) |

**The 6.2 hang reproduces on the x86_64 host.** Same image, same argument list, same behaviour under the Weilnetz 6.2.0 Windows build (`QEMU emulator version 6.2.0 (v6.2.0-11889-g5b72bf03f5-dirty)  [E:\qemu-versions\qemu-6.2.0\qemu-system-aarch64.exe]`): the log stops after the entropy line and `Unable to access /dev/random` never appears. The version effect is therefore host-independent — the last competing explanation (a host × version interaction) is excluded, and "the Orin hang was QEMU 6.2, not the host" no longer rests on the Orin alone.

**Release-aligned pair** (both hosts on upstream 11.1.0 — *different builds
of it*, which the stamps show: Windows `QEMU emulator version 11.1.0 (v11.1.0-12130-ge470268ff4)  [E:\qemu-versions\qemu-11.1.0\qemu-system-aarch64.exe]`, Orin `QEMU emulator version
11.1.0 (v11.1.0)` from source; rng in slot 3; `-snapshot`; the same
`95849168…` disk bytes):

| Segment (medians, ms) | Windows 11.1.0 | Orin 11.1.0 | ratio |
|---|---|---|---|
| launch → host post_start | 6,160 | 13,430 | 2.18× |
| qvm launched → guest banner | 22,613 | 48,452 | 2.14× |
| **launch → guest banner** | **28,829** | **62,058** | **2.15×** |

Windows n=5: 28,740, 28,756, 28,830, 28,829, 28,850 (spread 110 ms). **Same-host control:** on the same
Windows box, 11.0.50 (fork dev build) vs 11.1.0 (release build) medians are
28,720 vs 28,829 ms — a +0.4% shift from the QEMU build/version alone, which
bounds how much of any cross-host ratio can be blamed on the QEMU binary
rather than the host. This is the closest thing to a twin diff this leg can
produce: same images, same guest-visible machine, same accelerator, same
device set, same disk mode, same upstream release — with the host bundle
(CPU, OS, TCG backend, QEMU build) as the remaining difference, honestly
labelled as a bundle.

**Tooling lessons, because they cost real time:** `pgrep -f`/`pkill -f`
match the calling shell's own command line when the pattern appears in it
(three separate self-matches: a "still running" false positive that hid a
failed build for 13 minutes, a `pkill` that killed its own ssh session, and
one false negative from `pgrep`'s 15-character `comm` truncation that hid a
QEMU orphan holding the disk lock). Use `pgrep -f '[b]uild-…'` and check for
side effects (files, exit-code sentinels) rather than process tables. The
Bash-tool heredoc also mangles backslashes even with a quoted delimiter —
scripts with line continuations were written via the file tool instead.

**Diagnostic collector for the KVM/NISV hang (2026-09-09, same day).** A
user-supplied four-stage investigation plan (inspect → decode → classify →
report; read-only, no package installs, no QNX binaries copied, every test
marked PASS/FAIL/BLOCKED/NOT APPLICABLE/NOT RUN, facts kept apart from
hypotheses) was implemented as
[scripts/diagnose-gicv3-nisv.sh](../scripts/diagnose-gicv3-nisv.sh) and run
twice: an unedited script run
([results/gicv3-nisv-debug/20260909T100704Z](../results/gicv3-nisv-debug/20260909T100704Z/summary.md))
and a report run whose thin sections were rewritten by hand and then put
through a second, adversarial honesty review
([results/gicv3-nisv-debug/20260909T101030Z](../results/gicv3-nisv-debug/20260909T101030Z/summary.md)).
What it pinned down without touching a board: the sha256-identical `ifs.bin`
holds exactly one `str w3,[x0],#4` opcode in its startup blob, at VA
0x40085978 inside the `GICD_IPRIORITYR` loop; every vector slot at
`VBAR_EL1`=0x4008d800 is `b .`; the shipped startup carries the same four
writeback MMIO stores as the rebuilt `gic_v3.o`; `dumpifs -x` does not
extract `startup.*` (recipe corrected); and a Windows QEMU 6.2.0 TCG boot of
the same IFS reaches the banner (control only — TCG never synthesises the
Data Abort). What the honesty review forced into the open: the **only**
data-backed NISV in the repo is the Orin ftrace `hsr=0x92000045` (EC=0x24,
ISV=0, WnR=1, DFSC=0x05); the `a1.metal` run is symptom-only (no exit reason
was logged there); the 2026-07-28 note claims the traced PC matched the
static candidate but no numeric `pc=`/`ipa=`/`hxfar=` was ever written down,
so 0x40085978 stays a candidate; the `-smp 1` / `gic-version=host` /
`its=off` variants are asserted without a single logged run; and the
from-source 11.1.0 on the Orin was *configured* with `--enable-kvm` but never
tried under KVM. The report ends with the exact commands that would settle
each of those (ftrace re-run capturing `pc=`/`ipa=`, one logged run per
variant, the 11.1.0 KVM re-check) — that list is now the concrete to-do
behind next action 2 in CLAUDE.md. Two housekeeping decisions made while
landing it: the objdump windows of the SDP-shipped startup that the report
run had produced were replaced by fact summaries before commit (the repo has
withheld such listings since 2026-07-28; QDL v7 §4.6(c) remains an open
owner decision), and the `a1.metal` log header's EC2 instance id (instance
terminated 2026-07-29) was redacted to honour the CLAUDE.md secrets rule —
it stays in git history. Six intermediate build/review runs of the script
were parked outside the repo rather than deleted.

**Owner decisions (2026-09-09, recorded verbatim in intent, not paraphrased
into reasons the owner did not give):** (1) ADR-003 → option (B), native
Orin Nano port — chosen over the ADR's own Pi 4B recommendation; the Pi
route stays documented as the cheaper alternative. (2) Licence flags: the
work proceeds; the supervising professor is consulted before any
evaluation results are published (4.6(i)); 4.6(c) stays clean by using
source and documentation only. (3) The git history is to be cleaned of
the a1.metal instance id and, with it, the LAN address, key filename and
account names the repo's own conventions redact. A full-history bundle
and two `backup/pre-history-rewrite-2026-09-09*` branches were taken
first; the rewrite itself (`git filter-branch` over `main` and the README
branch, then a force-push with lease) is handed to the owner to run —
the session's tool policy declines history rewrites, which is the right
default for an action that cannot be undone remotely. Until it runs, the
old id is still reachable in the pushed history. (4) Start the port —
kicked off the same day as Phase 3b, see
[orin-native-port-plan.md](orin-native-port-plan.md).

---

## 2026-09-08 — QHV leg made host-portable: the twin gets a comparison on the *hypervisor* topology (Windows half measured; Orin half blocked on hardware — **superseded by the 2026-09-09 entry above**)

An architecture pass, not a feature. Reviewing
[digital-twin-design.md](digital-twin-design.md) §1 against what the repo
actually does turned up four claims that were no longer true, three of them in
the **invariant** set the document itself defines as "anything that differs
between twin sides in those rows is a bug":

1. *"QEMU acceleration: cloud = tcg; Orin = `-enable-kvm` (KVM works on
   A78AE)"* — false. Orin's KVM boot is blocked by the GICv3/NISV defect, so
   the `qnx-safety-vm` leg runs **TCG on both sides**.
2. *"Orin is a heterogeneous QNX↔Linux exchange … bridged under **KVM**"*
   (§4) — same error, same cause.
3. *"QNX IFS — **Yes, bit-for-bit identical**"* — false for the Phase-3 Orin
   IPC run, which used a **rebuilt** IFS with new TCP server code staged in.
   The twin's single most load-bearing invariant did not hold for the
   measurement that most depended on it.
4. *"Cloud twin — AWS Graviton (c7g.large)"* — as built, every QHV boot and
   IPC number attributed to "cloud" was produced on the **local Windows
   host**. Once ADR-002 removed KVM from that leg, nothing was left that
   required it to be in the cloud.

Add the unlisted one — the two legs run **different server programs**
(`qnx-server` over a console vdev vs. `qnx-server-net` over TCP) — and the
surviving invariant set is just **{wire protocol, harness/CSV shape, QEMU
machine shape}**. A twin diff with almost no invariants is not a twin diff.

**The cheap fix: the QHV leg turns out to be host-agnostic.** Its entire QEMU
invocation is `-machine virt,virtualization=on,gic-version=3 -cpu max -accel
tcg -smp 2 -m 2G` plus two image files. Everything that makes the leg
interesting — `qvm` itself, the guest, the virtio-console and `vdev shmem`
wiring, even the pty pair (`/dev/ptyp0`↔`/dev/ttyp0`, a **QNX** device inside
the emulated world, not a host one) — lives *inside* the emulation. Nothing
crosses to the host but the images and a serial log. So the same images can be
carried to the Orin and booted unchanged, giving a genuine one-variable
comparison on the **hypervisor** topology (a real EL2/EL1 boundary) rather
than on plain boot time alone.

Note carefully *why* this leg is TCG on both sides: **QHV needs EL2 for its
guest, i.e. nested virtualisation, which ARM KVM does not provide on A78AE.**
That is a hard architectural requirement, not the GICv3 blockage. For once
TCG-on-both is genuine symmetry, and the two must not be described the same
way. See [digital-twin-design.md](digital-twin-design.md) §1a.

**Built:** [`scripts/orin/launch-qhv-on-orin-tcg.sh`](../scripts/orin/launch-qhv-on-orin-tcg.sh)
(new), `-Runs` / `-StopOnGuestBanner` added to
[`scripts/launch-qhv-tcg.ps1`](../scripts/launch-qhv-tcg.ps1) (default
behaviour unchanged), and
[`scripts/twin/sync-qhv.sh`](../scripts/twin/sync-qhv.sh) to stage the images
with the checksum invariant enforced on arrival. `sync.sh` was left alone: it
targets `qnx-safety-vm/output`, demands a `CLOUD_RUNTIME_HOST` that no longer
exists for this leg, and uses `rsync`, which is absent from Git Bash on the
Windows build host — i.e. it cannot run from where the images now live.

**A wrong instruction found by building the instrument.** The curation header
of [qhv-tcg-host-and-guest-boot.log](../logs/sample-boot/qhv-tcg-host-and-guest-boot.log)
tells the reader to look for **two** banners — a host `QNX qnx-qhv … QEMU_virt`
and a guest `QNX qnx-guest … ARMv8_Foundation_Model` — and the original launch
script repeated the same advice. **No host banner exists** in that log's body,
or in any run reproduced since; only the guest prints one. A check written to
that instruction reports `host banner=no` on a perfectly healthy boot. Replaced
with three markers that are actually emitted: `=== AUTO-START QNX GUEST UNDER
QVM` (host reached post_start), `=== launching qvm @g2.conf` (hypervisor
invoked), and the guest banner (guest came up across EL2/EL1). They fail
distinguishably, which the single-banner check did not.

**Windows half, measured, n=5** (launch → guest banner, `-StopOnGuestBanner`):

| Run | ms |
|---|---|
| 1 | 49,080 |
| 2 | 49,165 |
| 3 | 49,275 |
| 4 | 49,124 |
| 5 | 49,300 |
| **median** | **49,165 ms** |
| mean | 49,188.8 ms |
| spread | 220 ms (49,080–49,300) |

That spread is **0.4% of the median** — far tighter than the plain
`qnx-safety-vm` boot-time measurement on this same host, whose five runs
spanned 1,103 ms because of a cold-start outlier. Worth knowing before the
Orin numbers arrive: this instrument is precise enough that a real host
difference will not be lost in noise.

**Not done, and the reason matters:** the Orin half. The board was
unreachable — `ssh` to 192.168.178.56 timed out on port 22 — so it is
presumably powered down or has taken a different DHCP lease. **This entry
therefore ships the instrument and one side's numbers, not the comparison.**
Nothing here should be quoted as a twin diff until the Orin column exists.

One measurement detail checked rather than assumed: the host's
`post_start.custom` holds a hard-coded `sleep 90` boot-grace, but the guest
banner lands at ~49 s — *inside* that sleep — so it contributes nothing to the
number. On a slower host a banner past 90 s would change the interleaving, so
any run reporting much more than that should be inspected, not plotted.

---

## 2026-09-08 — GICv3/NISV: the faulting instruction reproduced from BSP source, and a one-flag change removes it — compile-verified, boot-unverified

Started as a static-analysis lead and ended as a **compile-level
reproduction** of the defect this repo root-caused from disassembly on
2026-07-28. The faulting instruction can now be produced, inspected, and
made to disappear on demand. No rebuilt startup has been booted — the
boundary between what is proven and what is argued is spelled out at the
bottom of this entry.

**1. The source ships.** SDP 8.0's QNX Hypervisor guest-ARM BSP
(`$SDP/bsp/BSP_hyp-guest-arm_be-800_SVN1018940_JBN323.zip`) contains the
startup *library* source, including
`src/hardware/startup/lib/aarch64/gic_v3.c`. Its SPI priority-init loop
(~line 1018) writes `ARM_GICD_IPRIORITYn + reg_idx*4` starting from
`reg_idx=8`; with `ARM_GICD_IPRIORITYn = 0x400`
(`lib/public/aarch64/gic_v3.h`) the loop's first iteration targets
**0x420**. Also settled along the way: SDP ships exactly two aarch64
startup binaries — `startup-qemu-virt` and `startup-armv8_fm` — so
"rebuild the IFS with a GICv3 startup" is a no-op. The current startup is
already GICv3-aware; it prints `FOUND GICv3 ITS` and finishes
CPU-interface bring-up before dying in the *distributor*.

**2. The BSP builds unmodified**, using the SDP's **Windows** host
toolchain (`qcc -Vgcc_ntoaarch64`, gcc 12.2.0) — `libstartup.a` and
`gic_v3.o` produced with zero source changes. Worth noting in the BSP's
own flag set: `-fno-store-merging` is already there. QNX already suppresses
one codegen pattern for MMIO-safety reasons; this finding is about a second
one they did not.

**3. The freshly built object contains the exact faulting instruction.**
`ntoaarch64-objdump -d gic_v3.o`, inside `gic_v3_initialize`:

```
1a54:   91108020    add   x0, x1, #0x420        // GICD base + 0x420
1a58:   72b41403    movk  w3, #0xa0a0, lsl #16  // w3 = 0xA0A0A0A0
1a68:   b8004403    str   w3, [x0], #4          // post-indexed, writeback
1a70:   54ffffc1    b.ne  1a68
```

That is `str w3,[x0],#4` at offset 0x420 — the same instruction form at the
same offset the 2026-07-28 ftrace + static-disassembly work identified in
the shipped `startup-qemu-virt` binary. **The induction-variable
strength-reduction theory is now confirmed rather than inferred.** The
object holds **four** MMIO writeback stores in total: the GICD SPI priority
loop (`0x1a68`), a GICD clear loop (`0x1a90`), a GICR priority loop inside
`gic_v3_gicc_init` (`0x1b0`), and a 64-bit `str x0,[x2],#8` (`0x1af0`). All
four are the same ISV=0 instruction class; the GICD one is simply the first
executed, which is why the guest dies exactly there.

**4. A single compiler flag removes all four.** Recompiling the same file
with `-fno-auto-inc-dec` appended to the BSP's own flags takes the
writeback-store count from **4 to 0**. The loop becomes:

```
1a78:   91001000    add   x0, x0, #0x4
1a7c:   b81fc003    stur  w3, [x0, #-4]         // non-writeback, unscaled offset
1a84:   54ffffa1    b.ne  1a78
```

Same addresses, same values, same iteration count — the address arithmetic
is simply hoisted out of the store. A plain immediate-offset store reports
a valid ISS, so KVM's in-kernel vgic MMIO path can decode it instead of
bailing out to userspace with `KVM_EXIT_ARM_NISV`. It is a minimal,
behaviour-preserving change of exactly the kind QNX already applies via
`-fno-store-merging`.

**What this does NOT prove — the honest boundary:**

- **Nothing has been booted.** The chain "remove writeback stores → no NISV
  exit → guest boots under KVM" is argued from the architecture, not
  observed on hardware. Until a rebuilt startup boots on Orin or
  `a1.metal`, this is a strong hypothesis with a compile-level proof of its
  first link only.
- **`startup-qemu-virt` still cannot be relinked.** The BSP ships
  `boards/armv8_fm/` but **not** `boards/qemu-virt/`, so there is no board
  object for the startup this project actually boots. `libstartup.a` can be
  rebuilt; the binary that consumes it cannot. Getting to a bootable image
  needs either the qemu-virt board source from QNX, or adapting
  `armv8_fm` to QEMU `virt`'s memory map (GIC bases, pl011 UART, RAM at
  0x40000000) — real work, not a recompile.
- **Only `gic_v3.c` was audited.** Other startup objects may carry
  writeback MMIO stores of their own; a whole-library sweep was not done,
  so "four" is four *in this file*, not four in the startup.
- **The build ran on the local Windows host, not on AWS.** The installed
  SDP carries Windows host tools only — the installed Linux host packages
  are just `mkifs`/`mkxfs`/`dumpifs`/`dumpefs`, no `qcc` — so an EC2 Linux
  build host would first need the NCEULA-interactive QNX Software Center
  install that
  [scripts/bootstrap-build-host.sh](../scripts/bootstrap-build-host.sh)
  deliberately declines to automate. AWS's useful role here is the *test*
  bed, not the build host: `a1.metal` already reproduces the hang
  (2026-07-29 entry), so it can verify a fix the moment one is bootable.
- One correction worth recording, since it nearly became a false finding:
  an initial `grep -E "\t(str|stp)..."` over the disassembly returned zero
  writeback stores and briefly looked like a refutation. `grep -E` does not
  interpret `\t` as a tab, so the pattern could never match. The count is
  4, not 0.

**Why it matters anyway:** the defect report to QNX/BlackBerry moves from
"our disassembly suggests your startup uses a writeback store on a device
register" to "here is your own BSP source, built with your own flags,
emitting that instruction at that offset — and here is a one-flag change
that eliminates it without touching semantics." That is a materially
stronger filing, and it costs QNX almost nothing to verify.

**Next step, in order of cost:** (a) sweep the rest of `libstartup.a` for
other writeback MMIO stores; (b) ask QNX for the `qemu-virt` board source
(or file the defect and let them rebuild); (c) if neither, attempt the
`armv8_fm` → QEMU `virt` memory-map adaptation and boot the result on
`a1.metal` under KVM.

---

## 2026-07-29 — GICv3/NISV KVM hang reproduced on a second vendor's silicon (AWS `a1.metal`, Graviton1) — no longer Tegra234-specific

Cross-vendor validation of the 2026-07-28 Orin Nano finding (`docs/orin-port.md`
risk register). Provisioned an AWS EC2 `a1.metal` instance (Graviton1,
Annapurna Labs SoC, 16× Cortex-A72 — chosen over `c7g.metal`/Graviton3
because this AWS account's 32-vCPU quota blocked the 64-vCPU `c7g.metal`
launch outright) and booted the identical `qnx-safety-vm` `ifs.bin`/`disk-qemu`
under `-machine virt,gic-version=3 -cpu host -enable-kvm`. **Same exact
symptom**: `FOUND GICv3 ITS` printed, then zero further serial output for
a full 60s capture, process alive throughout (only the external timeout
killed it) — byte-for-byte the same hang shape as Orin Nano's Tegra234/
Cortex-A78AE. A bare vGIC smoke test on the same instance (`-kernel
/dev/null`) ran clean, same as on Orin — vGIC device creation is not
where either platform fails. Full capture:
[logs/sample-boot/aws-a1-metal-kvm-nisv-repro.log](../logs/sample-boot/aws-a1-metal-kvm-nisv-repro.log).
Instance terminated immediately after capture (no ongoing AWS cost).
**Honest framing:** one run, not a repeated series — strong single-data-point
evidence, not a statistically hardened claim. **What this changes:** the
defect is now evidenced across two independent ARM vendors (NVIDIA Tegra234
and Annapurna Labs/AWS Graviton1), which meaningfully strengthens the case
that this is a general `startup-qemu-virt` GICv3-bring-up defect rather
than a Jetson-specific quirk — relevant to how confidently this can be
raised with QNX/BlackBerry (see `docs/interview-narrative.md`'s Q&A
section). A same-generation `c7g.metal` (Graviton3) run remains a real,
not-yet-executed follow-up, blocked on this account's vCPU quota, not on
anything technical.

---

## 2026-07-28 — ADR-002 RQ-2 guest-side shmem round trip: RESOLVED YES, proven live, two-way (continuation session)

Completes the concrete next step the entry below left open: a `qnx-guest`
process attaching to the same named shared-memory region
(`phase2-rq2-probe`) the `qnx-qhv` host already proved it could create/attach
to, and a real byte exchange in both directions. New pieces: a `vdev shmem`
line (`loc 0x1c0f0000`, `intr gic:43`, `allow phase2-rq2-probe`) added to a
**staged, not committed** copy of the guest's `g2.conf` generator in
`post_start.custom`; a new guest-side program,
[ipc-test/qnx-guest-shmem-probe/probe.c](../ipc-test/qnx-guest-shmem-probe/probe.c),
using `qvm/guest_shm.h`'s raw-MMIO factory-page protocol
(`mmap_device_memory()` + `guest_shm_create()`, no library); and a new
host-side companion, `ipc-test/qnx-host-shmem-probe/roundtrip.c`, that writes
the host pattern before `qvm` launches the guest and then **polls** (not
interrupt-driven) for the guest's write-back instead of detaching
immediately. `scripts/qhv/g2.conf.allow` was extended with the `allow`
keyword and `vdev:shmem` type (least-directive: only what this g2.conf
actually uses was added; `create`/`deny`/`gid`/`sched`/`subst`/`umask` were
deliberately left out).

**First boot attempt crashed** (`Bus error`, log:
[logs/sample-boot/qhv-tcg-rq2-shmem-roundtrip-attempt1-bus-error.log](../logs/sample-boot/qhv-tcg-rq2-shmem-roundtrip-attempt1-bus-error.log)):
the factory page's signature read (a scalar load) succeeded, proving the
`vdev shmem loc/intr` MMIO wiring itself is real, but a block `memcpy()` of
the 32-byte region name into the factory page's virtual-register file took a
Bus error immediately after — most likely `qvm`'s MMIO trap decoder
rejecting whatever wide/vector store instruction the target's `memcpy()`
picked for that copy size (the same *class* of problem as the unrelated Orin
`KVM_EXIT_ARM_NISV` GICv3 finding in `docs/orin-port.md` — an MMIO emulator
that only decodes a subset of real instruction encodings). **Fix:** rewrite
the name write (and, defensively, the shared-data read/write) as explicit
byte-at-a-time volatile stores instead of a block copy.

**Second boot attempt succeeded end to end** (log:
[logs/sample-boot/qhv-tcg-rq2-shmem-roundtrip-success.log](../logs/sample-boot/qhv-tcg-rq2-shmem-roundtrip-success.log)):
the guest's `guest_shm_create()` returned `GSS_OK`, read the host's
`"hyp-shm-host-ok"` pattern byte-exact, and wrote back
`"hyp-shm-guest-ok"`; the still-running host prober saw the write-back 24
seconds later before detaching. Both ends resolving to the **same**
underlying named region (not two independent registries that happen to
share a name) answers the crux question the previous entry left open. The
existing committed virtio-console IPC benchmark then ran immediately
afterward in the same boot with no regression (one sentinel-kick recovery —
the same already-documented, unrelated non-deterministic `qvm`/TCG stall).
**Not attempted, explicitly:** the interrupt/notify-driven path
(`InterruptAttach()` + `guest_shm_control.notify`) — the vdev's intr line's
edge/level and masking semantics were not confirmed in the time available,
and a wrong guess risks an interrupt storm hanging the guest under TCG with
no fast iteration loop to debug it; `factory->vector` (`43`, matching
`gic:43`) is read and logged for a future attempt. Per the project's
"diagnostic variant, staged, reverted after use" convention (same as the
host-only probe), the manual `g2.conf`/`post_start.custom` edits were never
committed to `scripts/qhv/` — `scripts/build-qhv.bat` was re-run afterward to
regenerate both gitignored build trees from the clean committed sources
(verified via `diff` showing no drift). See
[ipc-test/qnx-guest-shmem-probe/README.md](../ipc-test/qnx-guest-shmem-probe/README.md)
for the full account.

---

## 2026-07-28 — ADR-002 RQ-2 host<->guest shmem viability: RESOLVED YES (host side, empirically proven live); guest side open, not attempted

Resolved the crux unknown behind ADR-002's RQ-2 stretch transport (see
[phase2-topology-decision.md](phase2-topology-decision.md) §5 and
[phase2-research-spike.md](phase2-research-spike.md)'s RQ-2/RQ-3 table,
which had only established that `vdev-shmem` exists and is
`io-sock`-free — it had NOT established whether the QHV **host**'s own
userspace, as opposed to a `qvm` guest, can attach to it). Two evidence
passes, both today:

1. **Full doc re-fetch** (`share_mem.html`, `share_mem_config.html`,
   `share_mem_vdevshmem.html`, `share_mem_pages.html`, `guest_shm.html`,
   `vdev_shmem.html` — all six pages under
   `com.qnx.doc.hypervisor.user/topic/share/` and `topic/vdev_ref/`,
   fetched via `curl` since no browser tool is available here) settles
   the ambiguity the research spike left open: the shmem vdev "provides a
   simple mechanism for sharing memory regions between guests, **or
   between guests and the hypervisor host**" and, decisively, "**Host
   applications may also create shared memory regions or attach to them
   if permission allows.**" The same page also says the *documented* path
   for this is "the Virtualization API (`libhyp.a`)... described in the
   Virtualization API Reference that's not included with the QNX
   hypervisor documentation... contact your QNX representative" — i.e.
   vendor docs frame the host-side API as requiring NDA'd documentation
   this project does not have access to.
2. **Local SDP 8.0 install inspection contradicts the "need NDA'd docs"
   framing being a hard wall.** `C:\Users\andy8\qnx800\target\qnx\usr\include\hyp_shm.h`
   ("Host side QNX hypervisor interface definitions") **is** shipped in
   the standard install, with a real, if terse, Doxygen-commented API
   (`hyp_shm_create`, `hyp_shm_attach_ext`, `hyp_shm_data`, `hyp_shm_poke`,
   `hyp_shm_detach`, ...), and `ntoaarch64-nm.exe` on
   `target/qnx/aarch64le/lib/libhyp.a` confirms every one of those symbols
   is a real, defined (`T`) function, not a stub. The guest-side
   counterpart, `qvm/guest_shm.h` (raw MMIO register layout +
   `guest_shm_create()`/`guest_shm_find()` inline helpers), is likewise
   present locally. Neither needs the gated "Virtualization API
   Reference" to attempt — the shipped headers are enough to try.
3. **Live empirical confirmation, same day:** a new, minimal **host-only**
   program (`ipc-test/qnx-host-shmem-probe/probe.c`, no `qvm`/`g2.conf`
   involvement at all) calling `hyp_shm_create()` +
   `hyp_shm_attach_ext()` on the already-proven `qnx-qhv` host image
   succeeded on the first boot tried: `rc=0`, a real mapped
   `data=4c194fb000` pointer, a successful write + `hyp_shm_poke()` +
   clean `hyp_shm_detach()`. See
   [logs/sample-boot/qhv-tcg-rq2-hyp-shm-host-probe.log](../logs/sample-boot/qhv-tcg-rq2-hyp-shm-host-probe.log)
   and [ipc-test/qnx-host-shmem-probe/README.md](../ipc-test/qnx-host-shmem-probe/README.md).
   Because this succeeded with **zero** `vdev shmem` declarations
   anywhere, the underlying named-region registry is a host-OS/kernel-level
   facility, not something scoped to a specific `qvm` VM — which is why an
   ordinary host process (not a guest) can reach it directly.

**Net verdict: RQ-2's host-side half is RESOLVED YES, proven live, not
just claimed from docs.** The guest-side half (a `qnx-guest` process
attaching to the *same* named region via `qvm/guest_shm.h`'s raw-MMIO
factory-page protocol, and a full host<->guest byte exchange) was
**deliberately not attempted this session** — a real, bounded time-box
decision, not a blocker found. Per this project's honest-framing rule:
this is a genuine "resolved-but-partially-implemented" stopping point,
not a claim that host<->guest shmem IPC is working end-to-end. The
concrete next step, if this stretch transport is picked up again: add a
`vdev shmem` line (with a new, unused interrupt, e.g. `gic:43`) to the
guest's `g2.conf` in `scripts/qhv/post_start.custom`, write a guest-side
program using `guest_shm_create()`/`mmap_device_memory()`/`InterruptAttach()`
per `qvm/guest_shm.h`, and verify it can see the host's test pattern (or
vice versa). `scripts/qhv/g2.conf.allow` does **not** yet list
`vdev:shmem` or the shmem-specific directives (`create`, `allow`, `deny`)
— that gate extension was correctly identified as a prerequisite by the
research spike but is likewise not done here, since no guest-side shmem
vdev was actually wired up this session.

---

## 2026-07-28 — Kick-safe sentinel frame implemented and proven: the `qvm`/TCG virtio-console stall is now a survivable, recoverable event, not a fatal one

Implements the concrete next step the two entries below left open: "a
kick-safe sentinel frame ... so a 'wake-up' write after a timeout cannot
leave a corrupting duplicate in the application frame stream." Design: a
reserved `seq` value, `FRAME_SENTINEL_SEQ = UINT64_MAX`
(`ipc-test/common/frame.h`), that both ends can treat as a no-op —
`qnx-server` needs **zero** code changes (it already echoes any frame
verbatim regardless of `seq`); only the initiator (`qnx-host-client`)
needs new logic. On a read timeout, `sentinel_recover()`
(`ipc-test/qnx-host-client/client.c`) writes a **sentinel**, not a resend
of the real in-flight frame — reusing the exact "new write activity
unsticks the missed notification" property the resend experiment
discovered, while avoiding the exact failure mode that made the resend
unsafe (a stale duplicate REAL echo corrupting the next iteration's
alignment; a stale sentinel echo is inert and simply discarded). Bounded
by `SENTINEL_MAX_ROUNDS=5` / `SENTINEL_READS_PER_ROUND=3` so a genuinely
dead link still fails loudly rather than hanging forever.

**Real evidence, 4 separate boots, same day, real (not simulated) stalls:**
a regression boot at the committed 15-timed/5-warmup config hit 1 stall
(recovered), and three diagnostic boots at a temporarily-raised
300-timed/5-warmup config (to raise the odds of hitting the known
~1–2%/iteration hazard within one boot; **never committed** — the
`scripts/qhv/post_start.custom` edit was reverted in full immediately
after, verified via `git diff` showing zero changes, matching this
project's established diagnostic-variant convention) hit 3, 8, and 7
stalls respectively. **19/19 stalls recovered cleanly across all 4
boots, zero unrecoverable timeouts, zero alignment-corruption failures.**
Every single recovery showed `sentinel_bounces=0` — the real echo was
always read back *before* the sentinel's own bounce, exactly matching the
theory that the guest's synchronous echo loop had already produced the
real reply before the notification was missed — and the sentinel's own
now-trailing echo was swept up harmlessly by the pre-existing
`cio_drain_stray()` call at the top of the next iteration (visible as a
benign "discarded 64 stray byte(s)" warning). Each run's reported
`samples` count equals `timed_iters - recoveries_in_timed_window` exactly,
confirming recovered iterations are correctly excluded from timing stats
rather than polluting P50/P99 with recovery-contaminated RTTs. Curated
logs:
[logs/sample-boot/qhv-tcg-sentinel-recovery-committed15-5-check.log](../logs/sample-boot/qhv-tcg-sentinel-recovery-committed15-5-check.log),
[...-diag300-run1.log](../logs/sample-boot/qhv-tcg-sentinel-recovery-diag300-run1.log),
[...-diag300-run2.log](../logs/sample-boot/qhv-tcg-sentinel-recovery-diag300-run2.log),
[...-diag300-run3.log](../logs/sample-boot/qhv-tcg-sentinel-recovery-diag300-run3.log).
Full account in
[ipc-test/qnx-host-client/README.md](../ipc-test/qnx-host-client/README.md)'s
new "Sentinel-kick recovery" section.

**Honest scope of the claim:** the `qvm`/TCG missed-notification root
cause is **still not fixed** — the underlying hazard rate is unchanged.
What changed is that the client no longer needs to treat a stall as
fatal or risk silent corruption recovering from it. The committed
benchmark configuration (`scripts/qhv/post_start.custom`'s 5 warm-up + 15
timed invocation) is **unchanged** by this session — the 300-iteration
runs were diagnostic-only, reverted, and exist purely as proof the
mechanism scales well past the old 15-sample ceiling. Whether to raise
the committed run size now that recovery is proven is a reasonable
follow-up decision, left open rather than actioned unilaterally in this
implementation pass.

---

## 2026-07-28 — `qvm`/TCG virtio-console stall: root-caused further (not fixed) via live interactive probing and a resend-retry experiment that failed instructively

Follow-up root-cause session on the Phase 2 cloud-leg stall left open by the
runtime-spike entry below. **Outcome: root-caused further, still NOT
fixed.** New tooling:
[`scripts/qhv/launch-qhv-tcg-interactive.ps1`](../scripts/qhv/launch-qhv-tcg-interactive.ps1)
boots the QHV host with its serial console on a TCP socket instead of a
plain log file, so commands can be injected into the live root shell
**while `qnx-host-client` is still running/stalled in the background** (a
diagnostic-only variant of `post_start.custom` backgrounds the client loop
so `post_startup.sh` reaches the login-less shell regardless of whether the
client stalls — never committed; reverted after use). Four things were
tried, three ruled out, one produced the key new evidence:

1. **`qvm` process-level deadlock — RULED OUT.** `pidin -p qvm` snapshots
   taken live during 8 separate diagnostic runs (200 iters + 5 warm-up
   each, no gap beyond the existing 20 ms pacing) always show `qvm`'s 4
   threads cycling normally among RECEIVE/RUNNING/REPLY/SEM/CONDVAR states
   — never frozen on the same blocked state across snapshots seconds apart.
   `qvm` itself is not wedged when the client stalls.
2. **`qvm`'s own debug/verbose logging — RULED OUT as a visibility path.**
   `use qvm` (QNX's embedded-usage-text convention; `qvm --help`/`-h`/`-v`
   are all rejected as unknown options) reveals a real, documented `logger
   debug stdout` / `logger verbose stdout` facility. Enabling both in
   `g2.conf` and redirecting `qvm`'s own stdout to a file produced **zero**
   additional log lines beyond ordinary startup output across a 250 s
   capture spanning multiple stalls — the virtio-console vdev does not
   appear to emit any per-transfer/virtqueue-level trace even at debug
   level, so this avenue gives no additional visibility.
3. **A config-level ring-size/queue-depth fix — RULED OUT.** The full `use
   qvm` option reference lists no vdev-specific queue-depth/ring-size
   tunable for `virtio-console`; the only related knobs are
   `message-block-timeout` / `vdev-message-block-timeout` (both default
   10s, unrelated to queue depth) and `slog-buffer`. There is no exposed
   config knob to mitigate this.
4. **A resend-on-timeout retry mitigation — TRIED, FAILED, but mechanistically
   informative.** Client-side change (tested, then fully reverted — never
   shipped): on a read timeout, resend the same frame (re-stamping
   `tstamp_cycles`) up to 5 times before giving up. Across 8 independent
   diagnostic runs this **failed identically every single time**: exactly
   one retry always returned data (never needed a 2nd–5th attempt), but
   that data was **always the stale, one-iteration-behind echo** (e.g.
   timeout at iter 88, resend, echo comes back tagged seq=88 — correct for
   *that* iteration — but a second, now-orphaned duplicate echo of iter 88
   is left queued behind it, which the *next* iteration's read then
   consumes instead of its own reply, producing an immediate, permanent
   `echo seq mismatch at iter N+1 (got N)`). This is not noise — it is the
   same exact off-by-one signature in 8/8 runs. It means: **the original
   echo was never lost — the guest had already produced it, and the host
   side's read-ready notification for it was missed.** The resend's WRITE
   is what unstuck the missed notification (a 10 s bounded wait alone,
   already tried separately per the runtime-spike entry below, does
   *not* recover it), but because the resend also injects a real duplicate
   request the synchronous guest echo loop dutifully answers, it corrupts
   frame alignment one step later — trading a clean, diagnosable abort for
   a worse, silent-until-next-iteration desync. **Reverted in full**
   (`ipc-test/qnx-host-client/client.c` and `scripts/qhv/post_start.custom`
   both restored to the exact committed baseline via `git checkout --`) —
   this was evaluated and rejected, not shipped.
5. **Expanded, more precise stall-iteration dataset.** 24 total diagnostic
   attempts across this session (16 without the retry experiment, 8 with
   it, all otherwise using the same 20 ms pacing as the committed config):
   failures at iterations 6, 8, 13, 14, 28, 33, 56, 62, 62, 70, 77, 87, 88,
   89, 98, 105, 108, 109, 132, 133, 150, 180, 180 — plus **one full, clean
   200-sample success** (P50=2,346,400 ns P99=6,341,700 ns
   Max=10,804,400 ns, zero errors). This *refutes* the runtime-spike
   entry's "single-digit to several-dozen iterations" characterization —
   the stall demonstrably also happens much later (up to 180) and 200 is
   achievable. The distribution has no common-divisor/fixed-boundary
   pattern (rules out a fixed ring-size threshold) and is consistent with
   a small, roughly constant per-iteration hazard rate (~1–2%): fitting a
   geometric model to the mean failure iteration (~71) predicts ~6% odds
   of a clean 200-iteration run, matching the observed 1/16 successes to
   within noise. This is the signature of a rare, timing-window-dependent
   missed notification, not a deterministic logic bug or a hard ring-size
   ceiling.

**Root cause: narrowed, not identified at the code level, not fixed.**
Best-supported hypothesis, now with a concrete mechanism instead of just a
label: a rare, TCG-timing-dependent missed wake-up/notify on the host side
of the `qvm` virtio-console byte stream — the guest-side echo is genuinely
produced (not lost, not delayed indefinitely, not a guest-side hang), but
the host-side read doesn't get told data is ready, and nothing *other than
new write activity* nudges it back to life (a longer passive wait does
not; see the runtime-spike entry's 25 s-timeout finding). No source access
to `qvm`/`vdev-virtio-console.so` exists from this environment, `use qvm`'s
option surface has no relevant tunable, and enabling `qvm`'s own
debug/verbose logging produced no additional evidence — those are the
avenues available from outside `qvm`, and they are exhausted. A real next
step (not attempted here, out of this session's time-box, and requiring a
protocol/wire-format change to BOTH ends) would be a kick-safe sentinel
frame — a byte pattern both `qnx-host-client` and `qnx-server` recognise
and silently discard — so a "wake-up" write after a timeout cannot leave a
corrupting duplicate in the application frame stream. The committed
config (`scripts/qhv/post_start.custom`'s 15 timed + 5 warm-up run,
[`results/cloud/cloud-ipc-latest.csv`](../results/cloud/cloud-ipc-latest.csv))
is unchanged — nothing here is a real, repeatable improvement over it, so
per this project's honest-framing rule the existing real 15-sample result
stands as-is.

---

## 2026-07-28 — Phase 3 IPC benchmark done end-to-end on real Orin Nano hardware: 100 000 clean round trips over a real `br0` bridge, twice

Closed [`docs/orin-port.md`](orin-port.md) steps 3, 5, and 6 with a real,
measured QNX-guest↔native-Linux TCP exchange on the Jetson Orin Nano,
building on the same-day networking fix above. New source, both written
this pass and both actually building and running (not just written):
[`ipc-test/qnx-server-net/server.c`](../ipc-test/qnx-server-net/server.c)
(QNX guest, `qcc -Vgcc_ntoaarch64le`, TCP echo on `:7000`; Phase-2's
`qnx-server/` is untouched — different transport, virtio-console, cloud
leg only) and
[`ipc-test/linux-client/client.c`](../ipc-test/linux-client/client.c)
(native L4T, `gcc 11.4.0`, `clock_gettime(CLOCK_MONOTONIC)`-timed, zero
warnings on both builds). Getting the server auto-started with a working
static IP needed a real `qnx-safety-vm` **rebuild** (`mkqnximage
--type=qemu --arch=aarch64le --build`, same baseline `local/options`, two
new `local/snippets/{ifs_files,post_start}.custom` files staging the
compiled server binary and forcing `vtnet0`'s address — `OPT_IP=dhcp`'s
`dhcpcd` never gets a lease on `br0` since
[`scripts/orin/setup-bridge-orin.sh`](../scripts/orin/setup-bridge-orin.sh)
runs no DHCP server there) — the same staging mechanism `build-qhv.bat`
already uses for the Phase-2 pair, applied to the plain (non-QHV)
Orin image. One real Windows-tooling gotcha surfaced during the rebuild:
invoking `cmd.exe /c "..."` from Git Bash silently no-ops (MSYS rewrites
the bare `/c` into a Windows path before `cmd.exe` sees it — exit code 0,
zero output, looks like success); `cmd.exe //c "..."` (doubled slash)
fixes it. Booted on real Orin Nano hardware via the new
[`scripts/orin/launch-qnx-on-orin-tcg.sh`](../scripts/orin/launch-qnx-on-orin-tcg.sh)
(TCG + `tap-qnx` + the virtio-rng fix), confirmed reachable at
`192.168.100.10` over the real `br0` bridge (real ping RTTs, 0% loss —
not SLIRP this time), then ran the native `linux-client` against it: a
1 000+1 000 smoke run (clean, ~4.7 s), then the full committed
**100 000-iteration + 1 000-warm-up measurement twice in a row, both
clean, zero echo-sequence mismatches, zero I/O errors** (~2 m 40 s each;
P50≈1.6 ms, P99≈2.55 ms, Max≈3.8–4.1 ms across the two runs — TCG-emulation-
and-bridge-bound, not a meaningful transport number, same honest framing
as the cloud leg). The QNX server's own frame counts (`70`, `2000`,
`101000`, `101000`) match the client's accounting exactly across all four
connections in one guest boot — see
[orin-tcg-qnx-ipc-boot1.log](../logs/sample-boot/orin-tcg-qnx-ipc-boot1.log)
and
[orin-tcg-qnx-ipc-client1.log](../logs/sample-boot/orin-tcg-qnx-ipc-client1.log).
**Notably better than the Phase-2 cloud leg**: TCP over `br0`/virtio-net
under TCG did not reproduce the console leg's non-deterministic
virtio-queue stall at all — both full 100 000-iteration runs completed
without incident, where the cloud leg's largest reliable run was 15
samples. CSV in
[`results/hw/orin-ipc-latest.csv`](../results/hw/orin-ipc-latest.csv),
schema-identical to `results/cloud/header.csv`. **Honest gaps left open:**
this is a rebuilt IFS, not the untouched Phase-1 one (the new code is
in-scope/additive per this task's brief, but it is a real deviation from
a strict "zero IFS changes" portability claim); `docs/orin-port.md` step 7
(`scripts/twin/diff-results.sh`) runs without crashing but is not a
meaningful sanity check — it assumes a `# ifs_sha256:`-comment-header +
`metric,p50_us,...`-body schema that neither this CSV nor the existing
cloud CSV actually use, so it silently misreads the first data row as a
header and prints nonsense deltas; this is a pre-existing Phase-4 tooling
gap (predates this entry), not something fixed here. KVM-accelerated
timing on Orin remains open per the entry below.

---

## 2026-07-28 — Orin TCG networking root-caused and fixed: a missing virtio-rng device, not a virtio-net one

Root-caused and fixed the `if_up: network stack down: Bad file descriptor` /
`ifconfig: interface vtnet0 does not exist` failure blocking
[`docs/orin-port.md`](orin-port.md) step 6, seen on every TCG boot of the
plain `qnx-safety-vm` build on the real Orin Nano
([`../logs/sample-boot/orin-tcg-qnx-boot1.log`](../logs/sample-boot/orin-tcg-qnx-boot1.log)).
**The symptom is misleading — this was never a virtio-net/FDT-discovery bug.**
Chain of findings, established via a live interactive shell over a QEMU
chardev unix-socket serial port (not guessed from logs): (1) `pidin` on a
live boot shows `io-sock` is **not running at all** — it never starts, so
there is no `/dev/socket` for `if_up`/`ifconfig` to open, which is the actual
cause of "Bad file descriptor" and "interface does not exist" (both are
downstream symptoms of io-sock's total absence, not a driver-attach or
FDT-discovery failure in `devs-vtnet_mmio.so`). (2) Running `/system/bin/io-sock`
by hand and reading `slog2info` (not `sloginfo`, absent from this minimal
build) shows the real reason: `Exiting: Cannot open /dev/random: No such
file or directory` — io-sock hard-requires a working `/dev/random` at
startup and aborts immediately if it can't get one, before it ever probes
for a net device. (3) `/dev/random` is unusable because `random`'s
`devr-virtio.so:mem=0xa003a00` entropy source can't find a virtio-rng
device at that fixed MMIO address (`devr-virtio: failed to find virtio
entropy device`, already visible, if under-explained, in the original
`orin-tcg-qnx-boot1.log`). (4) Comparing against
`C:\Users\andy8\qnx800\host\common\mkqnximage\qemu\runimage` (the
canonical qemu launch script `mkqnximage --type=qemu` itself ships)
confirms this build's `startup.sh` (`devb-virtio ... smem=0xa003e00,irq=79`
and `random ... devr-virtio.so:mem=0xa003a00`) assumes QEMU is invoked with
exactly three `-device` entries in a fixed order — `virtio-blk-device`,
`virtio-net-device`, `virtio-rng-device` — because QEMU's `virt` machine
assigns its fixed virtio-mmio slots to `-device` args strictly in
command-line order; slot 1 (`0xa003e00`) → disk, slot 3 (`0xa003a00`) →
rng. **The Orin TCG boot command used all session used had zero `-device`
entries beyond the disk — no net, no rng — so the rng slot was empty by
construction, entropy never initialised, and io-sock refused to start,
which looks identical to a virtio-net bug until you check what's actually
running.** **Fix (QEMU command line only — no IFS rebuild, no custom
startup snippet needed):** add `-netdev user,id=n0 -device
virtio-net-device,netdev=n0,mac=...` and `-object
rng-random,filename=/dev/urandom,id=rng0 -device
virtio-rng-device,rng=rng0` in that order, after the existing
`-device virtio-blk-device,drive=drv0`. Confirmed working end-to-end on
real Orin Nano hardware: `io-sock` starts, `vtnet0` comes up, gets a real
DHCP lease from QEMU's SLIRP (`10.0.2.15/24`, gateway `10.0.2.2`), and both
`ping 10.0.2.2` (SLIRP gateway) and `ping 10.0.2.15` (self, exercises the
vtnet0 TX/RX path) succeed with real RTTs and 0% loss — captured in
[`../logs/sample-boot/orin-tcg-qnx-network1.log`](../logs/sample-boot/orin-tcg-qnx-network1.log).
**Honest framing:** `-netdev user` (SLIRP) proves the virtio-net driver and
MMIO wiring work, but it is not the `br0`/tap bridge
[`docs/orin-port.md`](orin-port.md) step 3 needs for the native-L4T IPC
test against a real bridge interface — that remains open, though this
finding makes it look like a straightforward follow-up rather than a
blocked one. This is also the second time this exact defect class
(io-sock's networking depending on a working entropy source it silently
can't get) has surfaced in this repo — the 2026-06-11 QHV entry below hit
the *same class* of virtio-mmio-slot-order dependency on the QHV guest
side and was worked around, not root-caused; this entry is the first time
it has actually been root-caused and fixed rather than routed around.

---

## 2026-07-28 — Phase 2 runtime spike resolved: first real QNX-host<->QNX-guest IPC numbers (partial)

Resolved the qvm/TCG console-wiring spike blocking Phase 2
([`../ipc-test/qnx-host-client/README.md`](../ipc-test/qnx-host-client/README.md))
and captured the **first real measured numbers to exist anywhere in this
repo** for the cloud-leg IPC benchmark — with one real limitation still
open. Chain of findings, established via a live interactive host shell
(TCP-forwarded `qvm` console, driven while the QHV host was actually
running, rather than guessed from docs): (1) **host-side wiring** —
`vdev virtio-console` needs `hostdev /dev/ptyp0` or `qvm` fails to arm it
(`[g2.conf:9] Failed to arm a resource manager: Function not implemented`,
present even in the *pre-existing*, `hostdev`-less config); `/dev/ptyp0` is
a `devc-pty` master already running on the image, `qvm` opens it, and the
paired slave `/dev/ttyp0` is what `qnx-host-client` opens — not the
`/dev/qhv/con1` placeholder in the milestone-1 proposal, which does not
exist (`ls: /dev/qhv: No such file or directory`, confirmed live). (2)
**guest-side wiring** — the guest gets no device node for the vdev at all
until it explicitly starts `devc-virtio -E 0x20000000,42` (matching the
vdev's `loc`/`intr`), which creates `/dev/vcon2` (`/dev/vcon1` is already
pl011's); confirmed via a diagnostic guest boot dumping `ls -la /dev`
before/after. (3) **two more real bugs found only by running it**: a tty
canonical-mode deadlock (both `/dev/ttyp0` and `/dev/vcon2` default to
line-buffered "cooked" mode; a binary frame with no `\n` byte can sit
unflushed forever — fixed with `cfmakeraw`/`tcsetattr` raw mode on both
ends, `ipc-test/common/console_io.h`), and a short one-time byte-injection
artifact ahead of the first echoed frame, reproducible byte-for-byte across
boots and not originating from the server (whose received frame was
byte-exact) — almost certainly `qvm` virtio-queue negotiation overhead on
the first exchange, absorbed by a throwaway "priming" frame + drain before
the timed loop starts. **Result:** a clean run of 5 warm-up + 15 timed
iterations completed end to end — `qnx-echo-server` up on `/dev/vcon2`,
`qnx-host-client` linked on `/dev/ttyp0`, real measured
**P50=2,002,500 ns, P99=Max=2,332,300 ns** (15 samples, 48-byte payload),
captured in
[`../logs/sample-boot/qhv-tcg-ipc-benchmark.log`](../logs/sample-boot/qhv-tcg-ipc-benchmark.log)
and transcribed by the new `scripts/qhv/extract-ipc-result.sh` into
[`../results/cloud/cloud-ipc-latest.csv`](../results/cloud/cloud-ipc-latest.csv)
(the client cannot write that file itself — it runs inside the QNX host
image's own filesystem, with no path back to this checkout on this leg).
**What did NOT get resolved:** a fourth, unanticipated finding — repeated
back-to-back exchanges with no gap hang within single-digit iterations
under TCG (a real, reproducible hang under a bounded read timeout, not
framing corruption: every frame up to the stall point was byte-exact). A
20 ms inter-iteration pacing gap (measured outside the RTT sample window)
let some runs reach dozens of iterations, but repeated attempts at the
*same* 20 ms gap stalled anywhere from iteration 2 to iteration 35, and
neither a larger gap (100 ms, which stalled at iteration 16 and separately
at iteration 2) nor a much longer read timeout (25 s, no recovery) made it
reliable — a 10000-iteration attempt also stalled (iteration 35). This
points to `qvm`/TCG virtio-queue kick/notify timing sensitivity, not a
protocol defect, but it was not root-caused further within this spike.
**Honest framing:** the reported ~2 ms P50/P99 is TCG-emulation-bound, not
a transport-cost measurement (per `ipc-test/README.md`'s existing framing),
and the *sample count* itself is honestly small — 15, not the
1000-warm-up/100000-iteration target the client defaults to — because
larger counts hit the unresolved stall above; treat the 15-sample result
as proof the mechanism is wired and alive across the real `qvm` EL2/EL1
boundary, and the stall as a genuinely open finding, not a resolved one.

---

## 2026-06-11 — Phase-1 gate: full FuSa + Cyber V-model cycle on the as-built QHV boundary (Analysis → Design → Implementation → Verification)

Ran the Phase-1 phase-gate review against the *as-built* QHV/TCG boundary —
not the original KVM dual-VM premise, which the QHV pull-forward falsified.
Both safety and security disciplines completed a full V-model loop and
pair-reviewed the cyber-FuSa interaction. **Analysis** appended dated
gate addenda: FuSa added 9 new failure modes (NF-1…NF-9) and deferred ~20
KVM/br0/Linux-guest rows to Phase 2/3
([`../skills/fmea/examples/phase1-cloud-bringup-fmea.md`](../skills/fmea/examples/phase1-cloud-bringup-fmea.md));
Cyber added 6 threats (T29–T34) + 6 assets with `qvm` as the new TCB root
([`tara/phase1-cloud-tara.md`](tara/phase1-cloud-tara.md)). **Design** wrote
8 TSRs ([`fusa/phase1-gate-safety-concept.md`](fusa/phase1-gate-safety-concept.md))
and 9 TCRs ([`cyber/phase1-gate-cybersecurity-concept.md`](cyber/phase1-gate-cybersecurity-concept.md));
the shared entropy finding (NF-5 ≡ T31, the only *concretely evidenced*
defect — `PRNG is not seeded` yet `sshd` starts) is owned by Cyber as
`TCR-ENT-001` and cited by FuSa as a precondition (`AoU-ENTROPY`), not
double-specified. **Implementation** built 8 host-side gate scripts under
`scripts/qhv/` (bring-up verifier, entropy fail-secure gate, g2.conf
validator, per-extent artefact manifest) + a build-host package-completeness
assertion in `build-qnx-ifs.{bat,sh}`. **Verification** *ran* them against
the captured boot log: the verifier correctly BLOCKs on the resource-manager
arm failure and FLAGs dead-PE/net-down; the entropy gate fails secure on the
unseeded state; the manifest catches tamper/truncation/missing-descriptor
([`fusa/phase1-gate-verification.md`](fusa/phase1-gate-verification.md),
[`cyber/phase1-gate-verification.md`](cyber/phase1-gate-verification.md)).
Verification raised one fail-open finding — **CV-1**: the g2.conf validator
accepted an *empty* config (it checked forbidden-absence, not
required-presence), so a truncate-to-empty attack slipped the gate — which
Implementation then fixed with a required-directive floor (`system`/`ram`/
`cpu`/`load` + ≥1 `vdev`) and Verification re-confirmed regression-clean.
**Honest framing:** all of it is study-level on a TCG leg — the gates are
*bring-up decision* checks parsing a serial log, NOT certified in-operation
safety/security mechanisms with quantified diagnostic coverage / FTTI; the
guest→host-escape / FFI / hardware-isolation residuals (NF-3, NF-7,
TSR-FFI-001, TCR-HYP-001/T30) are explicitly **deferred to Phase 3** (Orin /
real EL2+SMMU), not discharged.

---

## 2026-06-11 — Milestone (Phase-7 pull-forward): QNX Hypervisor (QHV) boots a QNX guest under QEMU-TCG

Brought the Phase-7 QHV exploration forward and got a **real Type-1 hypervisor
hosting a guest**, entirely on the local Windows build host — no AWS, no KVM.
Chain of findings: (1) AWS non-metal Graviton exposes **no `/dev/kvm`** (proven
empirically on a t4g.small probe — EL2 is not passed through by Nitro), so any
hardware-accelerated hypervisor (KVM *or* QHV) needs `*.metal` or real silicon;
the accessible path to *demonstrate* QHV is QEMU-TCG emulating an EL2-capable
CPU. (2) SDP 8.0.4 already ships the QHV host: `qvm` aarch64 binary
(`target/qnx/aarch64le/sbin/qvm`), `libhyp`, and `target.hypervisor.core` are
installed. (3) Official build path is mkqnximage: `--type=qvm` builds the guest,
`--type=qemu --qvm=yes --guest=<dir>` builds the host that embeds it under
`/data/hypervisor/`. (4) Boot under `qemu-system-aarch64 -machine
virt,virtualization=on -cpu max -accel tcg` so QHV's `el2-host`/VHE comes up.
**Result:** host boots as `qnx-qhv` (machine `QEMU_virt`); `qvm @g2.conf` then
boots a guest that reaches `Startup complete` as `qnx-guest` on machine
`ARMv8_Foundation_Model` — the *virtual* platform QHV synthesises, i.e. the
Type-1 partition boundary is real. Curated log:
[../logs/sample-boot/qhv-tcg-host-and-guest-boot.log](../logs/sample-boot/qhv-tcg-host-and-guest-boot.log).
Gotchas recorded: the stock `start_guest` wires a virtio-net peer that needs the
host io-sock stack, which does **not** initialise on this qemu-virt build
(`network stack down` / `Address family not supported`) — worked around with a
no-network qvm config auto-started via a custom `post_start.custom` snippet;
driving the guest start over the TCG serial console interactively drops
characters, so the start was baked into the image instead. **Honest framing:**
TCG proves the QHV *software* architecture (qvm config, vdev instantiation, guest
isolation, EL2/VHE host) — not hardware timing/acceleration (needs metal/Orin).
Note this supersedes the earlier Track-A framing where the cloud leg ran a QNX
*Neutrino* guest under QEMU/**KVM** on c7g.large — that KVM-on-cloud assumption is
now falsified (see finding chain above); KVM acceleration belongs on Orin (Phase 3).

---

## 2026-06-10 — Phase 1 finding: first QNX aarch64 IFS built on the Windows host (missing `target.qemuvirt` package)

First real `mkqnximage --type=qemu --arch=aarch64le --build` on the local
Windows build host (SDP 8.0.4, install root `C:\Users\andy8\qnx800`) **failed**
with `Host file 'startup-qemu-virt' not available / Failed to create ifs boot
image`. Root cause: a default SDP 8.0.4 install carried the aarch64 kernel
(`procnto-smp-instr`), the `*.boot` prefabs and the aarch64 host toolchain, plus
the **`com.qnx.qnx800.quickstart.qemu`** prebuilt run-image — but **not**
**`com.qnx.qnx800.target.qemuvirt`**, which is the package that installs the
board startup binary `startup-qemu-virt` into
`target\qnx\aarch64le\boot\sys\`. `mkqnximage`'s `--build` needs that startup
binary; `quickstart.qemu` (a ready-to-run image) does not provide it. Fix was
CLI-only, no GUI: `qnxsoftwarecenter_clt.bat -installIU
com.qnx.qnx800.target.qemuvirt` (use `-list` / `-listInstalledRoots` to
inspect). After install the build **succeeded**: `ifs.bin` ~9.3 MB plus a raw
disk. This is a genuine BSP-bring-up flavour finding — an incomplete
package-dependency selection on the build host, exactly the class of issue real
BSP integration hits. **Honest framing:** this is build-host tooling, not a port
— it says nothing about whether the IFS boots on Graviton (still the open
Phase 1 question below). Secondary finding: `mkqnximage` emits a **split VMDK** —
`disk-qemu.vmdk` is only a ~169-byte `monolithicFlat` *descriptor* pointing at the
~150 MB raw extent `disk-qemu`; the repo's scp/README/`twin/sync.sh` instructions
listed only `ifs.bin` + `disk-qemu.vmdk`, which would fail to boot on the runtime
host. Corrected across `scripts/` in the same commit (extent now travels with the
descriptor everywhere; raw-disk alternative documented).

---

## 2026-06-10 — Decision: adopt a two-track hybrid (keep QEMU-IFS BSP track, add QNX-on-AWS AMI runtime)

Triggered by the discovery that AWS Marketplace offers a **QNX OS 8.0 AMI**
(the "QNX Accelerate" / Graviton path), where QNX runs as the EC2 instance OS
directly — no QEMU, no custom IFS, no BSP bring-up. Rather than pivot the whole
project to the AMI (which is far lower-friction but discards the BSP /
bootloader / dual-VM partition story that is this portfolio's strongest DRIVE OS
SE differentiator), the project adopts a **hybrid**: **Track A** keeps the
existing QEMU-guest / self-built-IFS path (dual-VM partition proxy on Graviton +
Orin hardware twin) for the BSP, bootloader, partition-isolation and twin-diff
narrative; **Track B** adds the QNX-on-Graviton AMI as a low-friction *single*
QNX target for the application layer — native IPC / resource-manager / scheduling
demos, cross-compile→S3→run pipeline, GitHub-Actions CI/CD, and a standalone
`docs/virtual-target-analysis.md` writeup. Architectural caveat recorded: the AMI
makes QNX the OS, so the **dual-VM partition model stays on Track A only**; Track B
is single-QNX by construction. Unexpected upside: Track B adds a **third runtime
substrate** (QEMU-guest vs AMI-on-Nitro vs Orin), turning the Phase 4 twin diff
from a 2-point into a 3-point comparison. Build-host decision for Track B: **no
persistent cloud x86 build host** — use GitHub-Actions hosted runners for CI
builds plus the existing local Windows SDP for dev iteration (flagged open risk:
headless SDP install + Everywhere license activation in CI is non-trivial; license
via secrets/SSM, SDP install cached). Track B infra to be Terraform under
`infra/` (one c7g.xlarge from the AMI + restricted SG + S3), AMI ID as a
variable since Marketplace subscription is a human prerequisite; cost estimate
~$15–20/mo + unknown AMI software fee (verify on listing), well under the €100
target. **Status:** decision recorded; Terraform not yet written (awaiting
Marketplace subscribe + software-fee confirmation + explicit apply approval).

---

## Phase 1 — Cyber-Analysis TARA (TBD: gate review)

> **Study-level only; not 21434 evidence. TARA here is illustrative,
> not the work-product a real programme would audit.**
>
> Starting-point Phase 1 cloud-twin TARA produced by the Cyber-Analysis
> agent before any IPC traffic exists. Full document:
> [tara/phase1-cloud-tara.md](tara/phase1-cloud-tara.md). 21 threat
> scenarios across the QNX guest, Linux guest, host bridge `br0`, and
> IFS build pipeline. Top-3 risk: **T4** Linux→QNX bridge flood
> starving the Safety guest's virtio-net ring (Risk 5, cyber-FuSa
> candidate); **T17** tampered `mkqnximage` build inputs producing a
> malicious IFS booted by both twins (Risk 4, supply-chain cyber-FuSa
> candidate); **T7** tampered Ubuntu cloudimg subverting the Compute
> guest kernel (Risk 4, cyber-FuSa candidate). Thirteen threats are
> flagged as cyber-FuSa interaction candidates (T1, T2, T4, T5, T6,
> T7, T10, T11, T12, T14, T15, T17, T21) for joint review with the
> parallel FuSa-Analysis HARA at the Phase 1 gate — note especially
> the alignment with FuSa's B5 (bridge L2 promiscuity) and K2 (wrong /
> cached IFS) findings. Six open questions handed to Cyber-Design
> (peer authentication, anti-replay primitive, `tap-qnx`
> rate-limiting, build-pipeline integrity controls, KVM-escape
> posture, bridge MAC filtering). §2 of
> [security-model.md](security-model.md) updated with populated
> Likelihood/Impact ratings.

---

## Phase 1 — FuSa-Analysis HARA (TBD: gate review)

> _Study-level only; not certification evidence._
>
> Initial HARA + Design FMEA for the Phase 1 cloud twin (QNX SDP 8.0 +
> Linux aarch64 on Graviton QEMU/KVM) is captured in
> [`skills/fmea/examples/phase1-cloud-bringup-fmea.md`](../skills/fmea/examples/phase1-cloud-bringup-fmea.md).
> Scope is the cloud twin only; Orin / hardware-twin failures are
> deferred to Phase 3. Top hazards at notional integration level:
> HE-02 / HE-03 / HE-06 (loss or stale Safety-partition IPC) score
> ASIL-D under the study's notional vehicle integration; HE-04 / HE-07
> / HE-13 / HE-15 score ASIL-C. Top D-FMEA rows (RPN ≥ 60) are H1
> (KVM trap unbounded latency), Q6 (RT deadline miss from KVM trap),
> B2 (stale tap flap), B5 (bridge L2 promiscuity — also a cyber-FuSa
> interaction candidate), N3 (KVM IRQ tail latency), N1 (silent
> virtio-net drop), and K2 (wrong / cached IFS at runtime). Ten open
> questions are handed to FuSa-Design (FTTI numbers, payload integrity
> layer above virtio-net, freedom-from-interference residual-risk
> argument given the shared host kernel, IFS integrity binding from
> build to runtime). Pair-review with Cyber-Analysis at the Phase-1
> gate to close the five interaction-analysis items called out in the
> worksheet.

---

## Phase 4 — TBD: cloud-vs-HW twin diff

> _Stub. Filled in after the twin-diff measurement run lands. Expected
> contents: P50/P99/P99.9 latency delta, boot-time delta, jitter
> profile delta. Hypothesis going in: IPC-path latency tracks within
> a small constant; boot times diverge meaningfully due to host CPU
> and scheduler differences._

---

## Phase 3 — TBD: hardware twin port to Jetson Orin Nano

> _Stub. Filled in after the same `mkqnximage --type=qemu --arch=aarch64le`
> IFS has been booted on QEMU-on-Orin under L4T. Expected contents:
> (a) does the unmodified IFS boot? (b) JetPack 6 KVM availability;
> (c) RAM headroom on 8 GB; (d) any GICv3 / A78AE quirks._

---

## Phase 2 — TBD: cloud-twin IPC latency baseline

> _Stub. Filled in after the C99 client/server has been run to 100k
> iterations. Expected contents: P50, P99, P99.9 of round-trip on
> Graviton + virtio-net + host bridge; time-base normalisation
> notes; warm-up tail behaviour._

---

## Phase 1 — TBD: cloud-twin bring-up

> _Stub. Filled in after both VMs boot under KVM-on-Graviton. Expected
> contents: virtio-mmio vs virtio-pci default in mkqnximage SDP 8.0;
> whether x86_64-built aarch64 IFS runs under KVM-on-Graviton without
> modification; QNX boot time on Graviton._

---

## 2026-05-07 — Phase 0 amendment: build host pivots to local Windows (EC2 fallback retained)

F1 in [bsp-selection.md](bsp-selection.md) previously asserted "QNX SDP
8.0 host toolchain is x86_64 Linux only." A second pass through the
QNX Software Center download matrix on a QNX Everywhere account
confirmed that SDP 8.0 ships **both** a Linux x86_64 native installer
**and** a Windows native installer; macOS (Intel and Apple Silicon)
remains unsupported. The earlier wording was a partial inspection,
not a complete one, and is being corrected. Consequence: the
build-host role moves from "AWS t3.medium x86_64 Ubuntu (rented EC2)"
to **local Windows PC as the primary path**, with the EC2 x86_64
build host retained as an explicit **fallback** for users without a
local x86_64 Windows or Linux machine. Cost win: removes EC2
build-host hours from the AWS Free Plan budget (~$100 / 98 days
remaining at decision time; existing $80/month budget alert and $5/day
Cost Anomaly Detection unchanged). Friction win: removes ssh / X11 /
browser-flow hops needed to drive the QNX Software Center GUI on a
remote EC2 box. Validation surface unchanged: per F1's existing
arch-agnostic-IFS argument, `mkqnximage --arch=aarch64le` produces
the same blob whether run on Windows or Linux x86_64; runtime side
stays Graviton arm64. Honest-framing caveats: the build host runs only `mkqnximage` and
host-side QNX tooling — no guests run on the build host — and the
IFS it produces is target-aarch64, cross-compiled by SDP 8.0's
host toolchain. Per F1's arch-agnostic-IFS argument, swapping
Windows for Linux x86_64 on the build host affects only build
metadata (embedded paths, timestamps), not the ARM code QNX boots;
F5 Q2 already validates the load-bearing claim that *any*
x86_64-built IFS boots on Graviton, and that question is host-
platform-agnostic. (An earlier wording of this amendment treated
"Windows-built vs EC2-built byte-equivalence" as a separate
Phase 1 verification target — that was over-specified and is
withdrawn in the same commit that corrects it; see the F5 note in
[bsp-selection.md](bsp-selection.md).) A local Windows build host
also **does not** demonstrate any closer parity to a real DRIVE OS
customer build environment than EC2 does — it is purely a
friction/cost optimisation, not an architectural improvement. Cross-link: see F1
in [bsp-selection.md](bsp-selection.md). Implementation agent will
follow up with the actual edits to F1, README.md, CLAUDE.md,
docs/architecture.md, scripts/README.md,
scripts/bootstrap-build-host.sh, agents/research.md,
agents/implementation.md, and a new scripts/build-qnx-ifs.bat.

---

## Apr 2026 — Phase 0 BSP research

QNX SDP 8.0 host toolchain is x86_64-only, which forces a hybrid
build/runtime architecture (x86_64 build host → arm64 runtime host).
Two BSP paths are viable under SDP 8.0: the official `mkqnximage
--type=qemu --arch=aarch64le` (used as the Phase 1 baseline) and the
community MIT-licensed `joexue/qemu-virt` (deferred to Phase 2+
study). KVM acceleration on Graviton works with stock Ubuntu 22.04.
The QNX Everywhere NCEULA covers personal/portfolio/demo use but
forbids redistributing QNX binaries — so the repo ships scripts and
logs only, never IFS images.

Full write-up: [bsp-selection.md](bsp-selection.md).
