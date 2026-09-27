"""The edge test (Phase 3b / A6, 2026-09-26): the report on synthetic runs
with the edge at 1460/1461, with it elsewhere, and with a read count missing; and the harness's
header."""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
REPORT = os.path.join(GC, "edge_report.py")
HARNESS = os.path.join(GC, "run-edge.sh")
BASH = shutil.which("bash")
G = (1448, 1449, 1452, 1456, 1458, 1459, 1460, 1461, 1462, 1464, 1468, 1472)
B = (1460, 1461)
ARMS = ["G%d" % s for s in G] + ["B%d" % s for s in B]
K, N, WARM = 14, 1000, 200


def _run(out, edge=1460, drop_read=None):
    out.mkdir()
    (out / "stamp.json").write_text(json.dumps({"n": N, "k": K, "warmup": WARM}))
    order, guest, ns, counters = [], [], [], []
    ex = N + WARM
    for r in range(1, K + 1):
        row = ARMS[r % len(ARMS):] + ARMS[:r % len(ARMS)]
        order.append("round %d order: %s" % (r, " ".join(row)))
        level = 2.0 * ((r * 5) % 7)
        for a in row:
            s = int(a[1:])
            if a[0] == "G":
                c = 196.0 + (5.0 if s > 1448 else 0.0) - (22.0 if s > edge else 0.0)
            else:
                c = 59.0 + 4.0
            wob = 0.2 * (((r * 11 + s) % 5) - 2)
            summ = {"p50_ms": (c + level + wob) / 1000.0, "n": N, "bad": 0, "rejected_by_monitor": 0, "frame_bytes": s}
            (out / ("lat-%s_r%d.json" % (a, r))).write_text(json.dumps({"summary": summ}))
            if drop_read != (a, r):
                (guest if a[0] == "G" else ns).append("sweep: reads :7121 greedy frames=%d reads=%d" % (ex, ex))
            p = 2 if s > 1448 else 1
            counters += ["%s_r%d dev before 0 0 0 0" % (a, r),
                         "%s_r%d dev after %d %d %d %d" % (a, r, p * ex, p * ex, ex * (s + 66 * p), ex * (s + 66 * p))]
    (out / "order.log").write_text("\n".join(order) + "\n")
    (out / "guest-console.log").write_text("\n".join(guest) + "\n")
    (out / "edge-ns.log").write_text("\n".join(ns) + "\n")
    (out / "counters.log").write_text("\n".join(counters) + "\n")


def _report(out):
    r = subprocess.run([sys.executable, REPORT, str(out)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _line(s, tag):
    return s.split("  " + tag + " ")[1].split("\n")[0]


def test_an_edge_at_1460_holds_everything(tmp_path):
    _run(tmp_path / "o")
    s = _report(tmp_path / "o")
    assert "FAILED" not in s, s
    for p in ("P1", "P2", "P3", "P4", "P5"):
        assert "-> HELD" in _line(s, p), s


def test_an_edge_elsewhere_refutes_p1_and_one_flank(tmp_path):
    _run(tmp_path / "o", edge=1456)
    s = _report(tmp_path / "o")
    assert "-> REFUTED" in _line(s, "P1") and "-> REFUTED" in _line(s, "P2") and "-> HELD" in _line(s, "P3"), s
    assert float(_line(s, "G1456 -> G1458").split("[")[0]) <= -20, s


def test_a_missing_read_count_voids(tmp_path):
    _run(tmp_path / "o", drop_read=("G1452", 3))
    s = _report(tmp_path / "o")
    assert "-> FAILED" in _line(s, "M2") and "VOID (M2 failed)" in _line(s, "P1"), s


def test_the_harness_parses_and_states_its_rule_and_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    text = open(HARNESS, encoding="utf-8").read()
    head, body = text.split("\nset -u\n", 1)
    for s in ("It is not to be amended", "The owner asked for this run",
              "P1 the edge is at 1460/1461: G1461 - G1460 <= -8 us.", "P2 flat before it", "P3 flat after it",
              "P4 the host path has no edge there", "P5 two packets each way", "d(3)..d(12), 98.7%, at"):
        assert s in head, s
    assert "ARMS=(" + " ".join(ARMS) + ")" in body and '"$OUT/edge-ns.log"' in body and "lan_default_route" in body
