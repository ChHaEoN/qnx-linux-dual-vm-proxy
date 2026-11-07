"""ifs-ctl.build (SDV plan Phase 8, WP5; the Phase 8 specification spec-2.md, section 8.2;
the project's local design notes, not in this tree) as ifs-vss-carla.build with
exactly three lines changed, two start lines added right after :7161's, and its own header: the monitor staged from the
kind 2 build of monitor.c (`make ctl`, qnx-safety-monitor-ctl), build/ifs.build this file by its own path, build.date
its own file, then :7150 `svc 500` and :7151 `stamp`, each its own process as every other start line is. The roots stay
ifs-vss-carla.build's: the monitor and the build file in the SDV worktree (S), every other staged file in the
main checkout (M). Every file in these build files is [+optional], so a wrong path is silent to mkifs; this pins the
lines, line by line against ifs-vss-carla.build (comments included), and 8.3's compare-ifs.py accepts the image.

The ctl monitor's host name stands in this build file alone: no other build file names qnx-safety-monitor-ctl, as a
substring (tests/test_ifs_vss.py holds the same of the vss monitor's name), and this file's header names neither the
vss nor the carla monitor's host name, which tests/test_ifs_vss.py and tests/test_ifs_vss_carla.py refuse in every
build file but their own.

What this does NOT show: that the image builds, boots or judges anything (no image is built or read here: 8.3 builds it
on the PC, 8.4 boots it on the Orin with the owner at the plug), or that the staged binary compiles kind 4's profile 4
and kind 2's profile 1 (the Makefile's guard, tests/test_make_ctl.py)."""
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
CTL_BIN = "qnx-safety-monitor-ctl"
RULE = "#" * 79
# The three lines of ifs-vss-carla.build that change, and what each becomes, in file order.
BUILDFILE_CARLA = "[perms=0444] build/ifs.build=" + S + MON + "ifs-vss-carla.build"
DATE_CARLA = "[perms=0444] build.date = output/build/ifs-vss-carla.build.date"
MONITOR_CARLA = "[perms=555] qnx-safety-monitor=" + S + MON + "qnx-safety-monitor-carla"
BUILDFILE_CTL = "[perms=0444] build/ifs.build=" + S + MON + "ifs-ctl.build"
DATE_CTL = "[perms=0444] build.date = output/build/ifs-ctl.build.date"
MONITOR_CTL = "[perms=555] qnx-safety-monitor=" + S + MON + CTL_BIN
CHANGED = [(BUILDFILE_CARLA, BUILDFILE_CTL), (DATE_CARLA, DATE_CTL), (MONITOR_CARLA, MONITOR_CTL)]
# The two start lines added, right after the :7161 line, in this order.
START_7161 = "/proc/boot/qnx-safety-monitor 7161 stamp &"
START_7150 = "/proc/boot/qnx-safety-monitor 7150 svc 500 &"
START_7151 = "/proc/boot/qnx-safety-monitor 7151 stamp &"
ADDED = [START_7150, START_7151]


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


def _expected_body(carla_body):
    """ifs-vss-carla.build's body with the three lines changed and the two start lines added after :7161's."""
    assert carla_body.count(START_7161) == 1
    for old, _new in CHANGED:
        assert carla_body.count(old) == 1, old
    at = carla_body.index(START_7161) + 1
    body = carla_body[:at] + ADDED + carla_body[at:]
    new_of = dict(CHANGED)
    return [new_of.get(ln, ln) for ln in body]


def _check(carla_text, ctl_text):
    carla_head, carla_body = _split(carla_text)
    ctl_head, ctl_body = _split(ctl_text)
    assert all(ln.startswith("#") for ln in ctl_head), "the header is comment lines only"
    assert ctl_head != carla_head, "the header says what this file is"
    want = _expected_body(carla_body)
    assert len(ctl_body) == len(want), (len(ctl_body), len(want))
    # Line by line, comments and blank lines included: exactly the three changes and the two start lines, each in its place.
    diffs = [(i, a, b) for i, (a, b) in enumerate(zip(want, ctl_body)) if a != b]
    assert diffs == [], diffs


def test_ifs_ctl_is_ifs_vss_carla_with_exactly_the_three_lines_and_the_two_start_lines():
    _check(_text("ifs-vss-carla.build"), _text("ifs-ctl.build"))


def test_the_start_lines_are_each_ports_own_process_7150_svc_500_then_7151_stamp_after_7161():
    body = _split(_text("ifs-ctl.build"))[1]
    starts = [ln for ln in body if ln.startswith("/proc/boot/qnx-safety-monitor")]
    assert starts == ["/proc/boot/qnx-safety-monitor &", "/proc/boot/qnx-safety-monitor 7101 udp &",
                      "/proc/boot/qnx-safety-monitor 7102 svc 2000 &", "/proc/boot/qnx-safety-monitor 7160 svc 500 &",
                      START_7161, START_7150, START_7151]
    at = body.index(START_7161)
    assert body[at + 1:at + 3] == ADDED, body[at:at + 4]


