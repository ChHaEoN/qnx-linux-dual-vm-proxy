"""The default monitor's golden: its corpus and its transport driver (sdv Phase 2, WP0).

One module drives both halves of kind4-spec C1, so the two can never send
different frames or read the console differently:

- tests/capture_monitor_golden.py built the monitor from the sources of main
  at 4ee3e532 (exported as blobs, never from a live checkout), ran this corpus
  through it and wrote tests/fixtures/monitor-golden-4ee3e532.json, captured
  from blobs before any monitor.c edit (re-captured once in review, 2026-10-01);
- tests/test_monitor_golden.py builds the CURRENT
  ipc-test/qnx-safety-monitor/monitor.c with the same gcc line, replays the
  same corpus and requires the same replies and the same console, byte for byte.

THE CORPUS. The kind 0 rule table and the kind 1 rule table of
tests/test_measure_lib.py (_RULES, _VLM_RULES), copied here and frozen: an edit
to those tables must not move the golden. Then the sentinel, and claim kinds 2,
7, 9 and 255, which no build knows. Kind 4 stays OUT: kind4-spec C2 runs this
corpus through the vss build, where kind 4 gets a real verdict instead of
reason 5, so C2 could never pass on it (C7 pins kind 4 on the default build in a
test of its own). UDP alone also gets a 63-byte and a 65-byte datagram, which
must be dropped without a reply; a byte stream cannot carry them without losing
its framing.

Every claim in the corpus carries 0xEE in its verdict and reason bytes
(p[6..7]), as test_measure_lib's _poisoned does: check_claim() never reads them,
so an ACCEPT's 00 00 in a reply is one the monitor WROTE, not one the request
already carried. FOUND BY REVIEW: with 00 00 preset, a build that
writes them on REJECT only replayed this corpus clean -- and C2 replays it
through the vss build, where kinds 0 and 1 are not judged anywhere else. The
stamp bytes p[8..23] stay zero, so a build that stops stamping still differs.

THE TRANSPORTS. UDP; plain TCP; the stamp mode (TCP); the service mode with a
60000 ms deadline, the most it takes, so no MISS or `client closed:` line can
appear on a slow host; the polling shm slot on a file. The notified shm-kick
mode is left out: it needs the ivshmem server and a kick client, its banner
carries a server-assigned peer id, and its burst and done lines count on timing.

DETERMINISM. Every frame waits for its reply. The byte streams use one
connection each and wait for `client done:` before the stop. The shm slot sends
one frame, takes its reply and waits for THAT frame's `shm quiet:` line before
the next: the line is printed on a timer after a quiet interval, so a slow host
could otherwise split or merge bursts. A datagram that must get no reply is
followed by one that must, so the stop cannot overtake it.

WHAT IS NORMALISED, and nothing else: the port in the banners that print
`:%d`; the file path in `serving shm on file %s,`; in a stamp-mode reply to a
claim, payload[8..23] (t_in, t_out) -- masked only when 0 < t_in <= t_out, so a
reply that stops carrying stamps still differs. The hostname, the login name
(either case, also inside a path such as /tmp/pytest-of-<user>) and /home/<user>
are redacted wherever they would appear (they do not, today).

Replay redacts too, with the REPLAY host's names: on a host or login named like
a word the console prints (monitor, shm, udp, ...) that word becomes <host> or
<user> and C1 fails, with nothing in the monitor changed. That failure is loud,
never silent: the golden's runs hold no <host> or <user> token
(test_the_fixture_is_redacted pins it), so a redacted word can only differ. On
such a host, run C1 under another login or hostname.

The shm client writes the slot through Python's mmap. That relies on x86-64's
store order (the frame is visible before req_seq) and on req_seq changing in
its low byte only (fewer than 255 frames), so a torn 8-byte store cannot show a
third value. Other machines skip the shm leg rather than race.
"""
import difflib
import getpass
import mmap
import os
import platform
import re
import signal
import socket
import struct
import subprocess
import threading
import time

FRAME = 64
HDR = 16
P_VERDICT, P_REASON, P_KIND = 6, 7, 24
P_T_IN, P_T_OUT = 8, 16
SENTINEL_SEQ = 0xFFFFFFFFFFFFFFFF

