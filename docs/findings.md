# Findings Log — append-only, newest at top

A running record of empirical findings, surprises, and decisions that
came out of actually running the toolchain. Phase 0 entries point to
their detailed write-ups; Phase 1+ entries will land here directly.

Format: one entry per finding, dated, one-paragraph max plus links.

**2026-09-27 — results withdrawn from this public copy.** On 2026-09-27 every
entry that reported a measured or functional result was withdrawn from this
public copy under NC QDL v7 clause 4.6(i), which bars making the results of any
performance or functional evaluation of the Software available to any third
party without BlackBerry's prior written approval. Entries that mixed results
with decisions, process or tooling keep only the latter, under neutral titles,
and name the records they drew on as held locally. The full log is kept
locally, and this file stays append-only from here on.

---


## 2026-09-23 (later) — the 2026-09-18 service's L4T client was never committed; recovered from the board

The 2026-09-18 service's record (`20260918T-kvm-gpu`, held locally) describes
`compute_client` — the L4T program that runs TensorRT on MNIST and sends the
claim — only in prose. Its source was not in the repo on any branch. It survived
on the board and is now committed as found:
[ipc-test/compute-client/](../ipc-test/compute-client/README.md).

- **What ties it to the run is timing, not proof.** Source 15:51:05, binary
  15:51:28, engine 15:52:00 on 2026-09-18, sha256 of each in the README.
- **How `mnist.engine` was built is not recorded**, and engines are not
  byte-reproducible, so that part of the 2026-09-18 service cannot be rebuilt to
  the same hash. Neither the binary nor the engine is committed.
- The lesson is the one the 2026-09-22 leak taught from the other side: what is
  not captured at the time is not recoverable later, only findable if lucky.

---


## 2026-09-23 — the first LLM interference run: harness notes

The first A6 interference arm with a real workload: L4T decodes SmolVLM-500M on
the GPU while the QNX guest runs beside it under KVM, and the probe times the
guest's TCP round trip. k = 12, n = 1000, arms `idle` / `llm` / `gpu` (`fma.cu`) /
`idle2`, Williams-balanced. The record, `20260923T-a6-orin-llm-interference`, is
held locally (NC QDL v7 4.6(i)).

- **Harness findings.** An ssh client that times out does not kill what it
  started on the board (three copies once ran together; now an `flock`); in its
  default REPL mode this build's `llama-cli` does not exit on SIGTERM (now TERM,
  3 s, KILL, and `-st` — see the correction below); and
  `set -o pipefail` breaks `m_thermal`'s `tegrastats | head -1`.
- **Correction, found on review later the same day.** The record's load logs are
  ~1.9 MB each, 22 MB in all, almost entirely `> ` lines. `llama-cli` was running
  as a chat REPL, not one-shot as the script's comment claimed: SIGTERM ended the
  turn, the REPL then read end-of-input and printed its prompt until the KILL. The
  comment was wrong. The script now passes `-st` (single-turn), with which SIGTERM
  makes it exit cleanly (verified on the board: 4 KB log, no prompt lines). The
  logs are left as captured.

---


## 2026-09-23 — LLM prep on L4T alone: board constraints and model licences

Prep on L4T alone, no QNX guest, to decide whether an `llm` interference arm was
worth a board session. The record, `20260923T-a6-orin-llm-prep`, is held locally.

- **Board constraints found.** `cudaMalloc` does not reclaim page cache (with
  3.7 GB cached the 4B cannot create a context; after `drop_caches` the same
  command runs); the 4B's default context wants a 1512 MiB KV cache; llama.cpp
  segfaulted on one OOM path.
- **Licences checked on the base model card**, not the GGUF repo's metadata:
  Qwen2.5-VL-3B was rejected because its base card has no licence field at all.
  Weights stay out of the repo; `fetch-models.sh` pins them by sha256.

---


## 2026-09-22 (later) — a sweep of the whole published history: two older identifiers are still in it, and the 2026-09-09 clean-up never ran

After the rewrite above, every text blob reachable from `origin/main` — all 280
commits — was scanned for the identifier classes this repo's conventions forbid.
**The tip is clean of all of them.** Two older ones survive in blobs no branch
points at: an EC2 instance id from a 2026-07-29 capture (24 commits), and the
board's address on the owner's LAN (97 commits). Both were redacted forward, in
2026-09-09 and 2026-09-13, and left where they were. The exact paths and commit
ranges are recorded locally rather than here, for the obvious reason.

- **This corrects the entry below.** It says this was the third time an AWS
  identifier had to come out of this history, counting 2026-09-09. That clean-up
  was decided (owner decision 3 of 2026-09-09) and handed to the owner to run,
  and **the evidence is that it never ran** — the id it was about is in the
  published history today. Today's rewrite is the only one this repo can show
  happened.
- **The decision is to leave both, and the reason is not cost alone.** The
  address is RFC 1918: not routable, and one of the most common home ranges
  there is. The instance id names an instance terminated on 2026-07-29, means
  nothing outside the account, and no account id accompanies it any more. Against
  that, the oldest affected commit is 2026-08-24, so a rewrite changes **254
  SHAs** and breaks **118 citations across 49 files** — and a number of those
  citations sit inside *captured evidence*, the `git-state.txt` files that record
  what the repo was at the moment of a capture. Editing captured evidence so it
  agrees with a rewritten history is a worse practice than the leak it would be
  fixing.
- **What that leaves.** The published history is not clean, and this entry says
  so rather than letting the repo carry an implicit claim that it is. The
  standing rule does not change: redact at capture time, and a test fixture is
  capture data.

---


## 2026-09-22 — four AWS identifiers went public inside the redactor's own selftest; 28 commits were rewritten to take them out

`orin-native/gpu-concurrency/redact-aws.sh` exists to mask AWS identifiers **at
capture time**, which is this repo's rule. Its selftest asserted both ways — a
string that must come out masked, one that must not — and the strings it used
were the real ones from the session it was written in: the account id, the
`a1.metal` instance's id, that instance's root volume id, and a public IPv4. The
redactor worked. Its fixture was the leak. The four were public from `41a2779`
(2026-09-21) until `c77ecdc` replaced them with documentation values.

- **What it exposed.** The account id is the only one with reach: it allows
  role-name probing against that account's trust policies and it sharpens
  targeted phishing. AWS does not treat an account id as a secret, but it is not
  meant to be broadcast. The instance and volume ids mean nothing outside the
  account. The IPv4 was an ephemeral EC2 address, released when the instance was
  terminated the same day. **No credential, key, token or key material was ever
  in the repo**, so there was nothing to revoke and nothing to rotate: this is
  removal, not revocation.
- **What was done.** The tip was corrected and pushed first. Then
  `20cee01^..main` — 28 commits — was rebuilt in a mirror clone with
  `commit-tree`/`write-tree` (the session's tool policy declined `filter-branch`,
  as it did on 2026-09-09) and force-pushed with lease. Checked before the push:
  author, committer, both dates and the subject identical across all 280
  commits; the new tip's tree byte-identical to the old tip's; a pickaxe over the
  whole new history returning zero for all five spellings; exactly four blobs
  changed, all versions of that one file.
- **Cost.** 28 SHAs changed; 21 citations of 9 of them across `docs/findings.md`,
  seven `results.md` and one test were re-pointed. The repo has no forks and both
  merged PRs predate the leak, so no fork and no `refs/pull/*` carries the old
  objects.
- **What the rewrite does NOT achieve.** GitHub still serves the old commits by
  full SHA until it garbage-collects: `a34f632` and `20cee01` both still resolve
  through the API after the force-push. Only GitHub Support can clear that. Any
  clone taken before today keeps them outright. A rewrite removes the reference,
  not the copies.
- **The lesson is not the obvious one.** "Redact at capture time" held for every
  capture — no record under `results/` carries any of these. It failed on the
  *test fixture of the redactor*, because a redaction test reads as test code
  rather than as captured data. It is captured data. This is the third time an
  AWS identifier has had to come out of this repo's history (2026-07-29,
  2026-09-09, today), and the first time it was inside the tool written to stop
  it.

---


## 2026-09-22 — a follow-up to the notified-shm records, and a review of the AWS tooling

A follow-up to both notified-shm records ran on the Orin in two sessions of
alternating guest boots (A B C C B A, then B S N C C N S B), at k = 4 per boot.
Each boot's services were read back from its console. The record,
`20260922T-a6-orin-shift`, is held locally (NC QDL v7 4.6(i)).

Also this day, from a review of the AWS tooling before it was committed
(`scripts/aws/`).
- **Termination.** `launch` and `wait` now terminate on any failure and confirm
  it. The earlier form could exit on an EC2 eventual-consistency error, or on a
  failed terminate, with the instance still running.
- **Reboot-safe self-termination.** The shutdown is now re-armed on reboot: the
  AMI boots with `panic=-1`, and a pending shutdown does not survive a reboot.
- **Leak scan.** `fetch` refuses a capture that a new leak scan
  (`leakscan.py`) finds identifying.
- **Tests.** Stub `aws`/`ssh`/`scp` tests now drive those paths. The committed
  versions have not driven a billed session yet.

