# A6 on the Orin — the guest's socket rungs rise 34–38 µs with the virtio console driver, and QEMU's main thread does 58 µs more per exchange — 2026-09-22

The notified-shm ladder
([20260922T-a6-orin-kick](../20260922T-a6-orin-kick/results.md), §5) found the
guest's socket rungs 32–38 µs above the two earlier runs that day. Its host-only
rungs were about the same as the shm run's, and 7–8 µs above the UDP run's. The
`a1.metal` replication
([20260922T-a6-a1metal-kick](../20260922T-a6-a1metal-kick/results.md), §4) found
about 76 µs across a larger set of changes. Neither record could separate the
changes. This one does it for the Orin, in two sessions of alternating guest boots.

**Answer.** What raises the guest's socket rungs is what the notified image adds
over the shm image. Every guest socket rung rises by the same order:
- TCP to the monitor and TCP to the echo server: 34–38 µs;
- UDP: 31–36 µs;
- the crossing itself: 34–38 µs.

Two things are ruled out:
- the ivshmem and console devices with the guest's ivshmem server, as long as the
  guest ignores them;
- the per-arm KVM snapshots.

Within the image, neither shm monitor matters. What remains is what N adds over S:
- `devc-virtio`, the SDP's virtio console driver, which brings QEMU's
  virtio-serial device to life. It is the most plausible part.
- `shmcfg`'s placement of BAR0. It stays for the whole boot, where the polled
  monitor on its own leaves BAR0 unassigned.
- A rebuilt monitor binary.

This design does not separate those three.

In the host the rise shows up as **QEMU's main thread doing about 58 µs more work
per TCP exchange**, while the guest traps about as often and the thread is woken
just as often.

## The two sessions

Both ran the ladder's TCP group with D-udp in it and arm C (`UDP_IN_TCP=1`,
`ARM_C_PORT=7000`). That is five rungs, k = 4 rounds each, n = 1000 samples per
arm and round, 2 ms spacing, the governor pinned and the deep idle state off, as
in the ladder records.

| session | order | conditions |
|---|---|---|
| 1 | A B C C B A | A = `ifs-udp.bin`, no extra devices · B = `ifs-udp.bin` + `ivshmem-doorbell` + virtio console + the guest's ivshmem server · C = `ifs-kick.bin` + the same |
| 2 | B S N C C N S B | S = `ifs-shm.bin` + the same devices · N = `ifs-kick-nomon.bin` + the same (the kick image without its notified monitor) |

- **Snapshots.** Session 1 ran each boot's ladder twice, with and without the
  per-arm KVM snapshot, in alternating order. Session 2 ran it with snapshots
  only.
- **The mirrored order.** It would cancel a linear drift. The drift here is not
  linear, so it bounds the noise instead of removing it. Between the two boots of
  one condition the levels moved up to 4.8 µs on D-guest and 6.4 µs on C-null and
  D-udp (`analyze.py`, last lines). Contrasts inside about ±3 µs are therefore
  within boot-to-boot noise.
- **The services each boot ran,** read from the guest's own console by
  `analyze.py`:

  | condition | services |
  |---|---|
  | A, B | no shm service |
  | S | the polled monitor |
  | N | `shmcfg` and the polled monitor |
  | C | `shmcfg` and both monitors |

  Every boot matched its condition. `devc-virtio` prints nothing, so its
  presence in N and C is inferred from the image. In C it is also shown by the
  notified monitor, which serves `/dev/vcon2`.
- **`ifs-kick-nomon.bin`** was built for this from
  [`ifs-kick-nomon.build`](../../../ipc-test/qnx-safety-monitor/ifs-kick-nomon.build).
  Extracted with `dumpifs`, 51 of its 54 files hash identically to
  `ifs-kick.bin`'s. The three that differ are the startup script (one line
  fewer: the notified monitor's), the embedded build file and the build date.

## Levels and contrasts

