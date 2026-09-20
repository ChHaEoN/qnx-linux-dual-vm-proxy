# Cyclone DDS on QNX SDP 8.0 — what is established (2026-09-20)

Upstream: eclipse-cyclonedds/cyclonedds @ 2f0d07d (v11.0.1).

## Established by running it

1. **It cross-compiles for QNX 8.0 aarch64.** `libddsc.so.11.0.1`, 1,665,376
   bytes, `ELF 64-bit LSB shared object, ARM aarch64`. Static also builds:
   `libddsc.a`.
2. **One upstream break, and only one.** `src/ddsrt/src/netstat/qnx/netstat.c`
   includes `sys/dcmd_io-net.h`, `net/ifdrvcom.h`, `hw/nicinfo.h` — none of the
   three exists anywhere in the SDP 8.0 tree (io-pkt-era; 8.0 uses io-sock).
   `src/ddsrt/CMakeLists.txt` adds it unconditionally for QNX, so every QNX 8.0
   build fails at that file. 170 of 227 objects built before it. Patch is
   version-gated so SDP 7.x is unaffected.
3. **Upstream ships no SDP 8.0 toolchain entry point** — only `qnx-sdp710-*`.
   Written here as `qnx-sdp800-aarch64le.cmake`.
4. **`find_package(Threads)` is fine on QNX 8.0.** Configure reports
   `Threads_FOUND=TRUE` with `CMAKE_THREAD_LIBS_INIT` empty, and the resulting
   `libddsc` NEEDED list is `libsocket.so.4, libm.so.3, libc.so.6,
   libgcc_s.so.1` — no `libpthread`, no `librt`. Hand-written `-lpthread`
   still fails; that is the real and narrower trap.
5. **The guest image already carries every runtime dependency.** Scanning
   `ifs-demo2.bin` / `disk-qemu`: `libm.so.3` 2/22, `libsocket.so.4` 6/48,
   `libc.so.6` 40/158, `libgcc_s.so.1` 38/125. Dynamic linking would need only
   `libddsc.so.11` staged; static needs nothing.
6. **`idlc` built natively on L4T works** (the Windows host has no host C
   compiler, so it cannot be built there). Generated `av.c`/`av.h` carry no
   licence header — generate at build time, do not commit.
7. **DDS publish/subscribe works on L4T, end to end.** Writer and reader in
   separate processes on the same host: `matched readers=1 after 100 ms`, five
   writes at `rc=0`, and the subscriber received the sample with every field
   intact (`seq=1 cls=3 conf=95 us=124`). A first attempt had timed out; the
   cause was mine, a QoS mismatch (reader RELIABLE/KEEP_ALL against a default
   writer), not discovery and not the platform. Note the match took **100 ms**,
   so upstream issue #2243's 4-5 s Orin/QNX discovery delay did not reproduce
   here -- on loopback, with both ends on L4T.

8. **A QNX-side DDS application links, statically.** `qnx-dds-monitor` — a
   subscriber shaped like `ipc-test/qnx-safety-monitor/monitor.c`: reads an
   `AvClaim`, applies the same accept/reject rules (`conf >= 60`,
   `inference_us <= 100000`, `cls <= 7`), publishes an `AvVerdict` — links
   against `libddsc.a` at `rc=0`, 1,480,600 bytes,
   `ELF 64-bit LSB pie executable, ARM aarch64`. Its `NEEDED` list is
   `libsocket.so.4, libm.so.3, libc.so.6, libgcc_s.so.1` with **zero** libddsc
   dependency, and all four are already in the guest image — so the guest needs
   **one executable staged and nothing else**. Both sides compile the same
   `idlc`-generated `av.c`/`av.h` rather than regenerating independently.
9. **The default interface selection would have broken the demo silently.**
   With `br0` present, Cyclone enumerated `lo / wlP1p1s0 / docker0 / br0` and
   **selected `wlP1p1s0`** — the wireless interface. It picks one by priority,
   so nothing would have reached the guest and nothing would have reported an
   error. Binding explicitly (`<NetworkInterface name="br0" multicast="false"/>`
   plus `AllowMulticast=false` and explicit `<Peers>`) gives
   `selected interfaces: br0 (index 9 priority 0 mc {})`. Both configs are in
   `dds/`; both sides must be configured, since a one-sided peer list converges
   slowly.

10. **Cyclone DDS runs inside the QNX KVM guest, and judges across the
    partition.** The guest boots with an IFS carrying our rebuilt
    `startup-qemu-virt` (entry `40081ab8`; the SDP's `40081da8` still hangs
    after 17 bytes) plus `qnx-dds-monitor` and its Cyclone config, started from
    a line inserted into the `[+script] startup-script` block AFTER
    `/proc/boot/startup.sh` -- `mkqnximage` regenerates `ifs.build` from
    templates and discards that line, so the buildfile is committed here.
    Console: `qnx-dds-monitor: waiting for claims`.
    L4T published `AvClaim` over `br0` with unicast peers; the guest matched in
    100 ms and judged every sample, including all four rejection reasons:
    `cls=42 -> REJECT(1)`, `conf=10 -> REJECT(3)`, `conf=200 -> REJECT(2)`,
    `us=999999 -> REJECT(4)`, `good -> ACCEPT(0)`. That is the same verdict
    logic as the TCP monitor, carried over DDS. Functional only; no timing,
    latency or throughput claim.

11. **The return path works, and the first failure was my configuration.**
    An `AvVerdict` reader on L4T first received **0 samples**. The cause was a
    fixed `ParticipantIndex=1` shared by two processes on the same host, not
    the transport and not the partition. With `auto` plus
    `MaxAutoParticipantIndex`, L4T received all five verdicts
    (`VERDICT seq=1..5 accepted=1 reason=0`). The committed L4T config now uses
    `auto`; a fixed index is a latent trap, since the Compute side normally
    runs more than one process. So the exchange is bidirectional: L4T publishes
    a claim, the QNX guest judges it, L4T receives the verdict.

## Not yet established
- No timing, latency or throughput claim of any kind.

## Licence

Cyclone DDS is `EPL-2.0 OR BSD-3-Clause`; BSD-3 is elected, compatible with this
MIT repo. The patch keeps upstream headers and SPDX lines intact. **No built
binary of Cyclone DDS or of QNX may enter this repo.**
