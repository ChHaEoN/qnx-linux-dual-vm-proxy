"""What a harness must refuse or read from the running system before a record is taken on
another kernel or another board (2026-10-04): the HZ guard of the harnesses whose reports use a
bin fixed in microseconds, the Wi-Fi names no harness or report may carry as a literal, and the
stamp's system object, which no harness may shadow with an extra of its own.

Text tests over the harnesses and reports, and each fixed-bin harness run against a fake kernel
config until it refuses. Nothing here needs a board; every value is made up.
"""
import gzip
import io
import os
import re
import shutil
import subprocess
import sys
import tokenize

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
EL = os.path.join(HERE, "..", "orin-native", "edge-llm")
LIB = os.path.join(GC, "lib-measure.sh")
BASH = shutil.which("bash")
PREFLIGHT = "\n# ---------------------------------------------------------------- preflight\n"

# The harnesses whose reports score against a bin fixed at the 4 ms tick grid (HZ 250):
# tick_report.in_bin and the reports that reuse it, and the two with their own multiples of a
# jiffy. run-metal.sh is not one: it derives its period from the HZ it reads.
HZ_HARNESSES = ("run-tick.sh", "run-guesttick.sh", "run-partition.sh", "run-boots.sh", "run-boots2.sh",
                "run-irqconf.sh", "run-wifi.sh", "run-tailhost.sh", "run-tjphase.sh")
FIXED_GRID_REPORTS = ("tick_report.py", "tailhost_report.py", "tjphase_report.py")
NEEDS = {"run-partition.sh": {"BOOT_TAG": "A1"}, "run-boots.sh": {"BOOT_TAG": "b1"},
         "run-boots2.sh": {"BOOT_TAG": "b1"}, "run-wifi.sh": {"WIFI_IF": "wlan0"}}


def _text(path):
    with open(path, "rb") as f:
        return f.read().decode("utf-8").replace("\r\n", "\n")


def _scripts(*dirs):
    for d in dirs:
        for n in sorted(os.listdir(d)):
            if n.endswith((".sh", ".py")):
                yield os.path.join(d, n)


def _code(path):
    """The file's text without its comments. Shell: full-line comments and a trailing ` # ...`
    are dropped. Python: COMMENT tokens are dropped; a docstring is code and stays."""
    text = _text(path)
    if path.endswith(".py"):
        src = text.split("\n")
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                row, col = tok.start
                src[row - 1] = src[row - 1][:col]
        return "\n".join(src)
    lines = []
    for line in text.split("\n"):
        if line.lstrip().startswith("#"):
            continue
        lines.append(re.sub(r"\s#\s.*$", "", line))
    return "\n".join(lines)


# ------------------------------------------------------------------ the HZ guard

def _report_of(harness):
    m = re.search(r'^REPORT="\$\{REPORT:-\$here/([a-z0-9_]+\.py)\}"$', _text(os.path.join(GC, harness)), re.M)
    return m.group(1) if m else None


def test_the_guarded_harnesses_are_exactly_those_whose_reports_use_the_fixed_grid():
    """Derived from the code, so a new harness whose report reuses tick_report's bin has to take
    the guard, and one that stops using it is noticed."""
    want = set()
    for n in sorted(os.listdir(GC)):
        if not (n.startswith("run-") and n.endswith(".sh")):
            continue
        rep = _report_of(n)
        if rep is None:
            continue
        if rep in FIXED_GRID_REPORTS or "tr.in_bin(" in _code(os.path.join(GC, rep)):
            want.add(n)
    assert want == set(HZ_HARNESSES), sorted(want ^ set(HZ_HARNESSES))
    assert "tr.in_bin(" not in _code(os.path.join(GC, "metal_report.py")), "metal_report.py derives its own period"


