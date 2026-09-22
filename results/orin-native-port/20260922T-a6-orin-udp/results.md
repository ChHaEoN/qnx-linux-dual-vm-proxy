# A6 on the Orin — the attribution ladder over UDP beside TCP — 2026-09-22

The first run of OD12's "other IPC paths across the same boundary": the four rungs
of the attribution ladder over **UDP**, beside the same four rungs over **TCP**, in
the same run on the same guest boot, and paired within rounds. Jetson Orin Nano
(Tegra234, 6× Cortex-A78AE), QNX SDP 8.0 as a KVM guest beside L4T.

| rung | TCP arm (port) | UDP arm (port) | path |
|---|---|---|---|
| A | A-loopback (7100) | A-udp (7101) | probe → monitor on the same Linux host, loopback |
| B | B-bridge (7100) | B-udp (7101) | probe → monitor in a network namespace behind `br0` |
| C | C-null (7000) | C-udp (7001) | probe → the guest's echo server, verbatim |
| D | D-guest (7100) | D-udp (7101) | probe → the guest's safety monitor (the published path) |

k = 12 rounds, n = 1000 timed samples per arm and round, 200 warm-up discarded,
2 ms spacing; governor pinned to `performance` and deep idle state `c7` disabled
(`CSTATE=shallow`), both restored and verified; QEMU pinned as a set to cores 0–2,
monitor on 3, probe on 4 (`SCHED_OTHER` on core 4 in all 96 files, by the probe's
own report). Which transport went first alternated by round. Every one of the 96
files passed the gate — including each file's own `proto` against its arm.

**The guest** is a new image, `ifs-udp.bin` (sha256 `853de923…`), and a new boot:
QEMU pid 66473, started 2026-09-22T07:52:12Z, disk `disk-qemu` (sha256 `f326b792…`)
under `-snapshot` — all recorded in the stamp from the running process itself. It
is the campaigns' `ifs-demo2.bin` with two start lines added: every file in it is
byte-identical except the two servers (which gained a UDP mode), the startup script,
the embedded build file and the build date. The TCP servers' code paths are
unchanged in behaviour, but they are new binaries on a new boot, so **no figure here
pairs with an earlier run**. Build file:
[`ipc-test/qnx-safety-monitor/ifs-udp.build`](../../../ipc-test/qnx-safety-monitor/ifs-udp.build);
the boot console, with all four servers' listening lines (the UDP echo's is
interleaved with the guest's banner, `…:7001/u` + `QNX…` + `d…`), is in
[`ladder/guest-console.log`](ladder/guest-console.log).

**Provenance.** Tooling as committed in `1d51b5f`; the stamp's script, library and
probe hashes name files of that commit. The host-side `monitor-native` is a
post-OD12 build whose UDP mode the run checked at start (its listening banner on
both ports); the stamp holds the binary's sha256 (`0bcb2a94…`), not the source it
was built from. Result JSONs copied byte-for-byte; logs and stamp redacted at
capture.

**What else this boot served.** Before the recorded run, the same guest boot took
the smoke checks — on the console, one-frame sessions to both servers and a
550-frame session to the monitor — and a K = 2 dry run of the same `UDP=1` ladder,
which completed clean. That is why the console shows 14 sessions of 1200 frames on
each TCP server against k = 12, and three zero-frame sessions, which are the
ladder's connect-and-close reachability checks. Nothing from the smoke checks or
the dry run is in `raw/`.

**Every difference below is paired**: the median over rounds of (arm − reference)
in the same round, with the min–max band and how many of the 12 rounds lie above
zero. The two per-arm levels in §1 and the maxima in §3 are not differences and are
labelled where they appear.

---

## 1. UDP is faster than TCP on every rung, in every round

| p50, UDP rung − TCP rung | median | band | rounds above 0 |
|---|---|---|---|
| A: loopback, both ends Linux | **−12.3 µs** | [−13.4, −10.5] | 0/12 |
| B: through the bridge, both ends Linux | **−11.5 µs** | [−13.2, −10.5] | 0/12 |
| C: to the guest's echo server | **−20.7 µs** | [−21.8, −16.2] | 0/12 |
| D: to the guest's safety monitor | **−20.0 µs** | [−23.0, −18.2] | 0/12 |

