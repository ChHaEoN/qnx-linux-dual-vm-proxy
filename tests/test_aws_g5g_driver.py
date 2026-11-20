"""A g5g.metal session, the operator's side and the small tools (SDV Phase 8, the g5g leg: T1, T2, T5's list file and
pin generator, T6, T7, T8).

Nothing here contacts AWS, a GPU or a package archive. drive-metal.sh runs against test_aws_tooling's stub `aws`, `ssh`
and `scp`, with one more answer (the availability zone); build-llama.sh runs on test_board_builds' made-up host;
vlm_stamp.py runs against a made-up root and a stub driver tool. Every id, address and version is a documentation
value or made up.

What these tests do not show: that EC2 takes the zone word, that any package exists, that a driver's tool prints what
the stub prints, or that anything here ran on a g5g.metal instance.

KVM here boots our startup-qemu-virt; this is not a QNX-supported
configuration, and no timing claim attaches to the boot.
"""
import hashlib
import json
import os
import re
import subprocess
import sys

import pytest

import test_aws_tooling as aws
from test_aws_tooling import BASH, REPO, needs_bash

rig = aws.rig      # the driver's stub rig, a fixture here too

EDGE = os.path.join(REPO, "orin-native", "edge-llm")
LIST = os.path.join(EDGE, "g5g-packages.list")
PINGEN = os.path.join(EDGE, "g5g_pins.py")
STAMP = os.path.join(EDGE, "vlm_stamp.py")
BUILD_LLAMA = os.path.join(EDGE, "build-llama.sh")
G5G_PHASES = ("stop", "gpu-facts", "gpu-install", "llama-build", "launch-svc", "vlm")
ZONE_CASE = '  *Placement.AvailabilityZone*) echo "${STUB_ZONE:-None}" ;;\n'
linux_only = pytest.mark.skipif(os.name == "nt", reason="made-up /proc, /sys and /dev trees: Linux only")


def _zone_stub(stub):
    """test_aws_tooling's stub aws with one more answer: the zone EC2 reports (STUB_ZONE)."""
    body = aws.STUB_AWS.replace('  *) echo "stub aws: unhandled', ZONE_CASE + '  *) echo "stub aws: unhandled')
    assert ZONE_CASE in body
    aws._write(stub / "aws", body, newline=False)


def _sent(log):
    return [ln for ln in log.splitlines() if "run-instances" in ln]


# ------------------------------------------------------------------ T1: the type and the zone

@needs_bash
def test_launch_without_the_zone_word_sends_todays_arguments_and_says_the_zone(rig, monkeypatch):
    monkeypatch.delenv("METAL_AZ", raising=False)
    run, state, stub = rig
    _zone_stub(stub)
    r, log = run("launch", METAL_TYPE="g5g.metal", STUB_ZONE="eu-central-1c")
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    sent = _sent(log)
    assert len(sent) == 1 and "--placement" not in sent[0] and "AvailabilityZone" not in sent[0], sent
    # the whole argument list, as it is sent today (the token and the rendered user-data's path are the run's own)
    assert re.fullmatch(
        r"ec2 run-instances --region eu-central-1 --image-id ami-0d9429f78b33241cd --instance-type g5g\.metal "
        r"--key-name lab-key --security-groups lab-sg --client-token qnx-a6-\S+ "
        r"--instance-initiated-shutdown-behavior terminate --user-data file://\S+ --block-device-mappings "
        r'\[\{"DeviceName":"/dev/sda1","Ebs":\{"DeleteOnTermination":true,"VolumeSize":16,"VolumeType":"gp3"\}\}\] '
        r"--tag-specifications ResourceType=instance,Tags=\[\{Key=Name,Value=qnx-a6-ladder\}\] "
        r"ResourceType=volume,Tags=\[\{Key=Name,Value=qnx-a6-ladder\}\] "
        r"--query Instances\[0\]\.InstanceId --output text", sent[0]), sent[0]
    assert "(g5g.metal, eu-central-1)" in out and "availability zone: eu-central-1c" in out, out
    assert (state / "type").read_text() == "g5g.metal\n"


