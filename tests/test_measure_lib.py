"""The shared measurement controls in orin-native/gpu-concurrency/lib-measure.sh.

These pin the one rule that file exists to enforce -- a control is APPLIED AND
VERIFIED, RECORDED AS ABSENT, or the run REFUSES; never skipped in silence --
against fake sysfs trees and fake result files, so no board is needed.

An adversarial review on 2026-09-21 confirmed 40 findings against the first
draft, 39 of them reproduced, and every serious one had that same shape. The
tests below are organised by the finding they pin, so a regression names the
defect it has brought back.

Each test was also checked the other way: the property must FAIL against the
code it replaced. A test that only passes proves nothing.
"""
import itertools
import json
import os
import shutil
import subprocess
import textwrap
import time

import pytest

HERE = os.path.dirname(__file__)
LIB = os.environ.get("MEASURE_LIB") or os.path.join(
    HERE, "..", "orin-native", "gpu-concurrency", "lib-measure.sh")
PROBE = os.path.join(HERE, "..", "orin-native", "gpu-concurrency", "latency_probe.py")
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(BASH is None, reason="bash not available")


def _posix(p):
    return os.path.abspath(p).replace("\\", "/")


def _sysfs(tmp_path, governors):
    root = tmp_path / "cpu"
    for i, gov in enumerate(governors):
        d = root / ("cpu%d" % i) / "cpufreq"
        d.mkdir(parents=True)
        (d / "scaling_governor").write_text(gov + "\n")
        (d / "scaling_cur_freq").write_text("1344000\n")
    if not governors:
        (root / "cpu0").mkdir(parents=True)
    return root


def _stub_sudo(tmp_path, body):
    """A `sudo` on PATH that does `body` instead of escalating, plus a `python3`.

    The python3 shim exists because the library shells out to python3 for its
    JSON checks, and under Git Bash on Windows `python3` resolves to the
    Microsoft Store placeholder. CI, the Orin and a1.metal all have a real one.
    The shim points at the interpreter running the tests, so the checks run for
    real everywhere. (Without it the library fails CLOSED -- it refuses the run
    -- which is the right behaviour but not what these tests are about.)
    """
    import sys
    b = tmp_path / "bin"
    b.mkdir(exist_ok=True)
    s = b / "sudo"
    s.write_text("#!/usr/bin/env bash\n" + body + "\n")
    s.chmod(0o755)
    py = b / "python3"
    py.write_text('#!/usr/bin/env bash\nexec "%s" "$@"\n' % _posix(sys.executable))
    py.chmod(0o755)
    return b


def _run(tmp_path, snippet, governors=(), sudo='exec "$@"'):
    sysfs = _sysfs(tmp_path, list(governors))
    sudo_bin = _stub_sudo(tmp_path, sudo)
    env = dict(os.environ)
    env["SYSFS_CPU"] = _posix(sysfs)
    env["PATH"] = _posix(sudo_bin) + os.pathsep + env.get("PATH", "")
    script = textwrap.dedent("""
        set -u
        . "%s"
        %s
    """) % (_posix(LIB), snippet)
    r = subprocess.run([BASH, "-c", script], env=env, capture_output=True, text=True)
    r.sysfs = sysfs
    return r


# ============================================================ the governor

def test_governor_present_is_pinned_and_verified(tmp_path):
    r = _run(tmp_path, 'm_governor_pin; echo "STATE=$GOV_STATE BEFORE=$PRE_GOV"', ["schedutil"] * 6)
    assert r.returncode == 0, r.stderr
    assert "STATE=pinned BEFORE=schedutil" in r.stdout
    for i in range(6):
        assert (r.sysfs / ("cpu%d" % i) / "cpufreq" / "scaling_governor").read_text().strip() == "performance"


def test_governor_absent_is_recorded_not_skipped(tmp_path):
    """The a1.metal case: no cpufreq sysfs at all."""
    r = _run(tmp_path, 'm_governor_pin; echo "STATE=$GOV_STATE"')
    assert r.returncode == 0, r.stderr
    assert "STATE=absent" in r.stdout and "recorded as absent" in r.stdout