# The reference sources, in the fixture header's order, each with its git blob id
# at the reference commit (`git rev-parse 4ee3e532:<path>`, checked on the Windows
# side on 2026-10-01). monitor.c includes the four headers; the native build links
# the two .c files from common/. Pinned here, not only read from a listing: the
# capture refuses any other blob even when an ls-tree listing agrees with it
# (capture_monitor_golden.source_ids), and C1 fails on a fixture that names any
# other (test_the_header_names_the_reference_and_the_build), so a re-capture from
# the wrong blobs cannot relabel the golden.
REFERENCE_COMMIT = "4ee3e532"
SOURCE_IDS = {
    "ipc-test/qnx-safety-monitor/monitor.c": "0929b1d0f3166ef04c51893aea321bb6687e4e27",
    "ipc-test/common/frame.h": "bb9a64d4c43abbbf2c3c7c92ea857b4b39693493",
    "ipc-test/common/frame_io.h": "761f3c38dca4e54df2f8963d99901950eeb85a17",
    "ipc-test/common/shm_chan.h": "0a701be12a7de486426770a6e27d6c2f7fb9a41b",
    "ipc-test/common/shm_map.h": "3b6ccda43decea2bec94b65140c78d781608c155",
    "ipc-test/common/shm_map_posix.c": "265f441b270d3d376a1a33fd6503c7aa0f580545",
    "ipc-test/common/ivshm_client.c": "95e8f76fba3dffd2fb9072da2dd907a2bf15c552",
    "ipc-test/common/ivshm_client.h": "ecd6c7849684ef94742a7591371b91013670242b",
}
SOURCES = tuple(SOURCE_IDS)
COMMON_DIR = "ipc-test/common"
COMPILED = ("ipc-test/qnx-safety-monitor/monitor.c", "ipc-test/common/shm_map_posix.c", "ipc-test/common/ivshm_client.c")
# tests/test_measure_lib.py's native_servers line for the monitor, as it stood at
# 4ee3e532 and still stands: no -Wformat=2, no -ffp-contract.
GCC_FLAGS = ("-O2", "-std=gnu99", "-Wall", "-Wextra", "-Werror")


def gcc_command(gcc, root, out):
    """The native_servers gcc line for the monitor under `root` (a tree with
    ipc-test/ in it: the repo, or a directory of exported blobs)."""
    def p(rel):
        return os.path.join(root, *rel.split("/"))
    return [gcc] + list(GCC_FLAGS) + ["-I", p(COMMON_DIR), "-o", out] + [p(s) for s in COMPILED]


# The same line as the fixture records it, with no host path in it.
GCC_LINE = ["gcc"] + list(GCC_FLAGS) + ["-I", "<root>/" + COMMON_DIR, "-o", "<out>"] + ["<root>/" + s for s in COMPILED]


def git_blob_id(data):
    """What `git hash-object --no-filters` prints for these bytes."""
    import hashlib
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


# ---------------------------------------------------------------- the corpus

POISON = 0xEE


def _base(seq):
    """latency_probe.build_frame(seq) -- class 3, conf 95, 124 us, zeros elsewhere --
    with the verdict and reason bytes preset to POISON (see the module's docstring)."""
    f = bytearray(FRAME)
    f[0:8] = seq.to_bytes(8, "little")
    f[HDR + 0] = 3
    f[HDR + 1] = 95
    f[HDR + 2:HDR + 6] = (124).to_bytes(4, "little")
    f[HDR + P_VERDICT] = f[HDR + P_REASON] = POISON
    return f


def mnist(seq, cls, conf, us):
    f = _base(seq)
    f[HDR + 0] = cls
    f[HDR + 1] = conf
    f[HDR + 2:HDR + 6] = us.to_bytes(4, "little")
    return bytes(f)


def vlm(seq, cls=3, conf=95, model=1, prompt_us=250000, gen_us=10000, total=None,
        kind=1, prompt_n=150, gen_n=2, wall_us=300000, mass_ppm=999999):
    f = _base(seq)
    p = HDR
    f[p + 0] = cls
    f[p + 1] = conf
    f[p + 2:p + 6] = (prompt_us + gen_us if total is None else total).to_bytes(4, "little")
    f[p + 24] = kind
    f[p + 25] = model
    f[p + 26:p + 28] = prompt_n.to_bytes(2, "little")
    f[p + 28:p + 30] = gen_n.to_bytes(2, "little")
    f[p + 30:p + 34] = prompt_us.to_bytes(4, "little")
    f[p + 34:p + 38] = gen_us.to_bytes(4, "little")
    f[p + 38:p + 42] = wall_us.to_bytes(4, "little")
    f[p + 42:p + 46] = mass_ppm.to_bytes(4, "little")
    return bytes(f)


