"""`make ctl`: the kind 2 (ctl) monitor's qcc build (SDV plan Phase 8, WP1b; the Phase 8 specification spec-2.md, section 3
item 4, and 2.1's name; the project's local design notes, not in this tree).

ipc-test/qnx-safety-monitor/Makefile gains `make ctl`, which builds qnx-safety-monitor-ctl (already in .gitignore) with
the vss recipe's flags but MONITOR_EXT_KINDS=0x14 and the generated contract from CTL_GEN (default the in-tree
sdv-out/gen that sdv/vss/generate.py writes). The image it is for judges kinds 2 and 4 with kind 4's profile 4, so the
recipe stops before any compiler runs when vss_ctl.h, vss_contract.h or vss_profiles.h is missing from CTL_GEN, when
vss_profiles.h holds no X() row for profile 4 or vss_ctl.h none for kind 2's profile 1 (the words "X(4u," and "X(1u," as
the generator writes its tables), and when a copy of any of the three beside monitor.c or in ../common would be compiled
instead of CTL_GEN's (a quoted include looks there first: vss-carla's guard). Every other recipe, `make clean` included,
is textually what it was.

Held here on synthetic generations in a temporary copy of what the Makefile reads, with `make -n`, `make -q` and a
compiler stand-in that leaves a mark and fails (Phase 7's _fake_cc pattern), so qcc never runs (it cannot in WSL or CI):
the planned line exactly, with and without -B, from CTL_GEN given on the command line or in the environment; each missing
header naming CTL_GEN and the generator; the row-4 and row-1 guards against tables without the row, with it under
another id, or listing it only in the ids string; the stray headers; `make -q` seeing each input; the default recipes,
the vss and vss-carla rules and clean textually unchanged; the binary ignored and left by clean; and, against this
tree's own generation, a plan exactly when it compiles both rows.

`make ctl-p5` (SDV plan Phase 8.5, WP9c; the project's local design notes, not in this tree) builds
qnx-safety-monitor-p5 for
ifs-ctl-p5.build with ctl's flags exactly (MONITOR_EXT_KINDS=0x14) and the contract from its own knob, CTL_P5_GEN (default
the same in-tree sdv-out/gen): the image it is for judges kind 4's profile 5, the CARLA 0.10.0 taxi, so its recipe stops
before any compiler runs when vss_profiles.h holds no X() row for profile 5 ("X(5u,") or vss_ctl.h none for kind 2's
profile 1, on a missing header (naming CTL_P5_GEN) and on a stray one, as ctl's does. Held here the same way, case for
case, beside ctl's tests; and that ctl's rules and targets are textually what they were, ctl-p5's .PHONY line and alias
are its own, CTL_P5_GEN moves no other target and CTL_GEN never moves ctl-p5, the p5 binary is ignored after ctl's and
left by clean, the make command ifs-ctl-p5.build's header gives (with -B) meets the guards on an up-to-date binary, and,
against this tree's generation, a plan exactly when the generator's COMPILED_PROFILE_IDS hold profile 5 (until WP3c F-c
compiled it, the row-5 guard refused it; this generation passes it).

`make lane` (SDV Phase 9, C2b LB; the project's local design notes, not in this tree) builds qnx-safety-monitor-lane
for ifs-lane.build with
ctl-p5's recipe but MONITOR_EXT_KINDS=0x54 (kinds 2, 4 and 6), the contract from its own knob, LANE_GEN (default the same
in-tree sdv-out/gen), and ctl-p5's guards: profile 5's row and kind 2's profile 1 row, a missing header (naming LANE_GEN)
and a stray one. Held here the same way, case for case, beside ctl-p5's tests; and that ctl-p5's rules are textually what
they were, lane's .PHONY line and alias are its own, LANE_GEN moves no other target and no other knob moves lane, the lane
binary is ignored after the p5 one and left by clean, no "!" line of .gitignore (git's backslash escapes read, and one
with no '/' matched by basename, as git does) and no .gitignore under ipc-test/ un-ignores the p5 or the lane binary
(WP9c's critic, mutants c24 and c25; LB's critic, cr2 and cr3), the make command ifs-lane.build's header gives meets the
guards on an up-to-date binary, and, against this tree's generation, a plan exactly when profile 5 is compiled. And
sdv/stack/README.md's guest-mode sentence names the build file of every row of stack.py's GUEST_IMAGE_BUILDS for its
image, ifs-lane.build for ifs-lane.bin among them, and no other (LB's critic#2, its text held since C2b NIT package 5).

What this does NOT show: anything about the qcc build or the guest binary (nothing here runs qcc, and 4.6(c) forbids taking
the guest binary apart), that the guest judges kind 2 (WP5's image and its board session), profile 5 (ifs-ctl-p5.bin)
or kind 6 (ifs-lane.bin), or that the generation's values are right
(tests/test_sdv_vss_ctl.py holds them to the specification).
Needs GNU make on Linux (WSL, CI's tooling job).
"""
import ast
import fnmatch
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
MON_DIR = REPO / "ipc-test" / "qnx-safety-monitor"
MAKEFILE = MON_DIR / "Makefile"
GEN = REPO / "sdv-out" / "gen"
HEADERS = ("vss_contract.h", "vss_profiles.h", "vss_ctl.h")
GENERATOR = "sdv/vss/generate.py"
REQUIRE_ENV = "SDV_REQUIRE_GEN"

QCC = "qcc -Vgcc_ntoaarch64le -std=gnu99 -Wall -Wextra -Wformat=2 -O2 -I../common"
CTL_BIN = "qnx-safety-monitor-ctl"
VSS_BIN = "qnx-safety-monitor-vss"
VSS_CARLA_BIN = "qnx-safety-monitor-carla"
CTL_LINE = (QCC + " -ffp-contract=off -DMONITOR_EXT_KINDS=0x14 -I../../sdv-out/gen -o " + CTL_BIN
            + " monitor.c ../common/shm_map_qnx.c -lsocket")
VSS_LINE = (QCC + " -ffp-contract=off -DMONITOR_EXT_KINDS=0x10 -I../../sdv-out/gen -o " + VSS_BIN
            + " monitor.c ../common/shm_map_qnx.c -lsocket")
VSS_CARLA_LINE = VSS_LINE.replace(" -o %s " % VSS_BIN, " -o %s " % VSS_CARLA_BIN)
CTL_RECIPE = ("\t$(CC) $(TARGET) $(CFLAGS) -ffp-contract=off -DMONITOR_EXT_KINDS=0x14 -I$(CTL_GEN) -o $@ monitor.c "
              "../common/shm_map_qnx.c $(LDFLAGS)")
ROW4_ERROR = "holds no kind 4 profile 4"
ROW1_ERROR = "holds no kind 2 profile 1"
SHADOW_ERROR = "would be compiled instead of the contract in"
KNOB = "or point CTL_GEN at"
CLEAN_SENTENCE = "`make clean` does not remove the binary"
# WP9c's ctl-p5: ctl's line and recipe under its own name and its own contract knob.
P5_BIN = "qnx-safety-monitor-p5"
P5_LINE = CTL_LINE.replace(" -o %s " % CTL_BIN, " -o %s " % P5_BIN)
P5_RECIPE = CTL_RECIPE.replace(" -I$(CTL_GEN) ", " -I$(CTL_P5_GEN) ")
P5_K4 = (1, 2, 3, 4, 5)
ROW5_ERROR = "holds no kind 4 profile 5"
P5_KNOB = "or point CTL_P5_GEN at"
# C2b LB's lane: ctl-p5's line and recipe with the lane switch value, 0x54, under its own name and its own contract knob.
LANE_BIN = "qnx-safety-monitor-lane"
LANE_LINE = P5_LINE.replace("-DMONITOR_EXT_KINDS=0x14 ", "-DMONITOR_EXT_KINDS=0x54 ").replace(" -o %s " % P5_BIN, " -o %s " % LANE_BIN)
LANE_RECIPE = P5_RECIPE.replace("-DMONITOR_EXT_KINDS=0x14 -I$(CTL_P5_GEN) ", "-DMONITOR_EXT_KINDS=0x54 -I$(LANE_GEN) ")
LANE_KNOB = "or point LANE_GEN at"

