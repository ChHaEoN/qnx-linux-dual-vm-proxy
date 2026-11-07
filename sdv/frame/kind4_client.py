"""Phase 2 step 5's synthetic kind-4 client (no timing claim).

Copy this plain Python file beside vssframe.py and rules.py. Supply the generated
vss_contract.py by path. Nothing here imports a board package or a container.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import platform
from collections import Counter
import socket
import struct
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import rules  # type: ignore[import-not-found]  # noqa: E402
import vssframe as vf  # type: ignore[import-not-found]  # noqa: E402


class CheckError(RuntimeError):
    """One expected reply or console fact was missing or different."""


class CheckWithoutConsole(CheckError):
    """Preflight refusal: a judged run needs console evidence."""

class ContractName(CheckError):
    """Preflight refusal: use the generated contract filename."""

class PortsInvalid(CheckError):
    """Preflight refusal: use distinct valid endpoints."""

class CampaignBounds(CheckError):
    """Preflight refusal: campaign settings are below the floors."""

class ImageIdentity(CheckError):
    """Preflight refusal: supply a bare image name and a SHA256."""

class NoVssAnnouncement(CheckError):
    """Preflight refusal: the console lacks the image announcement."""

class EarlierLiveness(CheckError):
    """Preflight refusal: the campaign needs a fresh boot."""

class OutputExists(CheckError):
    """Preflight refusal: an earlier output must be preserved."""

@dataclass(frozen=True)
class Case:
    name: str
    frame: bytes
    profile: int
    reason: int


def seq(frame: bytes) -> int:
    return struct.unpack_from("<Q", frame)[0]


def _claim(number: int, contract: Any, profile: int = 1, **kw: Any) -> bytes:
    return vf.encode(vf.Claim(seq=number, tstamp_ns=time.monotonic_ns(), profile=profile, **kw), contract)


def build_cases(contract: Any, tables: rules.Tables, start_seq: int = 100) -> List[Case]:
    """One ACCEPT followed by the ten first-failure reasons, all with unique sequence numbers.

    The order 8,9,10,21..27 avoids the same-reason suppression rule. The caller
    sends these about 120 ms apart, below the 500 ms svc deadline. Ten rejects
    in this fresh session cannot reach the cap of eleven, even without a gap.
    """
    n = start_seq

    def make(name: str, reason: int, frame: bytes, profile: int = 1) -> Case:
        if rules.judge_frame(frame, tables) != (int(reason != 0), reason):
            raise CheckError("case %s does not have reason %d under the generated table" % (name, reason))
        return Case(name, frame, profile, reason)

    cases = [make("accept", 0, _claim(n, contract, v=5.0, a_x=0.0, delta=0.0, psi_dot=0.0, gear=1))]
    n += 1
    cases.append(make("profile", 8, _claim(n, contract, profile=0, v=5.0), 0))
    n += 1
    nan = vf.pack_bits(n, time.monotonic_ns(), 1, contract.CATALOG_DIGEST, (0x7FC00000, None, None, None), None, 0)
    cases.append(make("nonfinite", 9, nan))
    n += 1
    invalid = bytearray(_claim(n, contract, v=5.0))
    invalid[vf.FRAME_HEADER_BYTES + vf.P_RESERVED] = 1
    cases.append(make("reserved", 10, bytes(invalid)))
    n += 1
    cases.append(make("catalog", 21, vf.encode(vf.Claim(n, time.monotonic_ns(), 1, v=5.0, digest=contract.CATALOG_DIGEST ^ 1), contract)))
    n += 1
    cases.append(make("stale", 22, _claim(n, contract, v=5.0, age_ms=tables.age_max_ms + 1)))
    n += 1
    cases.append(make("speed", 23, _claim(n, contract, v=41.0)))
    n += 1
    cases.append(make("accel", 24, _claim(n, contract, v=5.0, a_x=11.0)))
    n += 1
    cases.append(make("steer", 25, _claim(n, contract, v=5.0, delta=41.0)))
    n += 1
    cases.append(make("yaw", 26, _claim(n, contract, v=5.0, delta=20.0, psi_dot=0.0)))
    n += 1
    cases.append(make("gear", 27, _claim(n, contract, v=-2.0, gear=1)))
    return cases


def verify_reply(frame: bytes, received: bytes, tables: rules.Tables, stamp: bool = False) -> None:
    """Compare every byte the monitor may not change, plus the exact verdict.

    The stamp port accepts honest ACCEPT claims only. This guard runs before a
    network call too; it refuses an injection aimed at :7161 in this client.
    """
    if len(frame) != vf.FRAME_TOTAL_BYTES or len(received) != vf.FRAME_TOTAL_BYTES:
        raise CheckError("reply length differs from 64 bytes")
    expected = rules.reply(frame, tables)
    if stamp:
        if vf.layout_errors(frame) or rules.judge_frame(frame, tables) != (0, 0):
            raise CheckError("stamp port accepts honest kind 4 claims only")
        got = bytearray(received)
        t_in, t_out = struct.unpack_from("<QQ", got, vf.FRAME_HEADER_BYTES + vf.P_T_IN)
        if not (0 < t_in <= t_out):
            raise CheckError("stamp reply lacks ordered t_in and t_out")
        got[vf.FRAME_HEADER_BYTES + vf.P_T_IN : vf.FRAME_HEADER_BYTES + vf.P_T_OUT + 8] = b"\0" * 16
        if bytes(got) != expected:
            raise CheckError("stamp reply changes another byte or its verdict")
    elif received != expected:
        raise CheckError("reply differs from the reference judge's exact 64 bytes")


REJECT = re.compile(r"monitor: REJECT seq=(\d+) kind=vss profile=(\d+) reason=([a-z-]+)")
RAW_REJECT = re.compile(r"monitor: REJECT seq=(\d+)")
DONE = re.compile(r"monitor: client done: seen=(\d+) accepted=(\d+) rejected=(\d+)")
SUMMARY = re.compile(r"monitor: vss summary: seen=(\d+) rejected=(\d+) suppressed=(\d+) by reason:((?: \d+=\d+)*)")
MISS = re.compile(r"monitor: LIVENESS MISS: no claim for \d+ ms since seq=(\d+) \(.*\)")
RESTORED = re.compile(r"monitor: LIVENESS RESTORED: seq=(\d+) after .+")
CONSOLE_WAIT = 3.0
STAMP_SETTLE = 0.1


def check_console(
    text: str, cases: Sequence[Case], require_liveness: bool, require_summary: bool, flood_count: int = 64, only: Optional[str] = None
) -> None:
    """Judge appended console lines against this run's unique sequence numbers."""
    lines = [line.replace("\0", "").replace("\r", "") for line in text.splitlines()]
    rejects = [m for line in lines if (m := REJECT.fullmatch(line))]
    raw_rejects = [(int(m.group(1)), line) for line in lines for m in RAW_REJECT.finditer(line)]
    first = seq(cases[0].frame) - 3
    flood_start = seq(cases[-1].frame) + 1
    accepted = {first, first + 1, seq(cases[0].frame), flood_start + flood_count, flood_start + flood_count + 1}
    if only in (None, "reasons"):
        if any(number in accepted for number, _ in raw_rejects):
            raise CheckError("accepted claim has a REJECT line")
        for case in cases:
            if not case.reason:
                continue
            raw_matches = [line for number, line in raw_rejects if number == seq(case.frame)]
            matches = [m for line in raw_matches if (m := REJECT.fullmatch(line))]
            if len(matches) != len(raw_matches):
                raise CheckError("garbled reason evidence")
            if len(matches) != 1 or int(matches[0].group(2)) != case.profile or matches[0].group(3) != rules.REASON_NAMES[case.reason]:
                raise CheckError("reason evidence differs")
    if only in (None, "totals"):
        totals = Counter(tuple(map(int, m.groups())) for line in lines if (m := DONE.fullmatch(line)))
        expected_totals = Counter([(1, 1, 0), (1, 1, 0), (11, 1, 10), (flood_count, 0, flood_count), (2, 2, 0)])
        if totals != expected_totals:
            raise CheckError("five session totals differ")
    if require_liveness and only in (None, "liveness"):
        misses = [i for i, line in enumerate(lines) if (m := MISS.fullmatch(line)) and int(m.group(1)) == first]
        restores = [i for i, line in enumerate(lines) if (m := RESTORED.fullmatch(line)) and int(m.group(1)) == first + 1]
        wrong_restore = any((m := RESTORED.fullmatch(line)) and int(m.group(1)) == first for line in lines)
        if len(misses) != 1 or len(restores) != 1 or misses[0] >= restores[0] or wrong_restore:
            raise CheckError("this silence has no unique ordered MISS and RESTORED")
    if require_summary and only in (None, "flood"):
        summaries = [m for line in lines if (m := SUMMARY.fullmatch(line))]
        if not summaries:
            raise CheckError("flood has no summary")
        suppressed_total = 0
        for m in summaries:
            seen, rejected, suppressed = map(int, m.group(1, 2, 3))
            pairs = [(int(a), int(b)) for a, b in re.findall(r"(\d+)=(\d+)", m.group(4))]
            counts = [b for _, b in pairs]
            if not (
                0 < suppressed <= rejected <= seen
                and seen == rejected
                and rejected - suppressed == 11
                and sum(counts) == suppressed
                and len({a for a, _ in pairs}) == len(pairs)
                and all(a in (23, 24) for a, _ in pairs)
            ):
                raise CheckError("flood summary differs")
            suppressed_total += suppressed
        raw_flood = [line for number, line in raw_rejects if flood_start <= number < flood_start + flood_count]
        flood_lines = [m for m in rejects if flood_start <= int(m.group(1)) < flood_start + flood_count]
        if len(raw_flood) != len(flood_lines):
            raise CheckError("garbled flood evidence")
        if len(flood_lines) != flood_count - suppressed_total or len({m.group(1) for m in flood_lines}) != len(flood_lines):
            raise CheckError("flood line count differs")
        for m in flood_lines:
            reason = 23 if (int(m.group(1)) - flood_start) % 2 == 0 else 24
            if int(m.group(2)) != 2 or m.group(3) != rules.REASON_NAMES[reason]:
                raise CheckError("flood verdict evidence differs")


