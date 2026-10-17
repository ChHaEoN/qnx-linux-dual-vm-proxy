"""randomise_report.py (Phase 3b / A6, 2026-10-17): the analysis of run-randomise.sh, section by
section as its header fixes it -- the per-round contrasts, the order and layout effects per VM boot
(P1, P2), the S effect per adjacent F-R pair (P3, C1), the board-boot bootstrap of phi (P4), the
I95 / I999 scoring against the 3 us margin, the checks M1-M9 and the VOIDs they cause, and the
unscored U1-U8.

The records are synthetic, written here from a real schedule (randomise_schedule.generate) in the
format the harness writes, with effects put in on purpose: a null world must hold, an effect must be
refuted on exactly the contrasts it touches, and every failed check must void exactly the
predictions its row guards. Nothing here is a measured figure.
"""
import collections
import io
import json
import math
import os
import random
import re
import shutil
import sys
from contextlib import redirect_stdout

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
sys.path.insert(0, GC)
import randomise_report as rr  # noqa: E402
import randomise_schedule as rs  # noqa: E402

ORIGINAL_BOOTSTRAP_N = rr.BOOTSTRAP_N      # before the fixture below shortens it
SEED = 1234
ARM_NAME = {"A": "A-loopback", "B": "B-bridge", "C": "C-null", "D": "D-guest"}
BASE = {"A": 40.0, "B": 60.0, "C": 150.0, "D": 200.0}
SHA = "0" * 64


@pytest.fixture(scope="module")
def sched_text():
    return rs.generate(SEED)


@pytest.fixture(scope="module")
def sched(sched_text):
    return rs.parse(sched_text)


@pytest.fixture(autouse=True)
def _quick_bootstrap(monkeypatch):
    """Most tests do not need 10 000 resamples; the ones about the bootstrap set their own."""
    monkeypatch.setattr(rr, "BOOTSTRAP_N", 400)


def _want_core(pin, comm):
    if comm == "CPU 0/KVM":
        return pin[0]
    if comm == "CPU 1/KVM":
        return pin[1]
    return pin[2]


COMMS = [(5000, "qemu-system-aar"), (5001, "CPU 0/KVM"), (5002, "CPU 1/KVM"), (5003, "worker")]
# The paths the harness reads the host through, as the board has them (run-randomise.sh and lib-measure.sh
# defaults); boot.json records them as "hooks".
HOOKS = {"proc_root": "/proc", "sys_root": "/sys", "reset_reason": "/sys/devices/platform/bus@0/c360000.pmc/reset_reason",
         "pstore_var": "/var/lib/systemd/pstore", "emc_bpmp": "/sys/kernel/debug/bpmp/debug/clk/emc/rate",
         "emc_ccf": "/sys/kernel/debug/clk/emc/clk_rate", "sysfs_cpu": "/sys/devices/system/cpu",
         "kvm_debugfs": "/sys/kernel/debug/kvm", "tegra": 1}


def write_records(root, sched, sched_sha, tags, value, rng=None, break_=None):
    """The record of each board boot in tags, as run-randomise.sh writes it. value(ctx) gives an
    arm-round's p50 in us; break_(kind, ctx, line) may rewrite or drop (return None) a record line."""
    rng = rng or random.Random(7)
    brk = break_ or (lambda kind, ctx, line: line)
    for bi, tag in enumerate(tags):
        b = sched["boots"][tag]
        bd = root / tag
        bd.mkdir(parents=True)
        boot = {"experiment": "randomise", "boot_tag": tag, "kind": b["kind"], "pattern": b["pattern"],
                "schedule_sha256": sched_sha, "reset_reason": "SYS_RESET_N", "pstore": {"sys": [], "archive": []},
                "first_reads": True, "uptime_preflight_s": 640, "uptime_first_vm_s": 700, "cmdline_tokens": 0,
                "emc_first": {"bpmp": "2133000000", "ccf": "2133000000"},
                "boot_id": "0000000%d-1111-2222-3333-444444444444" % bi, "hooks": dict(HOOKS), "complete": True}
        boot = brk("boot", {"tag": tag}, boot)
        (bd / "boot.json").write_text(json.dumps(boot))
        logins = []
        for v, vm in sorted(b["vms"].items()):
            vd = bd / ("v%d" % v)
            vd.mkdir()
            brk("vmdir", {"tag": tag, "v": v, "path": vd}, None)        # a break_ may put a file in the directory
            pin = vm["pin"]
            stamp = {"experiment": "randomise", "boot_tag": tag, "vm": v, "s_regime": vm["S"],
                     "qemu_pin": ",".join(map(str, pin)), "qemu_pad": "-" if vm["pad"] is None else str(vm["pad"]),
                     "schedule_sha256": sched_sha, "guest_ifs_sha256": "a" * 64, "governor_state": "pinned",
                     "governor_after": "performance", "cstate_policy": "shallow", "tegra": 1,
                     "kernel": "6.8.12-1021-tegra", "qemu_version": "QEMU emulator version 8.2.2 (Debian 1:8.2.2+ds-0ubuntu1.4)",
                     "system": {"nvpmodel": "NV Power Mode: 25W 1", "proc_root": "/proc", "sys_root": "/sys",
                                "l4t_release": "# R39 (release), REVISION: 2.1, GCID: 0, BOARD: generic, EABI: aarch64"},
                     "platform": {"proc_root": "/proc", "sys_root": "/sys",
                                  "docker": {"enabled": "enabled", "active": "inactive"},
                                  "docker_socket": {"enabled": "enabled", "active": "inactive"},
                                  "containerd": {"enabled": "enabled", "active": "inactive"},
                                  "dockerd_cpus": "not running", "containerd_cpus": "not running", "containerd_shims": 0}}
            stamp["platform_after"] = dict(stamp["platform"])
            stamp = brk("stamp", {"tag": tag, "v": v}, stamp)
            (vd / "stamp.json").write_text(json.dumps(stamp))
            halt = "halt_poll_ns=500000 halt_poll_ns_grow=2 halt_poll_ns_grow_start=10000 halt_poll_ns_shrink=0"
            (vd / "halt.log").write_text("%s\n%s\n" % (brk("halt", {"tag": tag, "v": v, "when": "start"}, "start " + halt),
                                                       brk("halt", {"tag": tag, "v": v}, "end " + halt)))
            (vd / "gpu.log").write_text("%s\n%s\n" % (brk("gpu", {"tag": tag, "v": v, "when": "start"}, "start 0"),
                                                      brk("gpu", {"tag": tag, "v": v}, "end 0")))
            rb = [brk("readback", {"tag": tag, "v": v, "who": "qemu"},
                      "qemu r- pid=4000 personality=%s environ=%d startstack=281474976710000 maps=a,b,c stack=x-y t_ms=50"
                      % ("00040000" if vm["norand"] else "00000000", vm["env"]))]
            order, threads, cpu, confine, emc, rounds = [], [], [], [], [], []
            for r, rd in sorted(vm["rounds"].items()):
                ctx0 = {"tag": tag, "v": v, "r": r}
                for who in ("host", "ns"):
                    m = rd["mon"][who]
                    rb.append(brk("readback", dict(ctx0, who="mon-" + who),
                                  "mon-%s r%d pid=%d personality=%s environ=%d startstack=%d maps=a,b,c stack=x-y t_ms=20"
                                  % (who, r, 6000 + r, "00040000" if m["norand"] else "00000000", m["env"],
                                     281474976710000 + rng.randrange(4096))))
                order.append(brk("order", ctx0, "round %d cell=%s order: %s" % (r, rd["cell"], " ".join(rd["order"]))))
                for when in ("before", "after"):
                    for tid, comm in COMMS:
                        threads.append(brk("threads", dict(ctx0, when=when, comm=comm),
                                           "round %d %s tid=%d last=%d allowed=%d comm=%s"
                                           % (r, when, tid, _want_core(pin, comm), _want_core(pin, comm), comm)))
                    confine.append(brk("confine", dict(ctx0, when=when),
                                       "round %d %s udevd=3,5 pid1=3,5 shells=3,5;3,5" % (r, when)))
                rounds.append("round %d start=%d end=%d" % (r, 1000 + 40 * r, 1030 + 40 * r))
                logins.append(brk("logins", dict(ctx0), "v%d r%d accepted=0" % (v, r)))
                for pos, arm in enumerate(rd["order"], 1):
                    ctx = dict(ctx0, b=bi, S=vm["S"], cell=rd["cell"], O=rd["O"], L=rd["L"], arm=arm, pos=pos,
                               pin=pin, pad=rd["probe"][arm]["pad"], pattern=b["pattern"])
                    p = rd["probe"][arm]
                    rb.append(brk("readback", dict(ctx0, who="probe-" + arm),
                                  "probe-%s r%d pid=%d personality=%s environ=%d startstack=%d maps=a,b,c stack=x-y t_ms=30"
                                  % (arm, r, 7000 + pos, "00040000" if p["norand"] else "00000000", p["env"],
                                     281474976710000 + rng.randrange(4096))))
                    p50 = value(ctx)
                    tag_ = "%s_%s%d" % (ARM_NAME[arm], "s" if r == 0 else "r", r)
                    samples = [p50 / 1000.0 + rng.random() * 0.002 for _ in range(30)]
                    summ = {"tag": tag_, "proto": "tcp", "n": 1000, "warmup_discarded": 200, "bad": 0,
                            "rejected_by_monitor": 0, "p50_ms": p50 / 1000.0, "p99_ms": (p50 + 20) / 1000.0,
                            "max_ms": (p50 + 50 + rng.random()) / 1000.0, "sched_policy": "SCHED_OTHER",
                            "cpu_affinity": [4]}
                    summ = brk("lat", ctx, summ)
                    if summ is not None:
                        (vd / ("lat-%s.json" % tag_)).write_text(json.dumps({"summary": summ, "samples_in_order": samples}))
                    # every thread ran during the arm-round: its schedstat run time rose
                    kv = {"before": {"t_ns": 1, "counters": {"halt_wakeup": 100, "halt_attempted_poll": 50,
                                                             "halt_successful_poll": 10},
                                     "threads": {str(tid): {"comm": comm, "run_ns": 1000 * tid} for tid, comm in COMMS}},
                          "after": {"t_ns": 2, "counters": {"halt_wakeup": 1300, "halt_attempted_poll": 1250,
                                                            "halt_successful_poll": 260},
                                    "threads": {str(tid): {"comm": comm, "run_ns": 1000 * tid + 1200000 + 1000 * pos}
                                                for tid, comm in COMMS}}}
                    kv = brk("kvm", dict(ctx0, arm=arm), kv)
                    (vd / ("kvm-%s.json" % tag_)).write_text(json.dumps(kv))
                    for tid, comm in COMMS:
                        cpu.append(brk("cpu", dict(ctx0, arm=arm, comm=comm),
                                       "round %d after-%s tid=%d last=%d allowed=%d comm=%s"
                                       % (r, arm, tid, _want_core(pin, comm), _want_core(pin, comm), comm)))
                    emc.append(brk("emc", dict(ctx0, arm=arm), "round %d after-%s bpmp=2133000000 ccf=2133000000" % (r, arm)))
            for name, lines in (("readback.log", rb), ("order.log", order), ("threads.log", threads), ("cpu.log", cpu),
                                ("confine.log", confine), ("emc.log", emc), ("rounds.log", rounds)):
                (vd / name).write_text("".join(x + "\n" for x in lines if x is not None))
        (bd / "logins.txt").write_text("".join(x + "\n" for x in logins if x is not None) + "total accepted=0\n")
    return [root / t for t in tags]


