"""The setup-randomisation schedule (Phase 3b / A6, 2026-10-17): randomise_schedule.py draws every
randomised factor of run-randomise.sh from one master seed, before any run, and writes them to one
file whose sha256 is committed with the harness's header. The harness only executes that file.

These tests hold the generator to the design: the hierarchy and counts (six scored board boots of
four VM boots, a smoke boot of two), the S patterns, the cells in a drawn order, the fixed settling
round, the F and R levels of every factor, the environment sizes the read-backs are compared with,
and a stream that does not depend on the Python version. Nothing here needs a board.
"""
import collections
import hashlib
import itertools
import os
import re
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
sys.path.insert(0, GC)
import randomise_schedule as rs  # noqa: E402

GEN = os.path.join(GC, "randomise_schedule.py")
SEEDS = (1, 2, 3, 77, 4321)


def _sched(seed=1):
    return rs.parse(rs.generate(seed))


def _scored_vms(s):
    for tag in rs.SCORED:
        for v, vm in sorted(s["boots"][tag]["vms"].items()):
            yield tag, v, vm


# ------------------------------------------------------------------ the stream

def test_the_same_seed_gives_the_same_bytes_and_another_seed_other_draws():
    a, b, c = rs.generate(5), rs.generate(5), rs.generate(6)
    assert a == b
    assert a != c
    assert a.endswith("\n") and "\r" not in a


def test_the_stream_uses_random_alone_so_no_python_version_changes_it():
    """random() is the one method Python promises to keep reproducible for a given seed; randrange,
    choice, shuffle and sample may change their algorithm between versions. The schedule is drawn
    on one machine and its hash checked on another."""
    src = open(GEN, encoding="utf-8").read()
    for word in ("shuffle(", "choice(", "choices(", "randrange(", "randint(", "sample(", "getrandbits(",
                 "secrets", "os.urandom", "time.time"):
        assert word not in src, word
    assert "random.Random(" in src


def test_randbelow_and_the_permutation_are_uniform_over_their_range():
    r = rs._Stream(9)
    got = collections.Counter(r.below(6) for _ in range(6000))
    assert set(got) == set(range(6)) and min(got.values()) > 800
    perms = collections.Counter(tuple(r.permutation("ABCD")) for _ in range(4800))
    assert len(perms) == 24 and min(perms.values()) > 120


# ------------------------------------------------------------------ the hierarchy and counts

@pytest.mark.parametrize("seed", SEEDS)
def test_six_scored_board_boots_of_four_vm_boots_and_a_smoke_boot_of_two(seed):
    s = _sched(seed)
    assert list(s["boots"]) == ["b0", "b1", "b2", "b3", "b4", "b5", "b6"]
    assert s["boots"]["b0"]["kind"] == "smoke" and sorted(s["boots"]["b0"]["vms"]) == [1, 2]
    for tag in rs.SCORED:
        b = s["boots"][tag]
        assert b["kind"] == "scored" and sorted(b["vms"]) == [1, 2, 3, 4]
        for vm in b["vms"].values():
            assert sorted(vm["rounds"]) == [0, 1, 2, 3, 4]
    for vm in s["boots"]["b0"]["vms"].values():
        assert sorted(vm["rounds"]) == [0, 1, 2]


@pytest.mark.parametrize("seed", SEEDS)
def test_the_s_patterns_alternate_from_a_drawn_first_one(seed):
    s = _sched(seed)
    first = s["first_pattern"]
    assert first in ("FRRF", "RFFR")
    other = "RFFR" if first == "FRRF" else "FRRF"
    for i, tag in enumerate(rs.SCORED):
        b = s["boots"][tag]
        assert b["pattern"] == (first if i % 2 == 0 else other)
        assert "".join(b["vms"][v]["S"] for v in (1, 2, 3, 4)) == b["pattern"]
    smoke = s["boots"]["b0"]
    assert smoke["pattern"] in ("FR", "RF")
    assert "".join(smoke["vms"][v]["S"] for v in (1, 2)) == smoke["pattern"]


def test_both_first_patterns_and_both_smoke_patterns_are_drawn_over_seeds():
    firsts = {_sched(seed)["first_pattern"] for seed in range(40)}
    smokes = {_sched(seed)["boots"]["b0"]["pattern"] for seed in range(40)}
    assert firsts == {"FRRF", "RFFR"} and smokes == {"FR", "RF"}


@pytest.mark.parametrize("seed", SEEDS)
def test_the_totals_the_design_counts(seed):
    s = _sched(seed)
    vms = list(_scored_vms(s))
    assert len(vms) == 24
    assert collections.Counter(vm["S"] for _t, _v, vm in vms) == {"F": 12, "R": 12}
    cells = collections.Counter(vm["rounds"][r]["cell"] for _t, _v, vm in vms for r in (1, 2, 3, 4))
    assert cells == {"FF": 24, "FR": 24, "RF": 24, "RR": 24}
    fixed = sum(1 for _t, _v, vm in vms for r in (1, 2, 3, 4) if vm["S"] == "F" and vm["rounds"][r]["cell"] == "FF")
    assert fixed == 12


