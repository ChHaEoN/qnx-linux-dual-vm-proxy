"""ifs-lane.build (SDV Phase 9, C2b LB; the project's local design notes, not in this
tree) as ifs-ctl-p5.build with exactly three lines changed, two start lines added right after :7151's, and its own
header, as ifs-ctl.build is to ifs-vss-carla.build: the monitor staged from the lane build of monitor.c (`make lane`,
qnx-safety-monitor-lane, MONITOR_EXT_KINDS=0x54: kinds 2, 4 and 6), build/ifs.build this file by its own path,
build.date its own file, then :7170 `svc 500` and :7171 `stamp`, each its own process as every other start line is. The
roots stay ifs-ctl-p5.build's: the monitor and the build file in the SDV worktree (S), every other staged file in the
main checkout (M). Every file in these build files is [+optional], so a wrong path is silent to mkifs; this pins the
lines, line by line against ifs-ctl-p5.build (comments included), and compare-ifs.py must accept the image against
ifs-ctl-p5.bin (nothing here builds or compares it).

The lane monitor's host name stands in this build file alone: no other build file names qnx-safety-monitor-lane, as a
substring, and this file names none of the ctl, p5, vss and carla monitors' host names, which tests/test_ifs_ctl.py,
tests/test_ifs_ctl_p5.py, tests/test_ifs_vss.py and tests/test_ifs_vss_carla.py refuse in every build file but their own.

What this does NOT show: that the image builds, boots or judges anything (no image is built or read here), that the
staged binary compiles kind 6, kind 4's profile 5 and kind 2's profile 1 (the Makefile's guard, tests/test_make_ctl.py;
kind 6 itself, tests/test_monitor_lane.py, on the native build), or that anything answers on :7170 or :7171."""
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
LANE_BIN = "qnx-safety-monitor-lane"
P5_BIN = "qnx-safety-monitor-p5"
RULE = "#" * 79
# The three lines of ifs-ctl-p5.build that change, and what each becomes, in file order.
BUILDFILE_P5 = "[perms=0444] build/ifs.build=" + S + MON + "ifs-ctl-p5.build"
DATE_P5 = "[perms=0444] build.date = output/build/ifs-ctl-p5.build.date"
MONITOR_P5 = "[perms=555] qnx-safety-monitor=" + S + MON + P5_BIN
BUILDFILE_LANE = "[perms=0444] build/ifs.build=" + S + MON + "ifs-lane.build"
DATE_LANE = "[perms=0444] build.date = output/build/ifs-lane.build.date"
MONITOR_LANE = "[perms=555] qnx-safety-monitor=" + S + MON + LANE_BIN
CHANGED = [(BUILDFILE_P5, BUILDFILE_LANE), (DATE_P5, DATE_LANE), (MONITOR_P5, MONITOR_LANE)]
# ifs-ctl-p5.build's start lines, in its order, then the two added right after :7151's, in this order.
STARTS = ["/proc/boot/qnx-safety-monitor &", "/proc/boot/qnx-safety-monitor 7101 udp &",
          "/proc/boot/qnx-safety-monitor 7102 svc 2000 &", "/proc/boot/qnx-safety-monitor 7160 svc 500 &",
          "/proc/boot/qnx-safety-monitor 7161 stamp &", "/proc/boot/qnx-safety-monitor 7150 svc 500 &",
          "/proc/boot/qnx-safety-monitor 7151 stamp &"]
START_7151 = STARTS[6]
START_7170 = "/proc/boot/qnx-safety-monitor 7170 svc 500 &"
START_7171 = "/proc/boot/qnx-safety-monitor 7171 stamp &"
ADDED = [START_7170, START_7171]


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


def _expected_body(p5_body):
    """ifs-ctl-p5.build's body with the three lines changed and the two start lines added after :7151's."""
    assert p5_body.count(START_7151) == 1
    for old, _new in CHANGED:
        assert p5_body.count(old) == 1, old
    at = p5_body.index(START_7151) + 1
    body = p5_body[:at] + ADDED + p5_body[at:]
    new_of = dict(CHANGED)
    return [new_of.get(ln, ln) for ln in body]


