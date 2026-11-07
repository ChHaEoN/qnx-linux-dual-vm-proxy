"""Draft board-client checks. Only fake sockets and a native PC monitor are used."""

from pathlib import Path
import json
import shutil
import socket
import struct
import subprocess
import threading
import time
import sys
import hashlib
import platform
import os

import pytest

_saved = sys.dont_write_bytecode
sys.dont_write_bytecode = True
from sdv.frame import kind4_client as kc  # noqa: E402

sys.dont_write_bytecode = _saved

rules, vf = kc.rules, kc.vf

CONTRACT_PATH = Path(__file__).resolve().parents[1] / "sdv-out" / "gen" / "vss_contract.py"
DOC_NODE = "kind4-example-node.invalid"
DOC_BOOT = (
    'import runpy,socket,sys,platform;platform.node=lambda:"kind4-example-node.invalid";socket.gethostname=lambda:"kind4-example-node.invalid";'
    'sys.argv=sys.argv[1:];runpy.run_path(sys.argv[0],run_name="__main__")'
)


@pytest.fixture(autouse=True)
def documentation_metadata(monkeypatch):
    # Identifier-leak mutants must exercise a made-up value, never the PC's name.
    monkeypatch.setattr(socket, "gethostname", lambda: DOC_NODE)
    monkeypatch.setattr(platform, "node", lambda: DOC_NODE)


@pytest.fixture(scope="module")
def contract():
    if not CONTRACT_PATH.exists():
        pytest.skip("needs the generated contract")
    return vf.load_contract(CONTRACT_PATH.parent)


@pytest.fixture(scope="module")
def tables(contract):
    return rules.Tables.from_contract(contract)


def test_reason_campaign_has_one_of_each_and_one_accept(contract, tables):
    cases = kc.build_cases(contract, tables, start_seq=100)
    assert [case.reason for case in cases] == [0, 8, 9, 10, 21, 22, 23, 24, 25, 26, 27]
    assert len({vf.decode(case.frame, reply=False).seq for case in cases if case.reason not in (9, 10)}) == 9
    for case in cases:
        assert rules.judge_frame(case.frame, tables) == (int(case.reason != 0), case.reason)


def test_reply_check_is_byte_exact_and_catches_mutations(contract, tables):
    frame = kc.build_cases(contract, tables, start_seq=200)[-1].frame
    good = rules.reply(frame, tables)
    kc.verify_reply(frame, good, tables)
    for at in (0, 22, 23, 40, 63):
        bad = bytearray(good)
        bad[at] ^= 1
        with pytest.raises(kc.CheckError):
            kc.verify_reply(frame, bytes(bad), tables)


def test_stamp_path_refuses_injected_frame_and_requires_both_stamps(contract, tables):
    cases = kc.build_cases(contract, tables, start_seq=300)
    injected = cases[1].frame
    with pytest.raises(kc.CheckError):
        kc.verify_reply(injected, rules.reply(injected, tables), tables, stamp=True)
    frame = cases[0].frame
    plain = bytearray(rules.reply(frame, tables))
    with pytest.raises(kc.CheckError):
        kc.verify_reply(frame, bytes(plain), tables, stamp=True)
    plain[24:32] = (100).to_bytes(8, "little")
    plain[32:40] = (101).to_bytes(8, "little")
    kc.verify_reply(frame, bytes(plain), tables, stamp=True)
    plain[32:40] = (99).to_bytes(8, "little")
    with pytest.raises(kc.CheckError):
        kc.verify_reply(frame, bytes(plain), tables, stamp=True)
    rejected_with_stamps = bytearray(rules.reply(injected, tables))
    rejected_with_stamps[24:40] = struct.pack("<QQ", 100, 101)
    with pytest.raises(kc.CheckError):
        kc.verify_reply(injected, bytes(rejected_with_stamps), tables, stamp=True)


def test_stamp_injection_is_refused_before_socket_send(contract, tables):
    class UnusedSocket:
        def sendall(self, _data):
            raise AssertionError("an injected frame reached :7161")

    injected = kc.build_cases(contract, tables, start_seq=330)[1].frame
    with pytest.raises(kc.CheckError):
        kc._roundtrip(UnusedSocket(), injected, tables, stamp=True)


def test_console_requires_each_reason_line_by_seq(contract, tables):
    cases = kc.build_cases(contract, tables, start_seq=400)
    lines = r2_console(cases).splitlines()
    kc.check_console("\n".join(lines), cases, require_liveness=True, require_summary=True)
    with pytest.raises(kc.CheckError):
        kc.check_console("\n".join(lines[1:]), cases, require_liveness=True, require_summary=True)
    with pytest.raises(kc.CheckError):
        kc.check_console("\n".join(lines[:-1]), cases, require_liveness=True, require_summary=True)
    too_many_lines = [line.replace("suppressed=53", "suppressed=52") for line in lines]
    with pytest.raises(kc.CheckError):
        kc.check_console("\n".join(too_many_lines), cases, require_liveness=True, require_summary=True)


