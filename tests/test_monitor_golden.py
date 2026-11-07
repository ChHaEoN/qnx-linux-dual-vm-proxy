"""kind4-spec C1 and C2: both monitor builds against the golden (sdv Phase 2, WP0 and WP5).

tests/fixtures/monitor-golden-4ee3e532.json holds what the monitor built from
main at 4ee3e532 replied and printed for the corpus of tests/monitor_corpus.py
over UDP, plain TCP, the stamp mode, the service mode and the polling shm slot.
tests/capture_monitor_golden.py wrote it, captured from blobs before any
monitor.c edit (re-captured once in review, 2026-10-01), the blobs exported with
`git show` (never from a checkout, by design) and their ids pinned in
monitor_corpus.SOURCE_IDS. Here the CURRENT ipc-test/qnx-safety-monitor/monitor.c
is built with the same gcc line and the same corpus is replayed: every reply and
every console line must be the golden's, byte for byte, after the normalisation
monitor_corpus.py names (the port, the shm file's path, the stamps).

C2 (WP5): the vss build (MONITOR_EXT_KINDS=0x10, as tests/test_monitor_vss.py's
native_vss fixture compiles it) replays the same corpus, which holds no kind 4,
and must give the golden's replies and the golden's console once its
announcement is dropped: exactly one `monitor: vss rules:` line, then one
`monitor: vss profile N:` line per compiled id in the compiled order, right
after the `claim kinds:` line, and no other line of the vss build's own
(`monitor: vss ...`) anywhere. The drop is exact on purpose: a looser one (every
line that starts `monitor: vss `) would also hide a summary line or a repeated
announcement. The announcement's formats are C4's
(tests/test_monitor_kind4_console.py).

What this does NOT show: the guest build (a different compiler and C library),
kind 4 behaviour (C7 and the rest of 16.1 are tests/test_monitor_kind4*.py's),
or the shm-kick mode, which the corpus leaves out. Object files are not
compared, only behaviour.

Needs gcc on Linux, as tests/test_measure_lib.py's native_servers does: WSL or
CI's tooling job. The shm leg also needs x86-64 (monitor_corpus.py says why).
C2 also needs the generated contract in sdv-out/gen and skips without it.
"""
import importlib.util
import json
import os
import re
import shutil
import subprocess

import pytest

import monitor_corpus as mc
import test_monitor_vss as tmv

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
FIXTURE = os.path.join(HERE, "fixtures", "monitor-golden-4ee3e532.json")

# C2: the lines the vss build adds to a console that holds no kind 4 frame (kind4-spec section 12).
CLAIM_KINDS = "monitor: claim kinds: "
VSS_RULES = "monitor: vss rules: "
VSS_PROFILE = "monitor: vss profile %d: "
VSS_OWN = "monitor: vss "


@pytest.fixture(scope="module")
def golden():
    with open(FIXTURE, encoding="ascii") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def current_monitor(tmp_path_factory):
    gcc = shutil.which("gcc")
    if gcc is None or not hasattr(os, "sched_getaffinity"):
        pytest.skip("needs gcc on Linux: runs in WSL and in CI's tooling job")
    out = tmp_path_factory.mktemp("golden") / "monitor"
    r = subprocess.run(mc.gcc_command(gcc, REPO, str(out)), capture_output=True, text=True)
    assert r.returncode == 0, "the default build must compile clean under -Werror:\n" + r.stderr
    return str(out)


@pytest.fixture(scope="module")
def vss_monitor(tmp_path_factory):
    """The vss build, with the native_vss fixture's line (test_monitor_vss.VSS_FLAGS), and its compiled ids."""
    gcc = tmv._gcc()
    if not all((tmv.GEN / h).is_file() for h in tmv.GEN_HEADERS):
        pytest.skip("needs the generated contract in sdv-out/gen (sdv/vss/generate.py)")
    out = tmp_path_factory.mktemp("golden-vss") / "monitor"
    r = subprocess.run([gcc, *tmv.VSS_FLAGS, "-I", str(tmv.COMMON), "-I", str(tmv.GEN), "-o", str(out), str(tmv.MONITOR_C),
                        str(tmv.SHM_MAP_POSIX_C), str(tmv.IVSHM_CLIENT_C)], capture_output=True, text=True)
    assert r.returncode == 0, "the vss build must compile clean under -Werror:\n" + r.stderr
    spec = importlib.util.spec_from_file_location("vss_contract_c2", str(tmv.GEN / "vss_contract.py"))
    assert spec is not None and spec.loader is not None
    contract = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(contract)
    return str(out), tuple(contract.COMPILED_PROFILE_IDS)