def test_both_roots_are_ifs_vss_carla_builds():
    body = _split(_text("ifs-ctl.build"))[1]
    hosts = [ln[ln.index("E:/"):] for ln in body if "E:/" in ln and not ln.lstrip().startswith("#")]
    assert [h for h in hosts if h.startswith(S)] == [S + MON + "ifs-ctl.build", S + MON + CTL_BIN]
    assert [h for h in hosts if not h.startswith(S)] == [M + "ipc-test/qnx-server-net/qnx-echo-server-net"]


def _build_files():
    found = sorted(p for p in list(REPO.glob("ipc-test/*/*.build")) + list(REPO.glob("orin-native/*/*.build")))
    return [p for p in found if p.name != "ifs-ctl.build" or p.parent.name != "qnx-safety-monitor"]


def test_the_ctl_monitor_binary_name_is_its_own_and_the_makefiles():
    others = _build_files()
    names = {p.relative_to(REPO).as_posix() for p in others}
    assert {MON + "ifs-vss-carla.build", MON + "ifs-vss.build", "ipc-test/qnx-dds-monitor/ifs-dds.build",
            "orin-native/startup/m1.build"} <= names and len(others) > 30, sorted(names)
    for p in others:
        assert CTL_BIN not in p.read_text(encoding="utf-8", errors="replace"), p
    # tests/test_ifs_vss.py and tests/test_ifs_vss_carla.py read these substrings in every build file but their own.
    text = _text("ifs-ctl.build")
    assert "qnx-safety-monitor-vss" not in text and "qnx-safety-monitor-carla" not in text
    makefile = _text("Makefile")
    assert re.findall(r"^CTL := (\S+)$", makefile, re.M) == [CTL_BIN], "the build file stages what make writes"


def test_the_header_names_the_differences_the_build_the_guard_and_the_acceptance_rule_and_no_hash():
    head = [ln.lstrip("#").strip() for ln in _split(_text("ifs-ctl.build"))[0]]
    flat = " ".join(" ".join(head).split())
    for s in ("ifs-ctl.build", "Project source only", "it is ifs-vss-carla.build", CTL_BIN, "`make ctl`", "MONITOR_EXT_KINDS=0x14",
              "`make ctl` refuses a generation without kind 4's profile 4 or kind 2's profile 1 before any compiler runs",
              "TCP 7150 `svc 500`", "TCP 7151 `stamp`", "right after the :7161 `stamp` line",
              "each its own process, as every other start line is", "build/ifs.build -> this file",
              "output/build/ifs-ctl.build.date", "MIXED ROOTS", "[+optional]", "never by exit code",
              "make -C ipc-test/qnx-safety-monitor ctl", "BUILDFILE=" + S + MON + "ifs-ctl.build",
              "BUILD_DATE_FILE=output/build/ifs-ctl.build.date", "OUT=output/ifs-ctl.bin", "compare-ifs.py", "ifs-vss-carla.bin",
              "qnx-safety-monitor, startup-script, build/ifs.build and build.date", "none is added and none removed",
              "the startup-script differs by exactly the two start lines", '"ctl rules:"', "monitor.c's sha256 and commit",
              "the other start lines (:7100, :7101, :7102, :7160 `svc 500`, :7161 `stamp`) and every other line below this "
              "header are ifs-vss-carla.build's, byte for byte",
              "the monitor and build/ifs.build point into this worktree (" + S[:-1] + "); every other staged file keeps "
              "the main checkout's path (" + M[:-1] + ")",
              # The body's inherited WP11 comments say "the vss build"; the header says which build this image stages.
              "The body's WP11 comments, kept byte for byte, call the binary on the :7160 and :7161 lines and the staged "
              "monitor \"the vss build\": in this image it is the ctl build, which judges kind 4 by the same monitor.c code "
              "as the vss build"):
        assert s in flat, s
    body = "\n".join(_split(_text("ifs-ctl.build"))[1])
    assert "Both run the vss build." in body and "# WP11 (2026-10-02): the vss build of monitor.c" in body, \
        "the inherited comments the header sentence is about"
    assert head[1].startswith("ifs-ctl.build -- the A6 guest image"), head[1]
    # sha256 values are kept locally only: no hash-like run in the header.
    assert re.search(r"\b[0-9a-f]{8,}\b", "\n".join(head)) is None


CTL_BUILD_CMD = [
    "#   make -C ipc-test/qnx-safety-monitor ctl",
    "#   BSP=/e/Project/qnx-linux-dual-vm-proxy/qnx-safety-vm/bsp-overlay/aarch64le/boot/sys \\",
    "#   BUILD_DIR=qnx-safety-vm \\",
    "#   BUILDFILE=" + S + MON + "ifs-ctl.build \\",
    "#   BUILD_DATE_FILE=output/build/ifs-ctl.build.date OUT=output/ifs-ctl.bin \\",
    "#   /usr/bin/bash ipc-test/qnx-dds-monitor/rebuild-ifs-with-dds.sh",
]