---

## 2026-09-22 — the notified-shm ladder on AWS a1.metal: how the session ran

The owner asked for the cloud work to run first. The Orin's notified ladder
(20260922T-a6-orin-kick) ran again on a bare-metal Graviton1 host. It used the
same image, disk and QEMU package, and every stamped source and script hash was
identical; the two binaries built on each host (the native monitor and
libshmchan) differ.
It covered TCP, D-udp, the polled slot, the console kick and the doorbell out,
at k = 12. The record, `20260922T-a6-a1metal-kick`, is held locally (NC QDL v7
4.6(i)).

**How it ran, and what that found first.**
- **Driver and rehearsal.** One instance script and one local driver. The script
  was rehearsed end to end on the Orin at k = 4 before launch, and two reviewers
  read both for cost, teardown, leaks and fidelity.
- **The rehearsal found two capture bugs.**
  - Ubuntu 22.04's `mawk` does not support `{n}` intervals, so the redactor's
    MAC pattern had never matched there. Fixed in `0e19d15`, with a test under
    each awk. The published AWS records hold only the documented guest MAC.
  - The redactor's 12-digit account mask would have rewritten KVM nanosecond
    counters. JSON is now published byte-for-byte after checking only its
    strings.
- **The reviewers' findings, applied.** Proof that the 90-minute self-shutdown
  is armed before anything is uploaded, aws.exe error output redacted, and the
  root volume read back and checked.
- **The session.** Launched 13:20:34Z, terminate requested 13:31:38Z: about 11
  minutes billed, roughly $0.09. Nothing running or pending afterwards, and no
  orphaned volume.

---

## 2026-09-22 — correction: four places said no cloud IPC figure had been taken

The owner asked why `results/cloud/`'s figure is still TCG when a cloud host with
KVM exists. Answering it turned up a stale claim. On 2026-09-21 the A6
attribution ladder ran on AWS `a1.metal` over TCP (record
`20260921T-ladder-a1metal`, held locally). Yet `results/cloud/README.md`,
`docs/architecture.md` and `docs/digital-twin-design.md` all still said no IPC,
latency or throughput figure had ever been taken on a cloud host, and so did two
rules in `scripts/ci/claim-denylist.txt`. The first two were written before the
run (2026-09-20, and the morning of 2026-09-21); nothing flagged them afterwards,
and this log never had an entry for the a1.metal ladder. All four now name it as
the only cloud IPC figure. The rules stay for every other cloud IPC claim, and an
exemption clears the ladder.

The question's answer is now in `results/cloud/README.md`: A1 is QHV hosting a
QNX guest over QHV's own virtio-console vdev. QHV needs EL2, a KVM guest gets EL1,
and KVM on `a1.metal`'s Cortex-A72 does not nest. So a cloud host with KVM can
run A6 (QNX as a guest) but never A1, and A1's figure stays TCG history (OD10).

What this does not change: no cloud leg has been built, and no UDP,
shared-memory or throughput figure exists from any cloud host.

---

## 2026-09-22 — notified shared memory: the design, and what it took

The owner asked for the interrupt-driven variant of the shared-memory arm. It
was not built as asked. QEMU 6.2's `ivshmem-doorbell` always has its MSI feature
and interrupts a guest only through MSI-X, with no INTx fallback. Under KVM with
the ITS, `setup_interrupt()` leaves the guest's eventfd unattached until the
guest enables MSI-X, and on the path without an irqfd `ivshmem_vector_notify()`
drops the notification while MSI-X is off. MSI-X in this QNX guest would come
from the PCI server; programming the MSI-X table and the GIC ITS by hand, as
`shmcfg` does for the BARs, was not attempted. So, by the owner's choice of "both
variants", the probe kicks the guest over a virtio console driven by the SDP's
`devc-virtio` on a plain SPI, and the guest answers either over it (D-kick) or
through the `ivshmem` Doorbell register, which a KVM ioeventfd turns into a write
to the probe's eventfd (D-db). The record, `20260922T-a6-orin-kick`, is held
locally (NC QDL v7 4.6(i)).

**What it took.**
- **This project's own ivshmem server.** A design review read QEMU 6.2's source
  and found that reusing a peer id makes QEMU write into freed memory. Ids now
  only go up.
- **A readiness handshake.** QEMU drops a doorbell to a peer it has not yet
  registered, so each doorbell arm starts with an untimed handshake. A reply
  without its notification is its own failure ("lost"), never a stall.
- **A doorbell proof** before any doorbell arm, and **KVM counters** around every
  arm.
- **A code review.** Four lenses produced 24 findings, each verified, 19 of them
  real. They include a failing `recv` that only the kick arms paid for inside
  the timed window, and an early notification that came back as a sample as
  long as the timeout.
- **Two CI failures.** On the branch, a server outlived its SIGTERM on Python
  3.12; it now stops by a flag and a wake-up. On `main`, the same commit
  `a9df382` then failed one test that asserted an exact count of stale kicks
  (2 against 1). With no spacing between requests, the monitor's re-check can
  take request n+1 before reading its kick byte, and then counts that byte as
  stale, so the count is timing. `16826cc` asserts the probe's own notification
  accounting instead, and at least one stale kick where one is sent. That
  commit changes tests only; CI passed it with none of 337 tests skipped.

The run used a `git archive` of `a9df382`, whose tests had passed on its branch
with none skipped.

**Next (OD12):** a SOME/IP arm stays proposed, not decided. A doorbell into the
guest would need MSI-X: from a QNX PCI stack on QEMU virt, or from
programming the MSI-X table and the GIC ITS by hand, which was not attempted.

---

## 2026-09-22 — shared memory over ivshmem: the design, and what it took

OD12's second other IPC path ran: one 64-byte request/reply slot in QEMU's
`ivshmem`, both ends polling, beside the ladder's TCP and UDP rungs in one run, on a
fresh boot of a new image, paired within rounds (k = 12, c7 disabled). The record,
`20260922T-a6-orin-shm`, is held locally (NC QDL v7 4.6(i)).

**What it took.**
- **No PCI server in the image.** The monitor configures the one ivshmem function
  itself through ECAM, with single-register inline-asm accesses so KVM always gets
  a valid syndrome, and maps BAR2 cacheable, because without FEAT_S2FWB an
  uncached guest view would mismatch the host's. The image that ran carries none
  of the PCI server's files.
- **The probe's end is C.** Python has no store-release or load-acquire, and Armv8
  is weakly ordered; `shmchan.c`, built by the run, does the slot, and the timing
  stays in Python as for the sockets.
- **Three transports in one ladder** are ordered by a Williams design over the
  groups (period 6), lifted from the load arms' design with its output unchanged.
- The run's tooling was committed and pushed first (`2abbfba`, CI green including
  the gcc-only shm tests, which were also run by hand on the Orin), and the run used
  a `git archive` of that commit; a K = 6 dry run preceded it on an earlier boot.

