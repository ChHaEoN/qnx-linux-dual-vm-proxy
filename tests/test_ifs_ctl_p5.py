"""ifs-ctl-p5.build (SDV plan Phase 8.5, WP9c; the project's local design notes,
not in this tree) as ifs-ctl.build with exactly three lines changed and its own header, as ifs-ctl.build is to
ifs-vss-carla.build: the monitor staged from the profile-5 build of monitor.c (`make ctl-p5`, qnx-safety-monitor-p5),
build/ifs.build this file by its own path, build.date its own file. No start line is added or changed, so the
startup-script is ifs-ctl.build's. The roots stay ifs-ctl.build's: the monitor and the build file in the SDV worktree (S),
every other staged file in the main checkout (M). Every file in these build files is [+optional], so a wrong path is
silent to mkifs; this pins the lines, line by line against ifs-ctl.build (comments included), and compare-ifs.py must
accept the image against ifs-ctl.bin (nothing here builds or compares it).

The p5 monitor's host name stands in this build file alone: no other build file names qnx-safety-monitor-p5, as a
substring, and this file's header names none of the ctl, vss and carla monitors' host names, which tests/test_ifs_ctl.py,
tests/test_ifs_vss.py and tests/test_ifs_vss_carla.py refuse in every build file but their own.

What this does NOT show: that the image builds, boots or judges anything (no image is built or read here), or that the
staged binary compiles kind 4's profile 5 and kind 2's profile 1 (the Makefile's guard, tests/test_make_ctl.py)."""
import os
import re
from pathlib import Path

import pytest

HERE = os.path.dirname(__file__)
REPO = Path(HERE).resolve().parent
IFS_DIR = os.path.join(HERE, "..", "ipc-test", "qnx-safety-monitor")
M = "E:/Project/qnx-linux-dual-vm-proxy/"
S = "E:/Project/qnx-linux-dual-vm-proxy-sdv-local/"
MON = "ipc-test/qnx-safety-monitor/"
P5_BIN = "qnx-safety-monitor-p5"
CTL_BIN = "qnx-safety-monitor-ctl"
RULE = "#" * 79
# The three lines of ifs-ctl.build that change, and what each becomes, in file order.
BUILDFILE_CTL = "[perms=0444] build/ifs.build=" + S + MON + "ifs-ctl.build"
DATE_CTL = "[perms=0444] build.date = output/build/ifs-ctl.build.date"
MONITOR_CTL = "[perms=555] qnx-safety-monitor=" + S + MON + CTL_BIN
BUILDFILE_P5 = "[perms=0444] build/ifs.build=" + S + MON + "ifs-ctl-p5.build"
DATE_P5 = "[perms=0444] build.date = output/build/ifs-ctl-p5.build.date"
MONITOR_P5 = "[perms=555] qnx-safety-monitor=" + S + MON + P5_BIN
CHANGED = [(BUILDFILE_CTL, BUILDFILE_P5), (DATE_CTL, DATE_P5), (MONITOR_CTL, MONITOR_P5)]
# ifs-ctl.build's start lines, in its order: none is added, removed or changed here.
STARTS = ["/proc/boot/qnx-safety-monitor &", "/proc/boot/qnx-safety-monitor 7101 udp &",
          "/proc/boot/qnx-safety-monitor 7102 svc 2000 &", "/proc/boot/qnx-safety-monitor 7160 svc 500 &",
          "/proc/boot/qnx-safety-monitor 7161 stamp &", "/proc/boot/qnx-safety-monitor 7150 svc 500 &",
          "/proc/boot/qnx-safety-monitor 7151 stamp &"]
START_7150, START_7151 = STARTS[5], STARTS[6]


def _text(name):
    with open(os.path.join(IFS_DIR, name), encoding="utf-8") as f:
        return f.read()


def _split(text):
    """The file's own header (its leading comment block, both rule lines included) and the rest: mkqnximage's
    banner, which starts two lines above "# IFS Build file", and everything after it."""
    lines = text.split("\n")
    at = lines.index("# IFS Build file") - 2
    assert at > 0 and lines[at] == RULE and lines[at - 1] == RULE, lines[max(at - 1, 0):at + 1]
    return lines[:at], lines[at:]