def _connect(host: str, port: int) -> socket.socket:
    conn = socket.create_connection((host, port), timeout=5)
    conn.settimeout(3)
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return conn


def _roundtrip(conn: socket.socket, frame: bytes, tables: rules.Tables, stamp: bool = False) -> None:
    if stamp and (vf.layout_errors(frame) or rules.judge_frame(frame, tables) != (0, 0)):
        raise CheckError("injection aimed at stamp port is refused before sending")
    conn.sendall(frame)
    data = bytearray()
    deadline = time.monotonic() + 3
    while len(data) < vf.FRAME_TOTAL_BYTES:
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError()
        conn.settimeout(left)
        part = conn.recv(vf.FRAME_TOTAL_BYTES - len(data))
        if not part:
            raise CheckError("connection closed before a full reply")
        data.extend(part)
    conn.settimeout(3)
    verify_reply(frame, bytes(data), tables, stamp=stamp)


def _end_session(conn: socket.socket) -> None:
    """Reject trailing bytes, including after the session's last reply."""
    conn.shutdown(socket.SHUT_WR)
    conn.settimeout(0.2)
    try:
        if conn.recv(1):
            raise CheckError("trailing reply bytes")
    except socket.timeout:
        pass


def _console(path: Optional[Path], offset: int = 0) -> str:
    if not path:
        return ""
    data = path.read_bytes()
    if len(data) < offset:
        raise CheckError("console shrank during run")
    return data[offset:].replace(b"\0", b"").replace(b"\r", b"").decode("utf-8", "replace")


