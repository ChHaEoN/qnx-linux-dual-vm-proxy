# A6 on AWS `a1.metal` — the notified-shm ladder on a second host: TCP, the D-udp rung, polled and notified shared memory — 2026-09-22

The ladder of [20260922T-a6-orin-kick](../20260922T-a6-orin-kick/results.md), run
again on a bare-metal Graviton1 host with the same guest image, disk, QEMU build
and tooling. It covers the TCP rungs, D-udp, the polled slot, the console kick and
the ivshmem doorbell out. The question is which of the Orin's findings belong to
the arrangement — QNX SDP 8.0 as a KVM guest beside Linux, talking over these
paths — and which belong to the board.

**Host.** AWS `a1.metal`, `eu-central-1`: Graviton1, 16× Cortex-A72, Ubuntu 22.04
(`ami-02153ae97d7504246`), kernel `6.8.0-1063-aws`, no kernel lockdown, no cpufreq
and no cpuidle (recorded as `absent`). QEMU is the distro's 6.2.0, and `dpkg`
confirmed the same package build as the Orin's, `1:6.2+dfsg-2ubuntu6.31`
([`host-facts.txt`](host-facts.txt); the copies of the version string in the
stamp and in `guest-launch.log` are over-masked to `2<user>6.31` by the redactor,
as on 2026-09-21). KVM's halt-poll
parameters match the Orin's (500000/2/10000/0).

**What is the same as the Orin run.**
- **Inputs.** Image `ifs-kick.bin` (sha256 `7350e601…`) and disk `f326b792…`,
  both verified on the host before use.
- **QEMU.** The command line is identical apart from file paths (compared from
  both stamps).
- **Pinning.** QEMU on cores 0–2, the host monitors on 3, the probe on 4, the
  ivshmem servers and the counter reader on 5. QEMU and the monitor sit in one
  cluster and the probe and the aux core in the other, on both hosts. That is
  cluster membership only; the cache sharing differs (below).
- **Sizes and order.** k = 12, n = 1000, 200 warm-up, 2 ms spacing, the four
  transport groups in a Williams order (`order.log`).
- **Tooling.** Every stamped source and script hash (script, library, probe,
  `shmchan.c`, `shm_chan.h`, `shm_map_posix.c`, `ivshm_client.c`,
  `ivshmem_server.py`) equals the Orin run's. This run used a `git archive` of
  `0e19d15`, which differs from the Orin's `a9df382` only in tests, docs, the
  claims gate and `redact-aws.sh`. The native monitor and `libshmchan.so` were
  built on this host from byte-identical sources, so their binary hashes differ.

**What differs, recorded, not equalised.**
- **Cores.** A72 (ARMv8.0) against A78AE (ARMv8.2).
- **Kernel.** Canonical's 6.8 (EEVDF) against NVIDIA's 5.15 (CFS).
- **Power management.** No DVFS here; the Orin's governor was pinned to
  `performance` and its deep idle state disabled.
- **Memory.** Transparent hugepages `madvise` here, `always` on the Orin
  ([`orin-host-facts.txt`](orin-host-facts.txt), captured the same day by the same
  script).
- **Platform.** Nitro under "bare metal", and 16 cores against 6. The ENA
  NIC's interrupts land on host cores.
- **Speculation mitigations.** Software Spectre-v2 workarounds on the A72
  against hardware mitigation on the A78AE, as the 2026-09-21 record noted.
- **Caches.** Here the four cores of a cluster share an L2 (0–3, 4–7). On the
  Orin each core has its own L2 and the cluster shares an L3 (0–3, 4–5).
- **Bridge.** `br0` holds `tap-qnx` only on both hosts. The Orin's facts file
  also lists `usb0` and `usb1`; they are ports of L4T's own `l4tbr0`.

**Checks.**
- **The gate.** All 144 arm files passed it. That includes the per-exchange
  accounting: every one of the 60 notified files ended each of its 1200
  exchanges on exactly one notification.
- **The doorbell check.** Before any D-db sample it was answered by 10 000
  doorbells: all arrived, `mmio_exit_kernel` rose by 10 210 and
  `mmio_exit_user` by 4.
- **The guest.** The image had never booted on a Cortex-A72. Here `shmcfg`
  placed BAR2 and BAR0 exactly as on the Orin, and both shm monitors came up.
- **The host's notified monitor** ended with the Orin's counts to the unit:
  28 815 exchanges, 14 414 doorbells, 0 peer-table misses, 0 stale kicks,
  26 clients. The guest's ivshmem server saw peers 1–15, none reused.