@pytest.mark.parametrize("seed", SEEDS)
def test_every_vm_boot_runs_each_cell_once_in_a_drawn_order(seed):
    s = _sched(seed)
    orders = set()
    for _t, _v, vm in _scored_vms(s):
        assert sorted(vm["cells"]) == sorted(rs.CELLS)
        assert [vm["rounds"][r]["cell"] for r in (1, 2, 3, 4)] == vm["cells"]
        orders.add(tuple(vm["cells"]))
    assert len(orders) > 6, "the cell order is drawn, not fixed"
    for vm in s["boots"]["b0"]["vms"].values():
        assert len(set(vm["cells"])) == 2 and set(vm["cells"]) <= set(rs.CELLS)
        assert [vm["rounds"][r]["cell"] for r in (1, 2)] == vm["cells"]


@pytest.mark.parametrize("seed", SEEDS)
def test_the_cell_names_its_two_levels(seed):
    for _t, _v, vm in _scored_vms(_sched(seed)):
        for r in (1, 2, 3, 4):
            rd = vm["rounds"][r]
            assert rd["O"] + rd["L"] == rd["cell"]


# ------------------------------------------------------------------ the settling round

@pytest.mark.parametrize("seed", SEEDS)
def test_the_settling_round_is_fixed_in_order_and_layout(seed):
    s = _sched(seed)
    for tag in ("b0",) + rs.SCORED:
        for vm in s["boots"][tag]["vms"].values():
            r0 = vm["rounds"][0]
            assert r0["cell"] == "settle" and r0["O"] == "F" and r0["L"] == "F"
            assert r0["order"] == list(rs.ARMS)
            for who in ("host", "ns"):
                assert r0["mon"][who]["norand"] == 1 and r0["mon"][who]["pad"] is None
            for arm in rs.ARMS:
                p = r0["probe"][arm]
                assert p["norand"] == 1 and p["pad"] is None and p["hashseed"] == 0


# ------------------------------------------------------------------ the factors' levels

@pytest.mark.parametrize("seed", SEEDS)
def test_arm_order_is_the_ladders_when_fixed_and_a_permutation_when_random(seed):
    perms = set()
    for _t, _v, vm in _scored_vms(_sched(seed)):
        for r in (1, 2, 3, 4):
            rd = vm["rounds"][r]
            if rd["O"] == "F":
                assert rd["order"] == ["A", "B", "C", "D"]
            else:
                assert sorted(rd["order"]) == ["A", "B", "C", "D"]
                perms.add(tuple(rd["order"]))
    assert len(perms) > 8


@pytest.mark.parametrize("seed", SEEDS)
def test_layout_launches_are_fixed_or_padded_with_a_drawn_hash_seed(seed):
    seen_pads, seen_seeds = set(), set()
    for _t, _v, vm in _scored_vms(_sched(seed)):
        for r in (1, 2, 3, 4):
            rd = vm["rounds"][r]
            launches = [rd["mon"]["host"], rd["mon"]["ns"]] + [rd["probe"][a] for a in rs.ARMS]
            for la in launches:
                if rd["L"] == "F":
                    assert la["norand"] == 1 and la["pad"] is None
                else:
                    assert la["norand"] == 0 and la["pad"] in rs.PADS
                    seen_pads.add(la["pad"])
            for a in rs.ARMS:
                hs = rd["probe"][a]["hashseed"]
                if rd["L"] == "F":
                    assert hs == 0
                else:
                    assert 0 <= hs < 2 ** 32
                    seen_seeds.add(hs)
            assert "hashseed" not in rd["mon"]["host"] and "hashseed" not in rd["mon"]["ns"]
    assert len(seen_pads) > 20 and len(seen_seeds) > 100


def test_pads_are_the_designs_grid():
    assert rs.PADS == tuple(range(0, 4081, 16)) and len(rs.PADS) == 256


@pytest.mark.parametrize("seed", SEEDS)
def test_the_vm_setup_is_fixed_or_a_drawn_permutation_with_a_pad(seed):
    pins = set()
    for _t, _v, vm in _scored_vms(_sched(seed)):
        if vm["S"] == "F":
            assert vm["norand"] == 1 and vm["pad"] is None and vm["pin"] == (1, 2, 0)
        else:
            assert vm["norand"] == 0 and vm["pad"] in rs.PADS
            assert sorted(vm["pin"]) == [0, 1, 2]
            pins.add(vm["pin"])
    assert pins, "twelve R VM boots draw at least one permutation"