STEP_NAMES = (
    ["preflight", "stamp t_in/t_out and honest-only", "late connect", "silence closed idle connection", "restore reply"]
    + ["reply " + name for name in ("accept", "profile", "nonfinite", "reserved", "catalog", "stale", "speed", "accel", "steer", "yaw", "gear")]
    + [
        "profile 2 flood replies",
        "console each reason by seq",
        "console MISS and RESTORED",
        "console session totals",
        "console flood summary and cap",
    ]
)


class Steps:
    def __init__(self) -> None:
        self.active = "preflight"
        self.status: Dict[str, str] = {}

    def enter(self, name: str) -> None:
        self.active = name

    def passed(self, name: str) -> None:
        self.status[name] = "PASS"

    def failed(self, exc: BaseException) -> None:
        self.status[self.active] = "FAIL: " + type(exc).__name__

    def lines(self) -> List[str]:
        return [name + " " + self.status.get(name, "NOT RUN") for name in STEP_NAMES]


def _wait_done(console: Path, offset: int) -> None:
    end = time.monotonic() + CONSOLE_WAIT
    while True:
        totals = [tuple(map(int, m.groups())) for line in _console(console, offset).splitlines() if (m := DONE.fullmatch(line))]
        if totals.count((2, 2, 0)) == 1:
            return
        if time.monotonic() >= end:
            raise CheckError("stamp session did not finish")
        time.sleep(0.05)