def _expected_body(ctl_body):
    """ifs-ctl.build's body with the three lines changed, and nothing added or removed."""
    for old, _new in CHANGED:
        assert ctl_body.count(old) == 1, old
    new_of = dict(CHANGED)
    return [new_of.get(ln, ln) for ln in ctl_body]


def _check(ctl_text, p5_text):
    ctl_head, ctl_body = _split(ctl_text)
    p5_head, p5_body = _split(p5_text)
    assert all(ln.startswith("#") for ln in p5_head), "the header is comment lines only"
    assert p5_head != ctl_head, "the header says what this file is"
    want = _expected_body(ctl_body)
    assert len(p5_body) == len(want), (len(p5_body), len(want))
    # Line by line, comments and blank lines included: exactly the three changes, each in its place.
    diffs = [(i, a, b) for i, (a, b) in enumerate(zip(want, p5_body)) if a != b]
    assert diffs == [], diffs


def test_ifs_ctl_p5_is_ifs_ctl_with_exactly_the_three_lines():
    _check(_text("ifs-ctl.build"), _text("ifs-ctl-p5.build"))


def test_the_start_lines_are_ifs_ctl_builds_so_startup_script_is_the_same():
    for name in ("ifs-ctl.build", "ifs-ctl-p5.build"):
        body = _split(_text(name))[1]
        assert [ln for ln in body if ln.startswith("/proc/boot/qnx-safety-monitor")] == STARTS, name
    p5, ctl = _split(_text("ifs-ctl-p5.build"))[1], _split(_text("ifs-ctl.build"))[1]
    script = slice(p5.index("[+script] startup-script = {"), p5.index("startup.sh=output/build/startup.sh"))
    assert p5[script] == ctl[script] and START_7150 in p5[script] and START_7151 in p5[script]


def test_both_roots_are_ifs_ctl_builds():
    body = _split(_text("ifs-ctl-p5.build"))[1]
    hosts = [ln[ln.index("E:/"):] for ln in body if "E:/" in ln and not ln.lstrip().startswith("#")]
    assert [h for h in hosts if h.startswith(S)] == [S + MON + "ifs-ctl-p5.build", S + MON + P5_BIN]
    assert [h for h in hosts if not h.startswith(S)] == [M + "ipc-test/qnx-server-net/qnx-echo-server-net"]


def _build_files():
    found = sorted(p for p in list(REPO.glob("ipc-test/*/*.build")) + list(REPO.glob("orin-native/*/*.build")))
    return [p for p in found if p.name != "ifs-ctl-p5.build" or p.parent.name != "qnx-safety-monitor"]


def test_the_p5_monitor_binary_name_is_its_own_and_the_makefiles():
    others = _build_files()
    names = {p.relative_to(REPO).as_posix() for p in others}
    assert {MON + "ifs-ctl.build", MON + "ifs-vss-carla.build", MON + "ifs-vss.build", "ipc-test/qnx-dds-monitor/ifs-dds.build",
            "orin-native/startup/m1.build"} <= names and len(others) > 30, sorted(names)
    for p in others:
        assert P5_BIN not in p.read_text(encoding="utf-8", errors="replace"), p
    # tests/test_ifs_ctl.py, tests/test_ifs_vss.py and tests/test_ifs_vss_carla.py read these substrings in every build
    # file but their own: the header never names them.
    text = _text("ifs-ctl-p5.build")
    for other in (CTL_BIN, "qnx-safety-monitor-vss", "qnx-safety-monitor-carla"):
        assert other not in text, other
    makefile = _text("Makefile")
    assert re.findall(r"^CTL_P5 := (\S+)$", makefile, re.M) == [P5_BIN], "the build file stages what make writes"