# The six default recipes, the vss rules and the vss-carla rules as the Makefile had them at this package's base,
# and its CFLAGS and clean lines: textually unchanged by `make ctl`.
DEFAULT_RULES = """$(BIN): $(SRCS)
\t$(CC) $(TARGET) $(CFLAGS) -o $@ monitor.c ../common/shm_map_qnx.c $(LDFLAGS)

$(SVC): $(SRCS)
\t$(CC) $(TARGET) $(CFLAGS) -o $@ monitor.c ../common/shm_map_qnx.c $(LDFLAGS)

$(LIVE): $(SRCS)
\t$(CC) $(TARGET) $(CFLAGS) -o $@ monitor.c ../common/shm_map_qnx.c $(LDFLAGS)

$(STAMP): $(SRCS)
\t$(CC) $(TARGET) $(CFLAGS) -o $@ monitor.c ../common/shm_map_qnx.c $(LDFLAGS)

$(BELL): $(SRCS)
\t$(CC) $(TARGET) $(CFLAGS) -o $@ monitor.c ../common/shm_map_qnx.c $(LDFLAGS)

$(UNMASK): $(SRCS)
\t$(CC) $(TARGET) $(CFLAGS) -o $@ monitor.c ../common/shm_map_qnx.c $(LDFLAGS)
"""
VSS_RULES = """$(VSS): $(SRCS) $(VSS_GEN)/vss_contract.h $(VSS_GEN)/vss_profiles.h
\t$(CC) $(TARGET) $(CFLAGS) -ffp-contract=off -DMONITOR_EXT_KINDS=0x10 -I$(VSS_GEN) -o $@ monitor.c ../common/shm_map_qnx.c $(LDFLAGS)
"""
VSS_HEADER_RULE = """$(VSS_GEN)/vss_contract.h $(VSS_GEN)/vss_profiles.h:
\t$(if $(wildcard $@),,$(error $@ is missing: generate the kind 4 contract with sdv/vss/generate.py (sdv/vss/README.md), \
or point VSS_GEN at its output))
"""
VSS_CARLA_RULES = """$(VSS_CARLA): $(SRCS) $(VSS_CARLA_GEN)/vss_contract.h $(VSS_CARLA_GEN)/vss_profiles.h
\t$(if $(filter $(VSS_CARLA_ROW3),$(file <$(VSS_CARLA_GEN)/vss_profiles.h)),,$(error $(VSS_CARLA_NO_ROW3)))
\t$(if $(VSS_CARLA_STRAY),$(error $(VSS_CARLA_SHADOW)))
\t$(CC) $(TARGET) $(CFLAGS) -ffp-contract=off -DMONITOR_EXT_KINDS=0x10 -I$(VSS_CARLA_GEN) -o $@ monitor.c ../common/shm_map_qnx.c $(LDFLAGS)

# The headers' rule above serves vss-carla too while VSS_CARLA_GEN is VSS_GEN
# (both default to the in-tree output root); a second rule for the same files
# would override it. Pointed elsewhere, vss-carla's headers get their own. In
# the default case, when the command line names vss-carla or its binary, the
# headers are checked as the makefile is read, so a missing one names
# VSS_CARLA_GEN, the knob vss-carla reads; vss's message, naming VSS_GEN, stays.
ifneq ($(VSS_CARLA_GEN),$(VSS_GEN))
$(VSS_CARLA_GEN)/vss_contract.h $(VSS_CARLA_GEN)/vss_profiles.h:
\t$(if $(wildcard $@),,$(error $@ $(VSS_CARLA_MISSING)))
else ifneq ($(filter vss-carla $(VSS_CARLA),$(MAKECMDGOALS)),)
$(foreach h,vss_contract.h vss_profiles.h,$(if $(wildcard $(VSS_CARLA_GEN)/$(h)),,$(error $(VSS_CARLA_GEN)/$(h) $(VSS_CARLA_MISSING))))
endif
"""
# ctl's rules, its .PHONY line and the targets' aliases as the Makefile had them at WP9c's base: textually unchanged by
# `make ctl-p5`, which has a .PHONY line and an alias of its own.
CTL_RULES = """$(CTL): $(SRCS) $(CTL_GEN)/vss_contract.h $(CTL_GEN)/vss_profiles.h $(CTL_GEN)/vss_ctl.h
\t$(if $(filter $(CTL_ROW4),$(file <$(CTL_GEN)/vss_profiles.h)),,$(error $(CTL_NO_ROW4)))
\t$(if $(filter $(CTL_ROW1),$(file <$(CTL_GEN)/vss_ctl.h)),,$(error $(CTL_NO_ROW1)))
\t$(if $(CTL_STRAY),$(error $(CTL_SHADOW)))
""" + CTL_RECIPE + """

# ctl's three headers are checked as the makefile is read whenever the command
# line names ctl or its binary, so a missing one names CTL_GEN wherever it
# points; vss_ctl.h has no rule, and vss's or vss-carla's rule for the other
# two is never redefined here.
ifneq ($(filter ctl $(CTL),$(MAKECMDGOALS)),)
$(foreach h,$(CTL_HEADERS),$(if $(wildcard $(CTL_GEN)/$(h)),,$(error $(CTL_GEN)/$(h) $(CTL_MISSING))))
endif
"""
# ctl-p5's rule line and its four recipe lines as the Makefile has them: ctl's, with ctl-p5's own names.
P5_RULES = CTL_RULES.split("\n\n")[0].replace("$(CTL):", "$(CTL_P5):").replace("$(CTL_GEN)", "$(CTL_P5_GEN)").replace(
    "$(CTL_ROW4)", "$(CTL_P5_ROW5)").replace("$(CTL_NO_ROW4)", "$(CTL_P5_NO_ROW5)").replace(
    "$(CTL_NO_ROW1)", "$(CTL_P5_NO_ROW1)").replace("$(CTL_STRAY)", "$(CTL_P5_STRAY)").replace(
    "$(CTL_SHADOW)", "$(CTL_P5_SHADOW)") + "\n"
# ctl-p5's parse-time check as the Makefile had it at C2b LB's base: textually unchanged by `make lane`.
P5_PARSE_CHECK = """ifneq ($(filter ctl-p5 $(CTL_P5),$(MAKECMDGOALS)),)
$(foreach h,$(CTL_HEADERS),$(if $(wildcard $(CTL_P5_GEN)/$(h)),,$(error $(CTL_P5_GEN)/$(h) $(CTL_P5_MISSING))))
endif
"""
# lane's rule line and its four recipe lines: ctl-p5's, with lane's own names and switch value (the two row words are
# ctl-p5's, CTL_P5_ROW5 and ctl's CTL_ROW1).
LANE_RULES = P5_RULES.replace("$(CTL_P5):", "$(LANE):").replace("$(CTL_P5_GEN)", "$(LANE_GEN)").replace(
    "$(CTL_P5_NO_ROW5)", "$(LANE_NO_ROW5)").replace("$(CTL_P5_NO_ROW1)", "$(LANE_NO_ROW1)").replace(
    "$(CTL_P5_STRAY)", "$(LANE_STRAY)").replace("$(CTL_P5_SHADOW)", "$(LANE_SHADOW)").replace(
    "-DMONITOR_EXT_KINDS=0x14 ", "-DMONITOR_EXT_KINDS=0x54 ")
PHONY_AND_ALIASES = """.PHONY: all svc live stamp bell unmask vss vss-carla ctl clean
all: $(BIN)
svc: $(SVC)
live: $(LIVE)
stamp: $(STAMP)
bell: $(BELL)
unmask: $(UNMASK)
vss: $(VSS)
vss-carla: $(VSS_CARLA)
ctl: $(CTL)
"""
CFLAGS_LINE = "CFLAGS  := -std=gnu99 -Wall -Wextra -Wformat=2 -O2 -I../common"
CLEAN_RULE = "clean:\n\trm -f $(BIN) $(SVC) $(LIVE) $(STAMP) $(BELL) $(UNMASK) $(VSS)\n"
DEFAULT_BINS = ("qnx-safety-monitor", "qnx-safety-monitor-svc", "qnx-safety-monitor-live", "qnx-safety-monitor-stamp",
                "qnx-safety-monitor-bell", "qnx-safety-monitor-unmask")
# The Makefile's SRCS, relative to its directory; the temporary copy holds exactly these.
MAKE_SRCS = ("monitor.c", "../common/shm_map_qnx.c", "../common/frame.h", "../common/frame_io.h", "../common/shm_chan.h",
             "../common/shm_map.h")
T0 = 1_700_000_000


def _missing(what):
    value = os.environ.get(REQUIRE_ENV)
    if value == "1":
        pytest.fail("%s=1 and an input of the make ctl tests is missing: %s" % (REQUIRE_ENV, what), pytrace=False)
    if value not in (None, "", "0"):
        pytest.fail("%s is %r: it is 1, or unset (a mistyped switch must not read as off)" % (REQUIRE_ENV, value), pytrace=False)
    pytest.skip(what)


def _make():
    make = shutil.which("make")
    if make is None or not hasattr(os, "sched_getaffinity"):
        _missing("needs GNU make on Linux")
    return make


def _profiles_h(ids, listed=None):
    """A stand-in vss_profiles.h in sdv/vss/generate.py's form (render_c_profiles): one X() row per id; listed replaces
    the VSS_PROFILE_IDS line, to show the rows are read and not the ids string."""
    rows = ["    X(%du, 2790u, 40.0, 10.0, 57.0, 1.0, 5.0, 0.0, 3.0, 1.0)" % i for i in ids]
    lines = ["/* vss_profiles.h -- a stand-in in the generator's form.",
             " *   X(id, l_mm, v_max, a_max, delta_max, v26_lo, v26_hi, ay26_max, tol26, v_tol)", " */",
             "#ifndef VSS_PROFILES_H", "#define VSS_PROFILES_H", "", "#define VSS_PROFILE_TABLE(X) \\"]
    lines += [r + (" \\" if n < len(rows) - 1 else "") for n, r in enumerate(rows)]
    lines += ["", "#define VSS_PROFILE_COUNT %du" % len(ids),
              '#define VSS_PROFILE_IDS "%s"' % (" ".join(str(i) for i in ids) if listed is None else listed), "",
              "#endif /* VSS_PROFILES_H */", ""]
    return "\n".join(lines)


def _ctl_h(ids, listed=None):
    """A stand-in vss_ctl.h in sdv/vss/generate.py's form (render_c_ctl): one X() row per compiled kind 2 id."""
    rows = ["    X(%du, 2790u, 25.0, 5.0, 80.0, 1.0, 1.0, 5.0)" % i for i in ids]
    lines = ["/* vss_ctl.h -- a stand-in in the generator's form.",
             " * X(id, l_mm, v_max, a_max, jerk_max, steer_max, steer_rate_max, lat_acc_max)", " */",
             "#ifndef VSS_CTL_H", "#define VSS_CTL_H", "", "#define VSS_CTL_FORMAT 1u", "", "#define VSS_CTL_PROFILE_TABLE(X) \\"]
    lines += [r + (" \\" if n < len(rows) - 1 else "") for n, r in enumerate(rows)]
    lines += ["", "#define VSS_CTL_PROFILE_COUNT %du" % len(ids),
              '#define VSS_CTL_PROFILE_IDS "%s"' % (" ".join(str(i) for i in ids) if listed is None else listed), "",
              "#endif /* VSS_CTL_H */", ""]
    return "\n".join(lines)


def _write_headers(gen, headers=HEADERS, k4=(1, 2, 3, 4), k2=(1, 2), k4_listed=None, k2_listed=None):
    gen.mkdir(parents=True, exist_ok=True)
    for h in headers:
        if h == "vss_profiles.h":
            text = _profiles_h(k4, k4_listed)
        elif h == "vss_ctl.h":
            text = _ctl_h(k2, k2_listed)
        else:
            text = "/* stand-in for make's timestamps */\n"
        (gen / h).write_text(text, encoding="ascii")
        os.utime(gen / h, (T0, T0))
    return gen


