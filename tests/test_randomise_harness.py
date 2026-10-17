"""run-randomise.sh, the A6 setup randomisation's harness (Phase 3b / A6, 2026-10-17), and the
hooks it uses in launch-qnx-kvm-bridged.sh.

What is held here, with nothing run on a board:
  - the registered header: the design's sections word for word where the tests can see them, the
    departures from them named and made, a WHAT IS KNOWN that names records by topic and states
    neither a figure nor what a record found, the committed seed and schedule hash, the same values
    in the code and the report, and the generator reproducing the hash;
  - the plan (DRY=1): every launch of a board boot built from its schedule line -- the fixed layout
    as env -i then setarch -R, the random one with its pad and no setarch, setarch after sudo and ip
    netns exec, the environment size the schedule states, the arms in the round's order;
  - the refusals that come before anything is changed, run against a faked host;
  - the record lines the harness writes, read back by randomise_report.py's own parser;
  - the signal traps (a signalled run ends through the EXIT trap, run for real in a process group), the
    logins journal that keeps a login's time and nothing else, the logins counter's window, and the
    order of the VM-boot and round loops past the preflight;
  - the launcher's new knobs, refused before anything starts when they do not fit together, and its pin
    path run against a stand-in QEMU in a PID namespace of its own.
"""
import json
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
HARNESS = os.path.join(GC, "run-randomise.sh")
LAUNCHER = os.path.join(GC, "launch-qnx-kvm-bridged.sh")
BASH = shutil.which("bash")
sys.path.insert(0, GC)
sys.path.insert(0, os.path.join(HERE, "..", "scripts", "ci"))
import randomise_report as rr  # noqa: E402
import randomise_schedule as rs  # noqa: E402
import results_guard  # noqa: E402

pytestmark = pytest.mark.skipif(BASH is None, reason="bash not available")
SEED = 979784927940495478
SHA = "0da177e5aaeadc77511bf1927de5fa0017133bc83863a9679875adf3712119b9"


def _posix(p):
    return os.path.abspath(str(p)).replace("\\", "/")


def _text(p):
    with open(p, "rb") as f:
        return f.read().decode("utf-8").replace("\r\n", "\n")


def _head_body():
    head, body = _text(HARNESS).split("\nset -u\n", 1)
    return head, body


def _prose(head):
    """The header's comment text as one line of words."""
    return re.sub(r"\s+", " ", "\n".join(re.sub(r"^# ?", "", ln) for ln in head.split("\n")[1:]))


def _stub(path, body):
    with open(str(path), "w", newline="\n") as f:
        f.write("#!/usr/bin/env bash\n" + body + "\n")
    os.chmod(str(path), 0o755)


@pytest.fixture(scope="module")
def schedule_file(tmp_path_factory):
    d = tmp_path_factory.mktemp("sched")
    p = d / "schedule.txt"
    with open(str(p), "w", newline="\n") as f:
        f.write(rs.generate(SEED))
    return p


# ------------------------------------------------------------------ the registered header

def test_the_harness_parses():
    r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr


# The header's section on what is known names records and notes by topic and states nothing any of them found (the
# owner's rule for a pre-registration; the header goes to the public tree). results_guard sees a figure only, so the
# section is held to a grammar as well: after its fixed first sentence, every sentence is "<topic>: <references>." --
# a short noun phrase, a colon, then record names, named notes, or "no record". A sentence that says what a record
# found needs a verb, a clause, a comparison or a figure, and the grammar has room for none of them.
KNOWN_INTRO = ("WHAT IS KNOWN, by topic, records and notes only: every one held locally, the records on "
               "`a6-results-unpublished`, and all known when the thresholds were set.")
KNOWN_RECORD = re.compile(r"\d{8}T-[a-z0-9]+(?:-[a-z0-9]+)*\Z")
KNOWN_NOTES = ("the findings entry of 2026-09-30", "the Gate 2 note of 2026-10-10", "the R39 inventory note")
KNOWN_NONE = "no record"
KNOWN_TOPIC_WORDS_MAX = 9
# A word that makes a topic a claim: a verb, a negation, a modal, a clause or a comparison.
KNOWN_CLAIM_WORDS = re.compile(
    r"\b(?:is|are|was|were|be|been|being|has|have|had|does|do|did|can|could|would|will|may|might|must|should|"
    r"not|no|never|none|only|always|which|that|because|so|until|when|while|if|but|though|since|than|more|less|"
    r"most|least|higher|lower|larger|smaller|faster|slower|wider|narrower|better|worse|sets?|finds?|found|"
    r"shows?|showed|shown|matters?|mattered|moves?|moved|widens?|widened|narrows?|keeps?|kept|cancels?|"
    r"cancell?ed|limits?|limited|makes?|made|needs?|needed|takes?|took|holds?|held|lives?|exists?|existed|"
    r"confound\w*|neutral|known|autocorrelated|correlated|depends?|causes?|caused|changes?|changed|affects?|"
    r"affected|reduces?|reduced|removes?|removed|raises?|raised|explains?|explained|dominates?|dominated|"
    r"drives?|drove|costs?|trims?|trimmed|halves|halved|doubles?|doubled|rises?|rose|falls?|fell|goes|went|"
    r"gives?|gave|beats?|equals?|differs?|differed|varies|varied|tests?|tested|establish\w*|proves?|proved|"
    r"confirms?|confirmed|refutes?|refuted|fails?|failed|passes|passed|works?|worked)\b", re.I)
# The design's records, every one named in WHAT IS KNOWN and nothing else beside the notes.
KNOWN_RECORDS = {
    "20260919T-native-cmp", "20260924T-a6-stats", "20260925T-a6-orin-boots", "20260925T-a6-orin-boots2",
    "20260922T-a6-orin-shift", "20260921T-a6-orin", "20260921T-a6-orin-pinned", "20260924T-a6-orin-rate",
    "20260924T-a6-orin-haltpoll", "20260924T-a6-orin-vcpupin", "20260924T-a6-orin-tail",
    "20260924T-a6-orin-blockpath", "20260924T-a6-orin-smp", "20260924T-a6-orin-power", "20260924T-a6-orin-arrival",
    "20260921T-a6-orin-c7off", "20260925T-a6-orin-confine", "20260925T-a6-orin-natural", "20260925T-a6-orin-tick",
    "20260925T-a6-orin-partition", "20260925T-a6-orin-guesttick", "20260929T-a6-orin-residual",
    "20260929T-a6-orin-irqconf", "20260929T-a6-orin-wifi", "20260925T-a6-a1metal-natural",
    "20260921T-ladder-a1metal", "20260923T-a6-a1metal-ladder"}


def _known_text(head):
    """The header's WHAT IS KNOWN as results_guard reads it, comment marks off, one line of words."""
    known = results_guard.known_sections(head)
    return known, re.sub(r"\s+", " ", " ".join(re.sub(r"^\s*# ?", "", ln) for _n, ln in known)).strip()


def _known_claims(text):
    """What in a WHAT IS KNOWN text is not "<topic>: <references>." after the fixed first sentence; [] when
    it all is."""
    if not text.startswith(KNOWN_INTRO + " "):
        return ["the section does not open with its fixed first sentence"]
    probs = []
    for s in re.split(r"(?<=\.) (?=[A-Z])", text[len(KNOWN_INTRO) + 1:]):
        m = re.fullmatch(r"([^:.;]+): (.+)\.", s)
        if not m:
            probs.append("not '<topic>: <references>.': %r" % s)
            continue
        topic, refs = m.group(1), m.group(2).split(", ")
        if len(topic.split()) > KNOWN_TOPIC_WORDS_MAX:
            probs.append("a topic of more than %d words: %r" % (KNOWN_TOPIC_WORDS_MAX, topic))
        w = KNOWN_CLAIM_WORDS.search(topic)
        if w:
            probs.append("%r in the topic %r makes it a claim" % (w.group(0), topic))
        if results_guard.figures(topic):
            probs.append("a figure in the topic %r" % topic)
        if refs != [KNOWN_NONE] and not all(KNOWN_RECORD.match(x) or x in KNOWN_NOTES for x in refs):
            probs.append("not record names, named notes or %r alone: %r" % (KNOWN_NONE, m.group(2)))
    return probs


def test_what_is_known_names_records_and_quotes_no_figure():
    """WHAT IS KNOWN names the design's records and notes by topic. It holds no figure (and needs no entry in
    the figure allowlist), and no sentence of it says what a record found: each is "<topic>: <references>."."""
    head = _head_body()[0]
    known, text = _known_text(head)
    lines = head.split("\n")
    assert known[0][1].startswith("# WHAT IS KNOWN, ") and lines[known[-1][0]] == "#" \
        and lines[known[-1][0] + 1] == "# 3. Hypotheses", "the guarded block is the whole of what replaced section 2"
    path = "orin-native/gpu-concurrency/run-randomise.sh"
    assert not [e for e in results_guard.load_allowlist(results_guard.ALLOWLIST) if e[0] == path]
    assert [fig for _n, line in known for fig in results_guard.figures(line)] == []
    assert _known_claims(text) == []
    refs = set(re.findall(r"\d{8}T-[a-z0-9]+(?:-[a-z0-9]+)*", text))
    assert refs == KNOWN_RECORDS, sorted(refs ^ KNOWN_RECORDS)
    for note in KNOWN_NOTES:
        assert note + "." in text, note
    assert "An A6 timing on R39: no record." in text and "Arm order in the ladder: no record." in text


@pytest.mark.parametrize("planted", [
    "The colour of the case sets the tone: 20990101T-example.",
    "The moon matters: 20990101T-example.",
    "Tea and coffee were confounded: 20990101T-example.",
    "The hum of the fan is neutral: 20990101T-example.",
    "The kettle widens the gap: 20990101T-example.",
    "Lunch, which moves the chairs: 20990101T-example.",
    "Lunch: 20990101T-example, which found nothing.",
    "Lunch: 20990101T-example. Lunch keeps the pace.",
    "Lunch: 20990101T-example (a 7 ms nap).",
    "Lunch: no record, 20990101T-example.",
    "A lunch of 7 ms: 20990101T-example.",
    "The long and quiet lunch of the afternoon on the hill: 20990101T-example.",
])
def test_what_is_known_fails_on_a_finding_as_well_as_on_a_figure(planted):
    """The grammar's own check: a sentence that says what a record found (made up here, and about lunch),
    put into the header's own WHAT IS KNOWN, is caught."""
    _known, text = _known_text(_head_body()[0])
    assert _known_claims(text) == []
    at = len(KNOWN_INTRO) + 1
    assert _known_claims(text[:at] + planted + " " + text[at:]) != [], planted
    assert _known_claims(text + " " + planted) != [], planted


def test_the_departures_from_the_design_are_named_in_the_intro_and_made():
    """Sections 1, 3 and 4 depart from the design's text only so that the header states no outcome of a
    record; the intro names each departure, and each is made."""
    prose = _prose(_head_body()[0])
    for words in ("Sections 5 to 7 (D11) and 12 are copied word for word.",
                  "Sections 1, 3 and 4 are copied word for word but for the departures below, each made so that "
                  "this header states no outcome of any record",
                  "Section 2 is replaced by WHAT IS KNOWN below, which names the design's records and notes by topic "
                  "and states nothing that any of them found.",
                  "Section 1: Q2's first sentence, which stated a record's outcome, is dropped.",
                  "Section 3: H2's first sentence names the share that P4's phi estimates",
                  "Section 4.2: the \"why\" cells of the board boot, spacing, role placement and guest image rows",
                  "Section 4.3: the fallback image's devices are named as gate2-smoke.sh's G4 step presents them",
                  "Section 4.6: the confinement's heading names it without saying what it removes; the halt-polling "
                  "bullet on a blocked halt says that a contrast can include its cost"):
        assert words in prose, words
    for made in ("**Q2, where the level lives.** Is the p50 level re-drawn at every VM boot, or only at every board "
                 "boot? The answer decides",
                 "**H2.** At least half of the level's variance between boots, the VM boots' and the board boots' "
                 "together, is re-drawn by a VM boot with the setup held fixed.",
                 "| P4 sets the board boot against the VM boot as a level of the hierarchy. Six boots sample it (D2). |",
                 "| By KVM's source, an idle gap shorter than `halt_poll_ns` can end in a poll, so spacing selects a "
                 "halt-polling regime and is not a nuisance. Randomising it would mix regimes. |",
                 "| This is the A6 confinement's layout, which the A6 harnesses use. On R39,",
                 "| An image's services could move the rungs, so one image, identified by hash, holds that factor fixed. |",
                 "- Otherwise use `ifs-kick.bin` with its devices presented exactly as `gate2-smoke.sh`'s G4 step "
                 "presents them. - Confirming",
                 "**The confinement.** - **Applied in every round of both regimes.**",
                 "- At 2 ms spacing a contrast can include the cost of a blocked halt."):
        assert made in prose, made
    one_to_four = prose[prose.index("1. The question"):prose.index("5. Predictions, with thresholds")]
    for word in ("known cause", "known to set", "mitigation", "section 2"):
        assert word not in one_to_four, word
    assert "section 2" not in prose, "section 2 is replaced, so nothing refers to it"
    gate2 = _text(os.path.join(HERE, "..", "scripts", "orin", "gate2-smoke.sh"))
    assert 'G4|G21) IMAGES="ifs-kick.bin"' in gate2, "the step the fallback names presents ifs-kick.bin"


