# Dockerfile -- the kind 4 claim bridge image, vss-claim-bridge (sdv/bridge; Phase 2 WP7)
#
# Project-written. Built by sdv/bridge/build_image.py, never from the repo root: it stages a context
# outside the repo (~/sdv-cache) holding this file, requirements.lock and app/ -- the bridge's code
# (sdv/bridge: vss_claim_bridge.py, reasonsets.py, bridge_sources.py), the codec and reference rules it
# imports (sdv/frame), slice.dbc, and the generated contract with its generation manifest
# (sdv-out/gen/vss_contract.py, manifest.json), laid out as in the repo so every path the code computes
# holds -- and builds with --provenance=false --sbom=false. The contract is baked in: the image ID then
# names one generation, and the build labels its digest and the sha256 of the contract and of slice.dbc
# (SDV_GEN can still point the bridge at a mounted one). Run by image ID, never by tag.
#
# The base is the app's and the recorder's, pinned by the same index digest (sdv/stack/images.json,
# base.python; python:3.12-slim = 3.12.14-slim-trixie). Packages come only from requirements.lock,
# hash-checked, wheels only.
#
# Running it: the scenario lock is the host's file, which must exist before the run (the host's updater
# creates it, or touch it), bind-mounted at its default path with
# --mount type=bind,src=/run/lock/sdv-scenario.lock,dst=/run/lock/sdv-scenario.lock (the file itself, not a
# directory over /run/lock; not -v, which on a missing host file creates a directory there and breaks the
# host's lock path too), with the container run as the host user (--user UID:GID) so the file opens
# read-write: the flock the bridge takes is then the one the host's updater checks (one inode, so the host
# must never replace the file while a container has it mounted). The image makes the mount necessary: it
# sets SDV_SCENARIO_LOCK_MUST_EXIST=1 and leaves /run/lock writable by root only. With that setting the
# bridge takes no lock but /run/lock/sdv-scenario.lock (--lock and SDV_SCENARIO_LOCK may name no other
# path), never creates it, and refuses at start (exit 2) unless it is a regular file and a mount point
# (/proc/self/mountinfo), whatever the user, read-only root or not: a missing file, /dev/null or another
# file named by --lock, /dev/null mounted there, and a file made in a container started without the mount
# are all refused. Only an explicit act defeats it: -e SDV_SCENARIO_LOCK_MUST_EXIST=0 as root, or another
# file mounted at that path. The image has no writable run directory of its own: mount one and name it with
# --out. can mode needs the host's network namespace (SocketCAN interfaces belong to one); replay reads a
# file mounted read-only; broker mode reaches the databroker on its address.
FROM docker.io/library/python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f

ARG SDV_CATALOG_DIGEST=unset
ARG SDV_CONTRACT_SHA256=unset
ARG SDV_DBC_SHA256=unset

LABEL sdv.stack="1" \
      org.opencontainers.image.title="vss-claim-bridge" \
      org.opencontainers.image.version="0.1.0" \
      sdv.kind4.catalog_digest="${SDV_CATALOG_DIGEST}" \
      sdv.kind4.contract_sha256="${SDV_CONTRACT_SHA256}" \
      sdv.kind4.dbc_sha256="${SDV_DBC_SHA256}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SDV_SCENARIO_LOCK_MUST_EXIST=1

COPY requirements.lock /tmp/requirements.lock
RUN pip install --require-hashes --no-deps --only-binary=:all: -r /tmp/requirements.lock \
 && rm /tmp/requirements.lock \
 && chmod 0755 /run/lock

COPY app/ /app/
WORKDIR /app
USER 10001:10001
ENTRYPOINT ["python", "/app/sdv/bridge/bridge_sources.py"]
