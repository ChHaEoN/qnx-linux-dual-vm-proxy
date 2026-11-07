"""Phase 8 WP4b 7.1 (the Phase 8 specification's 2.7 and 2.12): sdv/aw, the ROS environment, the project entrypoint
and the host check every container started from the Autoware image, or built on it, runs under.

- ros-env.json: its four keys and values (ROS domain 73, rmw_cyclonedds_cpp), and its single-host DDS XML: equal to
  WP4a's cfg/cyclonedds-lo.xml but for comments (that file's text less its one comment is held below with the
  sha256 derived from it on 2026-10-20), with the loopback interface `lo`,
  multicast off, 127.0.0.1 the only unicast peer, participant index auto up to 160, the image's MaxMessageSize and
  WhcHigh kept and no receive-buffer minimum.
- aw-entrypoint.sh: read as text (bash; no `ip`, `sysctl`, `gosu`, `usermod` or `chown` anywhere in it; it sources
  exactly the two setup files, in order, and its last line is `exec "$@"`; no redirection but to stderr and no
  command that writes a file), and run on a copy whose two setup paths point at stand-ins, with a stand-in `id` first
  and alone on PATH: as a user it sources both, in order, and replaces itself with the command (the command's pid is
  the script's), the command's arguments and exit status intact, and the ROS environment (domain, rmw, DDS file, log
  directory) and the umask it was started with unchanged; as root, with no command or with a setup file missing it
  refuses and runs nothing, and its printed refusal says what the header and the README say: root, or `id -u`
  printing no number.
- hostcheck.sh: against stand-ins for `ip` and `sysctl` alone on PATH (so it runs no other program): the fixed form
  it prints, the four reads it makes, its refusals when one cannot be read; `--compare` on files in that form: equal,
  each of the four changed alone, two changed, each way a file can fail the form, a last line with no line end still
  read, and a third argument after two good files refused.

What this does NOT show: that the XML works for any ROS process (WP4a's run used it; WP4b's runs are the next use);
that the entrypoint's setup files exist in the image under those paths (WP4a's runs sourced them, spec section 1);
that the four settings are the only host settings a container could change (they are the ones the image's own
entrypoint changes, W4 S4); anything on the Orin or a metal host. The shell tests run where bash runs and not on
Windows.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
AW = REPO / "sdv" / "aw"
ENV_FILE = AW / "ros-env.json"
ENTRYPOINT = AW / "aw-entrypoint.sh"
HOSTCHECK = AW / "hostcheck.sh"
README = AW / "README.md"
BASH = shutil.which("bash")
needs_bash = pytest.mark.skipif(BASH is None or sys.platform == "win32", reason="the shell tests need bash off Windows")

# The comment-free single-host XML: loopback, unicast peer and bounded participant indices.
# sdv/aw/README.md explains these choices; WP4A_XML_SHA256 pins this test's reference text.
# The second line is split only to keep this file's width.
WP4A_XML = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<CycloneDDS xmlns="https://cdds.io/config" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xsi:schemaLocation="https://cdds.io/config '
            'https://raw.githubusercontent.com/eclipse-cyclonedds/cyclonedds/master/etc/cyclonedds.xsd">\n' + '''\
  <Domain Id="any">
    <General>
      <Interfaces>
        <NetworkInterface name="lo" multicast="false"/>
      </Interfaces>
      <AllowMulticast>false</AllowMulticast>
      <MaxMessageSize>65500B</MaxMessageSize>
    </General>
    <Internal>
      <Watermarks>
        <WhcHigh>500kB</WhcHigh>
      </Watermarks>
    </Internal>
    <Discovery>
      <ParticipantIndex>auto</ParticipantIndex>
      <MaxAutoParticipantIndex>160</MaxAutoParticipantIndex>
      <Peers>
        <Peer address="127.0.0.1"/>
      </Peers>
    </Discovery>
  </Domain>
</CycloneDDS>
''')
WP4A_XML_SHA256 = "83fc6ad56c0667d9c71769a674802163d0426a7f47458b3e69b65f910988389e"
NS = "{https://cdds.io/config}"
SETTINGS = ("lo.flags", "net.core.rmem_max", "net.ipv4.ipfrag_time", "net.ipv4.ipfrag_high_thresh")
SYSCTLS = SETTINGS[1:]
SETUP_FILES = ("/opt/ros/jazzy/setup.bash", "/opt/autoware/setup.bash")
FORBIDDEN = ("ip", "sysctl", "gosu", "usermod", "chown")


def env():
    return json.loads(ENV_FILE.read_text(encoding="utf-8"))


def canonical(xml_text):
    """The XML with its comments, its declaration and the whitespace between elements dropped (C14N 2.0)."""
    return ET.canonicalize(xml_data=xml_text, with_comments=False, strip_text=True)


def code_lines(path):
    """A shell script's lines that are neither blank nor a comment (the shebang included)."""
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and (not s.startswith("#") or s.startswith("#!")):
            out.append(s)
    return out


