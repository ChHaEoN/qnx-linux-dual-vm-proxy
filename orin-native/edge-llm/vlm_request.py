#!/usr/bin/env python3
"""vlm_request.py -- ask a resident llama-server which MNIST digit an image shows.

Phase 3b / A6, the VLM service arm. One request, one image, one digit back,
with the model's own confidence and the server's own timings. Used by
vlm-characterize.sh now and by the service client later, so both read the
answer the same way.

THE ANSWER IS CONSTRAINED, THEN PARSED STRICTLY. The grammar is `" " [0-9]`:
exactly a space and one digit. Anything else in the reply is an error, never a
guess -- the 2026-09-18 service's rule, "if it cannot classify it must fail,
not invent", carried over.

THE CONFIDENCE IS READ AT THE DIGIT'S POSITION, AND WHY THAT MATTERS. Measured
on the board on 2026-09-23: this model's first token is a space, with
probability ~1.000. A grammar that forces a digit into position 0 still gets
the right answer, but the "probability" reported for it there is ~1e-7 --
the probability of a digit where the model never meant to put one. So the
confidence here is taken from the distribution at position 1, after the
space, over the ten digit tokens: P(digit | image, prompt) restricted to the
label set, the analogue of the 2026-09-18 CNN's softmax at its argmax. How
much of the position's mass the ten digits hold is returned too, so a
renormalisation that hides a spread-out distribution cannot go unnoticed.

THE TIMINGS ARE THE SERVER'S OWN (prompt_ms includes the image encode,
predicted_ms the two generated tokens), the way TensorRT's own GPU time was
reported on 2026-09-18. wall_ms is the client's, and includes HTTP.

cache_prompt is off: an identical image and prompt would otherwise be served
partly from the KV cache, and a characterisation would measure the cache.
Standard library only; the board's python3 has no extra packages.
"""
import base64
import json
import math
import sys
import time
import urllib.request

PROMPT = "Which single digit 0-9 is written in this image? Answer with only the digit."
GRAMMAR = 'root ::= " " [0-9]'
DIGITS = [str(i) for i in range(10)]
TOP_LOGPROBS = 100


class Unclassifiable(Exception):
    """The reply was not exactly a space and one digit, or carried no probabilities."""


def _mime(path):
    return "image/x-portable-graymap" if path.endswith(".pgm") else "image/png"


def ask(server, image_path, timeout_s=60.0):
    img = base64.b64encode(open(image_path, "rb").read()).decode()
    body = {
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:%s;base64,%s" % (_mime(image_path), img)}},
            {"type": "text", "text": PROMPT}]}],
        "temperature": 0,
        "max_tokens": 2,
        "grammar": GRAMMAR,
        "logprobs": True,
        "top_logprobs": TOP_LOGPROBS,
        "cache_prompt": False,
    }
    req = urllib.request.Request(server.rstrip("/") + "/v1/chat/completions",
                                 json.dumps(body).encode(), {"Content-Type": "application/json"})
    t0 = time.monotonic()
    r = json.load(urllib.request.urlopen(req, timeout=timeout_s))
    wall_ms = (time.monotonic() - t0) * 1000.0

    ch = r["choices"][0]
    content = ch["message"]["content"]
    if len(content) != 2 or content[0] != " " or content[1] not in DIGITS:
        raise Unclassifiable("reply %r is not a space and one digit" % content)
    answer = int(content[1])

    ent = (ch.get("logprobs") or {}).get("content") or []
    if len(ent) < 2:
        raise Unclassifiable("no probabilities at the digit's position")
    tops = ent[1].get("top_logprobs", [])
    dig = {t["token"]: math.exp(t["logprob"]) for t in tops if t["token"] in DIGITS}
    mass = sum(dig.values())
    if content[1] not in dig or mass <= 0:
        raise Unclassifiable("the answer's own token is missing from the distribution")

    tm = r.get("timings") or {}
    return {
        "answer": answer,
        "p_answer": dig[content[1]] / mass,
        "digits_present": len(dig),
        "digit_mass": mass,
        "prompt_n": tm.get("prompt_n"),
        "prompt_ms": tm.get("prompt_ms"),
        "predicted_n": tm.get("predicted_n"),
        "predicted_ms": tm.get("predicted_ms"),
        "cache_n": tm.get("cache_n"),
        "wall_ms": wall_ms,
    }


