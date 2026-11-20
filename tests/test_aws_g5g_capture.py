"""What the capture takes as evidence of a g5g session (SDV Phase 8, the g5g leg: T10).

capture.py runs on made-up records, and remote-ladder.sh's capture phase on a made-up session directory, with the
real redactor. A g5g stem is gpu-facts, gpu-facts-N, gpu-install, llama-build or vlm. Every value in a record here is
a stand-in.

What these tests do not show: what a real phase writes into its stem (test_aws_g5g_phases.py runs the phases against
stubs), or that any of it ran on an instance.

KVM here boots our startup-qemu-virt; this is not a QNX-supported
configuration, and no timing claim attaches to the boot.
"""
import json
import os
import re
import shutil
import subprocess

import pytest

import test_aws_tooling as aws
from test_aws_tooling import BASH, needs_bash

SUMMARY = "capture: %d JSON verbatim, %d JSON with strings redacted, %d text files redacted"
FACTS = ("gpu-facts: cpu_part=0x41:0xd0c kvm=yes nvidia_pci=2 pci_ids=0x1eb4,0x1eb4 bound=none,none driver=absent "
         "uvm=no nodes=0/4 gpus=0 compute_cap=none kernel_oops=no boot=same")
AFTER = "2026-01-01T00:00:00Z\n0.00 0.00 0.00 1/100 1\nkernel_oops=no\nboot=same"
EVIDENCE = {
    "gpu-facts": {"host-after.txt": AFTER, "summary.txt": FACTS},
    "gpu-facts-2": {"host-after.txt": AFTER, "summary.txt": FACTS},
    "gpu-install": {"host-after.txt": AFTER, "set.txt": "cmake=0.0.1-1"},
    "llama-build": {"host-after.txt": AFTER, "BUILD-INFO": "llama.cpp commit " + "c" * 40},
    "vlm": {"host-after.txt": AFTER, "demo-exit.txt": "1"},
}
MISSING = {"gpu-facts": "host-after.txt, summary.txt with cpu_part=", "gpu-facts-2": "host-after.txt, summary.txt with cpu_part=",
           "gpu-install": "host-after.txt, set.txt", "llama-build": "host-after.txt, BUILD-INFO or stopped",
           "vlm": "host-after.txt, demo-exit.txt"}


def _setup_only(tmp_path):
    """rec/ as setup leaves it: its own empty ladder/, tooling/ and host-facts.txt."""
    rec = tmp_path / "rec"
    (rec / "ladder").mkdir(parents=True)
    aws._write(rec / "tooling" / "inputs.env", "IFS_NAME=ifs-vss.bin")
    aws._write(rec / "host-facts.txt", "== uname -r\n0.0.0-0-stub")
    return rec


def _stem(rec, stem, files=None):
    (rec / stem).mkdir(parents=True, exist_ok=True)
    for name, text in (EVIDENCE[stem] if files is None else files).items():
        aws._write(rec / stem / name, text)


def _lines(r):
    return r.stdout.splitlines()


@needs_bash
@pytest.mark.parametrize("stem", sorted(EVIDENCE))
def test_each_g5g_stem_alone_with_its_evidence_is_captured_and_named(tmp_path, stem):
    rec, pub = _setup_only(tmp_path), tmp_path / "pub"
    _stem(rec, stem)
    r = aws._capture(rec, pub)
    assert r.returncode == 0, r.stdout + r.stderr
    out = _lines(r)
    assert out[0] == "capture: a g5g record (%s)" % stem, out
    assert out[1].startswith("%s: evidence" % stem), out
    assert out[-1].startswith("capture: ") and " JSON verbatim, " in out[-1], out
    assert (pub / stem / "host-after.txt").exists() and (pub / "host-facts.txt").exists()
    log = (pub / "capture.log").read_text().splitlines()
    assert log == out, "the report is published as capture.log, the summary line its last"


@needs_bash
@pytest.mark.parametrize("stem,drop", [(s, n) for s in sorted(EVIDENCE) for n in sorted(EVIDENCE[s])] + [
    ("gpu-facts", "cpu"), ("llama-build", "empty")])
def test_each_g5g_stem_alone_without_its_evidence_is_refused(tmp_path, stem, drop):
    rec, pub = _setup_only(tmp_path), tmp_path / "pub"
    files = {n: t for n, t in EVIDENCE[stem].items() if n != drop}
    if drop == "cpu":
        files["summary.txt"] = "gpu-facts: kvm=yes"
    if drop == "empty":
        files = {}
    _stem(rec, stem, files)
    r = aws._capture(rec, pub)
    out = r.stdout + r.stderr
    assert r.returncode != 0, out
    assert "%s: no evidence (" % stem in r.stdout and "nothing ran" in out, out
    assert not (tmp_path / "pub.sha256").exists()