@pytest.mark.parametrize("name", HZ_HARNESSES)
def test_a_fixed_grid_harness_requires_hz_250_before_it_prepares_anything(name):
    text = _text(os.path.join(GC, name))
    head, body = text.split("\nset -u\n", 1)
    assert "m_require_hz" not in head
    assert body.split("\n").count("m_require_hz 250") == 1, "one guard, a statement of its own"
    guard = body.index("\nm_require_hz 250\n")
    assert guard < body.index("\nm_prepare_out "), "the guard comes before the run's directory exists"
    # The first statement of the preflight: before the lock, before any sudo, before any change.
    assert body.count(PREFLIGHT) == 1 and body.index(PREFLIGHT) + len(PREFLIGHT) - 1 == guard, \
        "m_require_hz 250 is the preflight's first statement"
    assert "CONFIG_HZ" not in body and "config.gz" not in body, "the library reads the config, in one place"


def test_the_guard_is_a_refusal_and_never_a_scaled_bin():
    """The bins are pre-registered in microseconds on a 4 ms grid. The reports keep those
    constants; nothing derives them from an HZ."""
    tick = _text(os.path.join(GC, "tick_report.py"))
    assert "PERIOD, BIN_LO, WINDOW, GRID_OK = 4000.0, 3850.0, 250.0, 100.0" in tick
    assert "def in_bin(t0):\n    return t0 % PERIOD >= BIN_LO\n" in tick
    assert "GRID = 32000.0" in _text(os.path.join(GC, "tailhost_report.py"))
    tj = _text(os.path.join(GC, "tjphase_report.py"))
    assert "PERIOD = 1024000.0" in tj and "LATE = 4500.0" in tj
    lib = _text(LIB)
    fn = lib[lib.index("\nm_require_hz() {"):]
    fn = fn[:fn.index("\n}\n")]
    assert fn.count("|| die ") == 2 and "$HOST_HZ" in fn and "$((" not in fn, fn


def _stubs(tmp_path):
    """A sudo that records its arguments and refuses, and a python3 that is this interpreter."""
    b = tmp_path / "bin"
    b.mkdir(parents=True)
    (b / "sudo").write_bytes(('#!/usr/bin/env bash\necho "$*" >> "%s"\nexit 1\n'
                              % str(tmp_path / "sudo.calls").replace("\\", "/")).encode())
    (b / "python3").write_bytes(('#!/usr/bin/env bash\nexec "%s" "$@"\n' % sys.executable.replace("\\", "/")).encode())
    for p in (b / "sudo", b / "python3"):
        p.chmod(0o755)
    return b


def _refused(tmp_path, name, hz):
    """Run a harness against a fake kernel config (hz=None: none readable). Everything it could
    touch points into tmp_path, and sudo is a stub that refuses."""
    b = _stubs(tmp_path)
    gz = tmp_path / "config.gz"
    if hz is not None:
        with gzip.open(str(gz), "wb") as f:
            f.write(("# a made-up kernel config\nCONFIG_HZ_%d=y\nCONFIG_HZ=%d\nCONFIG_PREEMPT=y\n" % (hz, hz)).encode())
    console = tmp_path / "console.log"
    console.write_bytes(b"")
    env = dict(os.environ, KCONFIG_GZ=str(gz).replace("\\", "/"), KCONFIG_BOOT=str(tmp_path / "no-boot-config").replace("\\", "/"),
               CONSOLE=str(console).replace("\\", "/"), LOCK=str(tmp_path / "lock").replace("\\", "/"),
               HOME=str(tmp_path / "home").replace("\\", "/"), OUT=str(tmp_path / "out").replace("\\", "/"), TEGRA="0",
               PATH=str(b).replace("\\", "/") + os.pathsep + os.environ.get("PATH", ""), **NEEDS.get(name, {}))
    r = subprocess.run([BASH, os.path.join(GC, name)], capture_output=True, text=True, timeout=120, env=env)
    r.sudo_calls = (tmp_path / "sudo.calls").read_text() if (tmp_path / "sudo.calls").exists() else ""
    r.made_out = (tmp_path / "out").exists()
    r.took_lock = (tmp_path / "lock").exists()
    return r


