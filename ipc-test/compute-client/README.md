# `ipc-test/compute-client/` — the L4T end of the 2026-09-18 service

Phase 3b / A6. `compute_client.cpp` is the program the 2026-09-18 cross-partition
service ran on L4T ([findings.md, 2026-09-18](../../docs/findings.md)): it loads a
TensorRT engine, classifies a real MNIST image on the Ampere iGPU, and sends
class, confidence and its own GPU time as one 64-byte frame
([frame.h](../common/frame.h)) to [the QNX safety monitor](../qnx-safety-monitor/)
in the KVM guest, then prints the verdict.

## Provenance, stated plainly

**This source was not committed when the service ran.** The 2026-09-18 commit
added the monitor, console logs and the findings entry, and described the client
only in prose. It was recovered from the board on 2026-09-23 and committed as
found. What can and cannot be tied to the published run:

| artefact | sha256 | mtime on the board |
|---|---|---|
| `compute_client.cpp` (this file) | `55b26d9b72ec8cf5…` | 2026-09-18 15:51:05 |
| `compute_client` binary (not committed) | `f71a0dae41566f7d…` | 2026-09-18 15:51:28 |
| `mnist.engine` (not committed) | `ced8b52d8a918…` | 2026-09-18 15:52:00 |

- The binary is 23 s younger than the source and the engine 32 s younger than
  the binary, consistent with a build-then-run on the day. **That is timing
  evidence, not proof** that this exact source produced the published verdicts.
- **How `mnist.engine` was built is not recorded.** NVIDIA ships `mnist.onnx`
  beside the sample images in `/usr/src/tensorrt/data/mnist/`, and `trtexec` is
  present; the command, precision and builder flags used are unknown. Engines are
  not byte-reproducible across builds, so a rebuilt one would not carry that hash.
- Neither the binary nor the engine is committed: the engine is derived from
  NVIDIA's model, and both are build outputs.

## Build and run, on the board

```bash
g++ -O2 -std=c++17 -o compute_client compute_client.cpp \
    -I/usr/include/aarch64-linux-gnu -I../common \
    -lnvinfer -lcudart -L/usr/local/cuda/lib64
./compute_client --host 192.168.100.10 --digit 3             # ACCEPT path
./compute_client --host 192.168.100.10 --digit 7 --corrupt   # claims class 42: REJECT
```

It needs the TensorRT and CUDA headers that only exist on the board, which is
why [ipc-test/Makefile](../Makefile) does not build it.

## What it is not

Not a benchmark: the GPU time is one engine execution timed with CUDA events,
with no warm-up and no percentiles, and the round trip is not a latency
measurement. Its successor for the VLM service arm lives under
[orin-native/edge-llm/](../../orin-native/edge-llm/).
