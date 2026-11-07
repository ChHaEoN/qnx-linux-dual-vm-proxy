# Dockerfile -- the twin connector image, twin-connector (sdv/connector; SDV Phase 4 WP3)
#
# Built by sdv/connector/build_image.py, never from the repo root and never by
# hand: that script stages a context outside the repo holding this file, the architecture's lock as
# requirements.lock, and app/ -- the connector's modules side by side (they import each other by name),
# appstate.schema.json, and the frozen allowlist twin_allowlist.py, which it first holds to a fresh generation
# from the catalogue -- and builds with buildx for one platform, --provenance=false --sbom=false. The frozen
# allowlist is BAKED IN: never mounted, never read from a file at run time. The image ID then names one allowlist
# and one generation, and the labels say which (the stack refuses an image of another generation). Run by image
# ID, never by tag; never pushed to any registry.
#
# The base is the app's, the recorder's and the bridge's, by the same index digest (sdv/stack/images.json,
# base.python; python:3.12-slim = 3.12.14-slim-trixie). Packages come only from requirements.lock: hash-checked,
# wheels only, no resolver. `pip check` follows, because --no-deps would not notice a pair of packages that do
# not belong together (the SDK names one exact version of its runtime). The modules' names are plain (config,
# source, limits, ...), so the build also fails when one of them shadows a module that is installed.
#
# What the image holds of a device: nothing. No endpoint, no name, no key, no certificate, no CA file: those are
# the device directory's, mounted read-only at /run/sdv-local/device when the stack starts the container, with
# the endpoint and the two names in its environment file (--env-file). Nothing here opens a port; the image has
# no docker client and no shell script of its own. It runs as a user of its own (10001), and the stack starts it
# as the host's user with a read-only root, every capability dropped and three mounts: the spool directory
# (read-write), the status directory and the device directory (both read-only).
#
# No second entry point: the one program in /app is connector.py, whose entry point puts the limiter in front of
# the uplink. The burst tool of the breaker's test is another program in another image and is not staged here.
FROM docker.io/library/python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f

ARG SDV_ALLOWLIST_VERSION=unset
ARG SDV_ALLOWLIST_DIGEST=unset
ARG SDV_CATALOGUE_SHA256=unset

LABEL sdv.stack="1" \
      org.opencontainers.image.title="twin-connector" \
      org.opencontainers.image.version="0.1.0" \
      sdv.twin.allowlist_version="${SDV_ALLOWLIST_VERSION}" \
      sdv.twin.allowlist_digest="${SDV_ALLOWLIST_DIGEST}" \
      sdv.twin.catalogue_sha256="${SDV_CATALOGUE_SHA256}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.lock /tmp/requirements.lock
RUN pip install --require-hashes --no-deps --only-binary=:all: -r /tmp/requirements.lock \
 && pip check \
 && rm /tmp/requirements.lock

COPY app/ /app/
RUN python -c "import importlib.util, os, sys; sys.path = [p for p in sys.path if p not in ('', '/app')]; names = sorted(f[:-3] for f in os.listdir('/app') if f.endswith('.py')); bad = [n for n in names if importlib.util.find_spec(n) is not None]; sys.exit('a module of /app shadows an installed module: %s' % bad if bad or len(names) < 15 else 0)"

WORKDIR /app
USER 10001:10001
ENTRYPOINT ["python", "/app/connector.py"]