def sentinel():
    """A keepalive that must come back untouched: a rejectable body (class 42)
    with its verdict bytes poisoned (by _base), so judging it would show."""
    f = _base(0)
    f[0:8] = b"\xff" * 8
    f[HDR + 0] = 42
    return bytes(f)


# Copied from tests/test_measure_lib.py _RULES (2026-10-01): label, class, conf, us, verdict, reason.
RULES = [
    ("the probe's frame",               3,   95,    124, 0, 0),
    ("class 9, the top label",          9,   95,    124, 0, 0),
    ("class 10",                       10,   95,    124, 1, 1),
    ("conf 100",                        3,  100,    124, 0, 0),
    ("conf 101",                        3,  101,    124, 1, 2),
    ("conf 60, which is CONF_MIN",      3,   60,    124, 0, 0),
    ("conf 59",                         3,   59,    124, 1, 3),
    ("us 100000, which is INFER_US_MAX", 3,  95, 100000, 0, 0),
    ("us 100001",                       3,   95, 100001, 1, 4),
    ("us 0: there is no lower bound",   3,   95,      0, 0, 0),
    ("class before conf range",        10,  101,    124, 1, 1),
    ("conf range before us",            3,  101, 100001, 1, 2),
    ("us before conf-low",              3,   59, 100001, 1, 4),
]

# Copied from tests/test_measure_lib.py _VLM_RULES (2026-10-01): label, claim fields, verdict, reason.
# Every field, verdict and reason is unchanged; the first row's label was reworded to drop a model name.
VLM_RULES = [
    ("an honest vlm-shaped claim",                    {},                                              0, 0),
    ("at the bound, 1000000 us",                      {"prompt_us": 990000},                           0, 0),
    ("one over the bound",                            {"prompt_us": 990001},                           1, 4),
    ("class 10",                                      {"cls": 10},                                     1, 1),
    ("conf 101",                                      {"conf": 101},                                   1, 2),
    ("conf 60, which is CONF_MIN",                    {"conf": 60},                                    0, 0),
    ("conf 59",                                       {"conf": 59},                                    1, 3),
    ("model 2 has no measured bound",                 {"model": 2},                                    1, 6),
    ("model 0",                                       {"model": 0},                                    1, 6),
    ("a total that is not the sum of its parts",      {"total": 260001},                               1, 7),
    ("a sum that would wrap in 32 bits",              {"prompt_us": 0xFFFFFFFF, "gen_us": 1, "total": 0}, 1, 7),
    ("class before model",                            {"cls": 10, "model": 2},                         1, 1),
    ("model before the sum",                          {"model": 2, "total": 1},                        1, 6),
    ("the sum before the bound",                      {"prompt_us": 1000000, "gen_us": 0, "total": 2000000}, 1, 7),
    ("the bound before conf-low",                     {"prompt_us": 1000001, "gen_us": 0, "conf": 59}, 1, 4),
]

# Unknown in the default build AND in the vss build (which adds kind 4 only).
UNKNOWN_KINDS = (2, 7, 9, 255)


def corpus():
    """[(label, frame, expected)] in sending order; expected is (verdict, reason),
    or None for a frame that must come back byte for byte."""
    items = [("mnist: " + r[0], mnist(100 + i, r[1], r[2], r[3]), (r[4], r[5])) for i, r in enumerate(RULES)]
    items.append(("sentinel", sentinel(), None))
    items += [("vlm: " + r[0], vlm(300 + i, **r[1]), (r[2], r[3])) for i, r in enumerate(VLM_RULES)]
    items += [("unknown kind %d" % k, vlm(500 + k, kind=k), (1, 5)) for k in UNKNOWN_KINDS]
    return items


NO_REPLY = "no reply"


def udp_corpus():
    """The corpus with a short and a long datagram after the sentinel; expected
    NO_REPLY for those two. The frames after them show they were taken in order."""
    items = corpus()
    first = items[0][1]
    at = [x[0] for x in items].index("sentinel") + 1
    items[at:at] = [("udp: short datagram, 63 bytes", first[:FRAME - 1], NO_REPLY),
                    ("udp: long datagram, 65 bytes", first + b"x", NO_REPLY)]
    return items


