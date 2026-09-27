# Cyclone DDS on QNX SDP 8.0 — build and configuration notes (2026-09-20)

Upstream: eclipse-cyclonedds/cyclonedds @ 2f0d07d (v11.0.1).

Results of running Cyclone DDS inside the QNX guest are held locally (NC QDL
v7 4.6(i); record `20260920T-dds-crosspartition`). What follows is what the
build and the Linux side establish.

## Established by building it, and on L4T

1. **It cross-compiles for QNX 8.0 aarch64.** `libddsc.so.11.0.1`,
   `ELF 64-bit LSB shared object, ARM aarch64`. Static also builds:
   `libddsc.a`.
2. **One upstream break, and only one.** `src/ddsrt/src/netstat/qnx/netstat.c`
   includes `sys/dcmd_io-net.h`, `net/ifdrvcom.h`, `hw/nicinfo.h` — none of the
   three exists anywhere in the SDP 8.0 tree (io-pkt-era; 8.0 uses io-sock).
   `src/ddsrt/CMakeLists.txt` adds it unconditionally for QNX, so every QNX 8.0
   build fails at that file. Patch is version-gated so SDP 7.x is unaffected.
3. **Upstream ships no SDP 8.0 toolchain entry point** — only `qnx-sdp710-*`.
   Written here as `qnx-sdp800-aarch64le.cmake`.
4. **`find_package(Threads)` is fine on QNX 8.0.** Configure reports
   `Threads_FOUND=TRUE` with `CMAKE_THREAD_LIBS_INIT` empty, and the resulting
   `libddsc` NEEDED list is `libsocket.so.4, libm.so.3, libc.so.6,
   libgcc_s.so.1` — no `libpthread`, no `librt`. Hand-written `-lpthread`
   still fails; that is the real and narrower trap.
5. **The guest image already carries every runtime dependency.** Scanning
   `ifs-demo2.bin` / `disk-qemu` finds `libm.so.3`, `libsocket.so.4`,
   `libc.so.6` and `libgcc_s.so.1`. Dynamic linking would need only
   `libddsc.so.11` staged; static needs nothing.
6. **`idlc` built natively on L4T works** (the Windows host has no host C
   compiler, so it cannot be built there). Generated `av.c`/`av.h` carry no
   licence header — generate at build time, do not commit.
7. **DDS publish/subscribe works on L4T, end to end.** Writer and reader in
   separate processes on the same host: five writes at `rc=0`, and the
   subscriber received the sample with every field intact. A first attempt had
   timed out; the cause was mine, a QoS mismatch (reader RELIABLE/KEEP_ALL
   against a default writer), not discovery and not the platform.

8. **A QNX-side DDS application links, statically.** `qnx-dds-monitor` — a
   subscriber shaped like `ipc-test/qnx-safety-monitor/monitor.c`: reads an
   `AvClaim`, applies the same accept/reject rules (`conf >= 60`,
   `inference_us <= 100000`, `cls <= 7`), publishes an `AvVerdict` — links
   against `libddsc.a` at `rc=0`,
   `ELF 64-bit LSB pie executable, ARM aarch64`. Its `NEEDED` list is
   `libsocket.so.4, libm.so.3, libc.so.6, libgcc_s.so.1` with **zero** libddsc
   dependency, and all four are already in the guest image — so the guest needs
   **one executable staged and nothing else**. Both sides compile the same
   `idlc`-generated `av.c`/`av.h` rather than regenerating independently.
9. **The default interface selection would have broken the demo silently.**
   With `br0` present, Cyclone on L4T enumerated `lo / wlP1p1s0 / docker0 / br0`
   and **selected `wlP1p1s0`** — the wireless interface. It picks one by
   priority, so nothing would have reached the guest and nothing would have
   reported an error. Binding explicitly (`<NetworkInterface name="br0"
   multicast="false"/>` plus `AllowMulticast=false` and explicit `<Peers>`)
   gives `selected interfaces: br0 (index 9 priority 0 mc {})`. Both configs
   are in `dds/`; both sides must be configured, since a one-sided peer list
   converges slowly.

## The guest side — how it is put together

10. **The guest image.** An IFS carrying our rebuilt `startup-qemu-virt` (not a
    QNX-supported configuration) plus `qnx-dds-monitor` and its Cyclone
    config, started from a line inserted into the `[+script] startup-script`
    block AFTER `/proc/boot/startup.sh` -- `mkqnximage` regenerates `ifs.build`
    from templates and discards that line, so the buildfile is committed here.
    L4T publishes `AvClaim` over `br0` with unicast peers and reads the
    guest's `AvVerdict`. The outcome is held locally (NC QDL v7 4.6(i)).

11. **Use `auto` participant indices.** Two processes on one host with the same
    fixed `ParticipantIndex` collide on the ports Cyclone derives from it, and
    nothing reports it. The committed L4T config uses `auto` plus
    `MaxAutoParticipantIndex`; a fixed index is a latent trap, since the
    Compute side normally runs more than one process.

## Not established here

- No timing, latency or throughput claim of any kind.

## Licence

Cyclone DDS is `EPL-2.0 OR BSD-3-Clause`; BSD-3 is elected, compatible with this
MIT repo. The patch keeps upstream headers and SPDX lines intact. **No built
binary of Cyclone DDS or of QNX may enter this repo.**
