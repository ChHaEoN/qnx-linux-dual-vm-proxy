"""The guest path's bump and fast path mapped (Phase 3b / A6, 2026-09-26): the report on synthetic
rounds where the fast path begins at one MSS, where it begins elsewhere, and where a read count or
a counter is missing; and the harness's header."""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
REPORT = os.path.join(GC, "mss_report.py")
HARNESS = os.path.join(GC, "run-mss.sh")
BASH = shutil.which("bash")
G = (1024, 1088, 1152, 1216, 1280, 1344, 1408, 1447, 1448, 1449, 1472, 1536)
B = (1024, 1280, 1448, 1449)
ARMS = ["G%d" % s for s in G] + ["B%d" % s for s in B]
K, N, WARM = 16, 1000, 200


def _cost_mss(a):
    s = int(a[1:])
    if a[0] == "G":
        return 0.005 * s + (10.0 if 1152 < s <= 1448 else 0.0) - (8.0 if s > 1448 else 0.0)
    return 0.002 * s + (6.0 if s > 1448 else 0.0)


def _run(out, cost=_cost_mss, edge=1448, drop_read=None, drop_counter=None):
    out.mkdir()
    (out / "stamp.json").write_text(json.dumps({"n": N, "k": K, "warmup": WARM}))
    order, guest, ns, counters = [], ["sweep: reads :7121 greedy frames=3 reads=3"], [], []
    ex = N + WARM
    for r in range(1, K + 1):
        row = ARMS[r % len(ARMS):] + ARMS[:r % len(ARMS)]
        order.append("round %d order: %s" % (r, " ".join(row)))
        level = 2.0 * ((r * 5) % 7)
        for a in row:
            s = int(a[1:])
            wob = 0.2 * (((r * 11 + s) % 5) - 2)
            summ = {"p50_ms": ((180.0 if a[0] == "G" else 55.0) + level + cost(a) + wob) / 1000.0, "n": N, "bad": 0,
                    "rejected_by_monitor": 0, "frame_bytes": s}
            (out / ("lat-%s_r%d.json" % (a, r))).write_text(json.dumps({"summary": summ}))
            if drop_read != (a, r):
                line = "sweep: reads :7121 greedy frames=%d reads=%d" % (ex, ex)
                (guest if a[0] == "G" else ns).append(line)
            p = 2 if s > edge else 1
            if drop_counter != (a, r):
                counters += ["%s_r%d dev before 0 0 0 0" % (a, r),
                             "%s_r%d dev after %d %d %d %d" % (a, r, p * ex, p * ex, ex * (s + 66 * p), ex * (s + 66 * p))]
    (out / "order.log").write_text("\n".join(order) + "\n")
    (out / "guest-console.log").write_text("\n".join(guest) + "\n")
    (out / "mss-ns.log").write_text("\n".join(ns) + "\n")
    (out / "counters.log").write_text("\n".join(counters) + "\n")


def _report(out):
    r = subprocess.run([sys.executable, REPORT, str(out)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _line(s, tag):
    return s.split("  " + tag + " ")[1].split("\n")[0]


def test_a_fast_path_from_one_mss_holds_everything(tmp_path):
    _run(tmp_path / "o")
    s = _report(tmp_path / "o")
    assert "FAILED" not in s, s
    for p in ("P1", "P2", "P3", "P4"):
        assert "-> HELD" in _line(s, p), s
    assert "+10." in _line(s, "G1152 -> G1216").split("[")[0], s


def test_a_fast_path_that_starts_before_the_mss_refutes_p1_and_p4(tmp_path):
    def cost(a):
        s = int(a[1:])
        if a[0] == "G":
            return 0.005 * s + (10.0 if 1152 < s <= 1344 else 0.0) - (8.0 if s > 1344 else 0.0)
        return 0.002 * s + (6.0 if s > 1448 else 0.0)
    _run(tmp_path / "o", cost=cost, edge=1344)
    s = _report(tmp_path / "o")
    assert "-> REFUTED" in _line(s, "P1") and "-> REFUTED" in _line(s, "P2") and "-> REFUTED" in _line(s, "P4"), s
    assert "-> HELD" in _line(s, "P3"), s


def test_a_missing_read_count_or_counter_voids(tmp_path):
    _run(tmp_path / "a", drop_read=("G1216", 4))
    s = _report(tmp_path / "a")
    assert "-> FAILED" in _line(s, "M2") and "G: 191 connections" in s and "VOID" in _line(s, "P1"), s
    _run(tmp_path / "b", drop_counter=("B1449", 2))
    s = _report(tmp_path / "b")
    assert "-> FAILED" in _line(s, "M3"), s


def test_the_harness_parses_and_states_its_rule_and_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    text = open(HARNESS, encoding="utf-8").read()
    head, body = text.split("\nset -u\n", 1)
    for s in ("It is not to be amended", "The owner asked for this run",
              "P1 the fast path begins at one MSS: G1449 - G1448 <= -8 us.",
              "P2 one packet each way up to one MSS, two above it",
              "P3 the host path's step is at the same byte: B1449 - B1448 >= +3 us.",
              "P4 the bump replicates and holds to the MSS", "M2 one read per frame"):
        assert s in head, s
    assert "ARMS=(" + " ".join(ARMS) + ")" in body
    assert '"$MSS_BIN" "$PORT" greedy' in body and 'PROBE_FRAME_BYTES="${a:1}" m_probe' in body
