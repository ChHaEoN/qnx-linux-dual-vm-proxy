#!/usr/bin/env python3
"""Time a QNX guest boot under KVM, from QEMU exec to "Startup complete".

Runs on the host being measured, so the clock is the host's own monotonic clock
and nothing crosses a network before the timestamp is taken.

THE DISK, AND WHY --snapshot IS NOT OPTIONAL. The guest disk drifts: the
2026-09-18 record states its runs used `disk-qemu` WITHOUT `-snapshot`, so the
guest wrote to it and the board's copy diverged from the PC's. Passing --disk
here always adds `-snapshot`, which sends guest writes to a temporary overlay
and leaves the backing file untouched, so the same bytes are measured on every
run and on every host. The hash is recorded in the stamp; check it matches on
both sides before comparing anything.

Without --disk the boot still completes, but `waitfor /dev/hd0` in the stock
mkqnximage startup.sh has no timeout argument and so takes QNX's 5 s default
EVERY time. Measured 2026-09-20: that wait is 5001.3 ms on a Cortex-A78AE and
5000.3 ms on a Cortex-A72 -- a software timeout does not care how fast the CPU
is, which is exactly why it swamps the metric. A diskless run is therefore
about 92% artefact and is kept only as the control for that finding.

WHAT THIS IS NOT. Not a hypervisor number: the QNX Hypervisor cannot run under
KVM at all (it needs EL2, and ARM KVM does not nest on A78AE). The startup
inside the IFS was rebuilt in this repo with -fno-auto-inc-dec; QNX ships no
such binary, so this is not a QNX-supported configuration.

Usage:
    time-kvm-boot.py --ifs ~/output/ifs-kvmfix.bin --runs 5 --json out.json
"""
import argparse
import json
import os
import platform
import select
import signal
import subprocess
import sys
import time

MARK = b"Startup complete"

# Segment boundaries. A single end-to-end number is easy to dilute: the
# 2026-09-20 run found three separate fixed waits hiding inside one, each of
# which made the two hosts look closer than they are. Recording the boundaries
# lets a reader see WHICH segment differs instead of trusting one total.
MARKS = [
    ("fsevmgr",     b"---> Starting fsevmgr"),
    ("mount_fs",    b"---> Mounting file systems"),
    ("networking",  b"---> Starting Networking"),
    ("sshd",        b"---> Starting sshd"),
    ("startup_end", b"Startup complete"),
    ("banner",      b"QEMU_virt_(aarch64),_KVM_guest"),
]


def _read_cpu_state():
    """Governor and current frequency per CPU, so an unpinned run is visible.

    On this board ~40% of an unpinned idle latency figure is the governor
    (schedutil idle p50 0.319 ms against performance 0.192 ms, measured
    directly). A run that does not record this is not interpretable.
    """
    out = []
    base = "/sys/devices/system/cpu"
    try:
        cpus = sorted(d for d in os.listdir(base)
                      if d.startswith("cpu") and d[3:].isdigit())
    except OSError:
        return out
    for cpu in cpus:
        d = os.path.join(base, cpu, "cpufreq")
        rec = {"cpu": cpu}
        for key, fname in (("governor", "scaling_governor"),
                           ("cur_khz", "scaling_cur_freq"),
                           ("max_khz", "scaling_max_freq")):
            try:
                with open(os.path.join(d, fname)) as fh:
                    rec[key] = fh.read().strip()
            except OSError:
                rec[key] = None
        out.append(rec)
    return out


def _qemu_version(qemu):
    try:
        v = subprocess.check_output([qemu, "--version"],
                                    stderr=subprocess.STDOUT).decode("utf-8", "replace")
        return v.splitlines()[0].strip()
    except Exception as exc:                                   # noqa: BLE001
        return "unknown (%s)" % exc