def test_governor_that_will_not_pin_refuses_the_run(tmp_path):
    r = _run(tmp_path, 'm_governor_pin; echo "SHOULD NOT REACH"', ["schedutil"] * 6, sudo="cat >/dev/null")
    assert r.returncode != 0
    assert "SHOULD NOT REACH" not in r.stdout
    assert "would not pin" in r.stderr


def test_governor_restore_puts_back_what_was_there(tmp_path):
    r = _run(tmp_path, "m_governor_pin; m_governor_restore", ["schedutil"] * 4)
    assert r.returncode == 0, r.stderr
    for i in range(4):
        assert (r.sysfs / ("cpu%d" % i) / "cpufreq" / "scaling_governor").read_text().strip() == "schedutil"


def test_restore_is_a_noop_when_nothing_was_pinned(tmp_path):
    r = _run(tmp_path, "m_governor_pin; m_governor_restore; echo OK", sudo="echo SUDO_CALLED >&2; exit 1")
    assert r.returncode == 0, r.stderr
    assert "SUDO_CALLED" not in r.stderr


def test_partial_pin_restores_exactly_the_cores_it_changed(tmp_path):
    """REVIEW: a pin that died part-way left changed cores at performance."""
    # sudo succeeds on cores 0-2 and silently swallows the write from core 3 on.
    sudo = ('case "$*" in *cpu[3-9]/*) cat >/dev/null ;; *) exec "$@" ;; esac')
    r = _run(tmp_path, "trap m_governor_restore EXIT; m_governor_pin",
             ["schedutil"] * 6, sudo=sudo)
    assert r.returncode != 0 and "would not pin" in r.stderr
    for i in range(6):
        got = (r.sysfs / ("cpu%d" % i) / "cpufreq" / "scaling_governor").read_text().strip()
        assert got == "schedutil", "cpu%d left at %r after a failed pin" % (i, got)


def test_governor_drift_during_the_run_is_caught(tmp_path):
    r = _run(tmp_path,
             'm_governor_pin; echo powersave > "$SYSFS_CPU/cpu2/cpufreq/scaling_governor"; '
             'm_governor_recheck; echo "SHOULD NOT REACH"',
             ["schedutil"] * 6)
    assert r.returncode != 0 and "SHOULD NOT REACH" not in r.stdout
    assert "drifted" in r.stderr


# ============================================================ QEMU affinity readback

@pytest.mark.parametrize("asked,readback", [
    ("0-2", "0-2"), ("0-2", "0,1,2"), ("0-1", "0,1"), ("0,1", "0-1"), ("3", "3"), ("0-2,5", "0,1,2,5"),
])
def test_affinity_readback_compares_cpu_sets_not_strings(tmp_path, asked, readback):
    """REVIEW (regression): an exact-string compare killed every valid 0,1 vs 0-1 pin."""
    r = _run(tmp_path, '[ "$(_cpuset "%s")" = "$(_cpuset "%s")" ] && echo SAME' % (asked, readback))
    assert r.stdout.strip() == "SAME", r.stderr


def test_affinity_readback_still_rejects_a_different_set(tmp_path):
    r = _run(tmp_path, '[ "$(_cpuset "0-2")" = "$(_cpuset "0-3")" ] && echo SAME || echo DIFFERENT')
    assert r.stdout.strip() == "DIFFERENT"


# ============================================================ Williams counterbalancing

ARM_SETS = {
    2: ["idle", "gpu", "cpu", "idle2"],
    5: ["idle", "cpu2", "cpu4", "cpu6", "cpu6_prio", "gpu_cpu6", "idle2"],
}


def _orders(tmp_path, arms, rounds):
    snippet = "; ".join('m_round_order %d %s' % (r, " ".join(arms)) for r in range(1, rounds + 1))
    return [line.split() for line in _run(tmp_path, snippet).stdout.strip().splitlines()]