# ============================================================ ros-env.json

def test_the_environment_file_holds_exactly_its_four_keys_and_values():
    e = env()
    assert list(e) == ["format", "ros_domain_id", "rmw", "cyclonedds_single_host"]
    assert e["format"] == 1 and type(e["format"]) is int
    assert e["ros_domain_id"] == 73 and type(e["ros_domain_id"]) is int        # WP4a's choice; never 0
    assert e["rmw"] == "rmw_cyclonedds_cpp"
    assert isinstance(e["cyclonedds_single_host"], str)


def test_the_held_wp4a_file_is_the_one_read():
    assert hashlib.sha256(WP4A_XML.encode("utf-8")).hexdigest() == WP4A_XML_SHA256


def test_the_held_wp4a_xml_is_its_comment_free_form():
    """WP4a's comment gave its reasons and one reading of a host; the test holds the XML without it (the reasons are in
    the README), so no reading enters the tree."""
    assert "<!--" not in WP4A_XML and "-->" not in WP4A_XML
    assert WP4A_XML.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<CycloneDDS ') and WP4A_XML.endswith("</CycloneDDS>\n")


def test_the_xml_is_wp4as_but_for_comments():
    xml = env()["cyclonedds_single_host"]
    assert canonical(xml) == canonical(WP4A_XML)
    assert "<!--" not in xml                                                    # the reasons live in the README
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<CycloneDDS ')


def test_the_xml_keeps_dds_on_the_loopback_with_no_multicast_and_one_peer():
    root = ET.fromstring(env()["cyclonedds_single_host"])
    assert root.tag == NS + "CycloneDDS"
    ifs = root.findall(".//%sNetworkInterface" % NS)
    assert [(i.get("name"), i.get("multicast")) for i in ifs] == [("lo", "false")]
    assert [x.text for x in root.iter(NS + "AllowMulticast")] == ["false"]
    assert [p.get("address") for p in root.iter(NS + "Peer")] == ["127.0.0.1"]
    assert [x.text for x in root.iter(NS + "ParticipantIndex")] == ["auto"]
    assert [x.text for x in root.iter(NS + "MaxAutoParticipantIndex")] == ["160"]
    assert [x.text for x in root.iter(NS + "MaxMessageSize")] == ["65500B"]
    assert [x.text for x in root.iter(NS + "WhcHigh")] == ["500kB"]
    assert not list(root.iter(NS + "SocketReceiveBufferSize"))                  # rmem_max is never raised
    assert [d.get("Id") for d in root.iter(NS + "Domain")] == ["any"]          # the domain is ROS_DOMAIN_ID's


# ============================================================ aw-entrypoint.sh, as text

