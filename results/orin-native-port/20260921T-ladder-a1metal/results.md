# Attribution ladder — AWS `a1.metal`, A6 — 2026-09-21

The second host. Same ladder, same client, same server source, same sizing
(n = 1000, 200 warm-up, 2 ms spacing, k = 12, interleaved) — run to answer one
question: **is the 126 µs guest crossing measured on the Orin a property of that
board, or of "QNX SDP 8.0 as a KVM guest" as an arrangement?**

Host: `a1.metal`, Graviton1 / Annapurna, 16× Cortex-A72, Ubuntu 22.04
(`ami-02153ae97d7504246`), kernel `6.8.0-1063-aws`, QEMU 6.2.0 from the distro,
QNX guest under `-enable-kvm` on `br0`/`tap-qnx`. Full configuration in
[`raw/stamp.json`](raw/stamp.json).

## Results

| arm | path | Orin (A78AE) | a1.metal (A72) |
|---|---|---|---|
| **A** loopback | client → `127.0.0.1` | 53.0 µs | **61.4 µs** |
| **B** bridge | client → `br0` → veth → netns | 55.8 µs | **64.5 µs** |
| **C** null | client → guest, **echo** server | *not run* | **224.3 µs** |
| **D** guest | client → guest, **monitor** | 181.8 µs | **224.3 µs** |

| derived | Orin | a1.metal |
|---|---|---|
| instrument floor (A) | 53.0 µs | 61.4 µs |
| bridge (B − A) | 2.8 µs | **3.1 µs** |
| guest crossing (D − B) | 126.0 µs | **159.7 µs** |
| — monitor's own work (D − C) | not measured | **−0.04 µs** |
| — transport (C − B) | not measured | **159.8 µs** |
| total (D) | 181.8 µs | 224.3 µs |

## What this shows

**The decomposition reproduces on a different vendor, core generation and core
count.** The shape is the same: a small instrument floor, a bridge cost of about
3 µs, and a guest crossing that dominates. The bridge is 2.8 µs against 3.1 µs —
for practical purposes the same number on both hosts.

**The monitor's own work inside the guest is not measurable.** Arm C, a verbatim
echo server on `:7000`, and arm D, the safety monitor on `:7100`, land 0.04 µs
apart — 0.02% of the crossing. Checked before reporting: the two arms' sample
arrays are different data, and their per-round medians differ from each other.
So the crossing is **transport**, not server-side work: the monitor's read,
verdict and write are lost in the noise of tap → virtio-net → `io-sock` →
scheduler.

**The crossing scales roughly with host CPU speed rather than being a fixed
cost.** a1.metal's instrument floor is 16% higher and its crossing 27% higher,
and the crossing-to-instrument ratio is close on both hosts — 2.38 on the Orin,
2.60 here. That is consistent with a cost dominated by host-side CPU work rather
than by a fixed hardware or hypervisor latency. **Consistent with, not proof of**:
two hosts is two points.

**The tails differ in the opposite direction from the medians.** The Orin has the
better median (181.8 vs 224.3 µs) but a much worse p99 (438.5 vs 246.5 µs), and
its between-round spread is 2–6% against 1.1–1.4% here. A datacentre host with no
DVFS and no thermal headroom problem is simply steadier than a passively cooled
dev kit.

## What this does not show

**It is not a one-variable comparison, and cannot be read as one.** It compares
two *host bundles* — the position `digital-twin-design.md` §1a already argues.
Recorded and not equalised: A72 (ARMv8.0, no LSE atomics) against A78AE
(ARMv8.2); an NVIDIA vendor kernel with CFS against Canonical's 6.8 with EEVDF;
software Spectre-v2 workarounds on A72 against hardware mitigation on A78AE;
5 of 16 cores committed here against 5 of 6 on the Orin; different shared-cache
topology at the same literal core numbers; ENA interrupts landing on host cores;
and Nitro underneath "bare metal". Any of these could move a 27% difference.

**The power regimes are different, and were not made the same.** The Orin ran
with the governor pinned to `performance`. `a1.metal` exposes **no cpufreq and no
cpuidle at all** — recorded as `"governor_state": "absent"` in the stamp rather
than silently skipped, which is what the previous version of the script would
have done.

**The Orin half is less well specified than this one.** That run has no stamp:
no QEMU version, no launch line, no image hashes, no confirmation the pinning
applied ([its record](../20260921T-ladder/results.md)). This one has all of that.
The comparison is therefore between a fully specified host and a partially
specified one.

**Arm C was measured here, not on the Orin.** The finding that the monitor's own
work is negligible is an `a1.metal` result. It makes the same very likely on the
Orin, but the Orin's 126 µs still formally contains an unmeasured monitor
component.

**One run per host.** No isolation, freedom-from-interference, contention or
determinism claim follows from any of this. It is round-trip latency under a
light load.

## Session

Launched 10:10:37Z, terminated 10:23Z — about 13 minutes billed, self-terminating
with a 90-minute hard stop that was not needed. Teardown verified: 0
non-terminated instances, 0 volumes, 0 elastic IPs, 0 snapshots, 0 network
interfaces. Two unrelated leftovers from earlier exam practice were removed in
the same session: an unused security group with SSH and HTTP open to `0.0.0.0/0`,
and its key pair.

Redaction ran **on the instance**, before anything was fetched
(`orin-native/gpu-concurrency/redact-aws.sh`). Verified afterwards on what
arrived: no AWS id shapes, no account-shaped tokens once digit-run false
positives inside the float arrays are excluded, the only addresses `0.0.0.0` and
`192.168.100.1`, the only MAC the documented guest one. One cosmetic
over-mask: the QEMU version string reads `2<user>6.31` because the instance's
username is a substring of the Debian package version. Over-masking is the safe
direction; it is noted rather than fixed after the fact.
