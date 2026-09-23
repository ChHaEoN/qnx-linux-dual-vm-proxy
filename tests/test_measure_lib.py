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
import re
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
        d.mkdir(parents=True, exist_ok=True)
        (d / "scaling_governor").write_text(gov + "\n")
        (d / "scaling_cur_freq").write_text("1344000\n")
    if not governors:
        # exist_ok: a test may call _run more than once in one tmp_path. The
        # first such test only ran where gcc exists -- CI -- and failed there.
        (root / "cpu0").mkdir(parents=True, exist_ok=True)
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

def _summary(tag, n=1000, warmup=200, bad=0, rejected=0,
             policy="SCHED_OTHER", priority=0, affinity=(4,)):
    return {"summary": {"tag": tag, "proto": "tcp", "n": n, "warmup_discarded": warmup, "bad": bad,
                        "sched_policy": policy, "sched_priority": priority,
                        "cpu_affinity": list(affinity) if affinity is not None else None,
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
    return _run(tmp_path, 'K=%d; N=1000; WARMUP=200; CORE_PROBE=4; m_require_complete "%s" idle gpu; echo PASSED'
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
        N=1000; K=2; WARMUP=200; INTERVAL_MS=2; CORE_PROBE=4
        m_prepare_out "" "%s"
        m_write_stamp "$OUT/stamp.json" '"experiment": "test"'
        sleep 1
        F='{"summary":{"tag":"%%s","n":1000,"warmup_discarded":200,"bad":0,'
        F="$F"'"rejected_by_monitor":0,"p50_ms":0.2,"p99_ms":0.3,"max_ms":0.4,'
        F="$F"'"sched_policy":"SCHED_OTHER","sched_priority":0,"cpu_affinity":[4],"proto":"tcp"}}'
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
TEGRA_LINE = ("09-21-2026 15:43:44 RAM 1928/7620MB (lfb 5x4MB) SWAP 0/3810MB (cached 0MB) "
              "CPU [1%@729,3%@729,4%@729,3%@729,0%@729,0%@729] GR3D_FREQ {pct}% "
              "cpu@48.281C soc2@47.718C soc0@48.531C gpu@48.25C tj@48.531C soc1@48.25C "
              "VDD_IN 4563mW/4563mW VDD_CPU_GPU_CV 524mW/524mW VDD_SOC 1373mW/1373mW")
# Captured from the board, 2026-09-21, with tegrastats run AS THE USER -- the way
# m_thermal and m_gpu_busy_pct run it. The first version of this fixture was
# written from memory and carried an "EMC_FREQ 0%@2133" field and a "@[1020]"
# suffix on GR3D. A later review asked why, and one board command answered it:
# tegrastats prints both only when run as root. So the user line below has
# neither, and the root line the window sampler sees has both.
TEGRA_LINE_ROOT = ("09-21-2026 16:47:06 RAM 1954/7620MB (lfb 4x4MB) SWAP 0/3810MB (cached 0MB) "
                   "CPU [0%@883,0%@883,0%@883,0%@883,0%@729,0%@729] EMC_FREQ 0%@2133 GR3D_FREQ {pct}%@[305] "
                   "NVDEC off NVJPG off NVJPG1 off VIC off OFA off APE 200 cpu@48.062C soc2@47.343C "
                   "soc0@48.218C gpu@48.156C tj@48.218C soc1@48C VDD_IN 4523mW/4523mW "
                   "VDD_CPU_GPU_CV 524mW/524mW VDD_SOC 1373mW/1373mW")


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


# ============================================================ CPU idle states

# The Orin's real cpuidle table, read on 2026-09-21: WFI at 1 us, c7 at 5000 us.
ORIN_IDLE = [("WFI", 1), ("c7", 5000)]


def _cpuidle(tmp_path, ncpu=6, states=ORIN_IDLE):
    for c in range(ncpu):
        for i, (name, lat) in enumerate(states):
            d = tmp_path / "cpu" / ("cpu%d" % c) / "cpuidle" / ("state%d" % i)
            d.mkdir(parents=True, exist_ok=True)
            (d / "name").write_text(name + "\n")
            (d / "latency").write_text("%d\n" % lat)
            (d / "disable").write_text("0\n")


def _run_idle(tmp_path, snippet, sudo='exec "$@"', states=ORIN_IDLE, ncpu=6):
    """Like _run, but with a cpuidle tree built before the snippet runs."""
    sudo_bin = _stub_sudo(tmp_path, sudo)
    if states:
        _cpuidle(tmp_path, ncpu, states)
    else:
        (tmp_path / "cpu" / "cpu0").mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["SYSFS_CPU"] = _posix(tmp_path / "cpu")
    env["PATH"] = _posix(sudo_bin) + os.pathsep + env.get("PATH", "")
    script = 'set -u\n. "%s"\n%s\n' % (_posix(LIB), snippet)
    return subprocess.run([BASH, "-c", script], env=env, capture_output=True, text=True)


def _disabled(tmp_path, cpu, state):
    return (tmp_path / "cpu" / ("cpu%d" % cpu) / "cpuidle" / ("state%d" % state) / "disable").read_text().strip()


def test_idle_states_default_is_recorded_as_found_and_untouched(tmp_path):
    """The default is the realistic system -- recorded in detail, not controlled.

    'cpuidle: present' alone is how c7 went unnoticed through a whole campaign.
    """
    r = _run_idle(tmp_path, 'CSTATE=""; m_cstate_apply; echo "S=$CSTATE_STATE E=$CSTATE_EXPOSED"')
    assert r.returncode == 0, r.stderr
    assert "S=as-found" in r.stdout
    assert "c7:5000us:on" in r.stdout and "WFI:1us:on" in r.stdout
    assert all(_disabled(tmp_path, c, 1) == "0" for c in range(6))


def test_shallow_disables_only_the_deep_states_and_verifies(tmp_path):
    r = _run_idle(tmp_path, 'CSTATE=shallow; m_cstate_apply; echo "S=$CSTATE_STATE"')
    assert r.returncode == 0, r.stderr
    assert "S=shallow" in r.stdout
    for c in range(6):
        assert _disabled(tmp_path, c, 1) == "1", "c7 still enabled on cpu%d" % c
        assert _disabled(tmp_path, c, 0) == "0", "WFI was disabled on cpu%d" % c


def test_shallow_restore_puts_back_exactly_what_was_there(tmp_path):
    r = _run_idle(tmp_path, "CSTATE=shallow; m_cstate_apply; m_cstate_restore")
    assert r.returncode == 0, r.stderr
    assert all(_disabled(tmp_path, c, s) == "0" for c in range(6) for s in (0, 1))


def test_shallow_that_will_not_disable_refuses_the_run(tmp_path):
    r = _run_idle(tmp_path, 'CSTATE=shallow; m_cstate_apply; echo "SHOULD NOT REACH"', sudo="cat >/dev/null")
    assert r.returncode != 0 and "SHOULD NOT REACH" not in r.stdout
    assert "would not disable" in r.stderr


def test_no_cpuidle_is_recorded_as_absent(tmp_path):
    """The a1.metal case."""
    r = _run_idle(tmp_path, 'CSTATE=shallow; m_cstate_apply; echo "S=$CSTATE_STATE"', states=None)
    assert r.returncode == 0, r.stderr
    assert "S=absent" in r.stdout


def test_unknown_policy_refuses(tmp_path):
    r = _run_idle(tmp_path, 'CSTATE=deep; m_cstate_apply; echo "SHOULD NOT REACH"')
    assert r.returncode != 0 and "not a policy" in r.stderr


# ============================================================ the probe's own scheduling report

def _sched_dir(tmp_path, arms, mutate):
    """A clean two-round run directory for `arms`; `mutate(arm, round, summary)` edits in place."""
    d = tmp_path / "run"
    d.mkdir(exist_ok=True)
    (d / "stamp.json").write_text("{}")
    (d / ".run-start").write_text("")
    past = time.time() - 60
    for f in ("stamp.json", ".run-start"):
        os.utime(d / f, (past, past))
    for a in arms:
        for r in (1, 2):
            tag = "%s_r%d" % (a, r)
            body = _summary(tag)
            mutate(a, r, body["summary"])
            (d / ("lat-%s.json" % tag)).write_text(json.dumps(body))
    return d


def _gate(tmp_path, d, arms, fifo=""):
    return _run(tmp_path, 'K=2; N=1000; WARMUP=200; CORE_PROBE=4; FIFO_ARMS="%s"; '
                'm_require_complete "%s" %s; echo PASSED' % (fifo, _posix(d), " ".join(arms)))


def _fifo_on(*which):
    def m(a, r, s):
        if a in which:
            s["sched_policy"], s["sched_priority"] = "SCHED_FIFO", 50
    return m


def _untouched(a, r, s):
    pass


def test_sched_gate_passes_fifo_where_asked_and_other_elsewhere(tmp_path):
    arms = ["idle", "cpu6", "cpu6_prio"]
    r = _gate(tmp_path, _sched_dir(tmp_path, arms, _fifo_on("cpu6_prio")), arms, fifo="cpu6_prio")
    assert "PASSED" in r.stdout, r.stderr


def test_sched_gate_refuses_a_priority_arm_that_ran_at_normal_priority(tmp_path):
    """The case the 2026-09-21 analysis could not rule out: chrt was asked, FIFO did not hold."""
    arms = ["idle", "cpu6_prio"]
    r = _gate(tmp_path, _sched_dir(tmp_path, arms, _untouched), arms, fifo="cpu6_prio")
    assert "PASSED" not in r.stdout
    assert "sched_policy='SCHED_OTHER', expected 'SCHED_FIFO'" in r.stderr


def test_sched_gate_refuses_fifo_leaking_into_an_ordinary_arm(tmp_path):
    arms = ["idle", "cpu6"]
    r = _gate(tmp_path, _sched_dir(tmp_path, arms, _fifo_on("cpu6")), arms, fifo="")
    assert "PASSED" not in r.stdout and "expected 'SCHED_OTHER'" in r.stderr


def test_sched_gate_refuses_the_wrong_priority(tmp_path):
    def low(a, r, s):
        if a == "cpu6_prio":
            s["sched_policy"], s["sched_priority"] = "SCHED_FIFO", 1
    arms = ["idle", "cpu6_prio"]
    r = _gate(tmp_path, _sched_dir(tmp_path, arms, low), arms, fifo="cpu6_prio")
    assert "PASSED" not in r.stdout and "sched_priority=1, expected 50" in r.stderr


def test_sched_gate_refuses_a_probe_off_its_core(tmp_path):
    def moved(a, r, s):
        if (a, r) == ("idle", 2):
            s["cpu_affinity"] = [0, 1, 2, 3, 4, 5]
    r = _gate(tmp_path, _sched_dir(tmp_path, ["idle"], moved), ["idle"])
    assert "PASSED" not in r.stdout and "cpu_affinity=[0, 1, 2, 3, 4, 5], expected [4]" in r.stderr


def test_sched_gate_refuses_a_probe_that_could_not_report(tmp_path):
    """A null reading is not a pass -- it is the gap this check exists to close."""
    def blind(a, r, s):
        s["sched_policy"] = s["sched_priority"] = s["cpu_affinity"] = None
    r = _gate(tmp_path, _sched_dir(tmp_path, ["idle"], blind), ["idle"])
    assert "PASSED" not in r.stdout and "sched_policy=None" in r.stderr


def test_sched_gate_refuses_a_file_written_before_the_fields_existed(tmp_path):
    def old(a, r, s):
        for k in ("sched_policy", "sched_priority", "cpu_affinity"):
            del s[k]
    r = _gate(tmp_path, _sched_dir(tmp_path, ["idle"], old), ["idle"])
    assert "PASSED" not in r.stdout and "cpu_affinity=None" in r.stderr


def test_sched_gate_refuses_to_run_without_a_probe_core(tmp_path):
    d = _sched_dir(tmp_path, ["idle"], _untouched)
    r = _run(tmp_path, 'K=2; N=1000; WARMUP=200; unset CORE_PROBE; '
             'm_require_complete "%s" idle; echo PASSED' % _posix(d))
    assert "PASSED" not in r.stdout and "needs CORE_PROBE" in r.stderr


# ============================================================ the pinned arm sets of 2026-09-21

PINNED_SETS = {
    "interference": ["idle", "gpu", "cpu_q", "cpu_nq", "idle2"],
    "saturation": ["idle", "cpu2_q", "cpu2_nq", "cpu3_q", "cpu6", "cpu6_prio", "gpu_cpu6", "idle2"],
}


@pytest.mark.parametrize("name", sorted(PINNED_SETS))
def test_williams_balances_the_pinned_arm_sets(tmp_path, name):
    """Three and six loaded arms both have period 6: every ordered pair adjacent equally often,
    every arm in every position equally often."""
    arms = PINNED_SETS[name]
    loaded = arms[1:-1]
    adj, pos = {}, {}
    for o in _orders(tmp_path, arms, 6):
        assert o[0] == "idle" and o[-1] == "idle2", o
        mid = o[1:-1]
        assert sorted(mid) == sorted(loaded), o
        for p, q in zip(mid, mid[1:]):
            adj[(p, q)] = adj.get((p, q), 0) + 1
        for i, a in enumerate(mid):
            pos.setdefault(a, []).append(i)
    counts = [adj.get(pq, 0) for pq in itertools.permutations(loaded, 2)]
    assert len(set(counts)) == 1, adj
    assert len({sum(v) / len(v) for v in pos.values()}) == 1, pos


@pytest.mark.parametrize("k,n,ok", [(12, 3, True), (12, 6, True), (6, 3, True), (10, 6, False), (9, 3, False)])
def test_default_k_fits_both_pinned_arm_sets(tmp_path, k, n, ok):
    r = _run(tmp_path, "m_require_balanced_k %d %d; echo PASSED" % (k, n))
    assert ("PASSED" in r.stdout) is ok, r.stderr


# ============================================================ the window sampler

def _sampler(tmp_path, snippet, emc_bpmp="2133000000", gpu_hz="306000000", tegra=True, gpu_node=True,
             sudo='[ "$1" = -n ] && shift; exec "$@"'):
    # Bytes, not text: on Windows write_text emits CRLF, and a sysfs value read
    # back with a trailing carriage return is a fixture artefact, not a finding.
    def put(path, text):
        path.write_bytes(text.encode())
    b = tmp_path / "bin"
    b.mkdir(exist_ok=True)
    t = b / "tegrastats"
    line = {True: TEGRA_LINE_ROOT.format(pct=0), False: "RAM 1928/7620MB",
            "user": TEGRA_LINE.format(pct=0)}[tegra]
    put(t, "#!/usr/bin/env bash\nwhile :; do echo '%s'; sleep 0.2; done\n" % line)
    t.chmod(0o755)
    clk = tmp_path / "clk"
    clk.mkdir(exist_ok=True)
    put(clk / "bpmp", emc_bpmp + "\n")
    put(clk / "ccf", "204000000\n")
    devfreq = tmp_path / "devfreq"
    node = devfreq / ("17000000.gpu" if gpu_node else "15340000.vic")
    node.mkdir(parents=True, exist_ok=True)
    put(node / "name", node.name + "\n")
    put(node / "cur_freq", gpu_hz + "\n")
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    return _run(tmp_path, 'EMC_BPMP="%s"; EMC_CCF="%s"; DEVFREQ_ROOT="%s"; OUT="%s"; %s'
                % (_posix(clk / "bpmp"), _posix(clk / "ccf"), _posix(devfreq), _posix(out), snippet),
                sudo=sudo)   # the clock loop runs under sudo -n


def test_sampler_preflight_passes_and_records_both_emc_sources(tmp_path):
    r = _sampler(tmp_path, 'm_sampler_preflight; cat "$OUT/clk-preflight.log"')
    assert r.returncode == 0, r.stderr
    assert "emc_bpmp_hz=2133000000" in r.stdout and "emc_ccf_hz=204000000" in r.stdout
    assert "gpu_hz=306000000" in r.stdout
    assert "window sampler verified" in r.stdout


def test_sampler_preflight_refuses_when_emc_cannot_be_read(tmp_path):
    """sudo -n denied or debugfs absent: the EMC gap would silently reopen."""
    r = _sampler(tmp_path, 'm_sampler_preflight; echo SHOULD NOT REACH', emc_bpmp="")
    assert r.returncode != 0 and "SHOULD NOT REACH" not in r.stdout
    assert "no BPMP reading" in r.stderr


def test_sampler_preflight_refuses_when_sudo_is_denied(tmp_path):
    b = tmp_path / "bin"
    b.mkdir(exist_ok=True)
    r = _sampler(tmp_path, 'cat > "%s/sudo" <<"EOF"\n#!/usr/bin/env bash\n'
                 'echo "sudo: a password is required" >&2; exit 1\nEOF\n'
                 'm_sampler_preflight; echo SHOULD NOT REACH' % _posix(b))
    assert r.returncode != 0 and "SHOULD NOT REACH" not in r.stdout
    assert "no BPMP reading" in r.stderr


def test_sampler_preflight_refuses_without_a_gpu_clock_node(tmp_path):
    r = _sampler(tmp_path, 'm_sampler_preflight; echo SHOULD NOT REACH', gpu_node=False)
    assert r.returncode != 0 and "no GPU devfreq node" in r.stderr


def test_sampler_preflight_refuses_without_per_core_cpu(tmp_path):
    r = _sampler(tmp_path, 'm_sampler_preflight; echo SHOULD NOT REACH', tegra=False)
    assert r.returncode != 0 and "SHOULD NOT REACH" not in r.stdout
    assert "printed no EMC_FREQ" in r.stderr


def test_sampler_preflight_refuses_a_tegrastats_that_is_not_root(tmp_path):
    """FOUND BY REVIEW: as the user, tegrastats omits EMC_FREQ -- the field the
    GPU-speedup hypothesis needs. The preflight names the likely cause."""
    r = _sampler(tmp_path, 'm_sampler_preflight; echo SHOULD NOT REACH', tegra="user")
    assert r.returncode != 0 and "printed no EMC_FREQ -- it only does as root" in r.stderr


def test_sampler_brackets_the_probe_only_when_asked(tmp_path):
    """SAMPLE_WINDOW=1 leaves a trace per tag; 0 (the ladder) leaves none."""
    fake = tmp_path / "fakeprobe.py"
    fake.write_text("import sys, json\nout = sys.argv[sys.argv.index('--out') + 1]\n"
                    "open(out, 'w').write(json.dumps({'summary': {}}))\n")
    snippet = ('N=10; WARMUP=1; INTERVAL_MS=0; CORE_PROBE=0; PROBE="%s"; '
               'taskset() { shift 2; "$@"; }; m_sampler_preflight; '
               'SAMPLE_WINDOW=1 m_probe "$OUT" on_r1 127.0.0.1 1; '
               'SAMPLE_WINDOW=0 m_probe "$OUT" off_r1 127.0.0.1 1; '
               'ls "$OUT"; echo "left=[$SAMPLER_ROOT]"' % _posix(fake))
    r = _sampler(tmp_path, snippet)
    assert r.returncode == 0, r.stderr
    assert "clk-on_r1.log" in r.stdout and "tegra-on_r1.log" in r.stdout
    assert "clk-off_r1.log" not in r.stdout and "tegra-off_r1.log" not in r.stdout
    assert "left=[]" in r.stdout


# ============================================================ the probe reports itself

def test_probe_writes_its_scheduling_fields(tmp_path):
    """Present on every platform; real values where the OS has the calls, null elsewhere."""
    import socket
    import sys
    import threading
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def serve():
        c, _ = srv.accept()
        while True:
            buf = b""
            while len(buf) < 64:
                chunk = c.recv(64 - len(buf))
                if not chunk:
                    return
                buf += chunk
            c.sendall(buf)
    threading.Thread(target=serve, daemon=True).start()
    out = tmp_path / "lat.json"
    r = subprocess.run([sys.executable, PROBE, "--host", "127.0.0.1", "--port", str(port),
                        "--n", "20", "--warmup", "2", "--interval-ms", "0",
                        "--tag", "t", "--out", str(out)], capture_output=True, text=True, timeout=60)
    srv.close()
    assert r.returncode == 0, r.stdout + r.stderr
    s = json.loads(out.read_text())["summary"]
    for k in ("sched_policy", "sched_priority", "cpu_affinity"):
        assert k in s
    if hasattr(os, "sched_getscheduler"):
        assert s["sched_policy"] == "SCHED_OTHER" and s["sched_priority"] == 0
        assert s["cpu_affinity"] == sorted(os.sched_getaffinity(0))
    else:
        assert s["sched_policy"] is None and s["cpu_affinity"] is None


# ============================================================ cpuload pinning (needs gcc)

CPULOAD_C = os.path.join(HERE, "..", "orin-native", "gpu-concurrency", "cpuload.c")


@pytest.fixture(scope="module")
def cpuload_bin(tmp_path_factory):
    gcc = shutil.which("gcc")
    if gcc is None or not hasattr(os, "sched_getaffinity"):
        pytest.skip("needs gcc on Linux: runs in CI's tooling job, and the run scripts build it on the board")
    out = tmp_path_factory.mktemp("cpuload") / "cpuload"
    subprocess.run([gcc, "-O2", "-Wall", "-Wextra", "-Werror", "-o", str(out), CPULOAD_C,
                    "-lpthread", "-lm"], check=True, capture_output=True)
    return str(out)


def test_cpuload_pins_and_verifies_each_thread(cpuload_bin):
    cores = sorted(os.sched_getaffinity(0))
    use = [cores[0], cores[-1]]
    r = subprocess.run([cpuload_bin, "1", "2", "%d,%d" % tuple(use)],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    for i, c in enumerate(use):
        assert "thread %d pinned to core %d (verified)" % (i, c) in r.stdout


@pytest.mark.parametrize("cores", ["0", "0,0,0", "0,x", "4096,0", "", "-1,0", "0,,1"])
def test_cpuload_refuses_a_core_list_that_does_not_fit(cpuload_bin, cores):
    """Two threads need exactly two valid cores -- no cycling, no guessing, no default."""
    r = subprocess.run([cpuload_bin, "1", "2", cores], capture_output=True, text=True, timeout=30)
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)


def test_cpuload_without_cores_stays_unpinned(cpuload_bin):
    r = subprocess.run([cpuload_bin, "1", "1"], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and "(verified)" not in r.stdout


# ============================================================ the pins, read back from cpuload's own log

def _pinlog(tmp_path, lines):
    p = tmp_path / "load.log"
    p.write_bytes(("\n".join(lines) + "\n").encode())
    return _posix(p)


PINNED_OK = ["cpuload: 2 thread(s) for 17 s (no GPU, no memory streaming), PINNED",
             "cpuload: thread 0 pinned to core 3 (verified)",
             "cpuload: thread 1 pinned to core 5 (verified)"]


def test_pins_confirmed_by_cpuload_pass(tmp_path):
    r = _run(tmp_path, 'm_load_require_pinned "%s" 3,5; echo PASSED' % _pinlog(tmp_path, PINNED_OK))
    assert "PASSED" in r.stdout, r.stderr


@pytest.mark.parametrize("lines,cores,why", [
    (["cpuload: 2 thread(s) for 17 s (no GPU, no memory streaming), unpinned"], "3,5",
     "a stale binary ignores CORES"),
    (PINNED_OK, "5,3", "thread 0 on core 5"),
    (PINNED_OK[:2], "3,5", "thread 1 on core 5"),
    (PINNED_OK, "3", "different number of pins"),
    ([], "0", "thread 0 on core 0"),
])
def test_pins_not_confirmed_refuse_the_arm(tmp_path, lines, cores, why):
    """The shape this closes: a pre-2026-09-21 cpuload runs unpinned, stays alive,
    and passes the liveness check -- only its own log says it never pinned."""
    r = _run(tmp_path, 'm_load_require_pinned "%s" %s; echo SHOULD NOT REACH'
             % (_pinlog(tmp_path, lines), cores))
    assert r.returncode != 0 and "SHOULD NOT REACH" not in r.stdout
    assert why in r.stderr, r.stderr


# ============================================================ review of the gap-fill, 2026-09-21

@pytest.mark.parametrize("specs,ok,why", [
    (["qemu=0-2", "probe=4"], True, ""),
    (["qemu=0-2", "monitor=3", "probe=4"], True, ""),
    (["qemu=0-2", "probe=2"], False, "core 2 is both qemu's and probe's"),
    (["qemu=0-2", "monitor=3", "probe=3"], False, "core 3 is both monitor's and probe's"),
    (["qemu=0,2", "probe=1"], True, ""),
])
def test_probe_must_not_share_a_core_with_what_it_measures(tmp_path, specs, ok, why):
    """FOUND BY REVIEW: CORE_PROBE=2 passed every check and put the probe -- at
    SCHED_FIFO in cpu6_prio -- beside a vCPU in every arm, idle included."""
    r = _run(tmp_path, "m_require_disjoint %s; echo PASSED" % " ".join('"%s"' % s for s in specs))
    assert ("PASSED" in r.stdout) is ok, r.stderr
    if not ok:
        assert why in r.stderr


def test_sampler_preflight_refuses_without_the_second_emc_source(tmp_path):
    """FOUND BY REVIEW: the header says BOTH EMC sources are recorded, but only
    BPMP was checked; a missing CCF path ran with a blank field in every window."""
    r = _sampler(tmp_path, 'EMC_CCF=/nonexistent/clk_rate; m_sampler_preflight; echo SHOULD NOT REACH')
    assert r.returncode != 0 and "SHOULD NOT REACH" not in r.stdout
    assert "no clock-framework reading" in r.stderr


def test_sampler_preflight_refuses_when_the_gpu_clock_cannot_be_read(tmp_path):
    """FOUND BY REVIEW: a node that exists but reads empty was never tested."""
    r = _sampler(tmp_path, 'm_sampler_preflight; echo SHOULD NOT REACH', gpu_hz="")
    assert r.returncode != 0 and "no reading from" in r.stderr


def test_sampler_preflight_announces_an_overridden_path(tmp_path):
    r = _sampler(tmp_path, 'm_sampler_preflight')
    assert r.returncode == 0, r.stderr
    assert "WARNING: EMC_BPMP overridden" in r.stdout


@pytest.mark.parametrize("line,ok", [
    ("1789998639.001839 emc_bpmp_hz=2133000000 emc_ccf_hz=204000000 gpu_hz=306000000", True),
    ("1789998639.001839 emc_bpmp_hz= emc_ccf_hz=204000000 gpu_hz=306000000", False),
    ("1789998639.001839 emc_bpmp_hz=2133000000 emc_ccf_hz= gpu_hz=306000000", False),
    ("1789998639.001839 emc_bpmp_hz=2133000000 emc_ccf_hz=204000000 gpu_hz=", False),
    ("1789998639,001839 emc_bpmp_hz=2133000000 emc_ccf_hz=204000000 gpu_hz=306000000", False),
])
def test_every_window_must_hold_a_complete_clock_reading(tmp_path, line, ok):
    """FOUND BY REVIEW: only the preflight was checked, so a credential or node
    lost mid-run would have left windows unrecorded with nothing refusing."""
    out = tmp_path / "out"
    out.mkdir()
    (out / "clk-a_r1.log").write_bytes((line + "\n").encode())
    (out / "tegra-a_r1.log").write_bytes((TEGRA_LINE_ROOT.format(pct=0) + "\n").encode())
    r = _run(tmp_path, 'OUT="%s"; m_sampler_require a_r1; echo PASSED' % _posix(out))
    assert ("PASSED" in r.stdout) is ok, r.stderr


def test_a_window_without_a_cpu_line_is_refused(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "clk-a_r1.log").write_bytes(
        b"1789998639.001839 emc_bpmp_hz=2133000000 emc_ccf_hz=204000000 gpu_hz=306000000\n")
    (out / "tegra-a_r1.log").write_bytes(b"")
    r = _run(tmp_path, 'OUT="%s"; m_sampler_require a_r1; echo PASSED' % _posix(out))
    assert "PASSED" not in r.stdout and "0 line(s) with per-core CPU and EMC_FREQ during a_r1" in r.stderr


def test_a_read_that_fails_mid_run_records_empty_not_the_last_value(tmp_path):
    """The loop clears each field before reading it. Without that, a debugfs node
    that vanished mid-run would repeat its last value and look like a reading."""
    snippet = ('m_sampler_preflight; m_sampler_start mid; sleep 1.3; rm -f "$EMC_BPMP"; '
               'sleep 1.3; m_sampler_stop; tail -n 1 "$OUT/clk-mid.log"')
    r = _sampler(tmp_path, snippet)
    assert r.returncode == 0, r.stderr
    last = r.stdout.strip().splitlines()[-1]
    assert " emc_bpmp_hz= emc_ccf_hz=204000000 " in last, last


def test_stamp_records_the_sampler_and_the_fifo_arms(tmp_path):
    """FOUND BY REVIEW: a comment said the stamp records the sampler's paths; it did not."""
    snippet = ('N=1000; K=12; WARMUP=200; INTERVAL_MS=2; SAMPLE_WINDOW=1; FIFO_ARMS="cpu6_prio"; '
               'm_sampler_preflight; m_write_stamp "$OUT/stamp.json" \'"experiment": "t"\'; '
               'cat "$OUT/stamp.json"')
    r = _sampler(tmp_path, snippet)
    assert r.returncode == 0, r.stderr
    j = json.loads(r.stdout[r.stdout.index("{"):])
    assert j["sample_window"] == 1 and j["fifo_arms"] == "cpu6_prio"
    assert j["sampler_paths"]["emc_bpmp"].endswith("clk/bpmp")
    assert j["sampler_paths"]["gpu_devfreq"].endswith("17000000.gpu/cur_freq")


def test_stamp_records_no_sampler_when_there_is_none(tmp_path):
    snippet = ('N=1000; K=12; WARMUP=200; INTERVAL_MS=2; SAMPLE_WINDOW=0; FIFO_ARMS=""; '
               'OUT="%s"; m_write_stamp "$OUT/stamp.json" \'"experiment": "t"\'; cat "$OUT/stamp.json"'
               % _posix(tmp_path))
    r = _run(tmp_path, snippet)
    assert r.returncode == 0, r.stderr
    j = json.loads(r.stdout[r.stdout.index("{"):])
    assert j["sample_window"] == 0 and "sampler_paths" not in j


def test_probe_refuses_a_window_the_sampler_did_not_record(tmp_path):
    """The per-window check must run inside m_probe, not only in the preflight:
    here the preflight passes, then the CCF node disappears before the arm."""
    fake = tmp_path / "fakeprobe.py"
    fake.write_bytes(b"import sys, json, time\nout = sys.argv[sys.argv.index('--out') + 1]\n"
                     b"time.sleep(1.5)\nopen(out, 'w').write(json.dumps({'summary': {}}))\n")
    snippet = ('N=10; WARMUP=1; INTERVAL_MS=0; CORE_PROBE=0; PROBE="%s"; '
               'taskset() { shift 2; "$@"; }; m_sampler_preflight; rm -f "$EMC_CCF"; '
               'SAMPLE_WINDOW=1 m_probe "$OUT" gone_r1 127.0.0.1 1; echo SHOULD NOT REACH' % _posix(fake))
    r = _sampler(tmp_path, snippet)
    assert r.returncode != 0 and "SHOULD NOT REACH" not in r.stdout
    assert "complete reading(s) during gone_r1" in r.stderr


# A sudo that behaves like the real one where it matters: it runs the command as
# its child and does NOT pass on a TERM sent to it. Real sudo declines to relay a
# signal that comes from the command's own process group, which is where the
# harness's `sudo -n kill` sat -- so on the board the stop was simply ignored.
SUDO_NO_RELAY = """[ "$1" = -n ] && shift
trap ':' TERM
"$@" & c=$!
while kill -0 "$c" 2>/dev/null; do wait "$c"; done
wait "$c"
"""


def test_sampler_stop_really_stops_when_sudo_will_not_relay(tmp_path):
    """FOUND ON THE BOARD, 2026-09-21: the stop signalled sudo, sudo ignored it,
    `wait` blocked for the whole 122 s ceiling and the root loop wrote on. The
    exec-style stub every other test uses could not show it."""
    snippet = ('m_sampler_preflight; t0=$SECONDS; m_sampler_start s; sleep 1.2; m_sampler_stop; echo "rc=$?"; '
               'echo "took=$((SECONDS - t0))"; a=$(wc -l < "$OUT/clk-s.log"); sleep 1.3; '
               'b=$(wc -l < "$OUT/clk-s.log"); echo "lines $a $b"')
    r = _sampler(tmp_path, snippet, sudo=SUDO_NO_RELAY)
    assert r.returncode == 0, r.stderr
    assert "rc=0" in r.stdout, r.stdout
    took = int(r.stdout.split("took=")[1].split()[0])
    assert took <= 6, "stop took %d s -- it waited for the ceiling" % took
    a, b = r.stdout.split("lines ")[1].split()[:2]
    assert a == b and int(a) >= 1, "the clock loop kept writing after stop: %s -> %s" % (a, b)



# ============================================================ a window must be traced across its length

CLK_OK = "1789998639.001839 emc_bpmp_hz=2133000000 emc_ccf_hz=204000000 gpu_hz=306000000"


@pytest.mark.parametrize("clk,tg,ms,ok", [
    (5, 4, 5000, True),      # 5 s window: needs 5 clock and 4 tegrastats lines
    (1, 4, 5000, False),     # the review's case: one sample, then a wedged read
    (5, 3, 5000, False),
    (1, 1, 1600, True),      # the preflight's 1.6 s
    (1, 1, 0, True),         # length unknown: at least one of each
    (12, 11, 12500, True),   # a stalled window runs past the probe's timeout
    (6, 11, 12500, False),
])
def test_a_window_needs_half_its_nominal_samples(tmp_path, clk, tg, ms, ok):
    """FOUND BY REVIEW: one sample passed for a 3 s window the stamp called traced every 500 ms."""
    out = tmp_path / "out"
    out.mkdir()
    (out / "clk-a_r1.log").write_bytes(("\n".join([CLK_OK] * clk) + "\n").encode())
    (out / "tegra-a_r1.log").write_bytes(("\n".join([TEGRA_LINE_ROOT.format(pct=0)] * tg) + "\n").encode())
    r = _run(tmp_path, 'OUT="%s"; m_sampler_require a_r1 %d; echo PASSED' % (_posix(out), ms))
    assert ("PASSED" in r.stdout) is ok, r.stderr


def test_a_user_tegrastats_line_does_not_count(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "clk-a_r1.log").write_bytes((CLK_OK + "\n").encode())
    (out / "tegra-a_r1.log").write_bytes((TEGRA_LINE.format(pct=0) + "\n").encode())
    r = _run(tmp_path, 'OUT="%s"; m_sampler_require a_r1; echo PASSED' % _posix(out))
    assert "PASSED" not in r.stdout and "is it running as root?" in r.stderr


# ============================================================ stalls, recorded (owner decision 2026-09-21)

def _stall_server(stall_at, stall_s):
    """An echo server that stops answering at frame `stall_at` for `stall_s` seconds."""
    import socket
    import threading
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(4)
    stop = threading.Event()

    def serve():
        while not stop.is_set():
            try:
                c, _ = srv.accept()
            except OSError:
                return
            n = 0
            while not stop.is_set():
                buf = b""
                try:
                    while len(buf) < 64:
                        chunk = c.recv(64 - len(buf))
                        if not chunk:
                            break
                        buf += chunk
                except OSError:
                    break
                if len(buf) < 64:
                    break
                n += 1
                if n == stall_at:
                    stop.wait(stall_s)
                try:
                    c.sendall(buf)
                except OSError:
                    break
            c.close()
    threading.Thread(target=serve, daemon=True).start()
    return srv, srv.getsockname()[1], stop


def _probe_cmd(port, *extra):
    import sys
    return [sys.executable, PROBE, "--host", "127.0.0.1", "--port", str(port)] + list(extra)


def test_probe_writes_a_stall_record_and_still_no_result(tmp_path):
    srv, port, stop = _stall_server(stall_at=50, stall_s=3)
    out, st = tmp_path / "lat.json", tmp_path / "stall.json"
    r = subprocess.run(_probe_cmd(port, "--n", "100", "--warmup", "10", "--interval-ms", "1",
                                  "--timeout-s", "1", "--tag", "s_r1", "--out", str(out),
                                  "--stall-out", str(st)),
                       capture_output=True, text=True, timeout=60)
    stop.set()
    srv.close()
    assert r.returncode == 3, r.stdout + r.stderr
    assert not out.exists(), "a stalled arm must not leave a result file"
    rec = json.loads(st.read_text())
    s = rec["stall"]
    assert s["tag"] == "s_r1" and s["kind"] == "timeout" and s["timeout_s"] == 1.0
    assert s["at_sample"] == 49 and s["of"] == 110 and s["warmup"] == 10
    assert len(rec["samples_before_ms"]) == 39, "the timed samples before the stall, in order"
    for k in ("sched_policy", "sched_priority", "cpu_affinity"):
        assert k in s


def test_probe_measures_recovery(tmp_path):
    """Nothing listens for ~1 s, then an echo server does: recovered, after about that long."""
    import socket
    import threading
    import time as _t
    probe_port = socket.socket()
    probe_port.bind(("127.0.0.1", 0))
    port = probe_port.getsockname()[1]
    probe_port.close()

    def late():
        _t.sleep(1.0)
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", port))
        srv.listen(1)
        c, _ = srv.accept()
        c.sendall(c.recv(64))
        c.close()
        srv.close()
    threading.Thread(target=late, daemon=True).start()
    out = tmp_path / "rec.json"
    r = subprocess.run(_probe_cmd(port, "--tag", "s_r1", "--await-recovery", "20", "--out", str(out)),
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    rec = json.loads(out.read_text())
    assert rec["recovered"] is True and rec["tag"] == "s_r1" and 0.5 <= rec["after_s"] < 10


def test_probe_reports_no_recovery_on_the_deadline(tmp_path):
    """A listener that accepts and never answers -- a guest still stalled."""
    import socket
    sk = socket.socket()
    sk.bind(("127.0.0.1", 0))
    sk.listen(16)
    port = sk.getsockname()[1]
    out = tmp_path / "rec.json"
    r = subprocess.run(_probe_cmd(port, "--tag", "s_r1", "--await-recovery", "2.5", "--out", str(out)),
                       capture_output=True, text=True, timeout=60)
    sk.close()
    assert r.returncode == 4 and "NOT RECOVERED" in r.stdout, r.stdout
    assert json.loads(out.read_text())["recovered"] is False


def _fake_probe(tmp_path, rc, stall=True):
    """A probe that exits `rc`, writing a stall record where --stall-out asks when `stall`."""
    fake = tmp_path / "fakeprobe.py"
    fake.write_bytes(("import sys, json\n"
                      "a = sys.argv\n"
                      "if '--stall-out' in a and %r:\n"
                      "    open(a[a.index('--stall-out') + 1], 'w').write(json.dumps({'stall': {}}))\n"
                      "if %d == 0:\n"
                      "    open(a[a.index('--out') + 1], 'w').write('{}')\n"
                      "print('FATAL desync tag=' + a[a.index('--tag') + 1] + ' at sample 7 of 1200: x')\n"
                      "sys.exit(%d)\n" % (stall, rc, rc)).encode())
    return _posix(fake)


@pytest.mark.parametrize("policy,rc,stall,expect", [
    ("record", 3, True, "returned 3"),                          # a recorded stall is an outcome
    ("record", 3, False, "wrote no stall record"),              # a stall with no record stops the run
    ("record", 2, True, "probe failed on s_r1 (exit 2)"),       # any other failure stops the run
    ("record", 5, True, "probe failed on s_r1 (exit 5)"),       # a broken stream is not a stall
    ("", 3, True, "probe failed on s_r1 (exit 3)"),             # without the policy, a stall stops the run
    ("record", 0, False, "returned 0"),
])
def test_m_probe_treats_only_a_recorded_stall_as_an_outcome(tmp_path, policy, rc, stall, expect):
    """FOUND BY REVIEW: the first version only looked for "FATAL", which the fake
    probe's own output supplied, so two mutants that broke the rule passed."""
    out = tmp_path / "out"
    out.mkdir()
    snippet = ('N=10; WARMUP=1; INTERVAL_MS=0; CORE_PROBE=0; SAMPLE_WINDOW=0; STALL_POLICY="%s"; PROBE="%s"; '
               'taskset() { shift 2; "$@"; }; m_probe "%s" s_r1 127.0.0.1 1; echo "returned $?"; '
               'cat "%s/stalls.log" 2>/dev/null; true'
               % (policy, _fake_probe(tmp_path, rc, stall), _posix(out), _posix(out)))
    r = _run(tmp_path, snippet)
    if expect.startswith("returned"):
        assert r.returncode == 0 and expect in r.stdout, r.stdout + r.stderr
    else:
        assert r.returncode != 0 and "returned" not in r.stdout, r.stdout + r.stderr
        assert expect in r.stderr, r.stderr
    if expect == "returned 3":
        assert "s_r1 stalled after" in r.stdout and "FATAL desync tag=s_r1" in r.stdout


@pytest.mark.parametrize("rc,ok", [(0, True), (4, False)])
def test_await_recovery_goes_on_only_if_the_guest_answers(tmp_path, rc, ok):
    fake = tmp_path / "rec.py"
    fake.write_bytes(("import sys\nprint('RECOVERED after 1.20 s (attempts=3)' if %d == 0 "
                      "else 'NOT RECOVERED within 120 s')\nsys.exit(%d)\n" % (rc, rc)).encode())
    out = tmp_path / "out"
    out.mkdir()
    (out / "probe.log").write_text("")
    r = _run(tmp_path, 'CORE_PROBE=0; PROBE="%s"; taskset() { shift 2; "$@"; }; '
             'm_await_recovery "%s" s_r1 127.0.0.1 1; echo WENT_ON' % (_posix(fake), _posix(out)))
    assert ("WENT_ON" in r.stdout) is ok, r.stdout + r.stderr
    assert "s_r1 recovery:" in (out / "stalls.log").read_text()


def _stall_record(tag, policy="SCHED_OTHER", priority=0, timeout=10.0):
    return {"stall": {"tag": tag, "proto": "tcp", "kind": "timeout", "at_sample": 391, "of": 1200, "warmup": 200,
                      "timeout_s": timeout, "why": "timed out", "bad": 1, "rejected_by_monitor": 0,
                      "sched_policy": policy, "sched_priority": priority, "cpu_affinity": [4]},
            "samples_before_ms": [0.3] * 191}


def _stall_dir(tmp_path, arms, stalled, recovered=True, both=False, record=None):
    d = _sched_dir(tmp_path, arms, _fifo_on("cpu6_prio"))
    for tag in stalled:
        a = tag.rsplit("_r", 1)[0]
        rec = record(tag) if record else _stall_record(
            tag, *(("SCHED_FIFO", 50) if a == "cpu6_prio" else ("SCHED_OTHER", 0)))
        (d / ("stall-%s.json" % tag)).write_text(json.dumps(rec))
        if not both:
            (d / ("lat-%s.json" % tag)).unlink()
        if recovered is not None:
            (d / ("recovery-%s.json" % tag)).write_text(json.dumps({"tag": tag, "recovered": recovered}))
    return d


def _stall_gate(tmp_path, d, arms, policy="record"):
    return _run(tmp_path, 'K=2; N=1000; WARMUP=200; CORE_PROBE=4; FIFO_ARMS="cpu6_prio"; STALL_POLICY="%s"; '
                'm_require_complete "%s" %s; echo PASSED' % (policy, _posix(d), " ".join(arms)))


def test_gate_accepts_a_recorded_stall_in_place_of_a_result(tmp_path):
    arms = ["idle", "cpu2_q", "cpu6_prio"]
    d = _stall_dir(tmp_path, arms, ["cpu2_q_r2", "cpu6_prio_r1"])
    r = _stall_gate(tmp_path, d, arms)
    assert "PASSED" in r.stdout, r.stderr
    assert "STALLED: cpu2_q in 1 of 2 rounds (r2)" in r.stdout


@pytest.mark.parametrize("kwargs,why", [
    (dict(both=True), "both a result and a stall record"),
    (dict(recovered=False), "does not say the guest answered again"),
    (dict(recovered=None), "no readable recovery record"),
    (dict(record=lambda t: _stall_record(t, timeout=5.0)), "stall timeout_s=5.0, expected 10.0"),
    (dict(record=lambda t: _stall_record(t, policy="SCHED_FIFO", priority=50)), "expected 'SCHED_OTHER'"),
    (dict(record=lambda t: {"stall": dict(_stall_record(t)["stall"], kind="odd")}), "stall kind='odd'"),
    (dict(record=lambda t: {"stall": dict(_stall_record(t)["stall"], kind="framing")}), "stall kind='framing'"),
])
def test_gate_refuses_a_stall_record_that_does_not_hold_up(tmp_path, kwargs, why):
    arms = ["idle", "cpu2_q"]
    d = _stall_dir(tmp_path, arms, ["cpu2_q_r2"], **kwargs)
    r = _stall_gate(tmp_path, d, arms)
    assert "PASSED" not in r.stdout and why in r.stderr, r.stderr


def test_gate_refuses_a_stall_record_without_the_policy(tmp_path):
    arms = ["idle", "cpu2_q"]
    d = _stall_dir(tmp_path, arms, ["cpu2_q_r2"])
    r = _stall_gate(tmp_path, d, arms, policy="")
    assert "PASSED" not in r.stdout and "STALL_POLICY is not 'record'" in r.stderr


def test_summary_reports_stalls_beside_k(tmp_path):
    arms = ["idle", "cpu2_q"]
    d = _stall_dir(tmp_path, arms, ["cpu2_q_r2"])
    r = _run(tmp_path, 'K=2; m_summary "%s" idle idle cpu2_q' % _posix(d))
    assert r.returncode == 0, r.stderr
    line = [l for l in r.stdout.splitlines() if l.strip().startswith("cpu2_q")][0]
    assert " 1 " in line and "STALLED in 1 round(s), not in k" in line
    assert "k counts complete rounds only" in r.stdout



def test_gate_accepts_a_stall_that_began_before_the_connect(tmp_path):
    arms = ["idle", "cpu2_q"]
    d = _stall_dir(tmp_path, arms, ["cpu2_q_r1"],
                   record=lambda t: {"stall": dict(_stall_record(t)["stall"], kind="connect", at_sample=0),
                                     "samples_before_ms": []})
    r = _stall_gate(tmp_path, d, arms)
    assert "PASSED" in r.stdout, r.stderr


# ============================================================ what is and is not a stall (review, 2026-09-21)

def _run_probe_with(tmp_path, patch, *args):
    """Run the real probe with socket.create_connection replaced by `patch` (source text)."""
    import sys
    runner = tmp_path / "runner.py"
    runner.write_bytes(("import runpy, socket, sys\n%s\n"
                        "sys.argv = [%r] + sys.argv[1:]\n"
                        "runpy.run_path(%r, run_name='__main__')\n" % (patch, PROBE, PROBE)).encode())
    return subprocess.run([sys.executable, str(runner)] + list(args), capture_output=True, text=True, timeout=60)


CONNECT_TIMES_OUT = ("def _ct(*a, **k):\n    raise socket.timeout('timed out')\n"
                     "socket.create_connection = _ct")
CONNECT_REFUSED = ("def _cr(*a, **k):\n    raise ConnectionRefusedError(111, 'Connection refused')\n"
                   "socket.create_connection = _cr")


def test_a_connect_timeout_is_a_stall_when_stalls_are_recorded(tmp_path):
    """FOUND BY REVIEW: the load runs ~5 s before the probe connects, so a stall can
    already be under way; the connect then timed out, the probe exited 2, and the
    run stopped -- while the same stall one frame later was recorded."""
    st = tmp_path / "stall.json"
    r = _run_probe_with(tmp_path, CONNECT_TIMES_OUT, "--host", "127.0.0.1", "--port", "1", "--n", "10",
                        "--warmup", "2", "--tag", "c_r1", "--out", str(tmp_path / "lat.json"),
                        "--stall-out", str(st))
    assert r.returncode == 3, r.stdout + r.stderr
    rec = json.loads(st.read_text())
    assert rec["stall"]["kind"] == "connect" and rec["stall"]["at_sample"] == 0
    assert rec["samples_before_ms"] == []


@pytest.mark.parametrize("patch,stall_out", [(CONNECT_TIMES_OUT, False), (CONNECT_REFUSED, True)])
def test_other_connect_failures_are_not_stalls(tmp_path, patch, stall_out):
    """No --stall-out: a connect timeout is the old exit 2. Refused: never a stall."""
    st = tmp_path / "stall.json"
    extra = ["--stall-out", str(st)] if stall_out else []
    r = _run_probe_with(tmp_path, patch, "--host", "127.0.0.1", "--port", "1", "--tag", "c_r1",
                        "--out", str(tmp_path / "lat.json"), *extra)
    assert r.returncode == 2 and "FATAL connect" in r.stdout, r.stdout + r.stderr
    assert not st.exists()


def test_a_dropped_connection_is_broken_not_stalled(tmp_path):
    """FOUND BY REVIEW: a reset or a close used to leave by the stall's door, so a
    connection the guest dropped would have been filed as a 10 s stall."""
    import socket
    import threading
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def serve():
        c, _ = srv.accept()
        for _ in range(20):
            buf = b""
            while len(buf) < 64:
                chunk = c.recv(64 - len(buf))
                if not chunk:
                    return
                buf += chunk
            c.sendall(buf)
        c.close()
    threading.Thread(target=serve, daemon=True).start()
    st, out = tmp_path / "stall.json", tmp_path / "lat.json"
    r = subprocess.run(_probe_cmd(port, "--n", "100", "--warmup", "5", "--interval-ms", "0",
                                  "--timeout-s", "5", "--tag", "d_r1", "--out", str(out),
                                  "--stall-out", str(st)),
                       capture_output=True, text=True, timeout=60)
    srv.close()
    assert r.returncode == 5 and "FATAL broken stream tag=d_r1" in r.stdout, r.stdout + r.stderr
    assert not st.exists() and not out.exists()


# ============================================================ cpuload is built by the run

def test_the_run_builds_cpuload_and_refuses_a_bad_source(tmp_path, cpuload_bin):
    good = _posix(CPULOAD_C)
    bad = tmp_path / "bad.c"
    bad.write_bytes(b"int main(void) { int unused; return 0; }\n")   # -Werror: unused variable
    out = tmp_path / "cpuload"
    r = _run(tmp_path, 'm_build_cpuload "%s" "%s"; echo BUILT' % (good, _posix(out)))
    assert "BUILT" in r.stdout and out.exists(), r.stderr
    r = _run(tmp_path, 'm_build_cpuload "%s" "%s"; echo SHOULD NOT REACH' % (_posix(bad), _posix(tmp_path / "x")))
    assert r.returncode != 0 and "did not build" in r.stderr


def test_a_garbled_reply_is_broken_not_stalled(tmp_path):
    """The framing path, reached without any socket error: frame 21 comes back
    with the wrong sequence number. Found by mutation: the dropped-connection
    test ends in a reset on some platforms and never reaches this check."""
    import socket
    import threading
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def serve():
        c, _ = srv.accept()
        n = 0
        while True:
            buf = b""
            while len(buf) < 64:
                chunk = c.recv(64 - len(buf))
                if not chunk:
                    return
                buf += chunk
            n += 1
            if n == 21:
                buf = bytes([buf[0] ^ 0xFF]) + buf[1:]
            try:
                c.sendall(buf)
            except OSError:
                return
    threading.Thread(target=serve, daemon=True).start()
    st, out = tmp_path / "stall.json", tmp_path / "lat.json"
    r = subprocess.run(_probe_cmd(port, "--n", "100", "--warmup", "5", "--interval-ms", "0",
                                  "--timeout-s", "5", "--tag", "g_r1", "--out", str(out),
                                  "--stall-out", str(st)),
                       capture_output=True, text=True, timeout=60)
    srv.close()
    assert r.returncode == 5, r.stdout + r.stderr
    assert "framing lost" in r.stdout and "seq MISMATCH" in r.stdout
    assert not st.exists() and not out.exists()


# ============================================================ UDP arms (owner decision OD12, 2026-09-21)

def _probe_mod():
    import importlib.util
    spec = importlib.util.spec_from_file_location("latency_probe_mod", PROBE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _udp_server(behaviour):
    """A UDP echo on loopback. behaviour(n, datagram) returns a list of datagrams
    to send back for the n-th datagram received (1-based)."""
    import socket
    import threading
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind(("127.0.0.1", 0))
    srv.settimeout(0.2)
    stop = threading.Event()

    def serve():
        n = 0
        while not stop.is_set():
            try:
                data, peer = srv.recvfrom(4096)
            except OSError:
                continue
            n += 1
            for out in behaviour(n, data):
                srv.sendto(out, peer)
    threading.Thread(target=serve, daemon=True).start()
    return srv, srv.getsockname()[1], stop


def _udp_probe(port, tmp_path, *extra):
    out, st = tmp_path / "lat.json", tmp_path / "stall.json"
    r = subprocess.run(_probe_cmd(port, "--proto", "udp", "--n", "60", "--warmup", "5", "--interval-ms", "0",
                                  "--timeout-s", "1", "--tag", "u_r1", "--out", str(out),
                                  "--stall-out", str(st), *extra),
                       capture_output=True, text=True, timeout=60)
    return r, out, st


def test_udp_probe_times_a_clean_arm(tmp_path):
    srv, port, stop = _udp_server(lambda n, d: [d])
    r, out, st = _udp_probe(port, tmp_path)
    stop.set()
    srv.close()
    assert r.returncode == 0, r.stdout + r.stderr
    s = json.loads(out.read_text())["summary"]
    assert s["proto"] == "udp" and s["n"] == 60 and not st.exists()


def test_udp_probe_records_a_missing_reply_as_a_stall(tmp_path):
    """The first run's loss policy: no reply within --timeout-s is a stall, and the
    record says it was UDP, where a loss and a stall cannot be told apart."""
    srv, port, stop = _udp_server(lambda n, d: [] if n == 20 else [d])
    r, out, st = _udp_probe(port, tmp_path)
    stop.set()
    srv.close()
    assert r.returncode == 3, r.stdout + r.stderr
    rec = json.loads(st.read_text())["stall"]
    assert rec["proto"] == "udp" and rec["kind"] == "timeout" and rec["at_sample"] == 19
    assert not out.exists()


@pytest.mark.parametrize("name,behaviour,why", [
    ("wrong seq", lambda n, d: [bytes([d[0] ^ 0xFF]) + d[1:]] if n == 20 else [d], "seq MISMATCH"),
    ("short", lambda n, d: [d[:63]] if n == 20 else [d], "framing lost (got 63 of 64"),
    ("long", lambda n, d: [d + b"x"] if n == 20 else [d], "framing lost (got 65 of 64"),
    ("duplicate", lambda n, d: [d, d] if n == 20 else [d], "seq MISMATCH"),
])
def test_udp_probe_treats_a_wrong_reply_as_broken(tmp_path, name, behaviour, why):
    """A reply that is not exactly the frame sent -- wrong sequence, wrong size, a
    duplicate read as the next frame's -- is a broken stream: exit 5, no record."""
    srv, port, stop = _udp_server(behaviour)
    r, out, st = _udp_probe(port, tmp_path)
    stop.set()
    srv.close()
    assert r.returncode == 5, (name, r.stdout, r.stderr)
    assert why in r.stdout, r.stdout
    assert not out.exists() and not st.exists()


def test_udp_recovery_waits_for_a_framed_reply(tmp_path):
    import socket
    import threading
    import time as _t
    tmp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    tmp.bind(("127.0.0.1", 0))
    port = tmp.getsockname()[1]
    tmp.close()

    def late():
        _t.sleep(1.0)
        srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        srv.bind(("127.0.0.1", port))
        srv.settimeout(10)
        data, peer = srv.recvfrom(4096)
        srv.sendto(data, peer)
        srv.close()
    threading.Thread(target=late, daemon=True).start()
    out = tmp_path / "rec.json"
    r = subprocess.run(_probe_cmd(port, "--proto", "udp", "--tag", "u_r1", "--await-recovery", "20",
                                  "--out", str(out)), capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    rec = json.loads(out.read_text())
    assert rec["recovered"] is True and 0.5 <= rec["after_s"] < 10


def _proto_dir(tmp_path, arms, proto_of):
    def m(a, r, s):
        s["proto"] = proto_of(a)
    return _sched_dir(tmp_path, arms, m)


def _proto_gate(tmp_path, d, arms, udp_arms):
    return _run(tmp_path, 'K=2; N=1000; WARMUP=200; CORE_PROBE=4; FIFO_ARMS=""; UDP_ARMS="%s"; '
                'm_require_complete "%s" %s; echo PASSED' % (udp_arms, _posix(d), " ".join(arms)))


def test_gate_accepts_udp_arms_that_say_udp(tmp_path):
    arms = ["A-loopback", "A-udp"]
    d = _proto_dir(tmp_path, arms, lambda a: "udp" if a.endswith("-udp") else "tcp")
    r = _proto_gate(tmp_path, d, arms, "A-udp")
    assert "PASSED" in r.stdout, r.stderr


@pytest.mark.parametrize("proto_of,udp_arms,why", [
    (lambda a: "tcp", "A-udp", "A-udp_r1: proto='tcp', expected 'udp'"),
    (lambda a: "udp", "A-udp", "A-loopback_r1: proto='udp', expected 'tcp'"),
    (lambda a: None, "", "A-loopback_r1: proto=None, expected 'tcp'"),
])
def test_gate_refuses_a_file_run_over_the_wrong_transport(tmp_path, proto_of, udp_arms, why):
    """FOUND BY DESIGN: a UDP arm silently run over TCP would pair two copies of one
    path and report a difference of zero as a finding."""
    arms = ["A-loopback", "A-udp"]
    d = _proto_dir(tmp_path, arms, proto_of)
    r = _proto_gate(tmp_path, d, arms, udp_arms)
    assert "PASSED" not in r.stdout and why in r.stderr, r.stderr


def test_gate_refuses_a_stall_record_from_the_wrong_transport(tmp_path):
    """FOUND BY REVIEW: deleting the stall-record half of the proto check left every
    test passing."""
    arms = ["D-guest", "D-udp"]

    def proto(a, r, s):
        s["proto"] = "udp" if a == "D-udp" else "tcp"
    d = _sched_dir(tmp_path, arms, proto)
    rec = _stall_record("D-udp_r2")          # proto 'tcp' in a UDP arm's stall record
    (d / "stall-D-udp_r2.json").write_text(json.dumps(rec))
    (d / "lat-D-udp_r2.json").unlink()
    (d / "recovery-D-udp_r2.json").write_text(json.dumps({"tag": "D-udp_r2", "recovered": True}))
    r = _run(tmp_path, 'K=2; N=1000; WARMUP=200; CORE_PROBE=4; FIFO_ARMS=""; STALL_POLICY=record; '
             'UDP_ARMS="D-udp"; m_require_complete "%s" %s; echo PASSED' % (_posix(d), " ".join(arms)))
    assert "PASSED" not in r.stdout and "D-udp_r2: proto='tcp', expected 'udp'" in r.stderr, r.stderr


def test_m_probe_passes_the_transport_to_the_probe(tmp_path):
    fake = tmp_path / "argv.py"
    fake.write_bytes(b"import sys, json\na = sys.argv\n"
                     b"open(a[a.index('--out') + 1], 'w').write(json.dumps({'argv': a[1:]}))\n")
    out = tmp_path / "out"
    out.mkdir()
    r = _run(tmp_path, 'N=10; WARMUP=1; INTERVAL_MS=0; CORE_PROBE=0; SAMPLE_WINDOW=0; PROBE="%s"; '
             'taskset() { shift 2; "$@"; }; m_probe "%s" x_r1 127.0.0.1 1 "" udp; '
             'm_probe "%s" y_r1 127.0.0.1 1' % (_posix(fake), _posix(out), _posix(out)))
    assert r.returncode == 0, r.stderr
    ux = json.loads((out / "lat-x_r1.json").read_text())["argv"]
    ty = json.loads((out / "lat-y_r1.json").read_text())["argv"]
    assert ux[ux.index("--proto") + 1] == "udp"
    assert ty[ty.index("--proto") + 1] == "tcp", "the default must stay tcp"


def test_m_pairs_is_the_median_of_within_round_differences(tmp_path):
    d = tmp_path / "run"
    d.mkdir()
    for arm, vals in (("A-loopback", [0.100, 0.200, 0.300]), ("A-udp", [0.300, 0.210, 0.310])):
        for r, v in enumerate(vals, 1):
            (d / ("lat-%s_r%d.json" % (arm, r))).write_text(json.dumps(
                {"summary": {"tag": "%s_r%d" % (arm, r), "p50_ms": v}}))
    r = _run(tmp_path, 'm_pairs "%s" A-udp:A-loopback B-udp:B-bridge' % _posix(d))
    assert r.returncode == 0, r.stderr
    line = [l for l in r.stdout.splitlines() if "A-udp - A-loopback" in l][0]
    assert "+10.0" in line and "3/3" in line, line   # per-round +200, +10, +10: paired median +10
    assert "no round where both completed" in r.stdout


BTIME = 1790000000        # 2026-09-21T13:33:20Z
STARTTIME = 500000        # clock ticks after boot: 500 s at 1000/s, 5000 s at 100/s


def _fake_qemu(tmp_path, kernel, drive, files=(), mtime=BTIME - 3600):
    """A fake /proc for pid 4242: its cmdline, a stat whose fields 20-23 are all
    DISTINCT (so reading the wrong field gives the wrong time), btime, and a cwd."""
    proc = tmp_path / "proc"
    (proc / "4242").mkdir(parents=True, exist_ok=True)
    cwd = proc / "4242" / "cwd"
    cwd.mkdir(exist_ok=True)
    for name, data in files:
        f = cwd / name
        f.write_bytes(data)
        os.utime(f, (mtime, mtime))
    argv = ["qemu-system-aarch64", "-machine", "virt", "-kernel", kernel, "-drive", drive, "-snapshot"]
    (proc / "4242" / "cmdline").write_bytes(("\0".join(argv) + "\0").encode())
    # Fields 4..21, then 22 = starttime, then 23. Fields 20 and 21 are small and
    # distinct and 22 is large, so reading the wrong field moves the start by
    # minutes whatever CLK_TCK is (Git Bash reports 1000, Linux 100). A first
    # version put 500 in field 23 and missed a field-21 mutant: at 1000 ticks/s
    # both it and the real field rounded to 0 s.
    fields = [b"0"] * 16 + [b"7", b"8"] + [b"%d" % STARTTIME, b"11"]
    (proc / "4242" / "stat").write_bytes(b"4242 (qemu-system-aar) S " + b" ".join(fields) + b"\n")
    (proc / "stat").write_bytes(b"cpu 1 2 3\nbtime %d\n" % BTIME)
    return proc, cwd


def _identity(tmp_path, proc):
    return _run(tmp_path, 'PROC_ROOT="%s"; QPID=4242; _guest_identity; echo "IFS=$GUEST_IFS"; '
                'echo "SHA=$GUEST_IFS_SHA"; echo "DSHA=$GUEST_DISK_SHA"; echo "START=$QSTART"' % _posix(proc))


def test_stamp_identifies_the_guest_by_hash(tmp_path):
    """ADDED 2026-09-22: the image and disk the running QEMU actually booted, read
    from its own command line -- relative paths resolved against QEMU's cwd, not
    this script's -- hashed; and when that process started, to the second."""
    import datetime
    import hashlib
    proc, cwd = _fake_qemu(tmp_path, "ifs-udp.bin", "file=disk-qemu,if=none,id=drv0,format=raw",
                           files=(("ifs-udp.bin", b"image"), ("disk-qemu", b"disk")))
    r = _identity(tmp_path, proc)
    assert r.returncode == 0, r.stderr
    assert "SHA=%s" % hashlib.sha256(b"image").hexdigest() in r.stdout
    assert "DSHA=%s" % hashlib.sha256(b"disk").hexdigest() in r.stdout
    tck = int(subprocess.run([BASH, "-c", "getconf CLK_TCK"], capture_output=True, text=True).stdout)
    want = datetime.datetime.fromtimestamp(BTIME + STARTTIME // tck, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert "START=%s" % want in r.stdout, (want, r.stdout)


@pytest.mark.parametrize("case,why", [
    ("unreadable", "cannot read the guest image"),
    ("changed", "changed after QEMU started"),
])
def test_guest_identity_refuses_an_image_it_cannot_vouch_for(tmp_path, case, why):
    """FOUND BY REVIEW: the hash is taken at stamp time, so a missing file, or one
    rebuilt over the same path after boot, would name the wrong image."""
    files = (("disk-qemu", b"disk"),) if case == "unreadable" else (("ifs-udp.bin", b"image"), ("disk-qemu", b"disk"))
    # well after QEMU's start at either clock rate (start = BTIME + 500 s or + 5000 s)
    mtime = BTIME + 100000 if case == "changed" else BTIME - 3600
    proc, cwd = _fake_qemu(tmp_path, "ifs-udp.bin", "file=disk-qemu,if=none", files=files, mtime=mtime)
    r = _identity(tmp_path, proc)
    assert r.returncode != 0 and why in r.stderr, r.stdout + r.stderr


@pytest.mark.parametrize("rc,why", [(4, "no framed reply in 5 s"), (2, "could not run (probe exit 2)")])
def test_udp_reachability_names_why_it_failed(tmp_path, rc, why):
    """FOUND BY REVIEW: a probe too old to know --proto exits 2 on the argument, and
    was reported as an unreachable guest."""
    fake = tmp_path / "p.py"
    fake.write_bytes(b"import sys\nsys.exit(%d)\n" % rc)
    r = _run(tmp_path, 'PROBE="%s"; m_reachable_udp 127.0.0.1 1 D-udp; echo SHOULD NOT REACH' % _posix(fake))
    assert r.returncode != 0 and why in r.stderr, r.stderr


LADDER = os.path.join(HERE, "..", "orin-native", "gpu-concurrency", "run-ladder.sh")


@pytest.mark.parametrize("env,why", [
    ({"UDP": "yes"}, "UDP='yes' must be 0 or 1"),
    ({"UDP": "1", "K": "13"}, "need K to be a multiple of 2"),
    ({"UDP": "1", "PORT_UDP": "71o1"}, "is not a port number"),
    ({"SHM": "yes"}, "SHM='yes' must be 0 or 1"),
    ({"SHM": "1", "K": "13"}, "need K to be a multiple of 2"),
    ({"UDP": "1", "SHM": "1", "K": "8"}, "need K to be a multiple of 6"),
    ({"K": "twelve"}, "K='twelve' is not a round count"),
    ({"KICK": "yes"}, "KICK='yes' must be 0 or 1"),
    ({"DB": "2"}, "DB='2' must be 0 or 1"),
    ({"KVM_STATS": "on"}, "KVM_STATS='on' must be 0 or 1"),
    ({"DB_BURST": "many"}, "DB_BURST='many' is not a count"),
    ({"SLOT_OFF": "100"}, "SLOT_OFF=100 must be a non-zero multiple of 4096"),
    ({"SLOT_OFF": "0"}, "SLOT_OFF=0 must be a non-zero multiple of 4096"),
    ({"SHM": "1", "KICK": "1", "DB": "1", "K": "6"}, "need K to be a multiple of 4"),
    ({"UDP": "1", "SHM": "1", "KICK": "1", "DB": "1", "K": "12"}, "need K to be a multiple of 10"),
    ({"UDP": "1", "UDP_IN_TCP": "1", "K": "2"}, "UDP_IN_TCP=1 needs UDP=0"),
    ({"UDP_IN_TCP": "yes"}, "UDP_IN_TCP='yes' must be 0 or 1"),
    ({"DB_BURST": "0"}, "DB_BURST=0 must be 1000..100000"),
    ({"DB_BURST": "200000"}, "DB_BURST=200000 must be 1000..100000"),
])
def test_ladder_refuses_a_udp_setting_it_cannot_honour(tmp_path, env, why):
    """FOUND BY REVIEW: UDP=true ran TCP-only under a stamp saying enabled; an odd K
    left the transport order unbalanced while the header called it balanced."""
    e = dict(os.environ)
    e.update(env)
    r = subprocess.run([BASH, LADDER], env=e, capture_output=True, text=True, timeout=60)
    assert r.returncode != 0 and why in r.stderr, r.stdout + r.stderr


# ============================================================ the servers' UDP modes (need gcc)

MONITOR_C = os.path.join(HERE, "..", "ipc-test", "qnx-safety-monitor", "monitor.c")
SERVER_C = os.path.join(HERE, "..", "ipc-test", "qnx-server-net", "server.c")
COMMON = os.path.join(HERE, "..", "ipc-test", "common")
SHM_MAP_POSIX_C = os.path.join(COMMON, "shm_map_posix.c")
IVSHM_CLIENT_C = os.path.join(COMMON, "ivshm_client.c")
IVSHMEM_SERVER_PY = os.path.join(HERE, "..", "orin-native", "gpu-concurrency", "ivshmem_server.py")
SHMCHAN_C = os.path.join(HERE, "..", "orin-native", "gpu-concurrency", "shmchan.c")


@pytest.fixture(scope="module")
def native_servers(tmp_path_factory):
    gcc = shutil.which("gcc")
    if gcc is None or not hasattr(os, "sched_getaffinity"):
        pytest.skip("needs gcc on Linux: runs in CI's tooling job")
    d = tmp_path_factory.mktemp("servers")
    # OD12 (2026-09-22): the monitor's shm transport maps its region through
    # shm_map(), which the host build takes from shm_map_posix.c.
    # 2026-09-22, notified variant: shm_map_posix.c joins an ivshmem server
    # through ivshm_client.c, so both the monitor and the library link it.
    for srcs, name in (([MONITOR_C, SHM_MAP_POSIX_C, IVSHM_CLIENT_C], "monitor"), ([SERVER_C], "echo")):
        subprocess.run([gcc, "-O2", "-std=gnu99", "-Wall", "-Wextra", "-Werror", "-I", COMMON,
                        "-o", str(d / name)] + srcs, check=True, capture_output=True)
    subprocess.run([gcc, "-O2", "-Wall", "-Wextra", "-Werror", "-shared", "-fPIC", "-I", COMMON,
                    "-o", str(d / "libshmchan.so"), SHMCHAN_C, SHM_MAP_POSIX_C, IVSHM_CLIENT_C],
                   check=True, capture_output=True)
    return d


def _free_udp_port():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _exchange(port, data, timeout=1.0):
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("127.0.0.1", port))
    s.settimeout(timeout)
    s.send(data)
    try:
        return s.recv(4096)
    except socket.timeout:
        return None
    finally:
        s.close()


@pytest.mark.parametrize("name", ["monitor", "echo"])
def test_native_server_udp_mode(native_servers, name):
    import time as _t
    lp = _probe_mod()
    port = _free_udp_port()
    p = subprocess.Popen([str(native_servers / name), str(port), "udp"],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        _t.sleep(0.3)
        frame = lp.build_frame(7)
        # A claim the monitor must REJECT (class 42 is outside 0..9). FOUND BY
        # REVIEW: with only acceptable claims, whose verdict bytes are already 0,
        # a UDP path that never judged passed every assertion.
        bad = bytearray(lp.build_frame(8))
        bad[16] = 42
        bad = bytes(bad)
        got = _exchange(port, frame)
        assert got is not None and len(got) == 64 and got[:8] == frame[:8]
        rej = _exchange(port, bad)
        if name == "monitor":
            assert got[16 + 6] == 0 and got[16 + 7] == 0, "an acceptable claim: verdict 0, reason 0"
            assert rej[16 + 6] == 1 and rej[16 + 7] == 1, "class 42: verdict 1 (reject), reason 1 (class range)"
        else:
            assert got == frame and rej == bad, "the echo must be verbatim, whatever the payload"
        # The sentinel carries the REJECTABLE payload: judging it would change it.
        sentinel = b"\xff" * 8 + bad[8:]
        assert _exchange(port, sentinel) == sentinel, "the sentinel comes back untouched"
        assert _exchange(port, frame[:63], timeout=0.5) is None, "a short datagram gets no reply"
        assert _exchange(port, frame + b"x", timeout=0.5) is None, "a long datagram gets no reply"
        second = subprocess.run([str(native_servers / name), str(port), "udp"],
                                capture_output=True, text=True, timeout=10)
        assert second.returncode == 1 and "bind" in second.stderr, "a second UDP server must fail to bind"
    finally:
        p.terminate()
        out, err = p.communicate(timeout=10)
    if name == "monitor":
        assert "udp done: seen=2 accepted=1 rejected=1 dropped=2" in out.decode(), \
            "the sentinel is not counted, drops are: %r" % out
    else:
        assert "udp stop after 3 frames, 2 dropped" in err.decode(), err


@pytest.mark.parametrize("name", ["monitor", "echo"])
def test_native_server_refuses_an_unknown_transport(native_servers, name):
    r = subprocess.run([str(native_servers / name), str(_free_udp_port()), "udq"],
                       capture_output=True, text=True, timeout=10)
    assert r.returncode == 2 and "unknown transport" in r.stderr


# ============================================================ the monitor's rules, pinned (2026-09-23)
#
# ADDED BEFORE the VLM service arm touches monitor.c, so that change can prove the
# legacy path came through it unchanged. Every A6 latency figure rides on that
# path: latency_probe's frame (class 3, conf 95, 124 us, zeros elsewhere) must
# keep getting verdict 0, or rejected_by_monitor > 0 and the completeness gate
# refuses the run. Until now only class 42 (reason 1) was tested, so a change to
# any threshold or to the order of the checks would have passed CI.

_RULES = [
    # label,                        class, conf,     us, verdict, reason
    ("the probe's frame",               3,   95,    124, 0, 0),
    ("class 9, the top label",          9,   95,    124, 0, 0),
    ("class 10",                       10,   95,    124, 1, 1),
    ("conf 100",                        3,  100,    124, 0, 0),
    ("conf 101",                        3,  101,    124, 1, 2),
    ("conf 60, which is CONF_MIN",      3,   60,    124, 0, 0),
    ("conf 59",                         3,   59,    124, 1, 3),
    ("us 100000, which is INFER_US_MAX", 3,  95, 100000, 0, 0),
    ("us 100001",                       3,   95, 100001, 1, 4),
    ("us 0: there is no lower bound",   3,   95,      0, 0, 0),
    # The order: the first failing check names the reason.
    ("class before conf range",        10,  101,    124, 1, 1),
    ("conf range before us",            3,  101, 100001, 1, 2),
    ("us before conf-low",              3,   59, 100001, 1, 4),
]


@pytest.fixture(scope="module")
def udp_monitor(native_servers):
    import time as _t
    port = _free_udp_port()
    p = subprocess.Popen([str(native_servers / "monitor"), str(port), "udp"],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _t.sleep(0.3)
    yield port, p
    p.terminate()
    p.communicate(timeout=10)


def _claim(seq, cls, conf, us):
    f = bytearray(_probe_mod().build_frame(seq))
    f[16 + 0] = cls
    f[16 + 1] = conf
    f[16 + 2:16 + 6] = us.to_bytes(4, "little")
    return bytes(f)


@pytest.mark.parametrize("label,cls,conf,us,verdict,reason", _RULES, ids=[r[0] for r in _RULES])
def test_monitor_rules_are_pinned_at_every_boundary(udp_monitor, label, cls, conf, us, verdict, reason):
    port, _ = udp_monitor
    frame = _claim(100 + _RULES.index((label, cls, conf, us, verdict, reason)), cls, conf, us)
    got = _exchange(port, frame)
    assert got is not None and len(got) == 64 and got[:8] == frame[:8], label
    assert (got[16 + 6], got[16 + 7]) == (verdict, reason), \
        "%s: verdict %d reason %d, want %d/%d" % (label, got[16 + 6], got[16 + 7], verdict, reason)


def test_monitor_echoes_every_byte_it_does_not_judge(udp_monitor):
    # A legacy claim with payload[24] == 0 -- the byte the VLM arm will use as a
    # claim kind, 0 meaning exactly this path -- and a pattern everywhere the
    # monitor does not write. Only payload[6] and [7] may change. measurement-
    # design section 3.3 will deliberately write [8..23] one day; when it does,
    # this test must change with it, visibly.
    port, _ = udp_monitor
    f = bytearray(_claim(200, 3, 95, 124))
    for i in range(8, 48):
        f[16 + i] = (0xA0 + i) & 0xFF
    f[16 + 24] = 0
    f = bytes(f)
    got = _exchange(port, f)
    assert got is not None and got[16 + 6] == 0 and got[16 + 7] == 0
    want = bytearray(f)
    want[16 + 6] = 0
    want[16 + 7] = 0
    assert got == bytes(want), "only the verdict and reason bytes may differ"


def test_monitor_banners_the_harnesses_grep_are_pinned(native_servers, tmp_path):
    # run-ladder.sh:298 greps ':<port>/udp' in the UDP monitor's log, and :305
    # greps 'serving shm on file <file>,' in the host shm monitor's. A reworded
    # banner fails those runs at preflight, on the board, not here.
    import time as _t
    port = _free_udp_port()
    p = subprocess.Popen([str(native_servers / "monitor"), str(port), "udp"],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _t.sleep(0.3)
    p.terminate()
    out, _ = p.communicate(timeout=10)
    assert (":%d/udp" % port) in out.decode(), out
    f = _shm_file(tmp_path)
    s = _shm_serve(native_servers, f)
    _t.sleep(0.3)
    s.terminate()
    out, err = s.communicate(timeout=10)
    assert ("serving shm on file %s," % f) in out.decode(), (out, err)
    # The shm-kick banner needs an ivshmem server to print; pin the words that
    # run-ladder.sh:311, run-shift-isolation.sh:131 and remote-ladder.sh:120 grep
    # in the source instead.
    src = open(MONITOR_C, encoding="utf-8").read()
    assert "safety monitor serving shm-kick on %s (" in src
    assert "safety monitor serving shm on %s (" in src


# ============================================================ the vlm claim kind (OD13, 2026-09-23)
#
# payload[24] = 1 is a vision-language model's digit claim. The layout, the
# rules and their order are documented in monitor.c's header and check_vlm().
# The defaults below are an honest SmolVLM-500M claim as the 2026-09-23
# characterisation measured one: 269.3 ms of prompt (image encode included),
# 12.5 ms of generation, 281.8 ms in all -- far over the mnist kind's 100 ms,
# well under the vlm kind's 1 s.

def _vlm_claim(seq, cls=3, conf=95, model=1, prompt_us=269300, gen_us=12500, total=None,
               kind=1, prompt_n=162, gen_n=2, wall_us=309900, mass_ppm=999999):
    f = bytearray(_probe_mod().build_frame(seq))
    p = 16
    f[p + 0] = cls
    f[p + 1] = conf
    f[p + 2:p + 6] = (prompt_us + gen_us if total is None else total).to_bytes(4, "little")
    f[p + 24] = kind
    f[p + 25] = model
    f[p + 26:p + 28] = prompt_n.to_bytes(2, "little")
    f[p + 28:p + 30] = gen_n.to_bytes(2, "little")
    f[p + 30:p + 34] = prompt_us.to_bytes(4, "little")
    f[p + 34:p + 38] = gen_us.to_bytes(4, "little")
    f[p + 38:p + 42] = wall_us.to_bytes(4, "little")
    f[p + 42:p + 46] = mass_ppm.to_bytes(4, "little")
    return bytes(f)


_VLM_RULES = [
    # label,                                          claim fields,                                verdict, reason
    ("an honest SmolVLM claim, as measured",          {},                                              0, 0),
    ("at the bound, 1000000 us",                      {"prompt_us": 987500},                           0, 0),
    ("one over the bound",                            {"prompt_us": 987501},                           1, 4),
    ("class 10",                                      {"cls": 10},                                     1, 1),
    ("conf 101",                                      {"conf": 101},                                   1, 2),
    ("conf 60, which is CONF_MIN",                    {"conf": 60},                                    0, 0),
    ("conf 59",                                       {"conf": 59},                                    1, 3),
    ("model 2 has no measured bound",                 {"model": 2},                                    1, 6),
    ("model 0",                                       {"model": 0},                                    1, 6),
    ("a total that is not the sum of its parts",      {"total": 281801},                               1, 7),
    ("a sum that would wrap in 32 bits",              {"prompt_us": 0xFFFFFFFF, "gen_us": 1, "total": 0}, 1, 7),
    # The order: the first failing check names the reason.
    ("class before model",                            {"cls": 10, "model": 2},                         1, 1),
    ("model before the sum",                          {"model": 2, "total": 1},                        1, 6),
    # Over the bound AND inconsistent: the bound alone would say 4.
    ("the sum before the bound",                      {"prompt_us": 1000000, "gen_us": 0, "total": 2000000}, 1, 7),
    ("the bound before conf-low",                     {"prompt_us": 1000001, "gen_us": 0, "conf": 59}, 1, 4),
]


@pytest.mark.parametrize("label,fields,verdict,reason", _VLM_RULES, ids=[r[0] for r in _VLM_RULES])
def test_vlm_claim_rules(udp_monitor, label, fields, verdict, reason):
    port, _ = udp_monitor
    frame = _vlm_claim(300 + [r[0] for r in _VLM_RULES].index(label), **fields)
    got = _exchange(port, frame)
    assert got is not None and len(got) == 64 and got[:8] == frame[:8], label
    assert (got[16 + 6], got[16 + 7]) == (verdict, reason), \
        "%s: verdict %d reason %d, want %d/%d" % (label, got[16 + 6], got[16 + 7], verdict, reason)
    want = bytearray(frame)
    want[16 + 6], want[16 + 7] = verdict, reason
    assert got == bytes(want), "%s: only the verdict and reason bytes may change" % label


def test_an_honest_vlm_time_is_why_the_kind_exists(udp_monitor):
    # The same honest 281.8 ms under the mnist kind is rejected on time alone:
    # the 2026-09-18 contract was written for a 0.1 ms CNN. That is the whole
    # reason a VLM claim needs a kind of its own.
    port, _ = udp_monitor
    mnist = bytearray(_vlm_claim(400))
    mnist[16 + 24] = 0
    got = _exchange(port, bytes(mnist))
    assert (got[16 + 6], got[16 + 7]) == (1, 4), "kind 0 must still apply the 100 ms bound"
    got = _exchange(port, _vlm_claim(401))
    assert (got[16 + 6], got[16 + 7]) == (0, 0), "the same claim as kind 1 is accepted"


@pytest.mark.parametrize("kind", [2, 7, 255])
def test_an_unknown_claim_kind_is_rejected(udp_monitor, kind):
    port, _ = udp_monitor
    got = _exchange(port, _vlm_claim(500 + kind, kind=kind))
    assert (got[16 + 6], got[16 + 7]) == (1, 5), "kind %d: reason 5, claim-kind-unknown" % kind


def test_vlm_claims_cross_the_shm_transport_unchanged(native_servers, tmp_path):
    # The kind is dispatched inside judge_frame(), so every transport carries it
    # with no change of its own. Check that on the slot, whose copy is a memcpy
    # of exactly FRAME_TOTAL_BYTES: an honest claim ACCEPTs, a claim from a
    # model with no measured bound REJECTs with reason 6, and the kind-specific
    # bytes come back as they went.
    lp = _probe_mod()
    f = _shm_file(tmp_path)
    p = _shm_serve(native_servers, f)
    try:
        chan = lp.ShmChannel(str(native_servers / "libshmchan.so"), str(f))
        assert chan.ready()
        good, bad = _vlm_claim(1), _vlm_claim(2, model=2)
        assert chan.roundtrip(good, 2.0) == lp.ShmChannel.OK
        got = chan.rsp.raw
        assert got[16 + 6] == 0 and got[16 + 7] == 0 and got[16 + 8:] == good[16 + 8:]
        assert chan.roundtrip(bad, 2.0) == lp.ShmChannel.OK
        got = chan.rsp.raw
        assert got[16 + 6] == 1 and got[16 + 7] == 6 and got[16 + 8:] == bad[16 + 8:]
        # And a kind-0 reject, whose console line must still read exactly as
        # the 2026-09-18 record's does.
        legacy = bytearray(lp.build_frame(3))
        legacy[16] = 42
        assert chan.roundtrip(bytes(legacy), 2.0) == lp.ShmChannel.OK
    finally:
        p.terminate()
        out, err = p.communicate(timeout=10)
    out = out.decode()
    assert "shm done: seen=3 accepted=1 rejected=2 jumps=0" in out, (out, err)
    assert "monitor: REJECT seq=2 kind=vlm model=2 class=3 conf=95 us=281800 reason=vlm-model-unbounded\n" in out, out
    assert "monitor: REJECT seq=3 class=42 conf=95 us=124 reason=class-out-of-range\n" in out, out


def test_the_monitor_announces_its_claim_kinds(native_servers):
    # A serving monitor names its kinds and bounds on a line of its own, so a
    # guest console shows which rules judged a run, and an image can be
    # checked for this build by the string alone.
    import time as _t
    port = _free_udp_port()
    p = subprocess.Popen([str(native_servers / "monitor"), str(port), "udp"],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _t.sleep(0.3)
    p.terminate()
    out, _ = p.communicate(timeout=10)
    line = [x for x in out.decode().splitlines() if "claim kinds:" in x]
    assert line == ["monitor: claim kinds: 0 mnist (us <= 100000), 1 vlm model 1 (us <= 1000000), conf_min=60%"], out


# ============================================================ the shm transport (OD12, 2026-09-22)
#
# shm_chan.h's slot: magic @0, version @4, req_seq @64, request @128, rsp_seq @192,
# reply @256. The tests that run the real monitor and the real libshmchan.so need
# gcc on Linux (CI's tooling job); the rest run anywhere bash does.

SHM_MAGIC = 0x314D4853
_PY = __import__("sys").executable


def _shm_file(tmp_path, name="slot"):
    f = tmp_path / name
    f.write_bytes(b"\0" * (1 << 20))
    return f


def _shm_serve(native_servers, f):
    """The native monitor in shm mode on file f; returns the process once its
    banner is out."""
    import time as _t
    p = subprocess.Popen([str(native_servers / "monitor"), "shm", str(f)],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    for _ in range(100):
        if f.read_bytes()[:4] == SHM_MAGIC.to_bytes(4, "little"):
            return p
        _t.sleep(0.02)
    p.kill()
    raise AssertionError("the monitor never published its magic: %r" % (p.communicate(timeout=5),))


def test_native_monitor_shm_mode_judges_through_the_slot(native_servers, tmp_path):
    lp = _probe_mod()
    f = _shm_file(tmp_path)
    # A request left in the slot BEFORE the server starts must not be answered:
    # its client is gone, and answering would give a later client a reply to a
    # frame it never sent. (It is an acceptable claim, so answering it would show
    # up as seen=3 below.)
    raw = bytearray(f.read_bytes())
    raw[64:72] = (5).to_bytes(8, "little")
    raw[128:192] = lp.build_frame(99)
    f.write_bytes(bytes(raw))
    p = _shm_serve(native_servers, f)
    try:
        chan = lp.ShmChannel(str(native_servers / "libshmchan.so"), str(f))
        assert chan.ready() and chan.what.startswith("file ")
        frame = lp.build_frame(7)
        bad = bytearray(lp.build_frame(8))
        bad[16] = 42                                  # class out of range: must be REJECTED
        bad = bytes(bad)
        assert chan.roundtrip(frame, 2.0) == lp.ShmChannel.OK
        got = chan.rsp.raw
        assert got[:8] == frame[:8] and got[16 + 6] == 0 and got[16 + 7] == 0
        assert chan.roundtrip(bad, 2.0) == lp.ShmChannel.OK
        rej = chan.rsp.raw
        assert rej[:8] == bad[:8] and rej[16 + 6] == 1 and rej[16 + 7] == 1, "class 42: reject, reason 1"
        sentinel = b"\xff" * 8 + bad[8:]
        assert chan.roundtrip(sentinel, 2.0) == lp.ShmChannel.OK
        assert chan.rsp.raw == sentinel, "the sentinel comes back untouched"
        slot = f.read_bytes()
        assert int.from_bytes(slot[64:72], "little") == 8, "three requests after the stale 5"
        assert int.from_bytes(slot[192:200], "little") == 8
    finally:
        p.terminate()
        out, err = p.communicate(timeout=10)
    assert "shm done: seen=2 accepted=1 rejected=1 jumps=0" in out.decode(), (out, err)
    assert f.read_bytes()[:4] == b"\0\0\0\0", "a stopped server must withdraw its magic"


def test_shm_probe_times_a_clean_arm(native_servers, tmp_path):
    f = _shm_file(tmp_path)
    p = _shm_serve(native_servers, f)
    out = tmp_path / "lat.json"
    try:
        r = subprocess.run([_PY, PROBE, "--proto", "shm",
                            "--shm", str(f), "--shm-lib", str(native_servers / "libshmchan.so"),
                            "--n", "50", "--warmup", "5", "--interval-ms", "0", "--tag", "s_r1",
                            "--out", str(out)], capture_output=True, text=True, timeout=60)
    finally:
        p.terminate()
        p.communicate(timeout=10)
    assert r.returncode == 0, r.stdout + r.stderr
    summ = json.loads(out.read_text())["summary"]
    assert summ["proto"] == "shm" and summ["n"] == 50 and summ["bad"] == 0
    assert summ["shm_region"].startswith("file %s" % f)


def test_shm_probe_with_no_server_is_a_refused_connect(native_servers, tmp_path):
    f = _shm_file(tmp_path)
    r = subprocess.run([_PY, PROBE, "--proto", "shm",
                        "--shm", str(f), "--shm-lib", str(native_servers / "libshmchan.so"),
                        "--n", "5", "--warmup", "0", "--tag", "s_r1"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 2 and "no server is serving" in r.stdout, r.stdout + r.stderr


def test_shm_probe_records_a_silent_server_as_a_stall(native_servers, tmp_path):
    """A slot whose magic says 'serving' but which never answers: the probe must
    time out, write a stall record that says shm, and write no result."""
    f = _shm_file(tmp_path)
    raw = bytearray(f.read_bytes())
    raw[0:4] = SHM_MAGIC.to_bytes(4, "little")
    raw[4:8] = (1).to_bytes(4, "little")
    f.write_bytes(bytes(raw))
    out, st = tmp_path / "lat.json", tmp_path / "stall.json"
    r = subprocess.run([_PY, PROBE, "--proto", "shm",
                        "--shm", str(f), "--shm-lib", str(native_servers / "libshmchan.so"),
                        "--n", "5", "--warmup", "0", "--timeout-s", "0.2", "--tag", "s_r1",
                        "--out", str(out), "--stall-out", str(st)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 3, r.stdout + r.stderr
    rec = json.loads(st.read_text())["stall"]
    assert rec["proto"] == "shm" and rec["kind"] == "timeout" and rec["at_sample"] == 0
    assert not out.exists()


@pytest.mark.parametrize("args,why", [
    (["--proto", "shm", "--shm-lib", "x.so"], "--proto shm needs --shm and --shm-lib"),
    (["--proto", "shm", "--shm", "/dev/shm/x"], "--proto shm needs --shm and --shm-lib"),
    (["--proto", "tcp"], "--host is required for --proto tcp"),
    (["--proto", "udp", "--port", "1"], "--host is required for --proto udp"),
])
def test_probe_refuses_a_destination_its_transport_cannot_use(args, why):
    import sys
    r = subprocess.run([sys.executable, PROBE] + args, capture_output=True, text=True, timeout=60)
    assert r.returncode == 2 and why in r.stderr, r.stderr


def test_m_probe_hands_an_shm_arm_its_file_and_library(tmp_path):
    fake = tmp_path / "argv.py"
    fake.write_bytes(b"import sys, json\na = sys.argv\n"
                     b"open(a[a.index('--out') + 1], 'w').write(json.dumps({'argv': a[1:]}))\n")
    out = tmp_path / "out"
    out.mkdir()
    r = _run(tmp_path, 'N=10; WARMUP=1; INTERVAL_MS=0; CORE_PROBE=0; SAMPLE_WINDOW=0; PROBE="%s"; '
             'SHMCHAN_LIB=x.so; taskset() { shift 2; "$@"; }; '
             'm_probe "%s" s_r1 shm-slot - "" shm' % (_posix(fake), _posix(out)))
    assert r.returncode == 0, r.stderr
    a = json.loads((out / "lat-s_r1.json").read_text())["argv"]
    assert a[a.index("--proto") + 1] == "shm"
    # Names without a slash: Git Bash rewrites /-paths it hands to a Windows python.
    assert a[a.index("--shm") + 1] == "shm-slot" and a[a.index("--shm-lib") + 1] == "x.so"
    assert "--host" not in a and "--port" not in a


def test_m_probe_refuses_an_shm_arm_without_the_library(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    r = _run(tmp_path, 'N=10; WARMUP=1; INTERVAL_MS=0; CORE_PROBE=0; SAMPLE_WINDOW=0; PROBE=/x; '
             'unset SHMCHAN_LIB; m_probe "%s" s_r1 /dev/shm/slot - "" shm; echo SHOULD NOT REACH' % _posix(out))
    assert r.returncode != 0 and "SHMCHAN_LIB unset" in r.stderr, r.stderr


@pytest.mark.parametrize("rc,why", [(0, None), (4, "no framed reply in 5 s"), (2, "could not run (probe exit 2)")])
def test_shm_reachability(tmp_path, rc, why):
    fake = tmp_path / "p.py"
    fake.write_bytes(b"import sys\nsys.exit(%d)\n" % rc)
    r = _run(tmp_path, 'PROBE="%s"; SHMCHAN_LIB=/lib/x.so; m_reachable_shm /dev/shm/slot D-shm; echo REACHED'
             % _posix(fake))
    if why is None:
        assert "REACHED" in r.stdout and "reachable: D-shm (/dev/shm/slot, shm)" in r.stderr + r.stdout
    else:
        assert r.returncode != 0 and why in r.stderr, r.stderr


def _shm_gate(tmp_path, d, arms, shm_arms, udp_arms=""):
    return _run(tmp_path, 'K=2; N=1000; WARMUP=200; CORE_PROBE=4; FIFO_ARMS=""; UDP_ARMS="%s"; SHM_ARMS="%s"; '
                'm_require_complete "%s" %s; echo PASSED' % (udp_arms, shm_arms, _posix(d), " ".join(arms)))


def test_gate_accepts_shm_arms_that_say_shm(tmp_path):
    arms = ["A-loopback", "A-udp", "A-shm"]
    d = _proto_dir(tmp_path, arms, lambda a: a.split("-")[1] if a != "A-loopback" else "tcp")
    r = _shm_gate(tmp_path, d, arms, "A-shm", "A-udp")
    assert "PASSED" in r.stdout, r.stderr


@pytest.mark.parametrize("proto_of,why", [
    (lambda a: "tcp", "A-shm_r1: proto='tcp', expected 'shm'"),
    (lambda a: "shm", "A-loopback_r1: proto='shm', expected 'tcp'"),
])
def test_gate_refuses_an_shm_arm_run_over_another_transport(tmp_path, proto_of, why):
    arms = ["A-loopback", "A-shm"]
    d = _proto_dir(tmp_path, arms, proto_of)
    r = _shm_gate(tmp_path, d, arms, "A-shm")
    assert "PASSED" not in r.stdout and why in r.stderr, r.stderr


def _williams_rows(tmp_path, n, rounds):
    snippet = "; ".join("m_williams_row %d %d" % (r, n) for r in range(1, rounds + 1))
    return [[int(x) for x in line.split()] for line in _run(tmp_path, snippet).stdout.strip().splitlines()]


def test_two_transports_keep_tcp_first_in_odd_rounds(tmp_path):
    """The UDP ladder of 2026-09-22 ran TCP first in odd rounds; ordering the
    transport groups by m_williams_row must not have changed that."""
    assert _williams_rows(tmp_path, 2, 4) == [[0, 1], [1, 0], [0, 1], [1, 0]]


def test_three_transports_balance_position_and_carryover_over_six_rounds(tmp_path):
    rows = _williams_rows(tmp_path, 3, 6)
    assert all(sorted(r) == [0, 1, 2] for r in rows)
    for pos in range(3):
        assert sorted(r[pos] for r in rows) == [0, 0, 1, 1, 2, 2], "position unbalanced: %r" % rows
    adj = {}
    for r in rows:
        for p_, q in zip(r, r[1:]):
            adj[(p_, q)] = adj.get((p_, q), 0) + 1
    assert len(adj) == 6 and len(set(adj.values())) == 1, "carryover unbalanced: %r" % adj


def test_native_build_keeps_qnx_only_calls_out_of_the_shared_source(tmp_path):
    """build-monitor-native.sh refuses a shared source that grew a QNX-only call.
    FOUND BY DESIGN, 2026-09-22: the guest's ivshmem mapping is QNX-only
    (mmap_device_memory), so it lives in shm_map_qnx.c; if it ever moved into
    monitor.c or shm_chan.h the host and guest would stop being one program."""
    src = os.path.join(HERE, "..", "orin-native", "gpu-concurrency", "build-monitor-native.sh")
    body = open(src, encoding="utf-8").read()
    for word in ("mmap_device_memory", "pci_device_", "shm_chan.h", "shm_map_posix.c", "ivshm_client.c"):
        assert word in body, "build-monitor-native.sh no longer mentions %s" % word
    for f in ("monitor.c",):
        text = open(os.path.join(HERE, "..", "ipc-test", "qnx-safety-monitor", f), encoding="utf-8").read()
        code = [ln for ln in text.splitlines() if not ln.lstrip().startswith(("*", "/*", "//"))]
        assert not any("mmap_device_memory" in ln for ln in code)


# ============================================================ the notified shm variant (OD12, 2026-09-22)
#
# The ivshmem server's protocol (QEMU 6.2's), the host monitor's shmkick mode, and
# the probe's shmkick/shmdb/kickecho transports, end to end on a host. The server
# tests need Linux (eventfd, SCM_RIGHTS); the end-to-end ones also need gcc.

import socket as _socket  # noqa: E402

LINUX_IPC = hasattr(os, "eventfd") and hasattr(_socket, "recv_fds") and hasattr(os, "sched_getaffinity")
needs_linux_ipc = pytest.mark.skipif(not LINUX_IPC, reason="needs Linux eventfd/SCM_RIGHTS: runs in CI's tooling job")


def _short_dir():
    import tempfile
    return tempfile.mkdtemp(prefix="a6k", dir="/tmp")   # UNIX socket paths are limited to 107 bytes


def _start_ivshmem_server(d, name="srv", extra=()):
    import time as _t
    shm = os.path.join(d, name + ".shm")
    with open(shm, "wb") as f:
        f.write(b"\0" * (1 << 20))
    sock = os.path.join(d, name + ".sock")
    ready = sock + ".ready"
    p = subprocess.Popen([_PY, IVSHMEM_SERVER_PY, "--socket", sock, "--shm", shm, "--ready", ready] + list(extra),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    for _ in range(100):
        if os.path.exists(ready) and os.path.getsize(ready) > 0:
            return p, sock, shm
        _t.sleep(0.05)
    p.kill()
    raise AssertionError("server never became ready: %r" % (p.communicate(timeout=5),))


def _msg(sock, timeout=2.0):
    """One server message: exactly 8 bytes (the fd rides on them), as QEMU reads."""
    import struct as _st
    sock.settimeout(timeout)
    data, fds, _flags, _addr = _socket.recv_fds(sock, 8, 1)
    assert len(data) == 8, data
    return _st.unpack("<q", data)[0], (fds[0] if fds else None)


def _peer(path):
    c = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
    c.connect(path)
    v, fd = _msg(c)
    assert v == 0 and fd is None, "protocol version 0, no fd"
    pid, fd = _msg(c)
    assert fd is None
    v, shm_fd = _msg(c)
    assert v == -1 and shm_fd is not None, "-1 with the shared memory's fd"
    os.close(shm_fd)
    return c, pid


@needs_linux_ipc
def test_ivshmem_server_speaks_qemus_protocol_and_never_reuses_an_id():
    """FOUND BY DESIGN REVIEW: QEMU 6.2 writes into freed memory when a peer id
    is reused, so ids must only go up; and a newcomer must be announced to the
    existing peers BEFORE it gets its own eventfd."""
    import fcntl
    import select as _sel
    d = _short_dir()
    srv, path, _shm = _start_ivshmem_server(d)
    try:
        c1, id1 = _peer(path)
        own1, efd1 = _msg(c1)
        assert id1 == 1 and own1 == 1 and efd1 is not None, "QEMU, the first peer, is 1 -- never 0"
        assert fcntl.fcntl(efd1, fcntl.F_GETFL) & os.O_NONBLOCK, "eventfds are created non-blocking"
        c2, id2 = _peer(path)
        other, ofd = _msg(c2)
        assert (other, ofd is not None) == (1, True), "the newcomer learns peer 1's eventfd"
        own2, efd2 = _msg(c2)
        assert (id2, own2) == (2, 2) and efd2 is not None
        # by now peer 1 must already hold the newcomer's notice
        assert _sel.select([c1], [], [], 0)[0], "peer 1 was not told about peer 2 before peer 2 got its eventfd"
        new, nfd = _msg(c1)
        assert new == 2 and nfd is not None
        c2.close()
        gone, gfd = _msg(c1)
        assert (gone, gfd) == (2, None), "a departure is the id with no fd"
        c3, id3 = _peer(path)
        assert id3 == 3, "a freed id is never handed out again (got %r)" % id3
        for fd in (efd1, efd2, ofd, nfd):
            os.close(fd)
        c1.close()
        c3.close()
    finally:
        srv.terminate()
        srv.communicate(timeout=10)


@needs_linux_ipc
def test_ivshmem_server_exits_with_its_owner_peer():
    d = _short_dir()
    srv, path, _shm = _start_ivshmem_server(d, extra=("--exit-with-peer", "1"))
    c1, _ = _peer(path)
    _msg(c1)
    c1.close()
    assert srv.wait(timeout=10) == 0
    assert not os.path.exists(path), "the server removes its socket on the way out"


@needs_linux_ipc
@pytest.mark.parametrize("size,why", [(5000, "power of two"), (2048, "power of two")])
def test_ivshmem_server_refuses_memory_qemu_cannot_map(size, why):
    d = _short_dir()
    shm = os.path.join(d, "bad.shm")
    with open(shm, "wb") as f:
        f.write(b"\0" * size)
    r = subprocess.run([_PY, IVSHMEM_SERVER_PY, "--socket", os.path.join(d, "s.sock"), "--shm", shm],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 2 and why in r.stdout, r.stdout


@needs_linux_ipc
def test_ivshmem_server_never_takes_over_an_existing_socket():
    d = _short_dir()
    shm = os.path.join(d, "x.shm")
    with open(shm, "wb") as f:
        f.write(b"\0" * 4096)
    path = os.path.join(d, "taken.sock")
    open(path, "w").close()
    r = subprocess.run([_PY, IVSHMEM_SERVER_PY, "--socket", path, "--shm", shm],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 2 and "exists" in r.stdout, r.stdout


def _notified_rig(native_servers):
    """A host ivshmem server and the native monitor in shmkick mode on it."""
    import time as _t
    d = _short_dir()
    srv, path, shm = _start_ivshmem_server(d)
    kick = os.path.join(d, "kick.sock")
    mon = subprocess.Popen([str(native_servers / "monitor"), "shmkick", path + "@4096", kick],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    for _ in range(100):
        if os.path.exists(kick):
            break
        _t.sleep(0.05)
    assert os.path.exists(kick), mon.communicate(timeout=5)
    return d, srv, path, shm, kick, mon


def _stop(*procs):
    """SIGTERM each process and collect its output. One that outlives its
    SIGTERM by 5 s is killed -- and the test FAILS, because the harness relies on
    these processes stopping when told."""
    outs, hung = [], []
    for p in procs:
        p.terminate()
        try:
            outs.append(p.communicate(timeout=5))
        except subprocess.TimeoutExpired:
            p.kill()
            outs.append(p.communicate(timeout=5))
            hung.append(p.args)
    assert not hung, "outlived SIGTERM: %r; output %r" % (hung, outs)
    return outs


def _notified_probe(native_servers, proto, shm, kick, ivshm, tmp_path, *extra):
    out = tmp_path / ("lat-%s.json" % proto)
    args = [_PY, PROBE, "--proto", proto, "--kick", kick, "--shm-lib", str(native_servers / "libshmchan.so"),
            "--n", "50", "--warmup", "5", "--interval-ms", "0", "--tag", proto + "_r1", "--out", str(out)]
    if proto != "kickecho":
        args += ["--shm", shm + "@4096"]
    if proto == "shmdb":
        args += ["--ivshm", ivshm]
    return subprocess.run(args + list(extra), capture_output=True, text=True, timeout=120), out


@pytest.mark.parametrize("proto", ["shmkick", "shmdb", "kickecho"])
def test_notified_arm_ends_every_exchange_on_exactly_one_notification(native_servers, tmp_path, proto):
    if not LINUX_IPC:
        pytest.skip("needs Linux")
    d, srv, path, shm, kick, mon = _notified_rig(native_servers)
    try:
        r, out = _notified_probe(native_servers, proto, shm, kick, path, tmp_path)
    finally:
        (mout, merr), _ = _stop(mon, srv)
    assert r.returncode == 0, r.stdout + r.stderr
    summ = json.loads(out.read_text())["summary"]
    nt = summ["notify"]
    assert summ["proto"] == proto and summ["n"] == 50
    assert nt["exchanges"] == 55 and nt["notifications"] == 55 and nt["wakeups"] == 55, nt
    assert nt["early_wakeups"] == 0 and nt["stray"] == 0 and nt["eagain"] == 0, nt
    if proto == "shmdb":
        assert summ["ivshm_peer"] >= 2 and summ["handshake_attempts"] >= 1
        assert summ["wait_fd_nonblock"] == [True, True], "the server's eventfds are non-blocking"
    done = mout.decode()
    # Not " stale=0 ": with --interval-ms 0 the monitor's re-check can take
    # request n+1 before reading its kick byte, which it then counts as stale
    # (CI on main, a9df382). A stale kick answered by a notification would show
    # above, as an early wake-up or a stray, and that is the deterministic check.
    assert "shm-kick done:" in done and " jumps=0 " in done and " stray=0 " in done and " ring_misses=0 " in done, done


def test_db_burst_delivers_every_doorbell(native_servers, tmp_path):
    if not LINUX_IPC:
        pytest.skip("needs Linux")
    d, srv, path, shm, kick, mon = _notified_rig(native_servers)
    try:
        r = subprocess.run([_PY, PROBE, "--proto", "shmdb", "--kick", kick, "--shm", shm + "@4096", "--ivshm", path,
                            "--shm-lib", str(native_servers / "libshmchan.so"), "--db-burst", "1000",
                            "--tag", "burst"], capture_output=True, text=True, timeout=120)
    finally:
        _stop(mon, srv)
    assert r.returncode == 0 and '"got": 1000' in r.stdout, r.stdout + r.stderr


def _fake_notified_server(shm, kick, behaviour, before=None, answer=True, close_on_accept=False):
    """A kick server in Python that answers in the slot and then does
    `behaviour(conn)` -- to make faults the real monitor never makes. `before`
    runs before the answer; answer=False never answers; close_on_accept hangs up
    at once."""
    import mmap
    import struct as _st
    import threading
    fd = os.open(shm, os.O_RDWR)
    mm = mmap.mmap(fd, 1 << 20)
    base = 4096
    mm[base:base + 8] = _st.pack("<II", 0x314B4853, 1)          # "SHK1", version 1
    ls = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
    ls.bind(kick)
    ls.listen(1)

    def serve():
        conn, _ = ls.accept()
        if close_on_accept:
            conn.close()
            return
        while True:
            b = conn.recv(64)
            if not b:
                return
            if before is not None:
                before(conn)
            if not answer:
                continue
            seq = _st.unpack("<Q", mm[base + 64:base + 72])[0]
            mm[base + 256:base + 320] = mm[base + 128:base + 192]
            mm[base + 192:base + 200] = _st.pack("<Q", seq)
            behaviour(conn)
    threading.Thread(target=serve, daemon=True).start()
    return ls


def test_a_reply_without_its_notification_is_lost_not_a_stall(native_servers, tmp_path):
    """FOUND BY DESIGN REVIEW: a doorbell QEMU drops, or a kick eaten on the way,
    leaves the reply in the slot with the probe asleep. That is a protocol fault
    (exit 5, "notification lost"), never a stall record."""
    if not LINUX_IPC:
        pytest.skip("needs Linux")
    d = _short_dir()
    shm = os.path.join(d, "slot.shm")
    with open(shm, "wb") as f:
        f.write(b"\0" * (1 << 20))
    kick = os.path.join(d, "kick.sock")
    _fake_notified_server(shm, kick, lambda conn: None)       # answers, never notifies
    st = tmp_path / "stall.json"
    r, out = _notified_probe(native_servers, "shmkick", shm, kick, "", tmp_path,
                             "--timeout-s", "0.3", "--stall-out", str(st))
    assert r.returncode == 5 and "notification lost" in r.stdout, r.stdout + r.stderr
    assert not st.exists() and not out.exists()


def test_stray_bytes_on_the_kick_stream_are_counted(native_servers, tmp_path):
    if not LINUX_IPC:
        pytest.skip("needs Linux")
    d = _short_dir()
    shm = os.path.join(d, "slot.shm")
    with open(shm, "wb") as f:
        f.write(b"\0" * (1 << 20))
    kick = os.path.join(d, "kick.sock")
    _fake_notified_server(shm, kick, lambda conn: conn.sendall(b"Kx"))
    r, out = _notified_probe(native_servers, "shmkick", shm, kick, "", tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    nt = json.loads(out.read_text())["summary"]["notify"]
    assert nt["stray"] >= 1 and nt["notifications"] == nt["exchanges"], nt


def test_a_polling_client_and_a_notified_server_never_pair(native_servers, tmp_path):
    """FOUND BY CODE REVIEW: the first version wrote the notified magic where the
    polling client never looks, so it passed whatever the magic check did. Now
    each client meets the OTHER kind's magic at its own offset."""
    import struct as _st
    if not LINUX_IPC:
        pytest.skip("needs Linux")
    d = _short_dir()
    shm = os.path.join(d, "slot.shm")
    with open(shm, "wb") as f:
        f.write(b"\0" * (1 << 20))
    with open(shm, "r+b") as f:
        f.seek(0)
        f.write(_st.pack("<II", 0x314B4853, 1))       # "SHK1" where a polling client looks
        f.seek(4096)
        f.write(_st.pack("<II", 0x314D4853, 1))       # "SHM1" where a notified client looks
    kick = os.path.join(d, "kick.sock")
    ls = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
    ls.bind(kick)
    ls.listen(1)
    lib = str(native_servers / "libshmchan.so")
    r = subprocess.run([_PY, PROBE, "--proto", "shm", "--shm", shm, "--shm-lib", lib,
                        "--n", "5", "--warmup", "0", "--tag", "p"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 2 and "no server is serving" in r.stdout, r.stdout
    r = subprocess.run([_PY, PROBE, "--proto", "shmkick", "--shm", shm + "@4096", "--kick", kick, "--shm-lib", lib,
                        "--n", "5", "--warmup", "0", "--tag", "k"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 2 and "no notified server is serving" in r.stdout, r.stdout
    ls.close()


@pytest.mark.parametrize("args,why", [
    (["--proto", "shmkick", "--shm-lib", "x.so", "--shm", "f@4096"], "needs --kick"),
    (["--proto", "shmdb", "--shm-lib", "x.so", "--shm", "f@4096", "--kick", "k"], "--proto shmdb needs --ivshm"),
    (["--proto", "kickecho", "--kick", "k"], "needs --kick, --shm-lib"),
    (["--proto", "shmkick", "--kick", "k", "--shm-lib", "x.so", "--shm", "f", "--db-burst", "5"],
     "--db-burst needs --proto shmdb"),
])
def test_probe_refuses_a_notified_arm_it_cannot_run(args, why):
    import sys
    r = subprocess.run([sys.executable, PROBE] + args, capture_output=True, text=True, timeout=60)
    assert r.returncode == 2 and why in r.stderr, r.stderr


def test_m_probe_hands_notified_arms_their_channels(tmp_path):
    fake = tmp_path / "argv.py"
    fake.write_bytes(b"import sys, json\na = sys.argv\n"
                     b"open(a[a.index('--out') + 1], 'w').write(json.dumps({'argv': a[1:]}))\n")
    out = tmp_path / "out"
    out.mkdir()
    r = _run(tmp_path, 'N=10; WARMUP=1; INTERVAL_MS=0; CORE_PROBE=0; SAMPLE_WINDOW=0; PROBE="%s"; '
             'SHMCHAN_LIB=x.so; taskset() { shift 2; "$@"; }; '
             'm_probe "%s" k_r1 slot@4096 kicksock "" shmkick; '
             'm_probe "%s" d_r1 slot@4096 kicksock "" shmdb ivsock; '
             'm_probe "%s" e_r1 - kicksock "" kickecho' % (_posix(fake), _posix(out), _posix(out), _posix(out)))
    assert r.returncode == 0, r.stderr
    k = json.loads((out / "lat-k_r1.json").read_text())["argv"]
    db = json.loads((out / "lat-d_r1.json").read_text())["argv"]
    e = json.loads((out / "lat-e_r1.json").read_text())["argv"]
    assert k[k.index("--shm") + 1] == "slot@4096" and k[k.index("--kick") + 1] == "kicksock" and "--ivshm" not in k
    assert db[db.index("--ivshm") + 1] == "ivsock" and db[db.index("--proto") + 1] == "shmdb"
    assert "--shm" not in e and e[e.index("--kick") + 1] == "kicksock"
    for a in (k, db, e):
        assert "--host" not in a and "--port" not in a


def test_m_probe_refuses_shmdb_without_its_server(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    r = _run(tmp_path, 'N=10; WARMUP=1; INTERVAL_MS=0; CORE_PROBE=0; SAMPLE_WINDOW=0; PROBE=/x; SHMCHAN_LIB=x.so; '
             'm_probe "%s" d_r1 slot@4096 kicksock "" shmdb; echo SHOULD NOT REACH' % _posix(out))
    assert r.returncode != 0 and "shmdb needs the ivshmem server" in r.stderr, r.stderr


@pytest.mark.parametrize("rc,why", [(0, None), (4, "no notified reply in 5 s"), (2, "could not run (probe exit 2)")])
def test_notified_reachability(tmp_path, rc, why):
    fake = tmp_path / "p.py"
    fake.write_bytes(b"import sys\nsys.exit(%d)\n" % rc)
    r = _run(tmp_path, 'PROBE="%s"; SHMCHAN_LIB=x.so; m_reachable_notified D-db shmdb slot@4096 kicksock ivsock; '
             'echo REACHED' % _posix(fake))
    if why is None:
        assert "REACHED" in r.stdout and "reachable: D-db (shmdb via kicksock)" in r.stderr + r.stdout
    else:
        assert r.returncode != 0 and why in r.stderr, r.stderr


def _notify_dir(tmp_path, arms, notify_of):
    def m(a, r, s):
        s["proto"] = {"A-kick": "shmkick", "D-db": "shmdb", "C-kick": "kickecho"}.get(a, "tcp")
        nt = notify_of(a)
        if nt is not None:
            s["notify"] = nt
    return _sched_dir(tmp_path, arms, m)


def _clean_notify(ex=1200):
    return {"exchanges": ex, "wakeups": ex, "early_wakeups": 0, "notifications": ex, "stray": 0, "eagain": 0}


def _notify_gate(tmp_path, d, arms, kvm=0):
    return _run(tmp_path, 'K=2; N=1000; WARMUP=200; CORE_PROBE=4; FIFO_ARMS=""; KICK_ARMS="A-kick"; DB_ARMS="D-db"; '
                'ECHO_ARMS="C-kick"; KVM_STATS=%d; m_require_complete "%s" %s; echo PASSED'
                % (kvm, _posix(d), " ".join(arms)))


def test_gate_accepts_notified_arms_with_one_notification_per_exchange(tmp_path):
    arms = ["A-loopback", "A-kick", "C-kick", "D-db"]
    d = _notify_dir(tmp_path, arms, lambda a: _clean_notify() if a != "A-loopback" else None)
    r = _notify_gate(tmp_path, d, arms)
    assert "PASSED" in r.stdout, r.stderr


@pytest.mark.parametrize("bad,why", [
    ({"stray": 1}, "notify.stray=1, expected 0"),
    ({"early_wakeups": 2}, "notify.early_wakeups=2, expected 0"),
    ({"eagain": 1}, "notify.eagain=1, expected 0"),
    ({"notifications": 1199}, "notify.notifications=1199, expected one per exchange"),
    ({"wakeups": 1201}, "notify.wakeups=1201, expected one per exchange"),
    ({"exchanges": 1000}, "notify.exchanges=1000, expected 1200"),
])
def test_gate_refuses_a_notified_arm_that_was_not_one_notification_per_exchange(tmp_path, bad, why):
    arms = ["A-kick"]

    def nt(a):
        x = _clean_notify()
        x.update(bad)
        if "exchanges" in bad and "notifications" not in bad:
            x["notifications"] = x["wakeups"] = bad["exchanges"]
        return x
    d = _notify_dir(tmp_path, arms, nt)
    r = _notify_gate(tmp_path, d, arms)
    assert "PASSED" not in r.stdout and why in r.stderr, r.stderr


def test_gate_refuses_a_notified_arm_with_no_accounting(tmp_path):
    arms = ["D-db"]
    d = _notify_dir(tmp_path, arms, lambda a: None)
    r = _notify_gate(tmp_path, d, arms)
    assert "PASSED" not in r.stdout and "D-db_r1: notify.exchanges=None" in r.stderr, r.stderr


def test_gate_wants_a_kvm_snapshot_per_arm_when_asked(tmp_path):
    arms = ["A-loopback"]
    d = _notify_dir(tmp_path, arms, lambda a: None)
    r = _notify_gate(tmp_path, d, arms, kvm=1)
    assert "PASSED" not in r.stdout and "A-loopback_r1: no readable KVM snapshot" in r.stderr, r.stderr
    for rr in (1, 2):
        (d / ("kvm-A-loopback_r%d.json" % rr)).write_text(json.dumps({"before": {}, "after": {}}))
    r = _notify_gate(tmp_path, d, arms, kvm=1)
    assert "PASSED" in r.stdout, r.stderr


def _fake_kvm(tmp_path, dirs=("4242-12",), counters=None):
    kvm = tmp_path / "kvm"
    for dname in dirs:
        (kvm / dname).mkdir(parents=True)
        for k, v in (counters or {"exits": 100, "mmio_exit_kernel": 10, "mmio_exit_user": 3}).items():
            (kvm / dname / k).write_text("%d\n" % v)
    task = tmp_path / "proc" / "4242" / "task" / "4243"
    task.mkdir(parents=True)
    (task / "schedstat").write_text("1000 20 3\n")
    (task / "comm").write_text("CPU 0/KVM\n")
    return kvm


def _kvm_snap(tmp_path, kvm, snippet):
    return _run(tmp_path, 'KVM_QEMU_PID=4242; KVM_DEBUGFS="%s"; PROC_ROOT="%s"; CORE_AUX=0; '
                'sleep() { :; }; taskset() { shift 2; "$@"; }; %s'
                % (_posix(kvm), _posix(tmp_path / "proc"), snippet),
                sudo='[ "$1" = -n ] && shift; exec "$@"')


def test_kvm_snapshot_records_counters_and_qemu_threads(tmp_path):
    kvm = _fake_kvm(tmp_path)
    j = tmp_path / "kvm.json"
    r = _kvm_snap(tmp_path, kvm, 'm_kvm_snap "%s" before && echo 250 > "%s/4242-12/mmio_exit_kernel" && '
                  'm_kvm_snap "%s" after && echo DONE' % (_posix(j), _posix(kvm), _posix(j)))
    assert "DONE" in r.stdout, r.stderr
    doc = json.loads(j.read_text())
    assert doc["before"]["counters"]["mmio_exit_kernel"] == 10 and doc["after"]["counters"]["mmio_exit_kernel"] == 250
    assert doc["before"]["counters"]["halt_wait_ns"] is None, "an absent counter is null, not a guess"
    assert doc["after"]["threads"]["4243"] == {"comm": "CPU 0/KVM", "run_ns": 1000, "wait_ns": 20, "slices": 3}
    assert doc["after"]["t_ns"] >= doc["before"]["t_ns"]


@pytest.mark.parametrize("dirs,why", [((), "expected one"), (("4242-12", "4242-13"), "expected one")])
def test_kvm_snapshot_refuses_an_ambiguous_vm(tmp_path, dirs, why):
    kvm = _fake_kvm(tmp_path, dirs=dirs) if dirs else (tmp_path / "kvm")
    kvm.mkdir(exist_ok=True)
    if not dirs:
        task = tmp_path / "proc" / "4242" / "task"
        task.mkdir(parents=True)
    r = _kvm_snap(tmp_path, kvm, 'm_kvm_snap "%s" before; echo SHOULD NOT REACH' % _posix(tmp_path / "k.json"))
    assert r.returncode != 0 and why in r.stderr, r.stderr



# ------------------------------------------------ notified variant: review follow-ups (2026-09-22)

def _proof_dir(tmp_path, got, dk, du):
    d = tmp_path / "proof"
    d.mkdir()
    (d / "db-burst.json").write_text(json.dumps({"burst": {"got": got}}))
    (d / "db-burst-kvm.json").write_text(json.dumps({
        "before": {"counters": {"mmio_exit_kernel": 100, "mmio_exit_user": 50, "exits": 1000}},
        "after": {"counters": {"mmio_exit_kernel": None if dk is None else 100 + dk,
                               "mmio_exit_user": 50 + du, "exits": 2000}}}))
    return d


@pytest.mark.parametrize("got,dk,du,ok", [
    (10000, 10000, 0, True),
    (10000, 10200, 999, True),
    (9999, 10000, 0, False),          # a doorbell went missing
    (10000, 9999, 0, False),          # fewer in-kernel exits than doorbells
    (10000, 10000, 1000, False),      # a tenth took QEMU's userspace path
    (10000, None, 0, False),          # a counter that could not be read
])
def test_doorbell_proof_refuses_anything_but_the_in_kernel_path(tmp_path, got, dk, du, ok):
    """FOUND BY CODE REVIEW: the proof was an inline heredoc no test could reach."""
    d = _proof_dir(tmp_path, got, dk, du)
    r = _run(tmp_path, 'm_db_proof "%s" 10000 && echo PROVEN' % _posix(d))
    assert ("PROVEN" in r.stdout) == ok, r.stdout + r.stderr
    assert ('"ok": true' in r.stdout) == ok


def test_a_burst_the_monitor_refuses_fails_the_probe(native_servers, tmp_path):
    if not LINUX_IPC:
        pytest.skip("needs Linux")
    d, srv, path, shm, kick, mon = _notified_rig(native_servers)
    try:
        r = subprocess.run([_PY, PROBE, "--proto", "shmdb", "--kick", kick, "--shm", shm + "@4096", "--ivshm", path,
                            "--shm-lib", str(native_servers / "libshmchan.so"), "--db-burst", "100001",
                            "--timeout-s", "0.5", "--tag", "burst"], capture_output=True, text=True, timeout=120)
    finally:
        _stop(mon, srv)
    assert r.returncode == 6 and '"got": 0' in r.stdout, r.stdout + r.stderr


def test_one_host_monitor_serves_probe_after_probe(native_servers, tmp_path):
    """A ladder run sends ~26 probes through one host monitor in turn."""
    if not LINUX_IPC:
        pytest.skip("needs Linux")
    d, srv, path, shm, kick, mon = _notified_rig(native_servers)
    summaries = []
    try:
        for i, proto in enumerate(("shmdb", "shmkick", "shmdb")):
            sub = tmp_path / ("p%d" % i)
            sub.mkdir()
            r, out = _notified_probe(native_servers, proto, shm, kick, path, sub)
            assert r.returncode == 0, r.stdout + r.stderr
            summaries.append(json.loads(out.read_text())["summary"])
    finally:
        (mout, _merr), _ = _stop(mon, srv)
    assert summaries[2]["ivshm_peer"] == 3 and summaries[2]["notify"] == _clean_notify(55)
    done = mout.decode()
    assert re.search(r"\bclients=3\b", done) and " ring_misses=0 " in done and " notify_fail=0 " in done, done


def _doorbell_far_end(path, shm, kick, drop_first):
    """A far end in Python: a peer of the real server that answers in the slot and
    rings the client's eventfd -- except, with drop_first, the first time, as
    QEMU does for a peer it has not registered yet."""
    import mmap
    import struct as _st
    import threading
    me, _ = _peer(path)
    _msg(me)                                      # its own eventfd
    me.setblocking(False)
    efds = {}
    fd = os.open(shm, os.O_RDWR)
    mm = mmap.mmap(fd, 1 << 20)
    base = 4096
    mm[base:base + 8] = _st.pack("<II", 0x314B4853, 1)
    ls = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
    ls.bind(kick)
    ls.listen(1)
    state = {"n": 0}

    def drain_server():
        while True:
            try:
                data, fds, _f, _a = _socket.recv_fds(me, 8, 1)
            except BlockingIOError:
                return
            if len(data) < 8:
                return
            v = _st.unpack("<q", data)[0]
            if fds:
                efds[v] = fds[0]

    def serve():
        conn, _ = ls.accept()
        while True:
            b = conn.recv(64)
            if not b:
                return
            drain_server()
            seq = _st.unpack("<Q", mm[base + 64:base + 72])[0]
            peer = _st.unpack("<I", mm[base + 76:base + 80])[0]
            mm[base + 256:base + 320] = mm[base + 128:base + 192]
            mm[base + 192:base + 200] = _st.pack("<Q", seq)
            state["n"] += 1
            if drop_first and state["n"] == 1:
                continue
            os.eventfd_write(efds[peer], 1)
    threading.Thread(target=serve, daemon=True).start()
    return me, ls


def test_the_doorbell_handshake_retries_a_dropped_doorbell(native_servers, tmp_path):
    """The reason the handshake exists: QEMU drops a doorbell to a peer it has not
    registered yet. The first exchange's doorbell is dropped here; the arm must
    still run, after exactly two handshake attempts, with clean accounting."""
    if not LINUX_IPC:
        pytest.skip("needs Linux")
    d = _short_dir()
    srv, path, shm = _start_ivshmem_server(d)
    kick = os.path.join(d, "kick.sock")
    try:
        _doorbell_far_end(path, shm, kick, drop_first=True)
        r, out = _notified_probe(native_servers, "shmdb", shm, kick, path, tmp_path)
    finally:
        _stop(srv)
    assert r.returncode == 0, r.stdout + r.stderr
    summ = json.loads(out.read_text())["summary"]
    assert summ["handshake_attempts"] == 2 and summ["notify"] == _clean_notify(55), summ


def test_an_early_notification_is_counted(native_servers, tmp_path):
    """A far end that notifies BEFORE its reply is visible: the wake-up is early,
    and the exchange completes only on the second notification."""
    import time as _t
    if not LINUX_IPC:
        pytest.skip("needs Linux")
    d = _short_dir()
    shm = os.path.join(d, "slot.shm")
    with open(shm, "wb") as f:
        f.write(b"\0" * (1 << 20))
    kick = os.path.join(d, "kick.sock")

    def early(conn):
        conn.sendall(b"K")
        _t.sleep(0.05)
    _fake_notified_server(shm, kick, lambda conn: conn.sendall(b"K"), before=early)
    r, out = _notified_probe(native_servers, "shmkick", shm, kick, "", tmp_path, "--n", "3", "--warmup", "0")
    assert r.returncode == 0, r.stdout + r.stderr
    nt = json.loads(out.read_text())["summary"]["notify"]
    assert nt["early_wakeups"] == 3 and nt["notifications"] == 6 and nt["exchanges"] == 3, nt


def test_an_early_notification_and_no_second_is_lost_not_a_long_sample(native_servers, tmp_path):
    """FOUND BY CODE REVIEW: this used to come back OK, as a sample as long as the
    timeout. A reply that sits in the slot with no notification of its own is lost."""
    import time as _t
    if not LINUX_IPC:
        pytest.skip("needs Linux")
    d = _short_dir()
    shm = os.path.join(d, "slot.shm")
    with open(shm, "wb") as f:
        f.write(b"\0" * (1 << 20))
    kick = os.path.join(d, "kick.sock")

    def early(conn):
        conn.sendall(b"K")
        _t.sleep(0.05)
    _fake_notified_server(shm, kick, lambda conn: None, before=early)
    r, out = _notified_probe(native_servers, "shmkick", shm, kick, "", tmp_path,
                             "--n", "3", "--warmup", "0", "--timeout-s", "0.5")
    assert r.returncode == 5 and "notification lost" in r.stdout, r.stdout + r.stderr
    assert not out.exists()


def test_no_reply_at_all_is_a_stall(native_servers, tmp_path):
    if not LINUX_IPC:
        pytest.skip("needs Linux")
    d = _short_dir()
    shm = os.path.join(d, "slot.shm")
    with open(shm, "wb") as f:
        f.write(b"\0" * (1 << 20))
    kick = os.path.join(d, "kick.sock")
    _fake_notified_server(shm, kick, lambda conn: None, answer=False)
    st = tmp_path / "stall.json"
    r, out = _notified_probe(native_servers, "shmkick", shm, kick, "", tmp_path,
                             "--timeout-s", "0.3", "--stall-out", str(st))
    assert r.returncode == 3, r.stdout + r.stderr
    rec = json.loads(st.read_text())["stall"]
    assert rec["kind"] == "timeout" and rec["proto"] == "shmkick" and not out.exists()


def test_a_doorbell_arm_whose_kick_stream_closes_is_broken_not_a_stall(native_servers, tmp_path):
    """FOUND BY CODE REVIEW: a shmdb wait watched only its eventfd, so a far end
    that hung up the kick stream was filed as a 10 s stall."""
    if not LINUX_IPC:
        pytest.skip("needs Linux")
    d = _short_dir()
    srv, path, shm = _start_ivshmem_server(d)
    kick = os.path.join(d, "kick.sock")
    import struct as _st
    with open(shm, "r+b") as f:
        f.seek(4096)
        f.write(_st.pack("<II", 0x314B4853, 1))
    try:
        _fake_notified_server(shm, kick, lambda conn: None, close_on_accept=True)
        st = tmp_path / "stall.json"
        r, out = _notified_probe(native_servers, "shmdb", shm, kick, path, tmp_path,
                                 "--timeout-s", "3", "--stall-out", str(st))
    finally:
        _stop(srv)
    assert r.returncode == 5, r.stdout + r.stderr
    assert not st.exists() and not out.exists()


def test_a_kick_with_no_request_is_stale_and_answered_by_nothing(native_servers, tmp_path):
    if not LINUX_IPC:
        pytest.skip("needs Linux")
    d, srv, path, shm, kick, mon = _notified_rig(native_servers)
    try:
        c = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        c.connect(kick)
        c.sendall(b"K")                     # the slot untouched: nothing to answer
        c.sendall(b"E")
        c.settimeout(2.0)
        assert c.recv(16) == b"E", "a stale kick must not be answered"
        c.close()
        r, out = _notified_probe(native_servers, "shmkick", shm, kick, path, tmp_path)
    finally:
        (mout, _merr), _ = _stop(mon, srv)
    assert r.returncode == 0 and json.loads(out.read_text())["summary"]["notify"] == _clean_notify(55)
    done = mout.decode()
    # At least one: the probe's own kicks can add stale counts (see the notified
    # test above), so the exact number is timing, not behaviour.
    m = re.search(r"\bstale=(\d+) ", done)
    assert m and int(m.group(1)) >= 1 and re.search(r"\bclients=2\b", done), done


def test_a_peer_missing_from_the_table_is_found_and_counted(native_servers, tmp_path):
    """The table-miss fallback: a client that joins the ivshmem server only AFTER
    the monitor accepted its kick connection. The doorbell must still arrive, and
    the miss must be counted, because it put system calls on that reply's path."""
    import select as _sel
    import struct as _st
    if not LINUX_IPC:
        pytest.skip("needs Linux")
    lp = _probe_mod()
    d, srv, path, shm, kick, mon = _notified_rig(native_servers)
    try:
        c = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        c.connect(kick)
        c.sendall(b"E")
        c.settimeout(2.0)
        assert c.recv(16) == b"E"          # the monitor is past accept() and its drain
        me, pid = _peer(path)
        own, efd = _msg(me)
        while own != pid:                   # the monitor (peer 1) is announced first
            if efd is not None:
                os.close(efd)
            own, efd = _msg(me)
        with open(shm, "r+b") as f:
            f.seek(4096 + 64)
            seq = _st.unpack("<Q", f.read(8))[0]
            f.seek(4096 + 128)
            f.write(lp.build_frame(1))
            f.seek(4096 + 72)
            f.write(_st.pack("<II", 1, pid))            # reply_via = doorbell, client_peer = pid
            f.seek(4096 + 64)
            f.write(_st.pack("<Q", seq + 1))
        c.sendall(b"K")
        assert _sel.select([efd], [], [], 2.0)[0], "the doorbell never arrived"
        assert _st.unpack("<Q", os.read(efd, 8))[0] == 1
        c.close()
        me.close()
    finally:
        (mout, _merr), _ = _stop(mon, srv)
    done = mout.decode()
    assert " ring_misses=1 " in done and " rings=1 " in done, done


@needs_linux_ipc
def test_ivshmem_server_announces_a_newcomer_before_its_own_eventfd_in_process():
    """FOUND BY CODE REVIEW: the socket-level order test passed with the order
    reversed. In-process, every message is logged in the order it is sent."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("ivsrv", IVSHMEM_SERVER_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    log = []
    real = mod.send_msg

    def spy(sock, value, fd=None):
        log.append((sock.fileno(), value, fd is not None))
        return real(sock, value, fd)
    mod.send_msg = spy
    d = _short_dir()
    shm = os.path.join(d, "x.shm")
    with open(shm, "wb") as f:
        f.write(b"\0" * 4096)
    sfd = os.open(shm, os.O_RDWR)
    srv = mod.Server(os.path.join(d, "s.sock"), sfd, 1, lambda m: None)
    clients = []
    try:
        for _ in range(2):
            c = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
            c.connect(os.path.join(d, "s.sock"))
            clients.append(c)
            srv.accept()
        by_id = {p.id: fileno for fileno, p in srv.peers.items()}
        told_old = log.index((by_id[1], 2, True))
        own_new = log.index((by_id[2], 2, True))
        assert told_old < own_new, "peer 1 must learn about peer 2 before peer 2 gets its own eventfd"
    finally:
        for c in clients:
            c.close()
        srv.close()


@needs_linux_ipc
def test_ivshmem_server_announces_the_departure_of_a_newcomer_that_failed_setup():
    import importlib.util
    spec = importlib.util.spec_from_file_location("ivsrv2", IVSHMEM_SERVER_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    d = _short_dir()
    shm = os.path.join(d, "x.shm")
    with open(shm, "wb") as f:
        f.write(b"\0" * 4096)
    srv = mod.Server(os.path.join(d, "s.sock"), os.open(shm, os.O_RDWR), 1, lambda m: None)
    c1 = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
    c1.connect(os.path.join(d, "s.sock"))
    srv.accept()
    for _ in range(4):                         # version, id, shm, own eventfd
        _msg(c1)
    real = mod.send_msg

    def failing(sock, value, fd=None):
        if value == 2 and fd is not None and sock.fileno() not in srv.peers:
            raise OSError("newcomer vanished")   # its own eventfd never goes out
        return real(sock, value, fd)
    mod.send_msg = failing
    c2 = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
    c2.connect(os.path.join(d, "s.sock"))
    srv.accept()
    try:
        told, fd = _msg(c1)
        assert (told, fd is not None) == (2, True)
        gone, gfd = _msg(c1)
        assert (gone, gfd) == (2, None), "peer 1 must hear that the failed newcomer is gone"
    finally:
        c1.close()
        c2.close()
        srv.close()


def test_kvm_snapshot_pauses_once_before_and_never_after(tmp_path):
    kvm = _fake_kvm(tmp_path)
    j = tmp_path / "kvm.json"
    r = _run(tmp_path, 'KVM_QEMU_PID=4242; KVM_DEBUGFS="%s"; PROC_ROOT="%s"; CORE_AUX=0; '
             'sleep() { echo "SLEPT $*" >&2; }; taskset() { shift 2; "$@"; }; '
             'm_kvm_snap "%s" before && m_kvm_snap "%s" after && echo DONE'
             % (_posix(kvm), _posix(tmp_path / "proc"), _posix(j), _posix(j)),
             sudo='[ "$1" = -n ] && shift; exec "$@"')
    assert "DONE" in r.stdout, r.stderr
    assert r.stderr.count("SLEPT 0.1") == 1, r.stderr


def test_m_probe_brackets_the_probe_with_kvm_snapshots(tmp_path):
    kvm = _fake_kvm(tmp_path)
    fake = tmp_path / "probe.py"
    fake.write_bytes(("import sys, json\na = sys.argv\n"
                      "open(%r, 'w').write('250\\n')\n"
                      "open(a[a.index('--out') + 1], 'w').write(json.dumps({'argv': a[1:]}))\n"
                      % str(kvm / "4242-12" / "mmio_exit_kernel")).encode())
    out = tmp_path / "out"
    out.mkdir()
    r = _run(tmp_path, 'N=10; WARMUP=1; INTERVAL_MS=0; CORE_PROBE=0; SAMPLE_WINDOW=0; PROBE="%s"; KVM_STATS=1; '
             'KVM_QEMU_PID=4242; KVM_DEBUGFS="%s"; PROC_ROOT="%s"; CORE_AUX=0; '
             'sleep() { :; }; taskset() { shift 2; "$@"; }; m_probe "%s" x_r1 127.0.0.1 1 && echo DONE'
             % (_posix(fake), _posix(kvm), _posix(tmp_path / "proc"), _posix(out)),
             sudo='[ "$1" = -n ] && shift; exec "$@"')
    assert "DONE" in r.stdout, r.stderr
    doc = json.loads((out / "kvm-x_r1.json").read_text())
    assert doc["before"]["counters"]["mmio_exit_kernel"] == 10
    assert doc["after"]["counters"]["mmio_exit_kernel"] == 250


# --------------------------------------------------------------------------
# redact-aws.sh under every awk on this host


REDACT = os.path.join(HERE, "..", "orin-native", "gpu-concurrency", "redact-aws.sh")


@pytest.mark.parametrize("impl", ["mawk", "gawk", "original-awk"])
def test_the_redactor_selftest_passes_under_each_awk(impl):
    """FOUND 2026-09-22 in a rehearsal on the Orin: the MAC pattern used a {5}
    interval, which Ubuntu 22.04's mawk does not support, so every foreign MAC
    went through unmasked. The selftest asserts both directions; run it under
    each implementation present rather than only the one `awk` resolves to."""
    if BASH is None:
        pytest.skip("needs bash")
    exe = shutil.which(impl)
    if exe is None:
        pytest.skip("%s not installed" % impl)
    env = dict(os.environ, AWK=exe)
    r = subprocess.run([BASH, REDACT, "selftest"], capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0 and "PASS" in r.stdout, r.stdout + r.stderr