@pytest.mark.parametrize("sentence", [
    "The margin is m = 3 µs",
    "k = 12: d(3)–d(10), 96.1%;",
    "k = 24: d(7)–d(18), 97.7%.",
    "k = 12: d(1)–d(12), the min–max band, 99.95%;",
    "k = 24: d(4)–d(21), 99.97%.",
    "HELD:** I95 lies wholly inside [−m, +m].",
    "REFUTED:** I999 lies wholly outside [−m, +m].",
    "The order effect is the median over the k = 24 VM boots of ½[(K_RF + K_RR) − (K_FF + K_FR)].",
    "The same, for the layout effect ½[(K_FR + K_RR) − (K_FF + K_RF)].",
    "The S effect is the median, over the k = 12 adjacent F–R pairs (VM boots 1–2 and 3–4 of every board boot), of V(R) − V(F).",
    "C1, control (scored, not a gate).** The S effect on `p50(A)` is within ±3 µs.",
    "HELD** if the bootstrap's 2.5% bound is at least 0.5. **REFUTED** if its 97.5% bound is below 0.5.",
    "A prediction is never guarded by a check that fails when the prediction is false.",
    "If more than 5% of arm-rounds are flagged, all predictions are VOID.",
    "σ²_vm = max(0, (MS_vm − MS_round) / 4);",
    "σ²_board = max(0, (MS_board − MS_vm) / 8);",
    "10 000 resamples from the schedule's seed; the 2.5% and 97.5% percentiles.",
    "If more than 10% are undefined, P4 is UNRESOLVED.",
    "A result printed without its interval and its k is not a result of this design.",
    "no figure here is comparable with any R36 record or is an R39 baseline",
    "They are not to be amended. A smoke run's data is never scored.",
    "It is not to be amended.",
])
def test_the_header_carries_the_designs_predictions_checks_and_analysis_word_for_word(sentence):
    assert sentence in _prose(_head_body()[0])


def test_every_check_row_and_its_guards_are_in_the_header():
    prose = _prose(_head_body()[0])
    for row, guards in (("M1", "all"), ("M2", "P2, P3"), ("M3", "P1, P2"), ("M4", "P3, P4"), ("M5", "all"),
                        ("M6", "all"), ("M7", "all"), ("M8", "all"), ("M9", "all")):
        m = re.search(r"\| %s \| (.*?) \| ([^|]*) \|" % row, prose)
        assert m and m.group(2).strip() == guards, row


def test_the_header_states_the_committed_seed_and_hash_and_the_code_and_report_hold_the_same():
    head, body = _head_body()
    assert "randomise_schedule.py --seed %d --out schedule.txt" % SEED in head
    assert "#     %s" % SHA in head
    assert "\nMASTER_SEED=%d\n" % SEED in body and "\nSCHEDULE_SHA256=%s\n" % SHA in body
    assert rr.MASTER_SEED == SEED and rr.SCHEDULE_SHA256 == SHA
    assert rs.sha256(rs.generate(SEED)) == SHA


def test_the_header_names_the_image_and_the_native_monitor_it_confirmed():
    prose = _prose(_head_body()[0])
    assert "THE IMAGE, confirmed from its build file as section 4.3 asks: ifs-stamp.bin." in prose
    assert "neither build file starts the echo server itself" in prose
    assert "~/gate2/bin/20261009T221811Z/monitor-native" in prose
    build = _text(os.path.join(HERE, "..", "ipc-test", "qnx-safety-monitor", "ifs-stamp.build"))
    assert "\n/proc/boot/qnx-safety-monitor &\n" in build, "the plain :7100 monitor in the image's own script"
    assert "qnx-echo-server-net=" in build and "qnx-echo-server-net &" not in build and "7000" not in build
    post = _text(os.path.join(HERE, "..", "scripts", "orin", "qnx-safety-vm-post_start.custom"))
    assert "/proc/boot/qnx-echo-server-net &" in post and ":7000" in post


@pytest.mark.parametrize("line", ["N=1000", "WARMUP=200", "INTERVAL_MS=2", "PORT=7100", "ARM_C_PORT=7000", "QEMU_CORES=0-2",
                                  "CORE_MON=3", "CORE_PROBE=4", "CORE_AUX=5", "CONF_CORES=3,5", "SETTLE_S=600",
                                  "READY_PAUSE_S=30", "PROBE_TIMEOUT_S=10"])
def test_the_design_values_are_constants_the_environment_cannot_change(line):
    body = _head_body()[1]
    name = line.split("=")[0]
    assert re.search(r"^%s(\s|$)" % re.escape(line), body, re.M), line
    assert not re.search(r"^%s=\"\$\{" % name, body, re.M), "%s is not taken from the environment" % name


def test_the_controls_the_design_fixes():
    """c7 off is set before the library loads, and no environment can turn it back on."""
    body = _head_body()[1]
    assert body.index("\nCSTATE=shallow ") < body.index('\n. "$LIB"\n')
    assert not re.search(r"\$\{CSTATE(?![A-Za-z0-9_])", body), "CSTATE is never read back from the environment"
    for line in ("KVM_STATS=1 ", "SAMPLE_WINDOW=0 ", "STALL_POLICY=refuse ", 'FIFO_ARMS=""', "CSTATE=shallow "):
        assert re.search(r"^" + re.escape(line), body, re.M), line


def test_cleanup_stops_the_guest_before_the_restore_and_restores_the_governor_last():
    body = _head_body()[1]
    fn = body[body.index("\ncleanup() {"):]
    fn = fn[:fn.index("\n}\n")]
    order = [fn.index(x) for x in ("mon_stop", "vm_stop", "ns_down", "conf_restore", "m_cstate_restore",
                                   '"$QUIESCE" restore', "m_governor_restore")]
    assert order == sorted(order)
    assert body.count("trap cleanup EXIT") == 1 and "trap - EXIT" not in body


def test_the_record_lines_the_report_parses_are_written_in_its_shape():
    body = _head_body()[1]
    assert 'echo "round $r cell=$(kv "$line" cell) order:$order" >> "$VM_DIR/order.log"' in body
    assert 'echo "round $r start=$t_start end=$t_end" >> "$VM_DIR/rounds.log"' in body
    assert 'echo "start $(halt_line)" > "$VM_DIR/halt.log"' in body and 'echo "end $(halt_line)" >> "$VM_DIR/halt.log"' in body
    assert 'echo "start $(gpu_pct)" > "$VM_DIR/gpu.log"' in body and 'echo "end $(gpu_pct)" >> "$VM_DIR/gpu.log"' in body
    assert 'echo "round $2 after-$3 $(emc_line)" >> "$VM_DIR/emc.log"' in body
    assert 'out.append("v%s r%s accepted=%s"' in body


# ------------------------------------------------------------------ the plan (DRY=1)

def _dry(schedule, tag, extra=None):
    env = dict(os.environ, DRY="1", BOOT_TAG=tag, SCHEDULE=_posix(schedule), OUT_BASE="/x/out", IMG="/x/img",
               MON="/x/bin/monitor-native", PYTHONDONTWRITEBYTECODE="1")
    env.update(extra or {})
    b = os.path.join(os.path.dirname(_posix(schedule)), "pybin")
    os.makedirs(b, exist_ok=True)
    _stub(os.path.join(b, "python3"), 'exec "%s" "$@"' % _posix(sys.executable))
    env["PATH"] = b + os.pathsep + env.get("PATH", "")
    return subprocess.run([BASH, HARNESS], capture_output=True, text=True, env=env, timeout=120)


def _arch():
    return subprocess.run([BASH, "-c", "uname -m"], capture_output=True, text=True).stdout.strip()


def _plan(out):
    lines = {}
    for ln in out.splitlines():
        m = re.match(r"plan: v(\d) r(\d) (mon-host|mon-ns|probe-[A-D]) env=(\d+): (.*)$", ln)
        if m:
            lines[(int(m.group(1)), int(m.group(2)), m.group(3))] = (int(m.group(4)), m.group(5))
    return lines


def _prefix_ok(cmd, la, probe):
    """The layout words of a command: env -i, the fixed list, [the hash seed], [the pad], [setarch -R]."""
    words = cmd.split()
    i = words.index("env")
    assert words[i + 1:i + 4] == ["-i", "PATH=/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL=C"], cmd
    j = i + 4
    if probe:
        assert words[j] == "PYTHONHASHSEED=%d" % la["hashseed"], cmd
        j += 1
    if la["norand"]:
        assert words[j:j + 3] == ["setarch", _arch(), "-R"], cmd
        assert "A6PAD" not in cmd
        return j + 3
    assert words[j] == "A6PAD=x{%d}" % la["pad"], cmd
    assert "setarch" not in cmd
    return j + 1


@pytest.mark.parametrize("tag", ["b0", "b1", "b2", "b3", "b4", "b5", "b6"])
def test_the_plan_builds_every_launch_from_its_schedule_line(schedule_file, tag):
    r = _dry(schedule_file, tag)
    assert r.returncode == 0, r.stdout + r.stderr
    plan = _plan(r.stdout)
    s = rs.parse(rs.generate(SEED))["boots"][tag]
    n = 0
    for v, vm in s["vms"].items():
        for k, rd in vm["rounds"].items():
            for who in ("host", "ns"):
                env, cmd = plan[(v, k, "mon-" + who)]
                la = rd["mon"][who]
                assert env == la["env"]
                at = _prefix_ok(cmd, la, False)
                assert cmd.split()[at:] == ["/x/bin/monitor-native", "7100"], cmd
                n += 1
            for a in "ABCD":
                env, cmd = plan[(v, k, "probe-" + a)]
                la = rd["probe"][a]
                assert env == la["env"]
                at = _prefix_ok(cmd, la, True)
                rest = cmd.split()[at:]
                host, port = {"A": ("127.0.0.1", "7100"), "B": ("192.168.100.20", "7100"),
                              "C": ("192.168.100.10", "7000"), "D": ("192.168.100.10", "7100")}[a]
                tag_ = "%s_%s%d" % (rr.ARM_NAME[a], "s" if k == 0 else "r", k)
                assert rest == ["python3", _posix(os.path.join(GC, "latency_probe.py")), "--host", host, "--port", port,
                                "--n", "1000", "--warmup", "200", "--interval-ms", "2", "--timeout-s", "10", "--proto", "tcp",
                                "--tag", tag_, "--out", "/x/out/%s/v%d/lat-%s.json" % (tag, v, tag_)], cmd
                n += 1
    assert n == len(plan)


@pytest.mark.parametrize("tag", ["b0", "b2"])
def test_the_monitors_and_probe_run_on_their_cores_and_setarch_comes_after_sudo_and_ip_netns(schedule_file, tag):
    plan = _plan(_dry(schedule_file, tag).stdout)
    for (_v, _k, who), (_env, cmd) in plan.items():
        w = cmd.split()
        if who == "mon-ns":
            assert w[:9] == ["sudo", "-n", "ip", "netns", "exec", "a6rand", "taskset", "-c", "3"], cmd
            if "setarch" in w:
                assert w.index("setarch") > w.index("exec") > w.index("sudo")
        elif who == "mon-host":
            assert w[:3] == ["taskset", "-c", "3"] and "sudo" not in w, cmd
        else:
            assert w[:3] == ["taskset", "-c", "4"] and "sudo" not in w, cmd


def test_the_probes_run_in_the_rounds_order(schedule_file):
    r = _dry(schedule_file, "b4")
    s = rs.parse(rs.generate(SEED))["boots"]["b4"]
    for v, vm in s["vms"].items():
        for k, rd in vm["rounds"].items():
            got = [m.group(1) for m in re.finditer(r"^plan: v%d r%d probe-([A-D]) " % (v, k), r.stdout, re.M)]
            assert got == rd["order"], (v, k)
            assert ("plan: v%d r%d %s order %s" % (v, k, rd["cell"], ",".join(rd["order"]))) in r.stdout


def test_each_vm_boot_is_launched_with_its_layout_and_its_thread_groups_by_name(schedule_file):
    r = _dry(schedule_file, "b1")
    s = rs.parse(rs.generate(SEED))["boots"]["b1"]
    for v, vm in s["vms"].items():
        line = [ln for ln in r.stdout.splitlines() if ln.startswith("plan: v%d launch: " % v)]
        assert len(line) == 1
        w = line[0].split()
        assert "IFS_BIN=/x/img/ifs-stamp.bin" in w and "DISK=/x/img/disk-qemu" in w
        assert "LOG=/x/out/b1/v%d/guest-console.log" % v in w
        assert "THREAD_NAMES=1" in w and "SMP=2" in w and "QEMU_PIN=%s" % ",".join(map(str, vm["pin"])) in w
        if vm["S"] == "F":
            assert "QEMU_LAYOUT=fixed" in w and not any(x.startswith("QEMU_PAD=") for x in w)
        else:
            assert "QEMU_LAYOUT=random" in w and "QEMU_PAD=%d" % vm["pad"] in w
        assert w[-1].endswith("launch-qnx-kvm-bridged.sh")


