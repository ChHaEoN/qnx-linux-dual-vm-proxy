"""Paired within-round contrasts for the llm interference run, at every
percentile the probe records -- the summary in lib-measure.sh reports p50 only,
and a safety partition is judged on its tail."""
import glob
import json
import os
import re
import statistics as st

REC = (r"E:\Project\qnx-linux-dual-vm-proxy\results\orin-native-port"
       r"\20260923T-a6-orin-llm-interference")
ARMS = ["idle", "llm", "gpu", "idle2"]
PCTS = [("p50_ms", "p50"), ("p90_ms", "p90"), ("p99_ms", "p99"),
        ("p999_ms", "p99.9"), ("max_ms", "max")]


def load():
    by = {a: {} for a in ARMS}
    for f in glob.glob(os.path.join(REC, "lat-*.json")):
        m = re.match(r"lat-(.+)_r(\d+)\.json$", os.path.basename(f))
        if not m:
            continue
        arm, r = m.group(1), int(m.group(2))
        d = json.load(open(f, encoding="utf-8"))
        by.setdefault(arm, {})[r] = d.get("summary", d)
    return by


def band(xs):
    """The same band the harness reports: min and max of the k round values."""
    return min(xs), max(xs)


by = load()
rounds = sorted(by["idle"])
print("rounds: %d, arms: %s" % (len(rounds), ", ".join("%s=%d" % (a, len(by[a])) for a in ARMS)))
print()
print("%-6s %-7s %9s %9s %9s  %s" % ("arm", "pct", "median", "min", "max", "paired vs idle: median [min,max] us"))
for key, label in PCTS:
    for arm in ARMS:
        vals = [by[arm][r][key] for r in rounds]
        med = st.median(vals)
        lo, hi = band(vals)
        if arm == "idle":
            extra = "(reference)"
        else:
            d = [(by[arm][r][key] - by["idle"][r][key]) * 1000.0 for r in rounds]
            dl, dh = band(d)
            extra = "%+7.1f [%+7.1f,%+7.1f]" % (st.median(d), dl, dh)
        print("%-6s %-7s %9.4f %9.4f %9.4f  %s" % (arm, label, med, lo, hi, extra))
    print()

# Did the llm arm actually behave like an LLM in THIS run, window by window?
print("=== what the SoC did during each arm's probe window (from tegra-*.log) ===")
print("%-6s %6s %6s %6s %6s" % ("arm", "GR3Dmd", "EMCu", "EMCMHz", "n"))
for arm in ARMS:
    gr, ep, ec, n = [], [], [], 0
    for r in rounds:
        p = os.path.join(REC, "tegra-%s_r%d.log" % (arm, r))
        if not os.path.exists(p):
            continue
        for line in open(p, errors="replace"):
            m = re.search(r"GR3D_FREQ (\d+)%", line)
            if m:
                gr.append(int(m.group(1)))
            m = re.search(r"EMC_FREQ (\d+)%@(\d+)", line)
            if m:
                ep.append(int(m.group(1))); ec.append(int(m.group(2)))
            n += 1
    f = lambda xs: round(st.median(xs), 1) if xs else None
    print("%-6s %6s %6s %6s %6d" % (arm, f(gr), f(ep), f(ec), len(gr)))
