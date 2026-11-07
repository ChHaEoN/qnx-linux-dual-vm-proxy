"""kind4-spec 16.1 C5, C6 and C32: the extension-kind switch and its build wiring (sdv Phase 2, WP1).

monitor.c gains MONITOR_EXT_KINDS (the kind 4 wire specification, section 11) in bare #if blocks after
its includes: the value check, a Phase 2 deviation that also stops 0x14 and 0x1C (design decision d),
and, for the vss build, the generated contract's includes with two #errors (contract format 1, and
__FLT_EVAL_METHOD__ defined and 0). The qcc Makefile gains `make vss`; build-monitor-native.sh gains
MONITOR_EXT_KINDS and MONITOR_VSS_GEN, read from the environment. Both vss builds pass -ffp-contract=off
(design decision e). What WP1 adds is checked here; kind 4 itself (WP2+3) is tests/test_monitor_kind4.py's:

- C5: every refused value stops with its #error; 0x10 compiles under -Wformat=2 -Wundef -Werror with
  -ffp-contract=off, and so does tests/vss_driver.c, which includes monitor.c with main renamed; the
  default build (switch undefined) compiles under -Wundef, includes no generated header, and someip.c,
  which includes monitor.c, still builds under -Werror. -Wundef holds section 11's "every guard tests
  definedness explicitly": a guard that reads the undefined switch as 0 fails the default compile, and
  the contract-format and float-evaluation tests refuse a -Wundef diagnostic beside their #error. A
  -Wpedantic compile of the default and the vss unit holds "only bare #if blocks": a stray file-scope
  ';' fails it. Since Phase 8 (WP1a narrowed the deviation to 0x1C; WP1b generates vss_ctl.h), 0x14
  compiles clean against the generation's vss_ctl.h, and 0x1C still stops as not implemented.
- C6: `make vss` without a generated header stops naming sdv/vss/generate.py, before any compiler runs,
  with or without -B; with both headers `make -n -B vss` plans the vss line alone; `make -q vss` sees a
  touched header. Run in a temporary copy of the build's inputs, with `make -n` and `make -q` only: qcc
  never runs here (it cannot in WSL or CI).
- C32: build-monitor-native.sh refuses the default OUT with the switch on, and its source-sha256 covers
  both headers, the switch value and the extra flag; with the switch off the gcc line and the hash are
  exactly the ones before the switch existed, and a generic EXT_KINDS or VSS_GEN in the environment is
  not read. A recording CC wrapper takes the gcc line as argv. Phase 8 WP1b: for 0x14 the script also
  takes vss_ctl.h, after the two, into the hash, and builds the ctl monitor to its own OUT.
- The default targets of the Makefile keep their recipes and CFLAGS textually, with no -D anywhere but the
  extension-kind recipes (vss, vss-carla, and Phase 8's ctl, whose own tests are tests/test_make_ctl.py);
  C1 (tests/test_monitor_golden.py) shows the default build's behaviour is unchanged.
- Phase 7 WP4a: `make vss-carla` builds qnx-safety-monitor-carla, the binary
  ifs-vss-carla.build stages, with the vss recipe's flags exactly and the contract from VSS_CARLA_GEN. It
  stops before any compiler runs when a header is missing (naming VSS_CARLA_GEN, in the default directory
  too), when vss_profiles.h has no X() row for profile 3, or when a vss_contract.h or vss_profiles.h beside
  monitor.c or in ../common would be compiled instead of VSS_CARLA_GEN's. The binary is ignored beside the
  vss one, `make clean` leaves it (the Makefile says so), and the vss target and its rules are textually
  unchanged.

What this does NOT show: anything about the qcc build or the guest binary (nothing here runs qcc, and
4.6(c) forbids taking the guest binary apart), any kind 4 behaviour (tests/test_monitor_kind4.py), and
that profile 3's row holds the frozen values (the generator's tests).

Needs gcc on Linux (WSL Ubuntu-24.04 or CI's tooling job); the C6 tests need make; the tests that compile
the vss build need the generated contract in sdv-out/gen (sdv/vss/generate.py) and skip without it.
"""
import hashlib
import importlib.util
import os
import platform
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
MON_DIR = REPO / "ipc-test" / "qnx-safety-monitor"
MONITOR_C = MON_DIR / "monitor.c"
MAKEFILE = MON_DIR / "Makefile"
COMMON = REPO / "ipc-test" / "common"
SHM_MAP_POSIX_C = COMMON / "shm_map_posix.c"
IVSHM_CLIENT_C = COMMON / "ivshm_client.c"
SOMEIP_C = REPO / "ipc-test" / "qnx-someip" / "someip.c"
DRIVER_C = HERE / "vss_driver.c"
NATIVE = REPO / "orin-native" / "gpu-concurrency" / "build-monitor-native.sh"
GEN = REPO / "sdv-out" / "gen"
GEN_HEADERS = ("vss_contract.h", "vss_profiles.h")
GENERATOR = "sdv/vss/generate.py"

# The vss build as the native_vss fixture compiles it (section 11; Phase 2 design decision e). -Wformat=2
# -Werror here is the only gate the qcc build's warnings get: the Makefile's CFLAGS has no -Werror.
# -Wundef: an #if that reads an undefined macro as 0 is an error, so every guard on the
# switch must test definedness explicitly, as section 11 requires; the default compile, where the switch
# is undefined, is the one that catches a guard that does not.
DEFAULT_FLAGS = ("-O2", "-std=gnu99", "-Wall", "-Wextra", "-Wformat=2", "-Wundef", "-Werror")
VSS_FLAGS = DEFAULT_FLAGS + ("-ffp-contract=off", "-DMONITOR_EXT_KINDS=0x10")
# The syntax-only gate for a stray file-scope ';' (ISO C has no empty declaration; only -Wpedantic says
# so). gnu11, not the builds' gnu99: shm_chan.h's _Static_assert is C11, and -Wpedantic under gnu99 fails
# on it in both units. Nothing is compiled to code here; the builds keep their own gnu99.
PEDANTIC_FLAGS = ("-fsyntax-only", "-std=gnu11", "-Wpedantic", "-Werror")

SWITCH_ERROR = "MONITOR_EXT_KINDS must be 0x10 (vss), 0x14 (ctl) or 0x1C (gap)"
NOT_IMPLEMENTED = "not implemented"
FORMAT_ERROR = "is not contract format 1"
FLT_EVAL_ERROR = "needs __FLT_EVAL_METHOD__ defined and 0"
# gcc's -Wundef diagnostic under -Werror. A guard whose own #error fires anyway when the macro is undefined
# (the contract format, the float evaluation method) shows a missing defined() only through it.
UNDEF_DIAG = "[-Werror=undef]"

NEEDS_GEN = pytest.mark.skipif(not all((GEN / h).is_file() for h in GEN_HEADERS),
                               reason="needs the generated contract in sdv-out/gen (sdv/vss/generate.py)")


def _gcc():
    gcc = shutil.which("gcc")
    if gcc is None or not hasattr(os, "sched_getaffinity"):
        pytest.skip("needs gcc on Linux: runs in WSL and in CI's tooling job")
    return gcc


def _make():
    make = shutil.which("make")
    if make is None or not hasattr(os, "sched_getaffinity"):
        pytest.skip("needs GNU make on Linux")
    return make


