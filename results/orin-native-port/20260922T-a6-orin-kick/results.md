# A6 on the Orin — notified shared memory: a virtio-console kick in, a console kick or an ivshmem doorbell out — 2026-09-22

The third run of OD12's "other IPC paths": the shared-memory slot of the polled
run, but **nobody spins**. The probe kicks the guest awake over a virtio console,
and the guest answers either over the same console (**D-kick**) or through the
ivshmem **Doorbell** register, which a KVM ioeventfd turns into a write to the
probe's eventfd (**D-db**). Beside them in the same run: the TCP rungs (with D-udp
in their group), the polled rungs of the last run, host baselines for every new
rung, and a bare console echo. Jetson Orin Nano (Tegra234, 6× Cortex-A78AE),
QNX SDP 8.0 as a KVM guest beside L4T, one guest boot, paired within rounds.

**Why the guest is kicked over a console, not a doorbell.** QEMU 6.2's
`ivshmem-doorbell` always has its MSI feature and interrupts a guest only through
MSI-X. Under KVM with the ITS, its `setup_interrupt()` leaves the guest's eventfd
unattached until the guest enables MSI-X, and on the path without an irqfd
`ivshmem_vector_notify()` drops the notification while MSI-X is off. MSI-X in
this guest would come from the QNX PCI server, whose `pci_hw-fdt.so` refuses QEMU
virt (an `[ecam]` override in its HW configuration file was tried the same day
and changed nothing); programming the MSI-X table and the GIC ITS by hand, as
`shmcfg` does for the BARs, was not attempted. So host→guest is the virtio
console in every guest arm, and only guest→host differs between D-kick and D-db.
The owner chose to build both.

| group | arm | request (probe → far end) | reply notification (far end → probe) |
|---|---|---|---|
| tcp | A-loopback, B-bridge, C-null, D-guest | TCP | TCP |
| tcp | D-udp | UDP | UDP |
| shm | A-shm, D-shm | slot at 0, polled | polled |
| kick | A-kick | slot at 4096 + a kick byte on a host UNIX socket | a kick byte back |
| kick | C-kick | an echo byte over the virtio console, no slot | the byte back |
| kick | D-kick | slot at 4096 + a kick byte over the virtio console | a kick byte back over it |
| db | A-db | as A-kick | the host monitor writes the probe's eventfd |
| db | D-db | as D-kick | the guest writes the ivshmem Doorbell → KVM ioeventfd → the probe's eventfd |

k = 12 rounds, n = 1000 timed samples per arm and round, 200 warm-up discarded,
2 ms spacing; governor pinned to `performance`, deep idle state `c7` disabled,
both restored and verified; QEMU pinned to cores 0–2, host monitors on 3, the
probe on 4, both ivshmem servers and the counter reader on 5 (`SCHED_OTHER` on
core 4 in all 144 files, by the probe's own report). The four transport groups
ran in a Williams order (period 4; `order.log`). Every one of the 144 files passed
the gate, which for this run also requires **every notified exchange to have ended
on exactly one notification** — the probe counts exchanges, wake-ups,
notifications, early wake-ups, stray bytes and empty reads, and all 60 notified
files show 1200 of each of the first three and none of the rest — and a KVM
snapshot around every arm.

**The doorbell path is checked, not assumed.** Before any D-db sample, one exchange
was answered by 10 000 doorbells: all 10 000 arrived, the VM's `mmio_exit_kernel`
rose by 10 174 and `mmio_exit_user` by 4 — the doorbells were caught by KVM in
the kernel and did not go to QEMU's userspace (4 exits there in all, against
10 000 doorbells). The run would have refused
otherwise (`db-burst.json`, `db-burst-kvm.json`, the stamp).