def null_world(sd_vm=0.2, sd_board=0.2, noise=0.3, seed=3):
    """The ladder's rungs at fixed levels, every path moved alike by the board boot and by the VM
    boot, every arm-round a little noise: no setup factor does anything, so no contrast moves. The
    two F VM boots of a board boot are moved by +d and -d, so the board boots' F means agree and,
    with a large sd_vm, the level clearly lives at the VM boot; the R VM boots by a draw of their
    own. The default is a quiet world, where the floor does not move between VM boots either."""
    rng = random.Random(seed)
    board = {}
    vmshift = {}

    def value(ctx):
        b = board.setdefault(ctx["tag"], rng.gauss(0, sd_board))
        key = (ctx["tag"], ctx["v"])
        if key not in vmshift:
            if ctx["S"] == "F":
                d = vmshift.setdefault((ctx["tag"], "d"), abs(rng.gauss(0, sd_vm)) + 0.5 * sd_vm)
                first_f = ctx["pattern"].index("F") + 1
                vmshift[key] = d if ctx["v"] == first_f else -d
            else:
                vmshift[key] = rng.gauss(0, sd_vm)
        return BASE[ctx["arm"]] + b + vmshift[key] + rng.gauss(0, noise)
    return value


def _report(dirs, sched_path, extra=()):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = rr.main(["--schedule", str(sched_path)] + list(extra) + [str(d) for d in dirs])
    return rc, buf.getvalue()


def _lines(out, start):
    return [ln for ln in out.splitlines() if ln.lstrip().startswith(start)]


def _verdict(out, name):
    """The verdict word printed on a prediction's line, e.g. _verdict(out, 'P1 K1')."""
    got = [ln for ln in out.splitlines() if ln.lstrip().startswith(name + " ") or ln.lstrip().startswith(name + ":")]
    assert len(got) == 1, (name, got)
    return got[0].rsplit("-> ", 1)[1].split()[0]


@pytest.fixture()
def world(tmp_path, sched, sched_text, monkeypatch):
    """(write(value, break_) -> report output) over the six scored board boots, with the
    committed hash pointed at this test's schedule."""
    p = tmp_path / "schedule.txt"
    p.write_text(sched_text)
    sha = rs.sha256(sched_text)
    monkeypatch.setattr(rr, "SCHEDULE_SHA256", sha)

    def go(value, break_=None, sub="run", tags=rs.SCORED, sha_in_records=sha, extra=()):
        dirs = write_records(tmp_path / sub, sched, sha_in_records, tags, value, break_=break_)
        return _report(dirs, p, extra)
    return go


# ------------------------------------------------------------------ the intervals