@pytest.mark.skipif(BASH is None, reason="bash not available")
@pytest.mark.parametrize("name", HZ_HARNESSES)
def test_a_fixed_grid_harness_refuses_another_hz_and_an_unreadable_one(tmp_path, name):
    r = _refused(tmp_path / "hz1000", name, 1000)
    assert r.returncode != 0, r.stdout + r.stderr
    assert "CONFIG_HZ is 1000" in r.stderr and "HZ=250" in r.stderr, r.stderr
    assert r.sudo_calls == "" and not r.made_out and not r.took_lock, "refused before anything was touched: %r" % r.sudo_calls
    r = _refused(tmp_path / "unread", name, None)
    assert r.returncode != 0, r.stdout + r.stderr
    assert "cannot read CONFIG_HZ" in r.stderr and "HZ=250" in r.stderr, r.stderr
    assert r.sudo_calls == "" and not r.made_out and not r.took_lock, "refused before anything was touched: %r" % r.sudo_calls


# ------------------------------------------------------------------ the stamp's system object

def _stampers():
    return [p for p in _scripts(GC, EL) if p.endswith(".sh") and os.path.basename(p) != "lib-measure.sh"
            and "m_write_stamp" in _text(p)]


def test_no_harness_passes_an_extra_named_system():
    """The library writes "system" before the extras, and a later duplicate key wins in every
    JSON parser this project uses: an extra of that name would replace it in silence."""
    stampers = _stampers()
    assert len(stampers) >= 55, len(stampers)
    for p in stampers:
        assert not re.search(r'\\?"system\\?"\s*:', _text(p)), os.path.basename(p)
    lib = _text(LIB)
    stamp = lib[lib.index("\nm_write_stamp() {"):]
    stamp = stamp[:stamp.index("\n}\n")]
    assert stamp.index("\"system\": %s") < stamp.index('local kv; for kv in "$@"'), "system comes before the extras"


# ------------------------------------------------------------------ the Wi-Fi's names

WIFI_STATE_HARNESSES = ("run-bell.sh", "run-bellrate.sh", "run-edge.sh", "run-free.sh", "run-ipcbench.sh", "run-mmio.sh",
                        "run-offload.sh", "run-paths.sh", "run-pin.sh", "run-readtime.sh", "run-someip.sh",
                        "run-someip0.sh", "run-someip1.sh", "run-spin.sh", "run-trace.sh", "run-trace2.sh", "run-unmask.sh")
# One board's interface, its driver (and interrupt), and its module.
BOARD_NAMES = ("wlP1p1s0", "rtl88x2ce", "rtl8822ce")


@pytest.mark.parametrize("path", sorted(_scripts(GC, EL)), ids=os.path.basename)
def test_no_harness_report_or_library_names_one_boards_wifi_outside_a_comment(path):
    code = _code(path)
    for name in BOARD_NAMES:
        assert name not in code, "%s carries %s outside a comment" % (os.path.basename(path), name)


def test_every_wifi_state_stamp_line_is_the_librarys_helper():
    users = sorted(os.path.basename(p) for p in _scripts(GC, EL)
                   if p.endswith(".sh") and os.path.basename(p) != "lib-measure.sh" and 'wifi_state\\"' in _code(p))
    assert users == sorted(WIFI_STATE_HARNESSES), users
    for n in WIFI_STATE_HARNESSES:
        body = _text(os.path.join(GC, n)).split("\nset -u\n", 1)[1]
        lines = [l for l in body.split("\n") if "wifi_state" in l]
        assert lines == ['\t"\\"wifi_state\\": \\"$(m_wifi_state)\\"" \\'], (n, lines)
        assert "operstate" not in body, "%s reads an interface's state itself" % n
    for p in _scripts(GC, EL):
        if p.endswith(".sh") and os.path.basename(p) != "lib-measure.sh":
            assert "operstate" not in _code(p), "%s reads an interface's state itself" % os.path.basename(p)


def test_the_library_finds_wireless_interfaces_by_what_they_are_not_by_a_name():
    lib = _text(LIB)
    for fn in ("_wifi_ifs() {", "m_wifi_if() {", "m_wifi_state() {"):
        assert "\n" + fn in lib, fn
    ifs = lib[lib.index("\n_wifi_ifs() {"):]
    ifs = ifs[:ifs.index("\n}\n")]
    assert '"${SYS_ROOT:-/sys}"/class/net/*' in ifs and "phy80211" in ifs
    assert "wl" not in ifs.replace("_wifi_ifs", ""), "no name pattern: an interface is wireless when it has a phy80211"