@needs_bash
def test_an_empty_rec_and_a_setup_only_rec_are_still_refused_with_todays_words(tmp_path):
    (tmp_path / "e" / "rec").mkdir(parents=True)
    for rec in (tmp_path / "e" / "rec", _setup_only(tmp_path)):
        r = aws._capture(rec, tmp_path / "pub")
        assert r.returncode != 0 and r.stdout == "", r.stdout
        assert "holds no stamp.json with lat-*.json, ex-*.json or an exchange set in scenarios.log: nothing ran" in r.stderr


@needs_bash
def test_todays_a6_record_is_captured_as_today_with_no_capture_log(tmp_path):
    rec, pub = aws._rec(tmp_path), tmp_path / "pub"
    r = aws._capture(rec, pub)
    assert r.returncode == 0, r.stderr
    assert r.stdout == SUMMARY % (3, 0, 1) + "\n", r.stdout
    assert not (pub / "capture.log").exists()


@needs_bash
def test_an_a6_record_with_g5g_stems_puts_the_g5g_lines_first_and_the_summary_last(tmp_path):
    rec, pub = aws._rec(tmp_path), tmp_path / "pub"
    _stem(rec, "gpu-facts")
    _stem(rec, "vlm", {"console.log": "guest up", "launch-svc.log": "x", "launch-svc-host-after.txt": AFTER})
    r = aws._capture(rec, pub)
    assert r.returncode == 0, r.stdout + r.stderr
    out = _lines(r)
    assert out[0] == "capture: today's A6 evidence, with g5g stems (gpu-facts vlm)", out
    assert out[1].startswith("gpu-facts: evidence") and out[2] == "vlm: no evidence (host-after.txt, demo-exit.txt)", out
    assert out[-1] == SUMMARY % (3, 0, 6) and sum(1 for ln in out if " JSON verbatim, " in ln) == 1, out
    assert (pub / "capture.log").read_text().splitlines() == out
    assert (pub / "vlm" / "console.log").exists(), "a stem without evidence is packed as it stands"
    raw = rec / "ladder" / "raw"
    assert (pub / "ladder" / "raw" / "lat-D-db_r1.json").read_bytes() == (raw / "lat-D-db_r1.json").read_bytes()


@needs_bash
def test_a_vlm_stem_says_which_of_its_packed_files_are_absent(tmp_path):
    rec, pub = _setup_only(tmp_path), tmp_path / "pub"
    _stem(rec, "vlm")
    r = aws._capture(rec, pub)
    assert r.returncode == 0 and _lines(r)[1] == "vlm: evidence (stamp.json absent, claims.log absent)", r.stdout
    shutil.rmtree(str(pub))
    os.remove(str(pub) + ".sha256")
    aws._write(rec / "vlm" / "stamp.json", json.dumps({"experiment": "vlm-demo"}), newline=False)
    aws._write(rec / "vlm" / "claims.log", "=== honest-digit-0")
    r = aws._capture(rec, pub)
    assert r.returncode == 0 and _lines(r)[1] == "vlm: evidence", r.stdout


TRACEBACK = 'Traceback (most recent call last):\n  File "vlm_request.py", line 1\nConnectionRefusedError: stub\n'


@needs_bash
def test_a_warmup_json_that_is_a_traceback_is_left_out_and_named_and_the_record_is_captured(tmp_path):
    rec, pub = _setup_only(tmp_path), tmp_path / "pub"
    _stem(rec, "gpu-facts")
    _stem(rec, "vlm", dict(EVIDENCE["vlm"], **{"warmup.json": TRACEBACK, "torn.jsonl": '{"a": 1}\nnot json\n{"b": 2}'}))
    r = aws._capture(rec, pub)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "excluded: vlm/warmup.json (does not parse, in a g5g stem: " in r.stdout, r.stdout
    assert "excluded: vlm/torn.jsonl (a line that does not parse, in a g5g stem: " in r.stdout, r.stdout
    assert not (pub / "vlm" / "warmup.json").exists() and not (pub / "vlm" / "torn.jsonl").exists()
    assert (pub / "gpu-facts" / "summary.txt").exists() and (pub / "vlm" / "demo-exit.txt").exists()
    assert "excluded: vlm/warmup.json" in (pub / "capture.log").read_text()