def _make_tree(tmp_path, **kw):
    """A copy of what the Makefile reads, at its repo-relative places, with a synthetic generation in sdv-out/gen (kw as
    _write_headers'; headers=() for none)."""
    root = tmp_path / "tree"
    mdir = root / "ipc-test" / "qnx-safety-monitor"
    mdir.mkdir(parents=True)
    (root / "ipc-test" / "common").mkdir()
    shutil.copy2(MAKEFILE, mdir / "Makefile")
    for rel in MAKE_SRCS:
        dst = mdir / rel
        shutil.copy2(MON_DIR / rel, dst)
        os.utime(dst, (T0, T0))
    if kw.get("headers", HEADERS):
        _write_headers(root / "sdv-out" / "gen", **kw)
    return mdir


def _run_make(mdir, *args, env=None):
    r = subprocess.run([_make(), "--no-print-directory", *args], cwd=str(mdir), capture_output=True, text=True, env=env)
    return r.returncode, r.stdout, r.stderr


def _lines(out):
    return [ln for ln in out.splitlines() if ln.strip()]


def _fake_cc(tmp_path):
    """A compiler stand-in that leaves a mark and fails, so no test here can run qcc or write the binary."""
    mark = tmp_path / "compiler-ran"
    fake = tmp_path / "fake-cc"
    fake.write_text("#!/bin/sh\ntouch '%s'\nexit 1\n" % mark, encoding="ascii")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    return mark, fake


def _env(**changes):
    env = {k: v for k, v in os.environ.items()
           if k not in ("CTL_GEN", "CTL_P5_GEN", "LANE_GEN", "VSS_GEN", "VSS_CARLA_GEN", "MAKEFLAGS")}
    env.update(changes)
    return env


# ============================================================ the planned line

@pytest.mark.parametrize("always", [(), ("-B",)], ids=["plain", "B"])
@pytest.mark.parametrize("goal", ["ctl", CTL_BIN])
def test_make_ctl_plans_the_vss_line_with_the_ctl_switch_under_its_own_name(goal, always, tmp_path):
    """Spec section 3 item 4: -ffp-contract=off -DMONITOR_EXT_KINDS=0x14 -I$(CTL_GEN), the vss recipe's flags otherwise; the
    guards' lines expand to nothing and no rule is defined twice (make would say so on stderr)."""
    assert CTL_LINE == VSS_LINE.replace("0x10", "0x14").replace(" -o %s " % VSS_BIN, " -o %s " % CTL_BIN)
    rc, out, err = _run_make(_make_tree(tmp_path), "-n", *always, goal, env=_env())
    assert rc == 0 and _lines(out) == [CTL_LINE] and err == "", (rc, out, err)


@pytest.mark.parametrize("how", ["command line", "environment"])
def test_ctl_gen_points_the_build_at_another_generation(how, tmp_path):
    """CTL_GEN ?= (spec section 3 item 4): from the command line or the environment, the guards and the -I read that
    directory; the default sdv-out/gen here lacks profile 4, so a plan proves the other one was read."""
    mdir = _make_tree(tmp_path / "a", k4=(1, 2, 3))
    other = _write_headers(tmp_path / "other")
    if how == "command line":
        rc, out, err = _run_make(mdir, "-n", "ctl", "CTL_GEN=" + str(other), env=_env())
    else:
        rc, out, err = _run_make(mdir, "-n", "ctl", env=_env(CTL_GEN=str(other)))
    assert rc == 0 and _lines(out) == [CTL_LINE.replace("-I../../sdv-out/gen ", "-I%s " % other)] and err == "", (rc, out, err)


def test_ctl_gen_is_ctls_alone(tmp_path):
    """The vss and vss-carla targets plan their own lines whatever CTL_GEN says, and ctl's guards never stop them."""
    mdir = _make_tree(tmp_path, k4=(1, 2, 3), k2=(2,))
    for goal, line in (("vss", VSS_LINE), ("vss-carla", VSS_CARLA_LINE)):
        for always in ((), ("-B",)):
            rc, out, err = _run_make(mdir, "-n", *always, goal, "CTL_GEN=" + str(tmp_path / "absent"), env=_env())
            assert rc == 0 and _lines(out) == [line] and err == "", (goal, always, rc, out, err)


# ============================================================ the missing headers

@pytest.mark.parametrize("always", [(), ("-B",)], ids=["plain", "B"])
@pytest.mark.parametrize("goal", ["ctl", CTL_BIN])
@pytest.mark.parametrize("absent", [HEADERS, ("vss_contract.h",), ("vss_profiles.h",), ("vss_ctl.h",)],
                         ids=["all", "contract", "profiles", "ctl"])
def test_make_ctl_without_a_generated_header_names_ctl_gen_and_the_generator(absent, goal, always, tmp_path):
    mdir = _make_tree(tmp_path, headers=tuple(h for h in HEADERS if h not in absent))
    rc, out, err = _run_make(mdir, "-n", *always, goal, env=_env())
    missing = "../../sdv-out/gen/%s is missing" % absent[0]
    assert rc != 0 and missing in err and GENERATOR in err and KNOB in err, (rc, out, err)
    assert "qcc" not in out, "no compile line may be planned without the contract"


@pytest.mark.parametrize("absent", [("vss_contract.h",), ("vss_profiles.h",), ("vss_ctl.h",)], ids=["contract", "profiles", "ctl"])
def test_make_ctl_names_its_own_directory_when_a_header_is_missing_there(absent, tmp_path):
    mdir = _make_tree(tmp_path)
    elsewhere = _write_headers(tmp_path / "elsewhere", headers=tuple(h for h in HEADERS if h not in absent))
    rc, out, err = _run_make(mdir, "-n", "ctl", "CTL_GEN=" + str(elsewhere), env=_env())
    assert rc != 0 and "%s/%s is missing" % (elsewhere, absent[0]) in err and GENERATOR in err and KNOB in err, (rc, out, err)
    assert "qcc" not in out


# ============================================================ the row guards

@pytest.mark.parametrize("always", [(), ("-B",)], ids=["plain", "B"])
@pytest.mark.parametrize("k4,listed", [((1, 2, 3), None), ((1, 2, 3), "1 2 3 4"), ((1, 2, 3, 14), None), ((40,), None),
                                       ((), None), ((5,), "4")],
                         ids=["rows 1-3", "rows 1-3 listed with 4", "row 14", "row 40", "no row", "row 5 listed as 4"])
def test_make_ctl_without_a_kind_4_profile_4_row_stops_before_any_compiler(k4, listed, always, tmp_path):
    rc, out, err = _run_make(_make_tree(tmp_path, k4=k4, k4_listed=listed), "-n", *always, "ctl", env=_env())
    assert rc != 0 and ROW4_ERROR in err and GENERATOR in err and "or point CTL_GEN at one" in err, (rc, out, err)
    assert "qcc" not in out


@pytest.mark.parametrize("always", [(), ("-B",)], ids=["plain", "B"])
@pytest.mark.parametrize("k2,listed", [((2,), None), ((2,), "1 2"), ((11,), None), ((21, 2), None), ((), None), ((3,), "1")],
                         ids=["row 2", "row 2 listed with 1", "row 11", "rows 21 2", "no row", "row 3 listed as 1"])
def test_make_ctl_without_a_kind_2_profile_1_row_stops_before_any_compiler(k2, listed, always, tmp_path):
    rc, out, err = _run_make(_make_tree(tmp_path, k2=k2, k2_listed=listed), "-n", *always, "ctl", env=_env())
    assert rc != 0 and ROW1_ERROR in err and GENERATOR in err and "or point CTL_GEN at one" in err, (rc, out, err)
    assert "qcc" not in out


def test_each_guard_reads_its_own_file(tmp_path):
    """Row 4 is read in vss_profiles.h and kind 2's row 1 in vss_ctl.h: a kind 2 table with a row 4 and a kind 4 table with
    a row 1 do not stand in for each other."""
    rc, out, err = _run_make(_make_tree(tmp_path / "a", k4=(1, 2, 3), k2=(1, 4)), "-n", "ctl", env=_env())
    assert rc != 0 and ROW4_ERROR in err and "qcc" not in out, (rc, out, err)
    rc, out, err = _run_make(_make_tree(tmp_path / "b", k4=(1, 4), k2=(2,)), "-n", "ctl", env=_env())
    assert rc != 0 and ROW1_ERROR in err and "qcc" not in out, (rc, out, err)


@pytest.mark.parametrize("k4,k2", [((4,), (1,)), ((4, 1, 2), (2, 1)), ((1, 2, 3, 4, 5), (1, 2, 3)), ((14, 4), (11, 1))])
def test_make_ctl_with_both_rows_anywhere_in_their_tables_plans_its_line(k4, k2, tmp_path):
    rc, out, err = _run_make(_make_tree(tmp_path, k4=k4, k2=k2), "-n", "ctl", env=_env())
    assert rc == 0 and _lines(out) == [CTL_LINE], (rc, out, err)


# ============================================================ the stray headers

@pytest.mark.parametrize("header", HEADERS)
@pytest.mark.parametrize("where", ["beside monitor.c", "in common"])
def test_make_ctl_refuses_a_contract_header_the_compiler_would_include_first(where, header, tmp_path):
    """monitor.c includes the three with quotes, so its own directory and CFLAGS's -I../common come before -I$(CTL_GEN):
    any copy there but CTL_GEN's own stops the build before any compiler (the stray holds both rows too)."""
    mdir = _make_tree(tmp_path)
    stray = (mdir if where == "beside monitor.c" else mdir.parent / "common") / header
    _write_headers(tmp_path / "stray-src", headers=(header,))
    shutil.copy2(tmp_path / "stray-src" / header, stray)
    rc, out, err = _run_make(mdir, "-n", "ctl", env=_env())
    assert rc != 0 and SHADOW_ERROR in err and os.path.realpath(str(stray)) in err and "qcc" not in out, (rc, out, err)
    mark, fake = _fake_cc(tmp_path)
    rc, out, err = _run_make(mdir, "ctl", "CC=" + str(fake), env=_env())
    assert rc != 0 and SHADOW_ERROR in err and not mark.exists() and not (mdir / CTL_BIN).exists(), (rc, out, err)


@pytest.mark.parametrize("own", [".", "../common"])
def test_make_ctl_takes_headers_that_are_ctl_gens_own(own, tmp_path):
    mdir = _make_tree(tmp_path, headers=())
    _write_headers(mdir / own)
    rc, out, err = _run_make(mdir, "-n", "ctl", "CTL_GEN=" + own, env=_env())
    assert rc == 0 and _lines(out) == [CTL_LINE.replace("-I../../sdv-out/gen ", "-I%s " % own)], (rc, out, err)