def one_run(qemu, ifs, smp, mem, timeout_s, disk=None, full_devices=False):
    """One boot. Returns timings in ms and the captured serial bytes."""
    cmd = [qemu,
           "-machine", "virt,gic-version=3",
           "-cpu", "host",
           "-enable-kvm",
           "-smp", str(smp),
           "-m", mem]
    if disk:
        # -snapshot is welded to --disk on purpose; see the module docstring.
        cmd += ["-drive", "file=%s,if=none,id=drv0,format=raw" % disk,
                "-device", "virtio-blk-device,drive=drv0",
                "-snapshot"]
    if full_devices:
        # ORDER IS LOad-BEARING. QEMU's virt machine hands its fixed virtio-mmio
        # slots to -device args strictly in command-line order, and this image's
        # startup.sh binds absolute addresses: devb-virtio at smem=0xa003e00
        # (slot 1) and devr-virtio.so at mem=0xa003a00 (slot 3). blk, then net,
        # then rng. Presenting them in any other order, or omitting one, leaves
        # the rng slot empty, entropy never initialises, and io-sock refuses to
        # start -- which looks exactly like a virtio-net bug (findings.md
        # 2026-07-28). SLIRP rather than tap, and a fixed MAC, so the device set
        # is identical on every host instead of depending on a local bridge.
        cmd += ["-netdev", "user,id=n0",
                "-device", "virtio-net-device,netdev=n0,mac=52:54:00:11:11:11",
                "-object", "rng-random,filename=/dev/urandom,id=rng0",
                "-device", "virtio-rng-device,rng=rng0"]
    cmd += ["-kernel", ifs, "-nographic"]
    t0 = time.monotonic()
    proc = subprocess.Popen(cmd,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, bufsize=0,
                            preexec_fn=os.setsid)
    buf = b""
    first_byte = None
    mark = None
    seen = {}
    try:
        while True:
            left = timeout_s - (time.monotonic() - t0)
            if left <= 0:
                break
            ready, _, _ = select.select([proc.stdout], [], [], min(left, 0.05))
            if not ready:
                continue
            chunk = proc.stdout.read(4096)
            if not chunk:
                break
            now = time.monotonic() - t0
            if first_byte is None:
                first_byte = now
            buf += chunk
            for name, needle in MARKS:
                if name not in seen and needle in buf:
                    seen[name] = now
            if MARK in buf and mark is None:
                mark = now
            if "banner" in seen:
                break
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except OSError:
            pass
        try:
            proc.wait(timeout=5)
        except Exception:                                      # noqa: BLE001
            pass

    ms = lambda v: None if v is None else round(v * 1000.0, 2)   # noqa: E731
    return {
        "ok": mark is not None,
        "ms_to_startup_complete": ms(mark),
        "ms_to_first_byte": ms(first_byte),
        "serial_bytes": len(buf),
        "serial_tail": buf[-200:].decode("utf-8", "replace"),
        "marks_ms": {name: ms(seen.get(name)) for name, _ in MARKS},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ifs", required=True)
    ap.add_argument("--qemu", default="qemu-system-aarch64")
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--warmup", type=int, default=1,
                    help="discarded runs before the timed ones")
    ap.add_argument("--smp", type=int, default=2)
    ap.add_argument("--mem", default="1G")
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--disk", default=None,
                    help="raw guest disk; ALWAYS paired with -snapshot")
    ap.add_argument("--full-devices", action="store_true",
                    help="also present virtio net and rng in the slot order "
                         "this image's startup.sh requires (blk, net, rng)")
    ap.add_argument("--json", default=None)
    ap.add_argument("--label", default="")
    a = ap.parse_args()

    ifs = os.path.expanduser(a.ifs)
    if not os.path.exists(ifs):
        sys.exit("no such IFS: %s" % ifs)

    import hashlib
    with open(ifs, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()

    disk = os.path.expanduser(a.disk) if a.disk else None
    disk_digest = None
    if disk:
        if not os.path.exists(disk):
            sys.exit("no such disk: %s" % disk)
        h = hashlib.sha256()
        with open(disk, "rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
        disk_digest = h.hexdigest()

    stamp = {
        "label": a.label,
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "host": platform.node(),
        "machine": platform.machine(),
        "kernel": platform.release(),
        "qemu": _qemu_version(a.qemu),
        "ifs": os.path.basename(ifs),
        "ifs_sha256": digest,
        "launch": ("-machine virt,gic-version=3 -cpu host -enable-kvm -smp %d -m %s%s"
                   " -kernel <ifs> -nographic"
                   % (a.smp, a.mem,
                      ((" -drive file=<disk>,if=none,id=drv0,format=raw"
                        " -device virtio-blk-device,drive=drv0 -snapshot") if disk else "")
                      + ((" -netdev user,id=n0 -device virtio-net-device,netdev=n0,"
                          "mac=52:54:00:11:11:11 -object rng-random,"
                          "filename=/dev/urandom,id=rng0 -device virtio-rng-device,rng=rng0")
                         if a.full_devices else ""))),
        "disk": os.path.basename(disk) if disk else "none",
        "disk_sha256": disk_digest,
        "snapshot": bool(disk),
        "devices": ("blk,net,rng" if (disk and a.full_devices)
                    else "blk" if disk else "none"),
        "cpu_before": _read_cpu_state(),
    }
    print("host   : %s  %s  %s" % (stamp["host"], stamp["machine"], stamp["kernel"]))
    print("qemu   : %s" % stamp["qemu"])
    print("ifs    : %s  sha256 %s" % (stamp["ifs"], digest[:32]))
    print("devices: %s" % stamp["devices"])
    print("disk   : %s%s" % (stamp["disk"],
                             ("  sha256 %s  (-snapshot)" % disk_digest[:32]) if disk_digest else ""))
    govs = sorted({c.get("governor") for c in stamp["cpu_before"]})
    print("governor: %s" % ", ".join(g or "?" for g in govs))
    print("")

    runs = []
    for i in range(a.warmup + a.runs):
        r = one_run(a.qemu, ifs, a.smp, a.mem, a.timeout, disk, a.full_devices)
        r["index"] = i
        r["warmup"] = i < a.warmup
        runs.append(r)
        tag = "warmup" if r["warmup"] else "timed "
        seg = "  ".join("%s=%s" % (k, r["marks_ms"].get(k))
                        for k in ("mount_fs", "networking", "startup_end", "banner"))
        print("  %s %d: ok=%-5s first_byte=%-8s %s  bytes=%d"
              % (tag, i, r["ok"], r["ms_to_first_byte"], seg, r["serial_bytes"]))
        if not r["ok"]:
            print("       tail: %r" % r["serial_tail"][-120:])

    stamp["cpu_after"] = _read_cpu_state()
    timed = [r["ms_to_startup_complete"] for r in runs
             if not r["warmup"] and r["ok"]]
    timed_sorted = sorted(timed)
    summary = {
        "n_ok": len(timed),
        "n_attempted": a.runs,
        "min_ms": timed_sorted[0] if timed else None,
        "median_ms": timed_sorted[len(timed_sorted) // 2] if timed else None,
        "max_ms": timed_sorted[-1] if timed else None,
    }
    print("")
    print("timed n=%d/%d  min=%s  median=%s  max=%s  (ms to 'Startup complete')"
          % (summary["n_ok"], summary["n_attempted"],
             summary["min_ms"], summary["median_ms"], summary["max_ms"]))

    blob = {"stamp": stamp, "runs": runs, "summary": summary}
    if a.json:
        with open(os.path.expanduser(a.json), "w") as fh:
            json.dump(blob, fh, indent=2)
        print("wrote %s" % a.json)
    return 0 if summary["n_ok"] == a.runs else 1


if __name__ == "__main__":
    sys.exit(main())