def characterize(server, image_dir, reps, rounds, warmup, out_path):
    """Every digit reps times per round, rounds rounds, in a per-round order
    that is a fixed rotation (deterministic, so a rerun asks in the same order).
    The first `warmup` requests are recorded but marked, not counted."""
    n = 0
    with open(out_path, "w") as out:
        for r in range(rounds):
            order = [(d + r * 3) % 10 for d in range(10)] * reps
            for d in order:
                rec = {"round": r + 1, "truth": d, "warmup": n < warmup}
                try:
                    rec.update(ask(server, "%s/%d.pgm" % (image_dir, d)))
                except Unclassifiable as e:
                    rec["error"] = str(e)
                out.write(json.dumps(rec) + "\n")
                out.flush()
                n += 1
    return n


def summarize(path):
    recs = [json.loads(line) for line in open(path)]
    live = [x for x in recs if not x["warmup"]]
    errs = [x for x in live if "error" in x]
    ok = [x for x in live if "error" not in x]
    right = sum(1 for x in ok if x["answer"] == x["truth"])

    def q(xs, p):
        xs = sorted(xs)
        return xs[min(len(xs) - 1, int(math.ceil(p * len(xs))) - 1)] if xs else float("nan")

    print("requests: %d total, %d warm-up excluded, %d counted" % (len(recs), len(recs) - len(live), len(live)))
    print("unclassifiable: %d" % len(errs))
    print("correct: %d of %d" % (right, len(ok)))
    wrong = [(x["truth"], x["answer"]) for x in ok if x["answer"] != x["truth"]]
    if wrong:
        print("wrong (truth, answer): %s" % sorted(set(wrong)))
    print("cache_n nonzero in %d requests" % sum(1 for x in ok if x.get("cache_n")))
    print("digits present at the answer position: min %d of 10; digit mass min %.4f" % (
        min(x["digits_present"] for x in ok), min(x["digit_mass"] for x in ok)))
    per = {}
    for x in ok:
        per.setdefault(x["truth"], []).append(x["p_answer"])
    print("P(answer) per digit, min / median:")
    for d in sorted(per):
        v = sorted(per[d])
        print("  %d: %.4f / %.4f" % (d, v[0], v[len(v) // 2]))
    for key in ("prompt_ms", "predicted_ms", "wall_ms"):
        v = [x[key] for x in ok if x.get(key) is not None]
        print("%-13s p50 %8.1f  p90 %8.1f  p99 %8.1f  p99.9 %8.1f  max %8.1f   (n=%d)" % (
            key, q(v, .5), q(v, .9), q(v, .99), q(v, .999), max(v), len(v)))
    tot = [x["prompt_ms"] + x["predicted_ms"] for x in ok
           if x.get("prompt_ms") is not None and x.get("predicted_ms") is not None]
    print("%-13s p50 %8.1f  p90 %8.1f  p99 %8.1f  p99.9 %8.1f  max %8.1f   (n=%d)" % (
        "model_ms", q(tot, .5), q(tot, .9), q(tot, .99), q(tot, .999), max(tot), len(tot)))


def main(argv):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://127.0.0.1:8089")
    ap.add_argument("--image", help="ask once about this image")
    ap.add_argument("--characterize", action="store_true")
    ap.add_argument("--images", default="/usr/src/tensorrt/data/mnist")
    ap.add_argument("--reps", type=int, default=20)
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--warmup", type=int, default=10)
    ap.add_argument("--out", default="vlm-requests.jsonl")
    ap.add_argument("--summarize", help="summarise an existing requests file")
    a = ap.parse_args(argv)
    if a.summarize:
        summarize(a.summarize)
        return 0
    if a.characterize:
        characterize(a.server, a.images, a.reps, a.rounds, a.warmup, a.out)
        summarize(a.out)
        return 0
    if a.image:
        try:
            print(json.dumps(ask(a.server, a.image)))
            return 0
        except Unclassifiable as e:
            print("unclassifiable: %s" % e, file=sys.stderr)
            return 3
    ap.error("one of --image, --characterize or --summarize")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