@pytest.mark.parametrize("n,period", [(2, 2), (5, 10)])
def test_williams_design_balances_first_order_carryover(tmp_path, n, period):
    """REVIEW: mirror reversal balanced POSITION but not CARRYOVER for 5 arms.

    Every ordered pair of distinct loaded arms must be adjacent equally often.
    """
    arms = ARM_SETS[n]
    loaded = arms[1:-1]
    orders = _orders(tmp_path, arms, period)
    adj = {}
    for o in orders:
        assert o[0] == "idle" and o[-1] == "idle2", "the brackets moved: %r" % o
        mid = o[1:-1]
        assert sorted(mid) == sorted(loaded), "an arm was dropped or repeated: %r" % o
        for p, q in zip(mid, mid[1:]):
            adj[(p, q)] = adj.get((p, q), 0) + 1
    counts = [adj.get(pq, 0) for pq in itertools.permutations(loaded, 2)]
    assert len(set(counts)) == 1, "carryover unbalanced: %r" % adj


@pytest.mark.parametrize("n", [2, 5])
def test_williams_design_balances_position(tmp_path, n):
    arms = ARM_SETS[n]
    period = 2 if n == 2 else 10
    pos = {}
    for o in _orders(tmp_path, arms, period):
        for i, a in enumerate(o[1:-1]):
            pos.setdefault(a, []).append(i)
    means = {a: sum(v) / len(v) for a, v in pos.items()}
    assert len(set(means.values())) == 1, means


def test_mirror_reversal_would_have_failed_the_carryover_test():
    """The property the first draft claimed, checked against its own construction."""
    loaded = ["cpu2", "cpu4", "cpu6", "cpu6_prio", "gpu_cpu6"]
    adj = {}
    for r in range(1, 11):
        seq = loaded if r % 2 else loaded[::-1]
        for p, q in zip(seq, seq[1:]):
            adj[(p, q)] = adj.get((p, q), 0) + 1
    counts = [adj.get(pq, 0) for pq in itertools.permutations(loaded, 2)]
    assert len(set(counts)) > 1


@pytest.mark.parametrize("k,n,ok", [(12, 2, True), (13, 2, False), (20, 5, True), (12, 5, False), (10, 5, True)])
def test_k_must_be_a_multiple_of_the_williams_period(tmp_path, k, n, ok):
    r = _run(tmp_path, "m_require_balanced_k %d %d; echo PASSED" % (k, n))
    assert ("PASSED" in r.stdout) is ok, r.stderr


# ============================================================ run directory

def test_prepare_out_refuses_a_directory_that_already_holds_results(tmp_path):
    """REVIEW: a failed arm was silently backfilled from the previous run's file."""
    d = tmp_path / "run"
    d.mkdir()
    (d / "lat-idle_r1.json").write_text("{}")
    r = _run(tmp_path, 'm_prepare_out "%s" /unused; echo "SHOULD NOT REACH"' % _posix(d))
    assert r.returncode != 0 and "SHOULD NOT REACH" not in r.stdout
    assert "refusing to mix runs" in r.stderr


def test_prepare_out_sets_the_global_and_can_really_die(tmp_path):
    """It must not be written as `OUT=$(...)`: a die inside $(...) exits only the subshell."""
    base = tmp_path / "base"
    r = _run(tmp_path, 'm_prepare_out "" "%s"; echo "OUT=$OUT"' % _posix(base))
    assert r.returncode == 0, r.stderr
    got = r.stdout.strip().split("OUT=", 1)[1]
    assert got.startswith(_posix(base) + "/") and os.path.isdir(got)


# ============================================================ completeness and validity

def _summary(tag, n=1000, warmup=200, bad=0, rejected=0):
    return {"summary": {"tag": tag, "n": n, "warmup_discarded": warmup, "bad": bad,
                        "rejected_by_monitor": rejected, "p50_ms": 0.2, "p99_ms": 0.3,
                        "max_ms": 0.4, "mean_ms": 0.21}}


