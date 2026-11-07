# sdv/arm64: the slice's arm64 images, and the static A72 scan

SDV Phase 3 runs the slice on `a1.metal` (Cortex-A72 cores: ARMv8.0-A,
no LSE atomics, no LDAPR). WP0 builds the three local images for `linux/arm64` on the PC, pins them, scans every
pinned arm64 image for instructions an ARMv8.0 core lacks, and smokes the local ones under emulation as an A72,
before any of them reaches the instance.

From 2026-10-17 the default bare-metal host is `c7g.metal` (Neoverse V1: ARMv8.4-A with SVE), and `a1.metal` stays
one `METAL_TYPE` away. The scan stays the gate for every image all the same (the owner's decision): V1 is a
superset of the Orin's Cortex-A78AE (ARMv8.2-A, no SVE), so an image that runs on `c7g.metal` may still use an
instruction the Orin lacks, which an A72 host would have refused at once. The scan holds every image to ARMv8.0,
below both.

| file | what it is |
|---|---|
| `a64scan.py` | The scanner. Standard library only. Classifies every aligned word of an aarch64 ELF's executable sections by encoding (LL/SC; the LSE CAS, CASP and atomic memory operations; LDAPR; LOR; and, as information, SHA512, SHA3, dot product and RDM); falls back to the executable `PT_LOAD` segments for an ELF without section headers; opens PyInstaller onefile archives, one nested in another too; walks OCI layer blobs, each checked against its digest as it is read, from a `docker save` tar or from a registry by digest: a gzip blob member after member to the end of its last, bzip2 and xz stream after stream, an uncompressed tar as it is, and a zstd blob refused; a tar nested inside a layer is not opened. Its module docstring is the full description: the classes, the guard rule, what it does not show. |
| `arm64.py` | The driver: `build` (the three images, their pins read back from the daemon, `--write-pins` into `sdv/stack/images.json`), `scan` (the seven images and the two native sim wheels, `scan.json` and the gate), `smoke` (the HWCAP canary, then each local image's probe with `QEMU_CPU=cortex-a72`; the bridge's `check` must report the contract and the DBC its pinned labels name). |

The builds themselves are `sdv/bridge/build_image.py --arch arm64` (the bridge) and `sdv/stack/stack.py`'s
`build_local_arm64` (the app and the recorder). Each stages its context outside the repo with the image's
`requirements.aarch64.lock` as `requirements.lock`, builds with `docker buildx build --platform linux/arm64
--provenance=false --sbom=false --load` from the unchanged Dockerfile, and tags the image `<tag>-arm64`. The
amd64 path does not change: `build_local`, `build_image.py` without `--arch`, the x86_64 locks and the
Dockerfiles are as they were, so no amd64 image ID moves.

## Running it

In WSL Ubuntu-24.04, from the repo root, with Docker Engine (the containerd image store) and the host's
`qemu-aarch64` binfmt registration (flags `POF`; no privileged `binfmt --install` container is used or needed):

    python3 sdv/arm64/arm64.py build --write-pins --out <outside the repo>/build.json
    python3 sdv/arm64/arm64.py scan --out <outside the repo>/scan.json --work <scratch>
    python3 sdv/arm64/arm64.py smoke --out <outside the repo>/smoke.json

`scan` fetches the four upstream images' arm64 layers from their registries by digest (anonymous pulls,
nothing reaches the image store) and the two wheels from PyPI; `--work` holds one save tar or one layer blob at
a time, each removed after it is read. Records are refused inside the repo.

## The rules

- **The A72 rule (`scan`).** Every scanned object: no unguarded LSE word, no LDAPR, no LOR, no object with an
  executable `PT_LOAD` read as 0 words, and no object unread (a cut file, a onefile archive that does not parse or is
  nested too deep, a layer whose tar stops before its data does). An LSE word is guarded only inside the compiler
  runtimes' outline-atomics helper, word for word: `ldrb w16, [x16, #imm]` two words before it, `cbz w16` one word
  before it branching three words on, `ret` right after it, and an LL/SC word within 4 words of that target. A CBNZ,
  another register or load, a branch elsewhere or a missing `ret` leaves it unguarded. The post-v8.0 counters are
  listed, never gated. So is the context of each flagged word: the share of reserved or unallocated top-level
  encodings around it, which reads near zero among code and near three in sixteen among constant tables a library
  keeps in its executable section. That split is evidence for a reader; a flagged word fails the rule whatever its
  context. Other ELFs (big-endian, ILP32, other machines) are listed with their class, encoding and machine, not
  scanned and not gated: none of them runs as A64 code on the host's little-endian arm64 kernel.
- **The reviewed exceptions (`scan`).** `arm64.py`'s `REVIEWED` lists three objects of the mock provider's base
  layer by sha256, path in the image and image, each with every flagged word it holds (address, class, word) and the
  constant tables those words lie in, each table checked against its definition. Such an object
  is set aside only when its flagged words are exactly the listed ones: other bytes, another path or image, a word
  not listed, or a listed word no longer flagged, and it is gated like any other object. `scan.json` records what
  was set aside under `reviewed`, with its counts per class and the reason.
- **The floor (`scan`).** Each upstream image must yield at least as many objects and LSE words as the read-only
  scan that preceded this tool (`arm64.py`'s `UPSTREAM_FLOOR`), each local image at least the base's CPython
  layer's objects, each wheel at least one object. A scan that reads less than that one did fails, so a reader
  that silently skips code cannot pass.
- **Identity (`scan`, `build`, the tests).** A local image's pin is the daemon's ID (a manifest digest under the
  containerd store) and the config digest of the manifest that ID names in a `docker save` stream, both
  hash-checked. Each pinned upstream index must list the pinned arm64 manifest, the base's included, and each
  local image's first layers must be the base's arm64 layers. The bridge's pin carries the three labels it was
  built with: a new generation means a rebuild and a new pin. A build that exits 0 but leaves no image under its tag
  is an error on both build paths, in the same words (`the build left no image tagged <tag>`), and no pin is read.
- **The canary (`smoke`).** `QEMU_CPU` reaches qemu-user through the container's environment only if the binfmt
  registration runs qemu as the container's own interpreter. The canary reads `getauxval(AT_HWCAP)` in the arm64
  python base under `QEMU_CPU=cortex-a72` and under `QEMU_CPU=max`: `HWCAP_ATOMICS` must be clear under the first
  and set under the second. When it is not, no image smoke runs. Each image smoke then reads the same HWCAP inside
  the image (atomics clear) and passes on exit 0 only. The bridge's probe is its `check`, and the contract sha256,
  catalog digest and DBC sha256 it reports must each equal `images.json`'s bridge label: an image that bakes in
  another generation than its pin names fails.

## What it does not show

That any image runs on the a1.metal host (Phase 3 V1 runs them there); that the crypto libraries' v8.2 SHA512 code is
dispatched by HWCAP; that a guarded word's flag is HWCAP_ATOMICS (the load's shape is matched, not its address); the
post-v8.0 classes the scanner does not classify (FP16 arithmetic, SVE, non-hint PAC, JSCVT, LDAPUR); code generated
or loaded at run time, or inside zip files, static archives or tar files nested in an image; that an ELF's section
headers tell the truth about which of its segment's bytes are code; that control never reaches a reviewed table (a
static scan reads what the bytes are, not where execution goes); under emulation, anything beyond the paths the
probes run; any timing.