def test_the_entrypoint_holds_no_command_that_changes_the_host_or_a_user():
    text = ENTRYPOINT.read_text(encoding="utf-8")
    for word in FORBIDDEN:
        assert not re.search(r"(?<![\w.-])%s(?![\w-])" % re.escape(word), text), word
    for word in ("/proc/sys", "/sys/"):
        assert word not in text, word
    for s in code_lines(ENTRYPOINT)[1:]:
        assert not re.search(r"(?<![\w.-])(sudo|su|chmod|setcap|mount|capsh|nsenter)(?![\w-])", s), s


def test_the_entrypoint_sources_exactly_the_two_setup_files_and_execs_its_arguments():
    lines = code_lines(ENTRYPOINT)
    assert lines[0] == "#!/bin/bash"
    sourced = [m.group(2) for m in (re.match(r"^(source|\.)\s+(\S+)", s) for s in lines) if m]
    assert sourced == list(SETUP_FILES)
    for path in SETUP_FILES:
        assert [s for s in lines if path in s] == ["source %s || exit 1" % path]
    assert lines[-1] == 'exec "$@"'
    assert sum(1 for s in lines if s.startswith("exec")) == 1


def test_the_entrypoint_writes_no_file():
    for s in code_lines(ENTRYPOINT)[1:]:
        assert not re.search(r"\b(tee|cp|mv|rm|mkdir|touch|dd|ln|install|truncate)\b", s), s
        for m in re.finditer(r">+", s):
            assert s[m.start():m.start() + 3] == ">&2", s                    # only to stderr


# ============================================================ aw-entrypoint.sh, run on a copy

def _entrypoint_copy(tmp_path, uid="1000", missing=None):
    """A copy of the script with the two setup paths pointing at stand-ins that log and export a mark, and a bin
    directory holding only a stand-in `id` that prints `uid`."""
    log = tmp_path / "sourced.log"
    text = ENTRYPOINT.read_text(encoding="utf-8")
    for i, path in enumerate(SETUP_FILES):
        stand_in = tmp_path / ("setup%d.bash" % i)
        if i != missing:
            stand_in.write_text('echo %d >> "%s"\nexport SDV_SETUP%d=yes\n' % (i, log, i), encoding="utf-8")
        assert text.count(path) == 1
        text = text.replace(path, str(stand_in))
    copy = tmp_path / "aw-entrypoint.sh"
    copy.write_text(text, encoding="utf-8")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    stub = bindir / "id"
    stub.write_text('#!%s\n[ "$*" = "-u" ] || exit 9\necho %s\n' % (BASH, uid), encoding="utf-8")
    stub.chmod(0o755)
    return copy, log, {"PATH": str(bindir), "HOME": str(tmp_path)}


@needs_bash
def test_the_entrypoint_sources_both_in_order_and_replaces_itself_with_the_command(tmp_path):
    copy, log, envv = _entrypoint_copy(tmp_path)
    out = tmp_path / "out"
    cmd = 'echo "$$ $SDV_SETUP0 $SDV_SETUP1" > "%s"; printf "%%s\\n" "$@" >> "%s"; exit 7' % (out, out)
    p = subprocess.Popen([BASH, str(copy), BASH, "-c", cmd, "argv0", "a b", "c"], env=envv)
    assert p.wait(timeout=30) == 7
    first, *args = out.read_text(encoding="utf-8").splitlines()
    assert first == "%d yes yes" % p.pid                                         # exec: the command is the script's process
    assert args == ["a b", "c"]
    assert log.read_text(encoding="utf-8").split() == ["0", "1"]


