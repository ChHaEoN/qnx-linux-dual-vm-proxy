# 20260923T-a6-orin-llm-prep — an LLM is a different load from `fma.cu`

**Phase 3b / A6 prep, L4T only. No QNX guest ran** (`qemu_running 0` in every
`state.txt`). Nothing here measures the partition, and no figure in this record
may be compared with any A6 rung: the governor was left on `schedutil` and `c7`
was left enabled, because no latency is measured here. This record exists to
answer one question before a board session is spent on it — **would an `llm` arm
stress anything the existing `gpu` arm does not?**

It would. At the same GPU occupancy, `fma.cu` never moves the memory controller
and an LLM drives it to about half of peak.

---

## 1. The result

Each window is traced by `tegrastats --interval 500` while that load runs alone,
after the page cache is dropped. Two independent end-to-end runs of
[characterize-load.sh](../../../orin-native/edge-llm/characterize-load.sh):

**Run 2** (committed as [`final/`](final/)):

| window | n | GR3D med/max | EMC util med/max | EMC MHz med/max | VDD_IN mW med/max | tj max |
|---|---:|---|---|---|---|---|
| idle | 64 | 0 / 0 | 0 / 0 | 2133 / 2133 | 4563 / 4757 | 53.4 |
| `fma` | 123 | **99 / 99** | **0 / 0** | **2133 / 2133** | 10350 / 10509 | 54.3 |
| `llm-big` (4B) | 189 | 97 / 99 | **44 / 45** | **3199 / 3199** | 17554 / 17751 | 59.6 |
| `llm-small` (500M) | 141 | 95 / 98 | **49 / 55** | **3199 / 3199** | 15439 / 16032 | 59.3 |

**Run 1**, quoted from the session console — its raw trace was removed when the
output directory was recreated for run 2, so only run 2's raw files are
committed:

| window | GR3D med/max | EMC util med/max | EMC MHz | VDD_IN med | tj max |
|---|---|---|---|---|---|
| idle | 0 / 0 | 0 / 0 | 2133 | 4482 | 47.2 |
| `fma` | 99 / 99 | 0 / 0 | 2133 | 10429 | 52.8 |
| `llm-big` | 96 / 99 | 44 / 45 | 3199 | 17515 | 58.9 |
| `llm-small` | 96 / 98 | 49 / 54 | 3199 | 15439 | 58.9 |

Throughput, from each tool's own report:

| load | run 1 | run 2 |
|---|---|---|
| `fma.cu` | 1557.6 GFLOP/s | 1557.9 GFLOP/s |
| Qwen3-VL-4B Q4_K_M, decode | 17.07 tok/s | 17.13 tok/s |
| SmolVLM-500M Q8_0, decode | 97.96 tok/s | 98.04 tok/s |

**The contrast.** `fma.cu` holds GR3D at 99% with EMC utilisation at **0%** and
the memory clock at its idle 2133 MHz. Both LLMs hold GR3D just as high **and**
drive EMC to 44–49%, forcing the clock to 3199 MHz — the Super SKU's full rate —
at 1.5–1.7× the power. `fma` burns FP32 ALUs out of registers; decode streams
the whole weight matrix past them for every token.

**A self-consistency check, not a second measurement.** Weights streamed per
second is size × decode rate:

- 2.32 GiB × 17.13 tok/s = **42.7 GB/s**
- 414.86 MiB × 98.04 tok/s = **42.6 GB/s**

Two models a factor of ten apart in size and 5.7× apart in rate demand the same
bandwidth, which is what "bandwidth-bound" means. At 3199 MHz a 128-bit LPDDR5
bus offers 102.4 GB/s, so that is 42% of peak — against the 44–49% tegrastats
reports. The arithmetic and the counter agree; neither validates the other.

---

## 2. What was run

| | |
|---|---|
| board | NVIDIA Jetson Orin Nano Engineering Reference Developer Kit **Super** |
| L4T | R36.4.7, GCID 42132812 (kernel 5.15.148-tegra) |
| CUDA | 12.6, compiled for sm_87 |
| power mode | `nvpmodel` **25 W, mode 1** — recorded because no earlier A6 record records it at all |
| governor | `schedutil`, **not pinned** (no latency measured here) |
| llama.cpp | `e6ab7c1a41054a888ada952eab4c886444c2f5ad`, built `-DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=87 -DLLAMA_CURL=OFF` |
| QNX guest | **not running** |

Models. Weights are not in this repo and never will be ([.gitignore](../../../.gitignore));
what is recorded is the manifest. Both are Apache-2.0 **verified on the base
model card**, not merely on the GGUF repository:

| model | repo | file (size) | sha256 |
|---|---|---|---|
| Qwen3-VL-4B-Instruct | `Qwen/Qwen3-VL-4B-Instruct-GGUF` | `Qwen3VL-4B-Instruct-Q4_K_M.gguf` (2.50 GB) | `66358cb18bb6b3b1b6675aa412c7a88ef01d228f481184d13668e5201c730a0a` |
| — its vision encoder | same | `mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf` (0.45 GB) | `30ba2c7dd3127a4561b6cba9d13d0f711c91bdb38742e2f56d73c8cb596bd06d` |
| SmolVLM-500M-Instruct | `ggml-org/SmolVLM-500M-Instruct-GGUF` | `SmolVLM-500M-Instruct-Q8_0.gguf` (0.42 GB) | `9d4612de6a42214499e301494a3ecc2be0abdd9de44e663bda63f1152fad1bf4` |
| — its vision encoder | same | `mmproj-SmolVLM-500M-Instruct-Q8_0.gguf` (0.10 GB) | `d1eb8b6b23979205fdf63703ed10f788131a3f812c7b1f72e0119d5d81295150` |

`Qwen2.5-VL-3B` was rejected: its **base** model card carries no licence field at
all, though the GGUF repository's metadata says `apache-2.0`. Checking the GGUF
repo alone would have imported an unknown licence into a public portfolio repo.

---

## 3. What the board refuses to do

Found the hard way, and all three are constraints on any future `llm` arm:

- **`cudaMalloc` does not reclaim page cache.** With 3.7 GB in `buff/cache` and
  2.1 GB free, the 4B model cannot create a context at all — `NvMapMemAllocInternalTagged
  … error 12`, then `cudaMalloc failed: out of memory` on a **302 MiB compute
  buffer**. After `echo 3 > /proc/sys/vm/drop_caches` the identical command runs.
  Reproduced in both directions. Dropping the cache is therefore part of the
  procedure, not housekeeping — see [`exploratory/loadcompare/`](exploratory/loadcompare/)
  for the failing runs.
- **A model's default context can exceed the board.** The 4B's default asked for
  a **1512 MiB KV cache** and died. It runs at `-c 1024 -b 256 -ub 64`. Context
  and batch are explicit, recorded parameters from now on.
- **llama.cpp segfaulted on one OOM path** rather than failing cleanly
  (`qwen3vl-c2048-b512`, core dumped). A load that can die mid-window needs a
  liveness proof that checks for output, which is why the committed script
  refuses a window that produced no throughput line.

A fourth trap was in the harness, not the board: `tegrastats` runs as root under
`sudo`, a plain `kill` from the launching shell is silently ignored, and `wait`
on it never returns. That hung the first attempt for ten minutes. The committed
script kills every match as root and never waits.

---

## 4. Vision, end to end

Both models were given `/usr/src/tensorrt/data/mnist/0.pgm` — **the same image
file the 2026-09-18 TensorRT service classifies** — and asked for the digit.
Both answered **0**, correctly:

| model | settings | answer |
|---|---|---|
| Qwen3-VL-4B | `-c 1024 -b 256 -ub 64 --no-mmproj-offload` | `0` |
| SmolVLM-500M | `-c 2048 -b 512 -ub 128` | `0` |

Logs in [`exploratory/`](exploratory/). This is a functional pass on one image,
not an accuracy claim: one image, one prompt, greedy decoding, no test set.

---

## 5. What this does NOT demonstrate

- **Nothing about the partition.** No QNX guest ran. This says nothing about
  interference, isolation, or cross-partition latency — those need the arm this
  record only argues for.
- **No latency figure**, and none of these numbers pairs with any A6 rung. The
  governor was `schedutil` and `c7` was enabled; the ladder's discipline was
  deliberately not applied because nothing here is a latency measurement.
- **The EMC clock is dynamic** — 2133 idle, 3199 loaded. Every earlier A6 record
  was taken while it sat at 2133. Any future arm must record EMC rate per window,
  or a load effect and a clock change will be indistinguishable.
- **`fma`'s 0% EMC is tegrastats' number**, on a counter that reads an integer
  percentage; it means "below the resolution of this counter", not "zero bytes".
- **Two runs is not a campaign.** These are two end-to-end repeats of one script
  on one board on one night, not the k ≥ 12 interleaved design OD11 requires for
  a published figure.
- **The load is not yet an arm.** `run-interference.sh`'s liveness check
  (`m_require_gpu_busy`, GPU_MIN_PCT=50) happens to suit decode at 95–97% GR3D,
  but nothing here has been run inside that harness, with a guest, or against a
  probe.

---

## 6. What it decides

- An `llm` arm is worth a board session: it stresses a resource the `gpu` arm
  provably does not touch.
- **Use the 500M model for the arm.** It reaches the same ~42.7 GB/s as the 4B
  while holding 0.42 GB instead of 2.50 GB — and the QNX guest will want 1 GB of
  the same DRAM. The 4B's margin against this board's allocator is thin enough
  that it failed repeatedly tonight.
- The arm must drop the page cache before each window, record EMC rate per
  window, and refuse a window with no throughput line.
- `nvpmodel` must go into the stamp. It is an unrecorded variable on every A6
  figure taken so far.
