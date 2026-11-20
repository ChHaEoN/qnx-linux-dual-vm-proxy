#!/usr/bin/env python3
"""vlm_stamp.py OUT -- write the stamp for a vlm-characterize.sh run.

A separate file, not a heredoc inside the shell script: this harness has lost
backslashes to heredocs before, and a stamp is the one file that must record
exactly what ran. Every value comes from the environment the script sets.

OFF L4T (2026-11-10: a g5g.metal session's vlm phase, scripts/aws/remote-ladder.sh). A host with no
/etc/nv_tegra_release is not a Tegra host, and the stamp says so instead of raising: the board and L4T fields carry
NOT_TEGRA, nvpmodel is not asked, and no field states an Orin fact. The page-cache field keeps "dropped before the
server started" (vlm-demo.sh drops it on every host) without the clause about this board; the governor field says what
vlm-demo.sh did (left as found); the core map holds the server's cores as given, the client's as vlm-demo.sh pins it,
and CORE_PROBE and CORE_QEMU when the session set them, else "not applicable". It adds the first GPU's name, compute
capability and driver version, asked of the driver's tool by index and by named fields (never a UUID or a serial
number), and the visible-devices word. EVERY STRING IS ONE LINE there: capture.py ends an A6 capture on a JSON string
holding a newline, and the driver's tool may answer for every GPU of the host, so an answer that still holds a newline
is written as the word "unreadable". On L4T the stamp is what it was, field for field.

STAMP_ROOT (tests only) stands before the two L4T paths, so a made-up root can be an L4T host or none.
"""
import hashlib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import vlm_request  # noqa: E402


def sha(p):
    if not p or not os.path.exists(p):
        return None
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def run(argv):
    return subprocess.run(argv, capture_output=True, text=True).stdout.strip()


def read(out, name):
    p = os.path.join(out, name)
    return open(p).read().strip() if os.path.exists(p) else None


def guest_ifs():
    """The image the running QEMU booted, from its own command line."""
    args = run(["ps", "-o", "args=", "-C", "qemu-system-aarch64"]).splitlines()
    for tok in (args[0].split() if args else []):
        if tok.endswith(".bin") and os.path.exists(tok):
            return tok
    return None


NOT_TEGRA = "not a Tegra host"
GPU_FIELDS = ("name", "compute_cap", "driver_version")


def first_gpu():
    """The first GPU's name, compute capability and driver version from the driver's tool, or a word."""
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=" + ",".join(GPU_FIELDS), "--format=csv,noheader", "-i", "0"],
                           capture_output=True, text=True)
    except OSError:
        return "no driver tool"
    if r.returncode != 0:
        return "driver tool failed"
    parts = [p.strip() for p in r.stdout.strip().split(",")]
    if len(parts) != len(GPU_FIELDS):
        return "unreadable"
    return dict(zip(GPU_FIELDS, parts))


def one_line(o):
    """o with every string that holds a newline replaced by the word "unreadable" (keys too)."""
    if isinstance(o, dict):
        return {one_line(k): one_line(v) for k, v in o.items()}
    if isinstance(o, list):
        return [one_line(v) for v in o]
    if isinstance(o, str) and ("\n" in o or "\r" in o):
        return "unreadable"
    return o


def main(out):
    e = os.environ
    b, m = e["BIN"], e["MODELS"]
    model_dir = os.path.dirname(os.path.dirname(b.rstrip("/")))
    ifs = guest_ifs()
    root = e.get("STAMP_ROOT", "")
    tegra = os.path.exists(root + "/etc/nv_tegra_release")
    if tegra:
        host = {
            "board": open(root + "/proc/device-tree/model", "rb").read().replace(b"\0", b"").decode(),
            "l4t": open(root + "/etc/nv_tegra_release").readline().strip(),
            "nvpmodel": " ".join(run(["sudo", "-n", "nvpmodel", "-q"]).split()),
            "governor": "pinned to performance for the run, restored after",
            "page_cache": "dropped before the server started; cudaMalloc does not reclaim it on this board",
        }
        cores = {"server": e["CORE_SRV"], "client": 5, "probe": 4, "qemu": "0-2"}
    else:
        host = {
            "board": NOT_TEGRA,
            "l4t": NOT_TEGRA,
            "nvpmodel": "not applicable",
            "governor": "left as found by vlm-demo.sh",
            "page_cache": "dropped before the server started",
        }
        cores = {"server": e["CORE_SRV"], "client": 5, "probe": e.get("CORE_PROBE", "not applicable"),
                 "qemu": e.get("CORE_QEMU", "not applicable")}
    stamp = {
        "experiment": "vlm-characterize",
        "utc": read(out, "requests.start"),
        "board": host["board"],
        "l4t": host["l4t"],
        "nvpmodel": host["nvpmodel"],
        "governor": host["governor"],
        "page_cache": host["page_cache"],
        "llama_cpp": run(["git", "-C", model_dir, "log", "-1", "--format=%H"]),
        "llama_server_sha256": sha(os.path.join(b, "llama-server")),
        "model": e["MODEL"], "model_sha256": sha(os.path.join(m, e["MODEL"])),
        "mmproj": e["MMPROJ"], "mmproj_sha256": sha(os.path.join(m, e["MMPROJ"])),
        "server_argv": e["SRV_ARGV_STR"],
        "cores": cores,
        "prompt": vlm_request.PROMPT,
        "grammar": vlm_request.GRAMMAR,
        "request": "temperature 0, max_tokens 2, top_logprobs %d, cache_prompt false" % vlm_request.TOP_LOGPROBS,
        "confidence": ("P(answer) at token position 1 (the model's first token is a space), over the ten "
                       "digit tokens present there, renormalised; the digit tokens' raw mass is recorded per request"),
        "reps": int(e["REPS"]), "rounds": int(e["ROUNDS"]), "warmup_excluded": int(e["WARMUP"]),
        "images": e["IMAGES"] + "/{0..9}.pgm (NVIDIA's TensorRT samples; not committed)",
        "vlm_request_sha256": sha(os.path.join(HERE, "vlm_request.py")),
        "vlm_stamp_sha256": sha(os.path.join(HERE, "vlm_stamp.py")),
        "script_sha256": sha(os.path.join(HERE, "vlm-characterize.sh")),
        "guest": "not running (NO_GUEST=1)" if e.get("NO_GUEST") == "1" else "running beside the server",
        "guest_ifs": os.path.basename(ifs) if ifs else None,
        "guest_ifs_sha256": sha(ifs),
        "mem_before": read(out, "mem-before.txt"),
        "mem_resident": read(out, "mem-resident.txt"),
        "mem_after": read(out, "mem-after.txt"),
    }
    if not tegra:
        stamp["gpu"] = first_gpu()
        stamp["cuda_visible_devices"] = e.get("CUDA_VISIBLE_DEVICES", "unset")
        stamp = one_line(stamp)
    json.dump(stamp, open(os.path.join(out, "stamp.json"), "w"), indent=1)
    print("stamp written: %s" % os.path.join(out, "stamp.json"))


if __name__ == "__main__":
    main(sys.argv[1])