def requests_record():
    """The requests as the fixture records them, to show the corpus did not move."""
    return {"stream": [[label, data.hex()] for label, data, _ in corpus()],
            "udp": [[label, data.hex()] for label, data, _ in udp_corpus()]}


# ---------------------------------------------------------------- redaction

# Account and host names that identify no one, and that the fixture may carry
# for other reasons ('<root>' in the gcc line, '<user>', the gcc version line):
# never redacted, never looked for.
GENERIC_NAMES = frozenset(("localhost", "root", "runner", "ubuntu", "user"))


def identifying_names():
    """[(name, tag)]: this host's name and this login's name, unless generic."""
    out = []
    try:
        host = socket.gethostname()
    except OSError:
        host = ""
    try:
        user = getpass.getuser()
    except Exception:  # no name for this uid: OSError from 3.13, KeyError before
        user = ""
    for name, tag in ((host, "<host>"), (user, "<user>")):
        if name and name.lower() not in GENERIC_NAMES:
            out.append((name, tag))
    return out


def name_pattern(name):
    """`name` in any case, anywhere it is not part of a longer word: also inside
    a path or a hyphenated name (/tmp/pytest-of-<user>, <host>.local)."""
    return re.compile(r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(name), re.IGNORECASE)


def redact(text):
    """No hostname, no login name and no /home/<user> in anything recorded
    (the repo's rule: no host identity in anything recorded)."""
    text = re.sub(r"/home/[^/\s\"']+", "/home/<user>", text)
    for name, tag in identifying_names():
        text = name_pattern(name).sub(tag, text)
    return text


# ---------------------------------------------------------------- the driver

TRANSPORTS = ("udp", "tcp", "stamp", "svc", "shm")
SVC_DEADLINE_MS = 60000
SHM_FILE_BYTES = 1 << 20
REPLY_TIMEOUT = 5.0     # a reply that must come
NO_REPLY_WAIT = 0.3     # a datagram that must get none
LINE_TIMEOUT = 10.0     # a console line that must come

BANNER = {
    "udp": b"monitor: safety monitor listening on :",
    "tcp": b"monitor: safety monitor listening on :",
    "stamp": b"monitor: stamping replies on :",
    "svc": b"monitor: service monitor listening on :",
    "shm": b"monitor: safety monitor serving shm on file ",
}
# The lines whose `:%d` is this run's port.
PORT_LINES = (b"monitor: safety monitor listening on :", b"monitor: stamping replies on :",
              b"monitor: service monitor listening on :")


class DriverError(Exception):
    pass


def shm_client_ok():
    return platform.machine().lower() in ("x86_64", "amd64")


class _Proc:
    """A monitor with its stdout and stderr read as they come, as raw lines."""

    def __init__(self, argv):
        self.p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.out = []
        self.err = []
        self.pumps = [threading.Thread(target=self._pump, args=(self.p.stdout, self.out), daemon=True),
                      threading.Thread(target=self._pump, args=(self.p.stderr, self.err), daemon=True)]
        for t in self.pumps:
            t.start()

    @staticmethod
    def _pump(stream, sink):
        for line in iter(stream.readline, b""):
            sink.append(line)

    def count(self, text):
        return sum(1 for line in list(self.out) if text in line)

    def wait_for(self, text, n=1, timeout=LINE_TIMEOUT):
        end = time.monotonic() + timeout
        while self.count(text) < n:
            if self.p.poll() is not None:
                for t in self.pumps:
                    t.join(timeout=5)
                if self.count(text) >= n:
                    return
                raise DriverError("the monitor exited (%s) before line %d with %r; stdout %r stderr %r"
                                  % (self.p.returncode, n, text, b"".join(self.out), b"".join(self.err)))
            if time.monotonic() > end:
                raise DriverError("no line %d with %r within %.0f s; stdout %r" % (n, text, timeout, b"".join(self.out)))
            time.sleep(0.005)

    def stop(self):
        """SIGTERM, which every mode honours promptly; a monitor that does not is
        killed so none is left behind, and that is an error."""
        if self.p.poll() is None:
            self.p.send_signal(signal.SIGTERM)
        try:
            rc = self.p.wait(timeout=10)
        except subprocess.TimeoutExpired as e:
            self.p.kill()
            self.p.wait()
            raise DriverError("the monitor ignored SIGTERM for 10 s") from e
        for t in self.pumps:
            t.join(timeout=5)
        return rc

    def kill(self):
        if self.p.poll() is None:
            self.p.kill()
        self.p.wait()