# ============================================================ make -q and a real make with a stand-in compiler

@pytest.mark.parametrize("touched", HEADERS + ("monitor.c",))
def test_make_q_ctl_sees_a_touched_input(touched, tmp_path):
    mdir = _make_tree(tmp_path)
    stub = mdir / CTL_BIN
    stub.write_text("stub, newer than every input\n", encoding="ascii")
    os.utime(stub, (T0 + 10, T0 + 10))
    assert _run_make(mdir, "-q", "ctl", env=_env())[0] == 0, "the stub target is up to date before anything is touched"
    path = mdir / touched if touched == "monitor.c" else mdir.parent.parent / "sdv-out" / "gen" / touched
    os.utime(path, (T0 + 20, T0 + 20))
    assert _run_make(mdir, "-q", "ctl", env=_env())[0] == 1, "make must rebuild after %s changed" % touched


@pytest.mark.parametrize("table", ["vss_profiles.h", "vss_ctl.h"])
def test_make_q_ctl_meets_the_guard_when_a_new_table_lacks_its_row(table, tmp_path):
    mdir = _make_tree(tmp_path)
    stub = mdir / CTL_BIN
    stub.write_text("stub, newer than every input\n", encoding="ascii")
    os.utime(stub, (T0 + 10, T0 + 10))
    gen = mdir.parent.parent / "sdv-out" / "gen"
    _write_headers(gen, headers=(table,), k4=(1, 2, 3), k2=(2,))
    os.utime(gen / table, (T0 + 20, T0 + 20))
    rc, out, err = _run_make(mdir, "-q", "ctl", env=_env())
    assert rc == 2 and (ROW4_ERROR if table == "vss_profiles.h" else ROW1_ERROR) in err, (rc, out, err)


@pytest.mark.parametrize("case", ["no contract", "no vss_ctl.h", "no profile 4", "no kind 2 profile 1", "both rows"])
def test_a_real_make_ctl_runs_the_compiler_only_with_the_contract_and_both_rows(case, tmp_path):
    kw = {"no contract": {"headers": ()}, "no vss_ctl.h": {"headers": HEADERS[:2]}, "no profile 4": {"k4": (1, 2, 3)},
          "no kind 2 profile 1": {"k2": (2,)}, "both rows": {}}[case]
    mdir = _make_tree(tmp_path, **kw)
    mark, fake = _fake_cc(tmp_path)
    rc, out, err = _run_make(mdir, "ctl", "CC=" + str(fake), env=_env())
    assert rc != 0, "the stand-in compiler fails, so every case fails"
    if case == "both rows":
        assert mark.exists(), "the control: with the contract and both rows the compiler runs"
    else:
        assert not mark.exists() and GENERATOR in err, (case, err)
    assert not (mdir / CTL_BIN).exists()


# ============================================================ every other recipe as it was

def test_the_default_recipes_the_vss_and_vss_carla_rules_and_clean_are_textually_unchanged():
    text = MAKEFILE.read_text(encoding="ascii")
    for block in (DEFAULT_RULES, VSS_RULES, VSS_HEADER_RULE, VSS_CARLA_RULES, CLEAN_RULE):
        assert text.count(block) == 1, block
    assert [ln for ln in text.splitlines() if ln.startswith("CFLAGS")] == [CFLAGS_LINE], "never the switch (or any -D) in CFLAGS"
    defines = [ln for ln in text.splitlines() if "-D" in ln and not ln.startswith("#")]
    assert defines == [VSS_RULES.splitlines()[1], VSS_CARLA_RULES.splitlines()[3], CTL_RECIPE, P5_RECIPE, LANE_RECIPE], defines


def test_the_default_targets_plan_exactly_as_before_beside_a_full_ctl_generation(tmp_path):
    mdir = _make_tree(tmp_path)
    rc, out, err = _run_make(mdir, "-n", "-B", "all", "svc", "live", "stamp", "bell", "unmask", env=_env())
    assert rc == 0 and err == "", err
    assert _lines(out) == [QCC + " -o %s monitor.c ../common/shm_map_qnx.c -lsocket" % b for b in DEFAULT_BINS]
    rc, out, err = _run_make(mdir, "-n", "clean", env=_env())
    assert rc == 0 and _lines(out) == ["rm -f " + " ".join(DEFAULT_BINS + (VSS_BIN,))], (out, err)
    for goal, line in (("vss", VSS_LINE), ("vss-carla", VSS_CARLA_LINE)):
        rc, out, err = _run_make(mdir, "-n", "-B", goal, env=_env())
        assert rc == 0 and _lines(out) == [line] and err == "", (goal, out, err)


def test_the_ctl_binary_is_ignored_and_left_by_clean_which_the_makefile_says(tmp_path):
    """Textual: the git-running tests are the Windows side's; `git check-ignore` was read there by hand. The name is the
    one make writes, the .gitignore line follows the vss-carla one, and the comment above CTL says clean leaves it."""
    rc, out, err = _run_make(_make_tree(tmp_path), "-n", "ctl", env=_env())
    assert rc == 0, err
    written = out.split(" -o ", 1)[1].split()[0]
    assert written == CTL_BIN
    lines = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    at = lines.index("ipc-test/qnx-safety-monitor/" + VSS_CARLA_BIN)
    assert lines[at + 1] == "ipc-test/qnx-safety-monitor/" + written, lines[at:at + 2]
    assert [ln for ln in lines if ln.startswith("!") and written in ln] == []
    rc, out, err = _run_make(_make_tree(tmp_path / "c", headers=()), "-n", "clean", env=_env())
    assert rc == 0 and CTL_BIN not in out, (out, err)
    mk = MAKEFILE.read_text(encoding="ascii").splitlines()
    at = start = next(n for n, ln in enumerate(mk) if ln.startswith("CTL :="))
    while mk[start - 1].startswith("#"):
        start -= 1
    comment = " ".join(" ".join(ln.lstrip("#").strip() for ln in mk[start:at]).split())
    for s in (CLEAN_SENTENCE, "qnx-safety-monitor-ctl", "MONITOR_EXT_KINDS=0x14", "profile 4", "X(4u,", "X(1u,", GENERATOR):
        assert s in comment, s


# ============================================================ against this tree's own generation

def test_make_ctl_against_this_trees_generation_plans_exactly_when_it_compiles_both_rows(tmp_path):
    """The guards read the X() rows as sdv/vss/generate.py writes them: each compiled id's row, and no other, stands as a
    whole word of the real headers (make's $(filter) splits on whitespace as str.split does), and `make -n ctl` plans its
    line exactly when kind 4's profile 4 and kind 2's profile 1 are both compiled (until WP3b compiles profile 4, it
    stops at the row-4 guard)."""
    if not all((GEN / h).is_file() for h in HEADERS):
        _missing("needs this tree's generation with vss_ctl.h in sdv-out/gen (sdv/vss/generate.py)")
    mdir = _make_tree(tmp_path, headers=())
    gen = mdir.parent.parent / "sdv-out" / "gen"
    gen.mkdir(parents=True)
    for h in HEADERS:
        shutil.copy2(GEN / h, gen / h)
    k4 = (GEN / "vss_profiles.h").read_text(encoding="ascii").split()
    k2 = (GEN / "vss_ctl.h").read_text(encoding="ascii").split()
    assert "X(1u," in k2, "kind 2's profile 1 is compiled (spec 2.3)"
    rc, out, err = _run_make(mdir, "-n", "ctl", env=_env())
    if "X(4u," in k4:
        assert rc == 0 and _lines(out) == [CTL_LINE], (rc, out, err)
    else:
        assert rc != 0 and ROW4_ERROR in err and "qcc" not in out, (rc, out, err)


# ============================================================ make ctl-p5 (SDV plan Phase 8.5, WP9c): the planned line

@pytest.mark.parametrize("always", [(), ("-B",)], ids=["plain", "B"])
@pytest.mark.parametrize("goal", ["ctl-p5", P5_BIN])
def test_make_ctl_p5_plans_the_ctl_line_under_its_own_name(goal, always, tmp_path):
    """MONITOR_EXT_KINDS=0x14 and the same flags as ctl, the contract from
    CTL_P5_GEN; the guards' lines expand to nothing and no rule is defined twice (make would say so on stderr)."""
    assert P5_LINE == CTL_LINE.replace(" -o %s " % CTL_BIN, " -o %s " % P5_BIN) != CTL_LINE
    rc, out, err = _run_make(_make_tree(tmp_path, k4=P5_K4), "-n", *always, goal, env=_env())
    assert rc == 0 and _lines(out) == [P5_LINE] and err == "", (rc, out, err)


@pytest.mark.parametrize("how", ["command line", "environment"])
def test_ctl_p5_gen_points_the_build_at_another_generation(how, tmp_path):
    """CTL_P5_GEN ?=: from the command line or the environment, the guards and the -I read that directory; the default
    sdv-out/gen here lacks profile 5, so a plan proves the other one was read."""
    mdir = _make_tree(tmp_path / "a")
    other = _write_headers(tmp_path / "other", k4=P5_K4)
    if how == "command line":
        rc, out, err = _run_make(mdir, "-n", "ctl-p5", "CTL_P5_GEN=" + str(other), env=_env())
    else:
        rc, out, err = _run_make(mdir, "-n", "ctl-p5", env=_env(CTL_P5_GEN=str(other)))
    assert rc == 0 and _lines(out) == [P5_LINE.replace("-I../../sdv-out/gen ", "-I%s " % other)] and err == "", (rc, out, err)