def test_r_vm_boots_draw_every_one_of_the_six_permutations_over_seeds():
    pins = set()
    for seed in range(30):
        for _t, _v, vm in _scored_vms(_sched(seed)):
            if vm["S"] == "R":
                pins.add(vm["pin"])
    assert pins == set(itertools.permutations((0, 1, 2)))


# ------------------------------------------------------------------ environment sizes

def test_the_fixed_environment_and_its_size_by_hand():
    assert rs.FIXED_ENV == ("PATH=/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL=C")
    fixed = len("PATH=/usr/sbin:/usr/bin:/sbin:/bin") + 1 + len("LC_ALL=C") + 1
    assert rs.env_bytes(rs.launch_env(None)) == fixed
    assert rs.env_bytes(rs.launch_env(None, hashseed=0)) == fixed + len("PYTHONHASHSEED=0") + 1
    assert rs.env_bytes(rs.launch_env(0)) == fixed + len("A6PAD=") + 1
    assert rs.env_bytes(rs.launch_env(4080, hashseed=4294967295)) == \
        fixed + len("A6PAD=") + 4080 + 1 + len("PYTHONHASHSEED=4294967295") + 1


def test_a_pad_is_that_many_bytes_of_one_letter():
    env = rs.launch_env(32, hashseed=7)
    assert env == ["PATH=/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL=C", "PYTHONHASHSEED=7", "A6PAD=" + "x" * 32]


@pytest.mark.parametrize("seed", SEEDS)
def test_every_launch_states_the_size_of_its_environment(seed):
    s = _sched(seed)
    for tag in ("b0",) + rs.SCORED:
        for vm in s["boots"][tag]["vms"].values():
            assert vm["env"] == rs.env_bytes(rs.launch_env(vm["pad"]))
            for rd in vm["rounds"].values():
                for who in ("host", "ns"):
                    m = rd["mon"][who]
                    assert m["env"] == rs.env_bytes(rs.launch_env(m["pad"]))
                for a in rs.ARMS:
                    p = rd["probe"][a]
                    assert p["env"] == rs.env_bytes(rs.launch_env(p["pad"], hashseed=p["hashseed"]))


# ------------------------------------------------------------------ the file

def test_the_header_lines_and_the_bootstrap_seed():
    text = rs.generate(11)
    lines = text.split("\n")
    assert lines[0] == "a6-randomise-schedule 1"
    assert lines[1] == "master_seed 11"
    assert re.fullmatch(r"bootstrap_seed \d+", lines[2])
    assert lines[3] == "env PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C"
    s = rs.parse(text)
    assert s["master_seed"] == 11 and 0 <= s["bootstrap_seed"] < 2 ** 32


def test_the_lines_the_harness_greps_have_one_fixed_shape():
    text = rs.generate(3)
    shapes = {
        "boot": r"boot b[0-6] (smoke|scored) [FR]+",
        "vm": r"vm b[0-6] v[1-4] S=[FR] norand=[01] pad=(-|\d+) env=\d+ pin=[0-2],[0-2],[0-2] cells=[FR]{2}(,[FR]{2})*",
        "round": r"round b[0-6] v[1-4] r[0-4] cell=(settle|[FR]{2}) O=[FR] L=[FR] order=[A-D],[A-D],[A-D],[A-D]",
        "mon": r"mon b[0-6] v[1-4] r[0-4] (host|ns) norand=[01] pad=(-|\d+) env=\d+",
        "probe": r"probe b[0-6] v[1-4] r[0-4] [A-D] norand=[01] pad=(-|\d+) hashseed=\d+ env=\d+",
    }
    counts = collections.Counter()
    for line in text.split("\n")[5:]:
        if not line:
            continue
        kind = line.split(" ", 1)[0]
        assert kind in shapes, line
        assert re.fullmatch(shapes[kind], line), line
        counts[kind] += 1
    assert counts == {"boot": 7, "vm": 26, "round": 2 * 3 + 24 * 5, "mon": 2 * (2 * 3 + 24 * 5),
                      "probe": 4 * (2 * 3 + 24 * 5)}


