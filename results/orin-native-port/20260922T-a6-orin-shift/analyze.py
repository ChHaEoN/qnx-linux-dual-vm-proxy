#!/usr/bin/env python3
"""analyze.py -- the figures in results.md that come from this record's own files,
re-derived from session1/ and session2/ (levels quoted from other records are not).

    python analyze.py            (run from this directory)

Levels are medians over a boot's rounds of each round's p50 (k = 4). A
condition's level is the mean of its boots (and, in session 1, of both snapshot
settings). "cross" is D-guest - B-bridge, paired within each round. KVM figures
come from the per-arm snapshots (KVM_STATS=1 ladders only): "idle" rates are per
second during A-loopback, which never touches the guest; per-exchange figures
are D-guest's deltas minus the same round's A-loopback rate, over 1200 exchanges.
"""
import glob
import json
import os
import re
import statistics as st

HERE = os.path.dirname(os.path.abspath(__file__))
ARMS = ["A-loopback", "B-bridge", "C-null", "D-guest", "D-udp"]
COUNTERS = ["exits", "mmio_exit_user", "mmio_exit_kernel", "wfi_exit_stat", "halt_wakeup"]


def rounds(d, arm):
    out = {}
    for f in glob.glob(os.path.join(d, "lat-%s_r*.json" % arm)):
        s = json.load(open(f))["summary"]
        out[int(s["tag"].rsplit("_r", 1)[1])] = s["p50_ms"] * 1000.0
    return out


def kvm(d, arm):
    out = {}
    for f in glob.glob(os.path.join(d, "kvm-%s_r*.json" % arm)):
        r = int(os.path.basename(f)[:-5].rsplit("_r", 1)[1])
        k = json.load(open(f))
        dt = (k["after"]["t_ns"] - k["before"]["t_ns"]) / 1e9
        qp = str(k["before"]["qemu_pid"])
        dc = {c: k["after"]["counters"][c] - k["before"]["counters"][c] for c in COUNTERS}
        a, b = k["after"]["threads"].get(qp), k["before"]["threads"].get(qp)
        dc["main_run_ns"] = a["run_ns"] - b["run_ns"]
        dc["main_slices"] = a["slices"] - b["slices"]
        dc["other_run_ns"] = sum(t["run_ns"] - k["before"]["threads"][tid]["run_ns"]
                                 for tid, t in k["after"]["threads"].items()
                                 if tid != qp and tid in k["before"]["threads"])
        out[r] = (dt, dc)
    return out


def boots(session):
    for bd in sorted(glob.glob(os.path.join(HERE, session, "b*-*")),
                     key=lambda p: int(re.search(r"b(\d+)-", os.path.basename(p)).group(1))):
        m = re.match(r"b(\d+)-([A-Z])$", os.path.basename(bd))
        yield int(m.group(1)), m.group(2), bd


def cell(d):
    row = {a: st.median(rounds(d, a).values()) for a in ARMS}
    ra, rb = rounds(d, "D-guest"), rounds(d, "B-bridge")
    row["cross"] = st.median(ra[r] - rb[r] for r in ra)
    row["k"] = len(ra)
    if glob.glob(os.path.join(d, "kvm-A-loopback_r*.json")):
        bg, dg = kvm(d, "A-loopback"), kvm(d, "D-guest")
        for c in ("wfi_exit_stat", "exits"):
            row["idle_%s_per_s" % c] = st.median(v[1][c] / v[0] for v in bg.values())
        for c in COUNTERS + ["main_run_ns", "other_run_ns"]:
            row["xch_" + c] = st.median((dg[r][1][c] - bg[r][1][c] / bg[r][0] * dg[r][0]) / 1200.0 for r in dg)
        row["xch_main_run_us"] = row.pop("xch_main_run_ns") / 1000.0
        row["xch_other_run_us"] = row.pop("xch_other_run_ns") / 1000.0
        # Raw (not background-corrected): slices per 1200 exchanges, and CPU per slice.
        row["main_slices_min"] = min(v[1]["main_slices"] for v in dg.values())
        row["main_slices_max"] = max(v[1]["main_slices"] for v in dg.values())
        row["main_us_per_slice"] = st.median(v[1]["main_run_ns"] / v[1]["main_slices"] / 1000.0 for v in dg.values())
    return row


def services(bd):
    t = open(os.path.join(bd, "guest-console.log"), "rb").read().replace(b"\0", b"").decode("utf-8", "replace")
    return " ".join(x for x, s in (("cfg", "shm configured:"), ("shm", "serving shm on ivshmem"),
                                   ("kick", "serving shm-kick")) if s in t)