def test_ctl_p5_gen_is_ctl_p5s_alone_and_ctl_gen_never_moves_ctl_p5(tmp_path):
    """The vss, vss-carla and ctl targets plan their own lines whatever CTL_P5_GEN says, and ctl-p5's guards never stop
    them; ctl-p5 reads CTL_P5_GEN alone, so CTL_GEN pointed elsewhere moves it neither way."""
    mdir = _make_tree(tmp_path / "a")
    for goal, line in (("vss", VSS_LINE), ("vss-carla", VSS_CARLA_LINE), ("ctl", CTL_LINE)):
        for always in ((), ("-B",)):
            rc, out, err = _run_make(mdir, "-n", *always, goal, "CTL_P5_GEN=" + str(tmp_path / "absent"), env=_env())
            assert rc == 0 and _lines(out) == [line] and err == "", (goal, always, rc, out, err)
    with_5 = _write_headers(tmp_path / "with-5", k4=P5_K4)
    rc, out, err = _run_make(mdir, "-n", "ctl-p5", "CTL_GEN=" + str(with_5), env=_env())
    assert rc != 0 and ROW5_ERROR in err and "qcc" not in out, (rc, out, err)
    rc, out, err = _run_make(_make_tree(tmp_path / "b", k4=P5_K4), "-n", "ctl-p5", "CTL_GEN=" + str(tmp_path / "absent"), env=_env())
    assert rc == 0 and _lines(out) == [P5_LINE] and err == "", (rc, out, err)


# ============================================================ ctl-p5: the missing headers

@pytest.mark.parametrize("always", [(), ("-B",)], ids=["plain", "B"])
@pytest.mark.parametrize("goal", ["ctl-p5", P5_BIN])
@pytest.mark.parametrize("absent", [HEADERS, ("vss_contract.h",), ("vss_profiles.h",), ("vss_ctl.h",)],
                         ids=["all", "contract", "profiles", "ctl"])
def test_make_ctl_p5_without_a_generated_header_names_ctl_p5_gen_and_the_generator(absent, goal, always, tmp_path):
    mdir = _make_tree(tmp_path, headers=tuple(h for h in HEADERS if h not in absent), k4=P5_K4)
    rc, out, err = _run_make(mdir, "-n", *always, goal, env=_env())
    missing = "../../sdv-out/gen/%s is missing" % absent[0]
    assert rc != 0 and missing in err and GENERATOR in err and P5_KNOB in err, (rc, out, err)
    assert "qcc" not in out, "no compile line may be planned without the contract"


@pytest.mark.parametrize("absent", [("vss_contract.h",), ("vss_profiles.h",), ("vss_ctl.h",)], ids=["contract", "profiles", "ctl"])
def test_make_ctl_p5_names_its_own_directory_when_a_header_is_missing_there(absent, tmp_path):
    mdir = _make_tree(tmp_path, k4=P5_K4)
    elsewhere = _write_headers(tmp_path / "elsewhere", headers=tuple(h for h in HEADERS if h not in absent), k4=P5_K4)
    rc, out, err = _run_make(mdir, "-n", "ctl-p5", "CTL_P5_GEN=" + str(elsewhere), env=_env())
    assert rc != 0 and "%s/%s is missing" % (elsewhere, absent[0]) in err and GENERATOR in err and P5_KNOB in err, (rc, out, err)
    assert "qcc" not in out


# ============================================================ ctl-p5: the row guards

@pytest.mark.parametrize("always", [(), ("-B",)], ids=["plain", "B"])
@pytest.mark.parametrize("k4,listed", [((1, 2, 3, 4), None), ((1, 2, 3, 4), "1 2 3 4 5"), ((1, 2, 3, 4, 15), None), ((50,), None),
                                       ((), None), ((4,), "5")],
                         ids=["rows 1-4", "rows 1-4 listed with 5", "row 15", "row 50", "no row", "row 4 listed as 5"])
def test_make_ctl_p5_without_a_kind_4_profile_5_row_stops_before_any_compiler(k4, listed, always, tmp_path):
    rc, out, err = _run_make(_make_tree(tmp_path, k4=k4, k4_listed=listed), "-n", *always, "ctl-p5", env=_env())
    assert rc != 0 and ROW5_ERROR in err and GENERATOR in err and "or point CTL_P5_GEN at one" in err, (rc, out, err)
    assert "qcc" not in out


@pytest.mark.parametrize("always", [(), ("-B",)], ids=["plain", "B"])
@pytest.mark.parametrize("k2,listed", [((2,), None), ((2,), "1 2"), ((11,), None), ((21, 2), None), ((), None), ((3,), "1")],
                         ids=["row 2", "row 2 listed with 1", "row 11", "rows 21 2", "no row", "row 3 listed as 1"])
def test_make_ctl_p5_without_a_kind_2_profile_1_row_stops_before_any_compiler(k2, listed, always, tmp_path):
    rc, out, err = _run_make(_make_tree(tmp_path, k4=P5_K4, k2=k2, k2_listed=listed), "-n", *always, "ctl-p5", env=_env())
    assert rc != 0 and ROW1_ERROR in err and GENERATOR in err and "or point CTL_P5_GEN at one" in err, (rc, out, err)
    assert "qcc" not in out


def test_each_ctl_p5_guard_reads_its_own_file(tmp_path):
    """Row 5 is read in vss_profiles.h and kind 2's row 1 in vss_ctl.h: a kind 2 table with a row 5 and a kind 4 table with
    a row 1 do not stand in for each other."""
    rc, out, err = _run_make(_make_tree(tmp_path / "a", k4=(1, 2, 3, 4), k2=(1, 5)), "-n", "ctl-p5", env=_env())
    assert rc != 0 and ROW5_ERROR in err and "qcc" not in out, (rc, out, err)
    rc, out, err = _run_make(_make_tree(tmp_path / "b", k4=(1, 5), k2=(2,)), "-n", "ctl-p5", env=_env())
    assert rc != 0 and ROW1_ERROR in err and "qcc" not in out, (rc, out, err)


@pytest.mark.parametrize("k4,k2", [((5,), (1,)), ((5, 1, 2), (2, 1)), ((1, 2, 3, 4, 5), (1, 2, 3)), ((15, 5), (11, 1))])
def test_make_ctl_p5_with_both_rows_anywhere_in_their_tables_plans_its_line(k4, k2, tmp_path):
    """Profile 5 and kind 2's profile 1 are what it asks for: a table without profile 4 plans too (ctl's row 4 is ctl's)."""
    rc, out, err = _run_make(_make_tree(tmp_path, k4=k4, k2=k2), "-n", "ctl-p5", env=_env())
    assert rc == 0 and _lines(out) == [P5_LINE], (rc, out, err)


# ============================================================ ctl-p5: the stray headers

@pytest.mark.parametrize("header", HEADERS)
@pytest.mark.parametrize("where", ["beside monitor.c", "in common"])
def test_make_ctl_p5_refuses_a_contract_header_the_compiler_would_include_first(where, header, tmp_path):
    """As ctl's guard: any copy of the three beside monitor.c or in ../common but CTL_P5_GEN's own stops the build before any
    compiler (the stray holds both rows too)."""
    mdir = _make_tree(tmp_path, k4=P5_K4)
    stray = (mdir if where == "beside monitor.c" else mdir.parent / "common") / header
    _write_headers(tmp_path / "stray-src", headers=(header,), k4=P5_K4)
    shutil.copy2(tmp_path / "stray-src" / header, stray)
    rc, out, err = _run_make(mdir, "-n", "ctl-p5", env=_env())
    assert rc != 0 and SHADOW_ERROR in err and os.path.realpath(str(stray)) in err and "qcc" not in out, (rc, out, err)
    mark, fake = _fake_cc(tmp_path)
    rc, out, err = _run_make(mdir, "ctl-p5", "CC=" + str(fake), env=_env())
    assert rc != 0 and SHADOW_ERROR in err and not mark.exists() and not (mdir / P5_BIN).exists(), (rc, out, err)


@pytest.mark.parametrize("own", [".", "../common"])
def test_make_ctl_p5_takes_headers_that_are_ctl_p5_gens_own(own, tmp_path):
    mdir = _make_tree(tmp_path, headers=())
    _write_headers(mdir / own, k4=P5_K4)
    rc, out, err = _run_make(mdir, "-n", "ctl-p5", "CTL_P5_GEN=" + own, env=_env())
    assert rc == 0 and _lines(out) == [P5_LINE.replace("-I../../sdv-out/gen ", "-I%s " % own)], (rc, out, err)


# ============================================================ ctl-p5: make -q and a real make with a stand-in compiler

@pytest.mark.parametrize("touched", HEADERS + ("monitor.c",))
def test_make_q_ctl_p5_sees_a_touched_input(touched, tmp_path):
    mdir = _make_tree(tmp_path, k4=P5_K4)
    stub = mdir / P5_BIN
    stub.write_text("stub, newer than every input\n", encoding="ascii")
    os.utime(stub, (T0 + 10, T0 + 10))
    assert _run_make(mdir, "-q", "ctl-p5", env=_env())[0] == 0, "the stub target is up to date before anything is touched"
    path = mdir / touched if touched == "monitor.c" else mdir.parent.parent / "sdv-out" / "gen" / touched
    os.utime(path, (T0 + 20, T0 + 20))
    assert _run_make(mdir, "-q", "ctl-p5", env=_env())[0] == 1, "make must rebuild after %s changed" % touched


@pytest.mark.parametrize("table", ["vss_profiles.h", "vss_ctl.h"])
def test_make_q_ctl_p5_meets_the_guard_when_a_new_table_lacks_its_row(table, tmp_path):
    mdir = _make_tree(tmp_path, k4=P5_K4)
    stub = mdir / P5_BIN
    stub.write_text("stub, newer than every input\n", encoding="ascii")
    os.utime(stub, (T0 + 10, T0 + 10))
    gen = mdir.parent.parent / "sdv-out" / "gen"
    _write_headers(gen, headers=(table,), k4=(1, 2, 3, 4), k2=(2,))
    os.utime(gen / table, (T0 + 20, T0 + 20))
    rc, out, err = _run_make(mdir, "-q", "ctl-p5", env=_env())
    assert rc == 2 and (ROW5_ERROR if table == "vss_profiles.h" else ROW1_ERROR) in err, (rc, out, err)


def _header_make_args(build="ifs-ctl-p5.build", goal="ctl-p5"):
    """The make command a build file's header (ifs-ctl-p5.build's by default) gives its image step, as make's arguments
    here: its options and its goal, without `make` and `-C <the monitor's directory>` (the tests run make in the copy's
    directory)."""
    head = (MON_DIR / build).read_text(encoding="ascii").splitlines()
    cmds = [ln[1:].split() for ln in head if ln.startswith("#   make ") and ln.rstrip().endswith(" " + goal)]
    assert len(cmds) == 1, cmds
    argv = cmds[0]
    at = argv.index("-C")
    assert argv[0] == "make" and argv[at + 1] == "ipc-test/qnx-safety-monitor" and argv[-1] == goal, argv
    return argv[1:at] + argv[at + 2:]


