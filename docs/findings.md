# Findings Log — append-only, newest at top

A running record of empirical findings, surprises, and decisions that
came out of actually running the toolchain. Phase 0 entries point to
their detailed write-ups; Phase 1+ entries will land here directly.

Format: one entry per finding, dated, one-paragraph max plus links.

---


## 2026-09-19 — saturating the GPU does not measurably disturb the QNX guest (a null result)

The KVM boot made a question askable that had not been askable before. The 2026-09-18 entry
measured what QNX costs the GPU; this measures the other direction — **what the GPU costs
QNX** — which under TCG would only have measured the emulator.

**Method.** One held TCP connection to the guest's `qnx-safety-monitor` on :7100 over the real
`br0`/`tap-qnx` bridge; each sample sends a valid 64-byte frame carrying a claim the monitor
accepts, timed with `perf_counter`. 3000 timed samples per arm at 2 ms spacing, after 200
warm-up samples that are timed and discarded. Arms: **idle**, **gpu** (`fma.cu`, GR3D 99%,
~1555 GFLOP/s), **cpu** (one core at 100%, GR3D 0%), **idle2**; then the gpu/idle pair repeated
interleaved.

**The `cpu` arm is not optional.** `fma.cu` drives the GPU from a CPU thread, so "GPU
saturated" and "system busier" arrive together. Without a CPU-only arm at the same footprint,
any change could not be attributed to the GPU rather than to contention.

**Result: no measurable interference.** Pooled, idle (n=12,000) against gpu (n=9,000):

| quantile | idle | gpu | delta |
|---|---|---|---|
| p50 | 0.298 | 0.293 | **−1.5%** |
| p99 | 0.646 | 0.619 | **−4.2%** |
| p99.9 | 0.772 | 0.730 | **−5.3%** |
| p90 | 0.342 | 0.358 | +4.7% |
| max | 1.021 | 0.827 | idle is worse |

The GPU arms are **faster at three of four quantiles**, and the worst single sample in the whole
experiment came from an idle arm. A real interference effect cannot be negative at p99 and
positive at p90. Per-arm p90 ranges overlap outright (idle 0.333–0.357, gpu 0.326–0.386), and
the third gpu arm's p90 is lower than every idle arm.

**A hint that dissolved, recorded rather than dropped.** The first run showed gpu p90 at +11%
over idle. That is why the arms were repeated interleaved — and the repeat killed it. Had the
run stopped at one pass, that +11% would have looked like a finding.

**Validity.** `bad=0` and `rejected_by_monitor=0` in all eight arms; the guest's own console
independently logs eight × `seen=3200 accepted=3200 rejected=0`. `idle2` returned to `idle`
(p50 0.297 vs 0.298), so thermal drift does not confound it (47.8 → 50.2 → 48.7 °C).
`disk-qemu` was byte-identical before and after all eight arms (`-snapshot`). Records:
[`results/orin-native-port/20260919T-interference/`](../results/orin-native-port/20260919T-interference/).

**What this does not show.** It is **not** freedom from interference, and no ISO 26262 or ASIL
claim attaches — one workload, one direction, one load level, one board. Not a QNX real-time
result: nothing here is a bounded-latency guarantee and the guest is not configured for one.
Not hypervisor IPC latency — under A6 there is no hypervisor; the figure is a whole-system
round trip through the Linux stack, virtio-net, the bridge, `io-sock`, the monitor and the
guest's scheduler. Not isolation: the boundary is KVM, where **Linux owns the QNX guest's
memory**. The guest had 2 vCPUs of 6 cores and a single busy core leaves four idle, so this says
nothing about full CPU saturation. n=3000 per arm supports p99; p99.9 is thin and reported as
indicative only.

---


## 2026-09-19 — the cloud twin's original premise is revivable, and today's run is the proof

A side effect of the cross-vendor check below, and arguably the more consequential half.

**What the cloud twin was for.** It was *designed* as AWS Graviton (`c7g.large`, arm64) for one
reason: a second **ARM** host that could run the same images under **KVM**, so the twin diff would
differ in the host and nothing else. That died in 2026-06, when ADR-002 found non-metal Graviton
exposes no `/dev/kvm`, and the leg fell back to the Windows PC under TCG — at which point, as
[digital-twin-design.md](digital-twin-design.md) §1 puts it, "there was nothing left that required
the leg to be in the cloud at all."

**ADR-002 was not wrong; it was read too broadly since.** Its own words are *"Any
hardware-accelerated partitioner — KVM **or** QHV — needs `*.metal` or real silicon."* That
sentence predicted exactly what happened today. What has been repeated downstream ever since, and
what is stale, is the flatter clause beside it: "KVM-on-cloud is dead." The limit was always
**non-metal**, never **cloud**.

**Today's evidence.** The `a1.metal` run below is bare metal: it reported `/dev/kvm` present and
`Hyp mode initialized successfully`, and our QNX guest booted on it under `-enable-kvm` to
`Startup complete` and the banner. That is **the first time a QNX guest has run under KVM on an AWS
host in this project** — it just happened while answering a different question.

**So the original twin becomes possible for the first time:**

| leg | designed | status before today | status now |
|---|---|---|---|
| hardware (Orin) | ARM + KVM | blocked by GICv3/NISV | **works** (2026-09-18) |
| cloud (Graviton) | ARM + KVM | no `/dev/kvm` on non-metal → abandoned | **works on `*.metal`** (2026-09-19) |

**What this is not.** No cloud *leg* has been built: one 60-second boot arm is not a leg, and **no
timing of any kind was taken on either side**. The twin diff has not been re-run and its earlier
results stay architecture-version history. `a1.metal` is Graviton1 / **Cortex-A72** against the
Orin's **Cortex-A78AE**, so even a revived pair differs in a *bundle* (core generation, kernel, OS),
not in one variable — the honest framing §1a already insists on. `c7g.metal`, the closer match,
stays quota-blocked at 64 vCPU. Non-metal Graviton still has no `/dev/kvm`. The Windows PC is
x86_64 and can **never** use KVM for an ARM guest, so any Windows-side pair is TCG-on-both by
necessity, not by choice. And the QNX Hypervisor still cannot run under KVM anywhere: it needs EL2,
which ARM KVM does not nest on A78AE.

**Cost, which is now a design input.** A board on a desk is free per run; a bare-metal cloud host is
~$0.466/h. Reviving the twin means paying per measurement, which is a different discipline from
anything this project has done so far.

---


## 2026-09-19 — the fix holds on a second vendor's silicon: a matched pair on AWS `a1.metal`

The 2026-07-29 entry below established that the GICv3/NISV hang was **not** Tegra-specific: the
same IFS died the same way on AWS `a1.metal` — Graviton1, Annapurna Labs, Cortex-A72, a different
vendor and core generation. But that was **symptom identity only, n=1**: no trace ever confirmed
the `a1.metal` hang was the same NISV fault (hypothesis **H-C**). Today asks the other half: does
the *fix* travel as well as the defect did?

**Method — control first, one variable.** The 2026-07-29 launch line verbatim, on a fresh
`a1.metal` in eu-central-1, changing exactly one thing per arm: which IFS boots. Same
`disk-qemu` (`fd2ee67d…`, byte-identical to that run), same QEMU 6.2.0 from the distro, kernel
`6.8.0-1063-aws` against that run's `-1061`. If the shipped startup did not hang here *today*,
the test arm would prove nothing and the run would be void.

| arm | IFS | serial | result |
|---|---|---|---|
| control | shipped `startup-qemu-virt` (`92868b2f…`) | **17 bytes** | `FOUND GICv3 ITS`, then silence — the historic hang, reproduced |
| test | rebuilt with `-fno-auto-inc-dec` (`26170cd7…`) | **1301 bytes** | through to `Startup complete` and the guest banner |

`QEMU_EXIT=124` in both arms is the 60 s timeout wrapper, not a crash — the same convention as the
2026-07-29 header. Capture:
[`logs/sample-boot/aws-a1-metal-kvm-fix-crossvendor.log`](../logs/sample-boot/aws-a1-metal-kvm-fix-crossvendor.log).

**What this settles.** The defect reproduced on two vendors' silicon, and now the fix does too, each
with its own same-session control. The cause is in QNX's board bring-up code, not in Tegra234, and
`-fno-auto-inc-dec` removes it on Cortex-A72 as it does on Cortex-A78AE. Hypothesis 7 in the
`gicv3-nisv-debug` reports — "Tegra234 / Cortex-A78AE / VHE-specific silicon quirk" — is refuted
rather than merely weakened.

**What it does not settle.** **H-C is still open as written.** No trace was taken on `a1.metal`, so
this does not prove the *2026-07-29* hang was NISV by data; what it shows is that today's
shipped-startup hang and its removal both reproduce here. It is one run per arm. No timing of any
kind was taken, and the guest's entropy and networking errors in the test arm are the known
virtio slot-order issue, not part of this result. The rebuilt startup is **ours**; QNX ships no such
binary, so this remains evidence about a defect, not a supported configuration. And per the
2026-09-18 decision the defect is **not being filed** with QNX/BlackBerry — this run strengthens a
record, not a report.

**Cost and hygiene.** One instance, ~1 h, ~$0.5, terminated immediately; `shutdown -h +90` plus
`--instance-initiated-shutdown-behavior terminate` were set at launch so it would self-terminate
even if contact were lost. No instance id, account id or address is recorded in the capture or
here: the 2026-07-29 run leaked its instance id into git history and needed a `filter-branch` to
clean, so this one redacts at capture time by construction.

---


## 2026-09-18 — a service across the partition: L4T infers on the GPU, QNX judges the claim

With QNX booting under KVM and the GPU staying with L4T, the architecture is finally in a state
where something can be *built on it* rather than about it. This is the first cross-partition
service: **L4T classifies a real image on the GPU and QNX decides whether to believe it.**

**The two ends.** On L4T, `compute_client` loads a TensorRT engine, reads an actual MNIST PGM from
`/usr/src/tensorrt/data/mnist/`, runs it on the Ampere GPU, and takes class and confidence from the
network's own output — never fabricated; if it cannot classify it exits non-zero. It sends class,
confidence and its own GPU time as a 64-byte frame in the existing
[`ipc-test/common/frame.h`](../ipc-test/common/frame.h) layout. In the QNX guest,
[`ipc-test/qnx-safety-monitor/`](../ipc-test/qnx-safety-monitor/) checks the claim against
plausibility rules and writes a verdict back. Transport is a **real `br0`/`tap-qnx` bridge**, not
slirp — the guest at a static address, reachable both ways.

**Both arms ran on the board.**

| arm | inference | claim | monitor verdict |
|---|---|---|---|
| valid | `3.pgm` → class 3, 100%, 0.124 ms | as measured | **ACCEPT** (`reason=ok`), rc=0 |
| corrupted | `7.pgm` → class 7, 100%, 0.125 ms | class forced to 42 | **REJECT** (`class-out-of-range`), rc=3 |

The guest's own console corroborates independently:
`monitor: REJECT seq=1 class=42 conf=100 us=125 reason=class-out-of-range`, with counters moving
`seen=1 accepted=1 rejected=0` then `seen=1 accepted=0 rejected=1`. The verdict logic was also
self-tested at its boundaries (10/10: `conf=60` accept vs `59` reject, `100000us` accept vs
`100001us` reject, and check ordering). Console capture:
[`results/orin-native-port/20260918T-kvm-gpu/`](../results/orin-native-port/20260918T-kvm-gpu/).

