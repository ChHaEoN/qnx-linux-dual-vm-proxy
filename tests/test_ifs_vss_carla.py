"""ifs-vss-carla.build (Phase 7 WP4a) as ifs-vss.build with exactly three lines
changed and its own header: the monitor staged from the profile-3 build of monitor.c (`make vss-carla`), build/ifs.build
this file by its own path, build.date its own file. The roots stay ifs-vss.build's: the monitor and the build file in
the SDV worktree (S), every other staged file in the main checkout (M). Every file in these build files is
[+optional], so a wrong path is silent to mkifs; this pins the lines, line by line against ifs-vss.build (comments
included), and WP4b's compare-ifs.py accepts the image.

The monitor's host name is qnx-safety-monitor-carla, not the spec's qnx-safety-monitor-vss-carla:
tests/test_ifs_vss.py (relied on, never changed) holds that no build file but ifs-vss.build names
"qnx-safety-monitor-vss" anywhere, and that string is inside the spec's name.

What this does NOT show: that the image builds, boots or judges anything (no image is built or read here; WP4b
builds it after the merge, WP6 and WP7 boot it), or that the staged binary compiles profile 3 (the Makefile's guard,
tests/test_monitor_vss.py)."""
import os
import re

import pytest

HERE = os.path.dirname(__file__)
IFS_DIR = os.path.join(HERE, "..", "ipc-test", "qnx-safety-monitor")
M = "E:/Project/qnx-linux-dual-vm-proxy/"
S = "E:/Project/qnx-linux-dual-vm-proxy-sdv-local/"
MON = "ipc-test/qnx-safety-monitor/"
CARLA_BIN = "qnx-safety-monitor-carla"
RULE = "#" * 79
# The three lines of ifs-vss.build that change, and what each becomes, in file order.
BUILDFILE_VSS = "[perms=0444] build/ifs.build=" + S + MON + "ifs-vss.build"
DATE_VSS = "[perms=0444] build.date = output/build/ifs-vss.build.date"
MONITOR_VSS = "[perms=555] qnx-safety-monitor=" + S + MON + "qnx-safety-monitor-vss"
BUILDFILE_CARLA = "[perms=0444] build/ifs.build=" + S + MON + "ifs-vss-carla.build"
DATE_CARLA = "[perms=0444] build.date = output/build/ifs-vss-carla.build.date"
MONITOR_CARLA = "[perms=555] qnx-safety-monitor=" + S + MON + CARLA_BIN
CHANGED = [(BUILDFILE_VSS, BUILDFILE_CARLA), (DATE_VSS, DATE_CARLA), (MONITOR_VSS, MONITOR_CARLA)]


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


def _check(vss_text, carla_text):
    vss_head, vss_body = _split(vss_text)
    carla_head, carla_body = _split(carla_text)
    assert all(ln.startswith("#") for ln in carla_head), "the header is comment lines only"
    assert carla_head != vss_head, "the header says what this file is"
    assert len(carla_body) == len(vss_body), (len(carla_body), len(vss_body))
    # Line by line, comments and blank lines included: exactly the three changes, each in its place.
    diffs = [(a, b) for a, b in zip(vss_body, carla_body) if a != b]
    assert diffs == CHANGED, diffs


def test_ifs_vss_carla_is_ifs_vss_with_exactly_the_three_lines():
    _check(_text("ifs-vss.build"), _text("ifs-vss-carla.build"))


def test_both_roots_are_ifs_vss_builds():
    body = _split(_text("ifs-vss-carla.build"))[1]
    hosts = [ln[ln.index("E:/"):] for ln in body if "E:/" in ln and not ln.lstrip().startswith("#")]
    assert [h for h in hosts if h.startswith(S)] == [S + MON + "ifs-vss-carla.build", S + MON + CARLA_BIN]
    assert [h for h in hosts if not h.startswith(S)] == [M + "ipc-test/qnx-server-net/qnx-echo-server-net"]