def _run_dir(tmp_path, k=12, arms=("idle", "gpu"), stamp_first=True, mutate=None):
    d = tmp_path / "run"
    d.mkdir(exist_ok=True)
    stamp = d / "stamp.json"
    start = d / ".run-start"
    if stamp_first:
        stamp.write_text("{}")
        start.write_text("")
        past = time.time() - 60
        os.utime(stamp, (past, past))
        os.utime(start, (past, past))
    for a in arms:
        for r in range(1, k + 1):
            tag = "%s_r%d" % (a, r)
            body = _summary(tag)
            if mutate:
                body = mutate(a, r, body)
            if body is not None:
                (d / ("lat-%s.json" % tag)).write_text(json.dumps(body))
    return d


def _complete(tmp_path, d, k=12):
    return _run(tmp_path, 'K=%d; N=1000; WARMUP=200; m_require_complete "%s" idle gpu; echo PASSED'
                % (k, _posix(d)))


def test_complete_clean_run_passes(tmp_path):
    r = _complete(tmp_path, _run_dir(tmp_path))
    assert "PASSED" in r.stdout, r.stderr


def test_missing_round_refuses(tmp_path):
    d = _run_dir(tmp_path, mutate=lambda a, r, b: None if (a, r) == ("gpu", 5) else b)
    r = _complete(tmp_path, d)
    assert "PASSED" not in r.stdout and "gpu_r5: missing" in r.stderr


def test_file_older_than_the_stamp_refuses(tmp_path):
    """REVIEW: the core of the backfill bug -- a file from before this run began."""
    d = _run_dir(tmp_path)
    old = d / "lat-gpu_r5.json"
    past = time.time() - 3600
    os.utime(old, (past, past))
    r = _complete(tmp_path, d)
    assert "PASSED" not in r.stdout and "gpu_r5: older than" in r.stderr


@pytest.mark.parametrize("field,value,message", [
    ("n", 129, "n=129"),
    ("bad", 171, "bad=171"),
    ("rejected_by_monitor", 1, "rejected_by_monitor=1"),
    ("warmup_discarded", 20, "warmup_discarded=20"),
    ("tag", "gpu_r9", "tag='gpu_r9'"),
])
def test_degraded_arm_file_refuses(tmp_path, field, value, message):
    """REVIEW: a truncated or corrupted arm used to count as a full run-median.

    n=129 and bad=171 are the numbers the reviewer's stalling monitor produced
    against the old probe, which exited 0 and wrote that file.
    """
    def mutate(a, r, b):
        if (a, r) == ("gpu", 5):
            b["summary"][field] = value
        return b
    r = _complete(tmp_path, _run_dir(tmp_path, mutate=mutate))
    assert "PASSED" not in r.stdout
    assert message in r.stderr, r.stderr


def test_round_outside_one_to_k_refuses(tmp_path):
    d = _run_dir(tmp_path)
    (d / "lat-gpu_r13.json").write_text(json.dumps(_summary("gpu_r13")))
    r = _complete(tmp_path, d)
    assert "PASSED" not in r.stdout and "outside 1..12" in r.stderr


# ============================================================ the probe itself

def test_probe_aborts_on_a_stall_and_writes_nothing(tmp_path):
    """REVIEW: after a recv timeout the old probe read every later reply one
    frame late, counted the rest of the arm as bad, exited 0, and left the
    stall out of max. The fake monitor stalls longer than the probe's timeout."""
    import socket
    import sys
    import threading

    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    stop = threading.Event()

    def serve():
        c, _ = srv.accept()
        n = 0
        while not stop.is_set():
            buf = b""
            while len(buf) < 64:
                chunk = c.recv(64 - len(buf))
                if not chunk:
                    return
                buf += chunk
            n += 1
            if n == 50:
                stop.wait(11)
            try:
                c.sendall(buf)
            except OSError:
                return

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    out = tmp_path / "lat.json"
    r = subprocess.run([sys.executable, PROBE, "--host", "127.0.0.1", "--port", str(port),
                        "--n", "100", "--warmup", "10", "--interval-ms", "1",
                        "--tag", "stall", "--out", str(out)],
                       capture_output=True, text=True, timeout=60)
    stop.set()
    srv.close()
    assert r.returncode == 3, r.stdout + r.stderr
    assert "FATAL desync" in r.stdout
    assert not out.exists(), "an aborted arm must not leave a result file"