def test_the_interval_table_is_the_designs_and_each_pair_is_the_narrowest_with_its_coverage():
    assert rr.INTERVALS == {12: {"I95": (3, 10), "I999": (1, 12)}, 24: {"I95": (7, 18), "I999": (4, 21)}}
    for k, want95, want999 in ((12, 0.961, 0.9995), (24, 0.977, 0.9997)):
        j95 = rr.INTERVALS[k]["I95"][0]
        j999 = rr.INTERVALS[k]["I999"][0]
        assert round(rr.coverage(k, j95), 3) == want95
        assert round(rr.coverage(k, j999), 4) == want999
        assert rr.coverage(k, j95 + 1) < 0.95 and rr.coverage(k, j95) >= 0.95
        assert (j999 + 1 > k // 2) or rr.coverage(k, j999 + 1) < 0.999
        assert rr.coverage(k, j999) >= 0.999
        assert rr.INTERVALS[k]["I95"][1] == k + 1 - j95 and rr.INTERVALS[k]["I999"][1] == k + 1 - j999


def test_interval_takes_the_order_statistics_of_the_k_values():
    vals = list(range(24, 0, -1))           # 24 .. 1, unsorted on purpose
    iv = rr.interval(vals)
    assert iv["k"] == 24 and iv["I95"] == (7, 18) and iv["I999"] == (4, 21) and iv["band"] == (1, 24)
    assert iv["median"] == 12.5
    iv = rr.interval([float(x) for x in range(1, 13)])
    assert iv["I95"] == (3.0, 10.0) and iv["I999"] == (1.0, 12.0) and iv["band"] == (1.0, 12.0)


def test_interval_refuses_a_k_the_design_has_no_interval_for():
    with pytest.raises(ValueError):
        rr.interval([1.0] * 23)


@pytest.mark.parametrize("i95,i999,want", [
    ((-3.0, 3.0), (-9.0, 9.0), "HELD"),         # the margin's ends are inside
    ((-2.9, 3.1), (-9.0, 9.0), "UNRESOLVED"),
    ((3.5, 6.0), (3.01, 7.0), "REFUTED"),
    ((3.5, 6.0), (3.0, 7.0), "UNRESOLVED"),     # I999 touches the margin: not wholly outside
    ((-8.0, -4.0), (-9.0, -3.01), "REFUTED"),
    ((-8.0, -4.0), (-9.0, -3.0), "UNRESOLVED"),
    ((-1.0, 1.0), (-1.0, 1.0), "HELD"),
])
def test_the_verdict_rule(i95, i999, want):
    assert rr.verdict({"I95": i95, "I999": i999}) == want


def test_the_margin_is_three_microseconds():
    assert rr.MARGIN == 3.0


# ------------------------------------------------------------------ the effects

def test_the_order_layout_and_interaction_effects_of_one_vm_boot():
    o, lay, inter = rr.vm_effects({"FF": 1.0, "FR": 3.0, "RF": 7.0, "RR": 13.0})
    assert o == 0.5 * ((7 + 13) - (1 + 3)) and lay == 0.5 * ((3 + 13) - (1 + 7)) and inter == 0.5 * ((13 - 7) - (3 - 1))


def test_components_of_a_balanced_nested_design_by_moments():
    # two boards of two VM boots of two rounds: worked by hand
    data = [[[1.0, 3.0], [5.0, 7.0]], [[9.0, 11.0], [13.0, 15.0]]]
    s2r, s2v, s2b = rr.components(data)
    # MS_round = 2 (each pair differs by 2); MS_vm = 2 * ((2-4)^2 + (6-4)^2 + (10-12)^2 + (14-12)^2) / 2 = 16
    # MS_board = 4 * ((4-8)^2 + (12-8)^2) / 1 = 128
    assert s2r == 2.0 and s2v == (16.0 - 2.0) / 2 and s2b == (128.0 - 16.0) / 4


def test_components_floor_at_zero():
    data = [[[1.0, 9.0], [1.0, 9.0]], [[1.0, 9.0], [1.0, 9.0]]]
    s2r, s2v, s2b = rr.components(data)
    assert s2r == 32.0 and s2v == 0.0 and s2b == 0.0


def test_phi_and_its_undefined_case():
    assert rr.phi(3.0, 1.0) == 0.75 and rr.phi(0.0, 2.0) == 0.0 and rr.phi(0.0, 0.0) is None


def test_the_cells_fixed_effects_are_removed_by_their_median_deviation():
    boards = [[[("FF", 10.0), ("FR", 20.0)], [("FF", 12.0), ("FR", 22.0)]],
              [[("FF", 14.0), ("FR", 24.0)], [("FF", 16.0), ("FR", 26.0)]]]
    adj = rr.remove_cells(boards)
    # overall median 18; FF median 13 (deviation -5), FR median 23 (deviation +5)
    assert adj == [[[15.0, 15.0], [17.0, 17.0]], [[19.0, 19.0], [21.0, 21.0]]]


def test_a_cells_deviation_is_its_median_not_its_mean():
    """FF holds 10, 11, 12 and an outlier 30: its median is 11.5 and its mean 15.75; FR holds 20 to 23.
    The overall median is 20.5, so FF's deviation is -9 by the median (the mean would give -4.75)."""
    boards = [[[("FF", 10.0), ("FR", 20.0)], [("FF", 11.0), ("FR", 21.0)]],
              [[("FF", 12.0), ("FR", 22.0)], [("FF", 30.0), ("FR", 23.0)]]]
    assert rr.remove_cells(boards) == [[[19.0, 19.0], [20.0, 20.0]], [[21.0, 21.0], [39.0, 22.0]]]


def test_the_bootstraps_interval_is_the_2_5_and_97_5_percentiles_of_its_resamples(monkeypatch):
    """phi is made to return 0.005, 0.010 ... 1.000 in turn over 200 resamples: the nearest ranks 5 and
    195 are 5/200 and 195/200 (the 95th percentile would be 190/200)."""
    vals = iter(i / 200.0 for i in range(1, 201))
    monkeypatch.setattr(rr, "phi_of", lambda pick: (next(vals), None))
    got = rr.bootstrap_phi([0] * 6, 1, 200)
    assert got["lo"] == 5 / 200.0 and got["hi"] == 195 / 200.0 and got["undefined"] == 0, got


def test_nearest_rank_percentiles():
    xs = [float(i) for i in range(1, 201)]
    assert rr.nearest_rank(xs, 2.5) == 5.0 and rr.nearest_rank(xs, 97.5) == 195.0
    assert rr.nearest_rank([7.0], 2.5) == 7.0


def _boards(sd_vm, sd_board, seed=1):
    """Six board boots of two VM boots of four rounds; the two VM boots of a board boot moved by +d
    and -d, so the VM level is clear of the board level whatever the draw."""
    rng = random.Random(seed)
    out = []
    for _b in range(6):
        bs = rng.gauss(0, sd_board)
        d = abs(rng.gauss(0, sd_vm)) + 0.5 * sd_vm
        out.append([[(c, 200 + bs + s * d + rng.gauss(0, 0.2)) for c in rs.CELLS] for s in (1, -1)])
    return out


def test_the_bootstrap_is_seeded_and_resamples_whole_board_boots(monkeypatch):
    b = _boards(5.0, 0.1)
    one = rr.bootstrap_phi(b, 99, 500)
    two = rr.bootstrap_phi(b, 99, 500)
    assert one == two and one["n"] == 500
    assert one["lo"] >= 0.5, one
    mixed = _boards(0.5, 3.0)          # both levels spread, so resamples differ
    assert rr.bootstrap_phi(mixed, 98, 500)["mean"] != rr.bootstrap_phi(mixed, 99, 500)["mean"]
    assert rr.bootstrap_phi(mixed, 99, 500) == rr.bootstrap_phi(mixed, 99, 500)


def test_the_bootstrap_draws_every_board_boot_the_last_included(monkeypatch):
    """Six board boots resampled with replacement: each resample is six picks, and over 200 of them every board
    boot is drawn, the last one among them (a draw that could never reach it would take P4's interval from five)."""
    boards = [[i] for i in range(6)]
    drawn = collections.Counter()

    def fake_phi(pick):
        assert len(pick) == 6
        drawn.update(id(x) for x in pick)
        return 0.5, None
    monkeypatch.setattr(rr, "phi_of", fake_phi)
    rr.bootstrap_phi(boards, 5, 200)
    assert set(drawn) == {id(b) for b in boards}, "every board boot is drawn"
    assert sum(drawn.values()) == 1200 and all(100 < n < 300 for n in drawn.values()), sorted(drawn.values())


def test_a_board_dominated_level_puts_the_whole_interval_below_one_half():
    got = rr.bootstrap_phi(_boards(0.05, 8.0), 5, 500)
    assert got["hi"] < 0.5, got


def test_resamples_with_no_level_variance_are_undefined_and_counted():
    flat = [[[(c, 200.0) for c in rs.CELLS] for _v in range(2)] for _b in range(6)]
    got = rr.bootstrap_phi(flat, 3, 100)
    assert got["undefined"] == 100 and got["lo"] is None and got["hi"] is None


def test_p4_rule():
    assert rr.p4_verdict({"lo": 0.5, "hi": 0.9, "undefined": 0, "n": 100}) == "HELD"
    assert rr.p4_verdict({"lo": 0.1, "hi": 0.49, "undefined": 0, "n": 100}) == "REFUTED"
    assert rr.p4_verdict({"lo": 0.1, "hi": 0.5, "undefined": 0, "n": 100}) == "UNRESOLVED", "a 97.5% bound at 0.5 is not below it"
    assert rr.p4_verdict({"lo": 0.4, "hi": 0.6, "undefined": 0, "n": 100}) == "UNRESOLVED"
    assert rr.p4_verdict({"lo": 0.6, "hi": 0.9, "undefined": 11, "n": 100}) == "UNRESOLVED"
    assert rr.p4_verdict({"lo": 0.6, "hi": 0.9, "undefined": 10, "n": 100}) == "HELD"
    assert rr.p4_verdict({"lo": None, "hi": None, "undefined": 100, "n": 100}) == "UNRESOLVED"


def test_the_bootstrap_uses_random_alone_and_the_schedules_seed():
    src = open(os.path.join(GC, "randomise_report.py"), encoding="utf-8").read()
    for word in ("shuffle(", "choice(", "choices(", "randrange(", "randint(", "sample(", "numpy"):
        assert word not in src, word
    assert "bootstrap_seed" in src and rr.BOOTSTRAP_N_DESIGN == 10000 and ORIGINAL_BOOTSTRAP_N == 10000


# ------------------------------------------------------------------ the whole report

def test_a_null_world_holds_every_contrast_and_the_label_is_on_the_page(world):
    rc, out = world(null_world())
    assert rc == 0, out
    assert out.count(rr.LABEL) >= 2
    for name in ("P1 A", "P1 K1", "P1 K2", "P1 K3", "P2 A", "P2 K1", "P2 K2", "P2 K3", "P3 K1", "P3 K2", "P3 K3", "C1 A"):
        assert _verdict(out, name) == "HELD", (name, out)
    for m in ("M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9"):
        assert any(ln.lstrip().startswith(m + " ") and ln.rstrip().endswith("ok") for ln in out.splitlines()), (m, out)


def test_a_level_that_lives_at_the_vm_boot_holds_p4_and_moves_no_contrast(world):
    rc, out = world(null_world(sd_vm=4.0, sd_board=0.2))
    assert _verdict(out, "P4") == "HELD", out
    for name in ("P1 A", "P1 K1", "P1 K2", "P1 K3", "P2 A", "P2 K1", "P2 K2", "P2 K3", "P3 K1", "P3 K2", "P3 K3"):
        assert _verdict(out, name) == "HELD", (name, out)


def test_every_scored_line_prints_its_median_both_intervals_its_band_and_k(world):
    rc, out = world(null_world())
    for ln in _lines(out, "P1 ") + _lines(out, "P2 ") + _lines(out, "P3 ") + _lines(out, "C1 "):
        assert "median" in ln and "I95" in ln and "I999" in ln and "min-max" in ln and "k=" in ln, ln
    assert all("k=24" in ln for ln in _lines(out, "P1 ") + _lines(out, "P2 "))
    assert all("k=12" in ln for ln in _lines(out, "P3 ") + _lines(out, "C1 "))
    p4 = _lines(out, "P4")[0]
    assert "phi" in p4 and "2.5%" in p4 and "97.5%" in p4 and "undefined" in p4


def test_an_order_effect_on_the_guest_echo_refutes_k1_and_k2_and_nothing_else(world):
    base = null_world()

    def value(ctx):
        return base(ctx) + (8.0 if ctx["arm"] == "C" and ctx["O"] == "R" else 0.0)
    rc, out = world(value)
    assert _verdict(out, "P1 K1") == "REFUTED" and _verdict(out, "P1 K2") == "REFUTED"
    assert _verdict(out, "P1 K3") == "HELD" and _verdict(out, "P1 A") == "HELD"
    for name in ("P2 A", "P2 K1", "P2 K2", "P2 K3", "P3 K1", "P3 K2", "P3 K3", "C1 A"):
        assert _verdict(out, name) == "HELD", (name, out)


def test_a_layout_effect_on_the_loopback_refutes_the_floor_and_the_bridge(world):
    base = null_world()

    def value(ctx):
        return base(ctx) + (6.0 if ctx["arm"] == "A" and ctx["L"] == "R" else 0.0)
    rc, out = world(value)
    assert _verdict(out, "P2 A") == "REFUTED" and _verdict(out, "P2 K3") == "REFUTED"
    assert _verdict(out, "P2 K1") == "HELD" and _verdict(out, "P2 K2") == "HELD"
    assert _verdict(out, "P1 A") == "HELD" and _verdict(out, "C1 A") == "HELD"


def test_a_vm_setup_effect_refutes_p3_and_leaves_the_control(world):
    base = null_world()

    def value(ctx):
        return base(ctx) + (5.0 if ctx["arm"] == "C" and ctx["S"] == "R" else 0.0)
    rc, out = world(value)
    assert _verdict(out, "P3 K1") == "REFUTED" and _verdict(out, "P3 K2") == "REFUTED"
    assert _verdict(out, "P3 K3") == "HELD" and _verdict(out, "C1 A") == "HELD"
    assert _verdict(out, "P1 K1") == "HELD" and _verdict(out, "P2 K1") == "HELD"


def test_a_drift_on_the_loopback_between_vm_boots_refutes_the_control(world):
    base = null_world()

    def value(ctx):
        return base(ctx) + (10.0 if ctx["arm"] == "A" and ctx["S"] == "R" else 0.0)
    rc, out = world(value)
    assert _verdict(out, "C1 A") == "REFUTED"
    assert _verdict(out, "P3 K3") == "REFUTED", "B - A moves with A"
    assert "does not void P3" in out


def test_large_round_noise_leaves_the_contrasts_unresolved_and_says_so(world):
    rc, out = world(null_world(noise=12.0, seed=5))
    got = {_verdict(out, n) for n in ("P1 K1", "P1 K2", "P2 K1", "P3 K1")}
    assert "UNRESOLVED" in got, out


def test_a_board_dominated_level_refutes_p4(world):
    rc, out = world(null_world(sd_vm=0.05, sd_board=8.0, seed=11))
    assert _verdict(out, "P4") == "REFUTED", out


def test_p4_is_resampled_from_the_schedules_bootstrap_seed(tmp_path, sched, sched_text, monkeypatch):
    p = tmp_path / "schedule.txt"
    p.write_text(sched_text)
    monkeypatch.setattr(rr, "SCHEDULE_SHA256", rs.sha256(sched_text))
    dirs = write_records(tmp_path / "run", sched, rs.sha256(sched_text), rs.SCORED, null_world(sd_vm=1.0, sd_board=2.0, seed=8))
    by = {b.tag: b for b in (rr.Boot(str(d)) for d in dirs)}
    fb = rr._f_boards(by, sched, "Lv")
    want = rr.bootstrap_phi(fb, sched["bootstrap_seed"], rr.BOOTSTRAP_N)
    other = rr.bootstrap_phi(fb, 0, rr.BOOTSTRAP_N)
    assert (other["lo"], other["hi"], other["mean"]) != (want["lo"], want["hi"], want["mean"]), "the seed matters here"
    rc, out = _report(dirs, p)
    p4 = _lines(out, "P4")[0]
    assert "2.5%% %.3f, 97.5%% %.3f over %d resamples" % (want["lo"], want["hi"], rr.BOOTSTRAP_N) in p4, p4


def test_p4_uses_the_f_vm_boots_only(world):
    """R VM boots get a huge level spread of their own; F boots are board-dominated: P4 must
    still refute, because R boots do not enter phi."""
    base = null_world(sd_vm=0.05, sd_board=8.0, seed=11)
    rng = random.Random(4)
    shift = {}

    def value(ctx):
        extra = 0.0
        if ctx["S"] == "R":
            extra = shift.setdefault((ctx["tag"], ctx["v"]), rng.gauss(0, 30.0))
        return base(ctx) + extra
    rc, out = world(value)
    assert _verdict(out, "P4") == "REFUTED", out


# ------------------------------------------------------------------ the checks void what they guard

def _void_set(out):
    names = ["P1 A", "P1 K1", "P1 K2", "P1 K3", "P2 A", "P2 K1", "P2 K2", "P2 K3", "P3 K1", "P3 K2", "P3 K3", "C1 A", "P4"]
    return {n for n in names if _verdict(out, n) == "VOID"}


ALL = {"P1 A", "P1 K1", "P1 K2", "P1 K3", "P2 A", "P2 K1", "P2 K2", "P2 K3", "P3 K1", "P3 K2", "P3 K3", "C1 A", "P4"}
P1 = {"P1 A", "P1 K1", "P1 K2", "P1 K3"}
P2 = {"P2 A", "P2 K1", "P2 K2", "P2 K3"}
P3 = {"P3 K1", "P3 K2", "P3 K3"}


def _env_off_by_one(kind, ctx, line):
    if kind == "readback" and ctx == {"tag": "b2", "v": 3, "r": 2, "who": "probe-B"}:
        n = int(line.split("environ=")[1].split()[0])
        return line.replace("environ=%d" % n, "environ=%d" % (n + 1))
    return line


def _personality_cleared(kind, ctx, line):
    if kind == "readback" and ctx.get("who") == "mon-ns" and ctx["tag"] == "b4" and "00040000" in line:
        return line.replace("00040000", "00000000")
    return line


def _readback_missing(kind, ctx, line):
    return None if kind == "readback" and ctx == {"tag": "b1", "v": 1, "r": 0, "who": "probe-D"} else line


def _order_wrong(kind, ctx, line):
    if kind == "order" and ctx == {"tag": "b5", "v": 2, "r": 3}:
        head, arms = line.split("order: ")
        a = arms.split()
        return head + "order: " + " ".join(a[1:] + a[:1])
    return line


def _thread_off_core(kind, ctx, line):
    if kind == "threads" and ctx.get("tag") == "b3" and ctx.get("r") == 4 and ctx.get("when") == "after" \
            and ctx.get("comm") == "CPU 1/KVM" and ctx.get("v") == 1:
        return line.replace("allowed=", "allowed=0-2 was=")
    return line


def _cpu_sample_off(kind, ctx, line):
    if kind == "cpu" and ctx == {"tag": "b6", "v": 4, "r": 2, "arm": "C", "comm": "worker"}:
        return line.replace("last=", "last=5 was=")
    return line


def _login(kind, ctx, line):
    return line.replace("accepted=0", "accepted=1") if kind == "logins" and ctx == {"tag": "b2", "v": 2, "r": 1} else line


def _emc(n):
    hit = []

    def f(kind, ctx, line):
        if kind == "emc" and ctx["r"] >= 1 and len(hit) < n:
            hit.append(1)
            return line.replace("bpmp=2133000000", "bpmp=3199000000")
        return line
    f.__name__ = "_emc%d" % n
    return f


def _uptime(kind, ctx, line):
    if kind == "boot" and ctx["tag"] == "b6":
        line["uptime_first_vm_s"] = 540
    return line


def _cmdline(kind, ctx, line):
    if kind == "boot" and ctx["tag"] == "b1":
        line["cmdline_tokens"] = 1
    return line


def _no_reset_reason(kind, ctx, line):
    if kind == "boot" and ctx["tag"] == "b3":
        del line["reset_reason"]
    return line


def _image(kind, ctx, line):
    if kind == "stamp" and ctx == {"tag": "b4", "v": 2}:
        line["guest_ifs_sha256"] = "b" * 64
    return line


def _docker_up(kind, ctx, line):
    if kind == "stamp" and ctx == {"tag": "b2", "v": 4}:
        line["platform_after"] = dict(line["platform_after"], dockerd_cpus="0-5")
    return line


def _halt_changed(kind, ctx, line):
    return line.replace("halt_poll_ns=500000", "halt_poll_ns=0") if kind == "halt" and ctx == {"tag": "b5", "v": 1} else line


def _gpu_busy(kind, ctx, line):
    return "end 12" if kind == "gpu" and ctx == {"tag": "b1", "v": 3} else line


def _gov(kind, ctx, line):
    if kind == "stamp" and ctx == {"tag": "b6", "v": 1}:
        line["governor_after"] = "schedutil"
    return line


def _nvp(kind, ctx, line):
    if kind == "stamp" and ctx == {"tag": "b3", "v": 3}:
        line["system"] = dict(line["system"], nvpmodel="NV Power Mode: 15W 0")
    return line


def _confine(kind, ctx, line):
    if kind == "confine" and ctx == {"tag": "b1", "v": 2, "r": 3, "when": "after"}:
        return line.replace("udevd=3,5", "udevd=0-5")
    return line


def _missing_lat(kind, ctx, line):
    return None if kind == "lat" and ctx["tag"] == "b4" and ctx["v"] == 4 and ctx["r"] == 2 and ctx["arm"] == "D" else line


def _short_lat(kind, ctx, line):
    if kind == "lat" and ctx["tag"] == "b2" and ctx["v"] == 1 and ctx["r"] == 1 and ctx["arm"] == "A":
        line = dict(line, n=999)
    return line


def _no_pstore(kind, ctx, line):
    if kind == "boot" and ctx["tag"] == "b4":
        del line["pstore"]
    return line


def _not_first(kind, ctx, line):
    if kind == "boot" and ctx["tag"] == "b5":
        line["first_reads"] = False
    return line


def _c7_on(kind, ctx, line):
    if kind == "stamp" and ctx == {"tag": "b2", "v": 3}:
        line["cstate_policy"] = "as-found"
    return line


def _shim(kind, ctx, line):
    if kind == "stamp" and ctx == {"tag": "b6", "v": 2}:
        line["platform"] = dict(line["platform"], containerd_shims=1)
    return line


def _no_order(kind, ctx, line):
    return None if kind == "order" and ctx == {"tag": "b3", "v": 3, "r": 0} else line


def _no_threads_before(kind, ctx, line):
    if kind == "threads" and ctx.get("tag") == "b1" and ctx.get("v") == 4 and ctx.get("r") == 2 \
            and ctx.get("when") == "before":
        return None
    return line


def _no_login_line(kind, ctx, line):
    return None if kind == "logins" and ctx == {"tag": "b6", "v": 1, "r": 3} else line


def _governor_unpinned(kind, ctx, line):
    if kind == "stamp" and ctx == {"tag": "b5", "v": 4}:
        line["governor_state"] = "absent"
    return line


def _sleeper_stale(kind, ctx, line):
    """A thread that slept from its pin through the arm-round keeps the last CPU it had before the pin, and
    its schedstat run time does not rise: it ran nowhere, so it is not off its core."""
    at = {"tag": "b6", "v": 4, "r": 2, "arm": "C"}
    if kind == "cpu" and ctx == dict(at, comm="worker"):
        return line.replace("last=", "last=5 was=")
    if kind == "kvm" and ctx == at:
        line["after"]["threads"]["5003"]["run_ns"] = line["before"]["threads"]["5003"]["run_ns"]
    return line


def _vcpu_stale(kind, ctx, line):
    """A vCPU thread is judged whether or not its run time rose: both run at every guest tick."""
    at = {"tag": "b2", "v": 1, "r": 3, "arm": "A"}
    if kind == "cpu" and ctx == dict(at, comm="CPU 1/KVM"):
        return line.replace("last=", "last=5 was=")
    if kind == "kvm" and ctx == at:
        line["after"]["threads"]["5002"]["run_ns"] = line["before"]["threads"]["5002"]["run_ns"]
    return line


def _no_runtime_record(kind, ctx, line):
    """A thread off its core with no entry at the snapshot's end has no run-time record: M4 fails closed."""
    at = {"tag": "b3", "v": 2, "r": 1, "arm": "B"}
    if kind == "cpu" and ctx == dict(at, comm="worker"):
        return line.replace("last=", "last=5 was=")
    if kind == "kvm" and ctx == at:
        del line["after"]["threads"]["5003"]
    return line


def _born_and_ran_off_core(kind, ctx, line):
    """A thread born during the arm-round (no entry at its start) that ran is judged from zero."""
    at = {"tag": "b5", "v": 3, "r": 4, "arm": "D"}
    if kind == "cpu" and ctx == dict(at, comm="worker"):
        return line.replace("last=", "last=5 was=")
    if kind == "kvm" and ctx == at:
        del line["before"]["threads"]["5003"]
    return line


def _tegra_off(kind, ctx, line):
    if kind == "stamp" and ctx == {"tag": "b1", "v": 1}:
        line["tegra"] = 0
    return line


def _proc_root_hook(kind, ctx, line):
    if kind == "stamp" and ctx == {"tag": "b4", "v": 3}:
        line["platform"] = dict(line["platform"], proc_root="/tmp/fake-proc")
    return line


def _hook_reset_reason(kind, ctx, line):
    if kind == "boot" and ctx["tag"] == "b2":
        line["hooks"] = dict(line["hooks"], reset_reason="/tmp/reset_reason")
    return line


def _no_hooks(kind, ctx, line):
    if kind == "boot" and ctx["tag"] == "b6":
        del line["hooks"]
    return line


def _kernel_not_the_labels(kind, ctx, line):
    if kind == "stamp" and ctx == {"tag": "b3", "v": 1}:
        line["kernel"] = "5.15.148-tegra"
    return line


def _qemu_not_the_labels(kind, ctx, line):
    if kind == "stamp" and ctx == {"tag": "b5", "v": 2}:
        line["qemu_version"] = "QEMU emulator version 6.2.0 (Debian 1:6.2+dfsg-2ubuntu6.24)"
    return line


def _l4t_not_the_labels(kind, ctx, line):
    if kind == "stamp" and ctx == {"tag": "b1", "v": 4}:
        line["system"] = dict(line["system"], l4t_release="# R36 (release), REVISION: 4.7, GCID: 0")
    return line


def _boot_id_reused(kind, ctx, line):
    if kind == "boot" and ctx["tag"] == "b3":
        line["boot_id"] = "00000001-1111-2222-3333-444444444444"       # b2's: the fixture numbers them by position
    return line


def _no_boot_id(kind, ctx, line):
    if kind == "boot" and ctx["tag"] == "b4":
        del line["boot_id"]
    return line


def _confine_twice(kind, ctx, line):
    """Two confinement read-backs for one round: which one is the round's cannot be told."""
    if kind == "confine" and ctx == {"tag": "b1", "v": 2, "r": 3, "when": "after"}:
        return line + "\n" + line
    return line


def _emc_never_read(kind, ctx, line):
    """No first EMC read in boot.json, and no clock token in the board boot's EMC lines: equal by absence."""
    if kind == "boot" and ctx["tag"] == "b3":
        del line["emc_first"]
    if kind == "emc" and ctx["tag"] == "b3":
        return line.replace(" bpmp=2133000000 ccf=2133000000", " note=none")
    return line


def _startstack_unread(kind, ctx, line):
    if kind == "readback" and ctx == {"tag": "b2", "v": 3, "r": 2, "who": "probe-B"}:
        return re.sub(r"startstack=\d+", "startstack=unread", line)
    return line


def _halt_across_vms(kind, ctx, line):
    """One VM boot's halt polling, start and end alike, differs from the board boot's first VM boot."""
    if kind == "halt" and ctx["tag"] == "b5" and ctx["v"] == 2:
        return line.replace("halt_poll_ns=500000", "halt_poll_ns=250000")
    return line


def _stall_record(kind, ctx, line):
    if kind == "vmdir" and ctx["tag"] == "b4" and ctx["v"] == 2:
        (ctx["path"] / "stall-A-loopback_r1.json").write_text("{}")
    return line


def _uptime_exactly_the_settle(kind, ctx, line):
    if kind == "boot" and ctx["tag"] == "b6":
        line["uptime_first_vm_s"] = 600
    return line


def _docker_failed(kind, ctx, line):
    """A Docker unit that failed is stopped, as an inactive one is."""
    if kind == "stamp" and ctx == {"tag": "b2", "v": 4}:
        line["platform_after"] = dict(line["platform_after"], docker={"enabled": "enabled", "active": "failed"})
    return line


def _not_complete(kind, ctx, line):
    """The board boot stopped after its last VM boot, before the restores were judged: no complete."""
    if kind == "boot" and ctx["tag"] == "b5":
        del line["complete"]
    return line


def _complete_false(kind, ctx, line):
    if kind == "boot" and ctx["tag"] == "b2":
        line["complete"] = False
    return line


def _stamp_regime_other(kind, ctx, line):
    if kind == "stamp" and ctx == {"tag": "b3", "v": 2}:
        line["s_regime"] = {"F": "R", "R": "F"}[line["s_regime"]]
    return line


def _stamp_pad_other(kind, ctx, line):
    """The R VM boots of b1 with a stamp whose pad is 16 bytes off their schedule lines'."""
    if kind == "stamp" and ctx["tag"] == "b1" and line["qemu_pad"] != "-":
        line["qemu_pad"] = str((int(line["qemu_pad"]) + 16) % 4096)
    return line


def _stamp_fixed_pad(kind, ctx, line):
    """The F VM boots of b4 with a stamp that names a pad, where their schedule lines have none."""
    if kind == "stamp" and ctx["tag"] == "b4" and line["qemu_pad"] == "-":
        line["qemu_pad"] = "0"
    return line


def _stamp_pin_other(kind, ctx, line):
    if kind == "stamp" and ctx == {"tag": "b6", "v": 3}:
        line["qemu_pin"] = ",".join(reversed(line["qemu_pin"].split(",")))
    return line


def _qemu_personality_flipped(kind, ctx, line):
    """A VM boot's QEMU read back with the other layout than its schedule line's (M2 reads QEMU's read-back
    beside every launch's)."""
    if kind == "readback" and ctx == {"tag": "b2", "v": 3, "who": "qemu"}:
        if "personality=00040000" in line:
            return line.replace("personality=00040000", "personality=00000000")
        return line.replace("personality=00000000", "personality=00040000")
    return line


def _qemu_environ_off(kind, ctx, line):
    if kind == "readback" and ctx == {"tag": "b4", "v": 1, "who": "qemu"}:
        n = int(line.split("environ=")[1].split()[0])
        return line.replace("environ=%d" % n, "environ=%d" % (n + 1))
    return line


def _gpu_busy_at_the_start(kind, ctx, line):
    """The GPU busy when a VM boot starts and idle at its end: M5 reads both."""
    return "start 37" if kind == "gpu" and ctx == {"tag": "b4", "v": 2, "when": "start"} else line


def _thread_off_core_in_the_settling_round(kind, ctx, line):
    """The settling round (round 0) is read back like the scored ones: M4 and M6 count it."""
    if kind == "threads" and ctx.get("tag") == "b2" and ctx.get("v") == 1 and ctx.get("r") == 0 \
            and ctx.get("when") == "before" and ctx.get("comm") == "CPU 0/KVM":
        return line.replace("allowed=", "allowed=0-2 was=")
    return line


def _login_in_the_settling_round(kind, ctx, line):
    return line.replace("accepted=0", "accepted=1") if kind == "logins" and ctx == {"tag": "b3", "v": 4, "r": 0} else line


def _bad_samples(kind, ctx, line):
    if kind == "lat" and ctx["tag"] == "b5" and ctx["v"] == 2 and ctx["r"] == 3 and ctx["arm"] == "B":
        return dict(line, bad=2)
    return line


@pytest.mark.parametrize("break_,voided", [
    (_env_off_by_one, P2 | P3),
    (_personality_cleared, P2 | P3),
    (_readback_missing, P2 | P3),
    (_order_wrong, P1 | P2),
    (_thread_off_core, P3 | {"P4"}),
    (_cpu_sample_off, P3 | {"P4"}),
    (_login, ALL),
    (_emc(20), ALL),
    (_uptime, ALL),
    (_cmdline, ALL),
    (_no_reset_reason, ALL),
    (_image, ALL),
    (_docker_up, ALL),
    (_halt_changed, ALL),
    (_gpu_busy, ALL),
    (_gov, ALL),
    (_nvp, ALL),
    (_confine, ALL),
    (_missing_lat, ALL),
    (_short_lat, ALL),
    (_no_pstore, ALL),
    (_not_first, ALL),
    (_c7_on, ALL),
    (_shim, ALL),
    (_no_order, P1 | P2),
    (_no_threads_before, P3 | {"P4"}),
    (_no_login_line, ALL),
    (_governor_unpinned, ALL),
    (_sleeper_stale, set()),
    (_vcpu_stale, P3 | {"P4"}),
    (_no_runtime_record, P3 | {"P4"}),
    (_born_and_ran_off_core, P3 | {"P4"}),
    (_tegra_off, ALL),
    (_proc_root_hook, ALL),
    (_hook_reset_reason, ALL),
    (_no_hooks, ALL),
    (_kernel_not_the_labels, ALL),
    (_qemu_not_the_labels, ALL),
    (_l4t_not_the_labels, ALL),
    (_boot_id_reused, ALL),
    (_no_boot_id, ALL),
    (_confine_twice, ALL),
    (_emc_never_read, ALL),
    (_startstack_unread, P2 | P3),
    (_halt_across_vms, ALL),
    (_stall_record, ALL),
    (_uptime_exactly_the_settle, set()),
    (_docker_failed, set()),
    (_not_complete, ALL),
    (_complete_false, ALL),
    (_stamp_regime_other, P2 | P3 | {"P4"}),
    (_stamp_pad_other, P2 | P3),
    (_stamp_fixed_pad, P2 | P3),
    (_stamp_pin_other, P3 | {"P4"}),
    (_qemu_personality_flipped, P2 | P3),
    (_qemu_environ_off, P2 | P3),
    (_gpu_busy_at_the_start, ALL),
    (_thread_off_core_in_the_settling_round, P3 | {"P4"}),
    (_login_in_the_settling_round, ALL),
    (_bad_samples, ALL),
], ids=lambda x: getattr(x, "__name__", "set"))
def test_a_failed_check_voids_exactly_what_it_guards(world, break_, voided):
    rc, out = world(null_world(), break_=break_)
    assert _void_set(out) == voided, out


def test_a_vm_boot_directory_that_is_missing_fails_m1_and_voids_everything(tmp_path, sched, sched_text, monkeypatch):
    p = tmp_path / "schedule.txt"
    p.write_text(sched_text)
    sha = rs.sha256(sched_text)
    monkeypatch.setattr(rr, "SCHEDULE_SHA256", sha)
    dirs = write_records(tmp_path / "run", sched, sha, rs.SCORED, null_world())
    shutil.rmtree(str(dirs[2] / "v2"))
    rc, out = _report(dirs, p)
    assert _check_line(out, "M1").rstrip().endswith("FAILED"), out
    assert "VM boots [1, 3, 4], the schedule has [1, 2, 3, 4]" in out and _void_set(out) == ALL, out


def _check_line(out, m):
    got = [ln for ln in out.splitlines() if ln.lstrip().startswith(m + " ")]
    assert len(got) == 1, (m, got)
    return got[0]


@pytest.mark.parametrize("break_,check,detail", [
    (_vcpu_stale, "M4", "b2 v1 r3 after A: CPU 1/KVM last on 5"),
    (_no_runtime_record, "M4", "b3 v2 r1 after B: worker (tid 5003) last on 5, no run-time record"),
    (_born_and_ran_off_core, "M4", "b5 v3 r4 after D: worker last on 5"),
    (_tegra_off, "M5", "b1 v1: the stamp's tegra is 0, not 1"),
    (_proc_root_hook, "M5", "b4 v3: platform proc_root '/tmp/fake-proc'"),
    (_hook_reset_reason, "M5", "b2: hook reset_reason '/tmp/reset_reason'"),
    (_no_hooks, "M5", "b6: no hooks recorded"),
    (_kernel_not_the_labels, "M5", "b3 v1: kernel '5.15.148-tegra', the label's 6.8.12-1021-tegra"),
    (_qemu_not_the_labels, "M5", "b5 v2: QEMU 'QEMU emulator version 6.2.0"),
    (_l4t_not_the_labels, "M5", "b1 v4: L4T '# R36 (release)"),
    (_boot_id_reused, "M8", "b2 and b3 ran on one boot"),
    (_no_boot_id, "M8", "b4: no boot id recorded"),
    (_not_complete, "M1", "b5: the board boot did not run to its end (boot.json complete None)"),
    (_complete_false, "M1", "b2: the board boot did not run to its end (boot.json complete False)"),
    (_stamp_regime_other, "M2", "b3 v2: the stamp's s_regime "),
    (_stamp_regime_other, "M4", "b3 v2: the stamp's s_regime "),
    (_stamp_pad_other, "M2", ": the stamp's qemu_pad "),
    (_stamp_fixed_pad, "M2", ": the stamp's qemu_pad '0', scheduled -"),
    (_stamp_pin_other, "M4", "b6 v3: the stamp's qemu_pin "),
    (_qemu_personality_flipped, "M2", "b2 v3 qemu r-: ADDR_NO_RANDOMIZE "),
    (_qemu_environ_off, "M2", "b4 v1 qemu r-: environ "),
    (_gpu_busy_at_the_start, "M5", "b4 v2: GR3D 37/0"),
    (_thread_off_core_in_the_settling_round, "M4", "b2 v1 r0 before: CPU 0/KVM allowed 0-2"),
    (_login_in_the_settling_round, "M6", "b3 v4 r0: accepted logins 1"),
    (_bad_samples, "M1", "b5 v2 B-bridge_r3: bad=2"),
], ids=lambda x: getattr(x, "__name__", str(x)))
def test_the_failed_check_names_what_failed(world, break_, check, detail):
    rc, out = world(null_world(), break_=break_)
    assert _check_line(out, check).rstrip().endswith("FAILED") and detail in out, out


def test_the_stamps_regime_pad_and_pin_are_their_schedule_lines(world, sched):
    """Section 4.5's "the stamps ... line for line": in the clean world every stamp carries its schedule line's
    regime, pad and pin, and M2 and M4 hold; each of the three, changed alone, fails exactly its own rows."""
    rc, out = world(null_world(), sub="clean")
    assert _check_line(out, "M1").rstrip().endswith("ok") and _check_line(out, "M2").rstrip().endswith("ok"), out
    assert _check_line(out, "M4").rstrip().endswith("ok"), out
    for break_, failed in ((_stamp_regime_other, {"M2", "M4"}), (_stamp_pad_other, {"M2"}), (_stamp_pin_other, {"M4"}),
                           (_not_complete, {"M1"})):
        rc, out = world(null_world(), break_=break_, sub=break_.__name__)
        got = {m for m in ("M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9")
               if _check_line(out, m).rstrip().endswith("FAILED")}
        assert got == failed, (break_.__name__, got)


def test_a_thread_that_slept_through_the_arm_round_is_not_off_its_core(world):
    """Its last CPU is the one it had before the pin (QEMU is pinned by name after it starts): M4 holds."""
    rc, out = world(null_world(), break_=_sleeper_stale)
    assert _check_line(out, "M4").rstrip().endswith("ok"), out


def _late_readback(kind, ctx, line):
    if kind == "readback" and ctx == {"tag": "b2", "v": 2, "r": 2, "who": "probe-C"}:
        return line.replace("t_ms=30", "t_ms=401")
    if kind == "readback" and ctx == {"tag": "b4", "v": 1, "r": 1, "who": "probe-A"}:
        return line.replace("t_ms=30", "t_ms=400")      # the earliest the warm-up can end: still inside it
    return line


def test_a_probe_read_back_past_the_warm_ups_earliest_end_is_flagged_and_voids_nothing(world):
    rc, out = world(null_world(), break_=_late_readback)
    assert _void_set(out) == set(), out
    got = [ln for ln in out.splitlines() if "probe read-backs" in ln]
    assert len(got) == 1 and "1 of 480" in got[0] and "voids nothing" in got[0], got
    assert "b2 v2 r2 probe-C t_ms=401" in out and "probe-A t_ms=400" not in out, out
    rc, out = world(null_world(), sub="clean")
    assert [ln for ln in out.splitlines() if "probe read-backs" in ln][0].split(":")[1].split()[0] == "0", out


def test_the_unscored_sections_carry_what_the_design_names(world):
    rc, out = world(null_world())
    lines = out.splitlines()
    # 7.3: the position-in-pair difference beside its two medians
    for key in ("A", "K1", "K2", "K3"):
        ln = [x for x in lines if x.lstrip().startswith("7.3 position in pair, S effect on %s:" % key)]
        assert len(ln) == 1, ln
        m = re.search(r"F first median (\S+) \(k=6\), R first median (\S+) \(k=6\), difference F first - R first (\S+)", ln[0])
        assert m and abs(float(m.group(1)) - float(m.group(2)) - float(m.group(3))) <= 0.016, ln   # three roundings to 0.01
    # U5: each QEMU thread's run time, per cell and regime
    for regime in "FR":
        for cell in rs.CELLS:
            ln = [x for x in lines if x.lstrip().startswith("U5 QEMU thread run time per arm-round, S=%s cell %s:" % (regime, cell))]
            assert len(ln) == 1 and all(c in ln[0] for c in ("qemu-system-aar", "CPU 0/KVM", "CPU 1/KVM", "worker")), ln
            assert "(n=48 arm-rounds)" in ln[0], ln
    # U6: the tail's share of variance at the board and VM levels
    for regime in "FR":
        for a in "ABCD":
            ln = [x for x in lines if x.lstrip().startswith("U6 tail variance, S=%s arm %s:" % (regime, a))]
            assert len(ln) == 1 and "p99" in ln[0] and "largest observed value" in ln[0], ln
            assert ln[0].count("board share") == 2 and ln[0].count("VM share") == 2, ln
    # 7.7: the quantile tables, below the headline
    head = out.index("predictions (")
    for regime in "FR":
        for a in "ABCD":
            ln = [x for x in lines if x.lstrip().startswith("7.7 quantiles, S=%s arm %s" % (regime, a))]
            assert len(ln) == 1 and all(q in ln[0] for q in ("min", "p50", "p90", "p99", "p99.9", "max", "k=48")), ln
            assert out.index(ln[0]) > head


# The unscored lines, one planted effect each, as test_a_vm_setup_effect_refutes_p3 does for a scored one: the
# value reported on a line is checked, not only the line's shape. Noise in the world is 0.3 us a round.

def test_a_first_in_pair_effect_is_reported_under_the_regime_that_ran_first(world):
    """7.3: the S effect of a pair, split by which regime's VM boot ran first. R's arm C is 5 us slower, but only in
    the pairs F ran first in."""
    base = null_world()

    def value(ctx):
        f_first = ctx["pattern"][(ctx["v"] - 1) // 2 * 2] == "F"
        return base(ctx) + (5.0 if ctx["arm"] == "C" and ctx["S"] == "R" and f_first else 0.0)
    rc, out = world(value)
    got = {}
    for key in ("A", "K1", "K2", "K3"):
        ln = _lines(out, "7.3 position in pair, S effect on %s:" % key)
        assert len(ln) == 1, ln
        m = re.search(r"F first median (\S+) \(k=6\), R first median (\S+) \(k=6\), difference F first - R first (\S+)", ln[0])
        got[key] = tuple(float(x) for x in m.groups())
    for key, want in (("A", (0, 0, 0)), ("K1", (5, 0, 5)), ("K2", (-5, 0, -5)), ("K3", (0, 0, 0))):
        assert got[key] == pytest.approx(want, abs=1.0), (key, got[key], want)


def test_a_first_position_effect_is_reported_at_position_one_with_the_rounds_it_came_from(world, sched):
    """U2: in the rounds whose arm order was drawn, an arm that ran first is 6 us slower. Each position's k is the
    number of such rounds in which the arm stood at that position, from the schedule."""
    base = null_world()
    rc, out = world(lambda ctx: base(ctx) + (6.0 if ctx["pos"] == 1 and ctx["O"] == "R" else 0.0))
    for a in "ABCD":
        want = [0, 0, 0, 0]
        for tag in rs.SCORED:
            for svm in sched["boots"][tag]["vms"].values():
                for r in range(1, 5):
                    rd = svm["rounds"][r]
                    if rd["O"] == "R":
                        want[rd["order"].index(a)] += 1
        ln = _lines(out, "U2 position effect, arm %s, positions 1-4:" % a)
        assert len(ln) == 1, ln
        cells = re.findall(r"(\S+) \(k=(\d+)\)", ln[0].split("positions 1-4:")[1])
        assert [int(k) for _m, k in cells] == want and all(want), (a, cells, want)
        meds = [float(m) for m, _k in cells]
        assert meds[0] > 2.0 and all(m < 1.0 for m in meds[1:]), (a, meds)


def test_a_core_zero_effect_is_reported_for_the_thread_group_that_sat_on_core_zero(world, sched):
    """U3: among the R VM boots, the one whose "rest" group sat on core 0 has arm C 6 us slower. The groups' counts
    are the schedule's (the group on core 0 is the one whose core is 0, not the core of vCPU 0)."""
    base = null_world()
    rc, out = world(lambda ctx: base(ctx) + (6.0 if ctx["arm"] == "C" and ctx["S"] == "R" and ctx["pin"].index(0) == 2 else 0.0))
    n = collections.Counter(svm["pin"].index(0) for tag in rs.SCORED for svm in sched["boots"][tag]["vms"].values()
                            if svm["S"] == "R")
    assert all(n[g] for g in range(3)), "the schedule has R VM boots for each group"
    for key, level, shift in (("K1", BASE["C"] - BASE["B"], 6.0), ("Lv", BASE["D"], 0.0)):
        ln = _lines(out, "U3 %s by the thread group on core 0" % key)
        assert len(ln) == 1, ln
        got = {g: (float(m) - level, int(c)) for g, m, c in re.findall(r"(vCPU 0|vCPU 1|the rest): (\S+) \(n=(\d+)\)", ln[0])}
        assert sorted(got) == ["the rest", "vCPU 0", "vCPU 1"], ln
        assert [got[g][1] for g in ("vCPU 0", "vCPU 1", "the rest")] == [n[0], n[1], n[2]], (key, got)
        assert got["the rest"][0] == pytest.approx(shift, abs=1.5) and abs(got["vCPU 0"][0]) < 1.5 \
            and abs(got["vCPU 1"][0]) < 1.5, (key, got)


def test_a_pad_effect_is_reported_against_the_pad_taken_mod_64(world, sched):
    """U4: arm A is slower by 2 us for each 16 bytes of its launch's pad within 64 (the pads are on a 16-byte grid,
    so a pad taken mod 16 would be the same for every launch and correlate with nothing)."""
    base = null_world()
    rc, out = world(lambda ctx: base(ctx) + (2.0 * ((ctx["pad"] % 64) // 16) if ctx["arm"] == "A" and ctx["L"] == "R" else 0.0))
    ln = _lines(out, "U4 A against E mod 64")
    assert len(ln) == 1, ln
    m = re.search(r"rank correlations (\S+), (\S+), (\S+) \(n=(\d+)\)", ln[0])
    n = sum(1 for tag in rs.SCORED for svm in sched["boots"][tag]["vms"].values() for r in range(1, 5)
            if svm["rounds"][r]["L"] == "R")
    assert int(m.group(4)) == n, ln
    assert float(m.group(1)) > 0.6, ln


def test_the_board_hooks_and_the_label_are_the_harness_and_library_defaults():
    assert rr.BOARD_HOOKS == HOOKS
    lib = open(os.path.join(GC, "lib-measure.sh"), encoding="utf-8").read()
    har = open(os.path.join(GC, "run-randomise.sh"), encoding="utf-8").read()
    assert 'EMC_BPMP_DEFAULT="%s"' % HOOKS["emc_bpmp"] in lib and 'EMC_CCF_DEFAULT="%s"' % HOOKS["emc_ccf"] in lib
    assert 'SYSFS_CPU_DEFAULT="%s"' % HOOKS["sysfs_cpu"] in lib
    assert 'KVM_DEBUGFS="${KVM_DEBUGFS:-%s}"' % HOOKS["kvm_debugfs"] in lib
    assert 'PSTORE_VAR="${PSTORE_VAR:-%s}"' % HOOKS["pstore_var"] in har
    assert "${SYS_ROOT:-/sys}/devices/platform/bus@0/c360000.pmc/reset_reason" in har
    assert "kernel " + rr.LABEL_KERNEL in rr.LABEL and "QEMU " + rr.LABEL_QEMU in rr.LABEL and "L4T " + rr.LABEL_L4T in rr.LABEL


def test_up_to_five_percent_of_flagged_emc_reads_are_kept_and_voids_nothing(world):
    rc, out = world(null_world(), break_=_emc(19))       # 19 of 384 is under 5%
    assert _void_set(out) == set(), out
    assert "19 of 384" in out


def test_a_schedule_that_is_not_the_committed_one_voids_everything(world):
    rc, out = world(null_world(), sha_in_records="f" * 64)
    assert _void_set(out) == ALL, out


def test_the_committed_hash_against_the_file_itself(world, monkeypatch):
    monkeypatch.setattr(rr, "SCHEDULE_SHA256", "e" * 64)
    rc, out = world(null_world())
    assert _void_set(out) == ALL and "M9" in out


def test_a_schedule_file_whose_bytes_are_not_the_committed_ones_voids_everything(tmp_path, sched, sched_text,
                                                                                 monkeypatch):
    """The records all name the committed schedule; only the file given to the report differs (in its
    master seed line, which parses alike): M9 reads the file itself."""
    sha = rs.sha256(sched_text)
    monkeypatch.setattr(rr, "SCHEDULE_SHA256", sha)
    dirs = write_records(tmp_path / "run", sched, sha, rs.SCORED, null_world())
    p = tmp_path / "other.txt"
    p.write_text(sched_text.replace("master_seed %d\n" % SEED, "master_seed %d\n" % (SEED + 1), 1))
    assert rs.parse(p.read_text())["boots"] == sched["boots"]
    rc, out = _report(dirs, p)
    assert _void_set(out) == ALL, out
    assert "the schedule file's sha256 is not the committed one" in out


def test_fewer_than_six_board_boots_are_not_scored(world):
    rc, out = world(null_world(), tags=rs.SCORED[:5])
    assert rc == 0 and "not scored" in out, out
    assert not _lines(out, "P1 ") and not _lines(out, "P4"), out


def test_the_unscored_sections_are_printed_and_say_so(world):
    rc, out = world(null_world())
    for u in ("U1", "U2", "U3", "U4", "U5", "U6", "U7", "U8"):
        assert any(ln.lstrip().startswith(u) for ln in out.splitlines()), (u, out)
    assert "unscored" in out.lower()
    assert "interaction" in out and "position in pair" in out and "split by S pattern" in out


def test_the_one_boot_summary_names_its_rounds_and_scores_nothing(tmp_path, sched, sched_text, monkeypatch):
    p = tmp_path / "schedule.txt"
    p.write_text(sched_text)
    monkeypatch.setattr(rr, "SCHEDULE_SHA256", rs.sha256(sched_text))
    d = write_records(tmp_path / "one", sched, rs.sha256(sched_text), ["b0"], null_world())[0]
    rc, out = _report([d], p, extra=["--one"])
    assert rc == 0, out
    assert "b0" in out and "smoke" in out and "never scored" in out
    assert "HELD" not in out and "REFUTED" not in out
    assert len([ln for ln in out.splitlines() if ln.lstrip().startswith("v1 r")]) == 2


def test_a_report_refuses_a_directory_that_is_not_a_board_boot(tmp_path, sched_text):
    p = tmp_path / "schedule.txt"
    p.write_text(sched_text)
    (tmp_path / "x").mkdir()
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = rr.main(["--schedule", str(p), str(tmp_path / "x")])
    assert rc == 2


def test_constants_name_the_committed_schedule():
    assert rr.MASTER_SEED == 979784927940495478
    assert len(rr.SCHEDULE_SHA256) == 64 and int(rr.SCHEDULE_SHA256, 16) >= 0
    assert rs.sha256(rs.generate(rr.MASTER_SEED)) == rr.SCHEDULE_SHA256
    assert math.isclose(rr.P4_THRESHOLD, 0.5) and rr.UNDEFINED_MAX == 0.10 and rr.EMC_FLAG_MAX == 0.05
