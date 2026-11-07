# Dockerfile -- the hard-brake-hazard app image (sdv/apps/hard-brake-hazard)
#
# Project-written. Built by sdv/stack/stack.py (`build`) with this directory as the context; run
# by image ID, never by tag. The base is pinned by its multi-arch index digest, read once from the
# registry on 2026-09-30 (python:3.12-slim = 3.12.14-slim-trixie; sdv/stack/images.json records the
# per-arch manifest). Packages come only from requirements.lock, hash-checked, wheels only.
FROM docker.io/library/python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f

LABEL sdv.stack="1" \
      org.opencontainers.image.title="hard-brake-hazard" \
      org.opencontainers.image.version="1.0.0"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.lock /tmp/requirements.lock
RUN pip install --require-hashes --no-deps --only-binary=:all: -r /tmp/requirements.lock \
 && rm /tmp/requirements.lock

COPY hazard.py app.py appstate.schema.json /app/
WORKDIR /app
USER 10001:10001
ENTRYPOINT ["python", "/app/app.py"]