def _free_port(kind):
    s = socket.socket(socket.AF_INET, kind)
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def _start_on_port(binary, words, kind, banner):
    """A port-taking mode, on a free port; a port taken between the probe and the
    bind is tried again, anything else is an error."""
    last = None
    for _ in range(5):
        port = _free_port(kind)
        proc = _Proc([binary, str(port)] + words)
        try:
            proc.wait_for(banner)
            return proc, port
        except DriverError as e:
            proc.kill()
            last = e
            if b"bind(" not in b"".join(proc.err):
                raise
    raise DriverError("no free port in five tries: %s" % last)


def _recv_exact(s, n):
    b = b""
    while len(b) < n:
        c = s.recv(n - len(b))
        if not c:
            raise DriverError("the monitor closed the connection after %d of %d bytes" % (len(b), n))
        b += c
    return b


def _drive_udp(port, items):
    replies = []
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("127.0.0.1", port))
        for label, data, want in items:
            s.settimeout(NO_REPLY_WAIT if want == NO_REPLY else REPLY_TIMEOUT)
            s.send(data)
            try:
                got = s.recv(4096)
            except socket.timeout:
                got = None
            replies.append([label, None if got is None else got.hex()])
    finally:
        s.close()
    return replies


def _drive_stream(port, items):
    replies = []
    with socket.create_connection(("127.0.0.1", port), timeout=REPLY_TIMEOUT) as s:
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        for label, data, _ in items:
            s.sendall(data)
            replies.append([label, _recv_exact(s, FRAME).hex()])
    return replies


SHM_MAGIC = 0x314D4853      # "SHM1": a polling server (shm_chan.h)
OFF_MAGIC, OFF_VERSION, OFF_REQ_SEQ, OFF_REQ, OFF_RSP_SEQ, OFF_RSP = 0, 4, 64, 128, 192, 256


def _drive_shm(path, proc, items):
    if len(items) >= 255:
        raise DriverError("the shm client changes req_seq in its low byte only: at most 254 frames")
    replies = []
    with open(path, "r+b") as fh:
        mm = mmap.mmap(fh.fileno(), 0)
    try:
        magic, version = struct.unpack_from("<II", mm, OFF_MAGIC)
        if (magic, version) != (SHM_MAGIC, 1):
            raise DriverError("the slot is not served: magic %#x version %d" % (magic, version))
        seq = struct.unpack_from("<Q", mm, OFF_REQ_SEQ)[0]
        for i, (label, data, _) in enumerate(items, 1):
            mm[OFF_REQ:OFF_REQ + FRAME] = data
            seq += 1
            struct.pack_into("<Q", mm, OFF_REQ_SEQ, seq)
            end = time.monotonic() + REPLY_TIMEOUT
            while struct.unpack_from("<Q", mm, OFF_RSP_SEQ)[0] != seq:
                if time.monotonic() > end:
                    raise DriverError("no shm reply to %r within %.0f s" % (label, REPLY_TIMEOUT))
                time.sleep(0.0005)
            replies.append([label, bytes(mm[OFF_RSP:OFF_RSP + FRAME]).hex()])
            proc.wait_for(b"monitor: shm quiet:", n=i)
    finally:
        mm.close()
    return replies


def _mask_stamps(items, replies):
    """payload[8..23] of a stamp-mode reply to a claim -> 'x', when they hold
    0 < t_in <= t_out; a sentinel's echo, or a reply without stamps, stays as is."""
    out = []
    for (_, data, _want), (rlabel, rep) in zip(items, replies):
        if rep is not None and data[:8] != b"\xff" * 8 and len(rep) == 2 * FRAME:
            t_in, t_out = struct.unpack_from("<QQ", bytes.fromhex(rep), HDR + P_T_IN)
            if 0 < t_in <= t_out:
                a, b = 2 * (HDR + P_T_IN), 2 * (HDR + P_T_OUT + 8)
                rep = rep[:a] + "x" * (b - a) + rep[b:]
        out.append([rlabel, rep])
    return out


def _lines(raw):
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as e:
        raise DriverError("a console line that is not ASCII: %r" % raw) from e
    return [redact(x) for x in text.splitlines(keepends=True)]