@needs_bash
def test_launch_with_the_zone_word_asks_for_that_zone_and_reads_it_back(rig):
    run, state, stub = rig
    _zone_stub(stub)
    r, log = run("launch", METAL_TYPE="g5g.metal", METAL_AZ="eu-central-1b", STUB_ZONE="eu-central-1b")
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    sent = _sent(log)
    assert len(sent) == 1 and "--placement AvailabilityZone=eu-central-1b " in sent[0], sent
    assert "availability zone: eu-central-1b" in out, out
    assert "terminate-instances" not in log


@needs_bash
@pytest.mark.parametrize("zone", ["eu-central-1", "us-east-1a", "eu-central-1ab", "b", "eu-central-1B", "eu-central-1a;x"])
def test_a_zone_word_of_the_wrong_shape_or_region_is_refused_before_any_aws_call(rig, zone):
    run, state, stub = rig
    _zone_stub(stub)
    r, log = run("launch", METAL_AZ=zone)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "METAL_AZ" in out and "availability zone of eu-central-1" in out, out
    assert log == "" and not (state / "id").exists() and not (state / "lock").exists()


@needs_bash
@pytest.mark.parametrize("got", ["eu-central-1a", "None"])
def test_a_zone_that_reads_back_as_another_terminates_the_launch(rig, got):
    run, state, stub = rig
    _zone_stub(stub)
    r, log = run("launch", METAL_AZ="eu-central-1b", STUB_ZONE=got)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "ABORT" in out and "not the eu-central-1b asked for" in out, out
    assert "terminate-instances" in log and (state / "terminated").exists()


@needs_bash
def test_a_zone_ec2_does_not_say_is_said_as_unread_when_none_was_asked_for(rig, monkeypatch):
    monkeypatch.delenv("METAL_AZ", raising=False)
    run, state, stub = rig          # the stub as every other test has it: it does not know the zone question
    r, log = run("launch")
    out = r.stdout + r.stderr
    assert r.returncode == 0 and "availability zone: unread" in out, out
    assert "terminate-instances" not in log


@needs_bash
def test_a_zone_read_back_that_is_not_a_zone_is_asked_again_and_the_asked_zone_then_stands(rig):
    """The AWS CLI's text form of a null is `None`: not a zone of the region, so a retry, not an answer."""
    run, state, stub = rig
    body = aws.STUB_AWS.replace(
        '  *) echo "stub aws: unhandled',
        '  *Placement.AvailabilityZone*) n="$(cat "$STUB_DIR/zn" 2>/dev/null || echo 0)"; echo $((n + 1)) > "$STUB_DIR/zn"\n'
        '    if [ "$n" = 0 ]; then echo None; else echo "$STUB_ZONE"; fi ;;\n  *) echo "stub aws: unhandled')
    assert "/zn" in body
    aws._write(stub / "aws", body, newline=False)
    r, log = run("launch", METAL_AZ="eu-central-1b", STUB_ZONE="eu-central-1b")
    out = r.stdout + r.stderr
    assert r.returncode == 0 and "availability zone: eu-central-1b" in out, out
    assert int((stub / "zn").read_text()) == 2 and "terminate-instances" not in log


@needs_bash
def test_a_zone_that_reads_as_none_with_no_zone_asked_for_is_said_as_unread(rig, monkeypatch):
    monkeypatch.delenv("METAL_AZ", raising=False)
    run, state, stub = rig
    _zone_stub(stub)            # STUB_ZONE not given: the stub answers `None`
    r, log = run("launch")
    out = r.stdout + r.stderr
    assert r.returncode == 0 and "availability zone: unread" in out, out
    assert "terminate-instances" not in log


# ------------------------------------------------------------------ T2 and the phase list

@needs_bash
@pytest.mark.parametrize("words", ["HARNESS=run-vss-setup.sh IMAGE=ifs-vss.bin",
                                   "HARNESS=run-vss-suite.sh IMAGE=ifs-vss.bin PLAN=v1 VSS_HOST=g5g-metal",
                                   "HARNESS=run-vss-setup.sh IMAGE=ifs-vss.bin VSS_HOST=c7g-metal"])
def test_a_vss_harness_on_a_g5g_metal_session_is_refused_before_anything_reaches_the_instance(rig, words):
    run, state, stub = rig
    aws._launched(state)
    (state / "armed").touch()
    (state / "ip").write_text("203.0.113.9\n")
    (state / "type").write_text("g5g.metal\n")
    r, _ = run("run", "harness", LADDER_ENV=words)
    out = r.stdout + r.stderr
    assert r.returncode != 0, out
    assert "this session launched g5g.metal, which has no vss host role (a1.metal: a1-metal, c7g.metal: c7g-metal)" in out
    assert not (stub / "ssh.log").exists(), "nothing may reach the instance"