Every difference below is paired: the median over rounds of (arm − reference) in
the same round, the min–max band, and how many of the 12 rounds lie above zero.
**Hosts are compared only through these within-run contrasts, never by level.**

---

## 1. The Orin's contrasts, on both hosts

| p50, paired within each host's ladder | `a1.metal` (A72) | Orin (A78AE) |
|---|---|---|
| D-db − D-guest (doorbell out against TCP) | **−97.1 µs** [−98.1, −96.2], 0/12 | −92.4 µs [−94.5, −90.1], 0/12 |
| D-kick − D-guest (console out against TCP) | **−32.5 µs** [−33.8, −31.4], 0/12 | −55.4 µs [−57.6, −50.2], 0/12 |
| D-db − D-udp | −76.9 µs [−78.0, −75.4], 0/12 | −73.3 µs [−75.2, −71.9], 0/12 |
| D-kick − D-udp | −12.6 µs [−13.5, −11.0], 0/12 | −35.6 µs [−38.2, −33.9], 0/12 |
| D-db − D-kick (the guest's reply) | **−64.5 µs** [−65.5, −63.6], 0/12 | −37.3 µs [−40.9, −35.3], 0/12 |
| A-db − A-kick (the same swap on the host) | −4.5 µs [−5.9, −3.6], 0/12 | −3.9 µs [−5.1, −1.9], 0/12 |
| (D-kick − D-db) − (A-kick − A-db) | **+59.7 µs** [+58.8, +61.8], 12/12 | +33.3 µs [+31.7, +37.8], 12/12 |
| D-kick − C-kick (slot, judgement, reply position) | +3.8 µs [+3.0, +4.9], 12/12 | +4.0 µs [+0.0, +5.1], 12/12 |
| C-kick − C-null (console echo against TCP echo) | −36.1 µs [−36.9, −34.9], 0/12 | −58.1 µs [−59.8, −55.6], 0/12 |
| D-shm − A-shm (the polled crossing) | **−0.0 µs** [−0.1, +0.1], 4/12 | −0.3 µs [−1.0, +0.2], 3/12 |
| D-udp − D-guest | −20.3 µs [−21.1, −19.2], 0/12 | −19.0 µs [−22.2, −15.3], 0/12 |
| D-guest − C-null (the monitor's own work) | +0.5 µs [−0.4, +1.0], 11/12 | +0.8 µs [−2.0, +3.0], 8/12 |

Levels here, medians of the round p50s (p99 in brackets):

| arm | p50 (p99) |
|---|---|
| D-db | 203.0 µs (229.4) |
| C-kick | 263.7 µs (287.9) |
| D-kick | 267.5 µs (292.3) |
| D-udp | 280.1 µs (309.0) |
| C-null | 299.8 µs (323.6) |
| D-guest | 300.2 µs (323.5) |
| A-loopback | 63.6 µs |
| B-bridge | 66.8 µs |
| A-kick | 49.1 µs |
| A-db | 44.6 µs |
| A-shm | 6.2 µs (7.3) |
| D-shm | 6.2 µs (14.0) |

At p90, D-db − D-guest is −98.4 µs [−99.5, −97.7] (0/12) and at p99 −96.8 µs
[−110.1, −83.9] (0/12). D-kick − D-guest is −33.6 µs at p90 (1 round above zero)
and −31.0 µs at p99 (2 rounds above zero).

## 2. What replicates

Everything in this section holds WITHIN each run. The first two items also rest
on the socket rungs that §4's level shift may inflate.

- **The order of the paths.** D-db < D-kick < D-udp < D-guest in every round, on
  both hosts. D-kick's place is the fragile part: if the shift belongs to the
  socket rungs alone, its bound here (about 76 µs) exceeds D-kick's lead over
  TCP (32.5 µs) and over UDP (12.6 µs).
- **The doorbell's lead over TCP**, in absolute terms: −97 µs here, −92 µs on the
  Orin, each subject to its own host's shift. D-db − D-kick, both notified
  arms, is the cross-host contrast that a socket-only shift cannot reach.
- **The polled crossing adds nothing**, now on a third boot and a second host:
  D-shm − A-shm is −0.0 µs, every round within ±0.15 µs ([−0.12, +0.15]).
- **The slot, the judgement and the reply's position in the loop cost about
  4 µs together** over a bare console echo on both hosts, and **UDP beats TCP by
  about 20 µs** on both.
- **The monitor's own work is small.** D-guest − C-null is +0.5 µs, above zero in
  11 of 12 rounds: small against a 234 µs crossing, but not zero on this host
  (the Orin: +0.8 µs, 8/12).
- **Exits to QEMU's userspace are the same.** Per exchange, over the same round's
  idle background:

  | arm | exits to QEMU userspace, here | exits to QEMU userspace, Orin | handled in the kernel, here | handled in the kernel, Orin |
  |---|---|---|---|---|
  | D-db | 2.14 | 2.14 | 7.28 | 7.24 |
  | D-kick | 4.13 | 4.13 | 10.44 | 10.73 |
  | D-guest | 2.10 | 2.10 | 6.64 | 7.01 |

  Exits to QEMU's userspace match to the hundredth. The other counters do not:
  - **Kernel-handled MMIO exits** differ by up to about 0.4 per exchange in the
    arms shown, and by 0.95 in D-udp (7.95 against 7.00).
  - **Halt (WFI) exits** are about 20% fewer here: D-kick 7.6 against 9.5, and
    D-db 3.7 against 4.6.

  Whether each exit costs more on this host was not measured.

## 3. What does not replicate

- **The console costs the guest far more here.** Net of the host's wait
  primitive, answering over the console costs the guest's side 59.7 µs more
  than the doorbell, against 33.3 µs on the Orin. The console's reply path is
  the one with two extra exits to QEMU's userspace per exchange (§2). That those
  exits simply cost more on this host is consistent with the counters, but it
  was not measured. The contrast also carries the two arms' halt-polling
  difference, which it does not separate: polling ended 23% of the console
  arms' halts here and 1% of D-db's. Either way, D-kick's lead over TCP shrinks
  to 32.5 µs, while D-db keeps its lead.
- **The Orin's D-db-only QEMU main-thread wait is absent.** QEMU's main-thread
  run-queue wait, background-corrected, is 0.03 µs per exchange in D-db here,
  against 4.6 µs on the Orin. In D-guest and D-kick it is 0.02–0.04 µs on both
  hosts. So that wait is not a property of the doorbell path alone; its cause on
  the Orin is still unknown.
- **Halt polling barely acts on the doorbell arm here.**

  | arm | halts KVM polled on | polls that succeeded | halts ended by polling |
  |---|---|---|---|
  | console arms | 66% | 35–36% | 23% |
  | D-db | 36% | 1% | 1% |
  | D-guest | 47% | 4% | 2% |
  | D-udp | 36% | 4% | 1% |

  These are raw ratios, not background-corrected; the Orin's 37–38%, 18% and 3%
  are its "ended by polling". Here the doorbell beats TCP with polling ending
  1–2% of halts in both arms, so a polling difference is not needed for the
  doorbell to lead on this host. How much of the Orin's 92 µs its own 18%
  against 3% accounts for is not measured.

## 4. The level shift, on both hosts

> **Isolated on the Orin later the same day**
> ([20260922T-a6-orin-shift](../20260922T-a6-orin-shift/results.md)).
>
> - **The cause there.** The shift is what the notified image adds for its kick,
>   most plausibly the guest's virtio console driver (`devc-virtio`): 34–38 µs on
>   every guest socket rung.
> - **This host.** It was not isolated here, and the ~76 µs here is about twice
>   the Orin's figure. If it is the same effect, the doorbell arm (203.0 µs) is
>   about 21 µs faster than the 2026-09-21 ladder's TCP (224.3 µs; another
>   instance and image), and the console arm slower.
> - **The polled monitor.** It is "ruled out" below by argument; it was then
>   ruled out by measurement on the Orin. The images carrying it add ~266 halts a
>   second, and those halts cost the socket rungs nothing.
>
> The text below is as written before that.

This run's guest rungs sit **about 76 µs higher** than on the 2026-09-21
`a1.metal` ladder:

| rung | 2026-09-21 | this run |
|---|---|---|
| D-guest | 224.3 µs | 300.2 µs |
| C-null | 224.3 µs | 299.8 µs |
| A-loopback | 61.4 µs | 63.6 µs |
| B-bridge | 64.5 µs | 66.8 µs |

So the guest crossing (D-guest − B-bridge, paired) went from 159.4 µs to
234.1 µs, while the host-only rungs moved about 2 µs.

The Orin showed a smaller guest-rung shift against its two earlier boots that
day ([its §5](../20260922T-a6-orin-kick/results.md)):
- about 37 µs against the `ifs-udp` boot, which had no shm device, like the
  a1.metal baseline;
- about 32 µs against the `ifs-shm` boot, which already had `ivshmem-plain` and
  the polled monitor.

The a1.metal comparison crosses more changes than either, and none can be
separated here:
- another instance;
- the image, `ifs-demo2.bin` → `ifs-kick.bin` (`devc-virtio`, two shm monitors,
  the UDP monitor);
- the devices: none → `ivshmem-doorbell` and a virtio-serial console;
- two ivshmem servers on core 5;
- a KVM snapshot with `sudo` and a 100 ms pause around every arm;
- the ladder script, `002bc7a` → `0e19d15`.

One candidate is ruled out: the guest's polled monitor stops spinning 50 ms after
its last request, and every arm is preceded by a 100 ms pause.

So, as on the Orin, the socket contrasts of §1 may include up to that shift if it
belongs to the socket path alone. That now means up to about 76 µs here. A
guest-rung shift thus appears on both hosts, but across different sets of
changes; whether it is the same effect is not established.

## What this does not show

- **A one-variable host comparison.** A72 against A78AE, two kernels, two power
  regimes, Nitro, THP policy and core count all differ, so no host-to-host
  difference above is attributed to any one of them.
- **The cause of the level shift** (§4), or whether it reaches the notified arms.
- **The notifier's cost in isolation.** D-db − D-kick also carries the two arms'
  halt-polling difference (§3); the contrast removes the host's wait primitive,
  not that.
- **A doorbell into the guest.** Host→guest is the virtio console in every guest
  arm, as on the Orin: QEMU 6.2 interrupts a guest only through MSI-X, which
  nothing here enables.
- **VM↔VM, a hypervisor-to-hypervisor path, isolation, or any real-time or safety
  property.** Host↔guest under KVM, one run on one instance.
- **CPU cost.** QEMU's per-thread run time is in the KVM files but was not
  analysed, and the probe's and the monitors' CPU time was not recorded.
- **Anything about EC2 instances in general.** Non-metal Graviton instances
  expose no `/dev/kvm` (a `t4g.small` probe, 2026-06), so none of this runs
  there.

## Session

- **Launched 13:20:34Z, terminate requested 13:31:38Z** ([`session.txt`](session.txt),
  the driver's own redacted output). About 11 minutes billed, roughly $0.09 at
  about $0.47/h. Of that, the ladder took about 8 minutes, from
  13:23:04Z to 13:30:44Z.
- **Self-termination.** The instance scheduled its own poweroff at +90 min, and
  it was checked as armed, 88 minutes ahead, before anything was uploaded.
  Termination was requested by hand.
- **Teardown.** Checked afterwards: no instance running or pending in the
  region, no available (orphaned) volume, and the root volume, created with
  delete-on-termination, followed the instance.
- **Rehearsal.** The same instance script had first run end to end on the Orin
  at k = 4. That rehearsal found two capture bugs, both fixed before launch:
  - The redactor's MAC pattern never matched under Ubuntu's `mawk`
    (`0e19d15`).
  - Piping JSON through the redactor would have rewritten 12-digit KVM counters
    as `<account>`.

**Redaction, at capture, on the instance.** Text files went through
`redact-aws.sh`. JSON files were copied byte-for-byte once every string in them
(keys and values) had come through the redactor unchanged; numbers are never
redacted. The arm files — 290 `lat-`, `kvm-` and `db-burst` JSONs — are
byte-identical to what the run wrote; `stamp.json` had only its strings masked.
Scanned after the fetch: no AWS id shapes, no addresses but `127.0.0.1`,
`0.0.0.0` and the bridge subnet, only the documented guest MAC, no `<account>`
anywhere. One value was masked after the fetch: the root `PARTUUID` in
`host-facts.txt`. It is probably AMI-level provenance, but that could not be
confirmed.

## Files

- `ladder/raw/`: the arm files, `stamp.json`, `order.log`, `probe.log` and the
  host monitor and ivshmem server logs, as in the Orin record.
- `ladder/run.log`: the script's output, with the paired tables.
- `ladder/guest-console.log`, `ladder/guest-launch.log`,
  `ladder/ivshmem-server.log`: the guest's side.
- `ladder/host-before.txt`, `ladder/host-after.txt`: load average and
  `/proc/interrupts` around the ladder.
- `host-facts.txt`: this host.
- `session.txt`: launch, safety-net and teardown times, from the driver.
- `orin-host-facts.txt`: the Orin, from the same script the same day.