def report(session, snaps):
    print("=" * 100)
    print(session)
    cells = {}
    for i, cond, bd in boots(session):
        for kv in snaps:
            d = os.path.join(bd, "kvm" + kv)
            if os.path.isdir(d):
                cells[(i, cond, kv)] = cell(d)
        print("  boot %d %s services: '%s'" % (i, cond, services(bd)))
    print("  %-4s %-4s %-3s %2s " % ("boot", "cond", "kvm", "k") + "".join("%10s" % a[:9] for a in ARMS + ["cross"]))
    for (i, c, kv), row in sorted(cells.items()):
        print("  %-4d %-4s %-3s %2d " % (i, c, kv, row["k"]) + "".join("%10.1f" % row[a] for a in ARMS + ["cross"]))
    conds = sorted({c for (_i, c, _k) in cells}, key="ABSNC".index)

    def mean(cond, key, kv=None):
        v = [row[key] for (i, c, k), row in cells.items() if c == cond and (kv is None or k == kv) and key in row]
        return st.mean(v) if v else float("nan")

    print("  condition means (both boots%s):" % (", both snapshot settings" if len(snaps) == 2 else ""))
    keys = ["D-guest", "C-null", "D-udp", "cross", "A-loopback", "B-bridge",
            "idle_wfi_exit_stat_per_s", "idle_exits_per_s", "xch_exits", "xch_mmio_exit_user",
            "xch_mmio_exit_kernel", "xch_wfi_exit_stat", "xch_main_run_us", "xch_other_run_us",
            "main_us_per_slice"]
    for key in keys:
        print("    %-26s " % key + "  ".join("%s %8.2f" % (c, mean(c, key, "1" if key.startswith(("idle", "xch")) else None))
                                            for c in conds))
    lo = min(row.get("main_slices_min", 10**9) for row in cells.values())
    hi = max(row.get("main_slices_max", 0) for row in cells.values())
    if hi:
        print("  QEMU main-thread slices per 1200 D-guest exchanges, every KVM_STATS=1 round of every boot: %d..%d" % (lo, hi))
    return cells, mean, conds


c1, m1, _ = report("session1", ["0", "1"])
print("  contrasts (boot-level means): B-A devices+server, C-B image, C-A all")
for key in ("D-guest", "cross", "C-null", "D-udp", "xch_main_run_us", "main_us_per_slice"):
    a, b, c = (m1(x, key) for x in "ABC")
    print("    %-8s B-A %+6.1f   C-B %+6.1f   C-A %+6.1f" % (key, b - a, c - b, c - a))
print("  snapshots, KVM_STATS=1 minus 0 within each boot (D-guest):",
      " ".join("b%d%s %+.1f" % (i, c, c1[(i, c, "1")]["D-guest"] - c1[(i, c, "0")]["D-guest"])
               for (i, c, kv) in sorted(c1) if kv == "1"),
      "median %+.1f" % st.median(c1[(i, c, "1")]["D-guest"] - c1[(i, c, "0")]["D-guest"]
                                for (i, c, kv) in c1 if kv == "1"))

c2, m2, _ = report("session2", ["1"])
print("  contrasts (boot-level means): S-B polled monitor, N-S devc-virtio (+shmcfg), C-N shmkick monitor, C-B all")
for key in ("D-guest", "cross", "C-null", "D-udp", "idle_wfi_exit_stat_per_s", "xch_main_run_us",
            "xch_other_run_us", "main_us_per_slice", "xch_exits"):
    b, s, n, c = (m2(x, key) for x in "BSNC")
    print("    %-26s S-B %+7.1f   N-S %+7.1f   C-N %+7.1f   C-B %+7.1f" % (key, s - b, n - s, c - n, c - b))
for sess, cells in (("session1", c1), ("session2", c2)):
    print("  %s drift, second minus first boot of each condition:" % sess)
    for cond in sorted({c for (_i, c, _k) in cells}, key="ABSNC".index):
        bs = sorted({i for (i, c, _k) in cells if c == cond})
        parts = []
        for key in ("D-guest", "C-null", "D-udp"):
            lv = [st.mean(cells[(i, cond, k)][key] for k in "01" if (i, cond, k) in cells) for i in bs]
            parts.append("%s %+.1f" % (key, lv[-1] - lv[0]))
        print("    %s boots %s: %s" % (cond, bs, "  ".join(parts)))