@needs_bash
def test_the_entrypoint_hands_the_command_the_ros_environment_and_umask_unchanged(tmp_path):
    """2.7: every container sets ROS_DOMAIN_ID, RMW_IMPLEMENTATION and CYCLONEDDS_URI from ros-env.json, and 2.12: never mode
    777. The script is started under umask 027 with those variables (and ROS_LOG_DIR) set: the command sees all four as they
    were and the same umask, so the script exports, unsets and loosens none of them."""
    copy, log, envv = _entrypoint_copy(tmp_path)
    ros = {"ROS_DOMAIN_ID": "73", "RMW_IMPLEMENTATION": "rmw_cyclonedds_cpp", "CYCLONEDDS_URI": "<CycloneDDS/>",
           "ROS_LOG_DIR": "/var/tmp/run/ros-log"}
    cmd = 'umask; for k in %s; do echo "$k=${!k-UNSET}"; done' % " ".join(ros)
    out = subprocess.run([BASH, str(copy), BASH, "-c", cmd], env=dict(envv, **ros), capture_output=True, text=True, timeout=30,
                         preexec_fn=lambda: os.umask(0o027))
    assert out.returncode == 0, out.stderr
    assert out.stdout.splitlines() == ["0027"] + ["%s=%s" % kv for kv in ros.items()]


@needs_bash
@pytest.mark.parametrize("uid", ["0", "", "x1"])
def test_the_entrypoint_refuses_root_or_an_unknown_uid_and_runs_nothing(tmp_path, uid, capfd):
    copy, log, envv = _entrypoint_copy(tmp_path, uid=uid)
    rc = subprocess.run([BASH, str(copy), BASH, "-c", 'echo ran > "%s"' % (tmp_path / "ran")], env=envv, timeout=30).returncode
    assert rc == 2 and "--user aw" in capfd.readouterr().err
    assert not (tmp_path / "ran").exists() and not log.exists()


@needs_bash
def test_the_entrypoint_refuses_no_command(tmp_path, capfd):
    copy, log, envv = _entrypoint_copy(tmp_path)
    assert subprocess.run([BASH, str(copy)], env=envv, timeout=30).returncode == 2
    assert "no command" in capfd.readouterr().err and not log.exists()


@needs_bash
@pytest.mark.parametrize("missing", [0, 1])
def test_the_entrypoint_stops_when_a_setup_file_cannot_be_sourced(tmp_path, missing):
    copy, log, envv = _entrypoint_copy(tmp_path, missing=missing)
    rc = subprocess.run([BASH, str(copy), BASH, "-c", 'echo ran > "%s"' % (tmp_path / "ran")], env=envv, timeout=30,
                        capture_output=True).returncode
    assert rc == 1 and not (tmp_path / "ran").exists()
    assert (log.read_text(encoding="utf-8").split() if log.exists() else []) == (["0"] if missing == 1 else [])


# ============================================================ hostcheck.sh

# What the stand-ins serve: a loopback's flags without MULTICAST (the form `ip -br` prints for any such interface), and
# three made-up sysctl values (each one digit repeated), none a reading of any host.
HOST = {"lo.flags": "<LOOPBACK,UP,LOWER_UP>", "net.core.rmem_max": "1111111", "net.ipv4.ipfrag_time": "22",
        "net.ipv4.ipfrag_high_thresh": "3333333"}
FORM = ["format=1", "lo.flags=LOOPBACK,UP,LOWER_UP", "net.core.rmem_max=1111111", "net.ipv4.ipfrag_time=22",
        "net.ipv4.ipfrag_high_thresh=3333333"]
IP_STUB = r'''#!%(bash)s
echo "ip $*" >> "%(d)s/calls.log"
[ ! -e "%(d)s/ip.fail" ] || exit 1
printf 'lo               UNKNOWN        00:00:00:00:00:00 %%s \n' "$(< "%(d)s/lo.flags")"
'''
SYSCTL_STUB = r'''#!%(bash)s
echo "sysctl $*" >> "%(d)s/calls.log"
[ "$1" = "-n" ] && [ "$#" = 2 ] || exit 9
[ -e "%(d)s/$2" ] || { echo "sysctl: cannot stat /proc/sys/$2" >&2; exit 255; }
printf '%%s\n' "$(< "%(d)s/$2")"
'''