@pytest.mark.parametrize("edit,why", [
    (lambda t: t.replace("a6-randomise-schedule 1", "a6-randomise-schedule 2"), "format"),
    (lambda t: t.replace("env PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C", "env PATH=/usr/bin LC_ALL=C"), "env"),
    (lambda t: t + "extra line\n", "unknown"),
    (lambda t: t.replace("\nboot b3 ", "\nboot b9 ", 1), "boot"),
    (lambda t: re.sub(r"(\nprobe b2 v1 r1 A norand=\d pad=\S+ hashseed=\d+ env=)(\d+)",
                      lambda m: m.group(1) + str(int(m.group(2)) + 1), t, count=1), "env="),
    (lambda t: re.sub(r"\nmon b4 v2 r3 ns [^\n]*", "", t, count=1), "missing"),
    (lambda t: re.sub(r"(\nround b1 v1 r1 [^\n]*)", r"\1\1", t, count=1), "twice"),
    # defence in depth: the harness re-derives the file byte for byte, and parse refuses these on its own
    pytest.param(lambda t: re.sub(r"(\nvm b\d v\d S=R [^\n]*? pin=)\d,\d,\d", r"\g<1>0,0,1", t, count=1), "pin",
                 id="pin-not-a-permutation"),
    pytest.param(lambda t: re.sub(r"(\nround b\d v\d r[1-4] cell=FF )O=F", r"\1O=R", t, count=1), "cell",
                 id="cell-not-its-levels"),
    pytest.param(lambda t: re.sub(r"(\nvm b\d v\d S=F [^\n]*? pin=)1,2,0", r"\g<1>0,1,2", t, count=1), "fpin",
                 id="f-pin-not-the-fixed-one"),
])
def test_parse_refuses_a_file_that_is_not_a_schedule_it_wrote(edit, why):
    text = rs.generate(4)
    assert edit(text) != text, "the edit applied"
    with pytest.raises(ValueError):
        rs.parse(edit(text))


def test_parse_refuses_a_pad_off_the_grid_even_when_its_environment_size_is_right():
    """The size a launch states would catch a pad off the grid by the size that pad implies; here the size is the one
    that pad would give, so only the grid refuses. (The harness re-derives the file byte for byte; parse holds this
    on its own.)"""
    text = rs.generate(4)
    m = re.search(r"\n(mon b\d v\d r\d host) norand=0 pad=(\d+) env=\d+", text)
    pad = int(m.group(2)) + 1
    assert pad not in rs.PADS
    edited = text.replace(m.group(0), "\n%s norand=0 pad=%d env=%d" % (m.group(1), pad, rs.env_bytes(rs.launch_env(pad))), 1)
    assert edited != text
    with pytest.raises(ValueError, match="not a pad of the grid"):
        rs.parse(edited)
    assert rs.parse(text)


@pytest.mark.parametrize("layout", ["F", "R"])
def test_parse_refuses_a_launch_of_the_other_layout_than_its_rounds(layout):
    """A monitor launch that is fixed in a round whose launches are random, or random in a fixed one, with a pad on the
    grid and the environment size that goes with it, so that only the round's L disagrees."""
    text = rs.generate(4)
    rounds = [(tag, v, r) for tag, b in rs.parse(text)["boots"].items() for v, vm in b["vms"].items()
              for r, rd in vm["rounds"].items() if rd["L"] == layout]
    assert rounds
    tag, v, r = rounds[0]
    other = ("norand=0 pad=0 env=%d" % rs.env_bytes(rs.launch_env(0))) if layout == "F" \
        else ("norand=1 pad=- env=%d" % rs.env_bytes(rs.launch_env(None)))
    edited = re.sub(r"\n(mon %s v%d r%d host) norand=\d pad=\S+ env=\d+" % (tag, v, r), lambda m: "\n%s %s" % (m.group(1), other),
                    text, count=1)
    assert edited != text
    with pytest.raises(ValueError, match="does not follow its round's L"):
        rs.parse(edited)


def test_the_command_line_writes_and_verifies(tmp_path):
    out = tmp_path / "schedule.txt"
    r = subprocess.run([sys.executable, GEN, "--seed", "21", "--out", str(out)], capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0, r.stderr
    raw = out.read_bytes()
    assert raw == rs.generate(21).encode() and b"\r" not in raw
    want = hashlib.sha256(raw).hexdigest()
    assert want in r.stdout
    v = subprocess.run([sys.executable, GEN, "--verify", str(out)], capture_output=True, text=True, timeout=60)
    assert v.returncode == 0 and want in v.stdout, v.stdout + v.stderr
    out.write_bytes(raw.replace(b"master_seed 21", b"master_seed 22", 1))
    v = subprocess.run([sys.executable, GEN, "--verify", str(out)], capture_output=True, text=True, timeout=60)
    assert v.returncode != 0 and "does not re-derive" in v.stderr, v.stdout + v.stderr


def test_the_command_line_refuses_an_existing_file_and_a_bad_seed(tmp_path):
    out = tmp_path / "s.txt"
    out.write_text("x")
    r = subprocess.run([sys.executable, GEN, "--seed", "3", "--out", str(out)], capture_output=True, text=True,
                       timeout=60)
    assert r.returncode != 0 and out.read_text() == "x"
    r = subprocess.run([sys.executable, GEN, "--seed", "-3"], capture_output=True, text=True, timeout=60)
    assert r.returncode != 0