@needs_bash
@pytest.mark.parametrize("phase", G5G_PHASES)
def test_run_reaches_each_g5g_phase_and_stop(rig, phase):
    run, state, stub = rig
    aws._launched(state)
    (state / "armed").touch()
    (state / "ip").write_text("203.0.113.9\n")
    r, _ = run("run", phase, LADDER_ENV="MODE=plan")
    assert r.returncode == 0, r.stdout + r.stderr
    sent = (stub / "ssh.log").read_text()
    assert "LADDER_ENV=MODE=plan" in sent.replace("\\", "") and "a1/remote-ladder.sh %s" % phase in sent, sent


# ------------------------------------------------------------------ T9: the README section

def test_the_readme_has_the_g5g_session_section_and_it_states_no_result():
    with open(os.path.join(REPO, "scripts", "aws", "README.md"), encoding="utf-8", newline="") as f:
        text = f.read()
    head = "### A g5g session (SDV plan Phase 8)\n"
    assert text.count(head) == 1
    section = text.split(head, 1)[1].split("\n## ", 1)[0]
    assert text.index("### An aw session (SDV plan Phase 8)") < text.index(head) < text.index("## What bounds the cost")
    assert section.strip(), "the section is empty"
    words = re.findall(r"\b(ran|passed|measured|worked)\b", section, re.I)
    assert not words, words


# ------------------------------------------------------------------ T5: the list file and the pin generator

def _list_rows():
    rows = []
    with open(LIST, encoding="utf-8", newline="") as f:
        for ln in f.read().split("\n"):
            if ln and not ln.startswith("#"):
                rows.append(ln.split(" "))
    return rows


def test_the_list_file_holds_names_only_in_three_lists_and_no_nvidia_modprobe_git_or_curl():
    raw = open(LIST, "rb").read()
    assert b"\r" not in raw and raw.endswith(b"\n")
    assert hashlib.sha256(raw).hexdigest().startswith("b6fec3a3"), "the list file's pinned content"
    rows = _list_rows()
    assert all(len(r) == 2 and r[0] in ("driver", "toolkit", "build") for r in rows), rows
    names = [r[1] for r in rows]
    assert names == ["linux-modules-nvidia-580-server-@KREL@", "nvidia-kernel-common-580-server",
                     "libnvidia-compute-580-server", "nvidia-utils-580-server", "cuda-nvcc-13-2", "cuda-cudart-dev-13-2",
                     "libcublas-dev-13-2", "cmake"]
    assert not any("=" in n for n in names), "names only, never a version"
    assert not {"nvidia-modprobe", "git", "curl"} & set(names)


# Made-up versions, each put together here so that this file's text holds no run of four dotted numbers (the shape of an
# address, which tests/test_no_real_identifiers.py allows only from its list): an Ubuntu revision and a four-part
# version, the two forms the redactor's IPv4 rule rewrites.
UB = "0.0.1-0ubuntu0.24" + ".04.1"
V4 = "13.0.0" + ".1-1"
APPROVED = """\
# a made-up approved-names file: every version, size and hash is a stand-in
pkg cmake=%(ub)s ubuntu 100 %(h1)s
pkg cuda-nvcc-13-2=%(v4)s nvidia 200 %(h2)s
pkg cuda-toolkit-config-common=13.0.86-1 nvidia 300 %(h3)s
pkg libnvidia-compute-580-server=580.0.04-%(ub)s ubuntu 400 %(h4)s
key cuda-keyring cuda-keyring_1.1-1_all.deb %(h5)s
pins g5g-nvidia-pins %(h6)s
index-cap 60000000
total all 1000
""" % dict({"h%d" % i: ("%x" % i) * 64 for i in range(1, 7)}, ub=UB, v4=V4)
PINS = ("Package: cuda-nvcc-13-2\nPin: version %s\nPin-Priority: 1001\n\n"
        "Package: cuda-toolkit-config-common\nPin: version 13.0.86-1\nPin-Priority: 1001\n" % V4)


