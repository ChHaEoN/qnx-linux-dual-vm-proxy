#!/usr/bin/env python3
"""vlm_stamp.py OUT -- write the stamp for a vlm-characterize.sh run.

A separate file, not a heredoc inside the shell script: this harness has lost
backslashes to heredocs before, and a stamp is the one file that must record
exactly what ran. Every value comes from the environment the script sets.
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


def main(out):
    e = os.environ
    b, m = e["BIN"], e["MODELS"]
    model_dir = os.path.dirname(os.path.dirname(b.rstrip("/")))
    ifs = guest_ifs()
    stamp = {
        "experiment": "vlm-characterize",
        "utc": read(out, "requests.start"),
        "board": open("/proc/device-tree/model", "rb").read().replace(b"\0", b"").decode(),
        "l4t": open("/etc/nv_tegra_release").readline().strip(),
        "nvpmodel": " ".join(run(["sudo", "-n", "nvpmodel", "-q"]).split()),
        "governor": "pinned to performance for the run, restored after",
        "page_cache": "dropped before the server started; cudaMalloc does not reclaim it on this board",
        "llama_cpp": run(["git", "-C", model_dir, "log", "-1", "--format=%H"]),
        "llama_server_sha256": sha(os.path.join(b, "llama-server")),
        "model": e["MODEL"], "model_sha256": sha(os.path.join(m, e["MODEL"])),
        "mmproj": e["MMPROJ"], "mmproj_sha256": sha(os.path.join(m, e["MMPROJ"])),
        "server_argv": e["SRV_ARGV_STR"],
        "cores": {"server": e["CORE_SRV"], "client": 5, "probe": 4, "qemu": "0-2"},
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
    json.dump(stamp, open(os.path.join(out, "stamp.json"), "w"), indent=1)
    print("stamp written: %s" % os.path.join(out, "stamp.json"))


if __name__ == "__main__":
    main(sys.argv[1])