def test_the_plan_refuses_a_schedule_that_is_not_the_committed_one(tmp_path):
    p = tmp_path / "s.txt"
    p.write_text(rs.generate(SEED + 1))
    r = _dry(p, "b1")
    assert r.returncode != 0 and "M9" in r.stderr and "plan:" not in r.stdout


def test_the_plan_refuses_a_schedule_that_does_not_re_derive(tmp_path):
    p = tmp_path / "s.txt"
    p.write_text(rs.generate(SEED).replace("bootstrap_seed ", "bootstrap_seed 1", 1))
    r = _dry(p, "b1")
    assert r.returncode != 0 and "does not re-derive" in r.stderr


@pytest.mark.parametrize("tag", ["b7", "", "B1", "b1 "])
def test_a_board_boot_the_schedule_has_not_is_refused(schedule_file, tag):
    r = _dry(schedule_file, tag)
    assert r.returncode != 0 and "BOOT_TAG" in r.stderr


def test_positional_arguments_are_refused(schedule_file):
    env = dict(os.environ, DRY="1", BOOT_TAG="b1", SCHEDULE=_posix(schedule_file))
    r = subprocess.run([BASH, HARNESS, "K=4"], capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode != 0 and "positional arguments are not read" in r.stderr


# ------------------------------------------------------------------ refused before anything is changed

# The root commands a refusal that comes before any change to the board may have run: reads, and the one
# write the design orders first, `cp -a`, the archive copy of pstore (section 10), which lands under $HOME.
BEFORE_ANY_CHANGE = ("cat ", "ls -A ", "find ", "cp -a ")


BOOT_ID = "6b1d5c7e-0a4f-4c3b-9e2d-1f0a2b3c4d5e"


def _host(tmp_path, uptime="900.12 1.0", cmdline="console=ttyTCU0 root=/dev/nvme0n1p1", reset="SYS_RESET_N",
          pstore=(), var=(), mark=None, boot_dir=False, aslr="2", personality="00000000"):
    """A faked host for the run's first reads and refusals: every path the harness reads early points
    into tmp_path, and sudo is a logging stub that runs the command."""
    sysr, proc, var_d, state = tmp_path / "sys", tmp_path / "proc", tmp_path / "var-pstore", tmp_path / "state"
    for d in (sysr / "fs" / "pstore", proc / "sys" / "kernel" / "random", proc / "self", var_d, state, tmp_path / "bin"):
        d.mkdir(parents=True, exist_ok=True)
    (proc / "uptime").write_text(uptime + "\n")
    (proc / "cmdline").write_text(cmdline + "\n")
    (proc / "sys" / "kernel" / "randomize_va_space").write_text(aslr + "\n")
    (proc / "sys" / "kernel" / "random" / "boot_id").write_text(BOOT_ID + "\n")
    (proc / "self" / "personality").write_text(personality + "\n")
    rr_path = tmp_path / "reset_reason"
    if reset is not None:
        rr_path.write_text(reset + "\n")
    for n in pstore:
        (sysr / "fs" / "pstore" / n).write_text("record\n")
    for n in var:
        (var_d / n).parent.mkdir(parents=True, exist_ok=True)
        (var_d / n).write_text("record\n")
    if mark is not None:
        (state / "a6-randomise.pstore-seen").write_text("".join(x + "\n" for x in mark))
    if boot_dir:
        (tmp_path / "out" / "b2").mkdir(parents=True)
    log = tmp_path / "sudo.log"
    _stub(tmp_path / "bin" / "sudo", 'echo "$*" >> "%s"\n[ "$1" = -n ] || exit 97\nshift\nexec "$@"' % _posix(log))
    _stub(tmp_path / "bin" / "python3", 'exec "%s" "$@"' % _posix(sys.executable))
    return {"SYS_ROOT": _posix(sysr), "PROC_ROOT": _posix(proc), "PSTORE_VAR": _posix(var_d), "XDG_STATE_HOME": _posix(state),
            "RESET_REASON": _posix(rr_path), "PSTORE_ARCHIVE": _posix(tmp_path / "archive"), "OUT_BASE": _posix(tmp_path / "out"),
            "LOCK": _posix(tmp_path / "lock"), "PATH": _posix(tmp_path / "bin") + os.pathsep + os.environ.get("PATH", "")}


def _run(tmp_path, schedule, env, script=HARNESS, prefix=()):
    e = dict(os.environ, BOOT_TAG="b2", SCHEDULE=_posix(schedule), PYTHONDONTWRITEBYTECODE="1", TEGRA="0")
    e.update(env)
    r = subprocess.run(list(prefix) + [BASH, script], capture_output=True, text=True, env=e, timeout=120)
    log = tmp_path / "sudo.log"
    r.sudo = log.read_text().splitlines() if log.exists() else []
    return r


def _nothing_changed(tmp_path, r):
    assert r.returncode != 0, r.stdout + r.stderr
    assert all(c.split(" ", 1)[1].startswith(BEFORE_ANY_CHANGE) for c in r.sudo), r.sudo
    assert not (tmp_path / "lock").exists(), "refused before the run lock"
    assert not (tmp_path / "out" / "b2" / "boot.json").exists()


def test_reset_reason_is_read_first_and_an_unreadable_one_refuses(tmp_path, schedule_file):
    r = _run(tmp_path, schedule_file, _host(tmp_path, reset=None))
    _nothing_changed(tmp_path, r)
    assert "cannot read reset_reason" in r.stderr and "M8" in r.stderr
    assert r.sudo[0].startswith("-n cat ") and r.sudo[0].endswith("reset_reason"), r.sudo


def test_a_crash_record_in_pstore_is_archived_and_stops_the_run(tmp_path, schedule_file):
    r = _run(tmp_path, schedule_file, _host(tmp_path, pstore=("dmesg-ramoops-0", "console-ramoops-0")))
    _nothing_changed(tmp_path, r)
    assert "crash record (dmesg-ramoops-0)" in r.stderr and "the stop rule" in r.stderr
    archived = list((tmp_path / "archive").glob("b2-*/dmesg-ramoops-0"))
    assert len(archived) == 1, "archived outside the record before the refusal"


def test_a_console_record_is_archived_and_does_not_stop_the_run(tmp_path, schedule_file):
    r = _run(tmp_path, schedule_file, _host(tmp_path, pstore=("console-ramoops-0",), uptime="30.0 1.0"))
    _nothing_changed(tmp_path, r)
    assert "crash record" not in r.stderr and "let it settle" in r.stderr, r.stderr
    assert list((tmp_path / "archive").glob("b2-*/console-ramoops-0"))


def test_a_crash_record_new_in_systemds_archive_since_the_last_board_boot_stops_the_run(tmp_path, schedule_file):
    r = _run(tmp_path, schedule_file, _host(tmp_path, var=("2026/dmesg-ramoops-1",), mark=["2026/console-ramoops-0"]))
    _nothing_changed(tmp_path, r)
    assert "appeared in" in r.stderr and "2026/dmesg-ramoops-1" in r.stderr


def test_a_crash_record_already_seen_at_the_last_board_boots_end_does_not_stop_it(tmp_path, schedule_file):
    r = _run(tmp_path, schedule_file, _host(tmp_path, var=("2026/dmesg-ramoops-1",), mark=["2026/dmesg-ramoops-1"],
                                            uptime="10.0 1.0"))
    _nothing_changed(tmp_path, r)
    assert "appeared in" not in r.stderr and "let it settle" in r.stderr


def test_an_unsettled_boot_is_refused(tmp_path, schedule_file):
    r = _run(tmp_path, schedule_file, _host(tmp_path, uptime="599.99 1.0"))
    _nothing_changed(tmp_path, r)
    assert "599 s old, under 600 s" in r.stderr


@pytest.mark.parametrize("token", ["isolcpus=1-4", "irqaffinity=0,5"])
def test_a_boot_off_the_shipped_command_line_is_refused(tmp_path, schedule_file, token):
    r = _run(tmp_path, schedule_file, _host(tmp_path, cmdline="console=ttyTCU0 %s quiet" % token))
    _nothing_changed(tmp_path, r)
    assert "not on the shipped command line" in r.stderr


def _past_the_lock(tmp_path, ifs_name="ifs-stamp.bin", source_ok=True, nvp="NV Power Mode: 25W\n1"):
    """A host that passes the first reads and the board-boot checks, with the image, the disk and a
    native monitor in tmp_path, and an nvpmodel stub."""
    env = _host(tmp_path)
    img = tmp_path / "img"
    img.mkdir()
    (img / ifs_name).write_bytes(b"image")
    (img / "disk-qemu").write_bytes(b"disk")
    mon = tmp_path / "gate2" / "monitor-native"
    mon.parent.mkdir()
    _stub(mon, "exit 0")
    src = os.path.join(HERE, "..", "ipc-test")
    files = ["qnx-safety-monitor/monitor.c", "common/shm_map_posix.c", "common/ivshm_client.c", "common/frame.h",
             "common/frame_io.h", "common/shm_chan.h", "common/shm_map.h", "common/ivshm_client.h"]
    import hashlib
    h = hashlib.sha256(b"".join(open(os.path.join(src, f), "rb").read() for f in files)).hexdigest()
    (tmp_path / "gate2" / "monitor-native.source-sha256").write_text((h if source_ok else "0" * 64) + "\n")
    _stub(tmp_path / "bin" / "nvpmodel", "printf '%s\\n'" + "".join(" '%s'" % x for x in nvp.split("\n")))
    env.update(IFS_BIN=_posix(img / ifs_name), DISK=_posix(img / "disk-qemu"), MON=_posix(mon))
    return env


def _changed_nothing_past_the_lock(r):
    assert r.returncode != 0, r.stdout + r.stderr
    assert all(c.split(" ", 1)[1].startswith(BEFORE_ANY_CHANGE + ("nvpmodel -q",)) for c in r.sudo), r.sudo


def test_an_image_other_than_the_confirmed_one_is_refused(tmp_path, schedule_file):
    r = _run(tmp_path, schedule_file, _past_the_lock(tmp_path, ifs_name="ifs-kick.bin"))
    _changed_nothing_past_the_lock(r)
    assert "the image confirmed for this design is ifs-stamp.bin" in r.stderr, r.stderr


def test_a_native_monitor_built_from_other_sources_is_refused(tmp_path, schedule_file):
    r = _run(tmp_path, schedule_file, _past_the_lock(tmp_path, source_ok=False))
    _changed_nothing_past_the_lock(r)
    assert "was not built from the monitor's sources at this commit" in r.stderr, r.stderr


def test_a_board_in_another_power_mode_is_refused_and_never_switched(tmp_path, schedule_file):
    r = _run(tmp_path, schedule_file, _past_the_lock(tmp_path, nvp="NV Power Mode: 15W\n0"))
    _changed_nothing_past_the_lock(r)
    assert "nvpmodel reads mode '0', not 1" in r.stderr, r.stderr
    assert [c for c in r.sudo if "nvpmodel" in c] == ["-n nvpmodel -q"], "read once, never set"


@pytest.mark.parametrize("aslr", ["0", "1"])
def test_a_host_without_full_aslr_is_refused_and_the_setting_is_never_changed(tmp_path, schedule_file, aslr):
    r = _run(tmp_path, schedule_file, _host(tmp_path, aslr=aslr))
    _nothing_changed(tmp_path, r)
    assert "kernel.randomize_va_space is '%s', not 2" % aslr in r.stderr, r.stderr
    assert (tmp_path / "proc" / "sys" / "kernel" / "randomize_va_space").read_text() == aslr + "\n"


def test_a_harness_shell_without_aslr_is_refused(tmp_path, schedule_file):
    """setarch -R on the harness itself would hand ADDR_NO_RANDOMIZE to every launch, R's included."""
    r = _run(tmp_path, schedule_file, _host(tmp_path, personality="00040000"))
    _nothing_changed(tmp_path, r)
    assert "this shell runs without ASLR (personality 00040000)" in r.stderr, r.stderr


def test_a_board_boot_already_recorded_is_refused(tmp_path, schedule_file):
    r = _run(tmp_path, schedule_file, _host(tmp_path, boot_dir=True))
    assert r.returncode != 0 and "is recorded once" in r.stderr, r.stderr
    assert all(c.split(" ", 1)[1].startswith(BEFORE_ANY_CHANGE) for c in r.sudo) and not (tmp_path / "lock").exists()


def _recorded(tmp_path, tag, boot_id):
    d = tmp_path / "out" / tag
    d.mkdir(parents=True)
    with open(str(d / "boot.json"), "w", newline="\n") as f:      # the shape bj writes: indent 1, sorted keys
        f.write('{\n "boot_id": "%s",\n "boot_tag": "%s"\n}' % (boot_id, tag))


def test_a_boot_another_board_boot_was_recorded_on_is_refused(tmp_path, schedule_file):
    """Section 4.1: each board boot is a fresh boot. b2 on the boot b1 ran on would be scored as a
    board boot of its own."""
    env = _host(tmp_path)
    _recorded(tmp_path, "b0", "00000000-0000-4000-8000-000000000000")
    _recorded(tmp_path, "b1", BOOT_ID)
    r = _run(tmp_path, schedule_file, env)
    _nothing_changed(tmp_path, r)
    assert "board boot b1 was recorded on this boot (%s)" % BOOT_ID in r.stderr and "reboot first" in r.stderr, r.stderr


def test_a_boot_no_board_boot_was_recorded_on_goes_on(tmp_path, schedule_file):
    env = _past_the_lock(tmp_path, ifs_name="ifs-kick.bin")     # stops at the image, past the freshness check
    _recorded(tmp_path, "b1", "00000000-0000-4000-8000-000000000000")
    r = _run(tmp_path, schedule_file, env)
    assert "recorded on this boot" not in r.stderr and "ifs-stamp.bin" in r.stderr, r.stderr


def test_an_unreadable_boot_id_refuses(tmp_path, schedule_file):
    env = _host(tmp_path)
    (tmp_path / "proc" / "sys" / "kernel" / "random" / "boot_id").unlink()
    r = _run(tmp_path, schedule_file, env)
    _nothing_changed(tmp_path, r)
    assert "cannot read this boot's id" in r.stderr, r.stderr


def test_an_unreadable_pstore_refuses_and_is_never_read_as_empty(tmp_path, schedule_file):
    env = _host(tmp_path)
    (tmp_path / "sys" / "fs" / "pstore").rmdir()
    r = _run(tmp_path, schedule_file, env)
    _nothing_changed(tmp_path, r)
    assert "cannot read %s/fs/pstore" % env["SYS_ROOT"] in r.stderr and "M8" in r.stderr, r.stderr


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root reads any directory")
def test_an_unreadable_archive_refuses(tmp_path, schedule_file):
    env = _host(tmp_path, var=("2026/console-ramoops-0",))
    var = tmp_path / "var-pstore"
    os.chmod(str(var), 0)
    try:
        r = _run(tmp_path, schedule_file, env)
    finally:
        os.chmod(str(var), 0o755)
    _nothing_changed(tmp_path, r)
    assert "cannot read systemd's pstore archive" in r.stderr, r.stderr


def test_a_missing_archive_reads_as_empty(tmp_path, schedule_file):
    """systemd makes the archive when it first archives a record: before that it does not exist."""
    env = _host(tmp_path, uptime="30.0 1.0")
    (tmp_path / "var-pstore").rmdir()
    r = _run(tmp_path, schedule_file, env)
    _nothing_changed(tmp_path, r)
    assert "let it settle" in r.stderr and "archive" not in r.stderr, r.stderr


def test_with_no_mark_yet_a_crash_record_in_systemds_archive_stops_the_run(tmp_path, schedule_file):
    """A crash on the reboot into the first board boot is archived by systemd at boot, and no board boot
    has marked the archive seen yet: it stops the run, and the message says how the owner goes on."""
    r = _run(tmp_path, schedule_file, _host(tmp_path, var=("2026/dmesg-ramoops-1", "2026/console-ramoops-0")))
    _nothing_changed(tmp_path, r)
    assert "holds a crash record (2026/dmesg-ramoops-1)" in r.stderr and "no board boot has marked" in r.stderr, r.stderr
    assert "a6-randomise.pstore-seen" in r.stderr and "the owner reads it" in r.stderr


def test_with_no_mark_yet_console_records_alone_do_not_stop_the_run(tmp_path, schedule_file):
    r = _run(tmp_path, schedule_file, _host(tmp_path, var=("2026/console-ramoops-0",), uptime="10.0 1.0"))
    _nothing_changed(tmp_path, r)
    assert "crash record" not in r.stderr and "let it settle" in r.stderr, r.stderr


# ------------------------------------------------------------------ refused between the image and the first change

# The refusals from the resident loads to the journal come after the check that /dev/kvm is readable, which a login
# outside the kvm group (a developer's, a CI runner's) fails. These tests run the harness's own text in a copy of it
# with two edits and no other: that check made true, and a barrier put where the next refusal reads the harness's own
# cgroup, so that a host which passes everything above stops there, with nothing changed, even on a systemd host.
RIG_KVM = ('[ -r /dev/kvm ] || die "/dev/kvm is not readable: the guest cannot run under KVM (is the login in the kvm '
           'group?)"')
RIG_ME = 'ME="$(basename "$(cut -d: -f3 /proc/self/cgroup)")"'
MONITOR_SOURCES = ["qnx-safety-monitor/monitor.c", "common/shm_map_posix.c", "common/ivshm_client.c", "common/frame.h",
                   "common/frame_io.h", "common/shm_chan.h", "common/shm_map.h", "common/ivshm_client.h"]
LOADS = ["llama-server", "llama-cli", "llama-bench", "fma", "cpuload"]
RIG_ONLY = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the copy runs on stub tools and reads the real /proc")
CLEAN_DMESG = ["[    1.000000] Booting Linux on physical CPU 0x0000000000 [0x410fd4a0]"]
OOPS_DMESG = CLEAN_DMESG + ["[   90.100000] Internal error: Oops: 0000000096000004 [#1] PREEMPT SMP",
                            "[   90.200000] Unable to handle kernel paging request at virtual address 0000000000000010",
                            "[   91.000000] eth0: link up"]
IP_STUB = r'''ST="%(st)s"
case "$*" in
  "netns list") cat "$ST/netns"; exit 0 ;;
  "link show veth-a6r") if [ -e "$ST/veth" ]; then echo "9: veth-a6r@if8: <BROADCAST> mtu 1500"; exit 0; fi; exit 1 ;;
  "link show br0") if [ -e "$ST/br0" ]; then echo "3: br0: <BROADCAST> mtu 1500"; exit 0; fi; exit 1 ;;
  "link show tap-qnx") echo "4: tap-qnx: <BROADCAST> mtu 1500 $(cat "$ST/tap")"; exit 0 ;;
esac
echo "ip: unexpected: $*" >&2
exit 99'''


def _rig(tmp_path, dmesg=CLEAN_DMESG, dmesg_rc=0, journal_rc=0, tegrastats="GR3D_FREQ 0%@[0]", netns="", veth=False,
         br0=True, tap="master br0 state UP", halt_poll=True):
    """_past_the_lock's faked host, the harness's copy (see above) and the tools the refusals read: dmesg, journalctl,
    tegrastats and ip are stubs; the loads are looked for in /proc, as the harness does (see _run_rig). Returns
    (env, the copy's path)."""
    env = _past_the_lock(tmp_path)
    gc = tmp_path / "rig" / "orin-native" / "gpu-concurrency"
    gc.mkdir(parents=True)
    text = _text(HARNESS)
    assert text.count(RIG_KVM) == 1 and text.count(RIG_ME) == 1, "the two lines the copy edits are not each there once"
    with open(str(gc / "run-randomise.sh"), "w", newline="\n") as f:
        f.write(text.replace(RIG_KVM, "true").replace(RIG_ME, 'echo "RIG-BARRIER" >&2; exit 0\n' + RIG_ME))
    for rel in MONITOR_SOURCES:                 # the harness hashes the monitor's sources relative to itself
        dst = tmp_path / "rig" / "ipc-test" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(os.path.join(HERE, "..", "ipc-test", rel), str(dst))
    st = tmp_path / "ipstate"
    st.mkdir()
    (st / "netns").write_text(netns)
    (st / "tap").write_text(tap + "\n")
    for flag, on in (("veth", veth), ("br0", br0)):
        if on:
            (st / flag).write_text("")
    b = tmp_path / "bin"
    _stub(b / "ip", IP_STUB % {"st": _posix(st)})
    _stub(b / "dmesg", "".join("echo %s\n" % shlex.quote(x) for x in dmesg) + "exit %d" % dmesg_rc)
    _stub(b / "journalctl", "exit %d" % journal_rc)
    _stub(b / "tegrastats", ("echo %s" % shlex.quote("RAM 1000/7000MB SWAP 0/0MB CPU [0%%@729] %s" % tegrastats)) if tegrastats else "exit 0")
    if halt_poll:
        hp = tmp_path / "sys" / "module" / "kvm" / "parameters"
        hp.mkdir(parents=True)
        (hp / "halt_poll_ns").write_text("500000\n")
    env.update(TEGRA="1", **{k: _posix(os.path.join(GC, v)) for k, v in (
        ("LIB", "lib-measure.sh"), ("PROBE", "latency_probe.py"), ("REPORT", "randomise_report.py"),
        ("GENERATOR", "randomise_schedule.py"), ("LAUNCHER", "launch-qnx-kvm-bridged.sh"), ("QUIESCE", "platform-quiesce.sh"))})
    return env, _posix(gc / "run-randomise.sh")


def _run_rig(tmp_path, schedule, env, script, resident=None, decoy=False):
    """_run on the copy, with a process started beside it first: RESIDENT, a sleep whose argv[0] is that name and whose
    comm is not (a resident program is looked for by argv[0]), or DECOY, a process with the loads' names among its
    arguments only. The harness looks for loads in /proc, so the whole run is inside a PID namespace of its own where
    the host lets a user make one: another test's resident, or a real QEMU on the machine, is then not seen, and
    the processes die with the namespace. Without one the host's /proc is what is read."""
    start = ""
    if resident:
        start += "(exec -a %s sleep 120) &\n" % shlex.quote(resident)
    if decoy:
        start += '"%s" -c "import time; time.sleep(120)" llama-server qemu-system-aarch64 monitor-native &\n' \
                 % _posix(os.path.realpath(sys.executable))
    inner = tmp_path / "rig-inner.sh"
    _stub(inner, start + 'bash "%s"\nrc=$?\nkill $(jobs -p) 2>/dev/null\nexit $rc' % script)
    prefix = ("unshare", "--user", "--map-root-user", "--pid", "--fork", "--mount-proc") if _private_pids() else ()
    return _run(tmp_path, schedule, env, script=_posix(inner), prefix=prefix)


def _read_only_in_the_rig(r):
    return all(c.split(" ", 1)[1].startswith(BEFORE_ANY_CHANGE + ("nvpmodel -q", "dmesg", "journalctl -n 1 -u ssh"))
               for c in r.sudo)


def test_the_loads_the_harness_refuses_are_the_ones_listed_here():
    assert '\nLOADS="%s"\n' % " ".join(LOADS) in _head_body()[1]


@RIG_ONLY
def test_a_host_with_nothing_in_the_way_reaches_the_barrier_having_read_only(tmp_path, schedule_file):
    """The control of the refusals below: the same host with nothing wrong gets past all of them. A process with
    the loads' names among its arguments only is not a resident."""
    env, script = _rig(tmp_path)
    r = _run_rig(tmp_path, schedule_file, env, script, decoy=True)
    assert r.returncode == 0 and "RIG-BARRIER" in r.stderr and "FATAL" not in r.stderr, \
        "expected the barrier (exit 0), got exit %d:\n%s" % (r.returncode, r.stdout + r.stderr)
    assert _read_only_in_the_rig(r), r.sudo
    assert [c for c in r.sudo if c.endswith("dmesg")] == ["-n dmesg"] and "-n journalctl -n 1 -u ssh" in r.sudo, r.sudo
    assert not (tmp_path / "out" / "b2" / "boot.json").exists()


def _refused_in_the_rig(tmp_path, schedule_file, why, resident=None, **faults):
    env, script = _rig(tmp_path, **faults)
    r = _run_rig(tmp_path, schedule_file, env, script, resident=resident)
    assert r.returncode == 1 and why in r.stderr and "RIG-BARRIER" not in r.stderr, \
        "expected a refusal (exit 1) saying %r, got exit %d:\n%s" % (why, r.returncode, r.stdout + r.stderr)
    assert _read_only_in_the_rig(r), r.sudo
    assert not (tmp_path / "out" / "b2" / "boot.json").exists()


@RIG_ONLY
@pytest.mark.parametrize("name", LOADS)
def test_a_resident_load_is_refused(tmp_path, schedule_file, name):
    _refused_in_the_rig(tmp_path, schedule_file, "%s is resident -- this design runs no load" % name, resident=name)


@RIG_ONLY
@pytest.mark.parametrize("name,why", [
    pytest.param("qemu-system-aarch64", "a qemu-system-aarch64 is already running; this harness launches its own", id="qemu"),
    pytest.param("monitor-native", "a monitor-native is already running; it would answer arm A in place of this run's",
                 id="monitor")])
def test_a_qemu_or_a_native_monitor_already_running_is_refused_by_its_argv0(tmp_path, schedule_file, name, why):
    # the resident's comm is sleep: a name taken from comm (truncated to 15 characters) would miss it
    _refused_in_the_rig(tmp_path, schedule_file, why, resident=name)


@RIG_ONLY
@pytest.mark.parametrize("faults,why", [
    ({"tegrastats": "GR3D_FREQ 37%@[612]"}, "GR3D is not 0% at preflight"),
    ({"tegrastats": ""}, "GR3D is not 0% at preflight"),
    ({"netns": "a6rand (id: 0)\n"}, "the namespace a6rand exists"),
    ({"veth": True}, "veth-a6r exists"),
    ({"br0": False}, "br0 does not exist"),
    ({"tap": "state DOWN"}, "tap-qnx is not enslaved to br0"),
    ({"dmesg": OOPS_DMESG}, "the kernel log holds 2 oops line(s)"),
    ({"dmesg_rc": 1}, "the kernel log holds unread oops line(s), or cannot be read"),
    ({"journal_rc": 1}, "sudo -n journalctl does not work"),
    ({"halt_poll": False}, "halt_poll_ns is not readable"),
], ids=["gpu-busy", "gpu-unread", "netns-left", "veth-left", "no-br0", "tap-not-on-br0", "oops", "dmesg-unreadable",
        "journal-unreadable", "no-halt-poll"])
def test_the_host_refusals_between_the_image_and_the_first_change(tmp_path, schedule_file, faults, why):
    _refused_in_the_rig(tmp_path, schedule_file, why, **faults)


# ------------------------------------------------------------------ the record lines, read by the report's parser

def _source_env(tmp_path, env=None):
    """The environment the harness's functions are sourced in: stub sudo, python3, taskset and pgrep first
    on PATH, the library switch on, /proc faked under tmp_path."""
    b = tmp_path / "bin"
    b.mkdir(exist_ok=True)
    _stub(b / "sudo", '[ "$1" = -n ] || exit 97\nshift\nexec "$@"')
    _stub(b / "python3", 'exec "%s" "$@"' % _posix(sys.executable))
    _stub(b / "taskset", 'shift 2\nexec "$@"')
    _stub(b / "pgrep", 'case "$*" in "-o -x systemd-udevd") echo 31 ;; "-x gnome-shell") echo 41; echo 42 ;; esac')
    e = dict(os.environ, A6R_LIB_ONLY="1", PROC_ROOT=_posix(tmp_path / "proc"),
             PATH=_posix(b) + os.pathsep + os.environ.get("PATH", ""))
    e.update(env or {})
    return e


def _source(tmp_path, snippet, env=None):
    script = 'set -u\n. "%s"\n%s\n' % (_posix(HARNESS), snippet)
    return subprocess.run([BASH, "-c", script], capture_output=True, text=True, env=_source_env(tmp_path, env), timeout=120)


def _task(tmp_path, pid, comm, allowed, last=0, tid=None):
    d = tmp_path / "proc" / str(pid) / ("task/%d" % tid if tid else "")
    d.mkdir(parents=True, exist_ok=True)
    (d / "status").write_text("Name:\t%s\nCpus_allowed_list:\t%s\n" % (comm, allowed))
    if tid:
        (d / "comm").write_text(comm + "\n")
        (d / "stat").write_text("%d (%s) %s\n" % (tid, comm, " ".join(["S"] + ["0"] * 35 + [str(last), "0"])))


def test_the_readback_line_is_what_the_report_reads(tmp_path):
    d = tmp_path / "proc" / "4242"
    d.mkdir(parents=True)
    (d / "personality").write_text("00040000\n")
    (d / "environ").write_bytes(b"PATH=/usr/sbin:/usr/bin:/sbin:/bin\0LC_ALL=C\0PYTHONHASHSEED=0\0")
    (d / "stat").write_text("4242 (python3) " + " ".join(["S"] + ["1"] * 24 + ["281474976711234"] + ["0"] * 3) + "\n")
    (d / "maps").write_text("aaaa0000-aaab0000 r-xp 0 0 0 x\nbbbb0000-bbbc0000 r--p 0 0 0 x\ncccc0000-cccd0000 rw-p 0 0 0 x\n"
                            "ffff0000-ffff1000 rw-p 0 0 0 [stack]\n")
    vm = tmp_path / "v1"
    vm.mkdir()
    r = _source(tmp_path, 'VM_DIR="%s"; readback_line probe-C r3 4242 "$(date +%%s%%N)"' % _posix(vm))
    assert r.returncode == 0, r.stderr
    got = rr.VM(str(vm), 1).readback
    assert len(got) == 1
    who, rnd, f = got[0]
    assert (who, rnd) == ("probe-C", "3") and f["personality"] == "00040000" and f["environ"] == "61"
    assert f["startstack"] == "281474976711234" and f["pid"] == "4242" and f["t_ms"].isdigit()
    assert int(f["environ"]) == rs.env_bytes(rs.launch_env(None, hashseed=0))


def test_the_thread_and_confinement_lines_are_what_the_report_reads(tmp_path):
    for tid, comm, allowed, last in ((900, "qemu-system-aar", "0", 0), (901, "CPU 0/KVM", "1", 1), (902, "CPU 1/KVM", "2", 2)):
        _task(tmp_path, 900, comm, allowed, last, tid=tid)
    for pid, allowed in ((31, "3,5"), (1, "3,5"), (41, "3,5"), (42, "3-5")):
        _task(tmp_path, pid, "x", allowed)
    vm = tmp_path / "v2"
    vm.mkdir()
    r = _source(tmp_path, 'VM_DIR="%s"; QPID=900; threads_line 3 before' % _posix(vm))
    assert r.returncode == 0, r.stderr
    v = rr.VM(str(vm), 2)
    assert [(rn, w, f["comm"], f["allowed"], f["last"]) for rn, w, f in v.threads] == [
        (3, "before", "qemu-system-aar", "0", "0"), (3, "before", "CPU 0/KVM", "1", "1"), (3, "before", "CPU 1/KVM", "2", "2")]
    assert v.confine == [(3, "before", {"udevd": "3,5", "pid1": "3,5", "shells": "3,5;3-5"})]


def test_the_restores_are_judged_before_a_board_boot_is_complete(tmp_path):
    """Section 10: the board reads as found before any reboot. A governor or an idle state that did not
    come back, or a confinement drop-in left behind, is named and fails the judgement."""
    gov, cst, drop = tmp_path / "cpu0-scaling_governor", tmp_path / "state1-disable", tmp_path / "control"
    gov.write_text("schedutil\n")
    cst.write_text("0\n")
    snippet = ('DROPIN_ROOT="%s"; UNITS="system.slice init.scope"; GOV_WANT["%s"]=schedutil; CST_WANT["%s"]=0; '
               'restores_judged && echo JUDGED-OK || echo JUDGED-FAILED') % (_posix(drop), _posix(gov), _posix(cst))
    r = _source(tmp_path, snippet)
    assert "JUDGED-OK" in r.stdout, r.stdout + r.stderr
    gov.write_text("performance\n")
    r = _source(tmp_path, snippet)
    assert "JUDGED-FAILED" in r.stdout and "reads 'performance', was 'schedutil'" in r.stderr, r.stdout + r.stderr
    gov.write_text("schedutil\n")
    cst.write_text("1\n")
    r = _source(tmp_path, snippet)
    assert "JUDGED-FAILED" in r.stdout and "state1-disable reads '1', was '0'" in r.stderr, r.stdout + r.stderr
    cst.write_text("0\n")
    (drop / "init.scope.d").mkdir(parents=True)
    (drop / "init.scope.d" / "50-AllowedCPUs.conf").write_text("[Scope]\nAllowedCPUs=3,5\n")
    r = _source(tmp_path, snippet)
    assert "JUDGED-FAILED" in r.stdout and "init.scope.d/50-AllowedCPUs.conf is still there" in r.stderr, r.stderr


def test_what_each_restore_must_read_back_is_what_the_pin_and_c7_changed(tmp_path):
    r = _source(tmp_path, 'GOV_ORIG=([/a]=schedutil [/b]=ondemand); CSTATE_ORIG=([/c]=0); remember_restores; '
                'echo "${GOV_WANT[/a]} ${GOV_WANT[/b]} ${CST_WANT[/c]} ${#GOV_WANT[@]} ${#CST_WANT[@]}"')
    assert r.stdout.split() == ["schedutil", "ondemand", "0", "2", "1"], r.stdout + r.stderr


def test_the_end_judges_the_restores_before_the_board_boot_is_complete():
    body = _head_body()[1]
    end = body[body.index("# ---------------------------------------------------------------- the board boot's end"):]
    assert end.index("m_governor_restore") < end.index("restores_judged ||") < end.index("bj complete true")
    assert body.index("\nm_cstate_apply\n") < body.index("\nremember_restores\n") < body.index("\nns_up ||")
    assert body.count("restores_judged ||") == 1 and body.count("\nremember_restores\n") == 1
    assert 'rm -f "$DROPIN_ROOT/$u.d/50-AllowedCPUs.conf"' in body and "\nDROPIN_ROOT=/run/systemd/system.control" in body


def test_the_confinement_is_restored_to_0_5_explicitly_with_its_drop_ins_removed(tmp_path):
    """Not 0-4, not an empty list: the units go back to every core, then the drop-ins go and systemd reloads,
    and udevd is read back; a board whose udevd is still confined is named and the restore fails."""
    mark = tmp_path / "sudo.log"
    snippet = ('sudo() { echo "$*" >> "$M"; }; CONF_TOUCHED=1; UNITS="system.slice init.scope"; DROPIN_ROOT=/dr; '
               'conf_restore; echo "rc=$? touched=$CONF_TOUCHED"')
    _task(tmp_path, 31, "x", "0-5")
    r = _source(tmp_path, snippet, env={"M": _posix(mark)})
    assert r.stdout.strip().endswith("rc=0 touched=0"), r.stdout + r.stderr
    assert mark.read_text().splitlines() == [
        "-n systemctl set-property --runtime system.slice AllowedCPUs=0-5",
        "-n systemctl set-property --runtime init.scope AllowedCPUs=0-5",
        "-n rm -f /dr/system.slice.d/50-AllowedCPUs.conf", "-n rmdir /dr/system.slice.d",
        "-n rm -f /dr/init.scope.d/50-AllowedCPUs.conf", "-n rmdir /dr/init.scope.d", "-n systemctl daemon-reload"]
    _task(tmp_path, 31, "x", "3,5")
    r = _source(tmp_path, snippet, env={"M": _posix(mark)})
    assert "rc=1 touched=0" in r.stdout and "WARNING: udevd is not on 0-5" in r.stderr, r.stdout + r.stderr
    mark.unlink()
    r = _source(tmp_path, snippet.replace("CONF_TOUCHED=1", "CONF_TOUCHED=0"), env={"M": _posix(mark)})
    assert "rc=0 touched=0" in r.stdout and not mark.exists(), "nothing was confined, so nothing is restored"


def test_boot_json_records_every_path_the_host_is_read_through(tmp_path):
    """A figure read through a test hook is not the board's: the report fails M5 on any hook here other
    than its BOARD_HOOKS (the board's own paths, and TEGRA=1)."""
    names = ("PROC_ROOT", "SYS_ROOT", "RESET_REASON", "PSTORE_VAR", "EMC_BPMP", "EMC_CCF", "SYSFS_CPU", "KVM_DEBUGFS", "TEGRA")
    clean = {k: v for k, v in os.environ.items() if k not in names}
    b = tmp_path / "bin"
    b.mkdir()
    _stub(b / "python3", 'exec "%s" "$@"' % _posix(sys.executable))
    cases = ((dict(clean, TEGRA="1"), dict(rr.BOARD_HOOKS)),
             (dict(clean, TEGRA="0", PROC_ROOT="/x/proc", EMC_CCF="/x/ccf"),
              dict(rr.BOARD_HOOKS, tegra=0, proc_root="/x/proc", emc_ccf="/x/ccf")))
    for i, (env, want) in enumerate(cases):
        d = tmp_path / ("boot%d" % i)
        d.mkdir()
        e = dict(env, A6R_LIB_ONLY="1", PATH=_posix(b) + os.pathsep + env.get("PATH", ""))
        r = subprocess.run([BASH, "-c", 'set -u; . "%s"; BOOT_DIR="%s"; record_hooks' % (_posix(HARNESS), _posix(d))],
                           capture_output=True, text=True, env=e, timeout=60)
        assert r.returncode == 0, r.stdout + r.stderr
        with open(str(d / "boot.json"), encoding="utf-8") as f:
            assert json.load(f)["hooks"] == want, i
    body = _head_body()[1]
    assert body.index("\nrecord_hooks\n") < body.index('\nQUIESCE_STATE="$QUIESCE_PATH"\n'), "recorded before anything is changed"


def test_section_4_6s_docker_bullet_says_what_this_commit_does_and_the_intro_names_the_change():
    prose = _prose(_head_body()[0])
    assert "this code does not exist" not in prose
    assert "- Ported to `main` by this harness's commit (D5)." in prose
    assert ("and the last Docker bullet, which said where this code lived before this commit, now says that this "
            "commit ports it (D5).") in prose


def test_the_header_says_what_the_fixes_decided():
    prose = _prose(_head_body()[0])
    for words in ("is the design's own text (only lines too long for this header are wrapped, and the markdown "
                  "heading marks dropped).",
                  "whose schedstat run time rose in that arm-round's KVM snapshot",
                  "A thread off its core with no entry at the snapshot's end has no run-time record and fails M4",
                  "QEMU is started on the REST core",
                  "200 x 2 ms = 400 ms after its launch, the earliest the warm-up can end",
                  "a flag voids nothing",
                  "that no board boot under OUT_BASE was recorded on (each one a fresh boot, section 4.1)",
                  "with no mark yet, any one",
                  "an unreadable one refuses",
                  "which the smoke boot b0 settles",
                  "M5 also fails on a test hook in force",
                  "M1 also needs boot.json's complete, which this harness writes only once the restores are judged",
                  "s_regime, qemu_pad and qemu_pin must equal its schedule line (section 4.5): the pad under M2, the "
                  "pin under M4, and the regime, which names both of S's parts, under both",
                  "the governor and the idle states read as they were before the pin and no drop-in is left"):
        assert words in prose, words


def test_the_emc_line_reads_both_nodes(tmp_path):
    a, b = tmp_path / "bpmp", tmp_path / "ccf"
    a.write_text("2133000000\n")
    b.write_text("2133000001\n")
    r = _source(tmp_path, "emc_line", env={"EMC_BPMP": _posix(a), "EMC_CCF": _posix(b)})
    assert r.stdout.strip() == "bpmp=2133000000 ccf=2133000001", r.stdout + r.stderr
    r = _source(tmp_path, "emc_line", env={"EMC_BPMP": _posix(tmp_path / "none"), "EMC_CCF": _posix(b)})
    assert r.stdout.strip() == "bpmp=unread ccf=2133000001"


def test_build_refuses_a_schedule_line_whose_environment_the_library_does_not_build(tmp_path):
    r = _source(tmp_path, 'build "probe b1 v1 r1 A norand=1 pad=- hashseed=0 env=60" probe-A python3 x; echo REACHED')
    assert r.returncode != 0 and "REACHED" not in r.stdout and "they disagree" in r.stderr


def test_sched_line_wants_exactly_one_line(tmp_path, schedule_file):
    r = _source(tmp_path, 'SCHEDULE="%s"; sched_line "probe b1 v1 r1 " && echo ONE || echo NOTONE; '
                'sched_line "boot b3 " > /dev/null && echo ONE' % _posix(schedule_file))
    assert r.stdout.split() == ["NOTONE", "ONE"], r.stdout + r.stderr


def test_the_source_only_switch_never_lets_a_run_go_on(tmp_path, schedule_file):
    env = dict(os.environ, A6R_LIB_ONLY="1", BOOT_TAG="b1", SCHEDULE=_posix(schedule_file), DRY="1")
    r = subprocess.run([BASH, HARNESS], capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode != 0 and "never for a run" in r.stderr and "plan:" not in r.stdout


# ------------------------------------------------------------------ signals, the last preflight refusal, the main flow

TRAPS = "trap 'exit 143' TERM; trap 'exit 129' HUP; trap 'exit 130' INT"
PIPE_TRAP = "trap 'exec >> \"$HOME/a6-randomise-hangup.log\" 2>&1; exit 141' PIPE"


def _stmts(text):
    """The lines of text, stripped: a statement is found by its whole line, so a copy that is commented
    out or has something put before it is not found."""
    return [ln.strip() for ln in text.split("\n")]


def _function(body, name):
    fn = body[body.index("\n%s() {" % name):]
    return fn[:fn.index("\n}\n")]


def _signal_traps():
    """The trap lines the harness has right after its EXIT trap (TRAPS and PIPE_TRAP, in the harness as committed)."""
    body = _head_body()[1]
    lines = body[body.index("\ntrap cleanup EXIT\n") + len("\ntrap cleanup EXIT\n"):].split("\n")
    n = 0
    while lines[n].startswith("trap "):
        n += 1
    return "\n".join(lines[:n])


def test_the_signal_traps_follow_the_exit_trap_before_the_first_change():
    assert _signal_traps() == TRAPS + "\n" + PIPE_TRAP
    body = _head_body()[1]
    assert body.index(TRAPS) < body.index(PIPE_TRAP) < body.index('\nQUIESCE_STATE="$QUIESCE_PATH"\n')


# The harness's functions sourced, its cleanup replaced by a marker write, and its own signal traps (the
# line it has after the EXIT trap) put on beside it; then a child to wait for. The marker is the proof
# that the EXIT trap ran, once.
SIGNALLED = '''set -u
. "%(harness)s"
export READY="$1"; MARK="$2"; SP=""
cleanup() { [ -z "$SP" ] || kill "$SP" 2>/dev/null; echo ran >> "$MARK"; }
trap cleanup EXIT
eval "$SIGNAL_TRAPS"
%(child)s
'''


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="process groups and signals")
@pytest.mark.parametrize("mode", ["wait", "foreground"])
@pytest.mark.parametrize("signame", ["TERM", "HUP", "INT"])
def test_a_signal_ends_the_run_through_the_exit_trap_every_time(tmp_path, signame, mode):
    """GNU timeout (partition_cycle's RUN_MAX_S) signals the harness's process group with TERM, and a
    dropped SSH session sends HUP. A shell with no trap of its own for the signal dies by it, and the
    cleanup that puts the board back (Docker, the confinement, the namespace, c7, the governor) is not
    guaranteed to run. With the traps the shell exits with 128 + the signal through the EXIT trap: the
    status shows it (a death by the signal itself is a negative return code), the marker shows the one
    cleanup. Ten runs of each, the group signalled 0.3 s after the child is running: a signal that lands
    in a child's fork-to-exec window is taken by the shell's copy there, not by the program (which then
    never sees it), and that is the shell's behaviour, not the trap's."""
    sig = getattr(signal, "SIG" + signame)
    child = {"wait": 'sleep 30 &\nSP=$!\necho started > "$READY"\nwait "$SP"',
             "foreground": 'sh -c \'echo started > "$READY"; exec sleep 30\''}[mode]
    script = tmp_path / "run.sh"
    _stub(script, SIGNALLED % {"harness": _posix(HARNESS), "child": child})
    env = _source_env(tmp_path)
    env["SIGNAL_TRAPS"] = _signal_traps()
    for i in range(10):
        ready, mark = tmp_path / ("ready%d" % i), tmp_path / ("mark%d" % i)
        p = subprocess.Popen([BASH, str(script), _posix(ready), _posix(mark)], env=env, start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            end = time.time() + 30
            while not ready.exists() and p.poll() is None and time.time() < end:
                time.sleep(0.005)
            if not ready.exists():
                os.killpg(p.pid, signal.SIGKILL)
                pytest.fail("the child never started: %s" % p.communicate()[1].decode("utf-8", "replace"))
            time.sleep(0.3)
            os.killpg(p.pid, sig)
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pytest.fail("run %d: still going 5 s after %s -- the shell waited for its child, not for the trap" % (i, signame))
            got = (p.returncode, mark.read_text() if mark.exists() else "")
            assert got == (128 + int(sig), "ran\n"), "run %d: %r" % (i, got)
        finally:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            p.wait()
            p.stderr.close()


# A cleanup that writes to stdout first, as the harness's does (its first line is say), then to a marker; the
# harness's own signal traps put on beside it; then output without end.
PIPED = '''set -u
cleanup() { echo "[cleanup] restoring"; echo "[cleanup] a warning" >&2; echo ran >> "$MARK"; }
trap cleanup EXIT
eval "$SIGNAL_TRAPS"
for i in $(seq 1 200); do echo "line $i"; sleep 0.05; done
'''


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="pipes and signals")
def test_a_reader_that_goes_away_ends_the_run_through_the_exit_trap_every_time(tmp_path):
    """An SSH session without a pty (what partition_cycle.sh opens) that drops sends the remote command no HUP:
    its next write gets EPIPE and SIGPIPE. The shell then dies by the signal, or runs the EXIT trap whose first
    line writes to the same pipe and dies inside it, and the cleanup that puts the board back is missed. With
    the PIPE trap the rest of the output, standard error included (one pipe over SSH), goes to a file, the shell
    exits with 141 through the EXIT trap, and the marker shows the one cleanup, whose own output is in the file.
    Ten runs, the reader closing after one line."""
    script = tmp_path / "run.sh"
    _stub(script, PIPED)
    home = tmp_path / "home"
    home.mkdir()
    env = dict(_source_env(tmp_path), HOME=_posix(home), SIGNAL_TRAPS=_signal_traps())
    for i in range(10):
        mark = tmp_path / ("mark%d" % i)
        env["MARK"] = _posix(mark)
        p = subprocess.Popen([BASH, str(script)], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            first = p.stdout.readline()
            p.stdout.close()                    # the reader goes away
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pytest.fail("run %d: still writing 10 s after its reader went away" % i)
            got = (first, p.returncode, mark.read_text() if mark.exists() else "")
            assert got == (b"line 1\n", 141, "ran\n"), "run %d: %r" % (i, got)
        finally:
            p.kill()
            p.wait()
    text = (home / "a6-randomise-hangup.log").read_text()
    assert text.count("[cleanup] restoring\n") == 10 and text.count("[cleanup] a warning\n") == 10


def test_cleanup_does_nothing_in_a_forked_copy_of_the_shell(tmp_path):
    """A group signal that lands in a child's fork-to-exec window can run the inherited EXIT trap in the forked
    copy as well as in the harness: cleanup acts only where $BASHPID is the harness's $$."""
    names = ("say", "mon_stop", "vm_stop", "ns_down", "conf_restore", "m_cstate_restore", "m_governor_restore")
    stubs = "; ".join('%s() { echo %s >> "$M"; }' % (n, n) for n in names)
    mark = tmp_path / "mark"
    for where in ("( cleanup )", "cleanup & wait", 'x="$(cleanup)"'):
        r = _source(tmp_path, stubs + "\n" + where, env={"M": _posix(mark)})
        assert r.returncode == 0 and not mark.exists(), (where, r.stdout + r.stderr)
    r = _source(tmp_path, stubs + "\ncleanup", env={"M": _posix(mark)})
    done = mark.read_text().split() if mark.exists() else []
    assert r.returncode == 0 and done == list(names), "cleanup in the harness's own process did %r" % done
    s = [x for x in _stmts(_function(_head_body()[1], "cleanup")) if x and not x.startswith("#")]
    assert s[:3] == ["cleanup() {", '[ "$BASHPID" = "$$" ] || return 0', 'say "cleanup"'], s[:4]


JOURNAL = ("1760720001.234567 orin-example sshd[4321]: Accepted publickey for tester from 203.0.113.9 port 51234 ssh2: "
           "ED25519 SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\n"
           "1760720002.000001 orin-example sshd[4322]: Connection closed by 203.0.113.9 port 51234\n"
           "1760720003.500000 orin-example sshd[4323]: Accepted password for tester from 203.0.113.10 port 40000 ssh2\n")


def _journal_line():
    return [ln for ln in _head_body()[1].split("\n") if ln.startswith("sudo -n journalctl -u ssh -u sshd --since")]


def _journal_run(tmp_path, sudo_body):
    d = tmp_path / "boot"
    d.mkdir()
    b = tmp_path / "bin"
    b.mkdir()
    _stub(b / "sudo", sudo_body)
    (tmp_path / "journal.txt").write_text(JOURNAL)
    line = _journal_line()
    assert len(line) == 1
    script = 'set -u\nT0=1760720000\nBOOT_DIR="%s"\n%s\njrc=${PIPESTATUS[0]}\necho "jrc=$jrc"\n' % (_posix(d), line[0])
    r = subprocess.run([BASH, "-c", script], capture_output=True, text=True, timeout=60,
                       env=dict(os.environ, PATH=_posix(b) + os.pathsep + os.environ.get("PATH", "")))
    return r, (d / "logins-journal.txt").read_text()


def test_the_logins_journal_keeps_the_time_of_each_accepted_login_and_nothing_else(tmp_path):
    """The record goes to a branch, and a line of sshd's journal carries the board's hostname, the login
    name, the client's address and port and the key's fingerprint: none of that is kept (documentation
    values here). The journalctl status is still the pipeline's first."""
    ok = '[ "$1" = -n ] || exit 97\nshift\n[ "$1" = journalctl ] || exit 98\ncat "%s"' % _posix(tmp_path / "journal.txt")
    r, kept = _journal_run(tmp_path, ok)
    assert r.returncode == 0 and r.stdout.strip() == "jrc=0", r.stdout + r.stderr
    assert kept == "1760720001.234567 Accepted\n1760720003.500000 Accepted\n", kept
    for word in ("orin-example", "tester", "203.0.113", "ED25519", "SHA256", "port", "ssh2"):
        assert word not in kept, word
    body = _head_body()[1]
    assert (_journal_line()[0] + "\njrc=${PIPESTATUS[0]}\n") in body


def test_a_journal_that_cannot_be_read_is_not_taken_for_one_with_no_logins(tmp_path):
    r, kept = _journal_run(tmp_path, "exit 5")
    assert r.stdout.strip() == "jrc=5" and kept == "", r.stdout + r.stderr


def _counter_code():
    body = _head_body()[1]
    head = "<<'PY' || die \"could not count the logins\"\n"
    start = body.index(head) + len(head)
    return body[start:body.index("\nPY\n", start)]


def test_a_login_counts_in_a_round_from_its_start_to_one_second_after_its_end(tmp_path):
    d = tmp_path / "boot"
    for v, rounds in (("1", ["round 0 start=1000 end=1010", "round 1 start=1100 end=1110"]), ("2", ["round 1 start=2000 end=2010"])):
        (d / ("v" + v)).mkdir(parents=True)
        (d / ("v" + v) / "rounds.log").write_text("".join(x + "\n" for x in rounds))
    (d / "logins-journal.txt").write_text("999.9 Accepted\n1000.0 Accepted\n1011.0 Accepted\n1011.5 Accepted\n"
                                          "not a time\n2010.5 Accepted\n")

    def counted(jrc):
        r = subprocess.run([sys.executable, "-", str(d), jrc, "1", "2"], input=_counter_code(), capture_output=True,
                           text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        return (d / "logins.txt").read_text().splitlines()
    assert counted("0") == ["v1 r0 accepted=2", "v1 r1 accepted=0", "v2 r1 accepted=1", "total accepted=3"]
    assert counted("1") == ["v1 r0 accepted=unread", "v1 r1 accepted=unread", "v2 r1 accepted=unread",
                            "total accepted=unread"]


def test_the_confinement_line_reads_udevd_and_process_one_each_from_its_own_process(tmp_path):
    for pid, allowed in ((31, "3,5"), (1, "0-5"), (41, "3,5"), (42, "4")):
        _task(tmp_path, pid, "x", allowed)
    r = _source(tmp_path, "conf_state")
    assert r.stdout.strip() == "udevd=3,5 pid1=0-5 shells=3,5;4", r.stdout + r.stderr


def test_the_vm_boot_loop_reads_the_threads_around_each_round_and_closes_a_vm_boot_in_order():
    body = _head_body()[1]
    end = "\n# " + "-" * 64 + " the board boot's end"
    loop = body[body.index("\nfor v in $VMS; do\n"):body.index(end)]
    s = _stmts(loop)
    order = ('threads_line "$r" before', 'mon_start "$v" "$r"', 'arm_round "$v" "$r" "$a"',
             'echo "round $r start=$t_start end=$t_end" >> "$VM_DIR/rounds.log"', 'threads_line "$r" after',
             'mon_stop || die "the native monitors would not stop at the end of v$v"', "m_governor_recheck",
             'm_stamp_after "$VM_DIR/stamp.json"', 'm_require_complete "$VM_DIR" A-loopback B-bridge C-null D-guest',
             'vm_stop || die "QEMU of v$v would not stop"')
    for stmt in order:
        assert s.count(stmt) == 1, stmt
    at = [s.index(x) for x in order]
    assert at == sorted(at)


def test_each_arm_round_samples_the_threads_cpus_and_the_emc_clock_after_the_probe_ended():
    s = _stmts(_function(_head_body()[1], "arm_round"))
    order = ('wait "$pid"; rc=$?', 'm_kvm_snap "$VM_DIR/kvm-$tag.json" after',
             'm_qemu_threads "$QPID" | sed "s/^/round $2 after-$3 /" >> "$VM_DIR/cpu.log"',
             'echo "round $2 after-$3 $(emc_line)" >> "$VM_DIR/emc.log"')
    for stmt in order:
        assert s.count(stmt) == 1, stmt
    at = [s.index(x) for x in order]
    assert at == sorted(at)


def test_the_monitors_are_read_back_by_their_own_pids_and_must_answer_on_both_paths():
    s = _stmts(_function(_head_body()[1], "mon_start"))
    assert s.count('readback_line mon-host "r$2" "$MON_HOST_PID" "$t0"') == 1
    assert s.count('readback_line mon-ns "r$2" "$MON_NS_PID" "$t0"') == 1
    assert 'for p in "127.0.0.1" "$NS_IP"; do' in s
    assert s.count('[ "$ok" = 1 ] || die "the native monitor at $p:$PORT does not answer in round $2"') == 1


def test_a_quiesce_stop_that_was_refused_is_not_restored_by_this_run():
    """platform-quiesce.sh stop exits 3 when another stop is outstanding: its state is not this run's, so
    cleanup must not restore it (QUIESCE_STATE is emptied at once)."""
    s = _stmts(_head_body()[1])
    at = s.index('rc=0; bash "$QUIESCE" stop "$QUIESCE_PATH" >> "$BOOT_DIR/quiesce.log" 2>&1 || rc=$?')
    assert s[at + 1] == '[ "$rc" != 3 ] || QUIESCE_STATE=""' and s[at + 2].startswith('[ "$rc" = 0 ] || die ')
    assert 'if [ -n "$QUIESCE_STATE" ]; then' in _stmts(_function(_head_body()[1], "cleanup"))


def test_the_units_to_confine_leave_out_the_harnesss_own_session_which_must_be_a_session_scope():
    s = _stmts(_head_body()[1])
    scope = 'case "$ME" in session-*.scope) ;; *) die "the harness is not in a session scope ($ME)" ;; esac'
    units = [x for x in s if x.startswith('UNITS="system.slice init.scope')]
    assert s.count(scope) == 1 and len(units) == 1 and "| grep -vx \"$ME\")" in units[0]
    assert s.index(scope) < s.index(units[0])


def test_the_qemu_that_runs_is_the_one_the_launcher_started():
    s = _stmts(_head_body()[1])
    launched = 'env "${LAUNCH_ENV[@]}" bash "$LAUNCHER" > "$VM_DIR/launch.log" 2>&1 < /dev/null; lrc=$?'
    only = '[ "$(m_pids_of qemu-system-aarch64)" = "$VM_PID" ] || die "the running QEMU is not the one the launcher started"'
    assert s.count(only) == 1
    assert s.index(launched) < s.index(only) < s.index('m_qemu_identify "$VM_PID"')


def test_the_pstore_mark_is_the_archive_listing_written_when_a_board_boot_completes():
    s = _stmts(_head_body()[1])
    mark = "mkdir -p \"$STATE_HOME\" && printf '%s\\n' $PSTORE_LIST > \"$PSTORE_MARK\""
    assert s.count(mark) == 1 and s.index(mark) + 1 == s.index("bj complete true")


def test_dev_kvm_is_checked_with_the_other_refusals_before_anything_is_changed():
    s = _stmts(_head_body()[1])
    tap = "ip link show tap-qnx 2>/dev/null | grep -q 'master br0' || die \"tap-qnx is not enslaved to br0: run setup-bridge-orin.sh\""
    kvm = '[ -r /dev/kvm ] || die "/dev/kvm is not readable: the guest cannot run under KVM (is the login in the kvm group?)"'
    assert s.count(kvm) == 1
    assert s.index(tap) < s.index(kvm) < s.index("trap cleanup EXIT")


def test_the_harness_reads_back_its_own_core_and_the_emc_clock_before_it_records_the_host():
    """Past the preflight these refusals cannot be run (the board boot's changes have been made), so each is held by
    its whole line and its place: a copy that is commented out, made true or changed does not match."""
    s = _stmts(_head_body()[1])
    move = 'taskset -pc "$CORE_AUX" $$ > /dev/null || die "could not move the harness onto core $CORE_AUX"'
    back = '[ "$(_cpuset "$(allowed $$)")" = "$CORE_AUX" ] || die "the harness reads $(allowed $$), not core $CORE_AUX"'
    emc = 'case "$EMC0" in *unread*) die "the EMC clock cannot be read ($EMC0): M7 needs it" ;; esac'
    for stmt in (move, back, emc):
        assert s.count(stmt) == 1, stmt
    at = s.index(move)
    assert s[at + 1] == back and s[at + 2] == 'EMC0="$(emc_line)"' and s[at + 3] == emc
    assert s.index("set_units \"$CONF_CORES\" || die \"could not confine the units to $CONF_CORES\"") < at


def test_every_vm_boot_ends_with_the_oops_check_before_its_stamp_is_finished():
    """The stop rule at the end of a VM boot: the kernel log read, and a line of an oops stops the run."""
    s = _stmts(_head_body()[1])
    die = '[ "$O" = 0 ] || die "the kernel log holds $O oops line(s) after v$v: the stop rule -- the owner decides"'
    assert s.count(die) == 1
    at = s.index(die)
    assert s[at - 1] == 'O="$(oops_count)"' and s[at + 1] == 'm_stamp_after "$VM_DIR/stamp.json"'
    assert s.index('m_thermal "v$v end" >> "$VM_DIR/thermal.log"') < at - 1


def test_the_schedules_fixed_list_must_be_the_librarys(tmp_path, schedule_file):
    """The schedule's `env` line is the library's M_FIXED_ENV; a library that builds another list than the one the
    schedule states is refused before the plan, as the sizes the schedule states would not be the launches'."""
    fixed = "M_FIXED_ENV=(PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C)"
    lib = _text(os.path.join(GC, "lib-measure.sh"))
    assert lib.count(fixed) == 1
    other = tmp_path / "lib-measure.sh"
    with open(str(other), "w", newline="\n") as f:
        f.write(lib.replace(fixed, fixed[:-1] + " TZ=UTC)"))
    r = _dry(schedule_file, "b1", {"LIB": _posix(other)})
    assert r.returncode != 0 and "the schedule's fixed list is not the library's" in r.stderr and "plan:" not in r.stdout, r.stderr
    r = _dry(schedule_file, "b1")
    assert r.returncode == 0 and "plan:" in r.stdout, r.stderr


def test_every_function_the_harness_defines_is_used():
    body = _head_body()[1]
    for name in re.findall(r"^([a-z_0-9]+)\(\) \{", body, re.M):
        uses = len(re.findall(r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % re.escape(name), body))
        assert uses >= 2, "%s is defined and never called" % name


# ------------------------------------------------------------------ the launcher's hooks

def _launch(tmp_path, **env):
    f = tmp_path / "x.bin"
    f.write_text("x")
    e = dict(os.environ, IFS_BIN=_posix(f), DISK=_posix(f))
    e.update(env)
    return subprocess.run([BASH, LAUNCHER], capture_output=True, text=True, env=e, timeout=30)


@pytest.mark.parametrize("env,why", [
    ({"QEMU_PIN": "1,2,0"}, "QEMU_PIN pins by thread name: it needs THREAD_NAMES=1"),
    ({"QEMU_PIN": "1,2,0", "THREAD_NAMES": "1", "SMP": "4"}, "QEMU_PIN has cores for two vCPUs: it needs SMP=2"),
    ({"QEMU_PIN": "1,1,0", "THREAD_NAMES": "1"}, "QEMU_PIN='1,1,0' is not three distinct cores"),
    ({"QEMU_PIN": "1,2", "THREAD_NAMES": "1"}, "QEMU_PIN='1,2' is not three distinct cores"),
    ({"QEMU_LAYOUT": "random"}, "QEMU_LAYOUT=random needs QEMU_PAD"),
    ({"QEMU_LAYOUT": "fixed", "QEMU_PAD": "16"}, "QEMU_LAYOUT=fixed takes no QEMU_PAD"),
    ({"QEMU_PAD": "16"}, "QEMU_PAD needs QEMU_LAYOUT=random"),
    ({"QEMU_LAYOUT": "aslr"}, "QEMU_LAYOUT='aslr' is not fixed or random"),
    ({"QEMU_PIN": "a,b,c", "THREAD_NAMES": "1"}, "QEMU_PIN='a,b,c' is not three distinct cores"),
    ({"QEMU_PIN": "1,2,0,3", "THREAD_NAMES": "1"}, "QEMU_PIN='1,2,0,3' is not three distinct cores"),
    ({"QEMU_PIN": "0,2,2", "THREAD_NAMES": "1"}, "QEMU_PIN='0,2,2' is not three distinct cores"),
    ({"QEMU_LAYOUT": "Fixed"}, "QEMU_LAYOUT='Fixed' is not fixed or random"),
])
def test_the_launcher_refuses_knobs_that_do_not_fit_before_anything_starts(tmp_path, env, why):
    r = _launch(tmp_path, **env)
    assert r.returncode == 1 and why in r.stderr, r.stderr
    assert "ifs    :" not in r.stdout, "refused before it printed or started anything"


NOHUP = 'nohup ${QEMU_PIN:+taskset -c ${QEMU_PIN##*,}} ${PREFIX[@]+"${PREFIX[@]}"} "${QEMU}" \\'


def test_the_launcher_puts_the_layout_before_qemu_and_keeps_the_device_order():
    text = _text(LAUNCHER)
    block = text[text.index(NOHUP):]
    block = block[:block.index('-nographic > "${LOG}" 2>&1 &')]
    order = [block.index(x) for x in ("-device virtio-blk-device,drive=drv0", "-device virtio-net-device,netdev=n0",
                                      "-device virtio-rng-device,rng=rng0", "KICK_ARGS", "SHM_ARGS", "NAME_ARGS",
                                      '-kernel "${IFS_BIN}"')]
    assert order == sorted(order)
    assert text.count(NOHUP) == 1 and "\nPREFIX=()\n" in text
    assert 'm_layout_cmd 1 -' in text and 'm_layout_cmd 0 "${QEMU_PAD}"' in text


# A stand-in for qemu-system-aarch64: QEMU's call_rcu thread is made before the vCPUs and waits on an
# event, so it sleeps across the launcher's pins; the vCPUs halt and wake; the "guest" answers on a port.
STANDIN = r'''import socket
import sys
import threading
import time

if len(sys.argv) > 1 and sys.argv[1] == "--version":
    print("QEMU emulator version 8.2.2 (a stand-in)")
    sys.exit(0)


def name(text):
    with open("/proc/self/task/%d/comm" % threading.get_native_id(), "w") as f:
        f.write(text)


def sleeper():
    name("call_rcu")
    threading.Event().wait()


def vcpu(n):
    name("CPU %d/KVM" % n)
    while True:
        time.sleep(0.02)


threading.Thread(target=sleeper, daemon=True).start()
time.sleep(0.1)
for i in (0, 1):
    threading.Thread(target=vcpu, args=(i,), daemon=True).start()
time.sleep(1.0)
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", __PORT__))
s.listen(8)
while True:
    s.accept()[0].close()
'''


# Run inside the launcher's PID namespace once it has returned: every QEMU thread as (tid, name, allowed
# CPUs, the CPU it last ran on -- /proc stat field 39), one JSON list.
THREADS_OF = r'''import json, os, sys
q = sys.argv[1]
out = []
for tid in sorted(os.listdir("/proc/%s/task" % q), key=int):
    with open("/proc/%s/task/%s/comm" % (q, tid)) as f:
        comm = f.read().strip()
    with open("/proc/%s/task/%s/stat" % (q, tid)) as f:
        stat = f.read()
    out.append([int(tid), comm, sorted(os.sched_getaffinity(int(tid))), int(stat[stat.rindex(")") + 2:].split()[36])])
print(json.dumps(out))
'''


def _private_pids():
    """Whether this host lets a user make a PID namespace of its own, with its own /proc."""
    if shutil.which("unshare") is None:
        return False
    r = subprocess.run(["unshare", "--user", "--map-root-user", "--pid", "--fork", "--mount-proc", "true"],
                       capture_output=True, timeout=30)
    return r.returncode == 0


# A stand-in whose second vCPU thread is created late: vCPU 0 exists at once, vCPU 1 a second later, and
# that thread reads its own allowed CPUs 1.2 s after it exists (a thread asks the kernel about itself with
# sched_getaffinity(0)) and writes them down, well before the "guest" answers at 3 s. The launcher polls
# every 0.1 s; the first pin is taken once both vCPU threads exist.
STANDIN_LATE = r'''import os
import socket
import sys
import threading
import time

if len(sys.argv) > 1 and sys.argv[1] == "--version":
    print("QEMU emulator version 8.2.2 (a stand-in)")
    sys.exit(0)


def name(text):
    with open("/proc/self/task/%d/comm" % threading.get_native_id(), "w") as f:
        f.write(text)


def vcpu0():
    name("CPU 0/KVM")
    while True:
        time.sleep(0.02)


def vcpu1():
    name("CPU 1/KVM")
    time.sleep(1.2)
    with open("__OUT__/vcpu1.affinity", "w") as f:
        f.write(",".join(str(c) for c in sorted(os.sched_getaffinity(0))))
    while True:
        time.sleep(0.02)


threading.Thread(target=vcpu0, daemon=True).start()
time.sleep(1.0)
threading.Thread(target=vcpu1, daemon=True).start()
time.sleep(2.0)
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", __PORT__))
s.listen(8)
while True:
    s.accept()[0].close()
'''


def _launcher_rig(tmp_path, standin, after, pin=None):
    """The launcher's copy, run from the auxiliary core inside a PID namespace of its own with a
    stand-in qemu-system-aarch64, and then the shell snippet AFTER inside the same namespace (it may use
    $qp, the stand-in's pid, and the placeholders __OUT__, __PY__ and __THREADS_OF__). The copy differs
    from the launcher only where a board is needed: /dev/kvm's check and the guest's address. The
    namespace is private so that another run's qemu-system-aarch64 on a shared host is not seen (the
    launcher refuses beside one), and the stand-in dies with the namespace. PIN gives the three cores
    (vCPU 0, vCPU 1, the rest) as the launcher's text from the host's first three CPUs. Returns
    (the finished process, the output directory, the launcher's log, the three cores, the auxiliary core)."""
    cpus = sorted(os.sched_getaffinity(0))
    if len(cpus) < 4 or shutil.which("taskset") is None or shutil.which("setarch") is None:
        pytest.skip("needs four CPUs, taskset and setarch")
    if not _private_pids():
        pytest.skip("needs a PID namespace of its own (unshare --user --pid)")
    aux, cores = cpus[-1], cpus[:3]
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    gc = tmp_path / "gc"
    gc.mkdir()
    text = _text(LAUNCHER)
    for old, new in (("[ -r /dev/kvm ]", '[ -r "%s" ]' % _posix(tmp_path / "kvm")),
                     ("/dev/tcp/192.168.100.10/7100", "/dev/tcp/127.0.0.1/%d" % port)):
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    with open(str(gc / "launch-qnx-kvm-bridged.sh"), "w", newline="\n") as f:
        f.write(text)
    shutil.copy(os.path.join(GC, "lib-measure.sh"), str(gc / "lib-measure.sh"))
    (tmp_path / "kvm").write_text("x")
    out = tmp_path / "out"
    out.mkdir()
    q = tmp_path / "qemu"
    q.mkdir()
    (q / "standin.py").write_text(standin.replace("__PORT__", str(port)).replace("__OUT__", _posix(out)))
    (q / "threads_of.py").write_text(THREADS_OF)
    py = os.path.realpath(sys.executable)
    _stub(q / "qemu-system-aarch64", 'exec -a qemu-system-aarch64 "%s" "%s" "$@"' % (py, _posix(q / "standin.py")))
    b = tmp_path / "bin"
    b.mkdir()
    _stub(b / "ip", 'echo "7: tap-qnx: <BROADCAST,MULTICAST,UP> mtu 1500 master br0 state UP"')
    img = tmp_path / "x.bin"
    img.write_text("x")
    snippet = after.replace("__OUT__", _posix(out)).replace("__PY__", py).replace("__THREADS_OF__", _posix(q / "threads_of.py"))
    inner = tmp_path / "inner.sh"
    _stub(inner, 'taskset -c %d bash "%s" > "%s/launch.log" 2>&1\necho "launcher exit $?" >> "%s/launch.log"\n'
                 'qp="$(sed -n "s/^qemu pid: //p" "%s/launch.log")"\n%s'
          % (aux, _posix(gc / "launch-qnx-kvm-bridged.sh"), _posix(out), _posix(out), _posix(out), snippet))
    env = dict(os.environ, IFS_BIN=_posix(img), DISK=_posix(img), LOG=_posix(tmp_path / "console.log"),
               QEMU=_posix(q / "qemu-system-aarch64"), QEMU_LAYOUT="fixed", THREAD_NAMES="1", SMP="2",
               QEMU_PIN=(pin or (lambda c: "%d,%d,%d" % tuple(c)))(cores),
               PATH=_posix(b) + os.pathsep + os.environ.get("PATH", ""))
    r = subprocess.run(["unshare", "--user", "--map-root-user", "--pid", "--fork", "--mount-proc", BASH, str(inner)],
                       capture_output=True, text=True, env=env, timeout=120)
    return r, out, (out / "launch.log").read_text(), cores, aux


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="threads and their CPUs under /proc")
def test_qemu_starts_on_the_rest_core_so_a_thread_asleep_across_the_pin_reads_its_groups_core(tmp_path):
    """The harness runs the launcher from its own core, the auxiliary reader's. A QEMU thread that sleeps
    from its birth through both pins keeps the CPU it was born on as its last CPU (the kernel moves a
    sleeping thread only when it wakes): born there, it would read the auxiliary core in every M4 sample.
    The stand-in is the one the rig runs, with threads named as QEMU names them."""
    r, out, log, (v0, v1, rest), _aux = _launcher_rig(
        tmp_path, STANDIN, '[ -z "$qp" ] || "__PY__" "__THREADS_OF__" "$qp" > "__OUT__/threads.json"')
    assert r.returncode == 0 and "launcher exit 0" in log and (out / "threads.json").exists(), log + r.stderr
    threads = {}
    for tid, comm, allowed, last in json.loads((out / "threads.json").read_text()):
        threads.setdefault(comm, []).append((tid, allowed, last))
    for comm, core in (("call_rcu", rest), ("CPU 0/KVM", v0), ("CPU 1/KVM", v1)):
        assert len(threads.get(comm, [])) == 1 and threads[comm][0][1] == [core], (comm, threads)
    sleeper, _allowed, last = threads["call_rcu"][0]
    assert last == rest, "born on the REST core, it reads it though it never woke after the pins (%d)" % last
    assert re.search(r"^pinned : tid=%d last=%d allowed=%d comm=call_rcu$" % (sleeper, rest, rest), log, re.M), log


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="threads and their CPUs under /proc")
def test_the_first_pin_waits_until_both_vcpu_threads_exist(tmp_path):
    """The second vCPU thread is created a second after the first. Pinned when it appears, it reads its
    own allowed CPUs (1.2 s later, long before the guest answers) as its group's core. A first pin taken
    when only vCPU 0 existed would leave it on the REST core it was born on, until the second pin that
    follows the guest's answer: a vCPU on another core for most of the launch."""
    r, out, log, (_v0, v1, _rest), _aux = _launcher_rig(tmp_path, STANDIN_LATE, "")
    assert r.returncode == 0 and "launcher exit 0" in log, log + r.stderr
    assert (out / "vcpu1.affinity").read_text() == str(v1), (out / "vcpu1.affinity").read_text()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="threads and their CPUs under /proc")