def _check(p5_text, lane_text):
    p5_head, p5_body = _split(p5_text)
    lane_head, lane_body = _split(lane_text)
    assert all(ln.startswith("#") for ln in lane_head), "the header is comment lines only"
    assert lane_head != p5_head, "the header says what this file is"
    want = _expected_body(p5_body)
    assert len(lane_body) == len(want), (len(lane_body), len(want))
    # Line by line, comments and blank lines included: exactly the three changes and the two start lines, each in its place.
    diffs = [(i, a, b) for i, (a, b) in enumerate(zip(want, lane_body)) if a != b]
    assert diffs == [], diffs


def test_ifs_lane_is_ifs_ctl_p5_with_exactly_the_three_lines_and_the_two_start_lines():
    _check(_text("ifs-ctl-p5.build"), _text("ifs-lane.build"))


def test_the_start_lines_are_ifs_ctl_p5_builds_then_7170_svc_500_and_7171_stamp_after_7151():
    p5 = _split(_text("ifs-ctl-p5.build"))[1]
    lane = _split(_text("ifs-lane.build"))[1]
    assert [ln for ln in p5 if ln.startswith("/proc/boot/qnx-safety-monitor")] == STARTS
    assert [ln for ln in lane if ln.startswith("/proc/boot/qnx-safety-monitor")] == STARTS + ADDED
    at = lane.index(START_7151)
    assert lane[at + 1:at + 3] == ADDED, lane[at:at + 4]
    # startup-script differs from ifs-ctl-p5.build's by exactly the two start lines (the acceptance rule's words).
    script = lambda body: body[body.index("[+script] startup-script = {"):body.index("startup.sh=output/build/startup.sh")]  # noqa: E731
    assert [ln for ln in script(lane) if ln not in ADDED] == script(p5) and len(script(lane)) == len(script(p5)) + 2


def test_both_roots_are_ifs_ctl_p5_builds():
    body = _split(_text("ifs-lane.build"))[1]
    hosts = [ln[ln.index("E:/"):] for ln in body if "E:/" in ln and not ln.lstrip().startswith("#")]
    assert [h for h in hosts if h.startswith(S)] == [S + MON + "ifs-lane.build", S + MON + LANE_BIN]
    assert [h for h in hosts if not h.startswith(S)] == [M + "ipc-test/qnx-server-net/qnx-echo-server-net"]


def _build_files():
    found = sorted(p for p in list(REPO.glob("ipc-test/*/*.build")) + list(REPO.glob("orin-native/*/*.build")))
    return [p for p in found if p.name != "ifs-lane.build" or p.parent.name != "qnx-safety-monitor"]


def test_the_lane_monitor_binary_name_is_its_own_and_the_makefiles():
    others = _build_files()
    names = {p.relative_to(REPO).as_posix() for p in others}
    assert {MON + "ifs-ctl-p5.build", MON + "ifs-ctl.build", MON + "ifs-vss-carla.build", MON + "ifs-vss.build",
            "ipc-test/qnx-dds-monitor/ifs-dds.build", "orin-native/startup/m1.build"} <= names and len(others) > 30, sorted(names)
    for p in others:
        assert LANE_BIN not in p.read_text(encoding="utf-8", errors="replace"), p
    # tests/test_ifs_ctl.py, tests/test_ifs_ctl_p5.py, tests/test_ifs_vss.py and tests/test_ifs_vss_carla.py read these
    # substrings in every build file but their own: this file never names them.
    text = _text("ifs-lane.build")
    for other in ("qnx-safety-monitor-ctl", P5_BIN, "qnx-safety-monitor-vss", "qnx-safety-monitor-carla"):
        assert other not in text, other
    makefile = _text("Makefile")
    assert re.findall(r"^LANE := (\S+)$", makefile, re.M) == [LANE_BIN], "the build file stages what make writes"


def _flat(lines):
    return " ".join(" ".join(ln.lstrip("#").strip() for ln in lines).split())