| condition | image runs | D-guest (TCP) | C-null (TCP echo) | D-udp | crossing, D − B (paired) |
|---|---|---|---|---|---|
| A (s1) | — | 179.0 | 179.2 | 159.9 | 122.5 |
| B (s1) | — | 180.6 | 180.2 | 161.3 | 124.6 |
| C (s1) | `shmcfg`, `devc-virtio`, both shm monitors | 218.3 | 217.1 | 197.5 | 162.2 |
| B (s2) | — | 183.8 | 183.6 | 165.1 | 128.0 |
| S (s2) | the polled monitor | 183.2 | 183.8 | 164.7 | 126.6 |
| N (s2) | `shmcfg`, `devc-virtio`, the polled monitor | 221.1 | 220.5 | 199.1 | 164.9 |
| C (s2) | `shmcfg`, `devc-virtio`, both shm monitors | 218.1 | 217.4 | 196.5 | 161.6 |

The table gives µs at p50. Each row is the mean of its condition's boots; in
session 1 it is also the mean of both snapshot settings. The host-only rungs sit
at 52.6–53.6 µs (A-loopback) and 55.5–56.5 µs (B-bridge) in every condition here.

C reproduces the notified-shm run's guest rungs: D-guest 218.3 and 218.1 against
217.0. It does not reproduce that run's host rungs, which were about 7 µs higher
(A-loopback 60.5, B-bridge 63.4), or its crossing, about 7 µs lower (154.5
against 161.6–162.2). That host-side offset between boots is unexplained, and
larger than the drift within a session.