**Two engineering notes worth keeping.** The monitor is started from **inside the IFS**, on a line
placed after `startup.sh` returns — `post_startup.sh` lives in the system partition, so auto-starting
it the conventional way would have meant rewriting `disk-qemu`, which published results depend on.
And this run used `-snapshot`: the disk hash was byte-identical before and after, fixing the silent
drift the concurrency runs had (recorded in that run's provenance note).

**What this does not show.** The monitor is **not a safety mechanism in any ISO 26262 sense** and no
ASIL claim attaches to it; its rules are legible plausibility checks, not a validated diagnostic. No
timing or latency claim — the frame round trip was never measured as a latency, and the inference
figure is TensorRT's own for one execution, not a benchmark. Nothing here shows isolation,
containment or freedom from interference: the boundary is KVM, where **Linux owns the QNX guest's
memory**, which is the inverse of the Type-1 arrangement this project's DRIVE OS comparison is
against. QNX still cannot touch the GPU. One image per arm, one run each — a demonstration that the
shape works, not a result about how well.

---


## 2026-09-18 — L4T keeps the GPU at full throughput while QNX runs beside it under KVM

The KVM fix above is only interesting if it buys something. What it buys is the architecture the
GPU question had been blocking on: **L4T on the metal owning the GPU outright, with QNX as a
hardware-virtualised guest beside it** — no pass-through, no vGPU, no emulation. QNX never touches
the GPU; the question is whether putting it there costs the GPU anything.

**Method.** A sustained FP32 FMA load on the iGPU (`orin-native/gpu-concurrency/fma.cu`, 512x256
threads, 200k iterations per round, 30 s arms, CUDA 12.6 / `sm_87`), with `tegrastats` sampling
`GR3D_FREQ` alongside so that "the GPU is busy" is measured rather than assumed. Liveness of the QNX
guest is a **byte-exact echo**, not a process check: `probe_qnx.py` sends valid 64-byte frames in the
[`ipc-test/common/frame.h`](../ipc-test/common/frame.h) layout through slirp `hostfwd 17000->7000`
and requires the frame back unchanged. Two arms, twice each.

| arm | QNX guest | mean GFLOP/s | GR3D mean | GR3D peak |
|---|---|---|---|---|
| baseline  | none | 1554.6 | 84% | 99% |
| baseline2 | none | 1553.9 | 84% | 99% |
| concurrent  | live under KVM | 1557.2 | 84% | 99% |
| concurrent2 | live under KVM | 1558.2 | 84% | 99% |

**Reading it honestly: the concurrent runs are nominally _faster_.** The two solo runs differ by
0.7 GFLOP/s; both concurrent runs sit 3-4 GFLOP/s above both of them. A negative cost is not a
speedup — it is the signature of run-to-run noise, and the correct statement is that **no cost was
measurable at this sample size**, not that concurrency is free.

Meanwhile the guest answered **21 of 21 frames byte-exact** across five connections — before the
load, twice at 99% GPU utilisation, and after — at mean round trips of 0.62–1.55 ms, and its own serial
log independently records every one (`client connected from ...`, `client EOF after N frames`), so
host and guest corroborate each other. Run records:
[`results/orin-native-port/20260918T-kvm-gpu/`](../results/orin-native-port/20260918T-kvm-gpu/).

**What this does not show.** It is **not** a GPU partitioning, isolation or freedom-from-interference
result — nothing divides the GPU, and L4T owns it outright. It is **not** a claim that QNX can use
the GPU; in this architecture it cannot. The probe round trips are a **liveness signal, not a latency
measurement** (one host, slirp NAT, a handful of frames, no percentiles). It is not a load, stress or
soak test: 30 s arms, the guest otherwise idle, n=2 per arm, no thermal control (board ~47-48 C). And
the GPU figure is raw FMA ALU throughput — not GEMM, not inference, and not to be quoted as a TFLOPS
headline.

---


## 2026-09-18 — QNX boots under KVM on the Orin: the GICv3/NISV blockage is cleared at the source

Since 2026-07-28 every KVM boot of the QNX IFS on this board ended identically — `FOUND GICv3 ITS`,
then seventeen bytes and silence — and on 2026-07-29 the same hang reproduced on a second vendor's
silicon ([a1.metal](../logs/sample-boot/aws-a1-metal-kvm-nisv-repro.log), Graviton1 / Cortex-A72).
On 2026-09-08 it was root-caused to a writeback MMIO store (`str w3,[x0],#4`, GICD+0x420) that
reports no instruction syndrome (ISV=0), which KVM cannot decode, so the guest exits
`KVM_EXIT_ARM_NISV`. The fix was known and unusable: `-fno-auto-inc-dec` removes that instruction
form, but relinking `startup-qemu-virt` needs its board source, and **the SDP ships that binary
without its source**. That is what changed today — we wrote the board.

**What was built.** `orin-native/startup/qemu-virt/`, written against the device tree QEMU actually
generates rather than copied from `t234-orin-nano`: the PSCI conduit is probed from the tree
(`method = "hvc"`) instead of forced to SMC, `psci_cpu_id` is left as the library's identity mapping
(the virt machine's MPIDRs are flat, unlike Tegra's), and RAM comes wholly from `init_raminfo_fdt()`.
The startup library was rebuilt with `-fno-auto-inc-dec`; non-SP writeback stores in `gic_v3.o` went
to **0**, counted from 2,295 disassembled lines of our own build — never from a QNX-shipped binary
(NC QDL v7 4.6(c) stays clean).

**Which startup is actually in the image, on two independent discriminators.** The IFS was built by
running `mkifs` directly with an overlay repo ahead of `$QNX_TARGET` in `MKFS_PATH`, so the bare name
`startup-qemu-virt` resolves to ours without touching the SDK. Proof it did: the `_CS_MACHINE` string
we compiled in appears **once** in our image and **zero** times in the known-good one, with a positive
control (our startup ELF 1 hit, the SDK's 0); and the startup entry point differs, `40081ab8` vs
`40081da8`. This mattered — `ifs.build` sets `[+optional]`, so an unresolved file is skipped silently
and `mkifs` still exits 0. A zero exit proves nothing here; only the contents do.

**The experiment.** One variable, the IFS. Control — the SDP's shipped startup, same launch line, same
host, same session: 17 bytes, dead after `FOUND GICv3 ITS`, the historic hang reproduced today. Test —
652 bytes, through to `Startup complete`, run twice with **byte-identical** captures. Repeated on QEMU
6.2.0 and 11.1.0 with byte-identical output, so the QEMU version is not a factor. With disk, net and
rng presented in the slot order [`launch-qnx-on-orin-tcg.sh`](../scripts/orin/launch-qnx-on-orin-tcg.sh)
documents, the guest reaches `Process count:22`, brings up `io-sock`, starts sshd, and its echo server
listens on :7000 — and prints its own banner:

```
QNX qnx-safety 8.0.0 2026/02/27-10:59:13EST QEMU_virt_(aarch64),_KVM_guest aarch64le
```

Captures: [`logs/sample-boot/orin-kvm-*.log`](../logs/sample-boot/) — control, two test runs, the
11.1.0 arm, the with-disk arm, and the full boot (guest IP redacted at the source).

**What this does not show.** No timing, latency, throughput or boot-time claim of any kind — none was
measured. Nothing about two guests under KVM. Nothing about the GPU. **Nothing about the QNX
Hypervisor under KVM**: QHV needs EL2, ARM KVM does not nest on A78AE, and that limitation is
untouched by this — do not read this entry as making the QHV legs KVM-capable. No isolation or
freedom-from-interference claim. And this is **not a supported configuration**: the fix lives in a
startup we rebuilt, and QNX ships no such binary — so it is evidence about a defect, not a product
capability.

**Not being filed (owner decision, 2026-09-18).** The evidence chain is now as strong as it will get —
their own BSP source emits the instruction, one flag removes it, and a matched control/test boot pair
on real silicon separates the two. The owner decided not to report it to QNX/BlackBerry. Earlier
entries and action items proposing that filing are superseded by this decision, not by new evidence.

---


## 2026-09-17 — the harness self-test's verdict depended on how fast it ran, and four checks drifted

Found while checking whether the X-f-c gate change had broken anything: `s1-board.sh harness-selftest`
reported `FAIL 1 of 778`. It had broken nothing — the same check fails on pristine HEAD — but the failure
was not the flake it first looked like. **The self-test's verdict was a function of its own speed.**
`cmd_harness_selftest` stamps `now=$(date +%s)` once and never again, then writes fixtures as `now - N`,
while the code under test reads the **live** clock (`com3_class`'s `idle`, and `capture_state` /
`capture_left_s`). Every fixture is therefore `N + (seconds elapsed since the stamp)` old by the time its
check runs, so any assertion that must stay **below** a threshold flips once the run is slow enough.
`ADVICE_NO_SAMPLE=1` rules out the sampling sleep: the drift is pure run speed.

**How it presented.** One failure on a quiet machine (`advice J4 F25w at 400 s`, a 200 s margin reached at
check #316), three under load, four in a review agent's run — the same defect each time, not different
ones. Two of them (`j_capture_gate`, 100 s margins) never call `com3_advice` at all; they reach the clock
through `capture_state`, so a fix aimed at the advice path alone would have left them broken. That scope
correction came from adversarial review; the first diagnosis had claimed exactly one exposed check, and
reached for the word "flake" before checking the gate that governs it.

**The fix, test fixtures only.** Six sites take the live clock at creation, and the `wqadv` block re-stamps
`now` before its calls, because the `armed_epoch` **arguments** are `now`-relative and the
detached-sequence hold is compared against the live clock. The mtime and the growth epoch at `:8377`/`:8378`
had to move together: `com3_class` takes `mt = max(mtime, grow)`, so a live mtime beside a frozen grow would
overtake it and break a test that passes today. Both patterns were already in the file — the j6 capture
headers use `"$(date +%s)"`, and the j7a block re-stamps `n7` and is drift-immune because of it. No
production code changed. A test-clock override was rejected deliberately: it would make time fakeable in
the gates enforcing capture life and uptime, in a harness where `QUIESCE_MAX_UPTIME_S` is not overridable
(§7.3), which trades a test bug for a safety hole.

**Verified, and the two runs did not carry identical code.** `PASS 778 checks` on both. The near-idle run
at 1.33 s/check exercised exactly what this entry describes, the seven-site fix including the `wqadv`
re-stamp. The loaded run at 3.37 s/check — slower than the run that failed four checks, and therefore the
harder condition — exercised the six-site version, before that re-stamp was added. A re-stamp can only
make `now` fresher and so cannot introduce drift, but that is an argument, not a measurement: **the exact
committed bytes have been measured near-idle only.**

**What this does not show.** The other fourteen frozen fixtures are argued safe, not proven so: they assert
a *class*, read from log content rather than from idle, or they assert `CUT ALLOWED`, which drift only
makes more true. **One known gap is left unfixed:** `:8362`'s header carries `seconds=6000` off the frozen
stamp, so a run exceeding roughly 100 minutes would flip a whole block of advice checks to `capture=expired`
at once. It is recorded rather than repaired, because its margin is not short and widening the patch beyond
what was agreed is its own risk. Nothing here touches the board, any rung, or any recorded reading.


## 2026-09-17 — B5 met: both guests under native qvm on the board, and S1-F is met (QNX plus Linux)

The two-guest rung ran on the board for the first time and passed. It had no precedent: claim R25 — that two
qvm instances on four cores let the QNX guest's banner and IPC complete — was class UNKNOWN, and nothing in
this project had ever run two qvm instances, on the board or under emulation. Three same-day steps made it
runnable: OD9 reversed the guest set to QNX plus Linux, OD7 regenerated the guest and host from clean sources,
and `s1-q2` was built on those regenerated artefacts with D14's derived `--q2-limit 0x8E000000`.

**What ran.** Under the native QNX Hypervisor at EL2 on four cores, the Linux guest and the cloud-leg QNX
guest ran together. The QNX guest reached its banner and the IPC pair completed its 15 iterations, the client
returning success with no sentinel recovery and no bounce — which is not a fix for the A1-era virtio-queue
stall or an explanation of it; it simply did not occur in these 15 iterations. The verdict line: `S1PC step=B5
S1PC verdict=pass`, `item3=pass`, `item5=ok`, with `tier_L5=ok`, `tier_L7=ok`,
`tiers_reached=L0,L1,L2,L3,L4,L5,L7` — L6 is n/a, because this is not a hold rung — `conf_gate=pass`, and
the image, initrd and configuration hashes matching the PC. All three canaries verified before either guest
launched and all three again after teardown; `md5_post` was ok for the image, initrd, configuration, guest and
disk; no failure state was recorded; the bootloader slot read equal to the session's first reading both before
and after; and the board reset itself, with L4T returning unaided. The image was built on the OD7-regenerated
guest, and the board's own md5 checks matched the regenerated values — the first board run these pins have
been through, which also discharges OD9's fourth consequence: this is v1 evidence for item 3, not only an
answer to R25.

**What follows for the record.** Pass item 3 is met, so the three mutually exclusive wordings resolve to the
third: **S1-F is met (QNX plus Linux)**. B5 carries items 3 and 5 only — the parser records items 1, 2 and 4
as `n/a`, and they stay where they were earned, on T1/T2, B3 and B4. That restores freeze gate item 1, which
OD9 had reopened the same morning, and it withdraws nothing from the 2026-09-14 B2 record or from the writer
diagnosis, both of which stand exactly as recorded. **No S1-F rung remains.** What the gate still needs is
written into it rather than run: the manifest itself, item 10's `-smp` field, item 11's two missing size rules,
item 3's exposure declaration, and item 13's 4.6(i) consultation, which gates publication rather than the
campaign.

**A defect found while checking the gate that let B5 run, recorded because nothing else records it.** The
revision-4 precondition at `s1-board.sh:5750` filters B2's readings with `grep -v ' X-f-final$'` and whitelists
no other class. Its own comment says B3-B5 run "while every B2 reading on file is **clean**", and §16.6.1
defines **X-f-c** as exactly that: the confirmatory run clean by §16.6's field rules, MET by §6.7. So a reading
correctly classed X-f-c would survive the filter, make `r4bad` non-empty and **block B3-B5** — the gate is
narrower than both its own comment and the design it implements. `X-f-c` appears in that file only in a
comment, in no conditional, and no self-test covers it. B5 ran today only because B2-a3's record says
`X-f-final`: `--confirmatory` was added to the parser after that reading was taken, and the harness passes the
flag only when D86's key is spent. Nothing is blocked now — the design notes D86's permission is spent, so
the flag has no run to read — but the next confirmatory run would hit it. ~~Not fixed here: it is a gate over a
pre-registered reading rule, and it is the owner's call.~~ **Fixed the same day, on the owner's decision.** The
filter now admits both of §16.6.1's clean classes, and three self-tests cover it: a confirmatory `X-f-c` beside
the original reading blocks neither B3 nor B4 nor B5, and an `X-f-provisional` still blocks, which pins the
boundary at the two **final** classes rather than at every name beginning `X-f`. The sibling gate at the D86
key was deliberately left strict on `X-f-final`: there, an `X-f-c` on file means a confirmatory run has already
been made, so admitting it would hand out a fourth observation against D86's bound of one. No recorded reading
moved, no class was re-labelled, and B5's pass is untouched. Recorded also in the B2-a3 run note.

**What this does not show.** Nothing about duration with two guests: B5 is not a hold rung, tier L6 is n/a,
and the only ten-minute evidence this project holds is B4's, with one guest. No timing, latency or throughput
claim: item 3 is completion only, and the IPC figures the capture carries are evaluation output under NC QDL
v7 4.6(i), unpublished. It still does not show that either guest's RAM came from the second window — no
host-side view of the physical addresses behind qvm's guest RAM was found, so that stays unknown
(`guestram=unknown`, Q14), and D14's premise that window 2 absorbs the guest RAM remains a budget convention
rather than a measurement. The canaries **bracket** the rung rather than cover it: they were read before
either guest launched and again after teardown, never while both guests were running, so this is intactness
before and after two-guest operation, not throughout it. And it is no isolation, containment or
freedom-from-interference claim: two guests ran side by side once, which is one observation and not a series,
and nothing here measures interference between them. One thing the rung could not pre-check is recorded rather
than smoothed over: `s1-q2.kimg` is about four times any previous S1 image and larger than anything previously
kexec'd here, the landing gate was skipped for want of `dyndbg`, and the shim's own check found the landing
sound — the landing hypothesis held at this size and remains a hypothesis. The run record is private and
git-ignored, and no figure is published here.
[s1-design.md](../results/orin-native-port/20260909T1100Z/s1-design.md) §5.2, §16;
[the plan's S1-F block](orin-native-port-plan.md#the-revised-ladder).


## 2026-09-17 — OD7 executed: the guest and host regenerated from clean sources, and the provenance break is closed

The owner reopened freeze item 2 the same day (OD9, QNX plus Linux), which put the QNX guest back into v1
and made its disk a first-class v1 artefact rather than a conditional one. That turned item 8 from housekeeping
into something B5 would stand on. The deferral's stated reason had already expired: the entry below stopped the
rebuild because "S1-F's revision 4 is pre-registered and has not run", and that ladder ran on 2026-09-16, with
B3 and B4 following on 2026-09-17. The same entry asked for the decision to be "re-taken against the real
cost" and to "follow the revision-4 ladder rather than precede it". Both conditions were met, the owner re-took
it, and `scripts/build-qhv.bat` ran its two-stage `mkqnximage` build.

**The result that matters is not a hash.** The as-run configuration now equals the committed
`scripts/qhv/post_start.custom` **exactly** — checked by expanding both through the generator's own
`expand_printf` and diffing. The PO-E record comparison, which used to show one line removed and five added,
now shows **one removed and one added: the load-path substitution alone.** The sentence this log carried since
2026-09-16 — that the guest disk "carries a diagnostic variant of its start-up script that no commit generates,
so the image v1 would freeze is not reproducible from sources" — is no longer true.

**Owner decision O1 is answered by construction, not by judgement.** Regeneration necessarily drops the fourth
`vdev shmem` and its `allow phase2-rq2-probe`, because the staged snippets are already clean and the build copies
them over. The stanza is gone from the as-run text, so it left `g2-m3.conf` and `g2-m3-diag.conf` too. The image
still carries `vdev-shmem.so`: nothing gates the carried `.so` set against the configuration's vdevs, and removing
it would perturb `Q2_NAMES`, `Q2_SDP_FILES`, `s1.build.in` and the q2 `size_check` sum for no functional gain.

**Measured, not assumed.** The guest pair's sizes are unchanged (`ifs.bin` 9,783,916 B, `disk-qvm`
153,432,576 B); only the bytes moved. `disk-qemu` lost 4,096 B. `qnx-host-client` rebuilt to the **identical**
hash, so `PIN_CLIENT` did not move and only two pins did. Because the guest sizes held, D14's derived
`--q2-limit 0x8E000000` survives the regeneration unchanged, with its 16.01 MiB margin intact — that was
checked rather than hoped, since `disk.layout` derives the disk's size from its partition contents.

**It was made reversible first.** `E:/qhv-preserve` already held two independent copies of the four artefacts
with manifests, plus complete output trees; each was verified against its pin before anything ran. Reading
`build-qhv.bat` in full first showed it also rebuilds the ipc-test binaries, so `qnx-host-client` — a third
pinned artefact, and not covered by that preserve — and the `local/snippets` were preserved the same day.

**The cost, paid:** 21 hash values across 12 code and configuration files; two generator gates changed in
`make-m3-images.sh` (the noblk derivation now expects **0** shmem lines, not 4, with the branch kept so it
asserts the stanza has not returned; the PO-E record check now expects the load line alone); three `qhv/`
configurations edited; the tracked twin-leg manifest carrying its new pair with the old one demoted to a
commented earlier-pair line, its own convention.

**What this does not close.** Item 8 is discharged; the freeze is not. ~~**B5 has never run**, and the new pins
have never been through a board run of any kind.~~ **2026-09-17, later the same day: B5 ran on the board and
passed, on these very pins — the board's own md5 checks matched the regenerated guest and disk values, so
the regeneration was checked by the board itself. See this file's B5 entry above.** M3's and M4's recorded figures were measured against the old
artefacts and stay exactly as recorded — they are A4 history, not v1. The five curated boot logs that name the
old host pair are **left untouched on purpose**: they record which images were actually booted, and the images
they name really are gone now. The records are private and git-ignored, and no figure is published here.
[orin-native-port-plan.md](orin-native-port-plan.md#freeze-gate) carries item 8's state.


## 2026-09-16 — S1-F's revision-4 ladder ran on the board: B1, the watcher run and B2 all passed, and B2 is met on the rebuilt image

With the owner at the plug, revision 4's three rungs ran in one session, in the pre-registered order, and each met
its rule. The rule that reads them, its reference and the image pins were registered before any of them ran, so
none of this reading was chosen after a result.

**B1, the option-off startup regression, met.** Its tokens were all present, and the console carried no cache-clean
line at all: with the S1 option off the rebuilt startup does not clean, so the flag gating is correct on the board
and B1 keeps the meaning it had. Its comparison against the M1b reference differed only in classes the rule already
admits — syspage map entries that move because the startup binary is larger again, a figure the normaliser masks,
and the same unexplained process-thread difference the original B1 recorded. The reference this time was the black
box of the curated M1b capture rather than the live serial span the original B1 cut; the two were diffed and found
byte-identical before use, so this was black box against black box.

**The watcher run met its diagnostic rule.** Under the rebuilt startup, on the control arm, window 2's base canary
verified at both checks; its watches saw no changed word, no heal and no writer active while QNX ran; every page
bitmap they produce — bad at the end, changed at any point, healed at any point — was empty in every bucket and for
every watch label; the window-1 canary was clean; and the large timed hold over sysram filled and verified. Both
cache-clean console lines were present and in position, the first time the real binary has emitted them — before
today they existed only in fixtures. At that point in the ladder the reading was provisional.

**B2, the rung that claims the second memory window, passed on the rebuilt image, and B2 is MET for it.** Every
canary check was ok at both points, the window was reflected in the host's address-space view as registered,
neither a canary nor the GPU range appeared in sysram, the window-2 allocation filled and verified, and no failure
state was recorded. That makes the reading X-f final. **The original 2026-09-14 B2 record is unchanged and stays
NOT MET, on data,** for the old startup; it is never regenerated, and this is a line beside it for the rebuilt
image.

**2026-09-17: a third observation was made, and the interpretive sentence is released.** One keyed, bounded
confirmatory run of the same rung (D86) ran on a fresh boot and read clean — every canary check ok at both
points, MET, the configuration gate passed, the black box consistent — which is class X-f-c and discharges
D83. The owner then released D77, so the sentence pre-registered before any of these runs ran is now stated,
verbatim as pre-registered: **The window-2 corruption seen in four runs did not appear in two runs on a startup
that cleans those ranges by virtual address before the fill. The reading is a CPU cache residue removed before
the fill (HYPOTHESIS: the mechanism and which cache are not shown). B2 is met on the rebuilt image; the original
B2 record stands as recorded.** The third run is reported beside that sentence rather than inside it —
pre-registered wording that is rewritten once the result is known stops being pre-registered — so, stated
separately: a third, keyed confirmatory run of the same rung read clean as well, which adds confidence and
changes nothing about what is not shown. The figures from all of it stay private and go to the 4.6(i)
consultation.

What this does not show, none of it changed by the pass: which cache held the residue, since the clean reaches
cluster 1's L3, cores 1-3's caches and the boot cluster's at once; that the VA operation rather than the interval
it takes removed it, since the whole-window clean is of the order of seconds and a delayed cluster power-down
inside that interval is the competing account; DMA quiescence after kexec, since a cache clean removes a CPU-cache
writer and says nothing about DMA, firmware or coprocessor writers outside the canaries' and the hold's coverage;
window 1's library writes and the black box, both still unmaintained in revision 4; and repeatability beyond what
this ladder observed. No Linux guest has run on the board, and there is no timing, isolation or containment claim.

Two process incidents, recorded because they are process rather than board findings: the watcher run's first
attempt refused at the pre-registration check because its rule-file variable was unset in the session environment
— before any board contact, with no kexec issued and the budget untouched, and the re-run matched the stage the
refused attempt had already appended to the append-only ledger, so nothing was recorded twice; and B1's capture was
started far larger than that rung needed and had to be stopped by hand to free the exclusive serial port for the
next rung, so captures are now sized per rung.

**2026-09-17: B3 met — the first Linux guest on the board.** D83 being discharged, the ladder resumed. The
rung that boots the guest ran and passed: the same configuration, unchanged from the emulated rehearsal,
reached a shell under native qvm and answered the host's probe (pass item 2). All three canaries verified
before and after, on the first rung to run a guest under the revision-4 startup; the guest's kernel, initrd
and configuration were unchanged at the end; the device-tree checks passed; the black box stayed consistent
with the serial capture; the bootloader slot was unchanged before and after; and the image reset itself so
Linux came back on its own.

What B3 does not show, stated because the design requires it to travel with the result: **not** that the
guest's memory came from the second window. No host-side view of the physical addresses behind the guest's
RAM was found, so that reading is unknown rather than affirmative. B3 is also a boot rung, not a duration
one — it says nothing about how long the arrangement holds.

What remains: **B4**, the ten-minute run, which is the rung that speaks to duration, and which has not run.
~~**B5 does not run at all**: under OD1 the guest set is Linux only, so the two-guest rung's pass item is not
applicable.~~ **2026-09-17, later (OD9): the guest set was reopened to QNX plus Linux, so B5 is owed after all.**
**2026-09-17, later still: B5 ran and passed — see this file's 2026-09-17 B5 entry.**

**2026-09-17, later: B4 met, and S1-F was recorded met — a line OD9 withdrew the same day
(below), when the guest set was reopened to QNX plus Linux, so pass item 3 applies again and B5 is
owed. B4's own result stands.** **2026-09-17, later still: B5 ran and passed, so item 3 is met and S1-F is met
(QNX plus Linux), on the third wording rather than the first.** The ten-minute rung ran the same session and passed. The
guest held for ten minutes; the hypervisor was alive at every one of the ten heartbeats; all three canaries
verified after the hold and again after teardown; the guest's kernel, initrd and configuration were
unchanged at the end; the bootloader slot was unchanged; and the board returned unaided. It is the first
rung to reach every tier of the ladder.

What B4 does not show, and this matters more than the pass: **nothing under load.** The design says it
outright — the guest is idle apart from the heartbeat — so this is not a load test, a stress test or
a soak test. Ten minutes is the longest evidence this project holds and it is still minutes, not hours or
days. It again does not show that the guest's memory came from the second window. No timing, isolation or
containment claim follows from it.

With items 1, 2, 4 and 5 held and item 3 not applicable, ~~**S1-F is met (Linux only; item 3 not applicable,
freeze item 2 = Linux only)** — the design's first branch, because the guest set was settled before this
record closed, not the provisional wording. Freeze gate items 1 and 6 are satisfied.~~

**2026-09-17, later (OD9): that met line is withdrawn, and S1-F is NOT met.** **(Superseded the same day,
below: B5 ran and passed, so S1-F is met — QNX plus Linux.)** The owner reopened freeze
item 2 and reversed it to QNX plus Linux, so pass item 3 applies again and the two-guest rung (B5) is
owed. The line was correctly written when it was written — the design's first branch requires item 2
settled before B4's record closed, and OD1 did settle it then — but its premise no longer holds.
Items 1, 2, 4 and 5 stand exactly as recorded; ~~item 3 is open; freeze gate item 6 still stands and
item 1 does not.~~ ~~The freeze still needs
the guest disk regeneration;~~ **2026-09-17, later: the regeneration ran (OD7, the 2026-09-17 "OD7 executed"
entry), so item 8 is discharged too, and what the freeze still needs is B5.** **2026-09-17, later still: B5
ran and passed, so item 3 is met, S1-F is met (QNX plus Linux) — s1-design §5.2's third wording — freeze
gate item 1 is satisfied again, and item 6 still stands, as the struck sentence said. No S1-F rung remains.** The attended instrument round ran and passed on
2026-09-17, discharging its gate item. The licence consultation gates publication, not the campaign.
The records are private and git-ignored, and no figure is published here.
[s1-design.md](../results/orin-native-port/20260909T1100Z/s1-design.md) §16;
[the plan's S1-F block](orin-native-port-plan.md#the-revised-ladder).

## 2026-09-16 — M4's r0 image rebuilt under the frozen instruments, and the guest-disk rebuild deliberately not done

> **2026-09-17: the guest-disk rebuild was subsequently done** — the deferral's stated reason, a pre-registration
> that had not yet run, expired when revision 4's ladder ran on 2026-09-16. See the 2026-09-17 "OD7 executed" entry.
> Nothing below is withdrawn: the cost analysis recorded here is what made the later decision quick to take.

Two freeze-gate items were taken up while the board was unattended. One is now done on the PC; the other
was stopped before it started, and the reason is the more useful of the two results.

**r0 rebuilt (freeze-gate item 9).** M4's two functional rungs passed under different instrument versions:
r1 under the current one, r0 under a parser that is in no commit, with an image predating the frozen
counter and carrying four of the six fixtures the frozen set now defines. Its as-run parameters had also
been lost to a generator check that overwrote them. The image is now rebuilt against the frozen
instruments, in a scratch worktree so the generator could not overwrite the as-run r1 image beside it, with
every generator gate passing and the divergence from the as-run r0 recorded privately. What this
discharges is the provenance break. What it does not discharge is anything functional: the frozen counter
has never run on the board, and the old capture cannot stand in, because the rebuilt image expects records
the board never printed. One attended board round remains, and the owner has already settled what it
must show.

**The guest disk was not rebuilt, on purpose (freeze-gate item 8).** The shipped guest disk carries a
diagnostic variant of its start-up script that no commit generates, so the image v1 would freeze is not
reproducible from sources — which is why regenerating it was approved. Preparing the work showed the cost
is larger than the estimate that approval rested on: the two pins are hard-coded across ten committed
files, three committed board configurations carry the matching stanza as live configuration, a generator
assertion counts those entries, and the host image has the same contamination as the guest. The decisive
objection is narrower and stronger. S1-F's revision 4 is pre-registered and has not run: its reading rule,
its reference and its image hashes are all registered against the current state, and moving those pins
would leave that rung unable to be rebuilt against the state it was registered under. So the artefacts
were preserved outside the repository, the analysis was written down, and the rebuild was left for after
the paused ladder runs. The one question it answered for free: regenerating from committed sources
necessarily drops the extra shared-memory entry the built images carry, because the staged snippets are
already clean and the build copies them over.

What this shows: two freeze-gate items advanced without the board, one by doing the work and one by
establishing that doing it now would damage a pre-registration. What it does not show: that either item is
closed. Item 9 needs its board round; item 8 needs the owner's decision re-taken against the real cost, and
should follow the revision-4 ladder rather than precede it. **2026-09-17: both happened, in that order.**
Item 9's attended board round ran and passed; the revision-4 ladder ran on 2026-09-16; the owner then re-took
item 8's decision against the cost recorded here, and the regeneration ran. The records are private and git-ignored, and no
figure is published here.
[orin-native-port-plan.md](orin-native-port-plan.md#freeze-gate) carries both items' state.

## 2026-09-16 — S1-F revision 4 built, reviewed and pre-registered on the PC; nothing has run on the board

Revision 4's startup change is implemented, reviewed and committed
([731c936](https://github.com/ChHaEoN/qnx-linux-dual-vm-proxy/commit/731c936)). Under the S1 option only, the T234
board startup now cleans by virtual address, before writing them, the ranges that option adds: the second window as a
whole and the top-of-window-1 canary's range. Two console lines record that each clean ran, and the parser requires
them on the new pin. With the option off the binary behaves as before, so the B1 rung keeps its meaning. The harness
gained the watcher arm the ladder needs, a one-data-run-per-rung rule, and the two-part gate that keeps the UEFI-entry
arm deferred. Three reviews read the change — cache-maintenance correctness, power of the reading, and feasibility
against the harness — and every finding they raised was applied; the largest was that nothing had stopped a rung being
rerun until it read well, which now refuses unless the run produced no reading about the canary at all.

The startup was rebuilt twice to the same hash before its pin moved, the symbol gates were re-run, and the board images
were regenerated on the new pin, with the drift limited to the startup, image and script hashes; every bound and the
emulated profile were untouched. Before any board step, the reading rule and the reference it compares against were
registered once in the private pre-registration ledger, bound to the commit, with the four earlier runs' captures
hashed, so the rule cannot be changed after a result.

What it shows: a remedy the architecture prescribes for a hand-over made this way, implemented, reviewed, and its
reading settled in advance of the runs that judge it. What it does not show: that the cache-residue reading is right. **Nothing of
revision 4 has run on the board**, no Linux guest has run on the board, and B2 stays **NOT MET, on data**. The
confirming runs — B1, a watcher run, then B2 — need the owner at the plug, and even a clean result would not show which
cache held the residue, nor that the clean rather than the time it takes removed it, nor DMA quiescence after kexec.
The records stay private and git-ignored, and no figure is published here.
[s1-design.md](../results/orin-native-port/20260909T1100Z/s1-design.md) §16;
[the plan's S1-F block](orin-native-port-plan.md#the-revised-ladder).

## 2026-09-15 — S1-F writer diagnosis: revision 3 closes with a CPU cache-residue hypothesis leading, and revision 4 opens with a startup cache clean (designed, not run)

The J6c watcher run, on the kexec control arm, stopped on F39 again (a small static write at c3). Its watches showed stable
re-reads at c2 and no writer active while QNX ran. The owner then chose a UEFI-entry arm (J7a), which was designed
([s1-design.md](../results/orin-native-port/20260909T1100Z/s1-design.md) §15.6.1, §15.13). Before any J7a board step, a
desk analysis of the four kexec runs' private records made a CPU cache-maintenance gap at the hand-over the leading
hypothesis (HYPOTHESIS, untested; §15.14). In that reading, the corrupted data comes in whole cache lines and looks like
the previous kernel's own data. Startup fills the canaries with the MMU off, and its only cache maintenance is a
set/way clean, which reaches only the boot CPU's own caches. A cache line of the same address that Linux left elsewhere
can later be written back over the pattern. Under that hypothesis both of J7a's pre-registered consequences would route
to the wrong next step, so the owner deferred J7a's board steps and suspended those consequence clauses, with a two-part
lift (D54). A Linux-side arm that takes every secondary CPU offline before the jump (J6o) was designed and then shelved
(D65), because it added no cache maintenance the controls lacked. Revision 3 closed as class U, and B2 stays not met on
data.

Revision 4 (s1-design §16, accepted by the owner with every recommendation) is a startup change. Under the S1 option
only, the T234 startup cleans by virtual address (`dc civac`, stride from `CTR_EL0`), before writing them, the ranges
the option adds: the second window as a whole and the top-of-window-1 canary's range. That is the maintenance the
architecture prescribes for a hand-over made this way. Two new console lines record that each clean ran. With the
option off, the binary behaves as before, so B1 keeps its meaning. B1, a watcher run and B2 then rerun on the rebuilt
images, in that order, with the owner present. The rule that reads the result was fixed before any run, including what
a clean, a partial and an unchanged canary mean and how a provisional reading is withdrawn.

What it shows: a design and a pre-registered reading, reviewed three times (cache maintenance, power of the reading,
feasibility against the harness), with the owner's decisions recorded. The exposure register gains a row: the startup
library's own MMU-off writes in window 1 were made without the same maintenance in every earlier kexec rung.

What it does not show: that the cache-residue hypothesis is right. Revision 4's startup is built on the PC and pinned; the board images are regenerated on the new pin, and nothing of
revision 4 has run on the board. Even a
clean rerun would not show which CPU cache held the residue, or that the clean removed it rather than the time it took,
and it would not show DMA quiescence after kexec. An unchanged canary would weaken the hypothesis only as far as the
clean reached every cache, which no QNX-side read shows. Window 1's library writes and the black box stay unmaintained
in revision 4. No Linux guest has run on the board, and there is no timing, isolation or containment claim. The records
are private and git-ignored, and no figure is published here. The plan's
[S1-F block](orin-native-port-plan.md#the-revised-ladder) carries the status.

## 2026-09-14 — S1-F on the board: B0 and B1 met, B2 not met on data, and the writer diagnosis excludes the removable DMA masters (J1-J4)

S1-F's first board session ran with the owner at the board. B0 and B1 met. B2, the first rung to use the second RAM
window, was **not met, on data**, at the window's lowest canary, so S1-F stopped and B3-B5 did not run. The owner
chose to find the writer first (s1-design D8 option 1). The design's revision 3 added diagnostic J rungs, with the rule
that classifies B2 registered before any of them ran
([s1-design.md](../results/orin-native-port/20260909T1100Z/s1-design.md) §14.12, §15). Four ran the same day, all on
B2's unchanged image.

- **B0, pre-flight and staging,** met after two harness corrections, neither a board finding. The `/proc/iomem` gate
  had failed on the running L4T kernel's own image, which KASLR had placed inside the candidate window; it now excludes
  only that exact kernel-image entry. The kexec landing check needs dynamic debug, which the board's kernel lacks, so
  it is recorded as skipped. The shim's own landing check, which resets the board before any QNX code runs, is the
  guard, together with the parser's entry-PC rule.
- **B1, the option-off startup,** met: every expected token, no `-b` line, and a clean return to L4T. Against M1b's
  R2 capture, nothing points at the option-off startup changing QNX's behaviour. A `pidin` thread total differs and
  is unexplained. B1's output also exposed a harness privacy-scan defect that could keep a copy raw; it was corrected,
  and the earlier copies were rescanned by hand.
- **B2, the host with window 2,** not met, on data. Startup added window 2, kept the GPU range out and filled the three
  canaries before procnto. procnto's address-space view showed both windows in sysram and neither a canary nor the GPU
  range. c1 (top of window 1) and c3 (top of window 2) verified at both checks, and an allocation in window 2 filled
  and verified. c2, at the very base of window 2, was bad at both checks, with a different count
  at each check. By the design's rule that is kill condition 1 for the candidate window. procnto's allocator is not
  the writer (VERIFIED: the canary is outside sysram).
- **J1, a census on L4T with no kexec,** met. It resolved the four removable DMA-capable devices: the wireless function
  that carries the harness's ssh, the xHCI, the Ethernet function and the NVMe drive. None holds a mounted filesystem,
  swap or the harness's directories. Markers from a shell and from a transient systemd timer both reached COM3, the
  page-flag snapshot worked, and a runtime shutdown trace printed per-device lines on a reboot.
- **J2, the matched control,** reproduced c2 bad at both checks. A detached sequence on the board issued the kexec
  after the same timed slots as the removal arm, with nothing removed, so the two arms differ only in the removal. J2 also found c3,
  clean in B2, bad at both checks, while c1 verified. That is F39, an immediate stop. The owner waived it for J3 and J4
  only (D34), and under the waiver the design's quiesce-shortfall class cannot hold.
- **J3, the removal rehearsed on L4T with no kexec,** met after one gate was re-judged. Every removal step ran, Bus
  Master read zero on every endpoint and root port, the fallback timer rebooted a board with no network without a
  power cut, and every removed device came back on the next boot. The harness first printed NOT MET for the xHCI: its
  return read omitted the xHCI path, so the rebind check had nothing to match, while the same read and a direct one
  showed the xHCI bound. On the owner's decision J3 was re-judged from its records, the original line kept; the
  harness read was corrected.
- **J4, the removal arm,** F36. With all four devices removed, and Bus Master zero on every endpoint and root port
  before the kexec, c2 was still bad at both checks; c1 and c3 verified. The removable DMA masters are excluded as
  c2's writer, as this sequence quiesced them.

Across B2, J2 and J4 (record-only observations): c2's mismatch started at the same place each time, and the second
check's count was lower than the first each time, so some words read back as the expected pattern again. A writer that
only overwrites cannot do that; one that restores earlier content, or reads that are not stable, can (HYPOTHESIS).
Linux's use of c2's pages differed by boot and by arm; the corruption did not. The class is U, unresolved (owner,
D31), and B2 stays not met on data. The owner put the exposure into the plan's freeze gate (item 3, D32): until DMA
quiescence after kexec is shown for the claimed windows or declared, no campaign record claims memory integrity. The
M0-M5 functional verdicts stand, because they rest on no memory-integrity claim.

What it shows: the S1 harness, the staging and the option-off startup work on the board. The base of the candidate
second window did not keep its canary after the quiesce and kexec in any of the three runs. The wireless, xHCI,
Ethernet and NVMe devices, removed this way, are not what writes it.

What it does not show: which device, firmware or code writes c2, or that it is a writer at all rather than unstable
reads. J4 gives no evidence on GPU residue, firmware or coprocessors, read instability, or a QNX-side cause. Whether
the SMMUs were in bypass after kexec, and whether Bus Master stayed clear through the kexec shutdown, rest on log lines
and upstream behaviour; no register was read after the shutdown began. The canaries sample three small ranges, so
nothing is shown about the rest of window 2 or of window 1, and the cause of J2's c3 hit is open. No Linux guest has
run on the board, and there is no timing, isolation or containment claim, and no repeatability beyond these runs.

Next is J6, a read-only watcher image (D27). A second build of the canary tool reports word classes, re-read and heal
counts and page bitmaps, never canary content, and a large timed hold watches sysram. Then comes the owner's decision
on a UEFI-entry arm (D30), which separates Linux residue from a writer anchored at window 2's base. The run records are
private and git-ignored, and no figure is published here. The plan's
[S1-F block](orin-native-port-plan.md#the-revised-ladder) carries the status.

## 2026-09-14 — S1-F under TCG: a stock Linux kernel boots as a qvm guest to a working shell (T1-T3)

S1-F's PC half ran, all under QEMU TCG (emulated) on the Windows PC; none of it ran on the board. T0 had built and
gated the pieces on the PC first ([s1-design.md](../results/orin-native-port/20260909T1100Z/s1-design.md) §14.6). The
guest is the board's stock L4T 5.15 kernel `Image`, with an initrd built from the board's own busybox. The host is a
TCG QHV host image, so qvm runs inside the emulation, as on the cloud leg.

- **T1, qvm's `dryrun`.** The first attempt wrote qvm's device tree, but qvm then exited with an error. It could not
  open the virtio-console `hostdev`, which named the pty slave (`Unable to open '/dev/ttyp3': Interrupted function
  call`). The gate passed it anyway, for two reasons: it recorded the exit code without judging it, and its error
  heuristic looked only for certain words. Two changes followed. The `hostdev` moved to the pty master, as M3 wired its
  console (the design's own fallback). Every dryrun gate now needs a zero exit and no qvm `[file:line]` diagnostic. The
  second attempt was clean. qvm reported `Exiting: dryrun complete`, and every gating device-tree row was present:
  memory, GICv3, timer, virtio-mmio, bootargs, initrd and PSCI. The host's memory-canary self-test also passed. The
  console reader would otherwise have opened the slave before qvm held the master, so the host script now starts it
  only after qvm is launched (s1-design §14.10).
- **T2, boot to a shell.** The kernel booted as a qvm guest on qvm's generated device tree, with its three vCPUs
  online. It ran our `/init` and reached busybox's shell on `hvc0`. The shell answered the host-injected probe. The
  console shows the echoed command with its arithmetic unevaluated, and on the next line the result that only the
  shell's arithmetic produces. That meets S1-F's pass item 1 under TCG only. The reader-order race the design had
  named did not occur in this TCG run.
- **T3, the hold path rehearsed.** The run showed ten host heartbeats with qvm alive, a host allocation verified after
  the hold, the end probe answered and a clean teardown. T3 rehearses the ten-minute script. It is not pass item 4.

What it shows, under TCG: qvm loads a stock arm64 Linux `Image` with a bare `load` line, and its gzip cpio initrd
with `initrd load`. Its generated
device tree carries no Tegra nodes, and 5.15-tegra boots on it. The secondary vCPUs start through PSCI, and console
input and output work over virtio-console. The design's risks R1-R10, R12-R14, R29 and R31 are answered for the
emulated leg only (s1-design §14.11).

What it does not show: nothing ran on the board, and a TCG pass does not predict a native pass. The board's PSCI, the
A78AE system registers a guest may touch, the second RAM window, the canaries and physical CPU pinning are all
untested. Whether the console reader's open waits for qvm's master is not observable, so the reader-order race stays
open on the board. It gives no timing of any kind, no isolation or containment claim, and nothing about a GPU. Next are the
board rungs, with the owner present:
- B0: pre-flight and staging;
- B1: the startup regression;
- B2: window 2 and the canaries;
- B3: the native boot, item 2;
- B4: the ten-minute run, item 4;
- B5: only if v1 keeps the QNX guest, item 3.

Item 5's stamps come with every run. The run records are private and git-ignored, and no figure is published here.
The plan's [S1-F block](orin-native-port-plan.md#the-revised-ladder) carries the status.

## 2026-09-13 — S1-F design written, and the owner takes every decision as recommended

The S1-F design, [s1-design.md](../results/orin-native-port/20260909T1100Z/s1-design.md) (revision 2), specifies how a
Linux guest without a GPU is shown under native qvm. The guest is the board's stock L4T R36.4.7 kernel `Image`, with an
initrd built from the busybox and libraries in the board's own initrd. It runs on the TCG QHV host first, then natively,
with one configuration byte for byte. The host is entered by kexec. A new startup option, off by default, adds the
checklist 11c window as a second `add_ram`. It keeps a provisional GPU range out of every `add_ram`, and takes three
fixed canary ranges out of the allocator, filling them in startup. A host tool injects shell probes whose answer
differs from their echo, since COM3 is receive-only. The ladder is T0-T3 on the PC, then B0-B5 on the board in two
attended sessions. Nothing has been built or run.

Three review lenses raised 30 findings, and all were applied. The blocker was that `avoid_ram` would not have kept the
canary ranges from procnto, because only `alloc_ram` removes a range from the RAM list the kernel receives.

The owner took all nineteen decisions as recommended:
- Linux only now; the two-guest rung runs only if v1 keeps the QNX guest. **2026-09-17 (OD9): v1 keeps it; the rung is owed.** **2026-09-17, later: it ran and passed.**
- D10 tightens plan item 4, so the guest's end probe is required, not only a live qvm.
- D12: the dumped FDT is private evaluation output.
- D17: any QNX support request goes through the supervising professor first.
- No download up front.

Next: copy the board's `Image` and `initrd` to the PC (D3), then T0. Unknowns T1 must answer first: whether qvm accepts
the EFI-stub `Image` with a bare `load`, and what device tree it generates.

## 2026-09-13 — Owner decision: Phases 2 and 3 are closed as architecture history

The owner closed two phases in chat. Phase 2 (cloud twin IPC and latency) is closed as architecture A1 history, and
Phase 3 (the hardware twin port on the Orin plain leg) as A2 history, so the README roadmap marks both done. Closed does
not mean their original targets were met. The cloud leg's reliable runs never reached the 100k-iteration target, and
KVM-accelerated boot on the Orin never worked; the Orin IPC run also used a rebuilt IFS. Their records are kept as
architecture-version history and not chased, as the 2026-09-11 freeze decision set out. Neither phase will be redone.
The v1 campaign's TCG twin legs and IPC runs are campaign work on reference architecture v1, not a reopening of Phase 2
or 3. Two items stay open, and neither is tracked under those phases any more. The `qvm`/TCG virtio-queue stall is
still not root-caused, and the IPC sample size is set once, at the v1 freeze. The GICv3/NISV KVM defect is a separate
filing track, outside reference architecture v1. The README roadmap (branch `readme/phase4-qhv-leg`, draft PR #1) now
shows Phase 3b's rungs: M0 to M5-F are done, and S1-F, the v1 freeze and the single measurement campaign are ahead.
CLAUDE.md's Phase status carries matching notes. Nothing was run for this entry. The freeze decision is in
[orin-native-port-plan.md](orin-native-port-plan.md#architecture-versions-and-the-measurement-freeze-decided-2026-09-11).

## 2026-09-13 — Checklist 11c: the quiesce frees no RAM window (S1-F prerequisite)

Checklist 11c ran on a freshly booted L4T with the owner present, as the first S1-F prerequisite. The `rmmod` quiesce was
clean again, with no Oops and no SMMU or EMEM line. Reading `/proc/iomem` before and after the quiesce on the same boot
showed that the quiesce frees no RAM window: every System RAM and reserved line stayed the same, and only the GPU and
display drivers' MMIO claims went away. The map is fixed at boot. M3's earlier diff had compared two different boots, so
what it showed was KASLR. Comparing several boots found one System RAM range that held no reservation on any of them;
it is the candidate second window. K5 is still a HYPOTHESIS: no firmware or BPMP user of that range has been ruled out.
Booting the host image with the range as a second `add_ram` is still owed, and the S1-F design is in progress. No
figure is published here; the record is in a git-ignored `s1/` run directory, and the plan's
[checklist 11c](orin-native-port-plan.md) carries the details.

## 2026-09-13 — M5-F: a UEFI cold boot reaches startup and procnto, and the M path ends

M5's functional rung passed on the Orin Nano in one attended session, with the owner at the plug from P1 to C. It ran
m5-design's option A. Our own EFI loader, `M5LOAD.EFI`, carries the unchanged, pinned M1b image. It was launched from
the firmware's built-in UEFI Shell on a cold boot, so no Linux and no kexec ran between the cold power-on and the
loader, and the firmware never loaded a QNX PE. The session staged that one file in the root of the SD card's ESP,
after backing up and hashing `extlinux.conf` and `BOOTAA64.efi`. A control cold boot with no key (P2) then showed
that L4T still autobooted with the TX wire on J14 pin 3. The record wording is "M5-F met (T3 reached)".

What the board showed:
- **T1, in P3 and again in R1:** the loader's `check` mode ran from the Shell and printed `M5L CHECK PASS`, with no
  refusal and the TCU chosen as its console after boot services exit. The Shell prompt came back.
- **T2, in R1 (the rung itself):** after `go`, the loader exited boot services and jumped. Then the shim printed
  `T234-SHIM EL=2`, with the load address and device-tree magic the design expects, then `NORMALISED` and `JUMP`, and
  startup printed `t234: WDT0 CR=`. The tokens came in order, and no negative token appeared before the next firmware
  banner.
- **T3, recorded, not required:** the VHE line, cpu 0 at EL2 with E2H and TGE set, the EL2 virtual timer wired,
  `procnto up`, a stock `pidin info` with `Release:8.0.0` and a Cortex-A78ae line, and
  `SMPCHECK RESULT PASS-DEGRADED cpus=1/6 secs=60 reasons=none`. The image then reset itself. The reset reason read
  `MAINSWRST`, the pstore black box carried the run from the shim line to the reset line, and L4T came back on a new
  boot.
- **The §5.2 state checks:** between each pair of snapshots, the only UEFI variable that changed was the MTC counter,
  which the control interval, from the baseline through P2, also changed. No variable was added or removed, and
  `efibootmgr -v` matched the baseline apart from `BootCurrent`. After R1 the ESP was the baseline plus exactly the
  staged file, with its staged hash. L4T came back with its bootloader slot, `extlinux.conf`, `BOOTAA64.efi` and
  firmware version as before.
- **Afterwards:** the file was removed from the ESP (D10), and the ESP listing again matches the baseline. The TX wire
  is off pin 3, so the board is back on the M0-M4 wiring.

Deviations, all recorded:
- **P1 item 4:** the terminal loopback test was not performed. The owner decided this with the TX wire already
  fitted. The terminal's self-test ran instead, and P2 was the control for a stray byte when COM3 opens.
- **P3's first attempt:** it missed the ESC window, because the keys went to another window. L4T was let boot fully,
  and P3 was repeated.
- **P3's second attempt:**
  - DC power was removed and restored before L4T's kernel reported its power-down, which made an unclean shutdown.
  - More than one ESC was sent where §6.5 asks for one.
  - The Shell, entered through the Boot Manager, was reached after the 120 s operator bound. No watchdog reset
    followed, which is a datum for risk R10; `PcdBootWatchdogTime` itself stays unread.
- **In R1** the Shell was reached within the bound, though more than one ESC was sent again. No key was armed or sent
  after `go`.
- **The PC tools:**
  - The terminal's key log had recorded nothing, ever. It was fixed in 7c2e87d before P3, so P2's no-key verdict rests
    on the COM3 log.
  - Three watch-and-judge helpers had defects. Two showed up in live use in P3 and were fixed before R1. The
    poweroff watcher took the Setup menu's silence for a finished shutdown, after the power had already been cut. The
    reset watcher's pattern rejected a stray trailing character, so it never handed over, and the L4T watch was
    started by hand instead, retroactively over the capture. The third, an awk pattern in the T2/T3 judge that could
    not run, was found in replay before R1. None changed a gate verdict. They are session tools and are not
    committed.

What this does not show (m5-design §10):
- No timing, and no comparison with kexec entry. The medians comparison waits for the campaign.
- That firmware entry leaves cleaner clock, CPU-frequency, GIC, timer or DMA state than kexec does.
- Repeatability: there was one `go`, on one board, one firmware (r36.4.4) and one image.
- An unattended entry path: an operator opened the Shell.
- A proof that no menu writes a variable: the check covers only the paths this session took.
- Anything about option B, `mkifsf_uefi` or the library's `efi_entry_point`, which never ran.
- Anything about DRIVE OS, QNX OS for Safety or a supported boot.

**The M path has ended.** The owner confirmed on 2026-09-11 that it ends at M5-F's functional pass, so README PR #1
can now merge. Merging it is the owner's call. Under the freeze decision this is a functional result, not a
measurement. The session's figures stay unpublished until the 4.6(i) consultation: the run note on the local
branch `m3-results-unpublished`, the logs in the session's git-ignored record. Next: S1-F, a Linux guest without a GPU under native qvm, with the qvm `dryrun` gate first. Details
are in
[m5-design.md](../results/orin-native-port/20260909T1100Z/m5-design.md) §14, "Board session (2026-09-13)", and in
[orin-native-port-plan.md](orin-native-port-plan.md#architecture-versions-and-the-measurement-freeze-decided-2026-09-11).

## 2026-09-11 — M4-F: the trace instrument works on the board (r0 and r1), with a partial cross-check

Both functional rungs of M4 passed on the Orin Nano, though under different instrument versions. r0 ran the trace
tools under the EL2 host without qvm. Its own harness verdict was a fail, caused by a parser defect (I24) rather than
the board; its pass comes from an offline re-parse with the fixed parser, and re-validating r0 under the instruments
the freeze will gate is now a freeze-gate item. r1 ran
M3's full run with a trace window around the IPC pair. Its first attempt stopped at the memory gate before the trace
was armed. The sizing rules had costed the linear window, which r0's rates selected, as a 512-buffer ring. That was
an implementation defect, I26: tracelogger's own usage message gives a linear capture's defaults. The fix changed
only that gate value, and the rerun passed every criterion of m4-design §2.2.

What the board showed:
- qvm's Class-10 IDs 0, 1 and 7 were emitted and paired, with one vCPU thread, one clock offset, no order violation
  and no time mismatch.
- `trcctl -x` stopped the linear capture, and every CPU's tail reached the file, on this one run.
- Both listings crossed the TCU intact.
- The image reset itself back to L4T.

An adversarial review of the pass (16 read-only agents) found no blocker, but it narrowed what the pass shows:
- **A partial cross-check:** the 1 MiB verbatim block was capped, so the PC's pair-for-pair check covered only the
  early part of the window, and the statistics cross-check did not run.
- **Ungated flush evidence:** the evidence that every CPU's tail was flushed sits in fields no gate reads.
- **Weaker gates:** several parser gates are weaker than the design's wording. They must be fixed before the
  campaign's timed runs rely on them.

Every GUEST_EXIT on the board carried a non-zero status whose low bits equal the ESR exception class, as under TCG,
so r1's E3=none stands. The review also found that the harness's COM3 redaction misses the board hostname in its
local, git-ignored copies.

Under the freeze decision these are functional results, not measurements. The run records and figures are on the
local branch `m3-results-unpublished`. Next on the M path: M5-F. Details are in
[m4-design.md](../results/orin-native-port/20260909T1100Z/m4-design.md) §14.8-14.9.

## 2026-09-11 — Owner answers on the freeze decision's open points, and a stale-document cleanup

The owner answered four points the plan's freeze section had flagged, and asked for stale documents to be cleaned up.
(1) The M path ends at M5-F's functional pass, so README PR #1 can merge then. Whether a failed M5-F also ends it is
still open. (2) The M0, M1, M2 and M1b run records and curated captures stay public for now. M3 and later figures stay
on the local branch `m3-results-unpublished`. (3) Of the research track's gates, S1-F needs only the qvm `dryrun` gate
first; the GPU checks wait for the first GPU stage. (4) The A2 plain-leg boot diff between Windows and the Orin stays
history, and experiments are redone after the architecture is confirmed. (5) For the cleanup, this log's Phase 1-4
stubs and several lines in older entries that later work disproved are now struck through, each with a dated note.
No original text was removed, except one LAN address, now `<orin-ip>`. CLAUDE.md and the plan carry matching
corrections. Nothing was run for this entry. The decisions are recorded in
[orin-native-port-plan.md](orin-native-port-plan.md#architecture-versions-and-the-measurement-freeze-decided-2026-09-11).

## 2026-09-11 — Decision: finish the M path functionally, add a Linux guest, freeze reference architecture v1, then measure once

The owner chose option B for how the rest of Phase 3b and the twin are measured. The reason is how this project has
moved. Its design changes never adjusted one architecture; each replaced the whole of it. The cloud leg went from a
plain QNX guest under TCG to the QNX Hypervisor inside TCG, and Phase 3b now runs the QNX Hypervisor natively on the
Orin. Many cloud-leg measurements were hard to test while the hardware integration was unfinished. Some earlier
measurements now need redoing only because the architecture changed under them, and chasing each one again would
repeat that. The order is now:
1. Finish the M path as functional verification only. M4 becomes r0 and r1, which must show the trace instrument
   working on the board; its timed runs wait. M5 is a UEFI cold boot that reaches startup; its comparison of medians waits.
2. Then S1, from the GPU pass-through research track: a Linux guest without a GPU under native qvm.
3. Then freeze reference architecture v1, as a manifest of images, configuration and instruments.
4. Then run one measurement campaign on v1: the M3 and M4 numbers, the M5 comparison and the twin diff, with every
   record stamped with the architecture version.

Earlier measurements become architecture-version history: kept, labelled with the architecture they ran on, and not
chased. That covers the release-aligned QHV pair of 2026-09-09, which CLAUDE.md still listed as the next deliverable.
It also covers M3's figures, which stay on the local branch `m3-results-unpublished`; M3 itself stands as a
functional pass. S1 crosses the native-port plan's non-goal of no Linux guest, which is now struck through there. One
assumption awaits the owner's confirmation: the M path ends at M5's functional pass, which sets when README PR #1 can
merge. Nothing was run for this entry. The architecture timeline, the measurement inventory, the freeze gate, the v1
manifest and the campaign are in
[orin-native-port-plan.md](orin-native-port-plan.md#architecture-versions-and-the-measurement-freeze-decided-2026-09-11).

## 2026-09-11 — M4 dry run (7b): qvm's Class-10 trace events are real, and the plan's ring recipe was not

Before any board time, M4's trace recipe was rehearsed inside the Windows-TCG QHV host. A variant host image, built in its own
git-ignored directory, carried the byte-identical guest plus traceprinter and two small tools (`clkcmp`, `trcctl`); the canonical
images were only hashed. Four attempts passed. qvm emits the Class-10 GUEST_ENTER, GUEST_EXIT and CYCLES events at its default
settings. The target counted them, and the PC recounted them from the extracted trace, so K11's event IDs are no longer a
vendor claim for this host. Three parts of the plan's recipe did not survive:
- Plain traceprinter output splits each event's arguments across lines, so the planned grep keeps only headers.
- `-S` does not size a ring capture. The planned `-r -M -S 8M` kept only a short tail and lost the whole workload; `-k` sizes the ring.
- `%e` in traceprinter's format is a sequence index, not the event ID.

A stop through `TraceEvent(_NTO_TRACE_STOP)` does make a ring capture write its file. Host time equals guest time minus
`clockcycles_offset`, as QNX documents, once 64-bit time is rebuilt from the trace's CONTROL TIME events. None of this is a board
number or a dwell figure: under TCG every clock is emulated. The run record and its figures stay on the local branch
`m3-results-unpublished`. Design: [m4-dryrun-design.md](../results/orin-native-port/20260909T1100Z/m4-dryrun-design.md).

## 2026-09-10 — M3: the QNX Hypervisor boots the cloud-leg guest natively on the Orin Nano

Late the same day, native `qvm` ran at EL2 on four of the board's Cortex-A78AE cores. It booted the byte-identical cloud-leg
QNX guest, with its unmodified disk, to its banner on all five timed runs. The Phase-2 IPC pair completed its 15 iterations in
every run. That closes the plan's unknown #5: stage-2 translation, the virtual GIC and the guest timers work on real A78AE
for this guest. The shake-down found three things the design could not. First, the plan's diskless guest configuration would
never print the banner, because the guest's `uname` lives on the disk. Second, the image lacked `libz.so.2` and four more
libraries the cloud host carried. Third, unloading the GPU modules put the cpufreq governor back to schedutil, which also
showed that the frequency Linux last sets carries into QNX. The quiesce rehearsal hit the third Linux teardown oops of the day
(in `tcp_metrics_flush_all`, after hours of uptime); on a fresh boot the quiesce worked. The measured interval and IPC figures
are evaluation output. The repo is public, so they, the run record and the curated capture stay on the local branch
`m3-results-unpublished` until the 4.6(i) consultation. Design:
[m3-design.md](../results/orin-native-port/20260909T1100Z/m3-design.md).

## 2026-09-10 — M1b: QNX runs as the hypervisor host at EL2 (VHE) on all six cores of the Orin Nano

The same evening as M2, the host moved from EL1 to EL2. With `-Q enable,el2-host` the startup library turned on VHE
(`HCR_EL2` E2H and TGE) on every core. procnto and user space ran at EL2 with the kernel clock on INTID 28, the EL2
virtual timer's interrupt, which the Tegra234 device tree does not list. A board probe settled that interrupt before
procnto depended on it. On each core it armed the EL2 physical timer as a control (INTID 26 went pending), then the EL2
virtual timer (INTID 28 went pending, and cleared when masked), without ever taking an interrupt. Any other outcome
would have stopped the run by name with a warm reset. It said `wired` on all six cores, closing the plan's ranked
unknown #3, so M3 can use the VHE host. R0 re-ran M2's six-core image with the new startup and differed from M2 in
exactly the three intended lines. R1 (one core), R2 (six cores) and R2b (a repeat) met every criterion. R1 ended in
`SMPCHECK RESULT PASS-DEGRADED cpus=1/6`, the expected shape with one core, while R2 and R2b each ended in
`SMPCHECK RESULT PASS cpus=6/6`. All three ended in the image's own warm reset. The design found one thing beyond the verdict: CPU0
had no working fault handler once QNX stays at EL2. The shim's vectors print through registers the startup's C code
reuses, and they fall outside the identity map once the MMU is on, so startup now installs its own EL2 table from
`board_init`. The runs also showed that a `CPU_ON` issued from EL2 enters a secondary in exactly the state one issued
from EL1 did. Still open: the two cluster-1 cores run the busy loop at the same fixed 57 million iterations per
second at EL2 as at EL1, and nothing hypervisor-shaped (qvm, a guest, stage 2) has run, which is M3. Before R0, a
plain reboot of L4T after 5 h 27 min of uptime ended in a Linux Oops in its own shutdown path and a watchdog reset,
the second such event. Record: [m1b-runs.md](../results/orin-native-port/20260909T1100Z/m1b-runs.md); design:
[m1b-design.md](../results/orin-native-port/20260909T1100Z/m1b-design.md); capture:
[orin-native-m1b-el2-host.log](../logs/sample-boot/orin-native-m1b-el2-host.log).

## 2026-09-10 — M2: QNX 8.0.0 on all six cores of the Jetson Orin Nano

The same day M1 ran QNX on one core, M2 ran it on all six. Every secondary was started through PSCI `CPU_ON` and
entered at EL2, including the two cores of the second cluster. Each bound its own redistributor (frames 0-3, 6 and 7)
with the expected IPI routing, and a user-space check that pinned a 60 s busy process to every core passed
(`SMPCHECK RESULT PASS cpus=6/6`) in two runs of the identical image, plus a third that added a tracelogger capture
with events on all six. The ladder `-P1`, `-P2`, `-P4`, `-P5`, `-P6` passed rung by rung, and every run ended in the
image's own warm reset. The startup library already had the core geometry right; the work that mattered was failure
handling, because a design, three design reviews, a parallel implementation and three code reviews found several
plausible secondary-core faults that would have hung the board silently. The runs settled three questions: a
QNX-issued `CPU_ON` enters at EL2 although QNX calls it from EL1; the unpopulated redistributor frames 4 and 5 read
cleanly and hold the two absent cores' affinities, closing ranked unknown #10; and firmware leaves every secondary
in the same non-VHE EL2 state. Two things stay open: both second-cluster cores run a busy loop at one fixed rate,
roughly a tenth of the first cluster's, and the trace shows no interrupt storm to explain it; and none of this is
under `-Q enable` yet. Along the way Linux panicked once in its own kexec shutdown (`tcp_metrics_flush_all`), and the
watchdog reset that followed preserved pstore. Record:
[m2-runs.md](../results/orin-native-port/20260909T1100Z/m2-runs.md); design:
[m2-design.md](../results/orin-native-port/20260909T1100Z/m2-design.md); capture:
[orin-native-m2-six-cores.log](../logs/sample-boot/orin-native-m2-six-cores.log).

## 2026-09-10 — M1: the QNX kernel ran natively on the Jetson Orin Nano

The first native QNX image booted on the board, entered by kexec from L4T with no
QEMU underneath, and was watched live over the J14 debug header. The kernel
printed `T234 M1: procnto up` through the TCU console callout this port wrote. So
the question Phase 3b was opened to answer at its first milestone — does QNX run
on Tegra234 at all — is answered yes. Record:
[m1-first-procnto.md](../results/orin-native-port/20260909T1100Z/m1-first-procnto.md);
full capture:
[orin-native-m1-first-procnto.log](../logs/sample-boot/orin-native-m1-first-procnto.log).

What came up, each line in the capture: the MMU; the GIC-600 identified as
arch v3.0 with 960 SPIs; **the GIC re-initialised cleanly against the controller
Linux had left enabled** (`Add SPI entry 0 for vectors 32 -> 991, Ok`), which the
pre-flight review had judged the single most likely place to hang; the A78AE with
its full cache topology; the redistributor frame found by affinity; the IFS
unpacked; a complete system page with the 31.25 MHz timer, the console callouts,
the RAM range and the machine string; and the hand-off to procnto.

What did not: user space. Every program failed to start, on two buildfile errors
rather than kernel ones. errno 83, `ELIBACC`, because the image carried the
`/usr/lib/ldqnx-64.so.2` symlink but not the runtime linker it points at; and
errno 2, `ENOENT`, because `devc-pty` sat in `/sbin` outside `PATH=/proc/boot`.
With `shutdown` also unable to start, the image could not reset itself as
designed, and the board stayed in QNX until the power was pulled — the case the
serial console had been added for an hour earlier, and the reason nothing of the
run was lost.

Two things this closes beyond the headline. The shim's register bank came out
identical to the M0 run, so the hand-over is repeatable rather than a one-off. And
the library printed the boot CPU's redistributor SGI frame, `0x0f450000`, which
was the one missing input that had kept the EL2 virtual-timer probe unimplemented.

What it does not show: anything above the kernel — no resource manager, no shell,
no process list — and only one CPU at EL1. SMP and the hypervisor host at EL2 are
untouched, and no number exists.

**Getting the console working took its own detour, recorded in
[serial-console-wiring.md](../results/orin-native-port/20260909T1100Z/serial-console-wiring.md).**
I first recommended the 40-pin header because its wiring could be checked from
Linux; three UARTs transmitting at once put nothing on its pin 8, the kernel showed
`UART1_TX_PR2` as `MUX UNCLAIMED`, and the carrier specification plus a known-good
adapter left the unrouted pad as the only cause. J14 carries the real console, and
the first capture off it was UEFI's own `L4TLauncher: Attempting Direct Boot`,
proving the wiring with none of this port's code involved. The carrier spec also
settled the long-open pin question: J14 pin 4 is `UART2_TXD`.

**And user space came up the same morning.** With the runtime linker in the image
and `devc-pty` on `PATH`, the next run printed `T234 M1: user space up` from
`tcu-cat`, and a stock `pidin info` reported **QNX Release 8.0.0 on a Cortex-A78ae,
975 MB free of 992 MB, 3 processes and 14 threads** — the operating system itself
confirming the RAM range the board code states rather than discovers. M1 is met:
QNX, kernel and user space, runs natively on this board. Two script errors were
left, neither in QNX nor in the board code: an IFS script is not a shell, so
`pidin info | tcu-cat` passed the pipe to `pidin` as an argument; and `shutdown -b`
turned out, by `shutdown`'s own embedded usage, to mean "do not reboot", so the
image halted at `Shutdown Complete` instead of resetting and the board needed the
power pulled. Both are fixed — no pipes, `shutdown -S reboot` — and the capture is
[orin-native-m1-userspace.log](../logs/sample-boot/orin-native-m1-userspace.log).
Still one CPU at EL1: SMP, the hypervisor host and any number are ahead.

**A third run the same morning closed the loop with nobody at the board.** With no
pipes and `shutdown -S reboot`, `pidin` printed its full table, and the image then
warm-reset the board: firmware follows `pidin` directly on the console, and L4T
answered ssh again with a new `boot_id` about 80 s after the launch. The RAM black
box survived that reset. On the next boot pstore held 7,252 bytes, from the shim's
register bank through the last `pidin` row, and it was the more complete record: the
live console lost its tail at the reset, stopping inside the `devc-pty` row, most
likely because bytes not yet sent to the UART were discarded. Two limits. `tcu-cat`
writes the mailbox itself, so its banners are never in the black box and the
`resetting` banner reached neither channel; the reset is attributed to `shutdown` by
elimination, not by a captured line. And this recovers only runs that end in a reset;
a hang still needs the power pulled. Record:
[m1-first-procnto.md](../results/orin-native-port/20260909T1100Z/m1-first-procnto.md),
section Run 3; capture:
[orin-native-m1-reboot-blackbox.log](../logs/sample-boot/orin-native-m1-reboot-blackbox.log).

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

**2026-09-17 (OD7): that pair no longer exists on disk.** The host and guest were regenerated from clean sources; regeneration is not byte-reproducible, so the values are new (`faa4485e…c74971` and `d3b61572…247b7c`, in [results/qhv-images-SHA256SUMS.txt](../results/qhv-images-SHA256SUMS.txt)). The hashes above are kept because the series described here ran against them. The curated boot logs that name the old pair are left untouched for the same reason: they record what was booted.

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
was logged there) — **2026-09-19: still symptom-only. A matched control/test
pair ran there that day and the fix worked, but it took no trace either, so the
only data-backed NISV in the repo is still the single Orin ftrace**; the 2026-07-28 note claims the traced PC matched the
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

**M0 gate passed on the board, 2026-09-09 evening: kexec accepts the shim and
places it exactly where the arithmetic said.** The first time any Phase 3b code
touched the hardware, and deliberately the smallest possible step: the 8 KiB
probe-mode shim was staged into kernel memory with both kexec syscalls, the
result read back, and the image unloaded again. **No reboot** — the board stayed
up throughout. Both paths returned `rc=0` with `kexec_loaded=1`, so nothing
stands between a non-Linux payload and this kernel: no signature check, no PE
check, nothing beyond the header. Claim K2 is settled on its acceptance half,
which source reading alone could not settle. The more valuable half came from
the `kexec_load` path, which prints its segment map: **segment 0 at
`0x80080000`, size `0x2000`** — precisely the address the shim's landing check
expects, and the value the plan had carried as a hypothesis since it was
written. One correction fell out of the same output: the plan says the device
tree is placed top-down above the image, which is what the kernel does on the
`kexec_file_load` path, but `kexec-tools` on the `kexec_load` path placed it
bottom-up immediately after the image, at `0x80082000` — where the IFS will live
once there is one. With a real image the payload grows and the DTB moves past
it, so nothing collides, but the placement should be re-read from `kexec -d`
rather than assumed when the first shim+IFS image is built. Full record:
[results/orin-native-port/20260909T1100Z/m0-kexec-acceptance.md](../results/orin-native-port/20260909T1100Z/m0-kexec-acceptance.md).
**What this does not show:** the shim has still never executed. The exception
level at entry, whether the SPE drains the TCU mailbox once Linux is gone,
whether a ramoops write survives a reset, and whether the un-petted watchdog
returns the board all need the reboot this test deliberately avoided.

**M0 ran, 2026-09-09 23:38: the first native instruction on this hardware, and
four ranked unknowns closed in one boot.** The owner ran `kexec -s -l` followed
by `systemctl kexec`; Linux handed over, the shim printed its state bank into
the ramoops console zone, normalised the timers and HCR, and reset. The board
was back in about twenty seconds with its boot configuration untouched. The
whole record is 419 bytes recovered from `/sys/fs/pstore/console-ramoops-0`:
[m0-first-run.md](../results/orin-native-port/20260909T1100Z/m0-first-run.md).

What it settled, in the plan's own order of risk. **`EL=2`** — unknown #1, the
one that could have killed the kexec approach outright, since a payload entered
at EL1 can never host a hypervisor. NVIDIA's kernel fork behaves as upstream
source said it would. **`TCUDROPS=0`** — unknown #2: the SPE is still draining
the mailbox after Linux is gone, so the console mechanism this port depends on
survives the hand-off. Precisely, the SPE consumed the words; whether they
reached the physical wire is unobserved, because no adapter is attached yet.
**`PC=0x80080000`** — the placement arithmetic, carried as a hypothesis since
the plan was written and confirmed by `kexec -d` earlier the same day, is now
confirmed by the code actually running there. **The black box worked end to
end** — a non-Linux payload wrote the ramoops zone in a form the kernel accepts
and pstore surfaced it, which is what makes the USB-TTL adapter a convenience
rather than a prerequisite.

Two things came back better specified than they went in. `MMFR1=0x10212122`
puts the VH field at 1, so `-Q enable,el2-host` is feasible on this silicon
rather than merely expected from the part number. And `CNTHP_CTL_EL2=0x5` shows
the EL2 physical timer was not just armed at hand-off but had already fired —
the shim disarms the timers for exactly this reason, and this is the first
direct evidence that it needed to.

What did not happen: no QNX instruction ran. This was the shim alone in probe
mode. The board directory written the same day has never been packaged into an
image, M1 has not been attempted, and the `hang` mode that would test whether an
un-petted watchdog recovers the board was not run — this boot reset itself
deliberately through PSCI, which says nothing about that path.

**The same evening, the `hang` test: the watchdog does not recover the board,
and the black box does not survive a power cycle.** Two assumptions died in one
run. The shim was rebuilt in `hang` mode — print, then `wfi` forever with nothing
petting WDT0 — to test whether the watchdog systemd arms at two minutes brings
the board back unattended. It sat there for six and a half minutes and came back
only when the owner pulled the power. Standing at the board they reported the
green LED lit and the fan stopped, which is what a core parked in `wfi` looks
like from outside: powered, idle, nothing running, and distinct from a brown-out
where the LED would be dark. Nothing could have woken it — the shim enters with
`DAIF` masked and never unmasks. Most likely systemd hands the watchdog back on
its own shutdown path, which `systemctl kexec` is; that is a hypothesis and one
boot would settle it.

The second death followed from the recovery. After the cold power cycle
`/sys/fs/pstore` came back **completely empty**, including `dmesg-ramoops`
records from days earlier — DRAM losing its contents, not pstore declining to
surface them. So the black box is bounded rather than general: it carries the
payload's output through a PSCI reset or through an exception the shim's vectors
turn into one, and carries nothing at all through a hang.

Together those sharpen the rule for M1 onward beyond "every path must reach a
reset". A startup that fails into a wait loop is now the *worst* available
outcome — worse than one that crashes, because crashing prints and hanging costs
both the evidence and a trip to the board. Anything resembling a spin needs a
bounded deadline with a reset at the end of it. The remotely switchable mains
socket also stops being a convenience: it is the only thing that restores the
recovery path the watchdog was assumed to provide.
[m0-hang-watchdog.md](../results/orin-native-port/20260909T1100Z/m0-hang-watchdog.md)


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
unreachable — `ssh` to `<orin-ip>` timed out on port 22 — so it is
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

> **Answered 2026-09-19.** The fix travels as well as the defect did: on a fresh `a1.metal` the
> shipped startup reproduced this hang and a startup rebuilt with `-fno-auto-inc-dec` booted to the
> guest banner, one variable apart. See that day's entry. What is **not** answered: no trace was
> taken there, so this run stays symptom-only and hypothesis H-C remains open.

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
   framing being a hard wall.** `C:\Users\<user>\qnx800\target\qnx\usr\include\hyp_shm.h`
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
`C:\Users\<user>\qnx800\host\common\mkqnximage\qemu\runimage` (the
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
host io-sock stack, ~~which does **not** initialise on this qemu-virt build~~ **(2026-09-11: not a
property of the build. Per RQ-4 in [phase2-research-spike.md](phase2-research-spike.md), the launch line
presented no virtio-net or virtio-rng device; with them presented it comes up, as the 2026-07-28 Orin networking
entry above found for the plain image)**
(`network stack down` / `Address family not supported`) — worked around with a
no-network qvm config auto-started via a custom `post_start.custom` snippet;
driving the guest start over the TCG serial console interactively drops
characters, so the start was baked into the image instead. **Honest framing:**
TCG proves the QHV *software* architecture (qvm config, vdev instantiation, guest
isolation, EL2/VHE host) — not hardware timing/acceleration (needs metal/Orin).
Note this supersedes the earlier Track-A framing where the cloud leg ran a QNX
*Neutrino* guest under QEMU/**KVM** on c7g.large — that KVM-on-cloud assumption is
now falsified (see finding chain above); ~~KVM acceleration belongs on Orin (Phase 3).~~
**2026-09-11:** KVM boot of the QNX IFS later hung on the Orin and on `a1.metal` (the GICv3/NISV defect,
2026-07-28 and 2026-07-29). The hardware-timed route became the native port (ADR-003).

---

## 2026-06-10 — Phase 1 finding: first QNX aarch64 IFS built on the Windows host (missing `target.qemuvirt` package)

First real `mkqnximage --type=qemu --arch=aarch64le --build` on the local
Windows build host (SDP 8.0.4, install root `C:\Users\<user>\qnx800`) **failed**
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
— it says nothing about whether the IFS boots on Graviton ~~(still the open
Phase 1 question below)~~ **(2026-09-11: never answered on Graviton; Phase 1 closed on the Windows PC
under TCG, in the 2026-06-11 QHV milestone entry above)**. Secondary finding: `mkqnximage` emits a **split VMDK** —
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
**2026-09-11:** Track B was never built. The plan's architecture table records it as A0′.

---

## Phase 1 — Cyber-Analysis TARA ~~(TBD: gate review)~~

> **2026-09-11:** the gate review ran on 2026-06-11 (the Phase-1 gate entry above), against the as-built
> hypervisor boundary. It deferred the KVM, `br0` and Linux-guest rows this body assumes. The text below
> keeps its original assumptions.
>
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

## Phase 1 — FuSa-Analysis HARA ~~(TBD: gate review)~~

> **2026-09-11:** the gate review ran on 2026-06-11 (the Phase-1 gate entry above), against the as-built
> hypervisor boundary. It deferred the KVM, `br0` and Linux-guest rows this body assumes. The text below
> keeps its original assumptions.
>
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

## Phase 4 — ~~TBD:~~ cloud-vs-HW twin diff

> ~~_Stub. Filled in after the twin-diff measurement run lands. Expected
> contents: P50/P99/P99.9 latency delta, boot-time delta, jitter
> profile delta. Hypothesis going in: IPC-path latency tracks within
> a small constant; boot times diverge meaningfully due to host CPU
> and scheduler differences._~~
>
> **2026-09-11:** superseded. Twin diffs were recorded in [digital-twin-design.md](digital-twin-design.md) §5
> (2026-07-28) and as the release-aligned QHV pair (the 2026-09-09 entry above). Under the 2026-09-11 decision
> they are architecture-version history, and the twin diff runs once, in the v1 campaign
> ([plan freeze section](orin-native-port-plan.md#architecture-versions-and-the-measurement-freeze-decided-2026-09-11)).

---

## Phase 3 — ~~TBD:~~ hardware twin port to Jetson Orin Nano

> ~~_Stub. Filled in after the same `mkqnximage --type=qemu --arch=aarch64le`
> IFS has been booted on QEMU-on-Orin under L4T. Expected contents:
> (a) does the unmodified IFS boot? (b) JetPack 6 KVM availability;
> (c) RAM headroom on 8 GB; (d) any GICv3 / A78AE quirks._~~
>
> **2026-09-11:** superseded by the 2026-07-28 and 2026-07-29 entries above. The plain IFS boots under TCG.
> KVM is present, but the boot hangs on the GICv3/NISV defect. The bridged IPC ran, on a rebuilt IFS.
> Phase 3b later ran QNX natively (2026-09-09 onward).

---

## Phase 2 — ~~TBD:~~ cloud-twin IPC latency baseline

> ~~_Stub. Filled in after the C99 client/server has been run to 100k
> iterations. Expected contents: P50, P99, P99.9 of round-trip on
> Graviton + virtio-net + host bridge; time-base normalisation
> notes; warm-up tail behaviour._~~
>
> **2026-09-11:** superseded by the 2026-07-28 Phase 2 entries above (A1): QNX host to QNX guest over the
> qvm virtio-console, with no Graviton and no bridge. Those numbers are now architecture-version history.

---

## Phase 1 — ~~TBD:~~ cloud-twin bring-up

> ~~_Stub. Filled in after both VMs boot under KVM-on-Graviton. Expected
> contents: virtio-mmio vs virtio-pci default in mkqnximage SDP 8.0;
> whether x86_64-built aarch64 IFS runs under KVM-on-Graviton without
> modification; QNX boot time on Graviton._~~
>
> **2026-09-11:** superseded by the 2026-06-11 QHV milestone entry above: the QNX Hypervisor and one guest
> under TCG on the Windows PC. The dual-VM KVM topology was never built (A0 in the plan's architecture table).

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
study). ~~KVM acceleration on Graviton works with stock Ubuntu 22.04.~~
**2026-09-11:** falsified on 2026-06-11 for non-metal Graviton, which has no `/dev/kvm` (ADR-002). On
`a1.metal` KVM is present, but the QNX IFS hangs there on the GICv3/NISV defect (the 2026-07-29 entry).
The QNX Everywhere NCEULA covers personal/portfolio/demo use but
forbids redistributing QNX binaries — so the repo ships scripts and
logs only, never IFS images.

Full write-up: [bsp-selection.md](bsp-selection.md).
