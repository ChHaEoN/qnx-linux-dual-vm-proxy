# A6 on the Orin — shared memory over ivshmem beside TCP and UDP — 2026-09-22

The second run of OD12's "other IPC paths across the same boundary": the same
64-byte frame through **one slot in shared memory** — QEMU's `ivshmem`, both ends
polling — beside the attribution ladder's rungs over **TCP** and **UDP**, in one run
on one guest boot, paired within rounds. Jetson Orin Nano (Tegra234, 6×
Cortex-A78AE), QNX SDP 8.0 as a KVM guest beside L4T.

| rung | TCP arm (port) | UDP arm (port) | shm arm (slot) | path |
|---|---|---|---|---|
| A | A-loopback (7100) | A-udp (7101) | A-shm (`/dev/shm/a6-shm-host`) | probe → monitor on the same Linux host |
| B | B-bridge (7100) | B-udp (7101) | — | probe → monitor in a network namespace behind `br0` |
| C | C-null (7000) | C-udp (7001) | — | probe → the guest's echo server, verbatim |
| D | D-guest (7100) | D-udp (7101) | D-shm (`/dev/shm/a6-ivshmem`) | probe → the guest's safety monitor (the published path) |

The shm slot ([`shm_chan.h`](../../../ipc-test/common/shm_chan.h)) holds one
request and one reply, each published with a store-release after its frame and
read with a load-acquire. **Both ends spin while they wait**: the plain `ivshmem`
device has no interrupt, so the probe spins on core 4 for each reply (it still
sleeps the 2 ms between samples, as on every rung), and the monitor holds core 3
(A-shm) or one of the guest's two vCPUs (D-shm) for the whole arm. No rung B or C
exists for shm: no bridge is involved, and the guest runs no shm echo server.

k = 12 rounds, n = 1000 timed samples per arm and round, 200 warm-up discarded,
2 ms spacing; governor pinned to `performance` and deep idle state `c7` disabled
(`CSTATE=shallow`), both restored and verified; QEMU pinned as a set to cores 0–2,
monitor on 3, probe on 4 (`SCHED_OTHER` on core 4 in all 120 files, by the probe's
own report). The order of the three transport groups followed a Williams design
over the groups (period 6, so k = 12 is two periods; `order.log`). Every one of the
120 files passed the gate, including each file's own `proto` against its arm.

**The guest** is a new image, `ifs-shm.bin` (sha256 `1e330bba…`), and a new boot:
QEMU pid 70981, started 2026-09-22T08:55:19Z, disk `disk-qemu` (sha256 `f326b792…`)
under `-snapshot`, and `-device ivshmem-plain` backed by a 1 MiB file zeroed at
launch — all in the stamp or the launch log. The image is the UDP run's
`ifs-udp.bin` plus one start line (the monitor in shm mode), with the monitor binary
rebuilt; checked with `dumpifs` against `ifs-udp.bin`: 48 files identical, one
identical except each ELF program header's `p_paddr` (mkifs writes a file's image
address there), the four expected files different, none added. The image's monitor
is the qcc build of the committed sources: code and data identical, differing only
in the ELF header's section fields and `p_paddr`. Build file:
[`ifs-shm.build`](../../../ipc-test/qnx-safety-monitor/ifs-shm.build).

**The guest configures the device itself.** The plan was SDP 8.0's `pci-server`
with `pci_hw-fdt.so`; on QEMU virt that module refused to load — by its own log it
read the ECAM window's size as zero, found no memory window and returned EINVAL —
and its HW configuration file can filter windows but not add them. So the monitor
finds `1af4:1110` on bus 0 through ECAM, sizes and places BAR2 at the base of the
32-bit window, enables decoding and maps BAR2 **cacheable**
([`shm_map_qnx.c`](../../../ipc-test/common/shm_map_qnx.c)). Its banner on the
console: `ivshmem 00:01.0 BAR2 0x10000000, 1048576 bytes prefetchable, address
assigned here, cmd=0x0002, cacheable`.