**Next (OD12):** an interrupt-driven shared-memory arm (`ivshmem`'s doorbell) is
not built; a SOME/IP arm stays proposed, not decided. OD11's remaining items are
still unscheduled.

---

## 2026-09-22 — UDP beside TCP on the ladder: the image and the tooling

OD12's first other IPC path ran: the four attribution-ladder rungs over UDP beside
the same four over TCP, in one run, on one guest boot, paired within rounds (k = 12,
c7 disabled), after a K = 2 dry run on the same boot. The record,
`20260922T-a6-orin-udp`, is held locally (NC QDL v7 4.6(i)).

**It needed a new guest image, built to a standard.** `ifs-udp.bin` is the campaigns'
`ifs-demo2.bin` plus two start lines: every file in it is byte-identical except the
two servers, the startup script, the embedded build file and the build date, and the
build script now refuses any startup entry but ours. The stamp now identifies the
guest from the running QEMU itself — image and disk sha256, pid, start time. Reading
that start time from the 2026-09-21 process before stopping it also showed, rather
than asserted, that the day's three campaigns shared one QEMU process.

**What the review of the tooling caught**, among 18 confirmed findings: a monitor test
that passed against a UDP path that never judged a claim; a build-script guard that
checked one of its two paths; and a diagnosis of its own that was wrong — the SDP's
msys tools strip backslashes from arguments with glob characters; its `sed` was fine.
The build of the image also moved the rebuilt `startup-qemu-virt`, which had lived
only in a session scratchpad since 2026-09-18, to a durable ignored location.

**Next (OD12):** shared memory over `ivshmem`. A SOME/IP arm over this UDP path with
vsomeip stays proposed, not decided.

---

## 2026-09-21 — pinned loads: the design gaps closed, and what the tooling review caught

The three gaps the first campaign left are closed and the campaign re-run with them
closed: the probe reports its own scheduling, every window is traced (root tegrastats,
both EMC readings, the GPU clock), and load threads are pinned and read back, so arms are
named by placement. The record, `20260921T-a6-orin-pinned`, is held locally (NC QDL v7
4.6(i)); c7 disabled, tooling as committed in `9dcf444`. An independent check re-derived
the record's first draft from the raw files, and the record is the corrected version.

**Stalls.** A stall is now recorded as an outcome rather than stopping the run (owner
decision).

**What the tooling review caught on the way**, besides the design gaps: a sampler that
could not be stopped on the board (sudo 1.9.9 ignores a signal from its own process
group -- invisible to stub-based tests), tegrastats' EMC field existing only as root, and
a probe that would have filed a dropped connection as a stall. Two adversarial reviews
(30 findings, 25 confirmed), mutation checks on every new guard, two board dry runs.

**Next (owner decision, 2026-09-21): other IPC paths** -- UDP first, then shared memory
over ivshmem. A SOME/IP arm is proposed with vsomeip; AUTOSAR's CAPI is on hold because
its licence allows information-only use without modification.

---

## 2026-09-21 — the first A6 campaign on the Orin: the bugs it found and the gaps it left

The adopted tooling ran on the board for the first time: the ladder with all four arms,
interference at k=12 and saturation at k=20, on the image, disk and QEMU build that had
run on `a1.metal` the same day. The record, `20260921T-a6-orin`, is held locally (NC QDL
v7 4.6(i)); its figures were independently re-derived from the raw files by a separate
analysis.

**Idle states.** The governor pin controls frequency; it never touched idle states, and
the Orin exposes `c7` (declared exit latency 5000 us) enabled. The campaign was re-run
with c7 disabled. Two design statements about `fma.cu` -- that the interference cpu arm
is its footprint twin, and that gpu_cpu6 runs seven busy threads -- were found wrong and
are corrected in the tooling.

**Four bugs the first real run found, all failing closed** -- the argv[0]/pgrep
self-match, a freshness check reading a rewritten stamp, "GR3D" matching its own digit,
and the redactor turning a latency sample into `0.<account>`. Committed separately with
mutation-tested fixes. The as-run library and scripts are committed before their comment
corrections, so every hash in a stamp names a file git holds; the one earlier ladder
library that no commit held was reconstructed byte-for-byte from two that do.

**Gaps it left, closed next:** whether SCHED_FIFO actually took effect in cpu6_prio (it
was established only by procedure), EMC and GPU clocks, and load-thread placement.

---

## 2026-09-21 — OD11: A6's gate closes on k, not n

The owner adopted [measurement-design.md](measurement-design.md) as written, which settles
the last item A6's gate had left. A6's gate is closed: OD10 fixed what it measures (KVM
only, TCG twin legs withdrawn), OD11 fixes how much.

**The answer was not a bigger sample.** The question on the table was "what sample size
should A6 use?", and measuring the thing itself answered it differently: the budget goes
into **k**, the number of interleaved rounds, not into n. The measurements behind that
choice are held locally (NC QDL v7 4.6(i)). Adopted: n = 1000 timed samples, 200 warm-up
discarded, 2 ms spacing, **k ≥ 12**.

Adopted with it, because the design fixes them together: the attribution ladder, guest-side
timestamps, the frame-size sweep, the §3.5 controls, the §3.6 reporting rules — including
publishing the per-run maximum as a k-sample set rather than as one number — and the §3.7
falsification.

**What it does not settle.** No isolation or freedom-from-interference claim follows from
any of it. The guest crossing stays undivided between tap, virtio-net, `io-sock` and
the guest scheduler; splitting it needs kernel tracing on both sides and is not proposed.
Nothing already published is retracted or re-derived — figures taken under n = 3000 / k = 2
keep that label. And the campaign itself has **not been run**: this is a design decision, not
a measurement.

v1's manifest fields are not inherited. A6 has no native QNX Hypervisor host, no kexec entry,
no second memory window and no startup `-P` value, so freeze gate items 3, 4, 6 and the
entry-path choice describe an architecture that no longer exists.

Also decided the same day: the 9 remaining prose-gate warnings stay as warnings. Six are ISO
26262 vocabulary in a study worksheet's own column headers; three name the never-built
Graviton runtime host in the body of `docs/fusa/phase1-cloud-bringup-fmea.md` and
`docs/tara/phase1-cloud-tara.md`, and both documents keep that body **verbatim on purpose**,
with a dated addendum correcting it — tara:14 says so in those words. The documents are
honest; the scanner cannot see a document-level correction. Building machinery to teach it
that convention was judged not worth it for nine warn-only lines.

---

## 2026-09-21 — seven paths out of a public repo, and the three things a link-checker could not see

The owner unpublished the AI-facing material: `CLAUDE.md`, `AGENTS.md`, `agents/`,
`.claude/agents/`, `.codex/`, `skills/`, `docs/jd-mapping.md` and
`docs/onboarding-prompt.md`. All stay on the build machine, gitignored. Untracking
hides a file from the tip only — every one remains in earlier commits, and the
2026-09-20 decision not to rewrite history stands.

**Two things were preserved rather than deleted, and both had to be found first.**
`skills/fmea/examples/phase1-cloud-bringup-fmea.md` was not study notes: two tracked
FuSa gate documents name it as their *input artefact*. It moved to `docs/fusa/`, beside
its consumers, and five relative paths inside it were rebased. `docs/onboarding-prompt.md`
held one substantive line — the honest-framing rule — which is now stated in README's
"Known limitations" section, because `docs/fusa/phase1-cloud-bringup-fmea.md` and
`docs/phase2-topology-decision.md` both cite that rule by name and, once `CLAUDE.md`
went private, nothing public stated it. An audit of `docs/jd-mapping.md` found no
equivalent: every fact it carried is recorded more fully elsewhere, each checked and
then adversarially re-checked.

**CI was right and the gate was wrong.** README said the denylist runs over `docs/**`;
`claims_gate.py` read `docs/*.md`. Seven tracked files under `docs/fusa/`, `docs/cyber/`,
`docs/tara/` and `docs/middleware/` had never been scanned — including the FMEA that had
just been moved there. Widening the glob to match README surfaced 13 hits, and the split
is the interesting part. The FuSa and TARA documents correct themselves with a dated
*addendum table* ("partially falsified", fmea:307, tara:634) rather than inline
`~~strike-through~~`, so `strip_superseded` cannot see the correction and every original
assumption sentence read as a live claim. Adding the hedges those documents actually use
— `assumed`, `illus*`, `notional`, `falsified`, `hypothes[ie]s` — to `PLANNED_RE` took it
to 9. Those 9 stand as warnings, not fixes: 6 are ISO 26262 vocabulary in a study
worksheet's own column headers, and **3 are genuinely stale sentences** naming the
never-built AWS Graviton runtime host in `docs/fusa/phase1-cloud-bringup-fmea.md` and
`docs/tara/phase1-cloud-tara.md`. Correcting a Phase-1 gate document is the owner's call,
so they are recorded here and left.

**Two latent traps, both of the CI-passes/local-fails shape.** First: the denylist
exemption `designed for AWS Graviton; as built, QEMU TCG` was sustained by
`docs/jd-mapping.md` alone, so `test_every_exemption_is_justified_and_used` would have
gone green locally — the file is still on disk — and failed only in Actions. Second, and
worse: the local-only skip list was hardcoded in three places, and only the gate's copy
was load-bearing. The two test copies could drift without failing anything, which means
the next exemption keyed to a local-only file would have reproduced this exact failure
after the lesson had supposedly been learned. Collapsed to `claims_lib.LOCAL_ONLY`, one
constant, three call sites. Verified both directions: with `docs/jd-mapping.md` on disk
and with it moved away, the gate reports the same file count and pytest passes — local
and CI now agree by construction rather than by luck.

**A third bug fell out of the widened scan.** The gate had no output-encoding guard, only
an input one, so printing a sentence containing `≥` crashed it with `UnicodeEncodeError`
on the owner's cp950 console while working in Actions. `sys.stdout.reconfigure(errors=
"replace")`.

**Job- and role-targeting phrasing removed**, per the owner's decision: 7 sentences across
`bsp-selection.md`, `future-multi-soc.md`, `orin-port.md`, `security-model.md` and
`digital-twin-design.md`. Two of them were dangling references to the now-unpublished
`docs/interview-narrative.md`. Eleven further candidates were rejected on review — the
`.gitignore` comments that explain *why* the material was removed must keep naming it, and
"a public portfolio has zero appetite for license risk" states the reason for a rule.
Removing those would have made the repo less honest, not less promotional. Dated entries in
this file that mention removed files are left alone: a record that names a removed file is
correct, an *instruction* to use one is a trap — which is why `docs/onboarding-prompt.md`
went and the ADR-002 §4 follow-up list stayed.

**Also:** `docs/architecture.md` rewritten overwrite-only, 511 lines to 189, 52 strike
markers to 0, with its three diagrams generated from computed widths after two were found
1–2 columns out; the two merged remote branches that still carried `docs/jd-mapping.md`
(`readme/phase4-qhv-leg`, `ci/claims-gate`, both 0 commits ahead of `main`) deleted, so
`main` is the only remote branch; `AGENTS.md` collapsed from a 284-line hand-maintained
copy of `CLAUDE.md` — 20 strike markers, a JD section, a `skills/` tree that no longer
exists — to a pointer; and `.gitignore`'s "11 of 257 commits mention an agent" corrected
to a figure that can actually be re-derived (22 of 248, `git log --grep=agent -i`).

No measurement was taken today and no claim about the hardware changed.

---

## 2026-09-19 — the cloud twin's premise, re-read: the KVM limit was non-metal, not cloud

**What the cloud twin was for.** It was *designed* as AWS Graviton (`c7g.large`, arm64) for one
reason: a second **ARM** host that could run the same images under **KVM**, so the twin diff would
differ in the host and nothing else. That died in 2026-06, when ADR-002 found non-metal Graviton
exposes no `/dev/kvm`, and the leg fell back to the Windows PC under TCG — at which point, as
[digital-twin-design.md](digital-twin-design.md) §1 puts it, "there was nothing left that required
the leg to be in the cloud at all."

**ADR-002 was not wrong; it was read too broadly since.** Its own words are *"Any
hardware-accelerated partitioner — KVM **or** QHV — needs `*.metal` or real silicon."* That
sentence holds. What has been repeated downstream ever since, and
what is stale, is the flatter clause beside it: "KVM-on-cloud is dead." The limit was always
**non-metal**, never **cloud**: a bare-metal `a1.metal` instance exposes `/dev/kvm`.

**What this is not.** No cloud *leg* has been built. The twin diff has not been re-run and its
earlier results stay architecture-version history. `a1.metal` is Graviton1 / **Cortex-A72** against the
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


## 2026-09-19 — an `a1.metal` session: cost and hygiene

A boot check of the QNX IFS under KVM ran on a fresh `a1.metal` in eu-central-1, with
the 2026-07-29 launch line and one variable (the IFS) per arm. Its capture,
`aws-a1-metal-kvm-fix-crossvendor.log`, is held locally (NC QDL v7 4.6(i)).

**Cost and hygiene.** One instance, ~1 h, ~$0.5, terminated immediately; `shutdown -h +90` plus
`--instance-initiated-shutdown-behavior terminate` were set at launch so it would self-terminate
even if contact were lost. No instance id, account id or address is recorded in the capture or
here: the 2026-07-29 run leaked its instance id into git history and needed a `filter-branch` to
clean, so this one redacts at capture time by construction.

---


## 2026-09-18 — a service across the partition: the design

This is the first cross-partition service: **L4T classifies a real image on the GPU and
QNX decides whether to believe it.**

**The two ends.** On L4T, `compute_client` loads a TensorRT engine, reads an actual MNIST PGM from
`/usr/src/tensorrt/data/mnist/`, runs it on the Ampere GPU, and takes class and confidence from the
network's own output — never fabricated; if it cannot classify it exits non-zero. It sends class,
confidence and its own GPU time as a 64-byte frame in the existing
[`ipc-test/common/frame.h`](../ipc-test/common/frame.h) layout. In the QNX guest,
[`ipc-test/qnx-safety-monitor/`](../ipc-test/qnx-safety-monitor/) checks the claim against
plausibility rules and writes a verdict back. Transport is a **real `br0`/`tap-qnx` bridge**, not
slirp — the guest at a static address, reachable both ways.

The run's console capture, `20260918T-kvm-gpu`, is held locally (NC QDL v7 4.6(i)).

**Two engineering notes worth keeping.** The monitor is started from **inside the IFS**, on a line
placed after `startup.sh` returns — `post_startup.sh` lives in the system partition, so auto-starting
it the conventional way would have meant rewriting `disk-qemu`, which published results depend on.
And this run used `-snapshot`, so the guest's writes went to a temporary overlay, not to the
disk file.

**What this does not show.** The monitor is **not a safety mechanism in any ISO 26262 sense** and no
ASIL claim attaches to it; its rules are legible plausibility checks, not a validated diagnostic.
Nothing here shows isolation, containment or freedom from interference: the boundary is KVM, where
**Linux owns the QNX guest's memory**, which is the inverse of the Type-1 arrangement this project's
DRIVE OS comparison is against. QNX cannot touch the GPU.

---


## 2026-09-18 — a `startup-qemu-virt` board written in this repo, and a decision not to file

Relinking `startup-qemu-virt` against a rebuilt startup library needs its board source, and **the
SDP ships that binary without its source**. That is what changed today — we wrote the board.

**What was built.** `orin-native/startup/qemu-virt/`, written against the device tree QEMU actually
generates rather than copied from `t234-orin-nano`: the PSCI conduit is probed from the tree
(`method = "hvc"`) instead of forced to SMC, `psci_cpu_id` is left as the library's identity mapping
(the virt machine's MPIDRs are flat, unlike Tegra's), and RAM comes wholly from `init_raminfo_fdt()`.
The startup library was rebuilt with `-fno-auto-inc-dec`; any disassembly was of our own build, never
of a QNX-shipped binary (NC QDL v7 4.6(c) stays clean).

**Which startup is actually in the image, on two independent discriminators.** The IFS was built by
running `mkifs` directly with an overlay repo ahead of `$QNX_TARGET` in `MKFS_PATH`, so the bare name
`startup-qemu-virt` resolves to ours without touching the SDK. Proof it did: the `_CS_MACHINE` string
we compiled in appears **once** in our image and **zero** times in one built with the SDK's startup, with a positive
control (our startup ELF 1 hit, the SDK's 0); and the startup entry point differs, `40081ab8` vs
`40081da8`. This mattered — `ifs.build` sets `[+optional]`, so an unresolved file is skipped silently
and `mkifs` still exits 0. A zero exit proves nothing here; only the contents do.

The boot captures are held locally (NC QDL v7 4.6(i)). This is **not a supported configuration**: the
startup is one we rebuilt, and QNX ships no such binary. Nothing here concerns the QNX Hypervisor under
KVM: QHV needs EL2, and ARM KVM does not nest on A78AE.

**Not being filed (owner decision, 2026-09-18).** The owner decided not to report the GICv3/NISV
investigation to QNX/BlackBerry. Earlier entries and action items proposing that filing are superseded
by this decision, not by new evidence.

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


## 2026-09-17 — the revision-4 precondition gate was narrower than its design, and was fixed

The two-guest rung, B5, ran on the board on 2026-09-17; its record is private and git-ignored, held
locally (NC QDL v7 4.6(i)).

**A defect found while checking the gate that let B5 run, recorded because nothing else records it.** The
revision-4 precondition at `s1-board.sh:5750` filters B2's readings with `grep -v ' X-f-final$'` and whitelists
no other class. Its own comment says B3-B5 run "while every B2 reading on file is **clean**", and §16.6.1
defines **X-f-c** as exactly that: the confirmatory run clean by §16.6's field rules, MET by §6.7. So a reading
correctly classed X-f-c would survive the filter, make `r4bad` non-empty and **block B3-B5** — the gate is
narrower than both its own comment and the design it implements. `X-f-c` appears in that file only in a
comment, in no conditional, and no self-test covers it. `--confirmatory` was added to the parser after
B2-a3's reading was taken, and the harness passes the flag only when D86's key is spent. Nothing is
blocked now — the design notes D86's permission is spent, so the flag has no run to read — but the next
confirmatory run would hit it. **Fixed the same day, on the owner's decision.** The
filter now admits both of §16.6.1's clean classes, and three self-tests cover it: a confirmatory `X-f-c` beside
the original reading blocks neither B3 nor B4 nor B5, and an `X-f-provisional` still blocks, which pins the
boundary at the two **final** classes rather than at every name beginning `X-f`. The sibling gate at the D86
key was deliberately left strict on `X-f-final`: there, an `X-f-c` on file means a confirmatory run has already
been made, so admitting it would hand out a fourth observation against D86's bound of one. No recorded reading
moved and no class was re-labelled. Recorded also in the B2-a3 run note.

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

**What this does not close.** Item 8 is discharged; the freeze is not. **2026-09-17, later the same day: B5
ran on the board on these pins; its record is held locally.** M3's and M4's recorded figures were measured against the old
artefacts and stay exactly as recorded — they are A4 history, not v1. The five curated boot logs that name the
old host pair are **left untouched on purpose**: they record which images were actually booted, and the images
they name really are gone now. The records are private and git-ignored, and no figure is published here.
[orin-native-port-plan.md](orin-native-port-plan.md#freeze-gate) carries item 8's state.


## 2026-09-16 — S1-F's revision-4 ladder on the board: two process incidents

With the owner at the plug, revision 4's three rungs — B1, the watcher run and B2 — ran in one session, in the
pre-registered order. The rule that reads them, its reference and the image pins were registered before any of
them ran. A keyed, bounded confirmatory run of B2 (D86) followed on 2026-09-17, and so did B3 and B4. The
records are private and git-ignored, held locally (NC QDL v7 4.6(i)).

Two process incidents, recorded because they are process rather than board findings: the watcher run's first
attempt refused at the pre-registration check because its rule-file variable was unset in the session environment
— before any board contact, with no kexec issued and the budget untouched, and the re-run matched the stage the
refused attempt had already appended to the append-only ledger, so nothing was recorded twice; and B1's capture was
started far larger than that rung needed and had to be stopped by hand to free the exclusive serial port for the
next rung, so captures are now sized per rung.

[s1-design.md](../results/orin-native-port/20260909T1100Z/s1-design.md) §16;
[the plan's S1-F block](orin-native-port-plan.md#the-revised-ladder).

## 2026-09-16 — M4's r0 image rebuilt under the frozen instruments, and the guest-disk rebuild deliberately not done

> **2026-09-17: the guest-disk rebuild was subsequently done** — the deferral's stated reason, a pre-registration
> that had not yet run, expired when revision 4's ladder ran on 2026-09-16. See the 2026-09-17 "OD7 executed" entry.
> Nothing below is withdrawn: the cost analysis recorded here is what made the later decision quick to take.

Two freeze-gate items were taken up while the board was unattended. One is now done on the PC; the other
was stopped before it started, and the reason is the more useful of the two results.

**r0 rebuilt (freeze-gate item 9).** M4's two functional rungs ran under different instrument versions:
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
Item 9's attended board round ran; the revision-4 ladder ran on 2026-09-16; the owner then re-took
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
revision 4 has run on the board**, and no Linux guest has run on the board. The
confirming runs — B1, a watcher run, then B2 — need the owner at the plug, and even a clean result would not show which
cache held the residue, nor that the clean rather than the time it takes removed it, nor DMA quiescence after kexec.
The records stay private and git-ignored, and no figure is published here.
[s1-design.md](../results/orin-native-port/20260909T1100Z/s1-design.md) §16;
[the plan's S1-F block](orin-native-port-plan.md#the-revised-ladder).

## 2026-09-15 — S1-F: a CPU cache-residue hypothesis, and revision 4's startup cache clean (designed, not run)

The owner chose a UEFI-entry arm (J7a), which was designed
([s1-design.md](../results/orin-native-port/20260909T1100Z/s1-design.md) §15.6.1, §15.13). Before any J7a board step, a
desk analysis of the kexec runs' private records made a CPU cache-maintenance gap at the hand-over the leading
hypothesis (HYPOTHESIS, untested; §15.14). Startup fills the canaries with the MMU off, and its only cache
maintenance is a set/way clean, which reaches only the boot CPU's own caches. A cache line of the same address that
Linux left elsewhere can later be written back over the pattern. Under that hypothesis both of J7a's pre-registered
consequences would route to the wrong next step, so the owner deferred J7a's board steps and suspended those
consequence clauses, with a two-part lift (D54). A Linux-side arm that takes every secondary CPU offline before the
jump (J6o) was designed and then shelved (D65), because it added no cache maintenance the controls lacked. The J6c
watcher run's record is held locally (NC QDL v7 4.6(i)).

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

## 2026-09-14 — S1-F's first board session: harness corrections and owner decisions

S1-F's first board session ran with the owner at the board: B0, B1 and B2, then four diagnostic J rungs (J1-J4)
that the design's revision 3 added, with the rule that classifies B2 registered before any of them ran
([s1-design.md](../results/orin-native-port/20260909T1100Z/s1-design.md) §14.12, §15). The run records are
private and git-ignored, held locally (NC QDL v7 4.6(i)).

- **B0, pre-flight and staging, needed two harness corrections**, neither a board finding. The `/proc/iomem`
  gate had failed on the running L4T kernel's own image, which KASLR had placed inside the candidate window; it
  now excludes only that exact kernel-image entry. The kexec landing check needs dynamic debug, which the
  board's kernel lacks, so it is recorded as skipped. The shim's own landing check, which resets the board
  before any QNX code runs, is the guard, together with the parser's entry-PC rule.
- **B1's output exposed a harness privacy-scan defect** that could keep a copy raw; it was corrected, and the
  earlier copies were rescanned by hand.
- **J3's xHCI read.** The harness's return read omitted the xHCI path, so the rebind check had nothing to
  match. On the owner's decision J3 was re-judged from its records, the original line kept; the harness read
  was corrected.

The owner put DMA quiescence after kexec into the plan's freeze gate (item 3, D32): until it is shown for the
claimed windows or declared, no campaign record claims memory integrity.

Next is J6, a read-only watcher image (D27). A second build of the canary tool reports word classes, re-read and heal
counts and page bitmaps, never canary content, and a large timed hold watches sysram. Then comes the owner's decision
on a UEFI-entry arm (D30). The run records are
private and git-ignored, and no figure is published here. The plan's
[S1-F block](orin-native-port-plan.md#the-revised-ladder) carries the status.

## 2026-09-14 — S1-F under TCG (T1-T3): gate and harness changes

S1-F's PC half ran, all under QEMU TCG (emulated) on the Windows PC; none of it ran on the board. T0 had built and
gated the pieces on the PC first ([s1-design.md](../results/orin-native-port/20260909T1100Z/s1-design.md) §14.6). The
guest is the board's stock L4T 5.15 kernel `Image`, with an initrd built from the board's own busybox. The host is a
TCG QHV host image, so qvm runs inside the emulation, as on the cloud leg.

Changes made during T1, qvm's `dryrun` (s1-design §14.10):
- The gate had recorded qvm's exit code without judging it, and its error heuristic looked only for certain
  words. Every dryrun gate now needs a zero exit and no qvm `[file:line]` diagnostic.
- The virtio-console `hostdev` moved from the pty slave to the pty master, as M3 wired its console (the design's
  own fallback).
- The console reader would otherwise have opened the slave before qvm held the master, so the host script now
  starts it only after qvm is launched.

T3 rehearses the ten-minute script; it is not pass item 4. Next are the board rungs, with the owner present:
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
- Linux only now; the two-guest rung runs only if v1 keeps the QNX guest. **2026-09-17 (OD9): v1 keeps it; the rung is owed.** **2026-09-17, later: it ran.**
- D10 tightens plan item 4, so the guest's end probe is required, not only a live qvm.
- D12: the dumped FDT is private evaluation output.
- D17: any QNX support request goes through the supervising professor first.
- No download up front.

Next: copy the board's `Image` and `initrd` to the PC (D3), then T0. Unknowns T1 must answer first: whether qvm accepts
the EFI-stub `Image` with a bare `load`, and what device tree it generates.

## 2026-09-13 — Owner decision: Phases 2 and 3 are closed as architecture history

The owner closed two phases in chat. Phase 2 (cloud twin IPC and latency) is closed as architecture A1 history, and
Phase 3 (the hardware twin port on the Orin plain leg) as A2 history, so the README roadmap marks both done. Closed does
not mean their original targets were met; the Orin IPC run also used a rebuilt IFS. Their records are kept as
architecture-version history and not chased, as the 2026-09-11 freeze decision set out. Neither phase will be redone.
The v1 campaign's TCG twin legs and IPC runs are campaign work on reference architecture v1, not a reopening of Phase 2
or 3. Two items stay open, and neither is tracked under those phases any more: the `qvm`/TCG virtio-queue
investigation, and the IPC sample size, which is set once, at the v1 freeze. The GICv3/NISV investigation is a
separate track, outside reference architecture v1. The README roadmap (branch `readme/phase4-qhv-leg`, draft PR #1)
now shows Phase 3b's rungs: M0 to M5-F have run, and S1-F, the v1 freeze and the single measurement campaign are ahead.
CLAUDE.md's Phase status carries matching notes. Nothing was run for this entry. The freeze decision is in
[orin-native-port-plan.md](orin-native-port-plan.md#architecture-versions-and-the-measurement-freeze-decided-2026-09-11).

## 2026-09-13 — M5-F's board session: deviations, tool defects, and the end of the M path

M5's functional rung ran on the Orin Nano in one attended session, with the owner at the plug from P1 to C. It ran
m5-design's option A. Our own EFI loader, `M5LOAD.EFI`, carries the unchanged, pinned M1b image. It was launched from
the firmware's built-in UEFI Shell on a cold boot, so no Linux and no kexec ran between the cold power-on and the
loader. P2 was a control cold boot with no key, and R1 the rung itself. The session staged that one file in the root
of the SD card's ESP, after backing up and hashing `extlinux.conf` and `BOOTAA64.efi`; afterwards the file was removed
from the ESP (D10), and the TX wire came off J14 pin 3, so the board is back on the M0-M4 wiring.

Deviations, all recorded:
- **P1 item 4:** the terminal loopback test was not performed. The owner decided this with the TX wire already
  fitted. The terminal's self-test ran instead, and P2 was the control for a stray byte when COM3 opens.
- **P3's first attempt:** it missed the ESC window, because the keys went to another window. L4T was let boot fully,
  and P3 was repeated.
- **P3's second attempt:**
  - DC power was removed and restored before L4T's kernel reported its power-down, which made an unclean shutdown.
  - More than one ESC was sent where §6.5 asks for one.
  - The Shell, entered through the Boot Manager, was reached after the 120 s operator bound.
- **In R1** the Shell was reached within the bound, though more than one ESC was sent again. No key was armed or sent
  after `go`.
- **The PC tools:**
  - The terminal's key log had recorded nothing, ever. It was fixed in 7c2e87d before P3.
  - Three watch-and-judge helpers had defects. Two showed up in live use in P3 and were fixed before R1. The
    poweroff watcher took the Setup menu's silence for a finished shutdown, after the power had already been cut. The
    reset watcher's pattern rejected a stray trailing character, so it never handed over, and the L4T watch was
    started by hand instead, retroactively over the capture. The third, an awk pattern in the T2/T3 judge that could
    not run, was found in replay before R1. They are session tools and are not
    committed.

**The M path has ended.** The owner confirmed on 2026-09-11 that it ends at M5-F, so README PR #1
can now merge. Merging it is the owner's call. The session's figures stay unpublished until the 4.6(i)
consultation: the run note on the local
branch `m3-results-unpublished`, the logs in the session's git-ignored record. Next: S1-F, a Linux guest without a GPU under native qvm, with the qvm `dryrun` gate first. Details
are in
[m5-design.md](../results/orin-native-port/20260909T1100Z/m5-design.md) §14, "Board session (2026-09-13)", and in
[orin-native-port-plan.md](orin-native-port-plan.md#architecture-versions-and-the-measurement-freeze-decided-2026-09-11).

## 2026-09-11 — M4-F's board rungs: harness and parser defects

M4's two functional rungs ran on the Orin Nano, under different instrument versions. r0 ran the trace tools under
the EL2 host without qvm; r1 ran M3's full run with a trace window around the IPC pair.

Defects in this project's own tooling, found on the way:
- **I24, a parser defect,** made r0's own harness verdict a fail. r0 was re-parsed offline with the fixed parser,
  and re-validating r0 under the instruments the freeze will gate is now a freeze-gate item.
- **I26, an implementation defect.** The sizing rules had costed the linear window as a 512-buffer ring, so r1's
  first attempt stopped at the memory gate before the trace was armed; tracelogger's own usage message gives a
  linear capture's defaults. The fix changed only that gate value.

An adversarial review (16 read-only agents) narrowed what the harness shows:
- **Ungated flush evidence:** the evidence that every CPU's tail was flushed sits in fields no gate reads.
- **Weaker gates:** several parser gates are weaker than the design's wording. They must be fixed before the
  campaign's timed runs rely on them.
- **Redaction:** the harness's COM3 redaction misses the board hostname in its local, git-ignored copies.

The run records and figures are on the
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
plain QNX guest under TCG to the QNX Hypervisor inside TCG, and Phase 3b now targets the QNX Hypervisor natively on the
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
It also covers M3's figures, which stay on the local branch `m3-results-unpublished`. S1 crosses the native-port
plan's non-goal of no Linux guest, which is now struck through there. One
assumption awaits the owner's confirmation: the M path ends at M5's functional pass, which sets when README PR #1 can
merge. Nothing was run for this entry. The architecture timeline, the measurement inventory, the freeze gate, the v1
manifest and the campaign are in
[orin-native-port-plan.md](orin-native-port-plan.md#architecture-versions-and-the-measurement-freeze-decided-2026-09-11).

## 2026-09-10 — M1: the serial console moves to J14

The first native QNX image was run on the board, entered by kexec from L4T with no
QEMU underneath, and watched live over the J14 debug header. Its runs' records and
captures are held locally (NC QDL v7 4.6(i)).

**Getting the console working took its own detour, recorded in
[serial-console-wiring.md](../results/orin-native-port/20260909T1100Z/serial-console-wiring.md).**
I first recommended the 40-pin header because its wiring could be checked from
Linux; three UARTs transmitting at once put nothing on its pin 8, the kernel showed
`UART1_TX_PR2` as `MUX UNCLAIMED`, and the carrier specification plus a known-good
adapter left the unrouted pad as the only cause. J14 carries the real console, and
the first capture off it was UEFI's own `L4TLauncher: Attempting Direct Boot`,
proving the wiring with none of this port's code involved. The carrier spec also
settled the long-open pin question: J14 pin 4 is `UART2_TXD`.

## 2026-09-09 — the QHV leg's write-up reviewed; tooling lessons, a board safety rule, and owner decisions

An adversarial review of the repo (map + consistency audit + eight refutation
attempts, two lenses per claim) was run against the previous day's path, and
the experiments it demanded were then executed on the Windows PC and the Orin.
Their logs are held locally (NC QDL v7 4.6(i)).

**What the review found wrong, in order of consequence:**

1. *"A genuine one-variable comparison"* — **overclaimed.** The QEMU binary
   was never controlled (Windows 11.0.50 fork build vs. Orin stock 6.2.0),
   and even at equal release the build (compiler, flags, libraries) and the
   TCG backend (`tcg/i386` vs. `tcg/aarch64`) travel with the host. §1a now
   defines "host" as that bundle and stamps every controllable part.
2. The authoritative log (this file) and CLAUDE.md still said the Orin half
   had never been run; §1a contradicted itself between adjacent paragraphs;
   the June curated log's header, `scripts/qhv/README.md` and §1a told the
   reader to look for a host banner; AGENTS.md carried a stale KVM statement.
   All corrected in this commit.
3. `disk-qemu` is a writable raw disk booted without `-snapshot`: it mutates
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

**QEMU builds for the version comparison.** QEMU v11.1.0 was built from source on
the Orin (`build-qemu-on-orin.sh`; ~9 min at `-j4`; needed `python3-venv` and
`python3-tomli` on Ubuntu 22.04 beyond the obvious). A second 11.1.0 build that
leaves the NS EL2 virtual-timer output unconnected to the GIC is carried as a
[patch](../scripts/orin/patches/qemu-v11.1.0-unwire-ns-el2-virt-timer-irq.patch).
Two Weilnetz Windows builds were fetched from the site qemu.org's download page
points to, SHA-512-verified against their sidecars, and *extracted* with 7-Zip
into `E:\qemu-versions\` (no installer executed, no PATH change; the winget
11.0.50 is untouched); `launch-qhv-tcg.ps1 -QemuPath` drives them with the same
stamped instrument.

**Tooling lessons, because they cost real time:** `pgrep -f`/`pkill -f`
match the calling shell's own command line when the pattern appears in it
(three separate self-matches: a "still running" false positive that hid a
failed build for 13 minutes, a `pkill` that killed its own ssh session, and
one false negative from `pgrep`'s 15-character `comm` truncation that hid a
QEMU orphan holding the disk lock). Use `pgrep -f '[b]uild-…'` and check for
side effects (files, exit-code sentinels) rather than process tables. The
Bash-tool heredoc also mangles backslashes even with a quoted delimiter —
scripts with line continuations were written via the file tool instead.

**Diagnostic collector for the KVM/NISV investigation (2026-09-09, same day).** A
user-supplied four-stage investigation plan (inspect → decode → classify →
report; read-only, no package installs, no QNX binaries copied, every test
marked PASS/FAIL/BLOCKED/NOT APPLICABLE/NOT RUN, facts kept apart from
hypotheses) was implemented as
`scripts/diagnose-gicv3-nisv.sh` (withdrawn from the public tree on 2026-09-27 with its reports, held locally) and run
twice: an unedited script run
(`results/gicv3-nisv-debug/20260909T100704Z`, held locally)
and a report run whose thin sections were rewritten by hand and then put
through a second, adversarial honesty review
(`results/gicv3-nisv-debug/20260909T101030Z`, held locally). Its findings
are held locally (NC QDL v7 4.6(i)). Two housekeeping decisions made while
landing it: the objdump windows of the SDP-shipped startup that the report
run had produced were replaced by fact summaries before commit (the repo has
withheld such listings since 2026-07-28; QDL v7 §4.6(c) remains an open
owner decision), and the `a1.metal` log header's EC2 instance id (instance
terminated 2026-07-29) was redacted to honour the CLAUDE.md secrets rule —
it stays in git history. Six intermediate build/review runs of the script
were parked outside the repo rather than deleted.

**A board safety rule, from M0's `hang` test the same evening.** The shim —
this project's own code; no QNX instruction ran — was built in `hang` mode
(print, then `wfi` forever with nothing petting WDT0) to test whether the
watchdog systemd arms at two minutes brings the board back unattended after
`systemctl kexec`. It did not: the board came back only when the owner pulled
the power, and after the cold power cycle `/sys/fs/pstore` came back
completely empty. So a hang costs both the evidence and a trip to the board.
The rule for M1 onward: a startup that fails into a wait loop is the *worst*
available outcome, anything resembling a spin needs a bounded deadline with a
reset at the end of it, and the remotely switchable mains socket is the only
thing that restores the recovery path the watchdog was assumed to provide.
`m0-hang-watchdog.md` (held locally).


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

## 2026-09-08 — QHV leg made host-portable: the twin gets a comparison on the *hypervisor* topology

An architecture pass, not a feature. Reviewing
[digital-twin-design.md](digital-twin-design.md) §1 against what the repo
actually does turned up four claims that were no longer true, three of them in
the **invariant** set the document itself defines as "anything that differs
between twin sides in those rows is a bug":

1. *"QEMU acceleration: cloud = tcg; Orin = `-enable-kvm` (KVM works on
   A78AE)"* — not how the leg runs: the `qnx-safety-vm` leg runs **TCG on
   both sides**.
2. *"Orin is a heterogeneous QNX↔Linux exchange … bridged under **KVM**"*
   (§4) — same error.
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
That is a hard architectural requirement. For once TCG-on-both is genuine
symmetry. See [digital-twin-design.md](digital-twin-design.md) §1a.

**Built:** [`scripts/orin/launch-qhv-on-orin-tcg.sh`](../scripts/orin/launch-qhv-on-orin-tcg.sh)
(new), `-Runs` / `-StopOnGuestBanner` added to
[`scripts/launch-qhv-tcg.ps1`](../scripts/launch-qhv-tcg.ps1) (default
behaviour unchanged), and
[`scripts/twin/sync-qhv.sh`](../scripts/twin/sync-qhv.sh) to stage the images
with the checksum invariant enforced on arrival. `sync.sh` was left alone: it
targets `qnx-safety-vm/output`, demands a `CLOUD_RUNTIME_HOST` that no longer
exists for this leg, and uses `rsync`, which is absent from Git Bash on the
Windows build host — i.e. it cannot run from where the images now live.

**The boot check's markers.** The curation header of a sample boot log
(`qhv-tcg-host-and-guest-boot.log`, held locally) and the original launch
script told the reader to look for a host banner as well as the guest's. The
check now uses three markers instead: `=== AUTO-START QNX GUEST UNDER
QVM` (host reached post_start), `=== launching qvm @g2.conf` (hypervisor
invoked), and the guest banner (guest came up across EL2/EL1). They fail
distinguishably, which a single-banner check did not.

The Windows half's boot-time series is held locally (NC QDL v7 4.6(i)). The
Orin half was not run that day: the board was unreachable — `ssh` to
`<orin-ip>` timed out on port 22.

One measurement detail: the host's `post_start.custom` holds a hard-coded
`sleep 90` boot-grace. On a slower host a banner past 90 s would change the
interleaving, so any run reporting much more than that should be inspected,
not plotted.

---

## 2026-07-28 — ADR-002 RQ-2 guest-side shmem probe: the code and the staging convention

Takes up the concrete next step the entry below left open: a `qnx-guest`
process attaching to the same named shared-memory region
(`phase2-rq2-probe`) the `qnx-qhv` host creates and attaches, and a byte
exchange in both directions. New pieces: a `vdev shmem`
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

The name write into the factory page's virtual-register file (and,
defensively, the shared-data read/write) uses explicit byte-at-a-time
volatile stores instead of a block copy. **Not attempted, explicitly:** the
interrupt/notify-driven path (`InterruptAttach()` +
`guest_shm_control.notify`) — the vdev's intr line's edge/level and masking
semantics were not confirmed in the time available, and a wrong guess risks
an interrupt storm hanging the guest under TCG with no fast iteration loop
to debug it; `factory->vector` (`43`, matching `gic:43`) is read and logged
for a future attempt. Per the project's "diagnostic variant, staged,
reverted after use" convention (same as the host-only probe), the manual
`g2.conf`/`post_start.custom` edits were never committed to `scripts/qhv/`
— `scripts/build-qhv.bat` was re-run afterward to regenerate both
gitignored build trees from the clean committed sources (verified via
`diff` showing no drift). The boot logs are held locally (NC QDL v7 4.6(i)).
See
[ipc-test/qnx-guest-shmem-probe/README.md](../ipc-test/qnx-guest-shmem-probe/README.md)
for the full account.

---

## 2026-07-28 — ADR-002 RQ-2 host<->guest shmem: what the documentation and the shipped headers say

Took up the crux unknown behind ADR-002's RQ-2 stretch transport (see
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
3. **A host-only probe, same day:** a new, minimal **host-only**
   program (`ipc-test/qnx-host-shmem-probe/probe.c`, no `qvm`/`g2.conf`
   involvement at all) calling `hyp_shm_create()` +
   `hyp_shm_attach_ext()` was run on the `qnx-qhv` host image; its log is
   held locally (NC QDL v7 4.6(i)). See
   [ipc-test/qnx-host-shmem-probe/README.md](../ipc-test/qnx-host-shmem-probe/README.md).

The guest-side half (a `qnx-guest` process attaching to the *same* named
region via `qvm/guest_shm.h`'s raw-MMIO factory-page protocol, and a full
host<->guest byte exchange) was **deliberately not attempted this
session** — a real, bounded time-box decision, not a blocker found. The
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

## 2026-07-28 — Kick-safe sentinel frame implemented

Design: a reserved `seq` value, `FRAME_SENTINEL_SEQ = UINT64_MAX`
(`ipc-test/common/frame.h`), that both ends can treat as a no-op —
`qnx-server` needs **zero** code changes (it already echoes any frame
verbatim regardless of `seq`); only the initiator (`qnx-host-client`)
needs new logic. On a read timeout, `sentinel_recover()`
(`ipc-test/qnx-host-client/client.c`) writes a **sentinel**, not a resend
of the real in-flight frame, so a "wake-up" write after a timeout cannot
leave a corrupting duplicate in the application frame stream (a stale
duplicate REAL echo would corrupt the next iteration's alignment; a stale
sentinel echo is inert and simply discarded). Bounded by
`SENTINEL_MAX_ROUNDS=5` / `SENTINEL_READS_PER_ROUND=3` so a genuinely dead
link still fails loudly rather than hanging forever. A sentinel's trailing
echo is swept up by the pre-existing `cio_drain_stray()` call at the top of
the next iteration, and recovered iterations are excluded from timing
statistics.

It was exercised the same day on four boots: one at the committed
15-timed/5-warm-up configuration and three at a temporarily raised
300-timed/5-warm-up configuration (**never committed** — the
`scripts/qhv/post_start.custom` edit was reverted in full immediately
after, verified via `git diff` showing zero changes, matching this
project's established diagnostic-variant convention). The logs are held
locally (NC QDL v7 4.6(i)). Full account in
[ipc-test/qnx-host-client/README.md](../ipc-test/qnx-host-client/README.md)'s
new "Sentinel-kick recovery" section.

**Scope:** the sentinel changes how the client recovers from a read
timeout; it changes nothing inside `qvm`. The committed benchmark
configuration (`scripts/qhv/post_start.custom`'s 5 warm-up + 15 timed
invocation) is **unchanged** by this session. Whether to raise the
committed run size is a follow-up decision, left open rather than actioned
unilaterally in this implementation pass.

---

## 2026-07-28 — an interactive QHV launcher for the virtio-console investigation

New tooling for the Phase 2 cloud-leg virtio-console investigation:
[`scripts/qhv/launch-qhv-tcg-interactive.ps1`](../scripts/qhv/launch-qhv-tcg-interactive.ps1)
boots the QHV host with its serial console on a TCP socket instead of a
plain log file, so commands can be injected into the live root shell
**while `qnx-host-client` is still running in the background** (a
diagnostic-only variant of `post_start.custom` backgrounds the client loop
so `post_startup.sh` reaches the login-less shell — never committed;
reverted after use). A resend-on-timeout client change was tried with it
and **reverted in full** (`ipc-test/qnx-host-client/client.c` and
`scripts/qhv/post_start.custom` both restored to the exact committed
baseline via `git checkout --`) — evaluated and rejected, not shipped. The
session's findings and logs are held locally (NC QDL v7 4.6(i)).

---

## 2026-07-28 — Phase 3 IPC on the Orin: a TCP echo server, a native client, and a rebuilt IFS

For [`docs/orin-port.md`](orin-port.md) steps 3, 5, and 6, a
QNX-guest↔native-Linux TCP exchange on the Jetson Orin Nano. New source,
both written this pass:
[`ipc-test/qnx-server-net/server.c`](../ipc-test/qnx-server-net/server.c)
(QNX guest, `qcc -Vgcc_ntoaarch64le`, TCP echo on `:7000`; Phase-2's
`qnx-server/` is untouched — different transport, virtio-console, cloud
leg only) and
[`ipc-test/linux-client/client.c`](../ipc-test/linux-client/client.c)
(native L4T, `gcc 11.4.0`, `clock_gettime(CLOCK_MONOTONIC)`-timed, zero
warnings on both builds). Getting the server auto-started with a static
IP needed a `qnx-safety-vm` **rebuild** (`mkqnximage
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
fixes it. The guest is launched by the new
[`scripts/orin/launch-qnx-on-orin-tcg.sh`](../scripts/orin/launch-qnx-on-orin-tcg.sh)
(TCG + `tap-qnx` + the virtio-rng device). The runs' logs and CSV are held
locally (NC QDL v7 4.6(i)). **Honest gaps left open:**
this is a rebuilt IFS, not the untouched Phase-1 one (the new code is
in-scope/additive per this task's brief, but it is a real deviation from
a strict "zero IFS changes" portability claim); `docs/orin-port.md` step 7
(`scripts/twin/diff-results.sh`) runs without crashing but is not a
meaningful sanity check — it assumes a `# ifs_sha256:`-comment-header +
`metric,p50_us,...`-body schema that neither this CSV nor the existing
cloud CSV actually use, so it silently misreads the first data row as a
header and prints nonsense deltas; this is a pre-existing Phase-4 tooling
gap (predates this entry), not something fixed here.