def drop_announcement(stdout, ids):
    """C2: a vss build's console lines less its announcement, which must be exactly one `vss rules:` line and one
    `vss profile N:` line per id of `ids`, in that order, right after the one `claim kinds:` line; no other line of
    the vss build's own may remain. Anything else is an AssertionError, never a silent pass."""
    at = [i for i, ln in enumerate(stdout) if ln.startswith(CLAIM_KINDS)]
    assert len(at) == 1, "one claim kinds line: %r" % (stdout,)
    want = [VSS_RULES] + [VSS_PROFILE % pid for pid in ids]
    first = at[0] + 1
    block = stdout[first:first + len(want)]
    assert len(block) == len(want) and all(ln.startswith(w) for ln, w in zip(block, want)), \
        "the announcement right after the claim kinds line: %r, want lines starting %r" % (block, want)
    rest = stdout[:first] + stdout[first + len(want):]
    assert not [ln for ln in rest if ln.startswith(VSS_OWN)], "a vss line beyond the announcement: %r" % (rest,)
    return rest


def test_the_header_names_the_reference_and_the_build(golden):
    ref = golden["reference"]
    assert ref["commit"] == mc.REFERENCE_COMMIT == "4ee3e532"
    assert list(ref["sources"]) == list(mc.SOURCES), "every source the native build reads, in order"
    for rel, blob in ref["sources"].items():
        assert re.fullmatch(r"[0-9a-f]{40}", blob), (rel, blob)
    # FOUND BY REVIEW: a 40-hex check alone would take a re-capture from the wrong blobs
    # with a matching ls-tree listing. Each id must be 4ee3e532's, as pinned in monitor_corpus.
    assert ref["sources"] == mc.SOURCE_IDS, "the golden must name 4ee3e532's blobs, and no others"
    assert golden["build"]["gcc_line"] == mc.GCC_LINE, "the golden was captured with this line; the replay uses it"
    assert golden["build"]["gcc_version"].startswith("gcc "), golden["build"]["gcc_version"]
    assert golden["capture"]["svc_deadline_ms"] == mc.SVC_DEADLINE_MS == 60000
    assert golden["capture"]["shm_file_bytes"] == mc.SHM_FILE_BYTES
    assert sorted(golden["runs"]) == sorted(mc.TRANSPORTS)


def test_the_capture_refuses_a_blob_that_is_not_pinned_even_when_the_listing_agrees(tmp_path, capsys):
    # The reference monitor.c is not in this tree after WP1 (and a line is appended so it never can be);
    # the listing is computed from the files themselves, so only the pinned ids can refuse it.
    import capture_monitor_golden as cap
    listing = {}
    for rel in mc.SOURCES:
        with open(os.path.join(REPO, *rel.split("/")), "rb") as fh:
            data = fh.read()
        if rel == mc.SOURCES[0]:
            data += b"/* not the reference */\n"
        dst = tmp_path.joinpath(*rel.split("/"))
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        listing[rel] = mc.git_blob_id(data)
    with pytest.raises(SystemExit) as e:
        cap.source_ids(str(tmp_path), listing)
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert mc.SOURCES[0] in err and mc.SOURCE_IDS[mc.SOURCES[0]] in err and "whatever the listing says" in err, err


def test_the_corpus_is_the_one_the_golden_was_captured_with(golden):
    assert golden["requests"] == mc.requests_record(), \
        "tests/monitor_corpus.py no longer builds the captured requests: the golden cannot judge it"
    kinds = {bytes.fromhex(h)[mc.HDR + mc.P_KIND] for _, h in golden["requests"]["udp"] if len(h) == 2 * mc.FRAME}
    assert 4 not in kinds, "kind 4 stays out of this corpus (C2 runs it through the vss build)"
    assert {2, 7, 9, 255} <= kinds


def test_the_golden_replies_are_what_the_rules_say(golden):
    # The fixture is judged on its own too, so a golden captured from a broken
    # build could not pass for a reference.
    for t in mc.TRANSPORTS:
        assert mc.check_replies(t, golden["runs"][t]) == [], t


def test_every_claim_in_the_corpus_has_poisoned_verdict_bytes(golden):
    # FOUND BY REVIEW: with 00 00 preset, a build that writes the
    # verdict and reason on REJECT only replayed the corpus clean.
    for transport in ("stream", "udp"):
        for label, h in golden["requests"][transport]:
            f = bytes.fromhex(h)
            assert f[mc.HDR + mc.P_VERDICT:mc.HDR + mc.P_REASON + 1] == bytes((mc.POISON, mc.POISON)), label
            if f[:8] != b"\xff" * 8 and len(f) == mc.FRAME:
                assert f[mc.HDR + mc.P_T_IN:mc.HDR + mc.P_T_OUT + 8] == bytes(16), \
                    label + ": the stamp bytes stay zero, or the stamp mask could hide a build that does not stamp"