| change | D-guest | crossing | C-null | D-udp |
|---|---|---|---|---|
| devices + the guest's ivshmem server, guest ignoring them (B − A) | +1.7 | +2.1 | +1.1 | +1.4 |
| KVM snapshots (within each boot; median of six) | +0.1 | — | — | — |
| the polled monitor, and the other differences between ifs-shm and ifs-udp (S − B) | −0.6 | −1.4 | +0.3 | −0.4 |
| **what N adds over S** (`devc-virtio`, `shmcfg`'s BAR0, the rebuilt monitor) | **+37.9** | **+38.3** | **+36.7** | **+34.4** |
| the notified monitor (C − N) | −3.0 | −3.2 | −3.2 | −2.6 |
| the whole kick image, session 1 (C − B) | +37.6 | +37.6 | +36.9 | +36.2 |
| the whole kick image, session 2 (C − B) | +34.3 | +33.6 | +33.8 | +31.4 |

## What the host shows

These figures come from the KVM snapshots (`KVM_STATS=1` ladders only).

**The idle guest.** Figures are per second while A-loopback runs, which never
touches the guest.

| condition | halts (WFI exits) per s | all exits per s |
|---|---|---|
| A / B | 64–70 | 255–275 |
| S, N, C | 332–336 | 1315–1330 |

The images carrying the polled monitor add about 266 halts a second, summed over
the guest's two vCPUs. The monitor checks its slot every 10 ms once idle, which
is 100 looks a second. So each look accounts for about 2.7 halts, or other
differences between the images contribute. Either way these halts cost the
socket rungs nothing (S − B above). What N adds over S changes the idle rate by
−3 halts/s.

**Per TCP exchange (D-guest).** Figures are over the same round's idle
background.

| condition | VM exits | exits to QEMU's userspace | QEMU main-thread CPU, µs | CPU per main-thread run, µs (raw) | QEMU's other threads, µs |
|---|---|---|---|---|---|
| A / B | 19.5–19.7 | 2.10 | 60.5–66.0 | 30.2–33.1 | 205–210 |
| S | 19.0 | 2.10 | 65.3 | 32.6 | 213 |
| N | 19.1 | 2.10 | **123.7** | **61.9** | 224 |
| C | 18.9–19.0 | 2.10 | **121.9–122.2** | **60.9–61.1** | 216–222 |

With what N adds, the guest traps about as often, 18.9–19.7 exits per exchange
across all conditions, and exactly as often into QEMU's userspace. QEMU's main
thread, which serves virtio-net without vhost, is scheduled just as often: 2,405
to 2,424 times per 1,200 exchanges in every snapshot round of every boot, about
two per exchange. But each run now costs about 29 µs more: 61–62 µs against
30–33. That makes +58 µs of main-thread CPU per exchange (N − S). QEMU's other
threads, including the vCPU threads that also carry the guest's own execution,
add about 10 µs more. The latency rises about 38 µs.

These are correlations measured together. Neither table shows that the latency
passes through that work. What inside QEMU does it was not identified: no
profiler or QEMU tracing was run. `devc-virtio` is a QNX-shipped binary and is
not examined beyond its behaviour.

## What this changes

- **The notified-shm records' socket contrasts.** In the notified image TCP and
  UDP carry this cost. So D-db − D-guest (−92.4 µs on the Orin, paired, one boot)
  compares the doorbell with a TCP slowed by 34–38 µs.
  - Subtracting this record's C − B (+34.3 to +37.6 µs) leaves the doorbell arm
    **about 55–58 µs faster** than TCP without the driver. That combines a paired
    figure with a contrast from other boots.
  - As a plain level comparison across boots and sessions, D-db's 124.8 µs
    against D-guest's 179–184 µs in A, B and S here gives about 54–59 µs.
  - Both estimates carry the ~7 µs host-side offset between the kick boot and
    these boots as an extra uncertainty.
  - Whether the notified arms carry some of the same cost is unknown: they cannot
    run without the driver.
- **`a1.metal` stays open.** The ~76 µs shift there crossed this change and
  several others: another instance, an older image and an older script. It was
  not isolated on that host, and it is about twice the Orin's figure. If it is
  the same effect:
  - the doorbell arm there (203.0 µs) is about 21 µs faster than the earlier
    `a1.metal` ladder's TCP (224.3 µs, another instance and image);
  - the console arm (267.5 µs) is slower.
- **The Orin record's §5 is explained;** the `a1.metal` record's §4 is not.

## What this does not show

- **Which of `devc-virtio`, `shmcfg`'s lasting BAR0 placement or the rebuilt
  monitor causes it,** though the host-side evidence points at the device the
  driver brings to life.
- **Which part of QEMU does the extra work,** why the guest's socket rungs pay
  for it, and whether the notified arms do.
- **The notified runs' other ingredients.** The kick run's host-side ivshmem
  server, its host-side shm and kick monitors, its doorbell burst and its
  interleaved groups were never present here; only the TCP group ran.
- **The same mechanism on `a1.metal`.** It is plausible there, but not measured.
- **Anything at OD11's k ≥ 12.** This is k = 4 per boot, a diagnostic.
- **Why the kick boot's host rungs sat ~7 µs higher** than every boot here.

## Files

- **`session1/`, `session2/`.** One directory per boot (`b<i>-<condition>`),
  each holding:
  - `kvm0/` and/or `kvm1/`, with the ladder's arm files, KVM snapshots and stamp;
  - the boot's guest console and launch logs;
  - plus, per session, `plan.txt` and `images.sha256`.
- **`analyze.py`.** It re-derives every figure above that comes from these
  files. The levels quoted from other records (217.0, 124.8, 60.5, 63.4, 154.5,
  203.0, 224.3) are those records' own.
- **Capture.** Captured with `scripts/aws/capture.py`. The arm JSON is
  byte-for-byte, `stamp.json` has only its strings masked, and the logs went
  through the redactor. The board's user name reads `<user>`.
- **The driver** is
  [`run-shift-isolation.sh`](../../../orin-native/gpu-concurrency/run-shift-isolation.sh).
  Its per-boot service check and palindrome check were added after these runs.
  `analyze.py` repeats the service check from the consoles.