class FakeMonitor:
    """Small spec-reading socket stand-in; it is deliberately independent of client I/O."""

    def __init__(self, path, tables):
        self.path, self.tables = path, tables
        self.frames = []
        self.keep_idle = False
        self.stamp_done = threading.Event()
        self.overlap = False
        self.cap = 11
        self.trailing = False
        self.path.write_text("monitor: vss rules: stand-in\n")
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.listeners = []
        self.threads = []
        self.ports = []
        for stamp in (False, True):
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))
            sock.listen()
            sock.settimeout(0.1)
            self.listeners.append(sock)
            self.ports.append(sock.getsockname()[1])
            thread = threading.Thread(target=self.serve, args=(sock, stamp), daemon=True)
            thread.start()
            self.threads.append(thread)

    def emit(self, line):
        with self.lock, self.path.open("a") as stream:
            stream.write("monitor: " + line + "\n")
            stream.flush()
        if line == "client done: seen=2 accepted=2 rejected=0":
            self.stamp_done.set()

    def serve(self, listener, stamp):
        missed = False
        while not self.stop.is_set():
            try:
                conn, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            seen = rejected = 0
            prev = 0
            lines = 0
            by_reason = {}
            last_seq = 0
            with conn:
                conn.settimeout(10 if self.keep_idle and not stamp else 0.5 if not stamp else 3)
                while not self.stop.is_set():
                    try:
                        data = bytearray()
                        while len(data) < 64:
                            part = conn.recv(64 - len(data))
                            if not part:
                                break
                            data.extend(part)
                        if not data:
                            break
                        if len(data) != 64:
                            break
                    except socket.timeout:
                        if not stamp and seen:
                            self.emit(f"LIVENESS MISS: no claim for 500 ms since seq={last_seq} (deadline 500 ms, miss 1)")
                            missed = True
                        break
                    request = bytes(data)
                    self.frames.append((stamp, request))
                    if not stamp and not self.stamp_done.is_set():
                        self.overlap = True
                    verdict, reason = rules.judge_frame(request, self.tables)
                    last_seq = kc.seq(request)
                    seen += 1
                    rejected += verdict
                    if missed:
                        self.emit(f"LIVENESS RESTORED: seq={last_seq} after 500 ms without a claim")
                        missed = False
                    if reason:
                        if reason != prev and lines < self.cap:
                            self.emit(f"REJECT seq={last_seq} kind=vss profile={request[17]} reason={rules.REASON_NAMES[reason]}")
                            lines += 1
                        else:
                            by_reason[reason] = by_reason.get(reason, 0) + 1
                    prev = reason
                    reply = bytearray(rules.reply(request, self.tables))
                    if stamp:
                        struct.pack_into("<QQ", reply, 24, 1000 + seen, 1001 + seen)
                    conn.sendall(reply + (b"EXTRA" if self.trailing and stamp and seen == 2 else b""))
                if by_reason:
                    desc = "".join(f" {key}={value}" for key, value in sorted(by_reason.items()))
                    self.emit(f"vss summary: seen={seen} rejected={rejected} suppressed={sum(by_reason.values())} by reason:{desc}")
                if seen:
                    self.emit(f"client done: seen={seen} accepted={seen - rejected} rejected={rejected}")

    def close(self):
        self.stop.set()
        for sock in self.listeners:
            sock.close()
        for thread in self.threads:
            thread.join(timeout=2)


def test_fake_monitor_campaign_and_console(tmp_path, contract, tables):
    console = tmp_path / "console.log"
    console.write_text("")
    fake = FakeMonitor(console, tables)
    try:
        cases = kc.run_campaign("127.0.0.1", fake.ports[0], fake.ports[1], contract, tables, console, flood_count=64, late_seconds=0.65)
        end = time.monotonic() + 2
        while True:
            try:
                kc.check_console(console.read_text(), cases, require_liveness=True, require_summary=True)
                break
            except kc.CheckError:
                if time.monotonic() > end:
                    raise
                time.sleep(0.01)
    finally:
        fake.close()


def test_cli_stamp_and_full_check(tmp_path, contract, tables):
    console = tmp_path / "console.log"
    console.write_text("")
    fake = FakeMonitor(console, tables)
    try:
        out = tmp_path / "out"
        cmd = [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-c",
            DOC_BOOT,
            str(Path(kc.__file__)),
            "--host",
            "127.0.0.1",
            "--contract",
            str(CONTRACT_PATH),
            "--svc-port",
            str(fake.ports[0]),
            "--stamp-port",
            str(fake.ports[1]),
            "--out",
            str(out),
            "--console",
            str(console),
            "--late-seconds",
            "0.65",
            "--guest-image-name",
            "ifs-vss.bin",
            "--guest-image-sha256",
            "0" * 64,
            "--check",
        ]
        run = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        assert run.returncode == 0, run.stdout + run.stderr
        assert "CHECK console each reason by seq PASS" in run.stdout
        assert json.loads((out / "result.json").read_text())["passed"] is True
        stamp = json.loads((out / "stamp.json").read_text())
        assert stamp["measured_timing"] is False and len(stamp["source_sha256"]) == 64
        assert "host" not in stamp and "hostname" not in stamp
        assert stamp["source_sha256"] == hashlib.sha256(Path(kc.__file__).read_bytes()).hexdigest()
        assert stamp["contract_sha256"] == hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest()
        assert stamp["rules_sha256"] == hashlib.sha256(Path(rules.__file__).read_bytes()).hexdigest()
        assert stamp["vssframe_sha256"] == hashlib.sha256(Path(vf.__file__).read_bytes()).hexdigest()
        assert stamp["guest_ifs"] == "ifs-vss.bin" and stamp["guest_ifs_sha256"] == "0" * 64
        assert stamp["guest_ifs_given"] is True
        assert stamp["kernel_release"] == platform.release()
        assert stamp["python_version"]
        private = [DOC_NODE, "127.0.0.1", str(console), "vss rules: stand-in"]
        record = (out / "stamp.json").read_text() + (out / "result.json").read_text()
        assert all(value not in record for value in private), "private value copied into record"
        if hasattr(os, "uname"):
            node_copied = os.uname().nodename in record
            assert not node_copied, "system node copied into record"
        assert all(stamp for stamp, _ in fake.frames[:2])
        assert not any(stamp for stamp, _ in fake.frames[2:])
        flood = [frame for stamp, frame in fake.frames[15:] if not stamp]
        assert len(flood) == 64 and all(frame[17] == 2 for frame in flood)
        assert [rules.judge_frame(frame, tables)[1] for frame in flood] == [23 if i % 2 == 0 else 24 for i in range(64)]
    finally:
        fake.close()