def test_the_header_names_the_differences_the_build_the_guard_and_the_acceptance_rule_and_no_hash():
    head = _split(_text("ifs-lane.build"))[0]
    flat = _flat(head)
    for s in ("ifs-lane.build", "(SDV Phase 9, C2b LB). Project source only.", "kind 6, the lane claim",
              "it is ifs-ctl-p5.build", LANE_BIN, "`make lane`",
              "ctl-p5's flags but MONITOR_EXT_KINDS=0x54 (kinds 2, 4 and 6)",
              "`make lane` refuses a generation without kind 4's profile 5 or kind 2's profile 1 before any compiler runs",
              "right after the :7151 `stamp` line", "TCP 7170 `svc 500`", "TCP 7171 `stamp`",
              "each its own process, as every other start line is", "build/ifs.build -> this file",
              "output/build/ifs-lane.build.date", "MIXED ROOTS", "[+optional]", "never by exit code",
              "make -B -C ipc-test/qnx-safety-monitor lane", "BUILDFILE=" + S + MON + "ifs-lane.build",
              "BUILD_DATE_FILE=output/build/ifs-lane.build.date", "OUT=output/ifs-lane.bin", "compare-ifs.py",
              "after WP3c F-c's merge compiles profile 5",
              "the other start lines (:7100, :7101, :7102, :7160 `svc 500`, :7161 `stamp`, :7150 `svc 500`, :7151 `stamp`) "
              "and every other line below this header are ifs-ctl-p5.build's, byte for byte (tests/test_ifs_lane.py pins it)",
              "no other build file names it (tests/test_ifs_lane.py)",
              "the monitor and build/ifs.build point into this worktree (" + S[:-1] + "); every other staged file keeps "
              "the main checkout's path (" + M[:-1] + ")",
              "monitor.c's sha256 and commit",
              # The body's inherited WP11 comments say "the vss build"; the header says which build this image stages.
              "The body's WP11 comments, kept byte for byte, call the binary on the :7160 and :7161 lines and the staged "
              "monitor \"the vss build\": in this image it is the lane build, which judges kind 4 by the same monitor.c "
              "code as the vss build (MONITOR_EXT_KINDS's 0x10 bit), against its generation's kind 4 profiles, profile 5 "
              "among them, kind 2 on :7150 and :7151 as the ctl build does, and kind 6 on :7170 and :7171 (its 0x40 bit)."):
        assert s in flat, s
    body = "\n".join(_split(_text("ifs-lane.build"))[1])
    assert "Both run the vss build." in body and "# WP11 (2026-10-02): the vss build of monitor.c" in body, \
        "the inherited comments the header sentence is about"
    assert head[1] == "# ifs-lane.build -- the A6 guest image for kind 6, the lane claim (a camera", head[1]
    # sha256 values are kept locally only: no hash-like run in the header.
    assert re.search(r"\b[0-9a-f]{8,}\b", "\n".join(head)) is None


LANE_BUILD_CMD = [
    "#   make -B -C ipc-test/qnx-safety-monitor lane",
    "#   BSP=/e/Project/qnx-linux-dual-vm-proxy/qnx-safety-vm/bsp-overlay/aarch64le/boot/sys \\",
    "#   BUILD_DIR=qnx-safety-vm \\",
    "#   BUILDFILE=" + S + MON + "ifs-lane.build \\",
    "#   BUILD_DATE_FILE=output/build/ifs-lane.build.date OUT=output/ifs-lane.bin \\",
    "#   /usr/bin/bash ipc-test/qnx-dds-monitor/rebuild-ifs-with-dds.sh",
]


def test_the_header_build_command_is_ifs_ctl_p5_builds_and_the_acceptance_rule_is_the_designed_one():
    head = _split(_text("ifs-lane.build"))[0]
    phead = _split(_text("ifs-ctl-p5.build"))[0]
    at, pat = head.index(LANE_BUILD_CMD[0]), phead.index("#   make -B -C ipc-test/qnx-safety-monitor ctl-p5")
    assert head[at:at + 6] == LANE_BUILD_CMD, head[at:at + 6]
    # The same command as ifs-ctl-p5.build's, -B included, but for the target and the two names.
    mapped = phead[pat:pat + 6]
    for old, new in (("monitor ctl-p5", "monitor lane"), ("ifs-ctl-p5.build", "ifs-lane.build"), ("ifs-ctl-p5.bin", "ifs-lane.bin")):
        mapped = [ln.replace(old, new) for ln in mapped]
    assert mapped == LANE_BUILD_CMD, mapped
    flat = _flat(head)
    for s in ("with make's -B, so that lane's guards run and the binary is compiled again every time: make tracks no "
              "LANE_GEN value, only times, and a qnx-safety-monitor-lane newer than its inputs, built against another "
              "generation, would otherwise be staged with no guard run",
              "Accept only if, against ifs-ctl-p5.bin (check its sha256 against its record first; ifs-ctl-p5.bin itself is "
              "never rebuilt for this)",
              "the only files that differ are qnx-safety-monitor, startup-script, build/ifs.build and build.date (each under "
              "proc/boot/), none is added and none removed, and the startup-script differs by exactly the two start lines",
              "(extracted by dumpifs -x) -- not the image as a whole, which embeds this file and so always carries the "
              "phrase -- carries \"lane rules:\" and holds the loaded bytes of qnx-safety-monitor-lane.",
              "At its first boot the console's lane rules: line follows its ctl rules: line, and its vss rules: line lists "
              "profile 5"):
        assert s in flat, s


