#!/usr/bin/env python3
"""ecrlogin.py -- the pulling host's login to the twin's private registry through the IoT credential provider
(SDV Phase 6 WP4). Standard library only: it runs on the board's own Python, with no venv and no AWS CLI.

WHAT IT DOES (the image-transport contract)
  login --config FILE --device DIR [--docker-config DIR] [--docker PREFIX]
    1. FILE is the one root-only file `twinctl ecr-config` wrote for this host (D7): exactly the keys credential_endpoint,
       role_alias, region and registry, each in its form; the alias is the spec's constant sdv-twin-ecr-pull.
    2. The credentials: GET https://<credential_endpoint>/role-aliases/sdv-twin-ecr-pull/credentials over mutual TLS, with
       DIR's device.crt and device.key (the connector's file names, sdv/connector/uplink_aws.py), the server held to DIR's
       ca.pem alone, SNI the endpoint (wp0-facts C7). The reply's accessKeyId, secretAccessKey and sessionToken are kept in
       memory only.
    3. One SigV4 request (C12): POST / to api.ecr.<region>.amazonaws.com, X-Amz-Target
       AmazonEC2ContainerRegistry_V20150921.GetAuthorizationToken, Content-Type application/x-amz-json-1.1, body {}, the session
       token signed as x-amz-security-token; the server held to the system's CA store. The token decodes to AWS:<password>, and
       the reply's proxyEndpoint must name the file's registry, or nothing is given to docker.
    4. `docker --config <docker-config> login --username AWS --password-stdin <registry>`, the password on docker's stdin. The
       directory must exist and be mode 0700 (the updater's launcher makes /run/sdv-local/ota/docker so, spec 2.2); docker's own
       file in it is the one place the token is written.
    It prints ONE line, the token's expiry, and nothing else: no host, key id, token or path. A refusal names a key, a file of
    the device directory or an exit code, never a value.
  logout [--docker-config DIR] [--docker PREFIX]
    `docker --config DIR logout <registry>` for each registry docker's file in DIR names, and the file is removed whatever docker
    answered: a logout that docker refused is exit 1, and the token is gone from the directory all the same.

Exit 0, or 1 with one line on stderr. The default docker directory is the updater's (DOCKER_CONFIG_DIR, spec 2.2).

Does not demonstrate: that the real credential provider answers a certificate with no thing (wp0-facts C9, settled by B3), that
ECR accepts this signature (tests/test_sdv_ecrlogin.py holds it to botocore 1.43.111's for the same request), that a token got with
temporary credentials outlives their session (R7: a pull follows the login at once), or anything about the board: no run here
was made on it. Not secure OTA: a token and a key on a host are files.
"""
from __future__ import annotations

import argparse
import base64
import datetime
import hashlib
import hmac
import http.client
import json
import os
import re
import shlex
import socket
import ssl
import stat
import subprocess
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROLE_ALIAS = "sdv-twin-ecr-pull"
DOCKER_CONFIG_DIR = "/run/sdv-local/ota/docker"
DEVICE_FILES = ("device.crt", "device.key", "ca.pem")
CONFIG_KEYS = ("credential_endpoint", "role_alias", "region", "registry")
ECR_TARGET = "AmazonEC2ContainerRegistry_V20150921.GetAuthorizationToken"
CONTENT_TYPE = "application/x-amz-json-1.1"
TIMEOUT = 30
BODY_MAX = 1 << 20
FORMS = {
    "credential_endpoint": re.compile(r"[A-Za-z0-9-]{1,63}\.credentials\.iot\.[a-z0-9-]{1,32}\.amazonaws\.com"),
    "role_alias": re.compile(re.escape(ROLE_ALIAS)),
    "region": re.compile(r"[a-z]{2}(?:-[a-z]+)+-[0-9]"),
    "registry": re.compile(r"[0-9]{12}\.dkr\.ecr\.[a-z0-9-]{1,32}\.amazonaws\.com"),
}


class LoginError(Exception):
    """A refusal by name. Its text never holds a host, a key id, a token or a path."""

    def __init__(self, name: str, detail: str) -> None:
        super().__init__("%s: %s" % (name, detail))
        self.name = name
        self.detail = detail