def test_the_header_names_the_differences_the_build_the_guard_and_the_acceptance_rule_and_no_hash():
    head = [ln.lstrip("#").strip() for ln in _split(_text("ifs-ctl-p5.build"))[0]]
    flat = " ".join(" ".join(head).split())
    for s in ("ifs-ctl-p5.build", "Project source only", "beside kind 4 with profile 5, the CARLA 0.10.0 taxi",
              "it is ifs-ctl.build", "as ifs-ctl.build is to ifs-vss-carla.build", P5_BIN, "`make ctl-p5`",
              "the ctl build's flags exactly (MONITOR_EXT_KINDS=0x14",
              "`make ctl-p5` refuses a generation without kind 4's profile 5 or kind 2's profile 1 before any compiler runs",
              "build/ifs.build -> this file", "output/build/ifs-ctl-p5.build.date", "MIXED ROOTS", "[+optional]",
              "never by exit code", "make -B -C ipc-test/qnx-safety-monitor ctl-p5",
              "BUILDFILE=" + S + MON + "ifs-ctl-p5.build", "BUILD_DATE_FILE=output/build/ifs-ctl-p5.build.date",
              "OUT=output/ifs-ctl-p5.bin", "compare-ifs.py",
              "ifs-ctl.bin", "after WP3c F-c's merge compiles profile 5",
              "the start lines (:7100, :7101, :7102, :7160 `svc 500`, :7161 `stamp`, :7150 `svc 500`, :7151 `stamp`), so "
              "startup-script, and every other line below this header are ifs-ctl.build's, byte for byte",
              "(tests/test_ifs_ctl_p5.py pins it)", "no other build file names it (tests/test_ifs_ctl_p5.py)",
              "the monitor and build/ifs.build point into this worktree (" + S[:-1] + "); every other staged file keeps "
              "the main checkout's path (" + M[:-1] + ")",
              "monitor.c's sha256 and commit",
              # The body's inherited WP11 comments say "the vss build"; the header says which build this image stages.
              "The body's WP11 comments, kept byte for byte, call the binary on the :7160 and :7161 lines and the staged "
              "monitor \"the vss build\": in this image it is the ctl-p5 build, which judges kind 4 by the same monitor.c "
              "code as the vss build (MONITOR_EXT_KINDS's 0x10 bit), against its generation's kind 4 profiles, profile 5 "
              "among them, and kind 2 on :7150 and :7151 as the ctl build does."):
        assert s in flat, s
    body = "\n".join(_split(_text("ifs-ctl-p5.build"))[1])
    assert "Both run the vss build." in body and "# WP11 (2026-10-02): the vss build of monitor.c" in body, \
        "the inherited comments the header sentence is about"
    assert head[1].startswith("ifs-ctl-p5.build -- the A6 guest image"), head[1]
    # The header's phase id (WP9c's critic, mutant c18): Phase 8.5, not Phase 8.
    assert "(SDV Phase 8.5, WP9c). Project source only." in flat, flat
    # sha256 values are kept locally only: no hash-like run in the header.
    assert re.search(r"\b[0-9a-f]{8,}\b", "\n".join(head)) is None


P5_BUILD_CMD = [
    "#   make -B -C ipc-test/qnx-safety-monitor ctl-p5",
    "#   BSP=/e/Project/qnx-linux-dual-vm-proxy/qnx-safety-vm/bsp-overlay/aarch64le/boot/sys \\",
    "#   BUILD_DIR=qnx-safety-vm \\",
    "#   BUILDFILE=" + S + MON + "ifs-ctl-p5.build \\",
    "#   BUILD_DATE_FILE=output/build/ifs-ctl-p5.build.date OUT=output/ifs-ctl-p5.bin \\",
    "#   /usr/bin/bash ipc-test/qnx-dds-monitor/rebuild-ifs-with-dds.sh",
]