def test_the_carla_monitor_binary_name_is_its_own_and_the_makefiles():
    others = [n for n in os.listdir(IFS_DIR) if n.startswith("ifs-") and n.endswith(".build") and n != "ifs-vss-carla.build"]
    assert "ifs-vss.build" in others and len(others) > 10, others
    for n in others:
        assert CARLA_BIN not in _text(n), n
    # tests/test_ifs_vss.py reads this substring in every build file but ifs-vss.build: the header never names it.
    assert "qnx-safety-monitor-vss" not in _text("ifs-vss-carla.build")
    makefile = _text("Makefile")
    assert re.findall(r"^VSS_CARLA := (\S+)$", makefile, re.M) == [CARLA_BIN], "the build file stages what make writes"


def test_the_header_names_the_differences_the_build_and_the_acceptance_rule_and_no_hash():
    head = [ln.lstrip("#").strip() for ln in _split(_text("ifs-vss-carla.build"))[0]]
    flat = " ".join(" ".join(head).split())
    for s in ("ifs-vss-carla.build", "Project source only", "it is ifs-vss.build", "qnx-safety-monitor-carla",
              "`make vss-carla`", "profile 3", "build/ifs.build -> this file", "output/build/ifs-vss-carla.build.date",
              "MIXED ROOTS", "[+optional]", "never by exit code", "make -C ipc-test/qnx-safety-monitor vss-carla",
              "BUILDFILE=" + S + MON + "ifs-vss-carla.build", "BUILD_DATE_FILE=output/build/ifs-vss-carla.build.date",
              "OUT=output/ifs-vss-carla.bin", "compare-ifs.py", "ifs-vss.bin",
              "qnx-safety-monitor, build/ifs.build and build.date", "none is added and none removed",
              "startup-script", '"vss rules:"', "WP4b",
              "the start lines (:7100, :7101, :7102, :7160 `svc 500`, :7161 `stamp`), so startup-script, and every other "
              "line below this header are ifs-vss.build's, byte for byte",
              "the monitor and build/ifs.build point into this worktree (" + S[:-1] + "); every other staged file keeps "
              "the main checkout's path (" + M[:-1] + ")"):
        assert s in flat, s
    assert head[1].startswith("ifs-vss-carla.build -- the A6 guest image"), head[1]
    # sha256 values are kept locally only: no hash-like run in the header.
    assert re.search(r"\b[0-9a-f]{8,}\b", "\n".join(head)) is None


# FOUND BY REVIEW: the phrase test above let the header's build command and acceptance rule change
# (the BSP root, the build script, startup-script allowed to differ, another binary or reference image) unseen.
CARLA_BUILD_CMD = [
    "#   make -C ipc-test/qnx-safety-monitor vss-carla",
    "#   BSP=/e/Project/qnx-linux-dual-vm-proxy/qnx-safety-vm/bsp-overlay/aarch64le/boot/sys \\",
    "#   BUILD_DIR=qnx-safety-vm \\",
    "#   BUILDFILE=" + S + MON + "ifs-vss-carla.build \\",
    "#   BUILD_DATE_FILE=output/build/ifs-vss-carla.build.date OUT=output/ifs-vss-carla.bin \\",
    "#   /usr/bin/bash ipc-test/qnx-dds-monitor/rebuild-ifs-with-dds.sh",
]