def test_check_without_console_names_unchecked_work(tmp_path, contract, tables):
    fake = FakeMonitor(tmp_path / "unread-console.log", tables)
    try:
        out = tmp_path / "out"
        cmd = [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-c",
            DOC_BOOT,
            str(Path(kc.__file__)),
            "--host",
            "127.0.0.1",
            "--contract",
            str(CONTRACT_PATH),
            "--svc-port",
            str(fake.ports[0]),
            "--stamp-port",
            str(fake.ports[1]),
            "--out",
            str(out),
            "--late-seconds",
            "0.65",
            "--guest-image-name",
            "ifs-vss.bin",
            "--guest-image-sha256",
            "0" * 64,
            "--check",
        ]
        run = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        assert run.returncode != 0
        assert "NOT CHECKED: guest console" in run.stdout
        assert json.loads((out / "result.json").read_text())["passed"] is False
        assert fake.frames == []
    finally:
        fake.close()


@pytest.mark.skipif(shutil.which("gcc") is None, reason="native PC monitor needs gcc")
def test_native_vss_monitor_campaign(tmp_path, contract, tables):
    """Real native C monitor, compiled from the frozen commit; never a QNX/board run."""
    import test_monitor_kind4 as native_tests
    import test_monitor_vss as build_info

    binary = native_tests._build(build_info._gcc(), build_info.GEN, tmp_path, names=("monitor",))["monitor"]
    console = tmp_path / "native-console.log"
    console.write_text("")
    lock = threading.Lock()
    processes = []
    pumps = []

    def unused_ports():
        with socket.socket() as first, socket.socket() as second:
            first.bind(("127.0.0.1", 0))
            second.bind(("127.0.0.1", 0))
            return first.getsockname()[1], second.getsockname()[1]

    def pump(stream, to_console):
        for line in iter(stream.readline, b""):
            if to_console:
                with lock, console.open("ab") as out:
                    out.write(line)
                    out.flush()

    svc_port, stamp_port = unused_ports()
    for args in ([str(svc_port), "svc", "500"], [str(stamp_port), "stamp"]):
        proc = subprocess.Popen([binary, *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        processes.append(proc)
        for stream, to_console in ((proc.stdout, True), (proc.stderr, False)):
            thread = threading.Thread(target=pump, args=(stream, to_console), daemon=True)
            thread.start()
            pumps.append(thread)
    try:
        end = time.monotonic() + 5
        while not all(f":{p}" in console.read_text() for p in (svc_port, stamp_port)):
            assert time.monotonic() < end, console.read_text()
            time.sleep(0.01)
        cases = kc.run_campaign("127.0.0.1", svc_port, stamp_port, contract, tables, console, flood_count=64, late_seconds=0.65)
        end = time.monotonic() + 3
        while True:
            try:
                kc.check_console(console.read_text(), cases, require_liveness=True, require_summary=True)
                break
            except kc.CheckError:
                if time.monotonic() > end:
                    raise
                time.sleep(0.01)
    finally:
        for proc in processes:
            proc.terminate()
        for proc in processes:
            proc.wait(timeout=5)
        for thread in pumps:
            thread.join(timeout=2)


def r2_console(cases, count=64):
    first = kc.seq(cases[0].frame) - 3
    lines = [
        "monitor: client done: seen=2 accepted=2 rejected=0",
        f"monitor: LIVENESS MISS: no claim for 500 ms since seq={first} (deadline 500 ms, miss 1)",
        "monitor: client done: seen=1 accepted=1 rejected=0",
        f"monitor: LIVENESS RESTORED: seq={first + 1} after 500 ms without a claim",
        "monitor: client done: seen=1 accepted=1 rejected=0",
    ]
    lines += [f"monitor: REJECT seq={kc.seq(c.frame)} kind=vss profile={c.profile} reason={rules.REASON_NAMES[c.reason]}" for c in cases if c.reason]
    lines.append("monitor: client done: seen=11 accepted=1 rejected=10")
    start = kc.seq(cases[-1].frame) + 1
    lines += [f"monitor: REJECT seq={start + i} kind=vss profile=2 reason={rules.REASON_NAMES[23 if i % 2 == 0 else 24]}" for i in range(11)]
    counts = {23: 0, 24: 0}
    for i in range(11, count):
        counts[23 if i % 2 == 0 else 24] += 1
    lines += [
        f"monitor: vss summary: seen={count} rejected={count} suppressed={count - 11} by reason: 23={counts[23]} 24={counts[24]}",
        f"monitor: client done: seen={count} accepted=0 rejected={count}",
    ]
    return "\n".join(lines) + "\n"


@pytest.mark.parametrize(
    "damage",
    [
        "miss",
        "restore",
        "wrong-miss",
        "wrong-restore",
        "restored-first",
        "reversed-live",
        "duplicate-miss",
        "duplicate-restore",
        "done-stamp",
        "done-idle",
        "done-flood",
        "done-bad",
        "accept-reject",
        "cap10",
        "summary-sum",
        "summary-zero",
        "summary-foreign",
        "summary-seen",
        "flood-profile",
        "flood-reason",
        "flood-missing",
        "flood-duplicate",
        "reason-name",
        "reason-profile",
        "reason-duplicate",
    ],
)
def test_r2_console_rejects_missing_or_false_evidence(contract, tables, damage):
    cases = kc.build_cases(contract, tables, start_seq=1000)
    text = r2_console(cases)
    lines = text.splitlines()
    first = kc.seq(cases[0].frame) - 3
    if damage == "miss":
        lines = [x for x in lines if "LIVENESS MISS" not in x]
    elif damage == "restore":
        lines = [x for x in lines if "RESTORED" not in x]
    elif damage == "wrong-miss":
        lines = [x.replace(f"since seq={first}", "since seq=1") for x in lines]
    elif damage == "wrong-restore":
        lines = [x.replace(f"RESTORED: seq={first + 1}", "RESTORED: seq=1") for x in lines]
    elif damage == "restored-first":
        lines = [x.replace(f"RESTORED: seq={first + 1}", f"RESTORED: seq={first}") for x in lines]
    elif damage == "reversed-live":
        lines[1], lines[3] = lines[3], lines[1]
    elif damage == "duplicate-miss":
        lines.append(lines[1])
    elif damage == "duplicate-restore":
        lines.append(lines[3])
    elif damage == "done-stamp":
        lines = [x for x in lines if "seen=2 accepted=2" not in x]
    elif damage == "done-idle":
        lines.remove("monitor: client done: seen=1 accepted=1 rejected=0")
    elif damage == "done-flood":
        lines = [x for x in lines if "seen=64 accepted=0" not in x]
    elif damage == "done-bad":
        lines = [x.replace("seen=11 accepted=1 rejected=10", "seen=11 accepted=0 rejected=11") for x in lines]
    elif damage == "accept-reject":
        lines.append(f"monitor: REJECT seq={kc.seq(cases[0].frame)} kind=vss profile=1 reason=vss-speed")
    elif damage == "cap10":
        lines = [x.replace("suppressed=53", "suppressed=54").replace("24=27", "24=28") for x in lines]
    elif damage == "summary-sum":
        lines = [x.replace("24=27", "24=26") for x in lines]
    elif damage == "summary-zero":
        lines = [
            x.replace("seen=64 rejected=64 suppressed=53 by reason: 23=26 24=27", "seen=11 rejected=11 suppressed=0 by reason: 23=0 24=0")
            for x in lines
        ]
    elif damage == "summary-foreign":
        lines = [x.replace("23=26", "25=26") for x in lines]
    elif damage == "summary-seen":
        lines = [x.replace("seen=64 rejected=64", "seen=65 rejected=64") for x in lines]
    elif damage.startswith("flood-"):
        i = next(i for i, x in enumerate(lines) if "profile=2 reason=vss-speed" in x)
        if damage == "flood-profile":
            lines[i] = lines[i].replace("profile=2", "profile=1")
        elif damage == "flood-reason":
            lines[i] = lines[i].replace("vss-speed", "vss-steer")
        elif damage == "flood-missing":
            lines.pop(i)
        else:
            lines.append(lines[i])
    else:
        i = next(i for i, x in enumerate(lines) if "reason=profile-unbound" in x)
        if damage == "reason-name":
            lines[i] = lines[i].replace("profile-unbound", "vss-speed")
        elif damage == "reason-profile":
            lines[i] = lines[i].replace("profile=0", "profile=1")
        else:
            lines.append(lines[i])
    with pytest.raises(kc.CheckError):
        kc.check_console("\n".join(lines), cases, require_liveness=True, require_summary=True)


@pytest.mark.parametrize("damage", ["miss", "restore", "summary", "stamp-total", "flood-lines", "stale", "cap10", "accept-reject"])
def test_r2_command_fails_on_bad_console(tmp_path, contract, tables, damage):
    console = tmp_path / "console.log"
    fake = FakeMonitor(console, tables)
    emit = fake.emit

    def corrupt(line):
        if damage == "miss" and "LIVENESS MISS" in line:
            return
        if damage == "restore" and "RESTORED" in line:
            return
        if damage == "summary" and "vss summary:" in line:
            return
        if damage == "stamp-total" and "seen=2 accepted=2" in line:
            return
        if damage == "flood-lines" and "profile=2 reason=" in line:
            return
        if damage == "stale" and (("client done:" in line and "seen=2 accepted=2" not in line) or "vss summary:" in line):
            return
        if damage == "accept-reject" and "seen=11 accepted=1" in line:
            emit(f"REJECT seq={kc.seq(fake.frames[4][1])} kind=vss profile=1 reason=vss-speed")
        emit(line)
        if damage == "miss" and "seen=64 accepted=0" in line:
            emit(f"LIVENESS MISS: no claim for 500 ms since seq={kc.seq(fake.frames[-1][1])} (deadline 500 ms, miss 2)")

    fake.emit = corrupt
    if damage == "cap10":
        fake.cap = 10
    if damage == "stale":
        old = r2_console(kc.build_cases(contract, tables)).splitlines()
        with console.open("a") as stream:
            stream.write("\n".join(x for x in old if ("client done:" in x and "seen=2 accepted=2" not in x) or "vss summary:" in x) + "\n")
    try:
        out = tmp_path / "out"
        cmd = [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-c",
            DOC_BOOT,
            str(Path(kc.__file__)),
            "--host",
            "127.0.0.1",
            "--contract",
            str(CONTRACT_PATH),
            "--svc-port",
            str(fake.ports[0]),
            "--stamp-port",
            str(fake.ports[1]),
            "--out",
            str(out),
            "--console",
            str(console),
            "--late-seconds",
            "0.65",
            "--check",
            "--guest-image-name",
            "ifs-vss.bin",
            "--guest-image-sha256",
            "0" * 64,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
        assert result.returncode != 0
        assert "FAIL:" in result.stdout
        assert not json.loads((out / "result.json").read_text())["passed"]
        assert "Traceback" not in result.stderr
    finally:
        fake.close()


def argv_for(out, console=None, contract=CONTRACT_PATH):
    args = [
        "--host",
        "127.0.0.1",
        "--contract",
        str(contract),
        "--out",
        str(out),
        "--guest-image-name",
        "ifs-vss.bin",
        "--guest-image-sha256",
        "0" * 64,
    ]
    return args + (["--console", str(console)] if console else [])


@pytest.mark.parametrize(
    "damage",
    ["no-console", "no-banner", "garbled-banner", "wrong-contract-name", "equal-ports", "out-exists", "bad-contract", "image-path", "image-hash"],
)
def test_r2_preflight_refuses_before_any_frame(tmp_path, monkeypatch, contract, damage, capsys):
    calls = []

    def forbid(*a, **kw):
        calls.append((a, kw))
        return None

    monkeypatch.setattr(kc, "_connect", forbid)
    out = tmp_path / "out"
    console = tmp_path / "console.log"
    console.write_text("monitor: vss rules: stand-in\n")
    args = argv_for(out, console)
    if damage == "no-console":
        args = argv_for(out)
    elif damage == "no-banner":
        console.write_text("")
    elif damage == "garbled-banner":
        console.write_text("xx monitor: vss rules: stand-in\n")
    elif damage == "wrong-contract-name":
        other = tmp_path / "comment.py"
        shutil.copyfile(CONTRACT_PATH, other)
        shutil.copyfile(CONTRACT_PATH, tmp_path / "vss_contract.py")
        args = argv_for(out, console, other)
    elif damage == "equal-ports":
        args += ["--svc-port", "7160", "--stamp-port", "7160"]
    elif damage == "out-exists":
        out.mkdir()
        (out / "result.json").write_text('{"passed": true}')
    elif damage == "bad-contract":
        cdir = tmp_path / "broken"
        cdir.mkdir()
        cpath = cdir / "vss_contract.py"
        cpath.write_text("# invalid\n")
        args = argv_for(out, console, cpath)
    elif damage == "image-path":
        args[args.index("--guest-image-name") + 1] = "dir/ifs-vss.bin"
    elif damage == "image-hash":
        args[args.index("--guest-image-sha256") + 1] = "0" * 16
    before = (out / "result.json").read_bytes() if damage == "out-exists" else None
    assert kc.main(args + ["--check"]) != 0
    assert calls == []
    if before is not None:
        assert (out / "result.json").read_bytes() == before
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err and "CHECK preflight FAIL:" in captured.out
    assert "late connect PASS" not in captured.out
    refusals = {
        "no-console": "CheckWithoutConsole", "no-banner": "NoVssAnnouncement", "garbled-banner": "NoVssAnnouncement",
        "wrong-contract-name": "ContractName", "equal-ports": "PortsInvalid", "out-exists": "OutputExists",
        "image-path": "ImageIdentity", "image-hash": "ImageIdentity",
    }
    if damage in refusals:
        assert "CHECK preflight FAIL: " + refusals[damage] in captured.out


@pytest.mark.parametrize("setting", ["late", "flood", "ports"])
def test_r2_campaign_invalid_settings_send_nothing(contract, tables, monkeypatch, setting):
    monkeypatch.setattr(kc, "_connect", lambda *a, **kw: pytest.fail("connect before refusal"))
    kw = {"late_seconds": 0.1} if setting == "late" else {"flood_count": 23} if setting == "flood" else {}
    with pytest.raises(kc.PortsInvalid if setting == "ports" else kc.CampaignBounds):
        kc.run_campaign("127.0.0.1", 7160, 7160 if setting == "ports" else 7161, contract, tables, None, **kw)


def test_r2_socket_timeouts_are_explicit(monkeypatch):
    calls = []

    class Conn:
        def settimeout(self, value):
            calls.append(("recv", value))

        def setsockopt(self, *a):
            pass

    def connect(address, timeout):
        calls.append(("connect", timeout))
        return Conn()

    monkeypatch.setattr(kc.socket, "create_connection", connect)
    kc._connect("127.0.0.1", 7160)
    assert calls == [("connect", 5), ("recv", 3)]


def test_r2_stamp_layout_guard_precedes_send(contract, tables):
    frame = bytearray(kc.build_cases(contract, tables)[0].frame)
    frame[22] = 1

    class Forbidden:
        def sendall(self, _):
            pytest.fail("layout injection sent")

    with pytest.raises(kc.CheckError):
        kc._roundtrip(Forbidden(), bytes(frame), tables, stamp=True)


def test_r2_wait_for_appended_console_evidence(tmp_path, contract, tables):
    path = tmp_path / "console.log"
    path.write_text("")
    cases = kc.build_cases(contract, tables, start_seq=3000)

    def append():
        time.sleep(0.08)
        path.write_text(r2_console(cases))

    thread = threading.Thread(target=append)
    thread.start()
    try:
        kc._wait_console(path, 0, cases, 64, "flood")
    finally:
        thread.join()


def test_r2_console_mark_discards_earlier_evidence(tmp_path, contract, tables):
    path = tmp_path / "console.log"
    cases = kc.build_cases(contract, tables, start_seq=4000)
    old = r2_console(cases).encode()
    path.write_bytes(old + b"new run has no evidence\n")
    with pytest.raises(kc.CheckError):
        kc.check_console(kc._console(path, len(old)), cases, True, True)


def test_r2_fresh_console_refusal_and_late_wait(tmp_path, contract, tables, monkeypatch):
    console = tmp_path / "console.log"
    fake = FakeMonitor(console, tables)
    console.write_text(console.read_text() + "monitor: LIVENESS MISS: stale\n")
    try:
        with pytest.raises(kc.EarlierLiveness):
            kc.run_campaign("127.0.0.1", fake.ports[0], fake.ports[1], contract, tables, console)
        assert fake.frames == []
        console.write_text("monitor: vss rules: stand-in\n")
        original_sleep = time.sleep
        waits = []

        def sleep(seconds):
            waits.append(seconds)
            if seconds == 0.65:
                fake.emit("LIVENESS MISS: appeared during late wait")
            original_sleep(seconds)

        monkeypatch.setattr(kc.time, "sleep", sleep)
        with pytest.raises(kc.EarlierLiveness):
            kc.run_campaign("127.0.0.1", fake.ports[0], fake.ports[1], contract, tables, console, late_seconds=0.65)
        assert 0.65 in waits
        assert not any(not stamp for stamp, _ in fake.frames)
    finally:
        fake.close()


def test_r2_new_sequence_numbers_each_run(tmp_path, contract, tables):
    path = tmp_path / "console.log"
    runs = []
    for _i in range(2):
        fake = FakeMonitor(path, tables)
        try:
            cases = kc.run_campaign("127.0.0.1", *fake.ports, contract, tables, path, late_seconds=0.65)
            runs.append({kc.seq(case.frame) for case in cases})
        finally:
            fake.close()
    assert runs[0].isdisjoint(runs[1])


def test_r2_no_exception_text_or_silent_steps(tmp_path, contract, capsys):
    console = tmp_path / "console.log"
    console.write_text("monitor: vss rules: stand-in\n")
    out = tmp_path / "out"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    rc = kc.main(argv_for(out, console) + ["--stamp-port", str(port), "--check"])
    assert rc != 0
    text = capsys.readouterr().out
    assert "stamp t_in/t_out and honest-only FAIL: ConnectionRefusedError" in text
    assert "console MISS and RESTORED NOT RUN" in text
    result = (out / "result.json").read_text()
    assert str(console) not in result and "Connection refused" not in result


def test_r2_zero_suppression_extra_summary_is_refused(contract, tables):
    cases = kc.build_cases(contract, tables)
    text = r2_console(cases) + "monitor: vss summary: seen=11 rejected=11 suppressed=0 by reason: 23=0 24=0\n"
    with pytest.raises(kc.CheckError):
        kc.check_console(text, cases, True, True)


def test_r2_idle_connection_must_really_close(tmp_path, contract, tables):
    console = tmp_path / "console.log"
    fake = FakeMonitor(console, tables)
    fake.keep_idle = True
    started = time.monotonic()
    try:
        with pytest.raises((TimeoutError, kc.CheckError)):
            kc.run_campaign("127.0.0.1", *fake.ports, contract, tables, console, late_seconds=0.65)
        assert time.monotonic() - started < 6
    finally:
        fake.close()


def test_r2_stamp_done_precedes_first_svc_frame(tmp_path, contract, tables):
    console = tmp_path / "console.log"
    fake = FakeMonitor(console, tables)
    emit = fake.emit

    def delayed(line):
        if line == "client done: seen=2 accepted=2 rejected=0":
            threading.Timer(0.9, lambda: emit(line)).start()
            return
        emit(line)

    fake.emit = delayed
    try:
        kc.run_campaign("127.0.0.1", *fake.ports, contract, tables, console, late_seconds=0.65)
        assert not fake.overlap
    finally:
        fake.close()


def test_r2_last_reply_trailing_bytes_are_refused(tmp_path, contract, tables):
    fake = FakeMonitor(tmp_path / "console.log", tables)
    fake.trailing = True
    try:
        with pytest.raises(kc.CheckError):
            kc.run_campaign("127.0.0.1", *fake.ports, contract, tables, fake.path, late_seconds=0.65)
    finally:
        fake.close()


def test_r2_reply_has_one_total_deadline(contract, tables, monkeypatch):
    ticks = iter([0.0, 1.0, 2.0, 3.0])
    monkeypatch.setattr(kc.time, "monotonic", lambda: next(ticks))

    class Trickle:
        def sendall(self, _):
            pass

        def settimeout(self, _):
            pass

        def recv(self, _):
            return b"\0"

    with pytest.raises(TimeoutError):
        kc._roundtrip(Trickle(), kc.build_cases(contract, tables)[0].frame, tables)


@pytest.mark.parametrize("damage", ["accepted-other-kind", "accepted-garbled", "flood-garbled-duplicate", "reason-garbled-duplicate"])
def test_r2_raw_reject_conflicts_cannot_be_ignored(contract, tables, damage):
    cases = kc.build_cases(contract, tables, start_seq=1000)
    text = r2_console(cases)
    if damage == "accepted-other-kind":
        extra = f"monitor: REJECT seq={kc.seq(cases[0].frame)} kind=mnist reason=confidence-low"
    elif damage == "accepted-garbled":
        extra = f"monitor: REJECT seq={kc.seq(cases[0].frame)} garbled"
    elif damage == "flood-garbled-duplicate":
        extra = f"monitor: REJECT seq={kc.seq(cases[-1].frame) + 1} garbled"
    else:
        extra = f"monitor: REJECT seq={kc.seq(cases[1].frame)} kind=vss profile=0 reason="
    with pytest.raises(kc.CheckError):
        kc.check_console(text + extra + "\n", cases, True, True)


def test_r3_command_without_console_cannot_pass(tmp_path, contract, tables, capsys):
    fake = FakeMonitor(tmp_path / "unread.log", tables)
    try:
        out = tmp_path / "out"
        rc = kc.main(argv_for(out) + ["--svc-port", str(fake.ports[0]), "--stamp-port", str(fake.ports[1]), "--late-seconds", "0.65"])
        text = capsys.readouterr().out
        assert "CHECK late connect NOT RUN" in text and "CHECK late connect PASS" not in text
        assert not json.loads((out / "result.json").read_text())["passed"]
        assert "NOT CHECKED: guest console" in text
        assert "NOT JUDGED: no campaign verdict" in text
        assert rc != 0
        assert len(fake.frames) == 79
    finally:
        fake.close()


def test_r3_no_console_settle_precedes_svc(tmp_path, contract, tables, monkeypatch):
    fake = FakeMonitor(tmp_path / "console.log", tables)
    waits = []
    connect = kc._connect
    sleep = time.sleep

    def recording_sleep(seconds):
        # kc.time is the time module itself, so this stands in for every thread's sleep: daemon threads an earlier
        # test module left (the bridge and connector tests sleep 0.002 s in loops) would land in waits first
        if threading.current_thread() is threading.main_thread():
            waits.append(seconds)
        sleep(seconds)

    def recording_connect(host, port):
        if port == fake.ports[0]:
            assert waits[:2] == [0.1, 0.65]
        return connect(host, port)

    monkeypatch.setattr(kc.time, "sleep", recording_sleep)
    monkeypatch.setattr(kc, "_connect", recording_connect)
    try:
        kc.run_campaign("127.0.0.1", *fake.ports, contract, tables, None, late_seconds=0.65)
    finally:
        fake.close()


@pytest.mark.parametrize("which", ["idle", "restore", "stamp-first", "stamp-second"])
def test_r3_all_accepted_sequences_refuse_reject(contract, tables, which):
    cases = kc.build_cases(contract, tables, start_seq=7000)
    first = kc.seq(cases[0].frame) - 3
    stamp = kc.seq(cases[-1].frame) + 65
    number = {"idle": first, "restore": first + 1, "stamp-first": stamp, "stamp-second": stamp + 1}[which]
    text = r2_console(cases) + f"monitor: REJECT seq={number} kind=vss profile=1 reason=speed\n"
    with pytest.raises(kc.CheckError):
        kc.check_console(text, cases, True, True)


@pytest.mark.parametrize(
    "damage",
    ["extra-done", "wrong-restore-beside-right", "duplicate-flood", "duplicate-reason", "reject-tail", "done-prefix", "merged-reject"],
)
def test_r3_console_conflicts(contract, tables, damage):
    cases = kc.build_cases(contract, tables, start_seq=7000)
    text = r2_console(cases)
    first = kc.seq(cases[0].frame) - 3
    start = kc.seq(cases[-1].frame) + 1
    if damage == "extra-done":
        text += "monitor: client done: seen=0 accepted=0 rejected=0\n"
    elif damage == "wrong-restore-beside-right":
        text += f"monitor: LIVENESS RESTORED: seq={first} after 500 ms without a claim\n"
    elif damage == "duplicate-flood":
        text = text.replace(f"seq={start + 2} kind=vss", f"seq={start} kind=vss")
    elif damage == "duplicate-reason":
        text = text.replace("23=26 24=27", "23=13 23=13 24=27")
    elif damage == "reject-tail":
        text = text.replace("profile=0 reason=profile-unbound\n", "profile=0 reason=profile-unbound extra\n")
    elif damage == "done-prefix":
        text = text.replace("monitor: client done: seen=11", "xx monitor: client done: seen=11")
    else:
        text += f"monitor: REJECT seq=1 kind=other monitor: REJECT seq={kc.seq(cases[0].frame)} garbled\n"
    with pytest.raises(kc.CheckError):
        kc.check_console(text, cases, True, True)


def test_r3_console_shrink_is_refused(tmp_path):
    path = tmp_path / "console.log"
    path.write_bytes(b"new")
    with pytest.raises(kc.CheckError):
        kc._console(path, 8)


def test_r3_duplicate_stamp_done_stops_before_svc(tmp_path, contract, tables, monkeypatch):
    fake = FakeMonitor(tmp_path / "console.log", tables)
    emit = fake.emit

    def twice(line):
        emit(line)
        if line == "client done: seen=2 accepted=2 rejected=0":
            emit(line)

    fake.emit = twice
    monkeypatch.setattr(kc, "CONSOLE_WAIT", 0.15)
    try:
        with pytest.raises(kc.CheckError):
            kc.run_campaign("127.0.0.1", *fake.ports, contract, tables, fake.path)
        assert len(fake.frames) == 2 and all(stamp for stamp, _ in fake.frames)
    finally:
        fake.close()


def test_r3_old_stamp_done_does_not_replace_this_run(tmp_path, contract, tables):
    fake = FakeMonitor(tmp_path / "console.log", tables)
    fake.emit("client done: seen=2 accepted=2 rejected=0")
    fake.stamp_done.clear()
    emit = fake.emit

    def delayed_capture(line):
        if line == "client done: seen=2 accepted=2 rejected=0":
            threading.Timer(0.9, lambda: emit(line)).start()
        else:
            emit(line)

    fake.emit = delayed_capture
    try:
        kc.run_campaign("127.0.0.1", *fake.ports, contract, tables, fake.path, late_seconds=0.65)
        assert not fake.overlap
    finally:
        fake.close()


def test_r3_campaign_connect_failure_names_accept(tmp_path, contract, tables, monkeypatch):
    fake = FakeMonitor(tmp_path / "console.log", tables)
    connect = kc._connect
    svc_calls = 0

    def fail_campaign(host, port):
        nonlocal svc_calls
        if port == fake.ports[0]:
            svc_calls += 1
            if svc_calls == 3:
                raise ConnectionRefusedError()
        return connect(host, port)

    steps = kc.Steps()
    monkeypatch.setattr(kc, "_connect", fail_campaign)
    try:
        with pytest.raises(ConnectionRefusedError) as exc:
            kc.run_campaign("127.0.0.1", *fake.ports, contract, tables, fake.path, late_seconds=0.65, steps=steps)
        steps.failed(exc.value)
        assert "restore reply PASS" in steps.lines()
        assert "reply accept FAIL: ConnectionRefusedError" in steps.lines()
    finally:
        fake.close()


def test_r3_command_interrupt_writes_failure(tmp_path, contract, monkeypatch, capsys):
    console = tmp_path / "console.log"
    console.write_text("monitor: vss rules: stand-in\n")

    def interrupted(*args, **kwargs):
        kwargs["steps"].enter("restore reply")
        raise KeyboardInterrupt()

    monkeypatch.setattr(kc, "run_campaign", interrupted)
    out = tmp_path / "out"
    try:
        code = kc.main(argv_for(out, console) + ["--check"])
    except KeyboardInterrupt:
        pytest.fail("the command leaked KeyboardInterrupt instead of writing its failure")
    assert code == 1
    captured = capsys.readouterr()
    assert "restore reply FAIL: KeyboardInterrupt" in captured.out
    assert captured.err == ""
    assert not json.loads((out / "result.json").read_text())["passed"]


@pytest.mark.parametrize(
    "damage,refusal",
    [("check", "CheckWithoutConsole"), ("ports", "PortsInvalid"), ("bounds", "CampaignBounds"),
     ("image", "ImageIdentity"), ("banner", "NoVssAnnouncement"), ("stale", "EarlierLiveness")],
)
def test_r3_preflight_refusal_type_is_actionable(tmp_path, contract, monkeypatch, capsys, damage, refusal):
    console = tmp_path / "console.log"
    console.write_text("monitor: vss rules: stand-in\n")
    args = argv_for(tmp_path / "out", console)
    if damage == "check":
        args = argv_for(tmp_path / "out") + ["--check"]
    elif damage == "ports":
        args += ["--svc-port", "0"]
    elif damage == "bounds":
        args += ["--flood-count", "23"]
    elif damage == "image":
        args[args.index("--guest-image-name") + 1] = "dir/image.bin"
    elif damage == "banner":
        console.write_text("unrelated\n")
    else:
        console.write_text(console.read_text() + "monitor: LIVENESS MISS: stale\n")
    calls = []
    monkeypatch.setattr(kc, "_connect", lambda *a: calls.append(a))
    assert kc.main(args) == 1
    assert calls == []
    assert "CHECK preflight FAIL: " + refusal in capsys.readouterr().out


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX SIGINT sent only to the private local child")
def test_r3_real_sigint_command(tmp_path, contract, tables):
    import signal

    fake = FakeMonitor(tmp_path / "console.log", tables)
    out = tmp_path / "out"
    args = argv_for(out, fake.path) + ["--svc-port", str(fake.ports[0]), "--stamp-port", str(fake.ports[1]), "--late-seconds", "4", "--check"]
    process = subprocess.Popen(
        [sys.executable, "-I", "-S", "-B", "-c", DOC_BOOT, kc.__file__, *args],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        end = time.monotonic() + 5
        while len(fake.frames) < 2:
            assert time.monotonic() < end
            time.sleep(0.01)
        time.sleep(0.25)
        process.send_signal(signal.SIGINT)
        stdout, stderr = process.communicate(timeout=5)
        assert process.returncode == 1 and stderr == ""
        assert "FAIL: KeyboardInterrupt" in stdout
        assert not json.loads((out / "result.json").read_text())["passed"]
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        fake.close()


def test_r3_reply_receive_hang_has_a_socket_deadline(contract, tables):
    client, peer = socket.socketpair()
    release = threading.Event()

    def silent_peer():
        try:
            peer.recv(64)
            release.wait(4.2)  # longer than the client's total reply deadline; no bytes sent
        finally:
            peer.close()

    thread = threading.Thread(target=silent_peer)
    thread.start()
    try:
        client.settimeout(3)
        with pytest.raises(TimeoutError):
            kc._roundtrip(client, kc.build_cases(contract, tables)[0].frame, tables)
    finally:
        release.set()
        client.close()
        thread.join(timeout=5)


def test_r3_judged_pass_without_check_flag_exits_zero_and_is_not_called_unjudged(tmp_path, contract, tables, capsys):
    fake = FakeMonitor(tmp_path / "console.log", tables)
    try:
        out = tmp_path / "out"
        rc = kc.main(argv_for(out, fake.path) + ["--svc-port", str(fake.ports[0]), "--stamp-port", str(fake.ports[1]), "--late-seconds", "0.65"])
        text = capsys.readouterr().out
        assert rc == 0 and json.loads((out / "result.json").read_text())["passed"] is True
        assert "NOT JUDGED" not in text and "NOT CHECKED" not in text
    finally:
        fake.close()


@pytest.mark.skipif(sys.platform == "win32", reason="on Windows a path under a file is refused as an existing file")
def test_r3_out_under_a_file_is_not_called_an_existing_output(tmp_path, monkeypatch, contract, capsys):
    calls = []
    monkeypatch.setattr(kc, "_connect", lambda *a: calls.append(a))
    (tmp_path / "afile").write_text("x")
    console = tmp_path / "console.log"
    console.write_text("monitor: vss rules: stand-in\n")
    assert kc.main(argv_for(tmp_path / "afile" / "out", console) + ["--check"]) == 1
    text = capsys.readouterr().out
    assert calls == [] and "CHECK preflight FAIL: NotADirectoryError" in text and "OutputExists" not in text


def test_r3_a_whole_reply_leaves_the_socket_its_three_seconds(contract, tables):
    frame = kc.build_cases(contract, tables)[0].frame
    client, peer = socket.socketpair()
    try:
        peer.sendall(rules.reply(frame, tables))
        client.settimeout(3)
        kc._roundtrip(client, frame, tables)
        assert client.gettimeout() == 3
    finally:
        client.close()
        peer.close()
