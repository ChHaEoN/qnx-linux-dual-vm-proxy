#!/usr/bin/env python3
"""waitfor_report.py OUT -- run-waitfor.sh's test: change the disk wait's constant (5, 2, 8 s)
and see whether the boot metric follows it (measurement-design.md section 3.7; Phase 3b / A6,
2026-09-26), by the rule the harness's header fixed before any run.

Each boot is boot-iN-WX.json from scripts/twin/time-kvm-boot.py. Per boot: WAIT = mount_fs -
fsevmgr, PRE = fsevmgr, POST = startup_end - mount_fs (serial marks, ms after QEMU exec). Per
image the median of its boots. images.txt holds the sha256 the harness hashed at the start.
"""
import glob
import json
import os
import re
import statistics as st
import sys

IMAGES = ("W5", "W2", "W8")
PATTERN = ["W5", "W2", "W8", "W8", "W2", "W5", "W5", "W2", "W8"]
SHIFT = {"W2": -3000.0, "W8": 3000.0}
TOL, SAME = 100.0, 100.0


def boots_of(out):
    got = []
    for f in glob.glob(os.path.join(out, "boot-i*-W*.json")):
        m = re.search(r"boot-i(\d+)-(W\d)\.json$", f)
        if m:
            got.append((int(m.group(1)), m.group(2), json.load(open(f))))
    return sorted(got)


def segments(run):
    mk = run["marks_ms"]
    if not run.get("ok") or any(mk.get(k) is None for k in ("fsevmgr", "mount_fs", "startup_end")):
        return None
    return {"WAIT": mk["mount_fs"] - mk["fsevmgr"], "PRE": mk["fsevmgr"], "POST": mk["startup_end"] - mk["mount_fs"]}


def main(argv):
    out = argv[0]
    boots = boots_of(out)
    want = {}
    p = os.path.join(out, "images.txt")
    if os.path.exists(p):
        for line in open(p):
            f = line.split()
            if len(f) == 3:
                want[f[0]] = f[2]
    seg = {w: [] for w in IMAGES}
    ok_all = diskless = sha_ok = gov_ok = 0
    for i, w, blob in boots:
        runs = [r for r in blob["runs"] if not r.get("warmup")]
        s = segments(runs[0]) if len(runs) == 1 else None
        if s is not None:
            ok_all += 1
            seg[w].append(s)
        st_ = blob["stamp"]
        diskless += st_.get("devices") == "none" and st_.get("disk") == "none"
        sha_ok += st_.get("ifs_sha256") == want.get(w)
        gov_ok += all(c.get("governor") == "performance" for c in st_.get("cpu_before", [])) and bool(st_.get("cpu_before"))
    nb = len(boots)
    med = {w: {k: (st.median([s[k] for s in seg[w]]) if seg[w] else float("nan")) for k in ("WAIT", "PRE", "POST")}
           for w in IMAGES}
    ok = {"M1": nb > 0 and ok_all == nb,
          "M2": [w for _, w, _ in boots] == PATTERN,
          "M3": nb > 0 and diskless == nb,
          "M4": nb > 0 and sha_ok == nb,
          "M5": nb > 0 and gov_ok == nb}
    print("  boots %d" % nb)
    print("  M1 boots that reached Startup complete with every mark: %d/%d -> %s" % (ok_all, nb, "ok" if ok["M1"] else "FAILED"))
    print("  M2 the pattern %s -> %s" % (" ".join(w for _, w, _ in boots), "ok" if ok["M2"] else "FAILED"))
    print("  M3 diskless boots: %d/%d -> %s" % (diskless, nb, "ok" if ok["M3"] else "FAILED"))
    print("  M4 image sha256 as hashed at the start: %d/%d -> %s" % (sha_ok, nb, "ok" if ok["M4"] else "FAILED"))
    print("  M5 governor pinned: %d/%d -> %s" % (gov_ok, nb, "ok" if ok["M5"] else "FAILED"))
    for w in IMAGES:
        print("  %s  WAIT %s  PRE %s  POST %s  (median %.1f / %.1f / %.1f ms)"
              % (w, [round(s["WAIT"], 1) for s in seg[w]], [round(s["PRE"], 1) for s in seg[w]],
                 [round(s["POST"], 1) for s in seg[w]], med[w]["WAIT"], med[w]["PRE"], med[w]["POST"]))
    base = [m for m in ok]

    def verdict(v):
        failed = [m for m in base if not ok[m]]
        return "VOID (%s failed)" % ", ".join(failed) if failed else v

    for pn, w in (("P1", "W2"), ("P2", "W8")):
        d = med[w]["WAIT"] - med["W5"]["WAIT"]
        print("  %s  WAIT(%s) - WAIT(W5) %+.1f ms (predicted %+.0f within %.0f) -> %s"
              % (pn, w, d, SHIFT[w], TOL, verdict("HELD" if abs(d - SHIFT[w]) <= TOL else "REFUTED")))
    spread = {k: max(med[w][k] for w in IMAGES) - min(med[w][k] for w in IMAGES) for k in ("PRE", "POST")}
    print("  P3  nothing else moves: PRE spread %.1f, POST spread %.1f ms (want each <= %.0f) -> %s"
          % (spread["PRE"], spread["POST"], SAME,
             verdict("HELD" if spread["PRE"] <= SAME and spread["POST"] <= SAME else "REFUTED")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
