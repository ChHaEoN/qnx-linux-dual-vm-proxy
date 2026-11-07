"""Capture the default monitor's golden from exported reference sources (sdv Phase 2, WP0).

Written on 2026-10-01 to produce tests/fixtures/monitor-golden-4ee3e532.json,
captured from blobs before any monitor.c edit (re-captured once in review,
2026-10-01: review poisoned the corpus's verdict bytes, and the fixture was
captured again from freshly exported blobs); kept so the capture can be run
again by hand. It is not a test (pytest does not collect it) and needs Linux
with gcc: WSL, with CI's Python pins.

THE SOURCES COME FROM GIT, NEVER FROM A CHECKOUT. On the Windows side, from any
checkout of the repository:

    REF=<scratch>/ref-4ee3e532            # outside the repository
    P="ipc-test/qnx-safety-monitor/monitor.c ipc-test/common/frame.h
       ipc-test/common/frame_io.h ipc-test/common/shm_chan.h ipc-test/common/shm_map.h
       ipc-test/common/shm_map_posix.c ipc-test/common/ivshm_client.c
       ipc-test/common/ivshm_client.h"
    for f in $P; do mkdir -p "$REF/$(dirname $f)"; git show 4ee3e532:$f > "$REF/$f"; done
    git ls-tree 4ee3e532 $P > <scratch>/ls-tree-4ee3e532.txt

Then in WSL, from the repository root:

    PYTHONDONTWRITEBYTECODE=1 ~/civenv/bin/python tests/capture_monitor_golden.py \\
        /mnt/c/.../ref-4ee3e532 /mnt/c/.../ls-tree-4ee3e532.txt

The script refuses a source directory inside the repository, and any file whose
git blob id (what `git hash-object --no-filters` prints, computed here) differs
from the ls-tree listing's or from the id tests/monitor_corpus.py pins
(SOURCE_IDS): a listing that agrees with the wrong blobs does not get them in.
It builds with tests/test_measure_lib.py's native_servers line, runs the corpus
of tests/monitor_corpus.py over every transport TWICE and refuses unless both
captures are identical and every reply is what the rules say; then writes the
fixture, redacted (no hostname, no login name, no /home/<user>), with the blob
ids, the gcc line and the version line of `gcc --version` (its first line only)
in its header.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import monitor_corpus as mc  # noqa: E402

DEFAULT_OUT = os.path.join(HERE, "fixtures", "monitor-golden-4ee3e532.json")


def die(msg):
    sys.stderr.write("capture_monitor_golden: %s\n" % msg)
    sys.exit(2)


def read_ls_tree(path):
    """`git ls-tree` lines ('MODE blob SHA<TAB>PATH') -> {path: sha}."""
    ids = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\r\n")
            if not line:
                continue
            meta, _, rel = line.partition("\t")
            parts = meta.split()
            if len(parts) != 3 or parts[1] != "blob" or not rel:
                die("not a git ls-tree line: %r" % line)
            ids[rel] = parts[2]
    return ids


def source_ids(src, listing):
    ids = {}
    for rel in mc.SOURCES:
        p = os.path.join(src, *rel.split("/"))
        if not os.path.isfile(p):
            die("%s is missing from %s" % (rel, src))
        with open(p, "rb") as fh:
            got = mc.git_blob_id(fh.read())
        if rel not in listing:
            die("%s is not in the ls-tree listing" % rel)
        if got != listing[rel]:
            die("%s hashes to %s, the listing says %s: not the reference blob" % (rel, got, listing[rel]))
        if got != mc.SOURCE_IDS[rel]:
            die("%s hashes to %s, but %s's blob is %s (monitor_corpus.SOURCE_IDS): not the reference blob, "
                "whatever the listing says" % (rel, got, mc.REFERENCE_COMMIT, mc.SOURCE_IDS[rel]))
        ids[rel] = got
    return ids


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src", help="a directory holding ipc-test/... exported with git show COMMIT:PATH")
    ap.add_argument("ls_tree", help="git ls-tree %s PATHS output for those files" % mc.REFERENCE_COMMIT)
    ap.add_argument("--out", default=DEFAULT_OUT, help="the fixture to write (default %(default)s)")
    a = ap.parse_args(argv)
    commit = mc.REFERENCE_COMMIT  # the one commit whose blob ids monitor_corpus pins

    src = os.path.realpath(a.src)
    if os.path.commonpath([src, os.path.realpath(REPO)]) == os.path.realpath(REPO):
        die("%s is inside the repository: export the blobs with git show, never use a checkout" % a.src)
    ids = source_ids(src, read_ls_tree(a.ls_tree))

    gcc = shutil.which("gcc")
    if gcc is None or not hasattr(os, "sched_getaffinity"):
        die("needs gcc on Linux")
    version = subprocess.run([gcc, "--version"], capture_output=True, text=True, check=True).stdout

    with tempfile.TemporaryDirectory(prefix="monitor-golden-") as tmp:
        binary = os.path.join(tmp, "monitor")
        r = subprocess.run(mc.gcc_command(gcc, src, binary), capture_output=True, text=True)
        if r.returncode != 0:
            die("the reference build failed:\n%s" % r.stderr)
        if not mc.shm_client_ok():
            die("the shm leg's client needs x86-64 (tests/monitor_corpus.py)")
        transports = mc.TRANSPORTS
        first = mc.run_all(binary, os.path.join(tmp, "a"), transports)
        second = mc.run_all(binary, os.path.join(tmp, "b"), transports)
    if first != second:
        die("two captures differ, so the golden would not be deterministic:\n%s"
            % "\n".join(mc.diff(json.dumps(first[t], indent=1).splitlines(), json.dumps(second[t], indent=1).splitlines(), t)
                        for t in transports if first[t] != second[t]))
    problems = [p for t in transports for p in mc.check_replies(t, first[t])]
    if problems:
        die("the reference does not reply as the rules say:\n" + "\n".join(problems))

    fixture = {
        "format": 1,
        "what": ("kind4-spec C1: the default monitor build's replies and console for one fixed corpus "
                 "(tests/monitor_corpus.py), captured from main at %s. Replayed by tests/test_monitor_golden.py." % commit),
        "reference": {
            "commit": commit,
            "how": ("each source exported with 'git show %s:<path>' on the Windows side, never from a checkout; "
                    "its git blob id (git hash-object --no-filters) recomputed at capture and checked against "
                    "'git ls-tree %s'" % (commit, commit)),
            "sources": ids,
        },
        "build": {
            "gcc_line": mc.GCC_LINE,
            "gcc_line_from": "tests/test_measure_lib.py native_servers (the monitor's line)",
            "gcc_version": mc.redact(version.splitlines()[0]),
            "gcc_version_from": "the first line of 'gcc --version' (the rest is the licence notice)",
        },
        "capture": {
            "transports": list(transports),
            "left_out": {
                "shmkick": ("needs the ivshmem server and a kick client; its banner carries a server-assigned peer "
                            "id, and its burst and done lines count on timing"),
                "kind 4": "kind4-spec C2 runs this corpus through the vss build, where kind 4 gets a real verdict; C7 pins it",
            },
            "svc_deadline_ms": mc.SVC_DEADLINE_MS,
            "shm_file_bytes": mc.SHM_FILE_BYTES,
            "normalised": [
                "the port in the ':%d' banners -> ':<port>'",
                "the file path in 'serving shm on file %s,' -> '<shm-file>'",
                "stamp mode: payload[8..23] (t_in, t_out) of a reply to a claim -> 'x', only when 0 < t_in <= t_out",
            ],
            "redacted": ("the hostname -> <host> and the login name -> <user>, in either case and inside paths, "
                         "and /home/<user> (the repo's rule: no host identity in anything recorded); none appeared"),
            "deterministic": "captured twice; both identical",
            "stdout_stderr": "lists of lines, each with its newline, decoded as ASCII; joined they are the bytes printed",
        },
        "requests": mc.requests_record(),
        "runs": first,
    }
    text = json.dumps(fixture, indent=1, ensure_ascii=True) + "\n"
    if mc.redact(text) != text:
        die("something identifying survived redaction")
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="ascii", newline="\n") as fh:
        fh.write(text)
    print("wrote %s: %d transports, %d stream frames, %d udp datagrams"
          % (a.out, len(transports), len(fixture["requests"]["stream"]), len(fixture["requests"]["udp"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
