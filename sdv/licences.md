# Third-party inputs of the SDV study

The repository keeps project source, pins and build recipes. Third-party
archives, wheels, images, maps and generated catalogues are fetched or supplied
at build/run time and are not vendored here. MIT in [LICENSE](../LICENSE) and
the scope note in [NOTICE](../NOTICE) do not relicense those inputs.

Every licence cell in these tables is **to be confirmed**: no row has yet
been checked against the pinned project's own licence files, its image's
component notices or its bundled dependencies' licences, and no image was
pulled or built for this inventory. The tables record each input's pin and
use. "To be confirmed" is not a claim that an input has no licence, or that
one licence covers a whole container.

## Catalogues, images and source inputs

| Input | Version or pin source | Licence | Use |
|---|---|---|---|
| COVESA Vehicle Signal Specification | v6.0, commit `20c609bf95c73b51d483fb8f81a099d1d5b73066`; archive SHA in [generate.py](vss/generate.py) | to be confirmed | Source-tag archive; only its spec tree is extracted during generation; catalogue not vendored. |
| kuksa-databroker | 0.7.1; revision `a79e2420b319cedccd98298e2a75ee78cfca4b87`, image digest in [images.json](stack/images.json) | to be confirmed | Pulled by digest for the slice stack; not vendored. |
| kuksa-can-provider | 0.5.0; revision `d03dd7db364dd1ce9f7d0c614d80ebf6642ad167`, image digest in [images.json](stack/images.json) | to be confirmed | Pulled by digest for the slice stack; not vendored. |
| kuksa-csv-provider | 0.4.6; revision `30a92880914bedd7f7adf06cb7707719daab3fd4`, image digest in [images.json](stack/images.json) | to be confirmed | Pulled by digest for the slice stack; not vendored. |
| kuksa-mock-provider | 0.4.1; revision `eb60bbff8451d14537f0c56a173c6e927e80b859`, image digest in [images.json](stack/images.json) | to be confirmed | Pulled by digest for the slice stack; not vendored. |
| Python / Debian base image | 3.12.14-slim-trixie; digest in [images.json](stack/images.json) | to be confirmed, per bundled component | Pulled at local image build time; base and OS packages not vendored. |
| Eclipse Mosquitto | 2.0.22; test_only digest in [images.json](stack/images.json) | to be confirmed | Optional local broker tests; not a deployed stack component. |
| Autoware universe / ROS Jazzy | 1.9.0; index `sha256:2c3ae9b76b205f2bad7b4906e2096cd9929f44627aa87813faa6e366c21cc274` in [images.json](stack/images.json) | to be confirmed, per package | Pulled for planning simulation and as rosvss/carlaif's image base; no image vendored. |
| autoware_carla_interface | commit `94b8fbd3a8e4df661568270494369b06eb913d66`, tree `472ed962c44bdd6da71d32a5b8253a7fee6a5fc4`, [pin.json](carlaif/pin.json) | to be confirmed | Pinned package supplied to the interface build; source is staged outside the repo. |
| CARLA server, client and simulation assets | 0.9.16 and 0.10.0; client wheel hashes in [requirements-live.lock](feeder/requirements-live.lock) and [wheel.lock](carlaif/wheel.lock) | to be confirmed separately for code, engine and assets | Simulator supplied outside the repo; wheels installed at build/run time. Map/frame fixtures carry names and hashes, not assets. |
| Cyclone DDS / rmw_cyclonedds_cpp | Autoware image's package set; [ros-env.json](aw/ros-env.json) selects the RMW, no independent version pin | to be confirmed | Middleware supplied by the Autoware image; XML configuration is project source. |
| Amazon Root CA 1 | sha256 in [ca.json](connector/ca.json) | to be confirmed | Fetched at run time for the connector's TLS trust; not vendored. |
| Autoware `sample-map-planning` (release 1.9.0's map archive) | map-file sha256 in [sample-lanelet-102.json](ctl/scenarios/sample-lanelet-102.json) | to be confirmed | Supplied outside the repo for the Autoware planning simulation; the scenario binds it by hash; no map file vendored. |
| zenoh | No active SDV import, download or build pin in this batch | to be confirmed if adopted | Study reference; no zenoh source, generated code or binary is vendored by this batch. |
| python-build-standalone | Runtime supplied to the setup harness in the upload bundle | to be confirmed, including its bundled libraries | Python environment unpacked outside the repo; no interpreter vendored. |
| OpenCV and NumPy for camera-file tests | Pins below; the camera path also uses the host's python3-opencv package | to be confirmed | Installed into the test venv or supplied by the host; no package vendored. |
| AWS CLI, Docker Engine / containerd, host Python and native C toolchain | Host-provided; Docker's required major is checked by the harness | to be confirmed, per component | Operator/host tools; no executable or SDK vendored. |
| GitHub checkout, setup-python and cache actions | v4, v5 and v4 in [tooling.yml](../.github/workflows/tooling.yml) | to be confirmed | CI actions fetched by GitHub, not copied into the repository. |
| ruff, pytest and mypy | 0.16.8, 9.1.1 and 1.18.2 | to be confirmed | Installed only in the CI tooling environment. |

Local project images inherit the base and locked dependencies above. The
recorder additionally stages the pinned upstream `recorder.py` from
`sources.csv-recorder` in [images.json](stack/images.json); that source's licence
is **to be confirmed** at its recorded revision. The drill's derived image uses
the app's base and lock, as [build_drill.py](drill/build_drill.py) describes.
No QNX component is supplied by these recipes; the operator supplies it under
its own licence, outside the repository.

## Locked Python distributions

Every distribution in the lock files is listed below, including transitive
dependencies. Versions and wheel hashes remain authoritative in those locks;
the group identifies the build or run that installs them. All are installed
from wheels at build/run time, never vendored as source or binaries here.

| Group | Lock and use |
|---|---|
| L1 | [sdv/apps/hard-brake-hazard/requirements.aarch64.lock](apps/hard-brake-hazard/requirements.aarch64.lock) |
| L2 | [sdv/apps/hard-brake-hazard/requirements.lock](apps/hard-brake-hazard/requirements.lock) |
| L3 | [sdv/bridge/requirements.aarch64.lock](bridge/requirements.aarch64.lock) |
| L4 | [sdv/bridge/requirements.lock](bridge/requirements.lock) |
| L5 | [sdv/carlaif/wheel.lock](carlaif/wheel.lock) |
| L6 | [sdv/cloud/breaker/requirements-dev.lock](cloud/breaker/requirements-dev.lock) |
| L7 | [sdv/connector/requirements.aarch64.lock](connector/requirements.aarch64.lock) |
| L8 | [sdv/connector/requirements.lock](connector/requirements.lock) |
| L9 | [sdv/feeder/requirements-live.lock](feeder/requirements-live.lock) |
| L10 | [sdv/rosvss/requirements.lock](rosvss/requirements.lock) |
| L11 | [sdv/sim/requirements.aarch64.lock](sim/requirements.aarch64.lock) |
| L12 | [sdv/sim/requirements.lock](sim/requirements.lock) |
| L13 | [sdv/stack/recorder/requirements.aarch64.lock](stack/recorder/requirements.aarch64.lock) |
| L14 | [sdv/stack/recorder/requirements.lock](stack/recorder/requirements.lock) |
| L15 | [sdv/vss/requirements.lock](vss/requirements.lock) |
| L16 | [orin-native/edge-llm/requirements-dry.lock](../orin-native/edge-llm/requirements-dry.lock) |

| Distribution | Version(s) | Installed by | Licence |
|---|---|---|---|
| annotated-types | 0.8.0 | L15 | to be confirmed |
| anytree | 2.13.0 | L15 | to be confirmed |
| argparse-addons | 0.12.0 | L3, L4, L9, L11, L12 | to be confirmed |
| attrs | 26.1.0 | L15 | to be confirmed |
| awscrt | 0.36.1 | L7, L8 | to be confirmed |
| awsiotsdk | 1.31.0 | L7, L8 | to be confirmed |
| bitstruct | 8.23.0 | L3, L4, L9, L11, L12 | to be confirmed |
| boto3 | 1.43.111 | L6 | to be confirmed |
| botocore | 1.43.111 | L6 | to be confirmed |
| cantools | 44.1.0 | L3, L4, L9, L11, L12 | to be confirmed |
| carla | 0.10.0, 0.9.16 | L5, L9 | to be confirmed |
| case-converter | 1.2.0 | L15 | to be confirmed |
| click | 8.5.0 | L15 | to be confirmed |
| cmd2 | 4.2.4 | L1, L2, L3, L4, L7, L8, L10, L13, L14 | to be confirmed |
| crccheck | 1.3.1 | L3, L4, L9, L11, L12 | to be confirmed |
| graphene | 3.4.3 | L15 | to be confirmed |
| graphql-core | 3.2.13 | L15 | to be confirmed |
| graphql-relay | 3.2.0 | L15 | to be confirmed |
| grpcio | 1.84.0 | L1, L2, L3, L4, L7, L8, L10, L13, L14 | to be confirmed |
| grpcio-tools | 1.82.1 | L1, L2, L3, L4, L7, L8, L10, L13, L14 | to be confirmed |
| jmespath | 1.1.0 | L6 | to be confirmed |
| jsonpath-ng | 1.8.0 | L1, L2, L3, L4, L7, L8, L10, L13, L14 | to be confirmed |
| jsonschema | 4.26.0 | L15 | to be confirmed |
| jsonschema-specifications | 2025.9.1 | L15 | to be confirmed |
| kuksa-client | 0.6.0 | L1, L2, L3, L4, L7, L8, L10, L13, L14 | to be confirmed |
| markdown-it-py | 4.2.0 | L1, L2, L3, L4, L7, L8, L10, L13, L14, L15 | to be confirmed |
| mdurl | 0.1.2 | L1, L2, L3, L4, L7, L8, L10, L13, L14, L15 | to be confirmed |
| numpy | 2.5.3 | L15, L16 | to be confirmed |
| opencv-python-headless | 4.14.0.94 | L16 | to be confirmed |
| packaging | 26.3 | L3, L4, L9, L11, L12 | to be confirmed |
| pandas | 3.0.6 | L15 | to be confirmed |
| prompt-toolkit | 3.0.53 | L1, L2, L3, L4, L7, L8, L10, L13, L14 | to be confirmed |
| protobuf | 7.36.2 | L1, L2, L3, L4, L7, L8, L10, L13, L14 | to be confirmed |
| pydantic | 2.13.5 | L15 | to be confirmed |
| pydantic-core | 2.46.5 | L15 | to be confirmed |
| pygments | 2.21.0 | L1, L2, L3, L4, L7, L8, L10, L13, L14, L15 | to be confirmed |
| pyparsing | 3.3.3 | L15 | to be confirmed |
| pyperclip | 1.11.0 | L1, L2, L3, L4, L7, L8, L10, L13, L14 | to be confirmed |
| python-can | 4.6.1 | L3, L4, L9, L11, L12 | to be confirmed |
| python-dateutil | 2.9.0.post0 | L6, L15 | to be confirmed |
| pyyaml | 6.0.3 | L15 | to be confirmed |
| rdflib | 7.6.0 | L15 | to be confirmed |
| referencing | 0.37.0 | L15 | to be confirmed |
| rich | 15.0.0 | L1, L2, L3, L4, L7, L8, L10, L13, L14, L15 | to be confirmed |
| rich-argparse | 1.8.0 | L1, L2, L3, L4, L7, L8, L10, L13, L14 | to be confirmed |
| rich-click | 1.9.9 | L15 | to be confirmed |
| rpds-py | 2026.6.3 | L15 | to be confirmed |
| s3transfer | 0.19.2 | L6 | to be confirmed |
| setuptools | 84.0.0 | L1, L2, L3, L4, L7, L8, L10, L13, L14 | to be confirmed |
| six | 1.17.0 | L6, L15 | to be confirmed |
| textparser | 0.26.2 | L3, L4, L9, L11, L12 | to be confirmed |
| typing-extensions | 4.16.0 | L1, L2, L3, L4, L7, L8, L9, L10, L11, L12, L13, L14, L15 | to be confirmed |
| typing-inspection | 0.4.4 | L15 | to be confirmed |
| urllib3 | 2.8.0 | L6 | to be confirmed |
| vss-tools | 6.0.0 | L15 | to be confirmed |
| wcwidth | 0.9.1 | L1, L2, L3, L4, L7, L8, L10, L13, L14 | to be confirmed |
| websockets | 17.1 | L1, L2, L3, L4, L7, L8, L10, L13, L14 | to be confirmed |
| wrapt | 1.17.3 | L3, L4, L9, L11, L12 | to be confirmed |

This inventory does not establish licence compatibility or permission to redistribute an input.
