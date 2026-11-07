# Dockerfile -- the ROS->VSS feeder image, ros-vss-feeder (sdv/rosvss; SDV Phase 8 WP3d)
#
# Local branch only. Built by sdv/rosvss/build_image.py, never from the repo root: it stages a context outside the repo
# (~/sdv-cache) holding this file, requirements.lock, aw-entrypoint.sh (sdv/aw's, copied in) and app/ with the feeder's
# five modules laid out as in the repo (sdv/rosvss: feeder_node.py, kuksa_out.py, mapping.py, update.py, vsswriter.py),
# and builds with --provenance=false --sbom=false. Run by image ID (sdv/stack/images.json's rosvss.amd64), never by tag.
#
# The base is Autoware's Jazzy 1.9.0 image by its amd64 manifest digest (images.json's autoware.amd64.manifest_digest,
# the Phase 8 specification's 2.6; trust on first use), amd64 only: no planned run puts the feeder on an arm64 host. It
# holds ROS 2 Jazzy, Autoware's message packages and Python 3.12, which kuksa-client 0.6.0 needs (3.11 or later), so the
# feeder is one process (D4's Jazzy branch).
#
# The image's own entrypoint never runs (2.12): it would turn the host's loopback multicast flag on and raise three
# kernel network settings whenever the container may. This image's ENTRYPOINT is the project's, sdv/aw/aw-entrypoint.sh,
# which sources the two setup files and execs its command and changes nothing outside the container. The image runs as
# the base's user aw (uid 1000); the entrypoint refuses root.
#
# The base's Python 3.12 is externally managed and has no pip, so the packages go into a venv made with
# --system-site-packages: the ROS packages come through the PYTHONPATH the setup files set, and what they import from
# the system's Python stays visible. Packages come only from requirements.lock, hash-checked, wheels only.
#
# Labels (from build arguments, so the image ID names them): the base digest, the lock's sha256 and the digest of the
# staged sources (build_image.py's sources_sha256: the five modules and the entrypoint).
FROM ghcr.io/autowarefoundation/autoware@sha256:e656efed42f68444bca718163619f3f47c3250ced658e4b2477799fc5c967d7b

ARG SDV_BASE_DIGEST=unset
ARG SDV_LOCK_SHA256=unset
ARG SDV_SOURCES_SHA256=unset

LABEL sdv.stack="1" \
      org.opencontainers.image.title="ros-vss-feeder" \
      org.opencontainers.image.version="0.1.0" \
      sdv.rosvss.base_digest="${SDV_BASE_DIGEST}" \
      sdv.rosvss.lock_sha256="${SDV_LOCK_SHA256}" \
      sdv.rosvss.sources_sha256="${SDV_SOURCES_SHA256}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY aw-entrypoint.sh /sdv-aw/aw-entrypoint.sh
COPY requirements.lock /tmp/requirements.lock
RUN python3 -m venv --system-site-packages /opt/sdv-rosvss/venv \
 && /opt/sdv-rosvss/venv/bin/pip install --require-hashes --no-deps --only-binary=:all: -r /tmp/requirements.lock \
 && rm /tmp/requirements.lock \
 && chmod 0755 /sdv-aw/aw-entrypoint.sh

COPY app/ /app/
USER aw
WORKDIR /app
ENTRYPOINT ["/sdv-aw/aw-entrypoint.sh"]
CMD ["/opt/sdv-rosvss/venv/bin/python", "/app/sdv/rosvss/feeder_node.py"]