def test_the_host_stand_ins_hold_made_up_values():
    """The three sysctl values the stand-ins serve are made up (each one digit repeated, which marks them so), never a
    reading of a real host; FORM holds the same."""
    for k in SYSCTLS:
        assert HOST[k].isdigit() and len(set(HOST[k])) == 1, k
    assert FORM[2:] == ["%s=%s" % (k, HOST[k]) for k in SYSCTLS] and FORM[1] == "lo.flags=" + HOST["lo.flags"].strip("<>")


def _host(tmp_path, values=None, ip_fails=False):
    d = tmp_path / "host"
    (d / "bin").mkdir(parents=True)
    for name, text in (("ip", IP_STUB), ("sysctl", SYSCTL_STUB)):
        f = d / "bin" / name
        f.write_text(text % {"bash": BASH, "d": d}, encoding="utf-8")
        f.chmod(0o755)
    for k, v in dict(HOST, **(values or {})).items():
        if v is not None:
            (d / k).write_text(v, encoding="utf-8")
    if ip_fails:
        (d / "ip.fail").write_text("", encoding="utf-8")
    return d


def _hostcheck(d, *args):
    """hostcheck.sh with the two stand-ins alone on PATH."""
    return subprocess.run([BASH, str(HOSTCHECK)] + [str(a) for a in args], env={"PATH": str(d / "bin")},
                          capture_output=True, text=True, timeout=30)


@needs_bash
def test_hostcheck_prints_the_four_settings_in_its_fixed_form_from_four_reads(tmp_path):
    d = _host(tmp_path)
    r = _hostcheck(d)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == FORM and r.stdout.endswith("\n")
    assert (d / "calls.log").read_text(encoding="utf-8").splitlines() == \
        ["ip -br link show lo"] + ["sysctl -n %s" % s for s in SYSCTLS]


@needs_bash
def test_hostcheck_reports_the_multicast_flag_when_lo_has_it(tmp_path):
    r = _hostcheck(_host(tmp_path, {"lo.flags": "<LOOPBACK,MULTICAST,UP,LOWER_UP>"}))
    assert r.returncode == 0 and "lo.flags=LOOPBACK,MULTICAST,UP,LOWER_UP" in r.stdout.splitlines()


@needs_bash
@pytest.mark.parametrize("case", ["ip fails", "no flags", "bad flags", "sysctl fails"] + ["%s missing" % s for s in SYSCTLS]
                         + ["%s not a number" % s for s in SYSCTLS])
def test_hostcheck_prints_nothing_and_exits_2_when_a_setting_cannot_be_read(tmp_path, case):
    values = {}
    if case == "no flags":
        values["lo.flags"] = "LOOPBACK,UP"
    elif case == "bad flags":
        values["lo.flags"] = "<loopback up>"
    elif case == "sysctl fails":
        values["net.core.rmem_max"] = None
    elif case.endswith(" missing"):
        values[case.split()[0]] = None
    elif case.endswith(" not a number"):
        values[case.split()[0]] = "1111111 x"
    r = _hostcheck(_host(tmp_path, values, ip_fails=(case == "ip fails")))
    assert r.returncode == 2 and r.stdout == "" and "hostcheck.sh" in r.stderr


def _form(tmp_path, name, lines):
    f = tmp_path / name
    f.write_text("".join(x + "\n" for x in lines), encoding="utf-8")
    return f


@needs_bash
def test_hostcheck_compare_passes_two_equal_reads(tmp_path):
    d = _host(tmp_path)
    before = _form(tmp_path, "before.txt", _hostcheck(d).stdout.splitlines())
    after = _form(tmp_path, "after.txt", _hostcheck(d).stdout.splitlines())
    r = _hostcheck(d, "--compare", before, after)
    assert (r.returncode, r.stdout) == (0, ""), r.stderr


