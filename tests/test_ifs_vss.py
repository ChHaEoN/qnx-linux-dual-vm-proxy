"""ifs-vss.build (SDV Phase 2, WP11; kind4-spec section 13) as ifs-live.build plus exactly the kind 4
lines. The roots are mixed on purpose: the vss monitor and the build file itself point into the SDV
worktree (S), every other staged file keeps the main checkout's path (M). Every file in these build files
is [+optional], so a wrong path is silent to mkifs; this pins the lines, and compare-ifs.py on the Windows
side accepts the image. No image is read here."""
import os
import re

import pytest

HERE = os.path.dirname(__file__)
IFS_DIR = os.path.join(HERE, "..", "ipc-test", "qnx-safety-monitor")
M = "E:/Project/qnx-linux-dual-vm-proxy/"
S = "E:/Project/qnx-linux-dual-vm-proxy-sdv-local/"
MON = "ipc-test/qnx-safety-monitor/"
SVC_7102 = "/proc/boot/qnx-safety-monitor 7102 svc 2000 &"
KIND4 = ["/proc/boot/qnx-safety-monitor 7160 svc 500 &", "/proc/boot/qnx-safety-monitor 7161 stamp &"]
MONITOR_VSS = "[perms=555] qnx-safety-monitor=" + S + MON + "qnx-safety-monitor-vss"
BUILDFILE_VSS = "[perms=0444] build/ifs.build=" + S + MON + "ifs-vss.build"
REMOVED = ["[perms=0444] build/ifs.build=" + M + MON + "ifs-live.build",
           "[perms=0444] build.date = output/build/ifs-live.build.date",
           "[perms=555] qnx-safety-monitor=" + M + MON + "qnx-safety-monitor-live"]
ADDED = KIND4 + [BUILDFILE_VSS, "[perms=0444] build.date = output/build/ifs-vss.build.date", MONITOR_VSS]


def _text(name):
    with open(os.path.join(IFS_DIR, name), encoding="utf-8") as f:
        return f.read()


def _lines(text):
    return [ln.rstrip() for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


def _check(live_text, vss_text):
    live, vss = _lines(live_text), _lines(vss_text)
    removed = [ln for ln in live if ln not in vss]
    added = [ln for ln in vss if ln not in live]
    assert removed == REMOVED, removed
    assert added == ADDED, added
    # Nothing else moved, doubled or dropped: what remains is ifs-live.build's, in its order.
    assert [ln for ln in vss if ln not in ADDED] == [ln for ln in live if ln not in REMOVED]
    at = vss.index(SVC_7102)
    assert vss[at + 1:at + 3] == KIND4, vss[at:at + 3]
    # Both roots, each where it belongs: S for the monitor and the build file, M for every other host path.
    for ln in vss:
        if "E:/" not in ln:
            continue
        host = ln[ln.index("E:/"):]
        if ln in (MONITOR_VSS, BUILDFILE_VSS):
            assert host.startswith(S), ln
        else:
            assert host.startswith(M) and not host.startswith(S), ln


def test_ifs_vss_is_ifs_live_with_exactly_the_kind4_lines():
    _check(_text("ifs-live.build"), _text("ifs-vss.build"))


def test_both_roots_are_used_where_the_plan_puts_them():
    vss = _lines(_text("ifs-vss.build"))
    hosts = [ln[ln.index("E:/"):] for ln in vss if "E:/" in ln]
    assert [h for h in hosts if h.startswith(S)] == [S + MON + "ifs-vss.build", S + MON + "qnx-safety-monitor-vss"]
    assert "[perms=555] qnx-echo-server-net=" + M + "ipc-test/qnx-server-net/qnx-echo-server-net" in vss


def test_the_vss_monitor_binary_name_is_its_own():
    others = [n for n in os.listdir(IFS_DIR) if n.startswith("ifs-") and n.endswith(".build") and n != "ifs-vss.build"]
    assert "ifs-live.build" in others and len(others) > 10, others
    for n in others:
        assert "qnx-safety-monitor-vss" not in _text(n), n


def test_the_header_names_the_differences_and_the_acceptance_rule_and_no_hash():
    text = _text("ifs-vss.build")
    head = []
    for ln in text.splitlines():
        if not ln.startswith("#"):
            break
        head.append(ln.lstrip("#").strip())
    flat = " ".join(" ".join(head).split())
    for s in ("it is ifs-live.build", "qnx-safety-monitor-vss", "`make vss`", "MONITOR_EXT_KINDS=0x10",
              "TCP 7160 `svc 500`", "TCP 7161 `stamp`", "build/ifs.build -> this file",
              "output/build/ifs-vss.build.date", "MIXED ROOTS", "[+optional]", "the OD14 record names",
              "compare-ifs.py", "qnx-safety-monitor, startup-script, build/ifs.build and build.date",
              "none is added and none removed", '"vss rules:"', "never by exit code"):
        assert s in flat, s
    # sha256 values are kept locally only: no hash-like run in the header.
    assert re.search(r"\b[0-9a-f]{8,}\b", "\n".join(head)) is None


PAIR = KIND4[0] + "\n" + KIND4[1] + "\n"
# Each mutant is a list of (old, new) edits applied in turn; every old must occur exactly once.
MUTANTS = {
    "an extra staged file": [(MONITOR_VSS + "\n", MONITOR_VSS + "\n[perms=555] qnx-extra=" + M + "ipc-test/qnx-extra\n")],
    "the monitor at M's default binary": [(MONITOR_VSS, "[perms=555] qnx-safety-monitor=" + M + MON + "qnx-safety-monitor")],
    "the monitor at S's default binary": [(MONITOR_VSS, "[perms=555] qnx-safety-monitor=" + S + MON + "qnx-safety-monitor")],
    "the monitor at M's vss path": [(MONITOR_VSS, "[perms=555] qnx-safety-monitor=" + M + MON + "qnx-safety-monitor-vss")],
    "the 7160 start line missing": [(KIND4[0] + "\n", "")],
    "the 7161 start line missing": [(KIND4[1] + "\n", "")],
    "the start lines swapped": [(PAIR, KIND4[1] + "\n" + KIND4[0] + "\n")],
    "the start lines before :7102": [(PAIR, ""), (SVC_7102 + "\n", PAIR + SVC_7102 + "\n")],
    "the echo server moved to S": [(M + "ipc-test/qnx-server-net/", S + "ipc-test/qnx-server-net/")],
    "the build file at M's root": [(BUILDFILE_VSS, "[perms=0444] build/ifs.build=" + M + MON + "ifs-vss.build")],
    "a staged file doubled": [(MONITOR_VSS + "\n", MONITOR_VSS + "\n" + "lib/libm.so.3\n")],
}


@pytest.mark.parametrize("name", sorted(MUTANTS))
def test_each_mutant_of_the_build_file_fails_the_pin(name):
    live, mutant = _text("ifs-live.build"), _text("ifs-vss.build")
    for old, new in MUTANTS[name]:
        assert mutant.count(old) == 1, old
        mutant = mutant.replace(old, new)
    with pytest.raises(AssertionError):
        _check(live, mutant)