**What this boot served: this run and nothing else.** On the console, besides the
servers' start lines: the launch script's connect check (one zero-frame TCP session
on :7100), the ladder's reachability checks (a connect-and-close on each TCP port,
and one framed exchange through the guest's shm slot; the UDP checks leave no
console line), 12 sessions of 1200 frames on each TCP server, and 1 + 12 × 1200 =
14 401 frames through the guest's shm monitor, all accepted. A K = 6 dry run of the
same ladder ran clean on an earlier boot of the same image; nothing from it is in
`raw/`.

**Provenance.** Tooling as committed in `410e78f`, run from a `git archive` of that
commit: the stamp's script, library and probe hashes, and those of `shmchan.c`,
`shm_chan.h` and `shm_map_posix.c`, are that commit's files. The probe's
`libshmchan.so` was built by the run from them (sha256 in the stamp); the host's
`monitor-native` was built with `build-monitor-native.sh` from the same archive
(sha256 `ae79d6f9…`). Result JSONs copied byte-for-byte; logs and stamp redacted at
capture.

**Every difference below is paired**: the median over rounds of (arm − reference)
in the same round, with the min–max band and how many of the 12 rounds lie above
zero. Levels (medians over the 12 rounds of each round's p50) are labelled as such.

---

## 1. Shared memory against the socket paths

| p50, paired | median | band | rounds above 0 |
|---|---|---|---|
| D-shm − D-guest (to the guest's monitor, shm vs TCP) | **−180.2 µs** | [−181.2, −177.8] | 0/12 |
| D-shm − D-udp (to the guest's monitor, shm vs UDP) | **−161.9 µs** | [−163.7, −160.2] | 0/12 |
| A-shm − A-loopback (host only, shm vs TCP) | **−55.9 µs** | [−57.3, −53.7] | 0/12 |

As levels: D-shm 4.53 µs [4.00, 4.80], A-shm 4.51 µs [4.06, 4.70], D-guest
184.90 µs, D-udp 166.48 µs, A-loopback 60.24 µs.

This is **a polling path against interrupt-driven ones**. On the socket rungs both
ends block and are woken; on the shm rungs neither end sleeps inside the round trip.
The 180 µs is therefore not "the cost of TCP over shared memory" in general: it
includes everything a sleeping waiter pays that a spinning one does not, on both
sides.

## 2. Crossing into the guest adds nothing measurable to a polled slot

| paired, D-shm − A-shm | median | band | rounds above 0 |
|---|---|---|---|
| p50 | **−0.0 µs** | [−0.3, +0.3] | 4/12 |
| p90 | −0.1 µs | [−0.4, +0.5] | 5/12 |
| p99 | +0.2 µs | [−0.5, +9.1] | 7/12 |

The same slot layout and code, the same probe, and at the far end the same
`monitor.c` — once a host build on core 3 serving a file in `/dev/shm`, once the
guest's qcc build on a vCPU of a QEMU pinned to cores 0–2, serving the `ivshmem`
file — and the two round trips differ by at most 0.32 µs at p50 in any round.
Measured the same way, D − A over TCP in this run is **+124.7 µs** [+121.3, +126.2],
12/12, and the difference of the two crossings, (D-guest − A-loopback) − (D-shm −
A-shm), is +124.6 µs [+121.6, +126.3], 12/12.

**What this does and does not attribute.** BAR2 is RAM in QEMU — a KVM memory
slot — so a guest load or store to it should not leave guest mode, and with both
ends spinning no one is woken; the partition boundary is then simply not on the
data path, which is what these figures are consistent with. That is inferred, not
observed: no KVM exit counters were read. The result says nothing about the cost
of **notifying** a waiter across the boundary (there is none here), nor about what
happens when the spinning vCPU is descheduled — the one D-shm round whose maximum
reached 131 µs (round 1; every other round's maximum was at most 36.4 µs, A-shm's
at most 23.4 µs) may be that, and one round is one observation.

## 3. The instrument, seen from a path with no system call

A-shm's 4.5 µs includes the probe's own Python loop around one `ctypes` call, the
slot's round trip and the monitor's judging — so the probe's loop costs at most
that much **around a call that makes no system call**. Rung A over TCP is 55.9 µs
slower in the same rounds: the loopback TCP path, its system calls, the probe's
Python around them, and waking two blocked ends. This run does not split that sum,
and it does not bound the probe's cost around socket calls; it does show that the
bulk of what the ladder's design calls rung A's "instrument floor" is not a fixed
per-sample cost of the probe itself.

## 4. UDP again, on a second boot

The UDP rungs ran beside TCP again, on this new image and boot:

| p50, paired | this run | the UDP run (2026-09-22, other boot) |
|---|---|---|
| D-udp − D-guest | −18.3 µs [−19.4, −14.1], 0/12 | −20.0 µs [−23.0, −18.2], 0/12 |
| C-udp − C-null | −18.1 µs [−20.4, −15.7], 0/12 | −20.7 µs [−21.8, −16.2], 0/12 |
| A-udp − A-loopback | −12.9 µs [−16.7, −9.7], 0/12 | −12.3 µs [−13.4, −10.5], 0/12 |
| B-udp − B-bridge | −11.3 µs [−14.1, −7.9], 0/12 | −11.5 µs [−13.2, −10.5], 0/12 |
| crossing, (D − B) UDP − (D − B) TCP | −6.8 µs [−9.5, −0.0], 0/12 | −8.4 µs [−12.0, −5.0], 0/12 |

Every UDP rung is again faster in every round, on a second boot of a second image
(the two images differ in the monitor binary and one start line). The guest-rung
and crossing differences are 1.6–2.6 µs smaller here; with one run per boot, that
is between-run variation this design cannot attribute. The TCP crossing D − B is
+122.4 µs [+120.2, +124.2] (the UDP run: +123.5). The monitor's own work, D − C, is
indistinguishable from zero on both transports: TCP +0.4 µs [−3.4, +2.0], UDP
−0.1 µs [−1.5, +3.2].

## 5. Tails

D-shm's median of round p99s is 6.1 µs (A-shm 5.8 µs); against TCP, D-shm − D-guest
at p99 is −218.6 µs [−267.8, −208.0], 0/12. Between UDP and TCP at p99 no difference
resolves (D-udp − D-guest −12.8 µs [−72.7, +54.9], 3/12), as in the UDP run. A
maximum is the largest value observed in a round, never a bound.

---

## Loss, stalls

None: all 120 arm files are complete, n = 1000 each, under the ladder's rule that
any stall stops the run (`STALL_POLICY=refuse`, 10 s probe timeout).

## What this does not show

- **An interrupt-driven shared-memory path.** `ivshmem`'s doorbell variant (MSI-X
  in the guest, eventfds on the host) is not built. Until it is, shm is compared
  with TCP and UDP as a spinning path against sleeping ones.
- **The CPU cost of spinning.** Not measured. By design the monitor holds its core
  or vCPU for the whole arm — it keeps spinning 50 ms after its last request, then
  looks every 10 ms — and the probe spins for each round trip.
- **VM↔VM, a hypervisor, or a mailbox.** This is host↔guest under KVM; DRIVE OS's
  inter-VM figure is a different quantity, and the comparison document keeps it on
  a row of its own.
- **Isolation.** The guest can read and write every page of that 1 MiB file, and the
  host every page of the BAR; nothing here restricts or tests what else a peer can
  touch, and the monitor validates nothing beyond judging the frame.
- **That KVM is never entered on the data path.** Inferred from BAR2 being RAM, not
  observed (§2).
- **Anything under load, any loss behaviour, any other frame size** — one 64-byte
  slot, one request outstanding, unloaded.
- **Comparability with earlier runs.** New image, new boot, rebuilt monitors: rung
  A-loopback here is 60.2 µs against 52.8 µs in the UDP run, which is why every
  figure above is paired within this run.
- **Any real-time, isolation or safety property.** Unchanged from every A6 record.

## Files

`ladder/raw/` — `lat-<arm>_r<k>.json` per arm and round (summary incl. `proto`, the
probe's scheduling report and, for shm arms, `shm_region`; samples sorted and in
arrival order), `stamp.json` (incl. guest image and disk sha256, QEMU pid and start,
and the shm block: files and source hashes), `order.log`, `probe.log`, the five
host-side monitor logs. The stamp's `order` string states the rule in words written
for two transports; `order.log` holds the orders as run. `ladder/run.log` — the script's output, with the summary
and the paired UDP/TCP and shm/TCP tables. `ladder/guest-console.log` and
`ladder/guest-launch.log` — the guest's boot and the whole run, redacted.