@needs_bash
@pytest.mark.parametrize("setting", SETTINGS)
def test_hostcheck_compare_fails_naming_each_setting_that_changed(tmp_path, setting):
    d = _host(tmp_path)
    changed = {"lo.flags": "LOOPBACK,MULTICAST,UP,LOWER_UP", "net.core.rmem_max": "2147483647", "net.ipv4.ipfrag_time": "3",
               "net.ipv4.ipfrag_high_thresh": "134217728"}[setting]
    after_lines = [x if x.split("=")[0] != setting else "%s=%s" % (setting, changed) for x in FORM]
    r = _hostcheck(d, "--compare", _form(tmp_path, "b", FORM), _form(tmp_path, "a", after_lines))
    old = dict(x.split("=", 1) for x in FORM)[setting]
    assert r.returncode == 1
    assert r.stdout.splitlines() == ["changed %s before=%s after=%s" % (setting, old, changed)]


@needs_bash
def test_hostcheck_compare_names_every_setting_that_changed(tmp_path):
    after_lines = FORM[:2] + ["net.core.rmem_max=1", FORM[3], "net.ipv4.ipfrag_high_thresh=2"]
    r = _hostcheck(_host(tmp_path), "--compare", _form(tmp_path, "b", FORM), _form(tmp_path, "a", after_lines))
    assert r.returncode == 1
    assert r.stdout.splitlines() == ["changed net.core.rmem_max before=1111111 after=1",
                                     "changed net.ipv4.ipfrag_high_thresh before=3333333 after=2"]


@needs_bash
@pytest.mark.parametrize("fault", ["missing %s" % s for s in SETTINGS] + ["missing format", "format 2", "repeated", "unknown",
                                                                             "not key=value", "carriage return", "empty"])
@pytest.mark.parametrize("which", ["before", "after"])
def test_hostcheck_compare_refuses_a_file_not_in_the_fixed_form(tmp_path, fault, which):
    bad = list(FORM)
    if fault.startswith("missing "):
        bad = [x for x in bad if x.split("=")[0] != fault.split()[1]]
    elif fault == "format 2":
        bad[0] = "format=2"
    elif fault == "repeated":
        bad.append(FORM[2])
    elif fault == "unknown":
        bad.append("net.ipv4.ip_forward=0")
    elif fault == "not key=value":
        bad.insert(1, "lo UNKNOWN")
    elif fault == "carriage return":
        bad[2] += "\r"
    else:
        bad = []
    good, broken = _form(tmp_path, "good", FORM), _form(tmp_path, "broken", bad)
    args = (broken, good) if which == "before" else (good, broken)
    r = _hostcheck(_host(tmp_path), "--compare", *args)
    assert r.returncode == 2 and r.stdout == "" and "hostcheck.sh" in r.stderr, (r.returncode, r.stdout)


@needs_bash
@pytest.mark.parametrize("args", [["--compare"], ["--compare", "x"], ["--compare", "x", "y", "z"], ["--set"], ["x"], ["-h"], ["--help"],
                                  ["--compare=x"], ["--compare", "--compare", "x"]])
def test_hostcheck_refuses_a_wrong_command_line(tmp_path, args):
    r = _hostcheck(_host(tmp_path), *args)
    assert r.returncode == 2 and r.stdout == ""


@needs_bash
def test_hostcheck_compare_refuses_a_file_it_cannot_read(tmp_path):
    good = _form(tmp_path, "good", FORM)
    r = _hostcheck(_host(tmp_path), "--compare", good, tmp_path / "absent")
    assert r.returncode == 2 and r.stdout == ""


def test_hostcheck_only_reads():
    """Every code line that names `ip` names it as `ip -br link show lo`, and every one that names `sysctl` as
    `sysctl -n`: no setting is ever written."""
    lines = code_lines(HOSTCHECK)
    assert lines[0] == "#!/bin/bash"
    text = "\n".join(lines)
    for word in (" -w", "link set", "/proc/sys", "tee ", ">/", "> /"):
        assert word not in text, word
    ips = [s for s in lines if re.search(r"(?<![\w.-])ip(?![\w-])", s)]
    sysctls = [s for s in lines if re.search(r"(?<![\w.-])sysctl(?![\w-])", s)]
    assert ips and all("ip -br link show lo" in s for s in ips), ips
    assert sysctls and all("sysctl -n " in s for s in sysctls), sysctls


