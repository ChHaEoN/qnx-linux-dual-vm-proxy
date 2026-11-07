# Dockerfile -- the VSS-layer recorder image (sdv/stack/recorder)
#
# Project-written. The pinned kuksa-csv-provider 0.4.6 image carries only its replayer (/dist/provider
# and a sample CSV); the recorder of that release is the source file recorder.py at the image's own
# revision (commit 30a92880), which the image does not include. sdv/stack/stack.py (`build`) fetches
# that file into a build context outside the repo (~/sdv-cache/csv-recorder-0.4.6/), checks its
# sha256 and its git blob id against the pins in images.json, copies this directory's lock beside
# it, and builds with `-f` pointing here. The file is used unmodified and never enters the repo.
#
# The csv-provider repository's requirements.txt at that commit (30a92880) declares kuksa-client ~= 0.5.2;
# recorder.py itself names no version. It runs here on 0.6.0 (the slice's one client pin), whose
# kuksa.val.v1 subscribe it uses is unchanged. The base is the app's, by the same digest.
FROM docker.io/library/python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f

LABEL sdv.stack="1" \
      org.opencontainers.image.title="kuksa-csv-provider-recorder" \
      org.opencontainers.image.version="0.4.6" \
      org.opencontainers.image.revision="30a92880914bedd7f7adf06cb7707719daab3fd4"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.lock /tmp/requirements.lock
RUN pip install --require-hashes --no-deps --only-binary=:all: -r /tmp/requirements.lock \
 && rm /tmp/requirements.lock

COPY recorder.py /app/recorder.py
WORKDIR /app
USER 10001:10001
ENTRYPOINT ["python", "/app/recorder.py"]
