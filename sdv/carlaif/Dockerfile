# Dockerfile -- CARLA 0.10.0's ROS 2 interface at the pinned commit, sdv-carlaif (sdv/carlaif; SDV Phase 8 WP9 P2)
#
# Local branch only. Built by sdv/carlaif/build_image.py, never from the repo root: it stages a context outside the repo
# (~/sdv-cache) holding this file, wheel.lock, aw-entrypoint.sh (sdv/aw's, copied in), wheels/ with the one wheel the
# lock names (its sha256 checked) and src/autoware_carla_interface/ with the pinned package's files (every blob id
# checked against pin.json, whose list hashes to the pin's tree id; the one file pin.json leaves out is not staged), and
# builds with --provenance=false --sbom=false --pull=false --network=none. Run by image ID (sdv/stack/images.json's
# carlaif.amd64), never by tag.
#
# The base is Autoware's Jazzy 1.9.0 image by its amd64 manifest digest (images.json's autoware.amd64.manifest_digest,
# as sdv/rosvss/Dockerfile), kept in the image store and never pulled. It holds ROS 2 Jazzy, Autoware 0.52.0's packages
# (among them the interface at 0.52.0, which cannot drive a 0.10.0 server), colcon and a compiler, and Python 3.12.
#
# The pinned package is built by colcon into an overlay prefix of its own, /opt/sdv-carlaif/install, so that once that
# prefix is sourced find-pkg-share and the Python path name the pin's files, not the 0.52.0 copy under /opt/autoware.
# The wheel goes into a venv made with --system-site-packages (the base's Python is externally managed and has no pip;
# the ROS packages come through the PYTHONPATH the setup files set), installed from the context alone and hash-checked,
# and the build imports it once and fails unless it is 0.10.0 from the venv.
#
# The image's own entrypoint never runs (2.12): this image's ENTRYPOINT is the project's, sdv/aw/aw-entrypoint.sh, which
# sources the two setup files and execs its command. The overlay is sourced by the command the launch step gives, as
# build_image.py's LAUNCH_ENV has it, never by the entrypoint. The image runs as the base's user aw (uid 1000).
# PYTHONUNBUFFERED: the interface's flat-curve line is a bare print, and it reaches `docker logs` only unbuffered.
#
# Labels (from build arguments, so the image ID names them): the base digest, the pin (commit:tree), the digest of the
# staged project files (build_image.py's sources_sha256) and the wheel's sha256.
FROM ghcr.io/autowarefoundation/autoware@sha256:e656efed42f68444bca718163619f3f47c3250ced658e4b2477799fc5c967d7b

ARG SDV_BASE_DIGEST=unset
ARG SDV_PIN=unset
ARG SDV_SOURCES_SHA256=unset
ARG SDV_WHEEL_SHA256=unset

LABEL sdv.stack="1" \
      org.opencontainers.image.title="sdv-carlaif" \
      org.opencontainers.image.version="0.1.0" \
      sdv.carlaif.base_digest="${SDV_BASE_DIGEST}" \
      sdv.carlaif.pin="${SDV_PIN}" \
      sdv.carlaif.sources_sha256="${SDV_SOURCES_SHA256}" \
      sdv.carlaif.wheel_sha256="${SDV_WHEEL_SHA256}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

COPY aw-entrypoint.sh /sdv-aw/aw-entrypoint.sh
COPY src/ /tmp/sdv-carlaif/src/
RUN source /opt/ros/jazzy/setup.bash \
 && source /opt/autoware/setup.bash \
 && colcon --log-base /tmp/sdv-carlaif/log build --base-paths /tmp/sdv-carlaif/src --packages-select autoware_carla_interface --build-base /tmp/sdv-carlaif/build --install-base /opt/sdv-carlaif/install --cmake-args -DBUILD_TESTING=OFF -DCMAKE_BUILD_TYPE=Release \
 && rm -rf /tmp/sdv-carlaif \
 && chmod 0755 /sdv-aw/aw-entrypoint.sh

COPY wheel.lock /tmp/sdv-carlaif-wheel/wheel.lock
COPY wheels/ /tmp/sdv-carlaif-wheel/wheels/
RUN python3 -m venv --system-site-packages /opt/sdv-carlaif/venv \
 && /opt/sdv-carlaif/venv/bin/pip install --no-index --no-deps --require-hashes --find-links /tmp/sdv-carlaif-wheel/wheels -r /tmp/sdv-carlaif-wheel/wheel.lock \
 && rm -rf /tmp/sdv-carlaif-wheel \
 && /opt/sdv-carlaif/venv/bin/python -c "import carla, importlib.metadata as m; v = m.version('carla'); assert v == '0.10.0', v; assert carla.__file__.startswith('/opt/sdv-carlaif/venv/'), carla.__file__"

USER aw
WORKDIR /home/aw
ENTRYPOINT ["/sdv-aw/aw-entrypoint.sh"]