---

## 2026-07-28 — the Orin TCG launch line: virtio blk, net and rng in the order the image expects

Comparing the plain `qnx-safety-vm` build's `startup.sh` (`devb-virtio ...
smem=0xa003e00,irq=79` and `random ... devr-virtio.so:mem=0xa003a00`)
against `C:\Users\<user>\qnx800\host\common\mkqnximage\qemu\runimage` (the
canonical qemu launch script `mkqnximage --type=qemu` itself ships) shows
that this build assumes QEMU is invoked with exactly three `-device`
entries in a fixed order — `virtio-blk-device`, `virtio-net-device`,
`virtio-rng-device` — because QEMU's `virt` machine assigns its fixed
virtio-mmio slots to `-device` args strictly in command-line order; slot 1
(`0xa003e00`) → disk, slot 3 (`0xa003a00`) → rng. The Orin TCG boot
command used until then had no `-device` entries beyond the disk. **The
launch line now (QEMU command line only — no IFS rebuild, no custom
startup snippet):** add `-netdev user,id=n0 -device
virtio-net-device,netdev=n0,mac=...` and `-object
rng-random,filename=/dev/urandom,id=rng0 -device
virtio-rng-device,rng=rng0` in that order, after the existing
`-device virtio-blk-device,drive=drv0`. The boot logs are held locally
(NC QDL v7 4.6(i)). `-netdev user` (SLIRP) is not the `br0`/tap bridge
[`docs/orin-port.md`](orin-port.md) step 3 needs for the native-L4T IPC
test against a real bridge interface.

---

## 2026-07-28 — Phase 2 console IPC: the wiring and the code

The qvm/TCG console wiring for the Phase 2 cloud-leg IPC benchmark
([`../ipc-test/qnx-host-client/README.md`](../ipc-test/qnx-host-client/README.md)),
established via a live interactive host shell (TCP-forwarded `qvm` console).
(**2026-09-20 note on the name:** "cloud leg" is this project's label
for architecture A1, not a statement about where it ran. Every figure in this
entry was produced on the local Windows PC under QEMU TCG. No IPC, latency or
throughput number has ever been taken on a cloud host.) The run's log, figures
and CSV are held locally (NC QDL v7 4.6(i)).

- **Host side.** `vdev virtio-console` takes `hostdev /dev/ptyp0`, a
  `devc-pty` master already running on the image, which `qvm` opens; the
  paired slave `/dev/ttyp0` is what `qnx-host-client` opens — not the
  `/dev/qhv/con1` placeholder in the milestone-1 proposal.
- **Guest side.** The guest starts `devc-virtio -E 0x20000000,42` (matching
  the vdev's `loc`/`intr`), which creates `/dev/vcon2` (`/dev/vcon1` is
  already pl011's).
- **Raw mode on both ends.** Both `/dev/ttyp0` and `/dev/vcon2` default to
  line-buffered "cooked" mode, in which a binary frame with no `\n` byte can
  sit unflushed; both ends switch to raw mode with `cfmakeraw`/`tcsetattr`
  (`ipc-test/common/console_io.h`).
- **A priming frame.** A throwaway "priming" frame + drain precede the timed
  loop.
- **Transcription.** The new `scripts/qhv/extract-ipc-result.sh` transcribes
  the result from the boot log into a CSV (the client cannot write that file
  itself — it runs inside the QNX host image's own filesystem, with no path
  back to this checkout on this leg).
- **Pacing.** A 20 ms inter-iteration gap separates exchanges, outside the
  RTT sample window.

---

## 2026-06-11 — Phase-1 gate: full FuSa + Cyber V-model cycle on the as-built QHV boundary (Analysis → Design → Implementation → Verification)

Ran the Phase-1 phase-gate review against the *as-built* QHV/TCG boundary —
not the original KVM dual-VM premise, which the QHV pull-forward falsified.
Both safety and security disciplines completed a full V-model loop and
pair-reviewed the cyber-FuSa interaction. **Analysis** appended dated
gate addenda: FuSa added 9 new failure modes (NF-1…NF-9) and deferred ~20
KVM/br0/Linux-guest rows to Phase 2/3
([`fusa/phase1-cloud-bringup-fmea.md`](fusa/phase1-cloud-bringup-fmea.md));
Cyber added 6 threats (T29–T34) + 6 assets with `qvm` as the new TCB root
([`tara/phase1-cloud-tara.md`](tara/phase1-cloud-tara.md)). **Design** wrote
8 TSRs ([`fusa/phase1-gate-safety-concept.md`](fusa/phase1-gate-safety-concept.md))
and 9 TCRs ([`cyber/phase1-gate-cybersecurity-concept.md`](cyber/phase1-gate-cybersecurity-concept.md));
the shared entropy item (NF-5 ≡ T31) is owned by Cyber as
`TCR-ENT-001` and cited by FuSa as a precondition (`AoU-ENTROPY`), not
double-specified. **Implementation** built 8 host-side gate scripts under
`scripts/qhv/` (bring-up verifier, entropy fail-secure gate, g2.conf
validator, per-extent artefact manifest) + a build-host package-completeness
assertion in `build-qnx-ifs.{bat,sh}`. **Verification** *ran* them against
the captured boot log; the manifest catches tamper/truncation/missing-descriptor
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

## 2026-06-11 — Phase-7 pull-forward: the QNX Hypervisor build path under QEMU-TCG

Brought the Phase-7 QHV exploration forward, entirely on the local Windows
build host — no AWS, no KVM.
Chain of findings: (1) AWS non-metal Graviton exposes **no `/dev/kvm`** (proven
empirically on a t4g.small probe — EL2 is not passed through by Nitro), so any
hardware-accelerated hypervisor (KVM *or* QHV) needs `*.metal` or real silicon;
the accessible path to *demonstrate* QHV is QEMU-TCG emulating an EL2-capable
CPU. (2) SDP 8.0.4 already ships the QHV host: `qvm` aarch64 binary
(`target/qnx/aarch64le/sbin/qvm`), `libhyp`, and `target.hypervisor.core` are
installed. (3) Official build path is mkqnximage: `--type=qvm` builds the guest,
`--type=qemu --qvm=yes --guest=<dir>` builds the host that embeds it under
`/data/hypervisor/`. (4) Boot under `qemu-system-aarch64 -machine
virt,virtualization=on -cpu max -accel tcg` so that QHV's `el2-host`/VHE can come up.
The guest start is baked into the image — a no-network qvm config auto-started via a
custom `post_start.custom` snippet — rather than driven over the TCG serial console
interactively. The boot log is held locally (NC QDL v7 4.6(i)). Note this supersedes
the earlier Track-A framing where the cloud leg ran a QNX *Neutrino* guest under
QEMU/**KVM** on c7g.large — that KVM-on-cloud assumption is now falsified (see finding
chain above). The hardware-timed route became the native port (ADR-003).

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
narrative — **2026-09-20: Track A's Graviton half never happened.** ADR-002
falsified it in 2026-06 (non-metal Graviton exposes no `/dev/kvm`), the
dual-VM-over-bridge topology was never built on any cloud host, and every
figure labelled "cloud" came from the local Windows PC. Track A as executed is
Windows-PC TCG plus the Orin. **Track B never happened at all:** no QNX-on-Graviton AMI was ever
launched, no application-layer work ran on one, and no IPC, latency or throughput figure has ever
been taken on any cloud host. As planned on 2026-06-10, **Track B** was to add the QNX-on-Graviton
AMI as a low-friction *single* QNX target for the application layer — native IPC / resource-manager / scheduling
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
> [`fusa/phase1-cloud-bringup-fmea.md`](fusa/phase1-cloud-bringup-fmea.md).
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
> **2026-09-11:** superseded. Earlier twin diffs (2026-07-28, and the release-aligned QHV pair of 2026-09-09)
> are architecture-version history under the 2026-09-11 decision, and the twin diff runs once, in the v1 campaign
> ([plan freeze section](orin-native-port-plan.md#architecture-versions-and-the-measurement-freeze-decided-2026-09-11)).

---

## Phase 3 — ~~TBD:~~ hardware twin port to Jetson Orin Nano

> ~~_Stub. Filled in after the same `mkqnximage --type=qemu --arch=aarch64le`
> IFS has been booted on QEMU-on-Orin under L4T. Expected contents:
> (a) does the unmodified IFS boot? (b) JetPack 6 KVM availability;
> (c) RAM headroom on 8 GB; (d) any GICv3 / A78AE quirks._~~
>
> **2026-09-11:** superseded by the 2026-07-28 entries above. The bridged IPC ran on a rebuilt IFS. Phase 3b, the
> native port, began on 2026-09-09.

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
`a1.metal` KVM is present.
The QNX Everywhere NCEULA covers personal/portfolio/demo use but
forbids redistributing QNX binaries — so the repo ships scripts and
logs only, never IFS images.

Full write-up: [bsp-selection.md](bsp-selection.md).
