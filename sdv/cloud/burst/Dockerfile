# Dockerfile -- the burst tool's own image, twin-burst: TEST ONLY (sdv/cloud/burst; SDV Phase 4, the burst-tool contract)
#
# Built by sdv/connector/build_image.py build --burst, never from the repo root and
# never by hand: that script stages a context outside the repo holding this file, the connector's x86_64 lock as
# requirements.lock, and app/ -- burst.py, burst_link.py and the four modules of the connector they import by name
# (limits.py, topics.py, uplink.py, uplink_aws.py), side by side.
#
# IT IS NOT THE CONNECTOR'S IMAGE AND SHARES NOTHING WITH IT BUT ITS INPUTS: the same base by the same index digest
# (sdv/stack/images.json, base.python) and the same lock, hash-checked, wheels only, no resolver, then `pip check`.
# It is never pinned in images.json, never part of a deploy set or a bundle, never built for arm64 and never pushed:
# the PC runs it, by the ID its build printed, on the owner's go and at the local test broker. The connector's image
# holds no file of this directory.
#
# What the image holds of a device: nothing. No endpoint, no name, no key, no certificate, no CA file, no thresholds
# file: the device directory, the thresholds directory and the state directory are mounted when it is run, and the
# endpoint and the two names come in its environment file. It opens no port and has no shell script of its own.
FROM docker.io/library/python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f

LABEL sdv.burst.test_only="1" \
      org.opencontainers.image.title="twin-burst" \
      org.opencontainers.image.version="test-only"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.lock /tmp/requirements.lock
RUN pip install --require-hashes --no-deps --only-binary=:all: -r /tmp/requirements.lock \
 && pip check \
 && rm /tmp/requirements.lock

COPY app/ /app/
RUN python -c "import importlib.util, os, sys; sys.path = [p for p in sys.path if p not in ('', '/app')]; names = sorted(f[:-3] for f in os.listdir('/app') if f.endswith('.py')); bad = [n for n in names if importlib.util.find_spec(n) is not None]; sys.exit('a module of /app shadows an installed module: %s' % bad if bad or names != ['burst', 'burst_link', 'limits', 'topics', 'uplink', 'uplink_aws'] else 0)"

WORKDIR /app
USER 10001:10001
# The tool is PID 1 of its container: for that process the kernel drops a signal that has only its default handling,
# so burst.py installs its SIGINT and SIGTERM handlers before anything else (its decision 8). A signal that comes
# before the interpreter has reached main() is still not seen; `docker run --init` is the run plan's second net.
ENTRYPOINT ["python", "/app/burst.py"]