def test_a_pin_that_does_not_hold_stops_qemu_and_fails_the_launch(tmp_path):
    """vCPU 0 is asked for a core the host does not have, with QEMU running on the REST core: the first
    pin fails, and the launcher kills the QEMU it started and exits 1 -- a guest left running under
    another placement than its VM boot's label would be measured as the wrong setup."""
    r, out, log, _cores, _aux = _launcher_rig(
        tmp_path, STANDIN,
        'for i in $(seq 1 50); do kill -0 "$qp" 2>/dev/null || break; sleep 0.1; done\n'
        'if kill -0 "$qp" 2>/dev/null; then echo RUNNING > "__OUT__/after.txt"; else echo GONE > "__OUT__/after.txt"; fi',
        pin=lambda c: "4094,%d,%d" % (c[1], c[2]))
    assert "launcher exit 1" in log and "could not be pinned by name to 4094," in log, log + r.stderr
    assert (out / "after.txt").read_text().strip() == "GONE", (out / "after.txt").read_text()


def test_the_launcher_pins_by_name_after_launch_and_again_once_the_guest_answers():
    text = _text(LAUNCHER)
    launch = text.index('qpid=$!')
    first = text.index('m_pin_by_name "${qpid}" "${QEMU_PIN}"', launch)
    up = text.index('guest up after')
    again = text.index('m_pin_by_name "${qpid}" "${QEMU_PIN}"', first + 1)
    assert launch < first < again < up
    assert text.count('m_pin_by_name "${qpid}" "${QEMU_PIN}"') == 2


def test_the_launchers_existing_knobs_and_messages_are_kept():
    text = _text(LAUNCHER)
    assert "THREAD_NAMES='${THREAD_NAMES}' is not 0 or 1" in text
    assert 'VECTORS="${VECTORS:-1}"' in text and 'case "${VECTORS}" in 1|2)' in text
    assert "DEVICE ORDER IS LOAD-BEARING: blk, then net, then rng." in text


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the real setarch, on Linux")
def test_the_launchers_prefix_is_the_librarys(tmp_path):
    """The words the launcher puts before QEMU for each layout, from the library it sources."""
    lib = os.path.join(GC, "lib-measure.sh")
    for args, want_setarch in (("1 -", True), ("0 96", False)):
        r = subprocess.run([BASH, "-c", '. "%s"; m_layout_cmd %s; printf "%%s\\n" "${LAYOUT_CMD[@]}"' % (_posix(lib), args)],
                           capture_output=True, text=True, timeout=30)
        assert ("setarch" in r.stdout.split()) is want_setarch, r.stdout + r.stderr