@pytest.mark.parametrize("k4", [(1, 2, 3, 4), P5_K4], ids=["rows 1-4", "rows 1-5"])
def test_the_build_files_make_command_runs_the_guards_on_an_up_to_date_binary(k4, tmp_path):
    """make tracks no knob's value, only times: a qnx-safety-monitor-p5 newer than every input, built against another
    generation (CTL_P5_GEN pointed at a trial one), is up to date to a plain `make ctl-p5` against the head generation,
    and no guard runs. The command ifs-ctl-p5.build's header gives the image step still meets the row-5 guard on a
    generation without profile 5 and plans the compile line again on one with it, so the binary it stages is always
    the head generation's."""
    mdir = _make_tree(tmp_path, k4=k4)
    stub = mdir / P5_BIN
    stub.write_text("stub, built against another generation and newer than every input\n", encoding="ascii")
    os.utime(stub, (T0 + 10, T0 + 10))
    rc, out, err = _run_make(mdir, "-n", "ctl-p5", env=_env())
    assert rc == 0 and "qcc" not in out and "CTL_P5_GEN" not in err, ("the control: plain make skips the guards", rc, out, err)
    rc, out, err = _run_make(mdir, "-n", *_header_make_args(), env=_env())
    if 5 in k4:
        assert rc == 0 and _lines(out) == [P5_LINE], (rc, out, err)
    else:
        assert rc != 0 and ROW5_ERROR in err and "qcc" not in out, (rc, out, err)


@pytest.mark.parametrize("case", ["no contract", "no vss_ctl.h", "no profile 5", "no kind 2 profile 1", "both rows"])
def test_a_real_make_ctl_p5_runs_the_compiler_only_with_the_contract_and_both_rows(case, tmp_path):
    kw = {"no contract": {"headers": ()}, "no vss_ctl.h": {"headers": HEADERS[:2], "k4": P5_K4}, "no profile 5": {"k4": (1, 2, 3, 4)},
          "no kind 2 profile 1": {"k4": P5_K4, "k2": (2,)}, "both rows": {"k4": P5_K4}}[case]
    mdir = _make_tree(tmp_path, **kw)
    mark, fake = _fake_cc(tmp_path)
    rc, out, err = _run_make(mdir, "ctl-p5", "CC=" + str(fake), env=_env())
    assert rc != 0, "the stand-in compiler fails, so every case fails"
    if case == "both rows":
        assert mark.exists(), "the control: with the contract and both rows the compiler runs"
    else:
        assert not mark.exists() and GENERATOR in err, (case, err)
    assert not (mdir / P5_BIN).exists()


# ============================================================ ctl-p5: ctl as it was, the binary ignored and left by clean

def test_ctls_rules_its_phony_line_and_the_aliases_are_textually_unchanged_by_ctl_p5():
    text = MAKEFILE.read_text(encoding="ascii")
    for block in (CTL_RULES, PHONY_AND_ALIASES):
        assert text.count(block) == 1, block
    assert text.count(".PHONY: ctl-p5\nctl-p5: $(CTL_P5)\n") == 1, "ctl-p5's own .PHONY line and alias"
    assert text.count(P5_RULES) == 1, "ctl-p5's rule line and its four recipe lines"
    assert text.index(CTL_RULES) < text.index("CTL_P5 :=") < text.index(CLEAN_RULE), "the ctl-p5 block stands between ctl's and clean"


def _no_line_un_ignores(written):
    """No "!" line of .gitignore un-ignores the binary through git's backslash escape (a "!" line holds no backslash, and
    none matches the binary's path once its escapes are read), and no .gitignore under ipc-test/ can un-ignore it beside
    the Makefile (WP9c's critic, mutants c24 and c25); nor does one with no '/' but a trailing one, which git matches
    against the basename at any level, match the binary's name once its escapes are read (LB's critic, mutants cr2 and
    cr3: "!qnx-safety-monitor-la?e")."""
    path = "ipc-test/qnx-safety-monitor/" + written
    negations = [ln[1:].lstrip("/") for ln in (REPO / ".gitignore").read_text(encoding="utf-8").splitlines() if ln.startswith("!")]
    assert [p for p in negations if "\\" in p] == [], "a '!' line with git's escape"
    assert [p for p in negations if fnmatch.fnmatch(path, re.sub(r"\\(.)", r"\1", p))] == []
    assert [p for p in negations if "/" not in p.rstrip("/")
            and fnmatch.fnmatch(written, re.sub(r"\\(.)", r"\1", p.rstrip("/")))] == [], "a '!' line git matches by basename"
    assert sorted(str(p) for p in (REPO / "ipc-test").rglob(".gitignore")) == [], "a .gitignore under ipc-test/"


def test_the_ctl_p5_binary_is_ignored_and_left_by_clean_which_the_makefile_says(tmp_path):
    """Textual, as ctl's test: the name is the one make writes, the .gitignore line follows the ctl one, and the comment
    above CTL_P5 says clean leaves it."""
    rc, out, err = _run_make(_make_tree(tmp_path, k4=P5_K4), "-n", "ctl-p5", env=_env())
    assert rc == 0, err
    written = out.split(" -o ", 1)[1].split()[0]
    assert written == P5_BIN
    lines = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    at = lines.index("ipc-test/qnx-safety-monitor/" + CTL_BIN)
    assert lines[at + 1] == "ipc-test/qnx-safety-monitor/" + written, lines[at:at + 2]
    assert [ln for ln in lines if ln.startswith("!") and written in ln] == []
    assert [ln for ln in lines if ln.startswith("!")
            and fnmatch.fnmatch("ipc-test/qnx-safety-monitor/" + written, ln[1:].lstrip("/"))] == []
    _no_line_un_ignores(written)
    rc, out, err = _run_make(_make_tree(tmp_path / "c", headers=()), "-n", "clean", env=_env())
    assert rc == 0 and P5_BIN not in out, (out, err)
    mk = MAKEFILE.read_text(encoding="ascii").splitlines()
    at = start = next(n for n, ln in enumerate(mk) if ln.startswith("CTL_P5 :="))
    while mk[start - 1].startswith("#"):
        start -= 1
    comment = " ".join(" ".join(ln.lstrip("#").strip() for ln in mk[start:at]).split())
    for s in (CLEAN_SENTENCE, P5_BIN, "ifs-ctl-p5.build", "MONITOR_EXT_KINDS=0x14", "profile 5", "X(5u,", "X(1u,", GENERATOR,
              "CTL_P5_GEN"):
        assert s in comment, s


# ============================================================ ctl-p5 against this tree's own generation

def _compiled_ids(path):
    """COMPILED_PROFILE_IDS of a generated contract module (vss_contract.py for kind 4, vss_ctl.py for kind 2), read as
    text and never imported, by the line sdv/vss/generate.py writes (orin-native/gpu-concurrency/aw_suite.py's rule)."""
    m = re.search(r"^COMPILED_PROFILE_IDS = \(([0-9, ]*)\)$", path.read_text(encoding="utf-8"), re.M)
    assert m, "%s holds no COMPILED_PROFILE_IDS line: not the generation's" % path
    return tuple(int(x) for x in m.group(1).replace(",", " ").split())


def test_make_ctl_p5_against_this_trees_generation_plans_exactly_when_it_compiles_profile_5(tmp_path):
    """`make -n ctl-p5` plans its line exactly when the generator says kind 4's profile 5 and kind 2's profile 1 are both
    compiled: by COMPILED_PROFILE_IDS of vss_contract.py and vss_ctl.py, the generator's own statement, not by the word
    the guard reads, so a header holding "X(5u," with profile 5 uncompiled (in a comment, or a row under #if 0) fails
    here. Until WP3c F-c compiled profile 5, it stopped at the row-5 guard, which this generation passes."""
    if not all((GEN / f).is_file() for f in HEADERS + ("vss_contract.py", "vss_ctl.py")):
        _missing("needs this tree's generation with vss_ctl.h and vss_ctl.py in sdv-out/gen (sdv/vss/generate.py)")
    mdir = _make_tree(tmp_path, headers=())
    gen = mdir.parent.parent / "sdv-out" / "gen"
    gen.mkdir(parents=True)
    for h in HEADERS:
        shutil.copy2(GEN / h, gen / h)
    k4, k2 = _compiled_ids(GEN / "vss_contract.py"), _compiled_ids(GEN / "vss_ctl.py")
    assert 1 in k2, "kind 2's profile 1 is compiled"
    rc, out, err = _run_make(mdir, "-n", "ctl-p5", env=_env())
    if 5 in k4:
        assert rc == 0 and _lines(out) == [P5_LINE], (rc, out, err)
    else:
        assert rc != 0 and ROW5_ERROR in err and "qcc" not in out, (rc, out, err)


def test_plain_make_still_builds_the_monitor_and_not_ctl_p5(tmp_path):
    """The Makefile's header tells users to run plain `make`: ctl-p5's block names no default goal."""
    mdir = _make_tree(tmp_path, k4=P5_K4)
    rc, out, err = _run_make(mdir, "-n", env=_env())
    assert rc == 0 and _lines(out) == [QCC + " -o qnx-safety-monitor monitor.c ../common/shm_map_qnx.c -lsocket"] and err == "", \
        (rc, out, err)


# ============================================================ make lane (SDV Phase 9, C2b LB): the planned line

@pytest.mark.parametrize("always", [(), ("-B",)], ids=["plain", "B"])
@pytest.mark.parametrize("goal", ["lane", LANE_BIN])
def test_make_lane_plans_the_ctl_p5_line_with_the_lane_switch_under_its_own_name(goal, always, tmp_path):
    """ctl-p5's recipe with MONITOR_EXT_KINDS=0x54 (kinds 2, 4 and 6), -ffp-contract=off
    and the contract from LANE_GEN; the guards' lines expand to nothing and no rule is defined twice."""
    assert LANE_LINE == P5_LINE.replace("0x14", "0x54").replace(" -o %s " % P5_BIN, " -o %s " % LANE_BIN) != P5_LINE
    assert " -ffp-contract=off -DMONITOR_EXT_KINDS=0x54 -I../../sdv-out/gen -o qnx-safety-monitor-lane " in LANE_LINE
    rc, out, err = _run_make(_make_tree(tmp_path, k4=P5_K4), "-n", *always, goal, env=_env())
    assert rc == 0 and _lines(out) == [LANE_LINE] and err == "", (rc, out, err)