def _compile_object(gcc, flags, tmp_path, src=MONITOR_C, gen=GEN):
    """Compile one translation unit to an object: the switch is settled before the linker."""
    cmd = [gcc, *flags, "-I", str(COMMON), "-I", str(gen), "-c", "-o", str(tmp_path / "unit.o"), str(src)]
    return subprocess.run(cmd, capture_output=True, text=True)


@pytest.fixture(scope="module")
def native_vss(tmp_path_factory):
    """The vss build of monitor.c and the test driver, both with the vss build's flags."""
    gcc = _gcc()
    if not all((GEN / h).is_file() for h in GEN_HEADERS):
        pytest.skip("needs the generated contract in sdv-out/gen (sdv/vss/generate.py)")
    d = tmp_path_factory.mktemp("vss")
    for src, name in ((MONITOR_C, "monitor"), (DRIVER_C, "driver")):
        cmd = [gcc, *VSS_FLAGS, "-I", str(COMMON), "-I", str(GEN), "-o", str(d / name),
               str(src), str(SHM_MAP_POSIX_C), str(IVSHM_CLIENT_C)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        assert r.returncode == 0, "the vss build of %s must compile clean under -Werror:\n%s" % (src.name, r.stderr)
    return d


# ============================================================ C5: the switch's values

@pytest.mark.parametrize("value", ["0x00", "0x04", "0x08", "0x18", "0x1D", "0x20", None])
def test_c5_every_other_defined_value_stops_with_the_switch_error(value, tmp_path):
    # None is a bare -DMONITOR_EXT_KINDS, which gcc defines as 1. 0x18 and 0x1D carry bit 4, so they also
    # reach the generated includes; the value check comes first and must fire whatever follows.
    define = "-DMONITOR_EXT_KINDS" if value is None else "-DMONITOR_EXT_KINDS=" + value
    r = _compile_object(_gcc(), DEFAULT_FLAGS + ("-ffp-contract=off", define), tmp_path)
    assert r.returncode != 0 and SWITCH_ERROR in r.stderr, r.stderr


@NEEDS_GEN
def test_c5_ctl_compiles_with_a_generated_vss_ctl_h(tmp_path):
    # Phase 8 WP1b (was ...stop_as_not_implemented_while_the_deviation_stands[0x14]): WP1a
    # narrowed the deviation to 0x1C, and sdv/vss/generate.py writes kind 2's contract beside kind 4's, so the ctl build
    # compiles clean under -Wundef -Werror with nothing but the generation on the include path, and takes vss_ctl.h
    # from there. A generation without vss_ctl.h is one the generator no longer writes: regenerate.
    assert (GEN / "vss_ctl.h").is_file(), "sdv-out/gen has no vss_ctl.h: regenerate it with " + GENERATOR
    flags = DEFAULT_FLAGS + ("-ffp-contract=off", "-DMONITOR_EXT_KINDS=0x14")
    r = _compile_object(_gcc(), flags, tmp_path)
    assert r.returncode == 0, "the ctl build must compile clean against the generated vss_ctl.h:\n" + r.stderr
    deps = subprocess.run([_gcc(), "-std=gnu99", "-DMONITOR_EXT_KINDS=0x14", "-I", str(COMMON), "-I", str(GEN), "-MM",
                           str(MONITOR_C)], check=True, capture_output=True, text=True).stdout
    assert str(GEN / "vss_ctl.h") in deps and all(str(GEN / h) in deps for h in GEN_HEADERS), deps


def test_c5_gap_stops_as_not_implemented_while_the_deviation_stands(tmp_path):
    # Phase 2 design decision d, narrowed in Phase 8 (WP1a; was ...[0x1C]): section 11 accepts 0x1C, but kind 3 does not
    # exist yet. The deviation's #error stands before any include, so a generation with vss_ctl.h changes nothing.
    r = _compile_object(_gcc(), DEFAULT_FLAGS + ("-ffp-contract=off", "-DMONITOR_EXT_KINDS=0x1C"), tmp_path)
    assert r.returncode != 0 and NOT_IMPLEMENTED in r.stderr and "0x1C (gap)" in r.stderr, r.stderr
    assert SWITCH_ERROR not in r.stderr, "the value check itself passes the spec's three values"


def test_c5_the_vss_build_and_its_driver_compile_clean(native_vss):
    assert (native_vss / "monitor").is_file() and (native_vss / "driver").is_file()


@NEEDS_GEN
def test_c5_the_driver_sees_the_generated_contract_through_monitor_c(native_vss):
    spec = importlib.util.spec_from_file_location("vss_contract_wp1", str(GEN / "vss_contract.py"))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = subprocess.run([str(native_vss / "driver")], check=True, capture_output=True, text=True).stdout
    lines = dict(ln.split(" ", 1) for ln in out.splitlines() if not ln.startswith("profile "))
    assert lines["ext_kinds"] == "0x10"
    assert int(lines["format"]) == mod.FORMAT == 1
    assert lines["flt_eval_method"] == "0"
    assert tuple(int(x, 16) for x in lines["uids"].split()) == mod.SLOT_UIDS
    assert int(lines["digest"], 16) == mod.CATALOG_DIGEST
    assert int(lines["age_max_ms"]) == mod.AGE_MAX_MS
    assert [float.fromhex(x) for x in lines["consts"].split()] == [mod.DEG_PER_RAD, mod.RAD_PER_DEG, mod.M_PER_MM]
    rows = [ln.split()[1:] for ln in out.splitlines() if ln.startswith("profile ")]
    compiled = [p for p in mod.PROFILES if p["compiled"]]
    assert [int(r[0]) for r in rows] == [p["id"] for p in compiled] == list(mod.COMPILED_PROFILE_IDS)
    for row, p in zip(rows, compiled):
        assert int(row[1]) == p["l_mm"]
        want = [p["v_max"], p["a_max"], p["delta_max"], p["v26_lo"], p["v26_hi"],
                0.0 if p["ay26_max"] is None else p["ay26_max"], p["tol26"], p["v_tol"]]
        assert [float.fromhex(x) for x in row[2:]] == want
    assert lines["ids"] == "%s count %d" % (" ".join(str(i) for i in mod.COMPILED_PROFILE_IDS), len(compiled))


@NEEDS_GEN
@pytest.mark.parametrize("edit", ["format 2", "no format"])
def test_c5_a_contract_of_another_format_stops_the_vss_build(edit, tmp_path):
    gen = tmp_path / "gen"
    gen.mkdir()
    for h in GEN_HEADERS:
        shutil.copy2(GEN / h, gen / h)
    text = (gen / "vss_contract.h").read_text(encoding="ascii")
    line = "#define VSS_CONTRACT_FORMAT 1u\n"
    assert text.count(line) == 1
    (gen / "vss_contract.h").write_text(text.replace(line, "#define VSS_CONTRACT_FORMAT 2u\n" if edit == "format 2" else ""),
                                        encoding="ascii")
    r = _compile_object(_gcc(), VSS_FLAGS, tmp_path, gen=gen)
    assert r.returncode != 0 and FORMAT_ERROR in r.stderr, r.stderr
    assert UNDEF_DIAG not in r.stderr, "the guard tests definedness before it reads the macro:\n" + r.stderr


@NEEDS_GEN
@pytest.mark.parametrize("how", ["undefined", "x87"])
def test_c5_a_wider_float_evaluation_stops_the_vss_build(how, tmp_path):
    # x87 arithmetic (FLT_EVAL_METHOD 2) is a real configuration on x86-64; an undefined macro is the
    # definedness half of the guard.
    if how == "x87" and platform.machine() not in ("x86_64", "AMD64"):
        pytest.skip("-mfpmath=387 is an x86 option")
    extra = ("-U__FLT_EVAL_METHOD__",) if how == "undefined" else ("-mfpmath=387",)
    r = _compile_object(_gcc(), VSS_FLAGS + extra, tmp_path)
    assert r.returncode != 0 and FLT_EVAL_ERROR in r.stderr, r.stderr
    assert UNDEF_DIAG not in r.stderr, "the guard tests definedness before it reads the macro:\n" + r.stderr


def test_c5_the_default_build_compiles_and_includes_no_generated_header(tmp_path):
    gcc = _gcc()
    r = _compile_object(gcc, DEFAULT_FLAGS, tmp_path)
    assert r.returncode == 0, ("with the switch undefined the default paths compile under -Wformat=2 -Wundef -Werror "
                               "(a guard that reads the undefined switch as 0 fails here):\n" + r.stderr)
    deps = subprocess.run([gcc, "-std=gnu99", "-I", str(COMMON), "-I", str(GEN), "-MM", str(MONITOR_C)],
                          check=True, capture_output=True, text=True).stdout
    assert not any(h in deps for h in GEN_HEADERS), deps


@NEEDS_GEN
def test_c5_the_vss_build_depends_on_both_generated_headers():
    deps = subprocess.run([_gcc(), "-std=gnu99", "-DMONITOR_EXT_KINDS=0x10", "-I", str(COMMON), "-I", str(GEN),
                           "-MM", str(MONITOR_C)], check=True, capture_output=True, text=True).stdout
    assert all(h in deps for h in GEN_HEADERS), deps


@pytest.mark.parametrize("unit", ["default", pytest.param("vss", marks=NEEDS_GEN)])
def test_c5_the_default_and_vss_units_hold_no_stray_semicolon(unit):
    # Only bare #if blocks, no stray ';' -- in the default unit, or a guarded block's leftover
    # in the vss one. -Wall -Wextra say nothing about an empty declaration at file scope; -Wpedantic does.
    extra = ("-ffp-contract=off", "-DMONITOR_EXT_KINDS=0x10") if unit == "vss" else ()
    r = subprocess.run([_gcc(), *PEDANTIC_FLAGS, *extra, "-I", str(COMMON), "-I", str(GEN), str(MONITOR_C)],
                       capture_output=True, text=True)
    assert r.returncode == 0, "the %s unit must be clean under -Wpedantic:\n%s" % (unit, r.stderr)


def test_c5_someip_c_still_builds_under_werror(tmp_path):
    # Its include of monitor.c defines no switch (section 11, Unaffected); the line is tests/test_someip.py's.
    r = subprocess.run([_gcc(), "-std=gnu99", "-Wall", "-Wextra", "-Wformat=2", "-Werror", "-O2", "-pthread",
                        "-I", str(COMMON), "-o", str(tmp_path / "someip"), str(SOMEIP_C), str(SHM_MAP_POSIX_C),
                        str(IVSHM_CLIENT_C)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


# ============================================================ C6 and the Makefile's other targets

# The six default recipes as main had them at 4ee3e532 (Makefile lines 57-73 there): textually unchanged.
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
CFLAGS_LINE = "CFLAGS  := -std=gnu99 -Wall -Wextra -Wformat=2 -O2 -I../common"
QCC = "qcc -Vgcc_ntoaarch64le -std=gnu99 -Wall -Wextra -Wformat=2 -O2 -I../common"
DEFAULT_BINS = ("qnx-safety-monitor", "qnx-safety-monitor-svc", "qnx-safety-monitor-live", "qnx-safety-monitor-stamp",
                "qnx-safety-monitor-bell", "qnx-safety-monitor-unmask")
VSS_BIN = "qnx-safety-monitor-vss"
VSS_LINE = (QCC + " -ffp-contract=off -DMONITOR_EXT_KINDS=0x10 -I../../sdv-out/gen -o " + VSS_BIN
            + " monitor.c ../common/shm_map_qnx.c -lsocket")
# The vss rules as the Makefile has them since Phase 2 (WP1, the critic's -B fix): textually unchanged by Phase 7.
VSS_RECIPE = ("\t$(CC) $(TARGET) $(CFLAGS) -ffp-contract=off -DMONITOR_EXT_KINDS=0x10 -I$(VSS_GEN) -o $@ monitor.c "
              "../common/shm_map_qnx.c $(LDFLAGS)")
VSS_RULES = ("$(VSS): $(SRCS) $(VSS_GEN)/vss_contract.h $(VSS_GEN)/vss_profiles.h\n" + VSS_RECIPE + "\n",
             "$(VSS_GEN)/vss_contract.h $(VSS_GEN)/vss_profiles.h:\n\t$(if $(wildcard $@),,$(error $@ is missing: generate the "
             "kind 4 contract with sdv/vss/generate.py (sdv/vss/README.md), or point VSS_GEN at its output))\n")
# Phase 7 WP4a: the profile-3 build, under its own host name. Not the spec's qnx-safety-monitor-vss-carla: that
# name holds "qnx-safety-monitor-vss", which tests/test_ifs_vss.py refuses in every build file but ifs-vss.build.
VSS_CARLA_BIN = "qnx-safety-monitor-carla"
VSS_CARLA_LINE = (QCC + " -ffp-contract=off -DMONITOR_EXT_KINDS=0x10 -I../../sdv-out/gen -o " + VSS_CARLA_BIN
                  + " monitor.c ../common/shm_map_qnx.c -lsocket")
VSS_CARLA_RECIPE = VSS_RECIPE.replace("$(VSS_GEN)", "$(VSS_CARLA_GEN)")
PROFILE3_ERROR = "holds no profile 3"
# A missing header's message for vss-carla names its own knob, in the default directory too; vss's message names
# VSS_GEN.
CARLA_KNOB, VSS_KNOB = "or point VSS_CARLA_GEN at its output", "or point VSS_GEN at its output"
SHADOW_ERROR = "would be compiled instead of the contract in"
CLEAN_SENTENCE = ("`make clean` does not remove the binary: the Phase 7 spec (7.1) keeps every other recipe, clean's "
                  "included, as it was.")
# The Makefile's SRCS, relative to its directory; the temporary copy holds exactly these.
MAKE_SRCS = ("monitor.c", "../common/shm_map_qnx.c", "../common/frame.h", "../common/frame_io.h", "../common/shm_chan.h",
             "../common/shm_map.h")
T0 = 1_700_000_000


def _profiles_h(ids, listed=None):
    """A stand-in vss_profiles.h in sdv/vss/generate.py's form (render_c_profiles): one X() row per id, the
    rows' values the base profile 1's. listed replaces the VSS_PROFILE_IDS line, to show the rows are read."""
    rows = ["    X(%du, 2700u, 40.0, 10.0, 40.0, 1.0, 20.0, 0.0, 3.0, 1.0)" % i for i in ids]
    lines = ["/* vss_profiles.h -- a stand-in in the generator's form.",
             " *   X(id, l_mm, v_max, a_max, delta_max, v26_lo, v26_hi, ay26_max, tol26, v_tol)", " */",
             "#ifndef VSS_PROFILES_H", "#define VSS_PROFILES_H", "", "#define VSS_PROFILE_TABLE(X) \\"]
    lines += [r + (" \\" if n < len(rows) - 1 else "") for n, r in enumerate(rows)]
    lines += ["", "#define VSS_PROFILE_COUNT %du" % len(ids),
              '#define VSS_PROFILE_IDS "%s"' % (" ".join(str(i) for i in ids) if listed is None else listed), "",
              "#endif /* VSS_PROFILES_H */", ""]
    return "\n".join(lines)


def _make_tree(tmp_path, headers=GEN_HEADERS, profile_ids=None, listed=None):
    """A copy of what the Makefile reads, at its repo-relative places, with the given generated headers.
    The headers are stand-ins: make only looks at their names and times, and with profile_ids (the vss-carla
    tests) at vss_profiles.h's X() rows, which are then written in the generator's form."""
    root = tmp_path / "tree"
    mdir = root / "ipc-test" / "qnx-safety-monitor"
    mdir.mkdir(parents=True)
    (root / "ipc-test" / "common").mkdir()
    shutil.copy2(MAKEFILE, mdir / "Makefile")
    for rel in MAKE_SRCS:
        dst = mdir / rel
        shutil.copy2(MON_DIR / rel, dst)
        os.utime(dst, (T0, T0))
    if headers:
        gen = root / "sdv-out" / "gen"
        gen.mkdir(parents=True)
        for h in headers:
            if h == "vss_profiles.h" and profile_ids is not None:
                (gen / h).write_text(_profiles_h(profile_ids, listed), encoding="ascii")
            else:
                (gen / h).write_text("/* stand-in for make's timestamps */\n", encoding="ascii")
            os.utime(gen / h, (T0, T0))
    return mdir


def _run_make(mdir, *args):
    r = subprocess.run([_make(), "--no-print-directory", *args], cwd=str(mdir), capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def _recipe_lines(out):
    return [ln for ln in out.splitlines() if ln.strip()]


@pytest.mark.parametrize("always", [(), ("-B",)], ids=["plain", "B"])
@pytest.mark.parametrize("absent", [GEN_HEADERS, ("vss_contract.h",), ("vss_profiles.h",)])
def test_c6_make_vss_without_a_generated_header_names_the_generator(absent, always, tmp_path):
    mdir = _make_tree(tmp_path, headers=tuple(h for h in GEN_HEADERS if h not in absent))
    rc, out, err = _run_make(mdir, "-n", *always, "vss")
    assert rc != 0 and GENERATOR in err, (rc, out, err)
    assert "qcc" not in out, "no compile line may be planned without the contract"


def test_c6_make_B_vss_with_both_headers_plans_exactly_the_vss_line(tmp_path):
    # FOUND BY REVIEW: -B remakes the header targets too, and an unconditional $(error)
    # in their recipe stopped `make -B vss` with "vss_contract.h is missing" while both headers existed.
    mdir = _make_tree(tmp_path)
    rc, out, err = _run_make(mdir, "-n", "-B", "vss")
    assert rc == 0, (rc, out, err)
    assert _recipe_lines(out) == [VSS_LINE], out
    assert "is missing" not in err, err


def test_c6_a_real_make_vss_without_the_contract_stops_before_any_compiler(tmp_path):
    # CC is a stand-in that leaves a mark, so this can never run qcc.
    mdir = _make_tree(tmp_path, headers=())
    mark = tmp_path / "compiler-ran"
    fake = tmp_path / "fake-cc"
    fake.write_text("#!/bin/sh\ntouch '%s'\nexit 1\n" % mark, encoding="ascii")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    rc, out, err = _run_make(mdir, "vss", "CC=" + str(fake))
    assert rc != 0 and GENERATOR in err, (rc, out, err)
    assert not mark.exists() and not (mdir / VSS_BIN).exists()


@pytest.mark.parametrize("touched", GEN_HEADERS + ("monitor.c",))
def test_c6_make_q_vss_sees_a_touched_header(touched, tmp_path):
    mdir = _make_tree(tmp_path)
    stub = mdir / VSS_BIN
    stub.write_text("stub, newer than every input\n", encoding="ascii")
    os.utime(stub, (T0 + 10, T0 + 10))
    assert _run_make(mdir, "-q", "vss")[0] == 0, "the stub target is up to date before anything is touched"
    path = mdir / touched if touched == "monitor.c" else mdir.parent.parent / "sdv-out" / "gen" / touched
    os.utime(path, (T0 + 20, T0 + 20))
    assert _run_make(mdir, "-q", "vss")[0] == 1, "make must rebuild after %s changed" % touched


def test_c6_the_vss_recipe_carries_the_switch_the_flag_and_the_contract_directory(tmp_path):
    mdir = _make_tree(tmp_path)
    rc, out, err = _run_make(mdir, "-n", "vss")
    assert rc == 0, err
    assert _recipe_lines(out) == [VSS_LINE]
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    for h in GEN_HEADERS:
        (elsewhere / h).write_text("/* stand-in */\n", encoding="ascii")
    rc, out, err = _run_make(mdir, "-n", "vss", "VSS_GEN=" + str(elsewhere))
    assert rc == 0 and ("-I%s -o %s" % (elsewhere, VSS_BIN)) in out, (out, err)


def test_the_default_targets_build_exactly_as_before_with_no_switch(tmp_path):
    mdir = _make_tree(tmp_path, headers=())
    rc, out, err = _run_make(mdir, "-n", "-B", "all", "svc", "live", "stamp", "bell", "unmask")
    assert rc == 0, err
    assert _recipe_lines(out) == [QCC + " -o %s monitor.c ../common/shm_map_qnx.c -lsocket" % b for b in DEFAULT_BINS]
    rc, out, err = _run_make(mdir, "-n", "clean")
    assert rc == 0 and _recipe_lines(out) == ["rm -f " + " ".join(DEFAULT_BINS + (VSS_BIN,))], (out, err)


def test_the_makefile_keeps_cflags_and_the_six_recipes_textually():
    text = MAKEFILE.read_text(encoding="ascii")
    assert DEFAULT_RULES in text, "recipes 57-73 of 4ee3e532 are unchanged"
    for rule in VSS_RULES:
        assert text.count(rule) == 1, "the vss rules are unchanged: " + rule
    cflags = [ln for ln in text.splitlines() if ln.startswith("CFLAGS")]
    assert cflags == [CFLAGS_LINE], "never put the switch (or any -D) in CFLAGS"
    # -D stands in the three extension-kind recipes alone (Phase 7 WP4a added vss-carla's, Phase 8 WP1b ctl's): the two
    # vss ones exactly the vss flags, ctl's exactly those with its switch value and its contract directory.
    ctl_recipe = VSS_RECIPE.replace("-DMONITOR_EXT_KINDS=0x10 -I$(VSS_GEN)", "-DMONITOR_EXT_KINDS=0x14 -I$(CTL_GEN)")
    assert ctl_recipe != VSS_RECIPE
    defines = [ln for ln in text.splitlines() if "-D" in ln and not ln.startswith("#")]
    assert defines == [VSS_RECIPE, VSS_CARLA_RECIPE, ctl_recipe], defines


# ============================================================ Phase 7 WP4a: make vss-carla (the profile-3 build)

def _fake_cc(tmp_path):
    """A compiler stand-in that leaves a mark and fails, so no test here can run qcc or write the binary."""
    mark = tmp_path / "compiler-ran"
    fake = tmp_path / "fake-cc"
    fake.write_text("#!/bin/sh\ntouch '%s'\nexit 1\n" % mark, encoding="ascii")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    return mark, fake


def _gen_dir(path, profile_ids=(3,), headers=GEN_HEADERS):
    """A contract directory outside the tree, for VSS_CARLA_GEN."""
    path.mkdir()
    for h in headers:
        (path / h).write_text(_profiles_h(profile_ids) if h == "vss_profiles.h" else "/* stand-in */\n", encoding="ascii")
    return path


def test_vss_carla_plans_the_vss_line_under_its_own_name(tmp_path):
    assert VSS_CARLA_LINE == VSS_LINE.replace(" -o %s " % VSS_BIN, " -o %s " % VSS_CARLA_BIN), "the vss recipe's flags exactly"
    mdir = _make_tree(tmp_path, profile_ids=(1, 2, 3))
    for always in ((), ("-B",)):
        rc, out, err = _run_make(mdir, "-n", *always, "vss-carla")
        # err empty: the guard's line expands to nothing, and no rule is defined twice (make would warn).
        assert rc == 0 and _recipe_lines(out) == [VSS_CARLA_LINE] and err == "", (always, rc, out, err)
        rc, out, err = _run_make(mdir, "-n", *always, "vss")
        assert rc == 0 and _recipe_lines(out) == [VSS_LINE] and err == "", (always, rc, out, err)
    elsewhere = _gen_dir(tmp_path / "elsewhere")
    rc, out, err = _run_make(mdir, "-n", "vss-carla", "VSS_CARLA_GEN=" + str(elsewhere))
    assert rc == 0 and _recipe_lines(out) == [VSS_CARLA_LINE.replace("-I../../sdv-out/gen ", "-I%s " % elsewhere)], (out, err)
    rc, out, err = _run_make(mdir, "-n", "vss", "VSS_CARLA_GEN=" + str(elsewhere))
    assert rc == 0 and _recipe_lines(out) == [VSS_LINE], "VSS_CARLA_GEN is vss-carla's alone"


def test_vss_carla_guard_reads_the_table_of_vss_carla_gen_not_the_default(tmp_path):
    # The default table has row 3 and VSS_CARLA_GEN's lacks it: refused, naming that directory.
    mdir = _make_tree(tmp_path / "a", profile_ids=(1, 2, 3))
    elsewhere = _gen_dir(tmp_path / "elsewhere", profile_ids=(1, 2))
    rc, out, err = _run_make(mdir, "-n", "vss-carla", "VSS_CARLA_GEN=" + str(elsewhere))
    assert rc != 0 and PROFILE3_ERROR in err and str(elsewhere) in err and "qcc" not in out, (rc, out, err)
    # The converse: the default lacks it and VSS_CARLA_GEN's has it: planned against that directory.
    mdir = _make_tree(tmp_path / "b", profile_ids=(1, 2))
    p3 = _gen_dir(tmp_path / "p3", profile_ids=(1, 2, 3))
    rc, out, err = _run_make(mdir, "-n", "vss-carla", "VSS_CARLA_GEN=" + str(p3))
    assert rc == 0 and _recipe_lines(out) == [VSS_CARLA_LINE.replace("-I../../sdv-out/gen ", "-I%s " % p3)], (rc, out, err)


def test_vss_carla_gen_is_read_from_the_environment(tmp_path, monkeypatch):
    # VSS_CARLA_GEN ?= (spec 7.1): a value in the environment wins over the default.
    mdir = _make_tree(tmp_path, profile_ids=(1, 2))
    p3 = _gen_dir(tmp_path / "p3", profile_ids=(1, 2, 3))
    monkeypatch.setenv("VSS_CARLA_GEN", str(p3))
    rc, out, err = _run_make(mdir, "-n", "vss-carla")
    assert rc == 0 and _recipe_lines(out) == [VSS_CARLA_LINE.replace("-I../../sdv-out/gen ", "-I%s " % p3)], (rc, out, err)


@pytest.mark.parametrize("always", [(), ("-B",)], ids=["plain", "B"])
@pytest.mark.parametrize("ids,listed",
                         [((1, 2), None), ((1, 2), "1 2 3"), ((1, 2, 13), None), ((1, 2, 30), None), ((), None),
                          ((1, 2, 33), None), ((4,), "3")],
                         ids=["rows 1 2", "rows 1 2 listed as 1 2 3", "row 13", "row 30", "no row", "row 33",
                              "row 4 listed as 3"])
def test_vss_carla_without_a_profile_3_row_stops_before_any_compiler(ids, listed, always, tmp_path):
    mdir = _make_tree(tmp_path, profile_ids=ids, listed=listed)
    rc, out, err = _run_make(mdir, "-n", *always, "vss-carla")
    assert rc != 0 and PROFILE3_ERROR in err and GENERATOR in err and "or point VSS_CARLA_GEN at one" in err, (rc, out, err)
    assert "qcc" not in out, "no compile line may be planned without profile 3"
    # The guard is vss-carla's alone: the vss target plans its line from the same table.
    rc, out, err = _run_make(mdir, "-n", *always, "vss")
    assert rc == 0 and _recipe_lines(out) == [VSS_LINE], (rc, out, err)


@pytest.mark.parametrize("ids", [(3,), (1, 2, 3), (3, 1, 2), (2, 3, 4), (3, 13), (30, 3), (1, 2, 3, 4, 5)])
def test_vss_carla_with_a_profile_3_row_anywhere_in_the_table_plans_its_line(ids, tmp_path):
    rc, out, err = _run_make(_make_tree(tmp_path, profile_ids=ids), "-n", "vss-carla")
    assert rc == 0 and _recipe_lines(out) == [VSS_CARLA_LINE], (rc, out, err)


@pytest.mark.parametrize("always", [(), ("-B",)], ids=["plain", "B"])
@pytest.mark.parametrize("absent", [GEN_HEADERS, ("vss_contract.h",), ("vss_profiles.h",)])
def test_make_vss_carla_without_a_generated_header_names_the_generator(absent, always, tmp_path):
    mdir = _make_tree(tmp_path, headers=tuple(h for h in GEN_HEADERS if h not in absent), profile_ids=(1, 2, 3))
    rc, out, err = _run_make(mdir, "-n", *always, "vss-carla")
    assert rc != 0 and GENERATOR in err and "is missing" in err, (rc, out, err)
    assert "qcc" not in out, "no compile line may be planned without the contract"


@pytest.mark.parametrize("absent", [GEN_HEADERS, ("vss_contract.h",), ("vss_profiles.h",)])
def test_make_vss_carla_names_its_own_directory_when_a_header_is_missing_there(absent, tmp_path):
    # The default directory is complete; VSS_CARLA_GEN points at one that is not, and the message says which knob.
    mdir = _make_tree(tmp_path, profile_ids=(1, 2, 3))
    elsewhere = _gen_dir(tmp_path / "elsewhere", headers=tuple(h for h in GEN_HEADERS if h not in absent))
    rc, out, err = _run_make(mdir, "-n", "vss-carla", "VSS_CARLA_GEN=" + str(elsewhere))
    assert rc != 0 and GENERATOR in err and "VSS_CARLA_GEN" in err and str(elsewhere) in err, (rc, out, err)
    assert "qcc" not in out


@pytest.mark.parametrize("always", [(), ("-B",)], ids=["plain", "B"])
@pytest.mark.parametrize("goal", ["vss-carla", VSS_CARLA_BIN])
@pytest.mark.parametrize("absent", [GEN_HEADERS, ("vss_contract.h",), ("vss_profiles.h",)],
                         ids=["both", "contract", "profiles"])
def test_make_vss_carla_names_its_own_knob_when_a_header_is_missing_in_the_default_directory(absent, goal, always, tmp_path):
    # FOUND BY REVIEW: with VSS_CARLA_GEN at its default, vss-carla's headers are vss's files and
    # met vss's rule, whose message names VSS_GEN, a knob vss-carla does not read. Asked for by name (the target or
    # its binary) it checks them as the Makefile is read and names VSS_CARLA_GEN; `make vss` keeps its own message.
    mdir = _make_tree(tmp_path, headers=tuple(h for h in GEN_HEADERS if h not in absent), profile_ids=(1, 2, 3))
    missing = "../../sdv-out/gen/%s is missing" % absent[0]
    rc, out, err = _run_make(mdir, "-n", *always, goal)
    assert rc != 0 and missing in err and GENERATOR in err and CARLA_KNOB in err and VSS_KNOB not in err, (rc, out, err)
    assert "qcc" not in out, "no compile line may be planned without the contract"
    rc, out, err = _run_make(mdir, "-n", *always, "vss")
    assert rc != 0 and missing in err and VSS_KNOB in err and "VSS_CARLA_GEN" not in err, (rc, out, err)


@pytest.mark.parametrize("case", ["no contract", "no profile 3", "profile 3"])
def test_a_real_make_vss_carla_runs_the_compiler_only_with_the_contract_and_profile_3(case, tmp_path):
    if case == "no contract":
        mdir = _make_tree(tmp_path, headers=())
    else:
        mdir = _make_tree(tmp_path, profile_ids=(1, 2) if case == "no profile 3" else (1, 2, 3))
    mark, fake = _fake_cc(tmp_path)
    rc, out, err = _run_make(mdir, "vss-carla", "CC=" + str(fake))
    assert rc != 0, "the stand-in compiler fails, so every case fails"
    if case == "profile 3":
        assert mark.exists(), "the control: with the contract and a profile 3 row the compiler runs"
    else:
        assert not mark.exists() and GENERATOR in err, (case, err)
    assert not (mdir / VSS_CARLA_BIN).exists()


@pytest.mark.parametrize("header", GEN_HEADERS)
@pytest.mark.parametrize("where", ["beside monitor.c", "in common"])
def test_make_vss_carla_refuses_a_contract_header_the_compiler_would_include_first(where, header, tmp_path):
    # FOUND BY REVIEW: monitor.c includes the contract with quotes, so its own directory and
    # CFLAGS's -I../common come before -I$(VSS_CARLA_GEN), and a copy there would be compiled, not the table the guard
    # read. The stray table holds row 3 too: any copy but VSS_CARLA_GEN's own stops the build before any compiler.
    mdir = _make_tree(tmp_path, profile_ids=(1, 2, 3))
    stray = (mdir if where == "beside monitor.c" else mdir.parent / "common") / header
    stray.write_text(_profiles_h((1, 2, 3)) if header == "vss_profiles.h" else "/* stray */\n", encoding="ascii")
    rc, out, err = _run_make(mdir, "-n", "vss-carla")
    assert rc != 0 and SHADOW_ERROR in err and os.path.realpath(str(stray)) in err and "qcc" not in out, (rc, out, err)
    mark, fake = _fake_cc(tmp_path)
    rc, out, err = _run_make(mdir, "vss-carla", "CC=" + str(fake))
    assert rc != 0 and SHADOW_ERROR in err and not mark.exists(), (rc, out, err)
    assert not (mdir / VSS_CARLA_BIN).exists()
    # The vss rules stay as they were (spec 7.1), the same include order with them.
    rc, out, err = _run_make(mdir, "-n", "vss")
    assert rc == 0 and _recipe_lines(out) == [VSS_LINE], (rc, out, err)


@pytest.mark.parametrize("own", [".", "../common"])
def test_make_vss_carla_takes_a_header_that_is_vss_carla_gen_s_own(own, tmp_path):
    # The control of the test above: VSS_CARLA_GEN at monitor.c's directory or at ../common is no stray to itself.
    mdir = _make_tree(tmp_path, headers=())
    for h in GEN_HEADERS:
        (mdir / own / h).write_text(_profiles_h((1, 2, 3)) if h == "vss_profiles.h" else "/* stand-in */\n",
                                    encoding="ascii")
    rc, out, err = _run_make(mdir, "-n", "vss-carla", "VSS_CARLA_GEN=" + own)
    assert rc == 0 and _recipe_lines(out) == [VSS_CARLA_LINE.replace("-I../../sdv-out/gen ", "-I%s " % own)], (rc, out, err)


@pytest.mark.parametrize("touched", GEN_HEADERS + ("monitor.c",))
def test_make_q_vss_carla_sees_a_touched_input(touched, tmp_path):
    mdir = _make_tree(tmp_path, profile_ids=(1, 2, 3))
    stub = mdir / VSS_CARLA_BIN
    stub.write_text("stub, newer than every input\n", encoding="ascii")
    os.utime(stub, (T0 + 10, T0 + 10))
    assert _run_make(mdir, "-q", "vss-carla")[0] == 0, "the stub target is up to date before anything is touched"
    path = mdir / touched if touched == "monitor.c" else mdir.parent.parent / "sdv-out" / "gen" / touched
    os.utime(path, (T0 + 20, T0 + 20))
    assert _run_make(mdir, "-q", "vss-carla")[0] == 1, "make must rebuild after %s changed" % touched


def test_make_q_vss_carla_meets_the_guard_when_a_new_table_lacks_profile_3(tmp_path):
    mdir = _make_tree(tmp_path, profile_ids=(1, 2, 3))
    stub = mdir / VSS_CARLA_BIN
    stub.write_text("stub, newer than every input\n", encoding="ascii")
    os.utime(stub, (T0 + 10, T0 + 10))
    table = mdir.parent.parent / "sdv-out" / "gen" / "vss_profiles.h"
    table.write_text(_profiles_h((1, 2)), encoding="ascii")
    os.utime(table, (T0 + 20, T0 + 20))
    rc, out, err = _run_make(mdir, "-q", "vss-carla")
    assert rc == 2 and PROFILE3_ERROR in err, (rc, out, err)


@NEEDS_GEN
def test_make_vss_carla_against_the_real_generation_follows_its_compiled_set(tmp_path):
    # The guard reads the X() rows as sdv/vss/generate.py writes them: profile 3 is planned exactly when the
    # generation compiles it (the base tree's does not; WP2's frozen profile 3 does).
    mdir = _make_tree(tmp_path, headers=())
    gen = mdir.parent.parent / "sdv-out" / "gen"
    gen.mkdir(parents=True)
    for h in GEN_HEADERS:
        shutil.copy2(GEN / h, gen / h)
    spec = importlib.util.spec_from_file_location("vss_contract_wp4a", str(GEN / "vss_contract.py"))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # The guard's word against the renderer's form: each compiled id's row, and no other, stands as a whole word of
    # the real header (make's $(filter) splits on whitespace as str.split does), so the stand-ins above are its form.
    words = (GEN / "vss_profiles.h").read_text(encoding="ascii").split()
    assert [i for i in (1, 2, 3) if "X(%du," % i in words] == [i for i in (1, 2, 3) if i in mod.COMPILED_PROFILE_IDS]
    rc, out, err = _run_make(mdir, "-n", "vss-carla")
    if 3 in mod.COMPILED_PROFILE_IDS:
        assert rc == 0 and _recipe_lines(out) == [VSS_CARLA_LINE], (rc, out, err)
    else:
        assert rc != 0 and PROFILE3_ERROR in err and "qcc" not in out, (rc, out, err)


def test_the_vss_carla_binary_is_ignored_beside_the_vss_one(tmp_path):
    # Textual: the git-running tests are the Windows side's (sdv/stack/wsl-pytest.args); git check-ignore is read
    # there by hand. The name is the one make writes, so the ignore line and the recipe cannot drift apart.
    rc, out, err = _run_make(_make_tree(tmp_path, profile_ids=(1, 2, 3)), "-n", "vss-carla")
    assert rc == 0, err
    written = out.split(" -o ", 1)[1].split()[0]
    assert written == VSS_CARLA_BIN
    lines = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    at = lines.index("ipc-test/qnx-safety-monitor/" + VSS_BIN)
    assert lines[at + 1] == "ipc-test/qnx-safety-monitor/" + written, lines[at:at + 2]
    assert [ln for ln in lines if ln.startswith("!") and written in ln] == [], "nothing re-includes it"


def test_the_makefile_says_clean_leaves_the_vss_carla_binary(tmp_path):
    # FOUND BY REVIEW: `make clean` leaves qnx-safety-monitor-carla, since spec
    # 7.1 keeps every other recipe as it was; the comment that names the binary says so, beside the behaviour.
    rc, out, err = _run_make(_make_tree(tmp_path, headers=()), "-n", "clean")
    assert rc == 0 and _recipe_lines(out) and VSS_CARLA_BIN not in out, (out, err)
    lines = MAKEFILE.read_text(encoding="ascii").splitlines()
    at = start = next(n for n, ln in enumerate(lines) if ln.startswith("VSS_CARLA :="))
    while lines[start - 1].startswith("#"):
        start -= 1
    comment = " ".join(" ".join(ln.lstrip("#").strip() for ln in lines[start:at]).split())
    assert CLEAN_SENTENCE in comment, comment


# ============================================================ C32: build-monitor-native.sh

DEFAULT_SOURCES = (MONITOR_C, SHM_MAP_POSIX_C, IVSHM_CLIENT_C, COMMON / "frame.h", COMMON / "frame_io.h",
                   COMMON / "shm_chan.h", COMMON / "shm_map.h", COMMON / "ivshm_client.h")
# The line the switch adds to the source-sha256 input, after the two headers.
SWITCH_HASH_LINE = b"MONITOR_EXT_KINDS=0x10 -ffp-contract=off\n"
DEFAULT_GCC_LINE = '"${CC}" -O2 -std=gnu99 -Wall -Wextra -I "${INC}" -o "${OUT}" "${SRC}" "${MAP}" "${IVC}"'


def _default_argv(out):
    return ["-O2", "-std=gnu99", "-Wall", "-Wextra", "-I", str(COMMON), "-o", str(out),
            str(MONITOR_C), str(SHM_MAP_POSIX_C), str(IVSHM_CLIENT_C)]


def _sha256(*parts):
    return hashlib.sha256(b"".join(parts)).hexdigest()


class _Native:
    """Runs build-monitor-native.sh with a CC that records its argv, then compiles with gcc."""

    def __init__(self, tmp_path):
        gcc = _gcc()
        self.tmp = tmp_path
        self.home = tmp_path / "home"
        self.home.mkdir()
        self.log = tmp_path / "cc-argv"
        self.cc = tmp_path / "cc-rec"
        self.cc.write_text('#!/bin/sh\nprintf "%%s\\n" "$@" > "%s"\nexec "%s" "$@"\n' % (self.log, gcc), encoding="ascii")
        self.cc.chmod(self.cc.stat().st_mode | stat.S_IXUSR)

    def run(self, **env):
        # The script's inputs, and the generic names they replaced, never leak in from the runner's environment.
        e = {k: v for k, v in os.environ.items()
             if k not in ("MONITOR_EXT_KINDS", "MONITOR_VSS_GEN", "EXT_KINDS", "VSS_GEN", "OUT", "FORCE")}
        e.update(HOME=str(self.home), CC=str(self.cc))
        e.update({k: str(v) for k, v in env.items()})
        if self.log.exists():
            self.log.unlink()
        return subprocess.run(["bash", str(NATIVE)], env=e, capture_output=True, text=True, timeout=120)

    def argv(self):
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else None


@pytest.fixture
def native(tmp_path):
    return _Native(tmp_path)


def _gen_copy(tmp_path):
    gen = tmp_path / "gen"
    gen.mkdir()
    for h in GEN_HEADERS:
        shutil.copy2(GEN / h, gen / h)
    return gen


@pytest.mark.parametrize("inherited", [{}, {"EXT_KINDS": "0x10"}, {"VSS_GEN": "/nonexistent"},
                                       {"EXT_KINDS": "0x10", "VSS_GEN": "/nonexistent"}],
                         ids=["clean", "EXT_KINDS", "VSS_GEN", "both"])
def test_c32_with_the_switch_off_the_gcc_line_and_the_hash_are_todays(native, tmp_path, inherited):
    # FOUND BY REVIEW: the inputs were EXT_KINDS and VSS_GEN, so one left in a harness's
    # environment could switch its host arm to the vss monitor, or make its default build refuse. They are
    # MONITOR_EXT_KINDS and MONITOR_VSS_GEN now, and a generic name changes nothing here.
    out = tmp_path / "out" / "monitor-default"
    r = native.run(OUT=out, **inherited)
    assert r.returncode == 0, r.stderr
    assert native.argv() == _default_argv(out)
    want = _sha256(*(p.read_bytes() for p in DEFAULT_SOURCES))
    assert Path(str(out) + ".source-sha256").read_text(encoding="ascii") == want + "\n"
    trace = [ln for ln in r.stderr.splitlines() if ln.startswith("+")]
    assert trace == ["+ " + " ".join([str(native.cc)] + _default_argv(out)), "+ set +x"], trace
    assert "switch:" not in r.stdout and "vss_contract.h" not in r.stdout


@NEEDS_GEN
def test_c32_the_switch_adds_its_flags_and_hashes_the_headers_and_the_switch(native, tmp_path):
    gen = _gen_copy(tmp_path)
    out = tmp_path / "out" / "monitor-vss"
    r = native.run(OUT=out, MONITOR_EXT_KINDS="0x10", MONITOR_VSS_GEN=gen)
    assert r.returncode == 0, r.stderr
    assert native.argv() == _default_argv(out) + ["-DMONITOR_EXT_KINDS=0x10", "-I", str(gen), "-ffp-contract=off"]
    side = Path(str(out) + ".source-sha256")
    base = [p.read_bytes() for p in DEFAULT_SOURCES]
    want = _sha256(*base, *((gen / h).read_bytes() for h in GEN_HEADERS), SWITCH_HASH_LINE)
    assert side.read_text(encoding="ascii") == want + "\n"
    assert "switch: MONITOR_EXT_KINDS=0x10 -ffp-contract=off" in r.stdout

    # A changed profile table is another program: the hash moves, and the guard refuses to rebuild the
    # existing OUT from it.
    with open(gen / "vss_profiles.h", "a", encoding="ascii") as fh:
        fh.write("/* edited */\n")
    r = native.run(OUT=out, MONITOR_EXT_KINDS="0x10", MONITOR_VSS_GEN=gen)
    assert r.returncode != 0 and "was built from other source" in r.stderr, r.stderr
    assert native.argv() is None
    out2 = tmp_path / "out" / "monitor-vss-2"
    r = native.run(OUT=out2, MONITOR_EXT_KINDS="0x10", MONITOR_VSS_GEN=gen)
    assert r.returncode == 0, r.stderr
    want2 = _sha256(*base, *((gen / h).read_bytes() for h in GEN_HEADERS), SWITCH_HASH_LINE)
    assert want2 != want and Path(str(out2) + ".source-sha256").read_text(encoding="ascii") == want2 + "\n"


@NEEDS_GEN
def test_c32_the_default_vss_gen_is_the_in_tree_output_root(native, tmp_path):
    out = tmp_path / "out" / "monitor-vss"
    r = native.run(OUT=out, MONITOR_EXT_KINDS="0x10")
    assert r.returncode == 0, r.stderr
    argv = native.argv()
    assert argv is not None and argv[-3:] == ["-I", os.path.realpath(str(GEN)), "-ffp-contract=off"], argv


@pytest.mark.parametrize("out", [None, "ladder/monitor-native", "ladder/../ladder/monitor-native"])
def test_c32_the_switch_refuses_the_default_out(native, out):
    env = {"MONITOR_EXT_KINDS": "0x10"}
    if out is not None:
        env["OUT"] = str(native.home / out)
    r = native.run(**env)
    assert r.returncode != 0 and "default OUT" in r.stderr, r.stderr
    assert native.argv() is None
    assert not (native.home / "ladder").exists()


@pytest.mark.parametrize("env,why", [
    ({"MONITOR_VSS_GEN": "/nonexistent"}, "MONITOR_VSS_GEN is set but MONITOR_EXT_KINDS is not"),
    ({"MONITOR_EXT_KINDS": "16"}, "spelt so"),
    ({"MONITOR_EXT_KINDS": "0x11"}, "spelt so"),
])
def test_c32_inputs_the_switch_cannot_take_are_refused(native, tmp_path, env, why):
    r = native.run(OUT=tmp_path / "out" / "monitor-x", **env)
    assert r.returncode != 0 and why in r.stderr, r.stderr
    assert native.argv() is None


def test_c32_a_missing_header_names_the_generator(native, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    r = native.run(OUT=tmp_path / "out" / "monitor-vss", MONITOR_EXT_KINDS="0x10", MONITOR_VSS_GEN=empty)
    assert r.returncode != 0 and GENERATOR in r.stderr, r.stderr
    assert native.argv() is None


@NEEDS_GEN
def test_c32_the_native_script_builds_the_ctl_monitor_to_its_own_out_with_vss_ctl_h_hashed(native, tmp_path):
    # Phase 8 WP1b (was test_c32_ctl_reaches_the_compiler_and_stops_there): for 0x14 the
    # script takes vss_ctl.h from MONITOR_VSS_GEN after the two kind 4 headers, so the source-sha256 covers it, and builds
    # the ctl monitor to its own OUT; a changed vss_ctl.h is another program, and a generation without it is refused,
    # naming the generator, before any compiler runs. 0x10's argv and hash are the tests above, unchanged.
    ctl_headers = GEN_HEADERS + ("vss_ctl.h",)
    assert (GEN / "vss_ctl.h").is_file(), "sdv-out/gen has no vss_ctl.h: regenerate it with " + GENERATOR
    gen = tmp_path / "gen"
    gen.mkdir()
    for h in ctl_headers:
        shutil.copy2(GEN / h, gen / h)
    out = tmp_path / "out" / "monitor-ctl"
    r = native.run(OUT=out, MONITOR_EXT_KINDS="0x14", MONITOR_VSS_GEN=gen)
    assert r.returncode == 0, r.stderr
    assert native.argv() == _default_argv(out) + ["-DMONITOR_EXT_KINDS=0x14", "-I", str(gen), "-ffp-contract=off"]
    base = [p.read_bytes() for p in DEFAULT_SOURCES]
    want = _sha256(*base, *((gen / h).read_bytes() for h in ctl_headers), b"MONITOR_EXT_KINDS=0x14 -ffp-contract=off\n")
    assert Path(str(out) + ".source-sha256").read_text(encoding="ascii") == want + "\n"
    assert want != _sha256(*base, *((gen / h).read_bytes() for h in GEN_HEADERS), b"MONITOR_EXT_KINDS=0x14 -ffp-contract=off\n")
    assert "switch: MONITOR_EXT_KINDS=0x14 -ffp-contract=off" in r.stdout and "make ctl" in r.stdout, r.stdout
    assert "source: %s  vss_ctl.h" % hashlib.sha256((gen / "vss_ctl.h").read_bytes()).hexdigest() in r.stdout
    assert not (native.home / "ladder").exists()
    with open(gen / "vss_ctl.h", "a", encoding="ascii") as fh:
        fh.write("/* edited */\n")
    r = native.run(OUT=out, MONITOR_EXT_KINDS="0x14", MONITOR_VSS_GEN=gen)
    assert r.returncode != 0 and "was built from other source" in r.stderr, r.stderr
    assert native.argv() is None
    (gen / "vss_ctl.h").unlink()
    r = native.run(OUT=tmp_path / "out" / "monitor-ctl-2", MONITOR_EXT_KINDS="0x14", MONITOR_VSS_GEN=gen)
    assert r.returncode != 0 and GENERATOR in r.stderr and str(gen / "vss_ctl.h") in r.stderr, r.stderr
    assert native.argv() is None
    # the gap build (0x1C) takes vss_ctl.h from the generation too, so a generation without it is refused the same way
    r = native.run(OUT=tmp_path / "out" / "monitor-gap", MONITOR_EXT_KINDS="0x1C", MONITOR_VSS_GEN=gen)
    assert r.returncode != 0 and GENERATOR in r.stderr and str(gen / "vss_ctl.h") in r.stderr, r.stderr
    assert native.argv() is None


def test_c32_every_extension_kind_build_line_carries_ffp_contract_off():
    # Was test_c32_both_vss_build_lines_carry_ffp_contract_off (Phase 8 WP1b): the Makefile's
    # three (vss, Phase 7's vss-carla and Phase 8's ctl) and the native script's switch line.
    mk = [ln for ln in MAKEFILE.read_text(encoding="ascii").splitlines() if "-DMONITOR_EXT_KINDS" in ln]
    assert len(mk) == 3 and all(ln.startswith("\t$(CC) ") and "-ffp-contract=off" in ln for ln in mk), mk
    sh = [ln.strip() for ln in NATIVE.read_text(encoding="ascii").splitlines() if ln.strip().startswith('"${CC}"')]
    assert len(sh) == 2, sh
    assert sh[0] == DEFAULT_GCC_LINE, "the default gcc line is today's, textually"
    assert "-DMONITOR_EXT_KINDS=" in sh[1] and "-ffp-contract=off" in sh[1], sh[1]
    assert "-ffp-contract=off" in VSS_FLAGS, "the tests' native vss build carries it too"
