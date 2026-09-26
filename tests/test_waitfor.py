"""The boot-timeout falsification (Phase 3b / A6, 2026-09-26): the report on synthetic boot records
where the wait follows the constant, where it does not, and where a check fails; and the
harness's header."""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
REPORT = os.path.join(GC, "waitfor_report.py")
HARNESS = os.path.join(GC, "run-waitfor.sh")
BASH = shutil.which("bash")
PAT = ["W5", "W2", "W8", "W8", "W2", "W5", "W5", "W2", "W8"]
SHA = {"W5": "a" * 64, "W2": "b" * 64, "W8": "c" * 64}


def _run(out, wait=None, disk=None, gov="performance", drop_mark=False):
    wait = wait or {"W5": 5001.0, "W2": 2001.0, "W8": 8001.0}
    out.mkdir()
    (out / "images.txt").write_text("".join("%s x %s\n" % (w, SHA[w]) for w in ("W5", "W2", "W8")))
    for i, w in enumerate(PAT, 1):
        pre = 410.0 + i % 3
        marks = {"fsevmgr": pre, "mount_fs": pre + wait[w] + (i % 2), "startup_end": pre + wait[w] + 700.0,
                 "banner": pre + wait[w] + 720.0, "networking": None, "sshd": None}
        if drop_mark and i == 4:
            marks["mount_fs"] = None
        blob = {"stamp": {"devices": "none" if not (disk and i == 2) else "blk", "disk": "none" if not (disk and i == 2) else "disk-qemu",
                          "ifs_sha256": SHA[w], "cpu_before": [{"cpu": c, "governor": gov} for c in range(6)]},
                "runs": [{"ok": True, "warmup": False, "marks_ms": marks, "ms_to_startup_complete": marks["startup_end"]}]}
        (out / ("boot-i%d-%s.json" % (i, w))).write_text(json.dumps(blob))


def _report(out):
    r = subprocess.run([sys.executable, REPORT, str(out)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _line(s, tag):
    return s.split(tag)[1].split("\n")[0]


def test_a_wait_that_follows_the_constant_holds_everything(tmp_path):
    _run(tmp_path / "o")
    s = _report(tmp_path / "o")
    assert "FAILED" not in s, s
    for p in ("P1", "P2", "P3"):
        assert "-> HELD" in _line(s, p), s


def test_a_wait_that_ignores_the_constant_refutes(tmp_path):
    _run(tmp_path / "o", wait={"W5": 5001.0, "W2": 5001.0, "W8": 5001.0})
    s = _report(tmp_path / "o")
    assert "-> REFUTED" in _line(s, "P1") and "-> REFUTED" in _line(s, "P2") and "-> HELD" in _line(s, "P3"), s


def test_a_disk_a_missing_mark_or_an_unpinned_governor_voids(tmp_path):
    _run(tmp_path / "a", disk=True)
    s = _report(tmp_path / "a")
    assert "-> FAILED" in _line(s, "M3") and "VOID (M3 failed)" in _line(s, "P1"), s
    _run(tmp_path / "b", drop_mark=True)
    s = _report(tmp_path / "b")
    assert "-> FAILED" in _line(s, "M1"), s
    _run(tmp_path / "c", gov="schedutil")
    s = _report(tmp_path / "c")
    assert "-> FAILED" in _line(s, "M5"), s


STUB_LIB = """MEASURE_LIB_LOADED=1
say() { echo "== $*"; }
die() { echo "FATAL: $*" >&2; exit 1; }
m_pids_of() { :; }
m_prepare_out() { OUT="${1:-$2}"; mkdir -p "$OUT"; }
m_governor_pin() { :; }; m_governor_restore() { :; }; m_governor_recheck() { :; }
m_cstate_apply() { :; }; m_cstate_restore() { :; }
"""
STUB_TIMER = """import argparse, hashlib, json, platform
ap = argparse.ArgumentParser()
for k in ("--ifs", "--json", "--label", "--runs", "--warmup"):
    ap.add_argument(k)
a = ap.parse_args()
w = float(open(a.ifs).read().strip()) * 1000.0 + 1.0
m = {"fsevmgr": 410.0, "mount_fs": 410.0 + w, "startup_end": 1110.0 + w, "banner": 1130.0 + w,
     "networking": None, "sshd": None}
node = platform.node()
json.dump({"stamp": {"host": node, "devices": "none", "disk": "none",
                     "ifs_sha256": hashlib.sha256(open(a.ifs, "rb").read()).hexdigest(),
                     "cpu_before": [{"cpu": 0, "governor": "performance"}]},
           "runs": [{"ok": True, "warmup": False, "marks_ms": m}]}, open(a.json, "w"))
print("host   : %s" % node)
print("  timed  0: ok=True  mount_fs=%s" % m["mount_fs"])
"""


def test_the_harness_runs_the_pattern_and_leaves_no_host_name(tmp_path):
    if BASH is None:
        return
    import platform
    stub = tmp_path / "bin"
    stub.mkdir()
    (stub / "python3").write_text('#!/usr/bin/env bash\nexec "%s" "$@"\n' % sys.executable.replace("\\", "/"), newline="\n")
    (stub / "flock").write_text("#!/usr/bin/env bash\nexit 0\n", newline="\n")
    for f in ("python3", "flock"):
        os.chmod(stub / f, 0o755)
    (tmp_path / "lib.sh").write_text(STUB_LIB, newline="\n")
    (tmp_path / "timer.py").write_text(STUB_TIMER)
    env = dict(os.environ, LIB=str(tmp_path / "lib.sh"), TIMER=str(tmp_path / "timer.py"), LOCK=str(tmp_path / "lock"),
               OUT=str(tmp_path / "out"), PATH=str(stub).replace("\\", "/") + os.pathsep + os.environ.get("PATH", ""))
    for w in (5, 2, 8):
        (tmp_path / ("W%d.bin" % w)).write_text(str(w))
        env["IMG_W%d" % w] = str(tmp_path / ("W%d.bin" % w))
    r = subprocess.run([BASH, HARNESS], capture_output=True, text=True, timeout=300, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    for p in ("P1", "P2", "P3"):
        assert "-> HELD" in _line(r.stdout, p), r.stdout
    assert "M4 image sha256 as hashed at the start: 9/9 -> ok" in r.stdout, r.stdout
    node = platform.node()
    for f in (tmp_path / "out").iterdir():
        assert node not in f.read_text(), f
    assert '"host": "<board>"' in (tmp_path / "out" / "boot-i1-W5.json").read_text()


def test_the_harness_parses_and_states_its_rule_and_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    text = open(HARNESS, encoding="utf-8").read()
    head, body = text.split("\nset -u\n", 1)
    for s in ("WAIT(W2) - WAIT(W5) = -3000 ms, within 100 ms", "WAIT(W8) - WAIT(W5) = +3000 ms, within 100 ms",
              "PRE and POST each within 100 ms", "W5 W2 W8 W8 W2 W5 W5 W2 W8", "It is not to be amended",
              "The owner asked for this run", "change the constant"):
        assert s in head, s
    assert "time-kvm-boot.py" in body and "--disk" not in body.split("python3 \"$TIMER\"")[1].split("\n")[0]