@needs_bash
def test_a_g5g_json_string_holding_a_newline_is_redacted_line_by_line_and_named(tmp_path):
    rec, pub = _setup_only(tmp_path), tmp_path / "pub"
    _stem(rec, "gpu-facts")
    aws._write(rec / "gpu-facts" / "extra.json", json.dumps({"two": "from 203.0.113.7\nsecond line", "n": 123456789012}),
               newline=False)
    r = aws._capture(rec, pub)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "gpu-facts/extra.json: 1 string(s) holding a newline redacted line by line" in r.stdout, r.stdout
    got = json.loads((pub / "gpu-facts" / "extra.json").read_text())
    assert got == {"two": "from <ip>\nsecond line", "n": 123456789012}


@needs_bash
@pytest.mark.parametrize("name,text,msg", [("warmup.json", TRACEBACK, ""),
                                           ("extra.json", json.dumps({"two": "a\nb"}), "a string holds a newline")])
def test_the_same_two_files_in_the_liveness_stem_refuse_the_capture_as_today(tmp_path, name, text, msg):
    rec, pub = aws._rec(tmp_path), tmp_path / "pub"
    _stem(rec, "gpu-facts")
    aws._write(rec / "liveness" / name, text, newline=False)
    r = aws._capture(rec, pub)
    assert r.returncode != 0 and msg in r.stderr, r.stdout + r.stderr