# Each mutant is a list of (old, new) edits applied in turn; every old must occur exactly once.
MUTANTS = {
    "the p5 monitor staged instead": [(MONITOR_LANE, MONITOR_P5)],
    "the ctl monitor staged instead": [(MONITOR_LANE, "[perms=555] qnx-safety-monitor=" + S + MON + "qnx-safety-monitor-ctl")],
    "the monitor at M's root": [(MONITOR_LANE, "[perms=555] qnx-safety-monitor=" + M + MON + LANE_BIN)],
    "the build file named ifs-ctl-p5.build": [(BUILDFILE_LANE, BUILDFILE_P5)],
    "the build file at M's root": [(BUILDFILE_LANE, "[perms=0444] build/ifs.build=" + M + MON + "ifs-lane.build")],
    "ifs-ctl-p5's build.date": [(DATE_LANE, DATE_P5)],
    "the 7170 line missing": [(START_7170 + "\n", "")],
    "the 7171 line missing": [(START_7171 + "\n", "")],
    "both added lines missing": [(START_7170 + "\n" + START_7171 + "\n", "")],
    "7170 without svc 500": [(START_7170, "/proc/boot/qnx-safety-monitor 7170 svc 2000 &")],
    "7171 not stamp": [(START_7171, "/proc/boot/qnx-safety-monitor 7171 svc 500 &")],
    "7170 and 7171 swapped": [(START_7170 + "\n" + START_7171 + "\n", START_7171 + "\n" + START_7170 + "\n")],
    "the two lines before 7151's": [(START_7151 + "\n" + START_7170 + "\n" + START_7171 + "\n",
                                     START_7170 + "\n" + START_7171 + "\n" + START_7151 + "\n")],
    "one process for both ports": [(START_7170 + "\n" + START_7171 + "\n", "/proc/boot/qnx-safety-monitor 7170 svc 500 7171 &\n")],
    "a third start line added": [(START_7171 + "\n", START_7171 + "\n/proc/boot/qnx-safety-monitor 7172 svc 500 &\n")],
    "a comment line added": [(START_7171 + "\n", START_7171 + "\n# C2b LB: kind 6\n")],
    "a body comment changed": [("# WP11 (2026-10-02): the vss build", "# C2b LB (2026-11-13): the vss build")],
    "an extra staged file": [(MONITOR_LANE + "\n", MONITOR_LANE + "\n[perms=555] qnx-extra=" + M + "ipc-test/qnx-extra\n")],
    "a staged file dropped": [("lib/libm.so.3\n", "")],
    "the echo server moved to S": [(M + "ipc-test/qnx-server-net/", S + "ipc-test/qnx-server-net/")],
    "build.date doubled": [(DATE_LANE + "\n", DATE_LANE + "\n" + DATE_LANE + "\n")],
}


@pytest.mark.parametrize("name", sorted(MUTANTS))
def test_each_mutant_of_the_build_file_fails_the_pin(name):
    p5, mutant = _text("ifs-ctl-p5.build"), _text("ifs-lane.build")
    for old, new in MUTANTS[name]:
        assert mutant.count(old) == 1, old
        mutant = mutant.replace(old, new)
    with pytest.raises(AssertionError):
        _check(p5, mutant)


def test_the_header_left_as_ifs_ctl_p5_builds_fails_the_pin():
    p5 = _text("ifs-ctl-p5.build")
    mutant = "\n".join(_split(p5)[0] + _split(_text("ifs-lane.build"))[1])
    with pytest.raises(AssertionError):
        _check(p5, mutant)


def test_the_file_is_lf_only_and_ascii():
    data = (Path(IFS_DIR) / "ifs-lane.build").read_bytes()
    assert b"\r" not in data and data.decode("ascii") and data.endswith(b"\n")