def run_campaign(
    host: str,
    svc_port: int,
    stamp_port: int,
    contract: Any,
    tables: rules.Tables,
    console: Optional[Path],
    flood_count: int = 64,
    late_seconds: float = 0.7,
    steps: Optional[Steps] = None,
) -> List[Case]:
    """Stamp session first, then one late svc connection and the four svc sessions."""
    if flood_count < 24 or late_seconds < 0.6:
        raise CampaignBounds("flood needs at least 24 claims and late connect at least 0.6 s")
    if svc_port == stamp_port:
        raise PortsInvalid("endpoints must differ")
    steps = steps or Steps()
    cases = build_cases(contract, tables, start_seq=time.monotonic_ns() + 10000)
    first = seq(cases[0].frame) - 3
    mark = console.stat().st_size if console else 0
    if console and "LIVENESS" in _console(console):
        raise EarlierLiveness("late connect needs a fresh boot without an earlier LIVENESS line")
    steps.enter("stamp t_in/t_out and honest-only")
    with _connect(host, stamp_port) as conn:
        for i in range(2):
            _roundtrip(
                conn, _claim(seq(cases[-1].frame) + flood_count + 1 + i, contract, v=5.0, a_x=0.0, delta=0.0, psi_dot=0.0, gear=1), tables, stamp=True
            )
        _end_session(conn)
    if console:
        _wait_done(console, mark)
    else:
        time.sleep(STAMP_SETTLE)  # stated fixed settle time; no console evidence claimed
    steps.passed("stamp t_in/t_out and honest-only")
    steps.enter("late connect")
    time.sleep(late_seconds)
    if console and "LIVENESS" in _console(console):
        raise EarlierLiveness("LIVENESS appeared before the first claim")
    if console:
        steps.passed("late connect")
    steps.enter("silence closed idle connection")
    with _connect(host, svc_port) as conn:
        _roundtrip(conn, _claim(first, contract, v=5.0), tables)
        time.sleep(0.75)  # svc 500: the idle connection must close and print MISS
        if conn.recv(1) != b"":
            raise CheckError("idle svc connection was not closed after silence")
    steps.passed("silence closed idle connection")
    steps.enter("restore reply")
    with _connect(host, svc_port) as conn:
        _roundtrip(conn, _claim(first + 1, contract, v=5.0), tables)
        _end_session(conn)
    steps.passed("restore reply")
    steps.enter("reply " + cases[0].name)
    with _connect(host, svc_port) as conn:
        for i, case in enumerate(cases):
            steps.enter("reply " + case.name)
            if i:
                time.sleep(0.12)  # below the 500 ms deadline; ten rejects cannot reach cap 11
            _roundtrip(conn, case.frame, tables)
            steps.passed("reply " + case.name)
        _end_session(conn)
    steps.enter("profile 2 flood replies")
    with _connect(host, svc_port) as conn:
        for i in range(flood_count):
            n = seq(cases[-1].frame) + 1 + i
            frame = _claim(n, contract, profile=2, v=11.0) if i % 2 == 0 else _claim(n, contract, profile=2, v=5.0, a_x=11.0)
            expected = 23 if i % 2 == 0 else 24
            if rules.judge_frame(frame, tables) != (1, expected):
                raise CheckError("profile 2 flood case does not have its planned reason")
            _roundtrip(conn, frame, tables)
        _end_session(conn)
    steps.passed("profile 2 flood replies")
    return cases


