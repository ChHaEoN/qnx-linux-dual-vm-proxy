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

def _summary(tag, n=1000, warmup=200, bad=0, rejected=0,
             policy="SCHED_OTHER", priority=0, affinity=(4,)):
    return {"summary": {"tag": tag, "n": n, "warmup_discarded": warmup, "bad": bad,
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
        F="$F"'"sched_policy":"SCHED_OTHER","sched_priority":0,"cpu_affinity":[4]}}'
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
    return {"stall": {"tag": tag, "kind": "timeout", "at_sample": 391, "of": 1200, "warmup": 200,
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