@needs_bash
@pytest.mark.parametrize("beside", ["setup only", "today's A6 evidence"])
def test_an_arm_named_json_that_does_not_parse_in_a_g5g_stem_is_left_out_by_a_word(tmp_path, beside):
    """No g5g phase writes a file of an arm's name; one that is there and does not parse is left out and named like any
    other JSON of a g5g stem, and the byte-for-byte check of the arm files does not look for its copy."""
    rec = _setup_only(tmp_path) if beside == "setup only" else aws._rec(tmp_path)
    pub = tmp_path / "pub"
    _stem(rec, "gpu-facts")
    for name in ("lat-x.json", "kvm-x.json", "db-burst.json", "ex-1.json"):
        aws._write(rec / "gpu-facts" / name, "not json")
    r = aws._capture(rec, pub)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Traceback" not in r.stderr and r.stdout.count("(does not parse, in a g5g stem: ") == 4, r.stdout + r.stderr
    assert "excluded: gpu-facts/lat-x.json (does not parse, in a g5g stem: " in r.stdout
    assert not (pub / "gpu-facts" / "lat-x.json").exists() and (pub / "gpu-facts" / "summary.txt").exists()


@needs_bash
def test_an_arm_file_outside_the_g5g_stems_is_still_held_byte_for_byte_beside_them(tmp_path):
    rec, pub = aws._rec(tmp_path), tmp_path / "pub"
    _stem(rec, "gpu-facts")
    r = aws._capture(rec, pub)
    assert r.returncode == 0, r.stdout + r.stderr
    for name in ("lat-D-db_r1.json", "kvm-D-db_r1.json"):
        assert (pub / "ladder" / "raw" / name).read_bytes() == (rec / "ladder" / "raw" / name).read_bytes()


def _probe_files(rec, where, names):
    for name in names:
        aws._write(rec / where / name, json.dumps({"experiment": "stand-in"}), newline=False)


@needs_bash
def test_a_g5g_stems_stamp_is_no_part_of_todays_a6_evidence(tmp_path):
    """vlm-demo.sh writes a stamp.json into the vlm stem. Beside probe output that has no stamp of its own (a liveness
    phase that died before it wrote one) it does not make today's A6 evidence: the first line says a g5g record."""
    rec, pub = _setup_only(tmp_path), tmp_path / "pub"
    _stem(rec, "gpu-facts")
    _stem(rec, "vlm")
    _probe_files(rec, "vlm", ["stamp.json"])
    _probe_files(rec, "liveness/demo", ["ex-1.json"])
    r = aws._capture(rec, pub)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _lines(r)[0] == "capture: a g5g record (gpu-facts vlm)", r.stdout
    assert (pub / "liveness" / "demo" / "ex-1.json").read_bytes() == (rec / "liveness" / "demo" / "ex-1.json").read_bytes()


@needs_bash
@pytest.mark.parametrize("case", ["a g5g stamp, probe output outside", "a stamp outside, probe output in a g5g stem",
                                  "a stamp outside, an exchange set in a g5g stem"])
def test_a_g5g_stems_files_cannot_make_todays_a6_evidence_for_a_record_that_has_none(tmp_path, case):
    """Without the g5g stem each of these records is refused today (nothing ran); a g5g stem that holds no evidence of
    its own does not change that."""
    rec, pub = _setup_only(tmp_path), tmp_path / "pub"
    _stem(rec, "vlm", {"console.log": "guest up"})
    if case == "a g5g stamp, probe output outside":
        _probe_files(rec, "vlm", ["stamp.json"])
        _probe_files(rec, "liveness/demo", ["ex-1.json"])
    elif case == "a stamp outside, probe output in a g5g stem":
        _probe_files(rec, "stamp", ["stamp.json"])
        _probe_files(rec, "vlm", ["lat-1.json"])
    else:
        _probe_files(rec, "stamp", ["stamp.json"])
        aws._write(rec / "vlm" / "scenarios.log", "A-tcp rc=0 t0=1 t1=2")
    r = aws._capture(rec, pub)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "no g5g stem with its evidence: nothing ran" in out, out
    assert "vlm: no evidence (host-after.txt, demo-exit.txt)" in r.stdout and "today's A6 evidence" not in out, out


U1 = "1b2c3d4e-5f6a-7b8c-9d0e-1f2a3b4c5d6e"      # made up


@needs_bash
def test_a_uuid_in_a_g5g_stems_log_is_masked_and_the_scan_after_the_fetch_passes(tmp_path):
    rec, pub = _setup_only(tmp_path), tmp_path / "pub"
    _stem(rec, "gpu-install")
    aws._write(rec / "gpu-install" / "apt.log", "update-initramfs: Generating a stub image\nI: (UUID=%s)" % U1)
    aws._write(rec / "gpu-install" / "extra.json", json.dumps({"device": "by uuid %s" % U1}), newline=False)
    r = aws._capture(rec, pub)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (pub / "gpu-install" / "apt.log").read_text().splitlines()[1] == "I: (UUID=<uuid>)"
    assert json.loads((pub / "gpu-install" / "extra.json").read_text()) == {"device": "by uuid <uuid>"}
    lk = subprocess.run([aws.PY, aws.LEAKSCAN, str(pub)], capture_output=True, text=True)
    assert lk.returncode == 0, lk.stdout + lk.stderr


@needs_bash
def test_the_published_report_went_through_the_redactor(tmp_path):
    rec, pub = _setup_only(tmp_path), tmp_path / "pub"
    _stem(rec, "gpu-facts")
    aws._write(rec / "gpu-facts" / "ip-10-0-0-5.json", "not json")
    r = aws._capture(rec, pub)
    assert r.returncode == 0, r.stdout + r.stderr
    log = (pub / "capture.log").read_text()
    assert "excluded: gpu-facts/<host> (does not parse" in log and "ip-10-0-0-5" not in log, log


# ------------------------------------------------------------------ the capture phase's printed output

def _session(tmp_path, rec_from):
    """W as a session leaves it before `run capture`: rec/, capture.py beside it, the redactor in the unpacked repo."""
    w = tmp_path / "w"
    r = w / "repo" / "orin-native" / "gpu-concurrency"
    r.mkdir(parents=True)
    shutil.copy(aws.REDACT, str(r / "redact-aws.sh"))
    shutil.copy(aws.CAPTURE, str(w / "capture.py"))
    shutil.copytree(str(rec_from), str(w / "rec"))
    return w


def _phase(w):
    return subprocess.run([BASH, aws.REMOTE, "capture"], capture_output=True, text=True, timeout=180,
                          env=dict(os.environ, W=aws._posix(w), USER="", PATH=aws._path_with()))


@needs_bash
def test_the_capture_phase_prints_the_g5g_lines_of_a_g5g_record(tmp_path):
    rec = _setup_only(tmp_path)
    _stem(rec, "gpu-facts")
    _stem(rec, "vlm", dict(EVIDENCE["vlm"], **{"warmup.json": TRACEBACK}))
    aws._write(rec / "ladder" / "junk.json", json.dumps({"ok": 1}), newline=False)
    r = _phase(_session(tmp_path, rec))
    assert r.returncode == 0, r.stdout + r.stderr
    out = _lines(r)
    assert out[0] == "capture: a g5g record (gpu-facts vlm)", out
    assert out[1].startswith("gpu-facts: evidence") and out[2].startswith("vlm: evidence"), out
    assert out[3].startswith("excluded: vlm/warmup.json (does not parse, in a g5g stem: "), out
    assert sum(1 for ln in out if " JSON verbatim, " in ln) == 1, "the summary line once"
    assert "captured " in out[-1] and " files into pub.tgz" in out[-1], out


@needs_bash
def test_the_capture_phase_prints_every_excluded_line_of_a_g5g_stem_which_the_tail_alone_would_not(tmp_path):
    """With two files of g5g stems left out, the phase prints both excluded: lines right after the stems' lines. The
    unchanged tail -2 shows only the last of them (and the summary), so one excluded line could not be held by what the
    tail prints."""
    rec = _setup_only(tmp_path)
    _stem(rec, "gpu-facts", dict(EVIDENCE["gpu-facts"], **{"gpus.json": TRACEBACK}))
    _stem(rec, "vlm", dict(EVIDENCE["vlm"], **{"warmup.json": TRACEBACK}))
    w = _session(tmp_path, rec)
    r = _phase(w)
    assert r.returncode == 0, r.stdout + r.stderr
    out = _lines(r)
    excluded = [ln for ln in (w / "capture.log").read_text().splitlines() if ln.startswith("excluded: ")]
    assert sorted(ln.split(" (")[0] for ln in excluded) == ["excluded: gpu-facts/gpus.json",
                                                            "excluded: vlm/warmup.json"], excluded
    assert out[0] == "capture: a g5g record (gpu-facts vlm)", out
    assert out[1].startswith("gpu-facts: evidence") and out[2].startswith("vlm: evidence") and out[3:5] == excluded, out
    assert out[5] == excluded[-1] and " JSON verbatim, " in out[6], "then the tail's two lines, as before"


@needs_bash
def test_the_capture_phase_prints_the_g5g_lines_first_and_the_summary_once_for_a_record_with_both(tmp_path):
    rec = aws._rec(tmp_path)
    aws._write(rec / "ladder" / "host-after.txt", "done")
    _stem(rec, "gpu-facts")
    r = _phase(_session(tmp_path, rec))
    assert r.returncode == 0, r.stdout + r.stderr
    out = _lines(r)
    assert out[0] == "capture: today's A6 evidence, with g5g stems (gpu-facts)" and out[1].startswith("gpu-facts: evidence")
    assert sum(1 for ln in out if " JSON verbatim, " in ln) == 1, out


@needs_bash
def test_the_capture_phase_prints_todays_lines_and_no_more_for_a_record_without_a_g5g_stem(tmp_path):
    rec = aws._rec(tmp_path)
    aws._write(rec / "ladder" / "host-after.txt", "done")
    # a text file whose line reads like a g5g line must not be taken for capture.py's report
    aws._write(rec / "ladder" / "note.txt", "gpu-facts: evidence")
    w = _session(tmp_path, rec)
    r = _phase(w)
    assert r.returncode == 0, r.stdout + r.stderr
    out = _lines(r)
    assert len(out) == 2 and out[0] == SUMMARY % (3, 0, 3) and "captured " in out[1], out
    assert (w / "capture.log").read_text().splitlines()[0] == out[0]


@needs_bash
def test_the_capture_phase_prints_no_g5g_line_for_a_vss_record_whose_report_names_a_g5g_path(tmp_path):
    """A vss record's report can hold a line of a g5g line's form (a stray directory called vlm is left out by the
    whitelist and named): the phase prints the g5g lines only for capture.py's two g5g first lines."""
    rec = aws._vss_record(tmp_path)
    aws._write(rec / "vlm" / "x.txt", "a stray directory of that name")
    w = _session(tmp_path, rec)
    r = _phase(w)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "excluded: vlm/x.txt (not on the vss whitelist)" in (w / "capture.log").read_text()
    out = _lines(r)
    assert not [ln for ln in out if ln.startswith(("excluded: ", "capture: a g5g", "capture: today's A6"))], out
    assert not (w / "pub" / "vlm").exists()


@needs_bash
def test_the_capture_phase_prints_a_vss_records_output_as_today(tmp_path):
    """The printed output of a vss record is held to today's form: the stems' status lines of the log, in order, the
    log's last two lines, and the one closing line of the phase."""
    rec = aws._vss_record(tmp_path)
    w = _session(tmp_path, rec)
    r = _phase(w)
    assert r.returncode == 0, r.stdout + r.stderr
    log = (w / "capture.log").read_text().splitlines()
    status = re.compile(
        r"^(vss-[A-Za-z0-9._-]+|ota-drill|aw-setup|aw-suite|aw-g1): (DONE|TIMEOUT|FAILED|INCOMPLETE|NO STATUS)")
    want = [ln for ln in log if status.match(ln)] + log[-2:]
    out = _lines(r)
    assert out[:-1] == want, (out, want)
    assert "captured " in out[-1] and " files into pub.tgz" in out[-1], out