# ============================================================ the README and the files

def test_the_readme_states_the_three_files_the_layers_and_what_they_do_not_show():
    text = README.read_text(encoding="utf-8")
    flat = " ".join(text.split())
    for name in ("ros-env.json", "aw-entrypoint.sh", "hostcheck.sh", "aw_scenario.py", "scenario.jsonl"):
        assert name in text, name
    for phrase in ("--entrypoint", "--user aw", "--cap-drop ALL", "no-new-privileges", "--privileged", "--cap-add",
                   "/docker-entrypoint.sh", "ROS_DOMAIN_ID", "CYCLONEDDS_URI", "RMW_IMPLEMENTATION", "ROS_LOG_DIR",
                   "host-before.txt", "--compare", "--require-claim-node"):
        assert phrase in flat, phrase
    tail = flat[flat.index("## What this does not demonstrate"):]
    for phrase in ("timing", "Orin", "metal host", "stand-ins"):
        assert phrase in tail, phrase


def test_the_scripts_and_this_file_keep_to_150_columns():
    for p in (ENTRYPOINT, HOSTCHECK, Path(__file__)):
        wide = [i + 1 for i, line in enumerate(p.read_text(encoding="utf-8").splitlines()) if len(line) > 150]
        assert wide == [], (p.name, wide)


def test_the_package_leaves_no_carriage_return_and_no_bytecode():
    for p in [ENV_FILE, ENTRYPOINT, HOSTCHECK, README, Path(__file__)]:
        assert b"\r" not in p.read_bytes(), p
    assert sorted(x.name for x in AW.iterdir()) == ["README.md", "aw-entrypoint.sh", "aw_g1_count.py", "aw_g1_diag.py", "g1_sampler.py",
                                                    "g1_watchdog.py", "hostcheck.sh", "prereg-g1g2.md", "ros-env.json"]
    assert not list(AW.rglob("__pycache__"))
    assert os.path.isfile(HOSTCHECK) and os.path.isfile(ENTRYPOINT)


# ============================================================ hostcheck.sh's command line, once more

@needs_bash
def test_hostcheck_compare_refuses_an_extra_argument_after_two_good_files(tmp_path):
    """--compare takes exactly two files: a third argument after two files that read well is a wrong command line (exit 2,
    nothing printed), not a comparison of the first two."""
    good = _form(tmp_path, "good", FORM)
    r = _hostcheck(_host(tmp_path), "--compare", good, good, good)
    assert r.returncode == 2 and r.stdout == ""


# ============================================================ hostcheck.sh's last line, the entrypoint's refusal in words

@needs_bash
def test_hostcheck_compare_reads_a_last_line_that_has_no_line_end(tmp_path):
    """A file whose last line lacks its line end (a hand-trimmed copy) is still read whole, not refused for a missing line."""
    good = _form(tmp_path, "good", FORM)
    trimmed = tmp_path / "trimmed"
    trimmed.write_text("\n".join(FORM), encoding="utf-8")
    r = _hostcheck(_host(tmp_path), "--compare", good, trimmed)
    assert (r.returncode, r.stdout) == (0, ""), r.stderr


@needs_bash
def test_the_entrypoints_refusal_says_root_or_no_number(tmp_path, capfd):
    """The printed refusal says what the script's header and the README say: root, or `id -u` printing no number."""
    copy, log, envv = _entrypoint_copy(tmp_path, uid="")
    assert subprocess.run([BASH, str(copy), "true"], env=envv, timeout=30).returncode == 2
    assert "running as root, or id -u printed no number; start the container with --user aw" in capfd.readouterr().err