@pytest.mark.parametrize("how", ["command line", "environment"])
def test_lane_gen_points_the_build_at_another_generation(how, tmp_path):
    """LANE_GEN ?=: from the command line or the environment, the guards and the -I read that directory; the default
    sdv-out/gen here lacks profile 5, so a plan proves the other one was read."""
    mdir = _make_tree(tmp_path / "a")
    other = _write_headers(tmp_path / "other", k4=P5_K4)
    if how == "command line":
        rc, out, err = _run_make(mdir, "-n", "lane", "LANE_GEN=" + str(other), env=_env())
    else:
        rc, out, err = _run_make(mdir, "-n", "lane", env=_env(LANE_GEN=str(other)))
    assert rc == 0 and _lines(out) == [LANE_LINE.replace("-I../../sdv-out/gen ", "-I%s " % other)] and err == "", (rc, out, err)


@pytest.mark.parametrize("knob", ["CTL_GEN", "CTL_P5_GEN"])
def test_lane_gen_is_lanes_alone_and_no_other_knob_moves_lane(knob, tmp_path):
    """vss, vss-carla, ctl and ctl-p5 plan their own lines whatever LANE_GEN says, and lane's guards never stop them; lane
    reads LANE_GEN alone, so CTL_GEN or CTL_P5_GEN pointed elsewhere moves it neither way."""
    mdir = _make_tree(tmp_path / "a", k4=P5_K4)
    for goal, line in (("vss", VSS_LINE), ("vss-carla", VSS_CARLA_LINE), ("ctl", CTL_LINE), ("ctl-p5", P5_LINE)):
        for always in ((), ("-B",)):
            rc, out, err = _run_make(mdir, "-n", *always, goal, "LANE_GEN=" + str(tmp_path / "absent"), env=_env())
            assert rc == 0 and _lines(out) == [line] and err == "", (goal, always, rc, out, err)
    rc, out, err = _run_make(mdir, "-n", "lane", knob + "=" + str(tmp_path / "absent"), env=_env())
    assert rc == 0 and _lines(out) == [LANE_LINE] and err == "", (rc, out, err)
    with_5 = _write_headers(tmp_path / "with-5", k4=P5_K4)
    rc, out, err = _run_make(_make_tree(tmp_path / "b"), "-n", "lane", knob + "=" + str(with_5), env=_env())
    assert rc != 0 and ROW5_ERROR in err and LANE_KNOB in err and "qcc" not in out, (rc, out, err)


# ============================================================ lane: the missing headers

@pytest.mark.parametrize("always", [(), ("-B",)], ids=["plain", "B"])
@pytest.mark.parametrize("goal", ["lane", LANE_BIN])
@pytest.mark.parametrize("absent", [HEADERS, ("vss_contract.h",), ("vss_profiles.h",), ("vss_ctl.h",)],
                         ids=["all", "contract", "profiles", "ctl"])
def test_make_lane_without_a_generated_header_names_lane_gen_and_the_generator(absent, goal, always, tmp_path):
    mdir = _make_tree(tmp_path, headers=tuple(h for h in HEADERS if h not in absent), k4=P5_K4)
    rc, out, err = _run_make(mdir, "-n", *always, goal, env=_env())
    missing = "../../sdv-out/gen/%s is missing" % absent[0]
    assert rc != 0 and missing in err and GENERATOR in err and LANE_KNOB in err, (rc, out, err)
    assert "qcc" not in out, "no compile line may be planned without the contract"


@pytest.mark.parametrize("absent", [("vss_contract.h",), ("vss_profiles.h",), ("vss_ctl.h",)], ids=["contract", "profiles", "ctl"])
def test_make_lane_names_its_own_directory_when_a_header_is_missing_there(absent, tmp_path):
    mdir = _make_tree(tmp_path, k4=P5_K4)
    elsewhere = _write_headers(tmp_path / "elsewhere", headers=tuple(h for h in HEADERS if h not in absent), k4=P5_K4)
    rc, out, err = _run_make(mdir, "-n", "lane", "LANE_GEN=" + str(elsewhere), env=_env())
    assert rc != 0 and "%s/%s is missing" % (elsewhere, absent[0]) in err and GENERATOR in err and LANE_KNOB in err, (rc, out, err)
    assert "qcc" not in out


# ============================================================ lane: the row guards

@pytest.mark.parametrize("always", [(), ("-B",)], ids=["plain", "B"])
@pytest.mark.parametrize("k4,listed", [((1, 2, 3, 4), None), ((1, 2, 3, 4), "1 2 3 4 5"), ((1, 2, 3, 4, 15), None), ((50,), None),
                                       ((), None), ((4,), "5")],
                         ids=["rows 1-4", "rows 1-4 listed with 5", "row 15", "row 50", "no row", "row 4 listed as 5"])
def test_make_lane_without_a_kind_4_profile_5_row_stops_before_any_compiler(k4, listed, always, tmp_path):
    rc, out, err = _run_make(_make_tree(tmp_path, k4=k4, k4_listed=listed), "-n", *always, "lane", env=_env())
    assert rc != 0 and ROW5_ERROR in err and GENERATOR in err and "or point LANE_GEN at one" in err, (rc, out, err)
    assert "qcc" not in out


@pytest.mark.parametrize("always", [(), ("-B",)], ids=["plain", "B"])
@pytest.mark.parametrize("k2,listed", [((2,), None), ((2,), "1 2"), ((11,), None), ((21, 2), None), ((), None), ((3,), "1")],
                         ids=["row 2", "row 2 listed with 1", "row 11", "rows 21 2", "no row", "row 3 listed as 1"])
def test_make_lane_without_a_kind_2_profile_1_row_stops_before_any_compiler(k2, listed, always, tmp_path):
    rc, out, err = _run_make(_make_tree(tmp_path, k4=P5_K4, k2=k2, k2_listed=listed), "-n", *always, "lane", env=_env())
    assert rc != 0 and ROW1_ERROR in err and GENERATOR in err and "or point LANE_GEN at one" in err, (rc, out, err)
    assert "qcc" not in out


def test_each_lane_guard_reads_its_own_file(tmp_path):
    """Row 5 is read in vss_profiles.h and kind 2's row 1 in vss_ctl.h: a kind 2 table with a row 5 and a kind 4 table with
    a row 1 do not stand in for each other."""
    rc, out, err = _run_make(_make_tree(tmp_path / "a", k4=(1, 2, 3, 4), k2=(1, 5)), "-n", "lane", env=_env())
    assert rc != 0 and ROW5_ERROR in err and "qcc" not in out, (rc, out, err)
    rc, out, err = _run_make(_make_tree(tmp_path / "b", k4=(1, 5), k2=(2,)), "-n", "lane", env=_env())
    assert rc != 0 and ROW1_ERROR in err and "qcc" not in out, (rc, out, err)


@pytest.mark.parametrize("k4,k2", [((5,), (1,)), ((5, 1, 2), (2, 1)), ((1, 2, 3, 4, 5), (1, 2, 3)), ((15, 5), (11, 1))])
def test_make_lane_with_both_rows_anywhere_in_their_tables_plans_its_line(k4, k2, tmp_path):
    rc, out, err = _run_make(_make_tree(tmp_path, k4=k4, k2=k2), "-n", "lane", env=_env())
    assert rc == 0 and _lines(out) == [LANE_LINE], (rc, out, err)


# ============================================================ lane: the stray headers

@pytest.mark.parametrize("header", HEADERS)
@pytest.mark.parametrize("where", ["beside monitor.c", "in common"])
def test_make_lane_refuses_a_contract_header_the_compiler_would_include_first(where, header, tmp_path):
    """As ctl-p5's guard: any copy of the three beside monitor.c or in ../common but LANE_GEN's own stops the build before
    any compiler (the stray holds both rows too)."""
    mdir = _make_tree(tmp_path, k4=P5_K4)
    stray = (mdir if where == "beside monitor.c" else mdir.parent / "common") / header
    _write_headers(tmp_path / "stray-src", headers=(header,), k4=P5_K4)
    shutil.copy2(tmp_path / "stray-src" / header, stray)
    rc, out, err = _run_make(mdir, "-n", "lane", env=_env())
    assert rc != 0 and SHADOW_ERROR in err and os.path.realpath(str(stray)) in err and "qcc" not in out, (rc, out, err)
    mark, fake = _fake_cc(tmp_path)
    rc, out, err = _run_make(mdir, "lane", "CC=" + str(fake), env=_env())
    assert rc != 0 and SHADOW_ERROR in err and not mark.exists() and not (mdir / LANE_BIN).exists(), (rc, out, err)


@pytest.mark.parametrize("own", [".", "../common"])
def test_make_lane_takes_headers_that_are_lane_gens_own(own, tmp_path):
    mdir = _make_tree(tmp_path, headers=())
    _write_headers(mdir / own, k4=P5_K4)
    rc, out, err = _run_make(mdir, "-n", "lane", "LANE_GEN=" + own, env=_env())
    assert rc == 0 and _lines(out) == [LANE_LINE.replace("-I../../sdv-out/gen ", "-I%s " % own)], (rc, out, err)


# ============================================================ lane: make -q and a real make with a stand-in compiler

@pytest.mark.parametrize("touched", HEADERS + ("monitor.c",))
def test_make_q_lane_sees_a_touched_input(touched, tmp_path):
    mdir = _make_tree(tmp_path, k4=P5_K4)
    stub = mdir / LANE_BIN
    stub.write_text("stub, newer than every input\n", encoding="ascii")
    os.utime(stub, (T0 + 10, T0 + 10))
    assert _run_make(mdir, "-q", "lane", env=_env())[0] == 0, "the stub target is up to date before anything is touched"
    path = mdir / touched if touched == "monitor.c" else mdir.parent.parent / "sdv-out" / "gen" / touched
    os.utime(path, (T0 + 20, T0 + 20))
    assert _run_make(mdir, "-q", "lane", env=_env())[0] == 1, "make must rebuild after %s changed" % touched