def read_config(path: str) -> Dict[str, str]:
    """The host's file: one JSON object of exactly CONFIG_KEYS, each a string of its form; the registry in the file's region."""
    try:
        with open(path, "rb") as f:
            doc = json.loads(f.read(BODY_MAX).decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        raise LoginError("config-refused", "the host's file cannot be read as one JSON object") from None
    if not isinstance(doc, dict) or sorted(doc) != sorted(CONFIG_KEYS):
        raise LoginError("config-refused", "the host's file does not hold exactly the keys %s" % ", ".join(CONFIG_KEYS))
    for key in CONFIG_KEYS:
        if not isinstance(doc[key], str) or not FORMS[key].fullmatch(doc[key]):
            raise LoginError("config-refused", "%s is not in its form (the value is not printed)" % key)
    if not doc["registry"].endswith(".dkr.ecr.%s.amazonaws.com" % doc["region"]):
        raise LoginError("config-refused", "registry is not in the file's region (the values are not printed)")
    return {k: str(doc[k]) for k in CONFIG_KEYS}


def device_files(device_dir: str) -> Dict[str, str]:
    out = {}
    for name in DEVICE_FILES:
        path = os.path.join(device_dir, name)
        if not os.path.isfile(path):
            raise LoginError("device-file-missing", "%s is not in the device directory" % name)
        out[name] = path
    return out


def https(host: str, method: str, path: str, headers: Dict[str, str], body: bytes, context: ssl.SSLContext,
          address: Optional[Tuple[str, int]]) -> Tuple[int, bytes]:
    """One HTTPS request to `host`, SNI and Host the host, over a connection to `address` when one is given (the tests' stand-ins)
    or to the host itself on 443; (the status, the body)."""
    sock = socket.create_connection(address or (host, 443), timeout=TIMEOUT)
    with context.wrap_socket(sock, server_hostname=host) as conn:
        head = "%s %s HTTP/1.1\r\nHost: %s\r\n" % (method, path, host)
        head += "".join("%s: %s\r\n" % (k, v) for k, v in headers.items() if k != "Host")
        head += "Content-Length: %d\r\nConnection: close\r\n\r\n" % len(body)
        conn.sendall(head.encode("ascii") + body)
        resp = http.client.HTTPResponse(conn)                    # type: ignore[arg-type]
        resp.begin()
        return resp.status, resp.read(BODY_MAX)


def credentials(endpoint: str, files: Dict[str, str], address: Optional[Tuple[str, int]] = None) -> Dict[str, str]:
    """The role alias's temporary credentials from the credential provider, over mutual TLS (wp0-facts C1, C7)."""
    context = ssl.create_default_context(cafile=files["ca.pem"])     # this CA alone: no system store
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    try:
        context.load_cert_chain(files["device.crt"], files["device.key"])
    except (OSError, ssl.SSLError):
        raise LoginError("device-files-refused", "device.crt and device.key are not a certificate and its key") from None
    try:
        status, body = https(endpoint, "GET", "/role-aliases/%s/credentials" % ROLE_ALIAS, {}, b"", context, address)
    except (OSError, ssl.SSLError, http.client.HTTPException) as e:
        raise LoginError("credentials-unreachable", "the credential provider was not reached over mutual TLS (%s)" % type(e).__name__) from None
    if status != 200:
        raise LoginError("credentials-refused", "the credential provider answered HTTP %d" % status)
    try:
        got = json.loads(body.decode("utf-8"))["credentials"]
        creds = {k: got[k] for k in ("accessKeyId", "secretAccessKey", "sessionToken")}
        if not all(isinstance(v, str) and v for v in creds.values()):
            raise TypeError
    except (UnicodeDecodeError, ValueError, KeyError, TypeError):
        raise LoginError("credentials-unreadable", "the credential provider's reply holds no credentials in their form") from None
    return creds


def sign(host: str, region: str, body: bytes, creds: Dict[str, str], amz_date: str) -> Dict[str, str]:
    """The headers of ECR's GetAuthorizationToken, signed by SigV4 for service ecr: the canonical request over content-type, host,
    x-amz-date, x-amz-security-token and x-amz-target, the key derived from the secret over the date, the region, the service and
    aws4_request (the IAM user guide's create-signed-request page; held to botocore by the tests)."""
    date = amz_date[:8]
    headers = {"Content-Type": CONTENT_TYPE, "Host": host, "X-Amz-Date": amz_date, "X-Amz-Security-Token": creds["sessionToken"],
               "X-Amz-Target": ECR_TARGET}
    canon = sorted((k.lower(), " ".join(v.split())) for k, v in headers.items())
    signed = ";".join(k for k, _v in canon)
    request = "\n".join(["POST", "/", ""] + ["%s:%s" % kv for kv in canon] + ["", signed, hashlib.sha256(body).hexdigest()])
    scope = "%s/%s/ecr/aws4_request" % (date, region)
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(request.encode("utf-8")).hexdigest()])
    key = ("AWS4" + creds["secretAccessKey"]).encode("utf-8")
    for part in (date, region, "ecr", "aws4_request"):
        key = hmac.new(key, part.encode("utf-8"), hashlib.sha256).digest()
    signature = hmac.new(key, to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    headers["Authorization"] = "AWS4-HMAC-SHA256 Credential=%s/%s, SignedHeaders=%s, Signature=%s" % (creds["accessKeyId"], scope, signed, signature)
    return headers


def authorization(config: Dict[str, str], creds: Dict[str, str], now: datetime.datetime, address: Optional[Tuple[str, int]] = None,
                  cafile: Optional[str] = None) -> Tuple[str, datetime.datetime]:
    """ECR's authorization token, by the one signed request: (the registry's password, the token's expiry). The token decodes to
    AWS:<password>, and its proxyEndpoint names the file's registry, or it is refused."""
    host = "api.ecr.%s.amazonaws.com" % config["region"]
    headers = sign(host, config["region"], b"{}", creds, now.astimezone(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    context = ssl.create_default_context(cafile=cafile)              # the system's store, unless a test names its stand-in's CA
    try:
        status, body = https(host, "POST", "/", headers, b"{}", context, address)
    except (OSError, ssl.SSLError, http.client.HTTPException) as e:
        raise LoginError("registry-unreachable", "ECR's API was not reached (%s)" % type(e).__name__) from None
    if status != 200:
        raise LoginError("token-refused", "ECR's API answered HTTP %d" % status)
    try:
        data = json.loads(body.decode("utf-8"))["authorizationData"]
        if not isinstance(data, list) or len(data) != 1:
            raise TypeError
        token, proxy, expires = data[0]["authorizationToken"], str(data[0]["proxyEndpoint"]), float(data[0]["expiresAt"])
        user, sep, password = base64.b64decode(str(token), validate=True).decode("utf-8").partition(":")
        if user != "AWS" or not sep or not password:
            raise ValueError
    except (UnicodeDecodeError, ValueError, KeyError, TypeError, IndexError):
        raise LoginError("token-unreadable", "ECR's reply holds no token that decodes to AWS:<password>") from None
    if proxy.split("://", 1)[-1].rstrip("/") != config["registry"]:
        raise LoginError("registry-not-the-files", "the token's proxy endpoint is not the registry the host's file names (neither is printed): "
                         "nothing was given to docker")
    return password, datetime.datetime.fromtimestamp(expires, datetime.timezone.utc)


def docker_dir(path: str) -> None:
    """Docker's directory for the registry's login: there, a directory, mode 0700, or refused before anything is sent."""
    try:
        st = os.stat(path)
    except OSError:
        st = None
    if st is None or not stat.S_ISDIR(st.st_mode) or (st.st_mode & 0o777) != 0o700:
        raise LoginError("docker-config-not-0700", "the docker directory is not a directory of mode 0700 (the updater's launcher makes it so)")


def docker(argv: List[str], what: str, stdin: Optional[str] = None) -> None:
    """One docker command; its words are not printed (a login's and a logout's name the registry)."""
    try:
        done = subprocess.run(argv, input=(stdin or "").encode("utf-8"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise LoginError("docker-%s-failed" % what, "docker could not be run (%s)" % type(e).__name__) from None
    if done.returncode != 0:
        raise LoginError("docker-%s-failed" % what, "docker exited %d (nothing of its words is printed)" % done.returncode)


def login(config_path: str, device_dir: str, docker_config: str, docker_prefix: List[str], *, connect: Optional[Dict[str, Tuple[str, int]]] = None,
          ecr_cafile: Optional[str] = None, now: Optional[datetime.datetime] = None) -> str:
    """The login; the token's expiry, as the one line prints it. The hooks are the tests': `connect` sends a host's connection to
    another address, `ecr_cafile` names the CA ECR's API is held to, `now` fixes the signature's time. With `connect` given, a host it
    names no address for is refused before anything is connected (fable#6): a test's stand-in is never replaced by the real host."""
    config = read_config(config_path)
    host = "api.ecr.%s.amazonaws.com" % config["region"]
    if connect is not None and not all(h in connect for h in (config["credential_endpoint"], host)):
        raise LoginError("stand-in-missing", "the tests' connect hook names no stand-in for %d of the two hosts: nothing was connected "
                         "(neither is printed)" % sum(1 for h in (config["credential_endpoint"], host) if h not in connect))
    files = device_files(device_dir)
    docker_dir(docker_config)
    creds = credentials(config["credential_endpoint"], files, (connect or {}).get(config["credential_endpoint"]))
    password, expires = authorization(config, creds, now or datetime.datetime.now(datetime.timezone.utc), (connect or {}).get(host), ecr_cafile)
    docker(docker_prefix + ["--config", docker_config, "login", "--username", "AWS", "--password-stdin", config["registry"]], "login", password)
    return expires.strftime("%Y-%m-%dT%H:%M:%SZ")


def logout(docker_config: str, docker_prefix: List[str]) -> bool:
    """docker's logout for each registry docker's file names, and the file removed whatever docker answered (a failed logout is raised
    after it); False when there was no file."""
    path = os.path.join(docker_config, "config.json")
    if not os.path.isfile(path):
        return False
    try:
        with open(path, "rb") as f:
            auths = json.loads(f.read(BODY_MAX).decode("utf-8")).get("auths", {})
        hosts = sorted(str(h) for h in auths) if isinstance(auths, dict) else []
    except (OSError, UnicodeDecodeError, ValueError, AttributeError):
        hosts = []
    try:
        for host in hosts:
            docker(docker_prefix + ["--config", docker_config, "logout", host], "logout")
    finally:
        os.remove(path)                                              # the token goes whatever docker answered: the exit stays 1 if it failed
    return True


def main(argv: Optional[Sequence[str]] = None, hooks: Optional[Dict[str, Any]] = None) -> int:
    ap = argparse.ArgumentParser(prog="ecrlogin.py", description="The pulling host's registry login through the IoT credential provider.")
    sub = ap.add_subparsers(dest="command", required=True)
    li = sub.add_parser("login")
    li.add_argument("--config", required=True, metavar="FILE", help="the host's file `twinctl ecr-config` wrote")
    li.add_argument("--device", required=True, metavar="DIR", help="device.crt, device.key and ca.pem")
    lo = sub.add_parser("logout")
    for p in (li, lo):
        p.add_argument("--docker-config", default=DOCKER_CONFIG_DIR, metavar="DIR", help="docker's directory, mode 0700 (default: %(default)s)")
        p.add_argument("--docker", default="docker", metavar="PREFIX", help="docker's argv prefix")
    args = ap.parse_args(argv)
    try:
        prefix = shlex.split(args.docker)
        if args.command == "login":
            expiry = login(args.config, args.device, args.docker_config, prefix, **(hooks or {}))
            print("ecrlogin: logged in; the token expires at %s" % expiry)
        elif logout(args.docker_config, prefix):
            print("ecrlogin: logged out; docker's file in the directory is removed")
        else:
            print("ecrlogin: nothing to log out of: docker's file is not in the directory")
        return 0
    except LoginError as e:
        print("ecrlogin: refused: %s: %s" % (e.name, e.detail), file=sys.stderr)
        return 1
    except Exception as e:                                           # noqa: BLE001 - the last net: no trace, no value
        print("ecrlogin: stopped on an error no check names (%s); nothing was written but what docker wrote" % type(e).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