def _wait_console(path: Path, offset: int, cases: Sequence[Case], count: int, category: str) -> None:
    end = time.monotonic() + CONSOLE_WAIT
    while True:
        try:
            check_console(_console(path, offset), cases, require_liveness=True, require_summary=True, flood_count=count, only=category)
            return
        except CheckError:
            if time.monotonic() >= end:
                raise
            time.sleep(0.05)


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Synthetic kind 4 board client; functional checks only")
    p.add_argument("--host", required=True)
    p.add_argument("--contract", required=True, type=Path, help="path to generated vss_contract.py")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--console", type=Path, help="guest console capture from this fresh boot")
    p.add_argument("--guest-image-name", required=True)
    p.add_argument("--guest-image-sha256", required=True, help="given by the operator; not computed by this client")
    p.add_argument("--svc-port", type=int, default=7160)
    p.add_argument("--stamp-port", type=int, default=7161)
    p.add_argument("--flood-count", type=int, default=64)
    p.add_argument("--late-seconds", type=float, default=0.7)
    p.add_argument("--check", action="store_true")
    args = p.parse_args(argv)
    steps = Steps()
    made_out = False
    failed = False
    code = 1
    try:
        try:
            args.out.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise OutputExists() from exc
        made_out = True
        if args.check and not args.console:
            raise CheckWithoutConsole("--check requires a console before any send")
        if args.contract.name != "vss_contract.py":
            raise ContractName("contract filename differs")
        if args.svc_port == args.stamp_port or not all(0 < x < 65536 for x in (args.svc_port, args.stamp_port)):
            raise PortsInvalid("ports invalid")
        if args.flood_count < 24 or args.late_seconds < 0.6:
            raise CampaignBounds("campaign bounds invalid")
        if (
            Path(args.guest_image_name).name != args.guest_image_name
            or "\\" in args.guest_image_name
            or not re.fullmatch(r"[0-9a-fA-F]{64}", args.guest_image_sha256)
        ):
            raise ImageIdentity("guest image identity invalid")
        mark = args.console.stat().st_size if args.console else 0
        if args.console and not re.search(r"(?m)^(?:monitor: )?vss rules: .+", _console(args.console)):
            raise NoVssAnnouncement("console lacks the vss image announcement")
        contract = vf.load_contract(args.contract.parent)
        tables = rules.Tables.from_contract(contract)
        stamp = {
            "kind4_client": 2,
            "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "rules_sha256": hashlib.sha256((HERE / "rules.py").read_bytes()).hexdigest(),
            "vssframe_sha256": hashlib.sha256((HERE / "vssframe.py").read_bytes()).hexdigest(),
            "contract_sha256": hashlib.sha256(args.contract.read_bytes()).hexdigest(),
            "guest_ifs_given": True,
            "guest_ifs": args.guest_image_name,
            "guest_ifs_sha256": args.guest_image_sha256.lower(),
            "kernel_release": platform.release(),
            "python_version": platform.python_version(),
            "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "svc_port": args.svc_port,
            "stamp_port": args.stamp_port,
            "flood_count": args.flood_count,
            "late_seconds": args.late_seconds,
            "measured_timing": False,
        }
        (args.out / "stamp.json").write_text(json.dumps(stamp, indent=2) + "\n", encoding="utf-8")
        steps.passed("preflight")
        cases = run_campaign(
            args.host, args.svc_port, args.stamp_port, contract, tables, args.console, args.flood_count, args.late_seconds, steps=steps
        )
        if args.console:
            for name, category in [
                ("console each reason by seq", "reasons"),
                ("console MISS and RESTORED", "liveness"),
                ("console session totals", "totals"),
                ("console flood summary and cap", "flood"),
            ]:
                steps.enter(name)
                try:
                    _wait_console(args.console, mark, cases, args.flood_count, category)
                    steps.passed(name)
                except (CheckError, OSError, ValueError) as exc:
                    steps.failed(exc)
                    failed = True
        code = 1 if failed or not args.console else 0
    except (Exception, KeyboardInterrupt) as exc:
        steps.failed(exc)
        failed = True
        code = 1
    checks = steps.lines()
    if not args.console:
        checks.append("NOT CHECKED: guest console reasons, session totals, MISS/RESTORED, flood cap and late connect (no --console)")
        checks.append("NOT JUDGED: no campaign verdict without --console")
    result = {"passed": not failed and bool(args.console), "checks": checks, "console_checked": bool(args.console)}
    if made_out:
        try:
            (args.out / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            steps.enter("preflight")
            steps.failed(exc)
            checks = steps.lines()
            code = 1
    for line in checks:
        print("CHECK " + line)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
