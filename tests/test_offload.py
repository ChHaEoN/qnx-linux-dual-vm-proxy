"""The receive-offload test (Phase 3b / A6, 2026-09-27): the report on synthetic runs where turning the
receive offloads off makes the read cheap, where it changes nothing, and where a boot's offloads are not
its configuration's; the two images; and the harness's header."""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
REPORT = os.path.join(GC, "offload_report.py")
HARNESS = os.path.join(GC, "run-offload.sh")
MON = os.path.join(HERE, "..", "ipc-test", "qnx-safety-monitor")
BASH = shutil.which("bash")
K, N, WARM = 12, 1000, 200
FR = N + WARM
ON = "\toptions=4c07bb<RXCSUM,TXCSUM,VLAN_MTU,VLAN_HWTAGGING,JUMBO_MTU,VLAN_HWCSUM,TSO4,TSO6,LRO,VLAN_HWTSO,LINKSTATE,TXCSUM_IPV6>"
OFF = "\toptions=4c03ba<TXCSUM,VLAN_MTU,VLAN_HWTAGGING,JUMBO_MTU,VLAN_HWCSUM,TSO4,TSO6,VLAN_HWTSO,LINKSTATE,TXCSUM_IPV6>"


def _run(out, r2=None, wrong=None):
    r2 = r2 or {"N1": 12.3, "F1": 7.2}
    out.mkdir()
    (out / "stamp.json").write_text(json.dumps({"n": N, "k": K, "warmup": WARM}))
    offl = []
    for r in range(1, K + 1):
        for c in ("N1", "F1"):
            opts = ON if c == "N1" else OFF
            if wrong == (c, r):
                opts = ON
            con = ["vtnet0: flags=8843<UP,BROADCAST,RUNNING,SIMPLEX,MULTICAST> metric 0 mtu 1500", opts,
                   "\tnd6 options=1<PERFORMNUD>"]
            offl.append("%s_r%d tap-qnx tx-checksumming: %s tcp-segmentation-offload: %s "
                        % (c, r, "on" if c == "N1" else "off", "on" if c == "N1" else "off"))
            for mode, port, reads in (("d", 7120, 1), ("s", 7122, 2)):
                rtt = 172.0 + (3.0 if c == "F1" else 0.0) + (r2[c] + 0.5 if mode == "s" else 0.0) + 0.2 * (r % 3)
                s = {"p50_ms": rtt / 1000.0, "n": N, "bad": 0, "rejected_by_monitor": 0, "frame_bytes": 64}
                (out / ("lat-%s%s64_r%d.json" % (c, mode, r))).write_text(json.dumps({"summary": s}))
                two = mode == "s"
                name = "default" if mode == "d" else "split"
                con.append("sweep: reads :%d %s frames=%d reads=%d" % (port, name, FR, reads * FR))
                con.append("sweep: timing :%d %s frames=%d r2_n=%d r2_p50_ns=%d w_p50_ns=25000 svc_p50_ns=%d"
                           % (port, name, FR, FR if two else 0, int(r2[c] * 1000) if two else -1,
                              int((25.5 + (r2[c] if two else 0)) * 1000)))
            (out / ("console-%s_r%d.log" % (c, r))).write_text("\n".join(con) + "\n")
            bl = ["op %s regime spaced n 300 p10_ns 1000 p50_ns %d p90_ns 3000 mean_ns 2000" % (o, v)
                  for o, v in (("kcall", 400), ("zero", 2800), ("msg", 2500), ("sock", 7100))] + ["done"]
            (out / ("bench-%s_r%d.txt" % (c, r))).write_text("\n".join(bl) + "\n")
    (out / "offloads.log").write_text("\n".join(offl) + "\n")


def _report(out):
    r = subprocess.run([sys.executable, REPORT, str(out)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _line(s, tag):
    return s.split("  " + tag + " ")[1].split("\n")[0]


def test_offloads_that_hold_the_cost_hold_everything(tmp_path):
    _run(tmp_path / "o")
    s = _report(tmp_path / "o")
    assert "FAILED" not in s, s
    for p in ("P1", "P2", "P3"):
        assert "-> HELD" in _line(s, p), s


def test_offloads_that_do_not_matter_refute_everything(tmp_path):
    _run(tmp_path / "o", r2={"N1": 12.3, "F1": 12.1})
    s = _report(tmp_path / "o")
    for p in ("P1", "P2", "P3"):
        assert "-> REFUTED" in _line(s, p), s


def test_a_boot_whose_offloads_are_not_its_configuration_voids(tmp_path):
    _run(tmp_path / "o", wrong=("F1", 6))
    s = _report(tmp_path / "o")
    assert "-> FAILED" in _line(s, "M3") and "VOID (M3 failed)" in _line(s, "P1"), s


def test_the_two_images_differ_in_the_ifconfig_lines_only():
    on = open(os.path.join(MON, "ifs-offon.build"), encoding="utf-8").read()
    off = open(os.path.join(MON, "ifs-offoff.build"), encoding="utf-8").read()
    assert "\nifconfig vtnet0\non -C 0 /proc/boot/qnx-echo-server-timed 7120 &" in on and "-lro" not in on.split("IFS Build file")[1]
    assert "\nifconfig vtnet0 -lro -rxcsum\nifconfig vtnet0\non -C 0 /proc/boot/qnx-echo-server-timed 7120 &" in off


def test_the_harness_parses_and_states_its_rule_and_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    text = open(HARNESS, encoding="utf-8").read()
    head, body = text.split("\nset -u\n", 1)
    for s in ("It is not to be amended", "The owner asked for this run",
              "P1 turning the receive offloads off shortens the second read: r2(F1s64) - r2(N1s64) <= -3 us.",
              "P2 without them the read is as cheap as a loopback read: r2(F1s64) <= 8.5 us.",
              "P3 the round trip's step follows: (F1s64 - F1d64) - (N1s64 - N1d64) <= -3 us.",
              "M3 the offloads were what each configuration says"):
        assert s in head, s
    assert "ARMS=(N1d64 N1s64 F1d64 F1s64)" in body and '"$OUT/offloads.log"' in body
