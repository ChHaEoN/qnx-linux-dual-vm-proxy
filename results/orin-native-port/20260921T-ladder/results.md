# Attribution ladder — Jetson Orin Nano, A6 — 2026-09-21

The decomposition of A6's published cross-partition round trip. One client
program, one server program, three paths; only the path changes.

| arm | path | k | p50 (median of round medians) |
|---|---|---|---|
| **A** loopback | client → `127.0.0.1` | 12 | **53.0 µs** |
| **B** bridge | client → `br0` → veth → netns | 12 | **55.8 µs** |
| **D** guest | client → `br0` → tap → virtio-net → QNX guest | 12 | **181.8 µs** |

Derived, by subtraction:

| quantity | value | how |
|---|---|---|
| instrument floor | **53.0 µs** | A, measured directly |
| bridge datapath | **2.8 µs** | B − A |
| **guest crossing** | **126.0 µs** | D − B |
| total | **181.8 µs** | D, measured directly |

Re-derived on every push: `scripts/ci/claims_gate.py` claims C21–C24 read the
figures out of README and recompute them from `raw/`, asserting k = 12.

`n` = 1000 timed samples per round, 200 warm-up discarded, 2 ms spacing, port
7100, arms interleaved so drift hits all three equally. That sizing is owner
decision **OD11** ([the plan](../../../docs/orin-native-port-plan.md)); this run
predates the decision and happens to match it, because the decision was taken
from this run's own variance data.

Script: `orin-native/gpu-concurrency/run-ladder.sh`,
sha256 `05f38c6838444780d83d97cd75045fda4b9721c6f4a47fc911616c793024b84c`.

---

## What this does not show

**Arm C was not run.** [measurement-design.md](../../../docs/measurement-design.md)
§3.2 specifies four arms; the fourth is a guest running a *null* server that
replies without judging the frame. Without it, the 126 µs attributed to "the
crossing" is the crossing **plus the monitor's own read, verdict and write
work** inside the guest. The split between those two is not measured. Arm C is
the single cheapest thing that would sharpen this result.

**Both derived rows are differences, not measurements.** Nothing was ever
instrumented at the bridge or at the partition boundary. Subtracting arm
medians assumes the arms share an additive floor, which is a model, not an
observation.

**No isolation or freedom-from-interference claim follows.** This is one
round-trip latency under a light load, not a contention or determinism result.

**Between-round variation is the reason for k.** Arm A's twelve round-medians
span 6.4%, arm B 4.1%, arm D 2.0%. A single round of any arm would have been a
worse estimate than this table by roughly that much.

---

## Provenance not captured, and not reconstructable

The 36 arm files are the complete numeric record. **The run's configuration
record was never written**, and the files were recovered from the machine's
temporary directory on 2026-09-21 and staged here after the fact. The following
were not captured at run time and are not being reconstructed from memory:

- `probe.log`, `monitor-host.log`, `monitor-ns.log`
- the governor value before and after, though the script pins `performance` and
  restores — so this is what the script *does*, not what was *observed*
- the QEMU version and the guest launch line
- the IFS and guest-disk sha256
- confirmation that the pinning map (QEMU on cores 0–2, monitors on 3, probe on
  4) was actually applied
- SoC temperature, which on this board throttles

Consequence, stated plainly: **this run cannot be exactly reproduced from the
repo**, and a second host compared against it is being compared against a
partially specified configuration. Any such comparison must say so. The fix is
in the script, not in this record — a run stamp is owed before the next ladder,
and that is a prerequisite for the a1.metal arm rather than a nice-to-have.

## Files

`raw/lat-<arm>_r<round>.json`, 36 files, one per (arm, round). Each carries the
full `samples_ms` array and a `summary` block. No hostnames, addresses or MACs
appear in any of them — checked, not assumed.