@pytest.mark.parametrize("table", ["vss_profiles.h", "vss_ctl.h"])
def test_make_q_lane_meets_the_guard_when_a_new_table_lacks_its_row(table, tmp_path):
    mdir = _make_tree(tmp_path, k4=P5_K4)
    stub = mdir / LANE_BIN
    stub.write_text("stub, newer than every input\n", encoding="ascii")
    os.utime(stub, (T0 + 10, T0 + 10))
    gen = mdir.parent.parent / "sdv-out" / "gen"
    _write_headers(gen, headers=(table,), k4=(1, 2, 3, 4), k2=(2,))
    os.utime(gen / table, (T0 + 20, T0 + 20))
    rc, out, err = _run_make(mdir, "-q", "lane", env=_env())
    assert rc == 2 and (ROW5_ERROR if table == "vss_profiles.h" else ROW1_ERROR) in err, (rc, out, err)


@pytest.mark.parametrize("k4", [(1, 2, 3, 4), P5_K4], ids=["rows 1-4", "rows 1-5"])
def test_the_lane_build_files_make_command_runs_the_guards_on_an_up_to_date_binary(k4, tmp_path):
    """As ctl-p5's: a qnx-safety-monitor-lane newer than every input, built against another generation, is up to date to
    a plain `make lane`, and no guard runs; the command ifs-lane.build's header gives the image step (with -B) meets the
    row-5 guard on a generation without profile 5 and plans the compile line again on one with it."""
    mdir = _make_tree(tmp_path, k4=k4)
    stub = mdir / LANE_BIN
    stub.write_text("stub, built against another generation and newer than every input\n", encoding="ascii")
    os.utime(stub, (T0 + 10, T0 + 10))
    rc, out, err = _run_make(mdir, "-n", "lane", env=_env())
    assert rc == 0 and "qcc" not in out and "LANE_GEN" not in err, ("the control: plain make skips the guards", rc, out, err)
    args = _header_make_args("ifs-lane.build", "lane")
    assert "-B" in args, args
    rc, out, err = _run_make(mdir, "-n", *args, env=_env())
    if 5 in k4:
        assert rc == 0 and _lines(out) == [LANE_LINE], (rc, out, err)
    else:
        assert rc != 0 and ROW5_ERROR in err and "qcc" not in out, (rc, out, err)


@pytest.mark.parametrize("case", ["no contract", "no vss_ctl.h", "no profile 5", "no kind 2 profile 1", "both rows"])
def test_a_real_make_lane_runs_the_compiler_only_with_the_contract_and_both_rows(case, tmp_path):
    kw = {"no contract": {"headers": ()}, "no vss_ctl.h": {"headers": HEADERS[:2], "k4": P5_K4}, "no profile 5": {"k4": (1, 2, 3, 4)},
          "no kind 2 profile 1": {"k4": P5_K4, "k2": (2,)}, "both rows": {"k4": P5_K4}}[case]
    mdir = _make_tree(tmp_path, **kw)
    mark, fake = _fake_cc(tmp_path)
    rc, out, err = _run_make(mdir, "lane", "CC=" + str(fake), env=_env())
    assert rc != 0, "the stand-in compiler fails, so every case fails"
    if case == "both rows":
        assert mark.exists(), "the control: with the contract and both rows the compiler runs"
    else:
        assert not mark.exists() and GENERATOR in err, (case, err)
    assert not (mdir / LANE_BIN).exists()


# ============================================================ lane: ctl-p5 as it was, the binary ignored and left by clean

def test_ctl_p5s_rules_are_textually_unchanged_by_lane_whose_phony_line_alias_and_rules_are_its_own():
    text = MAKEFILE.read_text(encoding="ascii")
    for block in (CTL_RULES, PHONY_AND_ALIASES, P5_RULES, P5_PARSE_CHECK, ".PHONY: ctl-p5\nctl-p5: $(CTL_P5)\n"):
        assert text.count(block) == 1, block
    assert text.count(".PHONY: lane\nlane: $(LANE)\n") == 1, "lane's own .PHONY line and alias"
    assert text.count(LANE_RULES) == 1, "lane's rule line and its four recipe lines"
    assert text.count("\nLANE_GEN ?= ../../sdv-out/gen\n") == 1
    assert text.index(P5_PARSE_CHECK) < text.index("LANE :=") < text.index(CLEAN_RULE), "the lane block stands between ctl-p5's and clean"
    lane_check = P5_PARSE_CHECK.replace("ctl-p5 $(CTL_P5)", "lane $(LANE)").replace("$(CTL_P5_GEN)", "$(LANE_GEN)").replace(
        "$(CTL_P5_MISSING)", "$(LANE_MISSING)")
    assert text.count(lane_check) == 1, "lane's parse-time check: ctl-p5's with lane's names"


def test_the_lane_binary_is_ignored_and_left_by_clean_which_the_makefile_says(tmp_path):
    """Textual, as ctl-p5's test: the name is the one make writes, the .gitignore line follows the p5 one, no line or nested
    .gitignore un-ignores it, and the comment above LANE says clean leaves it."""
    rc, out, err = _run_make(_make_tree(tmp_path, k4=P5_K4), "-n", "lane", env=_env())
    assert rc == 0, err
    written = out.split(" -o ", 1)[1].split()[0]
    assert written == LANE_BIN
    lines = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    at = lines.index("ipc-test/qnx-safety-monitor/" + P5_BIN)
    assert lines[at + 1] == "ipc-test/qnx-safety-monitor/" + written, lines[at:at + 2]
    assert [ln for ln in lines if ln.startswith("!") and written in ln] == []
    _no_line_un_ignores(written)
    rc, out, err = _run_make(_make_tree(tmp_path / "c", headers=()), "-n", "clean", env=_env())
    assert rc == 0 and LANE_BIN not in out, (out, err)
    mk = MAKEFILE.read_text(encoding="ascii").splitlines()
    at = start = next(n for n, ln in enumerate(mk) if ln.startswith("LANE :="))
    while mk[start - 1].startswith("#"):
        start -= 1
    comment = " ".join(" ".join(ln.lstrip("#").strip() for ln in mk[start:at]).split())
    for s in (CLEAN_SENTENCE, LANE_BIN, "ifs-lane.build", "MONITOR_EXT_KINDS=0x54", "kind 6", "profile 5", "X(5u,", "X(1u,",
              GENERATOR, "LANE_GEN", "-ffp-contract=off"):
        assert s in comment, s


# ============================================================ lane against this tree's own generation

def test_make_lane_against_this_trees_generation_plans_exactly_when_it_compiles_profile_5(tmp_path):
    """As ctl-p5's: `make -n lane` plans its line exactly when the generator's COMPILED_PROFILE_IDS hold kind 4's profile 5
    and kind 2's profile 1. Until WP3c F-c compiled profile 5, it stopped at the row-5 guard, which this generation
    passes."""
    if not all((GEN / f).is_file() for f in HEADERS + ("vss_contract.py", "vss_ctl.py")):
        _missing("needs this tree's generation with vss_ctl.h and vss_ctl.py in sdv-out/gen (sdv/vss/generate.py)")
    mdir = _make_tree(tmp_path, headers=())
    gen = mdir.parent.parent / "sdv-out" / "gen"
    gen.mkdir(parents=True)
    for h in HEADERS:
        shutil.copy2(GEN / h, gen / h)
    k4, k2 = _compiled_ids(GEN / "vss_contract.py"), _compiled_ids(GEN / "vss_ctl.py")
    assert 1 in k2, "kind 2's profile 1 is compiled"
    rc, out, err = _run_make(mdir, "-n", "lane", env=_env())
    if 5 in k4:
        assert rc == 0 and _lines(out) == [LANE_LINE], (rc, out, err)
    else:
        assert rc != 0 and ROW5_ERROR in err and "qcc" not in out, (rc, out, err)


def test_plain_make_still_builds_the_monitor_and_not_lane(tmp_path):
    """lane's block names no default goal either."""
    mdir = _make_tree(tmp_path, k4=P5_K4)
    rc, out, err = _run_make(mdir, "-n", env=_env())
    assert rc == 0 and _lines(out) == [QCC + " -o qnx-safety-monitor monitor.c ../common/shm_map_qnx.c -lsocket"] and err == "", \
        (rc, out, err)


# ============================================================ lane: the stack README names its build file

GUEST_SENTENCE = "In guest mode the run manifest's `vss-monitor-guest` component names the build file of the image that ran:"
OTHER_IMAGE = "and for any other image no build file of this tree."


def test_the_stack_readme_names_the_build_file_of_every_guest_image_build_row_for_its_image():
    """A2 (LB's critic#2): sdv/stack/README.md's guest-mode sentence names the build file of each row of stack.py's
    GUEST_IMAGE_BUILDS for its image, ifs-lane.build for ifs-lane.bin among them, and no other, so its "for any other
    image no build file of this tree" holds; and it states no board-run outcome of any image (no "booted" in it). The
    table is read from stack.py's source (ast), not imported (stack.py needs fcntl);
    tests/test_sdv_stack.py holds it to the build files that start the vss monitor."""
    tree = ast.parse((REPO / "sdv" / "stack" / "stack.py").read_text(encoding="utf-8"))
    tables = [ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
              and [getattr(t, "id", None) for t in n.targets] == ["GUEST_IMAGE_BUILDS"]]
    assert len(tables) == 1 and len(tables[0]) >= 5, tables
    rows = sorted((Path(build).name, image) for image, build in tables[0].items())
    text = " ".join((REPO / "sdv" / "stack" / "README.md").read_text(encoding="utf-8").split())
    assert text.count(GUEST_SENTENCE) == 1
    start = text.index(GUEST_SENTENCE)
    sentence = text[start:text.index(OTHER_IMAGE, start) + len(OTHER_IMAGE)]
    named = sorted(re.findall(r"`([A-Za-z0-9.-]+\.build)` for `([A-Za-z0-9.-]+\.bin)`", sentence))
    assert named == rows, (named, rows)
    assert ("ifs-lane.build", "ifs-lane.bin") in named
    assert "booted" not in sentence, sentence