**The guest** is a new image, `ifs-kick.bin` (sha256 `7350e601…`), and a new boot:
QEMU pid 78418, started 2026-09-22T11:29:18Z, disk `disk-qemu` (sha256
`f326b792…`) under `-snapshot`, `-device ivshmem-doorbell` served by this
project's `ivshmem_server.py` (pid in the launch log, pinned to core 5, peer ids
never reused — QEMU 6.2 writes into freed memory when one is), and a virtconsole
on a UNIX socket after virtio-rng (virtio-mmio slot `0xa003800`, SPI 44). The
image is `ifs-shm.bin` plus `devc-virtio` and three start lines; checked with
`dumpifs`: 39 files identical, 10 identical except each ELF program header's
`p_paddr`, the four expected files different, `devc-virtio` the only addition. The
image's monitor is the qcc build of the committed sources (code and data
identical). On the console: `shmcfg` placed BAR2 at `0x10000000` and BAR0 at
`0x10100000` once, both monitors mapped them from its marker, and the notified
monitor read its own peer id 1 from IVPosition.

**What this boot served: this run and nothing else** — the launch script's
connect check, the ladder's reachability checks, the doorbell proof, and the 144
arms. The guest's polled monitor shows 13 bursts (the reachability check and 12
arms); the notified monitor, after 5 frames of checks, 12 bursts of 1201 frames
(D-db: 1200 plus its one untimed doorbell handshake, one attempt in every round) and
11 of 1200 (D-kick) — the twelfth D-kick burst was the notified monitor's last
traffic (round 12 ended with A-shm and D-shm), and a burst's line is printed only
when the next one starts.
The guest's ivshmem server saw 14 probe peers, ids 2–15, none reused. The host
notified monitor ends with 28 815 exchanges, 14 414 doorbells rung, 0 peer-table
misses, 0 stale kicks, 0 stray bytes, 26 clients. A K = 4 dry run of an earlier
build ran on an earlier boot; nothing from it is in `raw/`.

**Provenance.** Tooling as committed in `6e1362a` (on `main`), run from a
`git archive` of it: the stamp's script, library, probe, `shmchan.c`,
`shm_chan.h`, `shm_map_posix.c`, `ivshm_client.c` and `ivshmem_server.py` hashes
— the guest's server's own script included — are that commit's files. That
commit's tests, including the Linux-only ivshmem-server and notified end-to-end
tests, passed in CI on its branch with none skipped. On `main` the same commit
then failed one test asserting an exact stale-kick count, which with no spacing
between requests is timing, not behaviour; `779d0e4` changes that test only, and
CI passed it with none skipped. The code was shaped by a design review (3
lenses) and a code review (4 lenses; 24 findings, each verified, 19 real, all
fixed). Result and KVM JSONs copied byte-for-byte; logs and stamp redacted at
capture.

**Every difference below is paired**: the median over rounds of (arm − reference)
in the same round, with the min–max band and how many of the 12 rounds lie above
zero. Levels are medians over the 12 rounds of each round's p50.

---

## 1. Notified shared memory against TCP and UDP

| p50, paired | median | band | rounds above 0 |
|---|---|---|---|
| D-db − D-guest | **−92.4 µs** | [−94.5, −90.1] | 0/12 |
| D-kick − D-guest | **−55.4 µs** | [−57.6, −50.2] | 0/12 |
| D-db − D-udp | −73.3 µs | [−75.2, −71.9] | 0/12 |
| D-kick − D-udp | −35.6 µs | [−38.2, −33.9] | 0/12 |

As levels: D-db **124.8 µs**, D-kick 162.6 µs, C-kick 158.7 µs, D-udp 198.1 µs,
D-guest 217.0 µs, D-shm 4.0 µs. Both notified arms sleep on both sides, as the
socket arms do — the comparison the polled run could not make — though KVM ended
more of the guest's sleeps by halt polling in these arms than over TCP (§2). The
socket rungs of this run sit 32–38 µs above the two earlier runs', and pairing
does not remove that from these contrasts (§5). At p90 both stay
below TCP in every round; at p99 D-kick does too (D-kick − D-guest −63.9 µs
[−86.8, −28.4], 0/12) and D-db in 11 of 12 rounds (−102.9 µs, one round above zero).

## 2. The guest's reply: the doorbell against the console