def _normalise_stdout(raw, port=None, shm_path=None):
    lines = []
    for line in raw.splitlines(keepends=True):
        if port is not None and line.startswith(PORT_LINES):
            line = re.sub(rb":%d(?!\d)" % port, b":<port>", line, count=1)
        if shm_path is not None and line.startswith(BANNER["shm"]):
            line = line.replace(b"on file %s, " % os.fsencode(shm_path), b"on file <shm-file>, ", 1)
        lines.append(line)
    return _lines(b"".join(lines))


def run(binary, transport, workdir):
    """One transport's run of the corpus: replies (hex, None for no reply),
    stdout and stderr as lines, the exit code, and the argv as recorded."""
    shm_path = None
    if transport == "udp":
        items = udp_corpus()
        proc, port = _start_on_port(binary, ["udp"], socket.SOCK_DGRAM, BANNER["udp"])
        argv = ["<monitor>", "<port>", "udp"]
    elif transport in ("tcp", "stamp", "svc"):
        items = corpus()
        words = {"tcp": [], "stamp": ["stamp"], "svc": ["svc", str(SVC_DEADLINE_MS)]}[transport]
        proc, port = _start_on_port(binary, words, socket.SOCK_STREAM, BANNER[transport])
        argv = ["<monitor>", "<port>"] + words
    elif transport == "shm":
        items = corpus()
        port = None
        shm_path = os.path.join(workdir, "slot")
        with open(shm_path, "wb") as fh:
            fh.write(b"\0" * SHM_FILE_BYTES)
        proc = _Proc([binary, "shm", shm_path])
        argv = ["<monitor>", "shm", "<shm-file>"]
        try:
            proc.wait_for(BANNER["shm"])
        except BaseException:
            proc.kill()
            raise
    else:
        raise ValueError("no transport %r" % transport)
    try:
        if transport == "udp":
            replies = _drive_udp(port, items)
        elif transport == "shm":
            replies = _drive_shm(shm_path, proc, items)
        else:
            replies = _drive_stream(port, items)
            proc.wait_for(b"monitor: client done:")
        rc = proc.stop()
    except BaseException:
        proc.kill()
        raise
    if transport == "stamp":
        replies = _mask_stamps(items, replies)
    stdout = b"".join(proc.out)
    return {
        "argv": argv,
        "replies": replies,
        "stdout": _normalise_stdout(stdout, port=port, shm_path=shm_path),
        "stderr": _lines(b"".join(proc.err)),
        "returncode": rc,
    }


def run_all(binary, workdir, transports=TRANSPORTS):
    out = {}
    for t in transports:
        d = os.path.join(workdir, t)
        os.makedirs(d, exist_ok=True)
        out[t] = run(binary, t, d)
    return out


def check_replies(transport, record):
    """What the rules say about each reply, independent of any golden: the
    verdict and reason written, every other byte echoed (stamps masked), a
    sentinel untouched, a bad datagram unanswered. [] when all hold."""
    items = udp_corpus() if transport == "udp" else corpus()
    problems = []
    if [r[0] for r in record["replies"]] != [x[0] for x in items]:
        return ["%s: the replies are not the corpus's, in order" % transport]
    for (label, data, want), (_, rep) in zip(items, record["replies"]):
        if want == NO_REPLY:
            if rep is not None:
                problems.append("%s: %s got a reply" % (transport, label))
            continue
        if rep is None:
            problems.append("%s: %s got no reply" % (transport, label))
            continue
        expect = bytearray(data)
        if want is not None:
            expect[HDR + P_VERDICT], expect[HDR + P_REASON] = want
        expect_hex = expect.hex()
        if transport == "stamp" and want is not None:
            a, b = 2 * (HDR + P_T_IN), 2 * (HDR + P_T_OUT + 8)
            expect_hex = expect_hex[:a] + "x" * (b - a) + expect_hex[b:]
        if rep != expect_hex:
            problems.append("%s: %s: reply %s, want %s" % (transport, label, rep, expect_hex))
    if record["returncode"] != 0:
        problems.append("%s: exit %s" % (transport, record["returncode"]))
    return problems


def diff(want, got, what):
    """A unified diff of two line lists, for an assertion message."""
    return "\n".join(difflib.unified_diff([str(x) for x in want], [str(x) for x in got],
                                          "golden " + what, "current " + what, lineterm=""))