def test_the_header_build_command_is_ifs_vss_builds_and_the_acceptance_rule_is_the_designed_one():
    head = _split(_text("ifs-vss-carla.build"))[0]
    vhead = _split(_text("ifs-vss.build"))[0]
    at, vat = head.index(CARLA_BUILD_CMD[0]), vhead.index("#   make -C ipc-test/qnx-safety-monitor vss")
    assert head[at:at + 6] == CARLA_BUILD_CMD, head[at:at + 6]
    # The same command as ifs-vss.build's, but for the three names.
    names = [("ifs-vss.build", "ifs-vss-carla.build"), ("ifs-vss.bin", "ifs-vss-carla.bin")]
    mapped = [vhead[vat] + "-carla"] + vhead[vat + 1:vat + 6]
    for old, new in names:
        mapped = [ln.replace(old, new) for ln in mapped]
    assert mapped == CARLA_BUILD_CMD, mapped
    flat = " ".join(" ".join(ln.lstrip("#").strip() for ln in head).split())
    for s in ("Accept only if, against ifs-vss.bin (check its sha256",
              "the only files that differ are qnx-safety-monitor, build/ifs.build and build.date (each under proc/boot/; "
              "startup-script is the same), none is added and none removed",
              "holds the loaded bytes of qnx-safety-monitor-carla.", "the console's vss rules: line lists profile 3.",
              "(extracted by dumpifs -x) -- not the image as a whole, which embeds this file and so always carries the "
              "phrase -- carries \"vss rules:\"", "first; ifs-vss.bin itself is never rebuilt for this)"):
        assert s in flat, s


START_7160 = "/proc/boot/qnx-safety-monitor 7160 svc 500 &"
# Each mutant is a list of (old, new) edits applied in turn; every old must occur exactly once.
MUTANTS = {
    "the vss monitor staged instead": [(MONITOR_CARLA, MONITOR_VSS)],
    "the monitor at M's root": [(MONITOR_CARLA, "[perms=555] qnx-safety-monitor=" + M + MON + CARLA_BIN)],
    "the build file named ifs-vss.build": [(BUILDFILE_CARLA, BUILDFILE_VSS)],
    "the build file at M's root": [(BUILDFILE_CARLA, "[perms=0444] build/ifs.build=" + M + MON + "ifs-vss-carla.build")],
    "ifs-vss's build.date": [(DATE_CARLA, DATE_VSS)],
    "a start line changed": [(START_7160, "/proc/boot/qnx-safety-monitor 7160 svc 2000 &")],
    "an extra staged file": [(MONITOR_CARLA + "\n", MONITOR_CARLA + "\n[perms=555] qnx-extra=" + M + "ipc-test/qnx-extra\n")],
    "a body comment changed": [("# WP11 (2026-10-02): the vss build", "# WP4a (2026-10-17): the vss build")],
    "a staged file dropped": [("lib/libm.so.3\n", "")],
    "the 7161 start line missing": [("/proc/boot/qnx-safety-monitor 7161 stamp &\n", "")],
    "the echo server moved to S": [(M + "ipc-test/qnx-server-net/", S + "ipc-test/qnx-server-net/")],
    "build.date doubled": [(DATE_CARLA + "\n", DATE_CARLA + "\n" + DATE_CARLA + "\n")],
    "the start lines before :7102": [
        ("/proc/boot/qnx-safety-monitor 7160 svc 500 &\n/proc/boot/qnx-safety-monitor 7161 stamp &\n", ""),
        ("/proc/boot/qnx-safety-monitor 7102 svc 2000 &\n",
         "/proc/boot/qnx-safety-monitor 7160 svc 500 &\n/proc/boot/qnx-safety-monitor 7161 stamp &\n"
         "/proc/boot/qnx-safety-monitor 7102 svc 2000 &\n"),
    ],
}


@pytest.mark.parametrize("name", sorted(MUTANTS))
def test_each_mutant_of_the_build_file_fails_the_pin(name):
    vss, mutant = _text("ifs-vss.build"), _text("ifs-vss-carla.build")
    for old, new in MUTANTS[name]:
        assert mutant.count(old) == 1, old
        mutant = mutant.replace(old, new)
    with pytest.raises(AssertionError):
        _check(vss, mutant)


def test_the_header_left_as_ifs_vss_builds_fails_the_pin():
    vss = _text("ifs-vss.build")
    mutant = "\n".join(_split(vss)[0] + _split(_text("ifs-vss-carla.build"))[1])
    with pytest.raises(AssertionError):
        _check(vss, mutant)