As levels rather than differences: the median over the 12 rounds of each round's
p50 is 180.0 µs for the published path over TCP and 160.3 µs over UDP, on this boot.

## 2. The guest crossing is 8 µs cheaper over UDP — and what that does not split

| p50, paired | TCP | UDP |
|---|---|---|
| bridge, B − A | +3.8 µs [+0.8, +5.1] | +4.4 µs [+2.5, +5.1] |
| guest crossing, D − B | +123.5 µs [+121.9, +126.9] | **+115.3 µs** [+112.8, +118.3] |
| monitor's own work, D − C | +0.4 µs [−2.1, +2.2] | −0.6 µs [−3.1, +2.5] |

The crossing's own difference, (D − B) over UDP minus (D − B) over TCP, is
**−8.4 µs [−12.0, −5.0], lower in 12 of 12 rounds**.

**What this does and does not attribute.** On rungs A and B both ends are Linux
stacks; on C and D the far end is the QNX guest's `io-sock` behind virtio-net. So
the 11–12 µs on A and B is Linux-to-Linux, client and server together. The 8.4 µs
is a **net** figure: the TCP-to-UDP change on rung D's far side — QNX's `io-sock`,
the tap, QEMU's userspace virtio-net, KVM's interrupt injection and the vCPU's wake
— minus the same change on rung B's far side, the Linux server in its namespace
and its veth. Neither side's own change is resolved here, nor how the guest side's
divides between the QNX stack and the virtio/tap path; that would need tracing on
both sides, which the measurement design does not propose. The monitor's own work
is indistinguishable from zero on both transports — the verdict logic is shared
code, and costs nothing measurable against the transport.

## 3. The tail does not resolve a transport difference

At p99, every UDP − TCP difference has a band spanning zero (e.g. D: −19.9 µs
[−425.5, +382.5], 4 of 12 above). Twelve rounds settle the median here, not the
tail. The largest single samples, each arm's maximum over its 12 rounds, were on
the host-only rung A (9.6 ms TCP, 10.4 ms UDP), not on the guest rungs — a maximum
is the largest value observed, never a bound.

---

## Loss, and the rule this run used

In the recorded run no arm stalled or lost a reply: all 96 arm files are complete,
n = 1000 each. The
run used the first-run loss rule recorded under OD12 — no reply within the probe's
10 s timeout is a stall, and the ladder refuses a stall — so a single lost datagram
would have stopped it. None did. That is not a loss rate: at 12 000 timed exchanges
per UDP rung it says only that no reply was lost here, on an unloaded path.

## What this does not show

- **How the ~8 µs crossing difference divides** between the QNX stack and the
  virtio/tap path (§2).
- **Anything under load.** This is the unloaded ladder; the interference and
  saturation arms were not re-run over UDP.
- **A UDP loss rate**, or behaviour when a datagram is lost — the rule in force
  would have stopped the run.
- **Comparability with earlier figures.** New image, new boot, new server binaries:
  the TCP rungs here (D − B +123.5 µs) are not a re-measurement of the published
  126 µs, which ran before the idle-state control and on an earlier boot. Nor do
  they match the c7-off ladder of 2026-09-21 under the same control and placement,
  which put the TCP crossing at +119.0 µs [+117.3, +120.7]: a ~4.5 µs shift between
  runs, in which the new image, the new boot and the rebuilt host-side monitor
  (rung B's far end) cannot be separated. That is why
  the UDP − TCP figures stand only as pairings within this run.
- **Reproducibility across boots or days**: one boot.
- **Any middleware.** UDP here carries the project's own 64-byte frame; SOME/IP or
  DDS over the same path would add their own layers (OD12 lists a SOME/IP arm as
  proposed, not decided).
- **Any real-time, isolation or safety property.** Unchanged from every A6 record.

## Files

`ladder/raw/` — `lat-<arm>_r<k>.json` per arm and round (summary incl. `proto` and
the probe's scheduling report; samples sorted and in arrival order), `stamp.json`
(incl. guest image and disk sha256, QEMU pid and start), `order.log`, `probe.log`,
the four host-side monitor logs. `ladder/run.log` — the script's output, with the
summary and the paired UDP/TCP table. `ladder/guest-console.log` and
`ladder/guest-launch.log` — the new guest's boot, redacted.