def test_the_pin_generator_writes_one_stanza_per_nvidia_line_in_the_files_order_and_nothing_for_ubuntus(tmp_path):
    p = tmp_path / "g5g-approved.txt"
    p.write_bytes(APPROVED.encode())
    r = subprocess.run([sys.executable, PINGEN, str(p)], capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout == PINS.encode(), r.stdout
    r = subprocess.run([sys.executable, PINGEN, "--name"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and r.stdout == "g5g-nvidia-pins\n", "one fixed name, with no extension"


@pytest.mark.parametrize("bad", ["pkg cuda-x 13.0-1 nvidia 1 " + "a" * 64, "pkg cuda-x=13.0-1 nvidia 1 short",
                                 "pkg cuda x=1 nvidia 1 " + "a" * 64, "pkg cuda-x=1.0 elsewhere 1 " + "a" * 64])
def test_the_pin_generator_refuses_a_package_line_it_cannot_read(tmp_path, bad):
    p = tmp_path / "g5g-approved.txt"
    p.write_bytes((APPROVED + bad + "\n").encode())
    r = subprocess.run([sys.executable, PINGEN, str(p)], capture_output=True, text=True, timeout=60)
    assert r.returncode != 0 and r.stdout == "" and "line" in r.stderr, r.stderr


# ------------------------------------------------------------------ T8: the redactor

GPU_UUID = "GPU-0a1b2c3d-4e5f-6a7b-8c9d-0e1f2a3b4c5d"      # made up, in the driver's form


def _redact(text, *args, **env):
    e = dict(os.environ, USER="", PATH=aws._path_with(), **env)
    return subprocess.run([BASH, aws.REDACT] + list(args), input=text, capture_output=True, text=True, env=e, timeout=120)


@needs_bash
@pytest.mark.parametrize("awk", aws._AWKS)
def test_the_redactor_masks_a_gpu_uuid_and_its_selftest_holds_the_case(awk):
    r = _redact("ggml_cuda_init: device 0 (%s) ready\nuuid=%s\n" % (GPU_UUID, GPU_UUID.upper()), AWK=awk)
    assert r.returncode == 0 and "0a1b2c3d" not in r.stdout.lower() and "0e1f2a3b4c5d" not in r.stdout.lower(), r.stdout
    assert r.stdout.count("<gpu-uuid>") == 2, r.stdout
    rule = r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"      # leakscan's, as LEAK_UUID below spells it
    assert re.search(rule, "uuid=%s\n" % GPU_UUID.upper()), "the rule finds a UUID-shaped string: the case it guards"
    assert not re.search(rule, r.stdout), "leakscan's rule"
    s = _redact("", "selftest", AWK=awk)
    assert s.returncode == 0 and "PASS" in s.stdout, s.stdout
    body = open(aws.REDACT, encoding="utf-8").read()
    assert re.search(r'check "gpu uuid"\s+"[^"]*GPU-[0-9a-f-]{36}[^"]*"\s+"[^"]+"\s+0', body), "a selftest case, masked direction"


LEAK_UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")     # leakscan.py's
U1, U2 = "1b2c3d4e-5f6a-7b8c-9d0e-1f2a3b4c5d6e", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"                       # made up


@needs_bash
@pytest.mark.parametrize("awk", aws._AWKS)
def test_the_redactor_masks_every_uuid_the_scan_after_the_fetch_would_refuse_and_no_other(awk):
    """A g5g stem brings in logs of package scripts and of a model server; one UUID in one of them, unmasked, would
    fail the fetch's scan and leave terminate refusing. The rule is the scan's own, boundary for boundary."""
    assert LEAK_UUID.pattern in open(aws.LEAKSCAN, encoding="utf-8").read(), "the scan's rule, as this test spells it"
    lines = ["I: The initramfs will attempt to resume from /dev/stub", "I: (UUID=%s)" % U1,
             "root=PARTUUID=%s ro" % U1, "after a dash: x-%s." % U2, "two: %s,%s" % (U1, U2.upper()), U1,
             "kept, glued to a word before: id_%s" % U1, "kept, glued to a word after: %sz" % U1,
             "kept, hex before: abc%s" % U1, "one, then its tail: %s-5f6a-7b8c-9d0e-1f2a3b4c5d6e" % U1,
             "kept, two runs that only overlap: 00000000-1111-2222-3333-aaaaaaaaaaaabbbbbbbb-1111-2222-3333-cccccccccccc"]
    r = _redact("".join(ln + "\n" for ln in lines), AWK=awk)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == [LEAK_UUID.sub("<uuid>", ln) for ln in lines], r.stdout
    assert not LEAK_UUID.search(r.stdout) and r.stdout.count("<uuid>") == 7, r.stdout
    body = open(aws.REDACT, encoding="utf-8").read()
    assert re.search(r'check "uuid"\s+"[^"]*[0-9a-f-]{36}[^"]*"\s+"[^"]+"\s+0', body), "a selftest case, masked direction"
    assert re.search(r'check "uuid, glued"\s+"[^"]*[0-9a-f-]{36}[^"]*"\s+"[^"]+"\s+1', body), "and one in the kept direction"


@needs_bash
def test_version_strings_with_underscores_and_hashes_pass_the_redactor_unchanged():
    """T5's rule for versions: a four-part version and an Ubuntu revision become <ip> in a transcript, so the set is
    also written with "_" for every "." of the version field, and equality is shown by hashes."""
    dotted = "cuda-nvcc-13-2=%s\ncmake=%s\n" % (V4, UB)
    under = "".join("%s=%s\n" % (n, v.replace(".", "_")) for n, v in (ln.split("=") for ln in dotted.split()))
    hashes = "approved %s\nplan: approved set %s\ninstalled set %s\n" % ("a" * 64, "b" * 64, "b" * 64)
    assert "<ip>" in _redact(dotted).stdout, "the reason for the rule"
    assert _redact(under + hashes).stdout == under + hashes


# ------------------------------------------------------------------ T6: build-llama.sh's architecture word

def _llama_host(tmp_path):
    import test_board_builds as tbb
    return tbb, tbb.Host(tmp_path / "host")


@needs_bash
@pytest.mark.parametrize("word,arch", [(None, "87"), ("87", "87"), ("75", "75")])
def test_build_llama_takes_the_cuda_architecture_as_a_word_and_87_without_one(tmp_path, monkeypatch, word, arch):
    monkeypatch.delenv("CUDA_ARCH", raising=False)
    tbb, host = _llama_host(tmp_path)
    r = host.run("llama", **({} if word is None else {"CUDA_ARCH": word}))
    assert r.returncode == 0, r.all
    cm = tbb.tools(r.calls, "cmake")
    flags = [f.replace("=87", "=" + arch) if "ARCHITECTURES" in f else f for f in tbb.LLAMA_FLAGS]
    assert cm[0].args[4:4 + len(flags)] == flags, cm[0].args
    assert ("-DCMAKE_CUDA_ARCHITECTURES=%s " % arch) in tbb.one(tbb.info_lines(host, "llama"), "flags ")


@needs_bash
@pytest.mark.parametrize("word", ["86", "native", "75;87", "075", ""])
def test_build_llama_refuses_any_other_architecture_word_before_anything_is_configured(tmp_path, word):
    tbb, host = _llama_host(tmp_path)
    r = host.run("llama", CUDA_ARCH=word)
    if word == "":      # an empty word is no word: today's 87
        assert r.returncode == 0, r.all
        return
    assert r.returncode == 1 and "CUDA_ARCH" in r.err and "75 or 87" in r.err, r.all
    assert tbb.tools(r.calls, "cmake") == []


# ------------------------------------------------------------------ T7: the stamp

STAMP_ENV = {"MODEL": "m.gguf", "MMPROJ": "mm.gguf", "SRV_ARGV_STR": "taskset -c 3,5 llama-server -np 1",
             "CORE_SRV": "3,5", "REPS": "0", "ROUNDS": "0", "WARMUP": "1", "NO_GUEST": "0"}
SMI_TWO = r'''
echo "nvidia-smi $*" >> "$STUB/calls.log"
q=""; for a; do case "$a" in --query-gpu=*) q="${a#--query-gpu=}" ;; esac; done
[ -n "$q" ] || { echo "a table"; exit 0; }
for i in 0 1; do      # every GPU of the host, whatever -i says: the worst case T7 names
  out=""
  for f in ${q//,/ }; do
    case "$f" in index) v=$i ;; name) v="Stub GPU" ;; compute_cap) v=7.5 ;; driver_version) v=0.0.00 ;;
      memory.total) v="1 MiB" ;; uuid) v=GPU-0a1b2c3d-4e5f-6a7b-8c9d-0e1f2a3b4c5d ;; *) v="[N/A]" ;; esac
    out="${out:+$out, }$v"
  done
  echo "$out"
done
'''


def _stamp_rig(tmp_path, tegra, smi=None):
    root = tmp_path / "root"
    if tegra:
        aws._write(root / "proc" / "device-tree" / "model", "Made-up Tegra Board\0", newline=False)
        aws._write(root / "etc" / "nv_tegra_release", "# R00 (release), REVISION: 0.0\nsecond line")
    out = tmp_path / "out"
    out.mkdir(parents=True)
    (out / "requests.start").write_text("2026-01-01T00:00:00Z\n")
    bins = {"sudo": 'echo "sudo $*" >> "$STUB/calls.log"; case "$*" in *nvpmodel*) printf "NV Power Mode:  STUB\\n1\\n" ;; esac',
            "ps": "exit 0", "git": "echo %s" % ("c" * 40)}
    if smi:
        bins["nvidia-smi"] = smi
    stub = aws._stubs(tmp_path / "bin", bins)
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "m.gguf").write_bytes(b"m")
    (tmp_path / "models" / "mm.gguf").write_bytes(b"mm")
    env = dict(os.environ, STUB=str(stub), PATH=str(stub) + os.pathsep + "/usr/bin" + os.pathsep + "/bin", STAMP_ROOT=str(root), IMAGES="/in",
               BIN=str(tmp_path / "llama.cpp" / "build" / "bin"), MODELS=str(tmp_path / "models"), **STAMP_ENV)
    env.pop("CUDA_VISIBLE_DEVICES", None)
    return out, env


def _sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def _todays_l4t_stamp(tmp_path, out):
    """What vlm_stamp.py writes today on the made-up Tegra root, field for field in today's order."""
    sys.path.insert(0, EDGE)
    try:
        import vlm_request
    finally:
        sys.path.remove(EDGE)
    return {
        "experiment": "vlm-characterize", "utc": "2026-01-01T00:00:00Z", "board": "Made-up Tegra Board",
        "l4t": "# R00 (release), REVISION: 0.0", "nvpmodel": "NV Power Mode: STUB 1",
        "governor": "pinned to performance for the run, restored after",
        "page_cache": "dropped before the server started; cudaMalloc does not reclaim it on this board",
        "llama_cpp": "c" * 40, "llama_server_sha256": None,
        "model": "m.gguf", "model_sha256": hashlib.sha256(b"m").hexdigest(),
        "mmproj": "mm.gguf", "mmproj_sha256": hashlib.sha256(b"mm").hexdigest(),
        "server_argv": STAMP_ENV["SRV_ARGV_STR"],
        "cores": {"server": "3,5", "client": 5, "probe": 4, "qemu": "0-2"},
        "prompt": vlm_request.PROMPT, "grammar": vlm_request.GRAMMAR,
        "request": "temperature 0, max_tokens 2, top_logprobs %d, cache_prompt false" % vlm_request.TOP_LOGPROBS,
        "confidence": ("P(answer) at token position 1 (the model's first token is a space), over the ten "
                       "digit tokens present there, renormalised; the digit tokens' raw mass is recorded per request"),
        "reps": 0, "rounds": 0, "warmup_excluded": 1,
        "images": "/in/{0..9}.pgm (NVIDIA's TensorRT samples; not committed)",
        "vlm_request_sha256": _sha(os.path.join(EDGE, "vlm_request.py")), "vlm_stamp_sha256": _sha(STAMP),
        "script_sha256": _sha(os.path.join(EDGE, "vlm-characterize.sh")),
        "guest": "running beside the server", "guest_ifs": None, "guest_ifs_sha256": None,
        "mem_before": None, "mem_resident": None, "mem_after": None,
    }


@linux_only
def test_the_stamp_on_l4t_is_todays_byte_for_byte(tmp_path):
    out, env = _stamp_rig(tmp_path, tegra=True, smi=SMI_TWO)
    r = subprocess.run([sys.executable, STAMP, str(out)], capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr
    want = json.dumps(_todays_l4t_stamp(tmp_path, out), indent=1)
    assert (out / "stamp.json").read_text() == want
    assert "nvidia-smi" not in (tmp_path / "bin" / "calls.log").read_text(), "on L4T no driver tool is asked"


def _strings(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield k
            yield from _strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from _strings(v)
    elif isinstance(o, str):
        yield o


@linux_only
def test_the_stamp_off_l4t_says_so_keeps_the_page_cache_word_and_is_one_line_per_string(tmp_path):
    out, env = _stamp_rig(tmp_path, tegra=False, smi=SMI_TWO)
    env["CUDA_VISIBLE_DEVICES"] = "0"
    (out / "mem-before.txt").write_text("two lines\nof a memory read\nand a third\n")   # any field's text may hold one
    r = subprocess.run([sys.executable, STAMP, str(out)], capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr
    raw = (out / "stamp.json").read_text()
    s = json.loads(raw)
    assert s["board"] == "not a Tegra host" and s["l4t"] == "not a Tegra host"
    assert s["page_cache"] == "dropped before the server started"
    assert "performance" not in s["governor"] and "left as found" in s["governor"]
    assert s["cores"] == {"server": "3,5", "client": 5, "probe": "not applicable", "qemu": "not applicable"}
    assert "0-2" not in raw and "this board" not in raw and "Tegra Board" not in raw
    assert s["cuda_visible_devices"] == "0" and s["mem_before"] == "unreadable"
    assert all("\n" not in x for x in _strings(s)), "capture.py's A6 rule ends the capture on a string with a newline"
    assert s["gpu"] in ("unreadable", {"name": "unreadable", "compute_cap": "unreadable", "driver_version": "unreadable"})
    calls = (tmp_path / "bin" / "calls.log").read_text()
    asked = [ln for ln in calls.splitlines() if ln.startswith("nvidia-smi")]
    assert asked and all("uuid" not in ln and "serial" not in ln and (" -i 0" in ln or "--id=0" in ln) for ln in asked), asked
    assert "nvpmodel" not in calls


@linux_only
def test_a_string_holding_a_carriage_return_is_one_line_too_unreadable_not_kept(tmp_path):
    """Text-mode reads turn a CR into a newline before the stamp sees it, so a raw CR can only come by an environment word:
    capture.py's A6 rule ends a capture on it, as on a newline."""
    out, env = _stamp_rig(tmp_path, tegra=False, smi=SMI_TWO)
    env["MODEL"] = "m\r.gguf"
    r = subprocess.run([sys.executable, STAMP, str(out)], capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr
    raw = (out / "stamp.json").read_text()
    s = json.loads(raw)
    assert s["model"] == "unreadable" and "\\r" not in raw, raw
    assert all("\r" not in x and "\n" not in x for x in _strings(s))


@linux_only
def test_the_stamp_off_l4t_names_the_first_gpu_and_without_a_driver_tool_says_that(tmp_path):
    one_gpu = SMI_TWO.replace("for i in 0 1; do", "for i in 0; do")
    out, env = _stamp_rig(tmp_path, tegra=False, smi=one_gpu)
    r = subprocess.run([sys.executable, STAMP, str(out)], capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr
    s = json.loads((out / "stamp.json").read_text())
    assert s["gpu"] == {"name": "Stub GPU", "compute_cap": "7.5", "driver_version": "0.0.00"}
    assert s["cuda_visible_devices"] == "unset"
    out2, env2 = _stamp_rig(tmp_path / "second", tegra=False)
    env2["PATH"] = str(tmp_path / "second" / "bin") + os.pathsep + "/usr/bin" + os.pathsep + "/bin"
    r = subprocess.run([sys.executable, STAMP, str(out2)], capture_output=True, text=True, env=env2, timeout=60)
    assert r.returncode == 0, r.stderr
    assert json.loads((out2 / "stamp.json").read_text())["gpu"] == "no driver tool"


@linux_only
@needs_bash
def test_a_two_gpu_stamp_passes_the_capture_as_it_stands(tmp_path):
    out, env = _stamp_rig(tmp_path, tegra=False, smi=SMI_TWO)
    assert subprocess.run([sys.executable, STAMP, str(out)], capture_output=True, env=env, timeout=60).returncode == 0
    rec = tmp_path / "rec"
    aws._write(rec / "liveness" / "cost" / "stamp.json", (out / "stamp.json").read_text(), newline=False)
    aws._write(rec / "liveness" / "cost" / "lat-A_r1.json", json.dumps({"samples_ms": [1.0]}), newline=False)
    r = aws._capture(rec, tmp_path / "pub")
    assert r.returncode == 0, r.stdout + r.stderr