def test_the_header_build_command_is_ifs_vss_carla_builds_and_the_acceptance_rule_is_the_designed_one():
    head = _split(_text("ifs-ctl.build"))[0]
    chead = _split(_text("ifs-vss-carla.build"))[0]
    at, cat = head.index(CTL_BUILD_CMD[0]), chead.index("#   make -C ipc-test/qnx-safety-monitor vss-carla")
    assert head[at:at + 6] == CTL_BUILD_CMD, head[at:at + 6]
    # The same command as ifs-vss-carla.build's, but for the target and the two names.
    mapped = chead[cat:cat + 6]
    for old, new in (("monitor vss-carla", "monitor ctl"), ("ifs-vss-carla.build", "ifs-ctl.build"), ("ifs-vss-carla.bin", "ifs-ctl.bin")):
        mapped = [ln.replace(old, new) for ln in mapped]
    assert mapped == CTL_BUILD_CMD, mapped
    flat = " ".join(" ".join(ln.lstrip("#").strip() for ln in head).split())
    for s in ("Accept only if, against ifs-vss-carla.bin (check its sha256",
              "first; ifs-vss-carla.bin itself is never rebuilt for this)",
              "the only files that differ are qnx-safety-monitor, startup-script, build/ifs.build and build.date (each under "
              "proc/boot/), none is added and none removed, and the startup-script differs by exactly the two start lines",
              "(extracted by dumpifs -x) -- not the image as a whole, which embeds this file and so always carries the "
              "phrase -- carries \"ctl rules:\" and holds the loaded bytes of qnx-safety-monitor-ctl.",
              "the console's ctl rules: line carries the generation's digest"):
        assert s in flat, s


# Each mutant is a list of (old, new) edits applied in turn; every old must occur exactly once.
MUTANTS = {
    "the carla monitor staged instead": [(MONITOR_CTL, MONITOR_CARLA)],
    "the monitor at M's root": [(MONITOR_CTL, "[perms=555] qnx-safety-monitor=" + M + MON + CTL_BIN)],
    "the build file named ifs-vss-carla.build": [(BUILDFILE_CTL, BUILDFILE_CARLA)],
    "the build file at M's root": [(BUILDFILE_CTL, "[perms=0444] build/ifs.build=" + M + MON + "ifs-ctl.build")],
    "ifs-vss-carla's build.date": [(DATE_CTL, DATE_CARLA)],
    "7150 without svc 500": [(START_7150, "/proc/boot/qnx-safety-monitor 7150 svc 2000 &")],
    "7150 plain": [(START_7150, "/proc/boot/qnx-safety-monitor 7150 &")],
    "7151 not stamp": [(START_7151, "/proc/boot/qnx-safety-monitor 7151 svc 500 &")],
    "7150 in the foreground": [(START_7150, "/proc/boot/qnx-safety-monitor 7150 svc 500")],
    "the 7150 line missing": [(START_7150 + "\n", "")],
    "the 7151 line missing": [(START_7151 + "\n", "")],
    "the two lines swapped": [(START_7150 + "\n" + START_7151 + "\n", START_7151 + "\n" + START_7150 + "\n")],
    "the two lines before :7161's": [(START_7161 + "\n" + START_7150 + "\n" + START_7151 + "\n",
                                      START_7150 + "\n" + START_7151 + "\n" + START_7161 + "\n")],
    "a comment line beside them": [(START_7151 + "\n", START_7151 + "\n# Phase 8 WP5: kind 2\n")],
    "a body comment changed": [("# WP11 (2026-10-02): the vss build", "# WP5 (2026-10-20): the vss build")],
    "a start line of kind 4 changed": [("/proc/boot/qnx-safety-monitor 7160 svc 500 &", "/proc/boot/qnx-safety-monitor 7160 svc 2000 &")],
    "an extra staged file": [(MONITOR_CTL + "\n", MONITOR_CTL + "\n[perms=555] qnx-extra=" + M + "ipc-test/qnx-extra\n")],
    "a staged file dropped": [("lib/libm.so.3\n", "")],
    "the echo server moved to S": [(M + "ipc-test/qnx-server-net/", S + "ipc-test/qnx-server-net/")],
    "build.date doubled": [(DATE_CTL + "\n", DATE_CTL + "\n" + DATE_CTL + "\n")],
}


@pytest.mark.parametrize("name", sorted(MUTANTS))
def test_each_mutant_of_the_build_file_fails_the_pin(name):
    carla, mutant = _text("ifs-vss-carla.build"), _text("ifs-ctl.build")
    for old, new in MUTANTS[name]:
        assert mutant.count(old) == 1, old
        mutant = mutant.replace(old, new)
    with pytest.raises(AssertionError):
        _check(carla, mutant)


def test_the_header_left_as_ifs_vss_carla_builds_fails_the_pin():
    carla = _text("ifs-vss-carla.build")
    mutant = "\n".join(_split(carla)[0] + _split(_text("ifs-ctl.build"))[1])
    with pytest.raises(AssertionError):
        _check(carla, mutant)


def test_the_file_is_lf_only_and_ascii():
    data = (Path(IFS_DIR) / "ifs-ctl.build").read_bytes()
    assert b"\r" not in data and data.decode("ascii") and data.endswith(b"\n")