| p50, paired | median | band | rounds above 0 |
|---|---|---|---|
| D-db − D-kick (guest side) | **−37.3 µs** | [−40.9, −35.3] | 0/12 |
| A-db − A-kick (host side, same change) | −3.9 µs | [−5.1, −1.9] | 0/12 |
| (D-kick − D-db) − (A-kick − A-db) | **+33.3 µs** | [+31.7, +37.8] | 12/12 |

Both variants carry the request over the console, so D-db − D-kick changes only how
the guest says "done": a 32-bit store to the Doorbell register that KVM turns
into an eventfd write, against a byte written to the console, which goes out
through the virtio queue and QEMU's userspace. On the host the same change of
notifier is worth 3.9 µs (an eventfd write against a socket write, and the probe
waking from an eventfd against a socket). Net of the host's wait primitive,
answering over the console costs the guest's side **33 µs** more than a doorbell —
together with the halt-polling and main-thread differences below, which the
contrast does not separate.

**What the KVM counters show** (per exchange, over the background rate the idle
guest showed in the same round's A-loopback arm):

| arm | MMIO exits to QEMU userspace | MMIO exits handled in the kernel | halts KVM polled on | polls that succeeded | halts ended by polling |
|---|---|---|---|---|---|
| D-db | 2.1 | 7.2 | 47% | 38% | 18% |
| D-kick | 4.1 | 10.7 | 72% | 52% | 37% |
| C-kick | 4.0 | 10.5 | 72% | 53% | 38% |
| D-guest (TCP) | 2.1 | 7.0 | 47% | 6% | 3% |
| D-shm (polled) | 0.1 | 0.4 | — | — | — (fewer halts than the idle background: a vCPU spins) |

The exit columns are background-corrected; the three halt-polling columns are
raw ratios of the arm's own counters (medians over rounds), not corrected.

The console's transmit adds about **two MMIO exits to QEMU's userspace per
exchange** over the doorbell, which adds none — consistent with the 10 000-doorbell proof.
Two things in the counters are not the notifier and are stated, not corrected:
- **Halt polling differs.** On a halt KVM may first poll — spin in the host
  kernel for up to its adaptive window — before putting the vCPU to sleep. It
  polled on 72% of the halts in the console arms and on 47% in D-db and over TCP;
  those polls succeeded 52–53%, 38% and 6% of the time, so polling ended 37–38% of
  all halts in the console arms, 18% in D-db and 3% over TCP. D-db − D-kick
  therefore also carries a difference in how often the guest was woken from a
  real sleep.
- **QEMU's main thread waited in D-db.** Its run-queue wait was 4.6 µs per
  exchange in D-db and at most 0.04 µs in every other arm; the vCPU threads show
  nothing similar. It is not explained here. Whether it lies on the exchange's
  path is not measured; if it does, it weighs against the doorbell.

## 3. What the partition adds, per path

| p50, paired: D − A (crossing into the guest) | median | band |
|---|---|---|
| TCP: D-guest − A-loopback | +156.3 µs | [+154.7, +162.8] |
| console both ways: D-kick − A-kick | +123.8 µs | [+122.3, +126.0] |
| console in, doorbell out: D-db − A-db | +90.5 µs | [+88.2, +91.2] |
| polled: D-shm − A-shm | −0.3 µs | [−1.0, +0.2], 3/12 above 0 |

The polled crossing again adds nothing measurable. That replicates the last run on
a new boot and a new device (`ivshmem-doorbell`, its memory from the server
rather than `memory-backend-file`), meeting the criterion a design review proposed
before this run (median within ±0.5 µs, band straddling zero). Every notified
crossing costs 90–124 µs, and each includes waking a guest that had halted: 3.6
(D-db) to 5.7 (D-kick) vCPU wake-ups per exchange over background.

## 4. The notification alone, and the slot

C-kick, one byte echoed over the console with no slot, is **158.7 µs** — the bare
console round trip. D-kick − C-kick is **+4.0 µs** [+0.0, +5.1] (12/12, one round at
+0.03). Both arms move one byte each way; what D-kick adds is the slot, the
judgement, and a reply sent from the monitor's loop after its wait returns
rather than from inside the wait, where the echo is answered. Together they cost
about 4 µs. Against TCP's null echo, C-kick − C-null is −58.1 µs [−59.8, −55.6],
0/12: a notification-only round trip through the console is cheaper than a TCP
round trip that carries 64 bytes through the guest's network stack, in this run
(C-null carries the shift of §5).

## 5. Replications and a level shift

UDP, a third time: D-udp − D-guest −19.0 µs [−22.2, −15.3], 0/12 (the earlier
runs: −20.0 and −18.3). The socket rungs, however, sit **32–38 µs higher** than in
the two earlier runs today: D-guest 217.0 µs (184.9 and 180.0 before), C-null
216.8 (184.4 and 180.2), D-udp 198.1 (166.5 and 160.3). The TCP crossing over the
bridge is +154.5 µs [+150.7, +158.4] against +122.4 and +123.5. This run changed several things at once — the image
(`devc-virtio`, a second monitor process), the device (`ivshmem-doorbell`), two
ivshmem servers on core 5, and a KVM snapshot with a 100 ms pause and `sudo`
reads before and after every arm — and none of them is separable here. That is
why every figure above is paired within this run; **no level here compares with
an earlier record**.

Pairing removes drift between rounds; it does not remove a shift present in every
round of the run. If the shift belongs to the socket path alone, the socket
contrasts above — D-db and D-kick against D-guest and D-udp, C-kick against
C-null — include up to that much of it; if it affects every guest arm, they do
not. The notified arms have no earlier run to tell which.

---

## Loss, stalls

None: all 144 arm files are complete, n = 1000 each, under the ladder's
refuse-on-stall rule (10 s probe timeout). No notified exchange lost its
notification (that would have been its own failure, "notification lost").

## What this does not show

- **A guest interrupted by the ivshmem doorbell.** QEMU 6.2 notifies a guest by
  MSI-X only, and nothing here enables MSI-X in this guest; the host→guest path is
  a virtio console in every guest arm. D-db measures the doorbell in one direction
  only.
- **The notifier's cost in isolation.** D-db − D-kick also carries different
  halt-polling behaviour and QEMU main-thread queueing (§2); the contrast removes
  the host's wait primitive, not those.
- **The cause of the D-db main-thread wait** and of the 32–38 µs socket level
  shift (§5), or whether that shift reaches the notified arms.
- **VM↔VM, a hypervisor, or a mailbox.** Host↔guest under KVM.
- **Isolation.** Guest and host share the 1 MiB file; nothing restricts what else a
  peer touches, and the monitor validates nothing beyond judging the frame.
- **CPU cost.** QEMU's per-thread run time is in the KVM files but was not
  analysed, and the probe's and the monitors' CPU time was not recorded. The
  notified arms sleep, but KVM's halt polling spends host CPU on their behalf (§2).
- **Anything under load, any loss behaviour, any other frame size.**
- **Any real-time, isolation or safety property.**

## Files

`ladder/raw/` — `lat-<arm>_r<k>.json` per arm and round (summary incl. `proto`,
the probe's scheduling report and, for notified arms, `notify` accounting,
`wait_fd_nonblock`, `ivshm_peer` and `handshake_attempts`); `kvm-<arm>_r<k>.json`
(the VM's KVM counters and QEMU's per-thread schedstat before and after the arm,
with CLOCK_MONOTONIC); `db-burst.json` and `db-burst-kvm.json` (the doorbell
proof); `stamp.json`; `order.log`; `probe.log`; the host-side monitor logs and the
host ivshmem server's log. `ladder/run.log` — the script's output with the summary
and the paired tables. `ladder/guest-console.log`, `ladder/guest-launch.log`,
`ladder/ivshmem-server.log` — the guest's boot, its launch and its ivshmem server,
redacted. The stamp's `order` string describes the rule; `order.log` holds the
orders as run.