def test_full_sequence_passes_even_though_stamp_after_rewrites_the_stamp(tmp_path):
    """FOUND BY THE FIRST REAL RUN, 2026-09-21, not by the unit tests.

    m_stamp_after rewrites stamp.json at the end of a run. The first version of
    the freshness check compared result files against stamp.json's mtime, so
    after that rewrite every file looked older than the run and a clean Orin
    run was refused. The unit tests above call m_require_complete against a
    pre-dated stamp and never run m_stamp_after first -- the two only met in a
    real run. This drives the actual order a script uses.
    """
    base = tmp_path / "base"
    tags = " ".join('%s_r%d' % (a, r) for a in ("idle", "gpu") for r in (1, 2))
    snippet = textwrap.dedent("""
        N=1000; K=2; WARMUP=200; INTERVAL_MS=2
        m_prepare_out "" "%s"
        m_write_stamp "$OUT/stamp.json" '"experiment": "test"'
        sleep 1
        F='{"summary":{"tag":"%%s","n":1000,"warmup_discarded":200,"bad":0,'
        F="$F"'"rejected_by_monitor":0,"p50_ms":0.2,"p99_ms":0.3,"max_ms":0.4}}'
        for t in %s; do
            printf "$F" "$t" > "$OUT/lat-$t.json"
        done
        sleep 1
        m_stamp_after "$OUT/stamp.json"
        m_require_complete "$OUT" idle gpu
        echo PASSED
    """) % (_posix(base), tags)
    r = _run(tmp_path, snippet)
    assert "PASSED" in r.stdout, r.stdout + r.stderr


# ============================================================ the GPU load check

# A real JetPack 6 tegrastats line, as the Orin printed it on 2026-09-21.
TEGRA_LINE = ("09-21-2026 12:04:00 RAM 2345/7620MB (lfb 2x4MB) SWAP 0/3810MB (cached 0MB) "
              "CPU [2%@729,1%@729,0%@729,0%@729,0%@729,0%@729] EMC_FREQ 0%@2133 "
              "GR3D_FREQ {pct}%@[1020] NVDEC off NVJPG off VIC off OFA off APE 200 "
              "cpu@49.031C soc2@47.5C gpu@48.843C tj@49.031C")


def _stub_tegrastats(tmp_path, pct):
    b = tmp_path / "bin"
    b.mkdir(exist_ok=True)
    s = b / "tegrastats"
    s.write_text("#!/usr/bin/env bash\necho '%s'\n" % TEGRA_LINE.format(pct=pct))
    s.chmod(0o755)


@pytest.mark.parametrize("pct", [99, 7, 0, 100, 3, 33])
def test_gpu_busy_reads_the_value_not_the_digit_in_the_label(tmp_path, pct):
    """FOUND ON THE FIRST REAL RUN: '[0-9]+' also matched the 3 in 'GR3D'.

    pct=3 and pct=33 are here on purpose: they are the values most easily
    confused with that stray digit.
    """
    _stub_tegrastats(tmp_path, pct)
    r = _run(tmp_path, "m_gpu_busy_pct")
    assert r.stdout.strip() == str(pct), "read %r from a %d%% line" % (r.stdout, pct)


def test_gpu_arm_passes_when_the_gpu_is_loaded(tmp_path):
    _stub_tegrastats(tmp_path, 99)
    r = _run(tmp_path, 'm_require_gpu_busy 50; echo "OK $GPU_PCT"')
    assert r.returncode == 0 and "OK 99" in r.stdout, r.stderr


def test_gpu_arm_refuses_when_the_gpu_is_idle(tmp_path):
    _stub_tegrastats(tmp_path, 7)
    r = _run(tmp_path, 'm_require_gpu_busy 50; echo "SHOULD NOT REACH"')
    assert r.returncode != 0 and "SHOULD NOT REACH" not in r.stdout
    assert "GR3D is 7%" in r.stderr