def test_the_header_build_command_is_ifs_ctl_builds_and_the_acceptance_rule_is_the_designed_one():
    head = _split(_text("ifs-ctl-p5.build"))[0]
    chead = _split(_text("ifs-ctl.build"))[0]
    at, cat = head.index(P5_BUILD_CMD[0]), chead.index("#   make -C ipc-test/qnx-safety-monitor ctl")
    assert head[at:at + 6] == P5_BUILD_CMD, head[at:at + 6]
    # The same command as ifs-ctl.build's, but for make's -B (the header says why; tests/test_make_ctl.py runs it), the
    # target and the two names.
    mapped = chead[cat:cat + 6]
    for old, new in (("make -C", "make -B -C"), ("monitor ctl", "monitor ctl-p5"), ("ifs-ctl.build", "ifs-ctl-p5.build"),
                     ("ifs-ctl.bin", "ifs-ctl-p5.bin")):
        mapped = [ln.replace(old, new) for ln in mapped]
    assert mapped == P5_BUILD_CMD, mapped
    flat = " ".join(" ".join(ln.lstrip("#").strip() for ln in head).split())
    for s in ("with make's -B, so that ctl-p5's guards run and the binary is compiled again every time: make tracks no "
              "CTL_P5_GEN value, only times, and a qnx-safety-monitor-p5 newer than its inputs, built against another "
              "generation, would otherwise be staged with no guard run",
              "Accept only if, against ifs-ctl.bin (check its sha256 against its record first; ifs-ctl.bin itself is never "
              "rebuilt for this)",
              "the only files that differ are qnx-safety-monitor, build/ifs.build and build.date (each under proc/boot/; "
              "startup-script is the same), none is added and none removed",
              "(extracted by dumpifs -x) -- not the image as a whole, which embeds this file and so always carries the "
              "phrase -- carries \"ctl rules:\" and holds the loaded bytes of qnx-safety-monitor-p5.",
              "At its first boot, in the replays' run, the console's vss rules: line lists profile 5 and its ctl rules: line "
              "carries the generation's digest"):
        assert s in flat, s


# Each mutant is a list of (old, new) edits applied in turn; every old must occur exactly once.
MUTANTS = {
    "the ctl monitor staged instead": [(MONITOR_P5, MONITOR_CTL)],
    "the monitor at M's root": [(MONITOR_P5, "[perms=555] qnx-safety-monitor=" + M + MON + P5_BIN)],
    "the build file named ifs-ctl.build": [(BUILDFILE_P5, BUILDFILE_CTL)],
    "the build file at M's root": [(BUILDFILE_P5, "[perms=0444] build/ifs.build=" + M + MON + "ifs-ctl-p5.build")],
    "ifs-ctl's build.date": [(DATE_P5, DATE_CTL)],
    "7150 without svc 500": [(START_7150, "/proc/boot/qnx-safety-monitor 7150 svc 2000 &")],
    "7151 not stamp": [(START_7151, "/proc/boot/qnx-safety-monitor 7151 svc 500 &")],
    "the 7150 line missing": [(START_7150 + "\n", "")],
    "the 7151 line missing": [(START_7151 + "\n", "")],
    "a start line added": [(START_7151 + "\n", START_7151 + "\n/proc/boot/qnx-safety-monitor 7152 svc 500 &\n")],
    "a comment line added": [(START_7151 + "\n", START_7151 + "\n# Phase 8.5 WP9c: profile 5\n")],
    "a body comment changed": [("# WP11 (2026-10-02): the vss build", "# WP9c (2026-11-13): the vss build")],
    "an extra staged file": [(MONITOR_P5 + "\n", MONITOR_P5 + "\n[perms=555] qnx-extra=" + M + "ipc-test/qnx-extra\n")],
    "a staged file dropped": [("lib/libm.so.3\n", "")],
    "the echo server moved to S": [(M + "ipc-test/qnx-server-net/", S + "ipc-test/qnx-server-net/")],
    "build.date doubled": [(DATE_P5 + "\n", DATE_P5 + "\n" + DATE_P5 + "\n")],
}


@pytest.mark.parametrize("name", sorted(MUTANTS))
def test_each_mutant_of_the_build_file_fails_the_pin(name):
    ctl, mutant = _text("ifs-ctl.build"), _text("ifs-ctl-p5.build")
    for old, new in MUTANTS[name]:
        assert mutant.count(old) == 1, old
        mutant = mutant.replace(old, new)
    with pytest.raises(AssertionError):
        _check(ctl, mutant)


def test_the_header_left_as_ifs_ctl_builds_fails_the_pin():
    ctl = _text("ifs-ctl.build")
    mutant = "\n".join(_split(ctl)[0] + _split(_text("ifs-ctl-p5.build"))[1])
    with pytest.raises(AssertionError):
        _check(ctl, mutant)


def test_the_file_is_lf_only_and_ascii():
    data = (Path(IFS_DIR) / "ifs-ctl-p5.build").read_bytes()
    assert b"\r" not in data and data.decode("ascii") and data.endswith(b"\n")