def test_redaction_takes_either_case_and_names_inside_paths(monkeypatch):
    # FOUND BY REVIEW: the hostname was matched in one case only,
    # and the login name only after /home/.
    monkeypatch.setattr(mc.socket, "gethostname", lambda: "Box-One")
    monkeypatch.setattr(mc.getpass, "getuser", lambda: "someone")
    got = mc.redact("/tmp/pytest-of-someone/x SOMEONE BOX-ONE box-one.local /home/other/y box-ones someones")
    assert got == "/tmp/pytest-of-<user>/x <user> <host> <host>.local /home/<user>/y box-ones someones"
    monkeypatch.setattr(mc.getpass, "getuser", lambda: "root")
    assert mc.redact("<root>/ipc-test") == "<root>/ipc-test", "a generic account name is not identifying"


def test_the_fixture_is_redacted():
    # The capture host's names were checked at capture (capture_monitor_golden.py
    # refuses a fixture that redaction would still change); this checks the names
    # of the host that runs it, in either case and inside paths too.
    with open(FIXTURE, encoding="ascii") as fh:
        text = fh.read()
    assert set(re.findall(r"/home/[^/\s\"']+", text)) <= {"/home/<user>"}
    for name, tag in mc.identifying_names():
        assert mc.name_pattern(name).search(text) is None, "the fixture names this machine's " + tag
    assert mc.redact(text) == text
    assert "/tmp/" not in text and "/mnt/" not in text, "no capture-time path survives normalisation"
    # What makes replay's own redaction fail loudly, never silently, on a host or login named like a
    # console word (monitor_corpus.py's docstring): no redaction token in what the monitor sent.
    runs = json.dumps(json.loads(text)["runs"])
    assert "<host>" not in runs and "<user>" not in runs


@pytest.mark.parametrize("transport", mc.TRANSPORTS)
def test_the_default_build_replays_the_golden(current_monitor, golden, transport, tmp_path):
    if transport == "shm" and not mc.shm_client_ok():
        pytest.skip("the shm leg's client relies on x86-64 store order")
    got = mc.run(current_monitor, transport, str(tmp_path))
    want = golden["runs"][transport]
    assert got["argv"] == want["argv"]
    assert got["replies"] == want["replies"], mc.diff(want["replies"], got["replies"], transport + " replies")
    assert got["stdout"] == want["stdout"], mc.diff(want["stdout"], got["stdout"], transport + " stdout")
    assert got["stderr"] == want["stderr"], mc.diff(want["stderr"], got["stderr"], transport + " stderr")
    assert got["returncode"] == want["returncode"]


# ============================================================ C2: the vss build (WP5)

@pytest.mark.parametrize("transport", mc.TRANSPORTS)
def test_c2_the_vss_build_replays_the_golden_less_its_announcement(vss_monitor, golden, transport, tmp_path):
    binary, ids = vss_monitor
    if transport == "shm" and not mc.shm_client_ok():
        pytest.skip("the shm leg's client relies on x86-64 store order")
    got = mc.run(binary, transport, str(tmp_path))
    want = golden["runs"][transport]
    assert got["argv"] == want["argv"]
    assert got["replies"] == want["replies"], mc.diff(want["replies"], got["replies"], transport + " replies")
    stdout = drop_announcement(got["stdout"], ids)
    assert stdout == want["stdout"], mc.diff(want["stdout"], stdout, transport + " stdout, the announcement dropped")
    assert got["stderr"] == want["stderr"], mc.diff(want["stderr"], got["stderr"], transport + " stderr")
    assert got["returncode"] == want["returncode"]


def test_c2_the_drop_takes_exactly_the_announcement(golden):
    # The drop on its own, on the golden's UDP console with an announcement put where the vss build prints it:
    # the right one comes off clean; a missing, repeated, misplaced or reordered one, or any other vss line
    # left behind, fails -- so C2 can never pass by dropping more than the announcement.
    base = golden["runs"]["udp"]["stdout"]
    assert base[0].startswith(CLAIM_KINDS) and not [ln for ln in base if ln.startswith(VSS_OWN)]
    ids = (1, 2)
    rules = VSS_RULES + "kind 4, ...\n"
    prof = {pid: (VSS_PROFILE % pid) + "L ...\n" for pid in ids}
    summary = VSS_OWN + "summary: seen=2 rejected=2 suppressed=1 by reason: 23=1\n"

    def console(block, after=()):
        return base[:1] + list(block) + base[1:-1] + list(after) + base[-1:]

    assert drop_announcement(console([rules, prof[1], prof[2]]), ids) == base
    bad = {
        "no announcement": console([]),
        "no profile 2": console([rules, prof[1]]),
        "the rules line twice": console([rules, rules, prof[1], prof[2]]),
        "a profile line twice": console([rules, prof[1], prof[2], prof[2]]),
        "the profiles reordered": console([rules, prof[2], prof[1]]),
        "after the banner": base[:2] + [rules, prof[1], prof[2]] + base[2:],
        "a summary left behind": console([rules, prof[1], prof[2]], after=[summary]),
    }
    for what, lines in bad.items():
        with pytest.raises(AssertionError):
            drop_announcement(lines, ids)
            raise RuntimeError("the drop passed a console with %s" % what)
