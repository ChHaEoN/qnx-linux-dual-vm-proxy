"""sdv/cloud/ecrlogin.py: the pulling host's registry login through the IoT credential provider (SDV Phase 6 WP4).

NOTHING HERE REACHES AWS OR THE NETWORK. Both servers are local TLS stand-ins on 127.0.0.1, made by these tests: one for the
credential provider's endpoint, which takes the device's certificate (mutual TLS) and answers with credentials, and one for ECR's
API, which records the signed request and answers with an authorization token. Their certificates, the device's and a CA's are
made when the tests run (openssl), in the test's own directory: no key and no certificate stands in a file of the work tree.
Docker is a stand-in script of the test's own. ecrlogin.py's hooks (`connect`, `ecr_cafile`, `now`) send its two connections to
the stand-ins and fix its clock; nothing else of it is replaced.

THE SIGV4 VECTOR was computed once with botocore 1.43.111 (the breaker's dev venv, sdv/cloud/breaker/requirements-dev.lock),
signing ecrlogin.py's one request (POST / to api.ecr.us-east-1.amazonaws.com, the GetAuthorizationToken target, the JSON 1.1
content type, body {}) with documentation values: AWS's example key id AKIDEXAMPLE and its published secret, the example time
20150830T123600Z, region us-east-1, and a session token of this file's own words. botocore 1.43 reads the clock through
get_current_datetime(), which was fixed for the computation; nothing was sent. The headers botocore set are VECTOR below.

What is held: the signature is botocore's for the same request, the session token signed among the headers; the credentials
are fetched over mutual TLS with the device's certificate and key, the server held to the device directory's CA and named by
SNI; the token's proxy endpoint must be the file's registry; docker logs in by stdin, under the directory given, which must be
mode 0700; one line is printed, the token's expiry, and no host, key id, token or path; nothing is written but docker's own
file; logout runs docker's and removes that file whatever docker answered; the server is held to the endpoint's name, to the device
directory's CA alone and to TLS 1.2 at least; the module takes the standard library only.

Does not demonstrate: that the real credential provider answers so (the servers here are local stand-ins), that ECR accepts
this signature (botocore's own agreement is the evidence), or anything on the board.
"""
import ast
import base64
import datetime
import hashlib
import importlib.util
import io
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = saved
    return mod


EL = _load("sdv_cloud_ecrlogin_under_test", REPO / "sdv" / "cloud" / "ecrlogin.py")

ENDPOINT = "aexample000000.credentials.iot.us-east-1.amazonaws.com"         # the documentation prefix of tests/test_no_real_identifiers.py
REGION = "us-east-1"
REGISTRY = "123456789012.dkr.ecr.us-east-1.amazonaws.com"
ECR_API = "api.ecr.us-east-1.amazonaws.com"
KEY_ID = "AKIDEXAMPLE"
SECRET = "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"
SESSION = "the-test-session-token"
PASSWORD = "a-test-registry-password-of-no-account"
AT = datetime.datetime(2015, 8, 30, 12, 36, 0, tzinfo=datetime.timezone.utc)
EXPIRES = AT + datetime.timedelta(hours=12)
VECTOR = {
    "Authorization": ("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20150830/us-east-1/ecr/aws4_request, "
                      "SignedHeaders=content-type;host;x-amz-date;x-amz-security-token;x-amz-target, "
                      "Signature=9d00dbd7a856795f29dc572e8bfedb608cadccee8dd0adcd7513722d6a1d3933"),
    "Content-Type": "application/x-amz-json-1.1",
    "X-Amz-Date": "20150830T123600Z",
    "X-Amz-Security-Token": "the-test-session-token",
    "X-Amz-Target": "AmazonEC2ContainerRegistry_V20150921.GetAuthorizationToken",
}
LINE = "ecrlogin: logged in; the token expires at 2015-08-31T00:36:00Z\n"
SECRETS = (KEY_ID, SECRET, SESSION, PASSWORD, ENDPOINT, REGISTRY, base64.b64encode(("AWS:" + PASSWORD).encode()).decode())
POSIX = pytest.mark.skipif(os.name == "nt", reason="the pulling host is Linux: a directory's mode 0700 is a POSIX mode")

DOCKER = '''import base64, hashlib, json, os, sys
from pathlib import Path
here = Path(__file__).resolve().parent
args = sys.argv[1:]
stdin = sys.stdin.read() if "--password-stdin" in args else ""
with open(here / "docker.jsonl", "a") as f:
    f.write(json.dumps({"argv": args, "stdin_sha256": hashlib.sha256(stdin.encode()).hexdigest() if stdin else ""}) + "\\n")
if (here / "docker-fails").exists():
    sys.stderr.write("Error response from daemon: the stand-in fails\\n")
    sys.exit(1)
config = Path(args[1]) / "config.json"
if args[2] == "login":
    auth = base64.b64encode(("AWS:" + stdin.strip()).encode()).decode()
    config.write_text(json.dumps({"auths": {args[-1]: {"auth": auth}}}))
    print("Login Succeeded, and docker's warning about " + str(config))
elif args[2] == "logout":
    doc = json.loads(config.read_text())
    doc["auths"].pop(args[3], None)
    config.write_text(json.dumps(doc))
    print("Removing login credentials for " + args[3])
'''


# ------------------------------------------------------------------------------------------------ the TLS stand-ins

def openssl(cwd: Path, *args: str) -> None:
    done = subprocess.run(["openssl"] + list(args), cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")


def issue(d: Path, name: str, usage: str, names: str) -> None:
    """A certificate `name`.pem and its key `name`.key in `d`, signed by the CA (ca.pem, ca.key) that is there, with the extensions
    `names` (a subjectAltName line, or none) and the extended key usage `usage`."""
    (d / (name + ".ext")).write_text(names + "basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n"
                                     "extendedKeyUsage=%s\nauthorityKeyIdentifier=keyid,issuer\nsubjectKeyIdentifier=hash\n" % usage,
                                     encoding="ascii")
    openssl(d, "req", "-newkey", "rsa:2048", "-nodes", "-keyout", name + ".key", "-out", name + ".csr", "-subj", "/CN=the test's " + name)
    openssl(d, "x509", "-req", "-in", name + ".csr", "-CA", "ca.pem", "-CAkey", "ca.key", "-CAcreateserial", "-out", name + ".pem",
            "-days", "2", "-extfile", name + ".ext")


@pytest.fixture(scope="module")
def pki(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A CA, a server certificate for the two stand-ins' names and a client certificate for the device, all made now."""
    if shutil.which("openssl") is None:
        pytest.skip("openssl is not on PATH: the TLS stand-ins' certificates cannot be made")
    d = tmp_path_factory.mktemp("pki")
    openssl(d, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "ca.key", "-out", "ca.pem", "-days", "2", "-subj",
            "/CN=ecrlogin test CA", "-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,keyCertSign,cRLSign",
            "-addext", "subjectKeyIdentifier=hash")
    issue(d, "server", "serverAuth", "subjectAltName=DNS:%s,DNS:%s\n" % (ENDPOINT, ECR_API))
    issue(d, "device", "clientAuth", "")
    return d


class StandIn:
    """One TLS server on 127.0.0.1 in a thread: each connection is one HTTP request, recorded, and answered by `answer`."""

    def __init__(self, pki: Path, answer: Callable[[Dict[str, Any]], Tuple[int, bytes]], client_cert: bool) -> None:
        self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.ctx.load_cert_chain(str(pki / "server.pem"), str(pki / "server.key"))
        self.names: List[Optional[str]] = []
        self.ctx.sni_callback = lambda sock, name, ctx: self.names.append(name)          # type: ignore[assignment]
        if client_cert:
            self.ctx.verify_mode = ssl.CERT_REQUIRED
            self.ctx.load_verify_locations(str(pki / "ca.pem"))
        self.answer = answer
        self.requests: List[Dict[str, Any]] = []
        self.failures: List[str] = []
        self.sock = socket.create_server(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self) -> None:
        while True:
            try:
                raw, _peer = self.sock.accept()
            except OSError:
                return
            try:
                with self.ctx.wrap_socket(raw, server_side=True) as conn:
                    f = conn.makefile("rb")
                    method, path, _version = f.readline().decode("ascii").split()
                    headers: Dict[str, str] = {}
                    for line in iter(f.readline, b"\r\n"):
                        name, _sep, value = line.decode("ascii").partition(":")
                        headers[name.strip().lower()] = value.strip()
                    body = f.read(int(headers.get("content-length", "0")))
                    peer = conn.getpeercert()
                    req = {"method": method, "path": path, "headers": headers, "body": body, "client": peer}
                    self.requests.append(req)
                    status, data = self.answer(req)
                    conn.sendall(b"HTTP/1.1 %d X\r\nContent-Type: application/json\r\nContent-Length: %d\r\nConnection: close\r\n\r\n"
                                 % (status, len(data)) + data)
            except (OSError, ValueError, ssl.SSLError) as e:
                self.failures.append(type(e).__name__)

    def close(self) -> None:
        self.sock.close()


def credentials_answer(req: Dict[str, Any]) -> Tuple[int, bytes]:
    return 200, json.dumps({"credentials": {"accessKeyId": KEY_ID, "secretAccessKey": SECRET, "sessionToken": SESSION,
                                            "expiration": "2015-08-30T13:36:00Z"}}).encode()


def ecr_answer(proxy: str = "https://" + REGISTRY, token: str = "") -> Callable[[Dict[str, Any]], Tuple[int, bytes]]:
    token = token or base64.b64encode(("AWS:" + PASSWORD).encode()).decode()
    return lambda req: (200, json.dumps({"authorizationData": [{"authorizationToken": token, "expiresAt": EXPIRES.timestamp(),
                                                                 "proxyEndpoint": proxy}]}).encode())


class Site:
    """A test's directory: the device directory (the connector's file names), the host's file of ecr-config's keys, docker's
    directory (mode 0700) and the docker stand-in; and the two stand-ins once started."""

    def __init__(self, base: Path, pki: Path) -> None:
        self.base = base
        self.device = base / "device"
        self.device.mkdir()
        for name, src in (("device.crt", "device.pem"), ("device.key", "device.key"), ("ca.pem", "ca.pem")):
            shutil.copyfile(str(pki / src), str(self.device / name))
        self.config = base / "ecr.json"
        self.config.write_text(json.dumps({"credential_endpoint": ENDPOINT, "role_alias": "sdv-twin-ecr-pull", "region": REGION,
                                           "registry": REGISTRY}), encoding="ascii")
        self.docker_dir = base / "docker"
        self.docker_dir.mkdir()
        os.chmod(str(self.docker_dir), 0o700)
        self.stand_in = base / "stand-in"
        self.stand_in.mkdir()
        (self.stand_in / "docker.py").write_text(DOCKER, encoding="utf-8")
        self.pki = pki
        self.creds: Optional[StandIn] = None
        self.ecr: Optional[StandIn] = None

    def start(self, ecr: Optional[Callable[[Dict[str, Any]], Tuple[int, bytes]]] = None,
              creds: Callable[[Dict[str, Any]], Tuple[int, bytes]] = credentials_answer) -> "Site":
        self.creds = StandIn(self.pki, creds, client_cert=True)
        self.ecr = StandIn(self.pki, ecr or ecr_answer(), client_cert=False)
        return self

    def hooks(self) -> Dict[str, Any]:
        assert self.creds is not None and self.ecr is not None
        return {"connect": {ENDPOINT: ("127.0.0.1", self.creds.port), ECR_API: ("127.0.0.1", self.ecr.port)},
                "ecr_cafile": str(self.pki / "ca.pem"), "now": AT}

    def docker(self) -> str:
        return " ".join([Path(sys.executable).as_posix(), (self.stand_in / "docker.py").as_posix()])

    def docker_log(self) -> List[Dict[str, Any]]:
        p = self.stand_in / "docker.jsonl"
        return [json.loads(x) for x in p.read_text(encoding="utf-8").split("\n") if x.strip()] if p.is_file() else []

    def login(self, *more: str, hooks: Optional[Dict[str, Any]] = None) -> Tuple[int, str, str]:
        return run(["login", "--config", str(self.config), "--device", str(self.device), "--docker-config", str(self.docker_dir),
                    "--docker", self.docker()] + list(more), self.hooks() if hooks is None else hooks)

    def close(self) -> None:
        for s in (self.creds, self.ecr):
            if s is not None:
                s.close()


def run(argv: List[str], hooks: Optional[Dict[str, Any]] = None) -> Tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    saved = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = EL.main(argv, hooks=hooks)
    finally:
        sys.stdout, sys.stderr = saved
    return rc, out.getvalue(), err.getvalue()


@pytest.fixture
def site(tmp_path: Path, pki: Path) -> Any:
    s = Site(tmp_path, pki)
    yield s
    s.close()


# ------------------------------------------------------------------------------------------------ the signature

def test_the_signature_is_botocores_for_the_same_request_with_the_session_token_signed() -> None:
    headers = EL.sign(ECR_API, REGION, b"{}", {"accessKeyId": KEY_ID, "secretAccessKey": SECRET, "sessionToken": SESSION}, "20150830T123600Z")
    assert {k: v for k, v in headers.items() if k != "Host"} == VECTOR and headers["Host"] == ECR_API
    # without the session token among the signed headers the signature is another
    assert "x-amz-security-token" in VECTOR["Authorization"]
    other = EL.sign(ECR_API, REGION, b"{}", {"accessKeyId": KEY_ID, "secretAccessKey": SECRET, "sessionToken": SESSION + "x"},
                    "20150830T123600Z")
    assert other["Authorization"] != VECTOR["Authorization"]


def test_the_module_takes_the_standard_library_only_and_names_the_hosts_paths_and_constants_of_the_spec() -> None:
    tree = ast.parse((REPO / "sdv" / "cloud" / "ecrlogin.py").read_text(encoding="utf-8"))
    imported = {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    imported |= {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    stdlib = set(getattr(sys, "stdlib_module_names", ())) | {"__future__"}
    assert imported and imported <= stdlib, imported - stdlib
    assert EL.ROLE_ALIAS == "sdv-twin-ecr-pull" and EL.DOCKER_CONFIG_DIR == "/run/sdv-local/ota/docker"
    assert EL.DEVICE_FILES == ("device.crt", "device.key", "ca.pem")
    assert EL.CONFIG_KEYS == ("credential_endpoint", "role_alias", "region", "registry")


# ------------------------------------------------------------------------------------------------ the login

@POSIX
def test_login_fetches_the_credentials_over_mutual_tls_signs_one_ecr_call_and_logs_docker_in_by_stdin(site: Site) -> None:
    site.start()
    rc, out, err = site.login()
    assert (rc, out, err) == (0, LINE, "")
    assert site.creds is not None and site.ecr is not None
    # the credential provider: the device's certificate presented, SNI the endpoint, the alias's path, no body
    req, = site.creds.requests
    assert (req["method"], req["path"], req["body"]) == ("GET", "/role-aliases/sdv-twin-ecr-pull/credentials", b"")
    assert req["headers"]["host"] == ENDPOINT and site.creds.names == [ENDPOINT]
    assert dict(x[0] for x in req["client"]["subject"]) == {"commonName": "the test's device"}
    # ECR: one signed POST, the session token signed as x-amz-security-token
    req, = site.ecr.requests
    assert (req["method"], req["path"], req["body"]) == ("POST", "/", b"{}") and site.ecr.names == [ECR_API]
    h = req["headers"]
    assert {k: h[k.lower()] for k in VECTOR} == VECTOR and h["host"] == ECR_API
    # docker: logged in under the directory given, the password by stdin and on no argv
    call, = site.docker_log()
    assert call["argv"] == ["--config", str(site.docker_dir), "login", "--username", "AWS", "--password-stdin", REGISTRY]
    assert call["stdin_sha256"] == hashlib.sha256((PASSWORD + "\n").encode()).hexdigest() or \
        call["stdin_sha256"] == hashlib.sha256(PASSWORD.encode()).hexdigest()
    # nothing is written but docker's own file; and nothing of the exchange is printed
    written = sorted(str(p.relative_to(site.base)) for p in site.base.rglob("*") if p.is_file())
    assert [w for w in written if not w.startswith(("device", "stand-in"))] == ["docker/config.json", "ecr.json"]
    for p in site.base.rglob("*"):
        if p.is_file() and p.name != "config.json":
            data = p.read_bytes()
            assert not [s for s in SECRETS[:4] if s.encode() in data and p.name != "docker.py"], p
    assert not [s for s in SECRETS if s in out + err] and str(site.base) not in out + err
    assert site.creds.failures == [] and site.ecr.failures == []


@POSIX
def test_a_token_whose_proxy_endpoint_is_another_registry_is_refused_and_docker_is_not_called(site: Site) -> None:
    site.start(ecr=ecr_answer(proxy="https://111122223333.dkr.ecr.us-east-1.amazonaws.com"))
    rc, out, err = site.login()
    assert rc == 1 and out == "" and "ecrlogin: refused: registry-not-the-files:" in err
    assert site.docker_log() == [] and not (site.docker_dir / "config.json").exists()
    assert not [s for s in SECRETS + ("111122223333",) if s in err]


@POSIX
@pytest.mark.parametrize("token,name", [(base64.b64encode(b"root:x").decode(), "token-unreadable"), ("not base64 at all", "token-unreadable")])
def test_a_token_that_is_no_aws_password_is_refused(site: Site, token: str, name: str) -> None:
    site.start(ecr=ecr_answer(token=token))
    rc, out, err = site.login()
    assert rc == 1 and "ecrlogin: refused: %s:" % name in err and site.docker_log() == []


# c17: a reply with more than one authorizationData is no token
@POSIX
def test_a_reply_with_two_tokens_is_refused_and_docker_is_not_called(site: Site) -> None:
    one = json.loads(ecr_answer()({})[1])["authorizationData"][0]
    site.start(ecr=lambda req: (200, json.dumps({"authorizationData": [one, dict(one)]}).encode()))
    rc, out, err = site.login()
    assert rc == 1 and out == "" and "ecrlogin: refused: token-unreadable:" in err and site.docker_log() == []
    assert not [s for s in SECRETS if s in err]


@POSIX
@pytest.mark.parametrize("side,status,said", [("creds", 403, "ecrlogin: refused: credentials-refused: the credential provider answered HTTP 403"),
                                              ("ecr", 400, "ecrlogin: refused: token-refused: ECR's API answered HTTP 400")])
def test_an_error_status_from_either_server_is_refused_by_its_status_alone(site: Site, side: str, status: int, said: str) -> None:
    def answer(req: Dict[str, Any]) -> Tuple[int, bytes]:
        return status, b"{}"

    site.start(**({"creds": answer} if side == "creds" else {"ecr": answer}))
    rc, out, err = site.login()
    assert rc == 1 and out == "" and said in err and site.docker_log() == [] and not [s for s in SECRETS if s in err]
    if side == "creds":
        assert site.ecr is not None and site.ecr.requests == []


@pytest.mark.parametrize("missing", ["the-credential-endpoint", "ecrs-api"])
def test_a_connect_hook_that_names_no_stand_in_for_a_host_is_refused_before_any_socket_is_opened(site: Site, monkeypatch: pytest.MonkeyPatch,
                                                                                                  missing: str) -> None:
    """fable#6: with the tests' `connect` hook given, a host it names no stand-in for is refused (stand-in-missing) before anything is
    connected: never the real host, and never a request signed with a stand-in's credentials on its way to one."""
    tried: List[Any] = []

    def no_socket(address: Any, *args: Any, **kwargs: Any) -> Any:
        tried.append(address)
        raise OSError("the test opens no socket")

    monkeypatch.setattr(EL.socket, "create_connection", no_socket)
    connect = {ENDPOINT: ("127.0.0.1", 9), ECR_API: ("127.0.0.1", 9)}
    del connect[ENDPOINT if missing == "the-credential-endpoint" else ECR_API]
    rc, out, err = site.login(hooks={"connect": connect, "ecr_cafile": str(site.pki / "ca.pem"), "now": AT})
    assert rc == 1 and out == "" and "ecrlogin: refused: stand-in-missing:" in err and tried == []
    assert site.docker_log() == [] and not [s for s in SECRETS if s in err]


@POSIX
def test_a_server_the_device_directorys_ca_does_not_sign_is_refused(site: Site, tmp_path: Path) -> None:
    other = tmp_path / "other-ca"
    other.mkdir()
    openssl(other, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "ca.key", "-out", "ca.pem", "-days", "2", "-subj", "/CN=other CA",
            "-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,keyCertSign,cRLSign")
    shutil.copyfile(str(other / "ca.pem"), str(site.device / "ca.pem"))
    site.start()
    rc, out, err = site.login()
    assert rc == 1 and "ecrlogin: refused: credentials-unreachable:" in err and site.docker_log() == []
    assert site.ecr is not None and site.ecr.requests == []


@POSIX
def test_a_server_whose_certificate_is_signed_by_the_device_directorys_ca_for_another_host_name_is_refused(site: Site, tmp_path: Path) -> None:
    """verify#27: the server is held to the endpoint's NAME as well as to the CA: a certificate the right CA signed for another host
    name (the stand-in's, here) gets no request, and nothing reaches ECR or docker."""
    other = tmp_path / "pki-another-name"
    other.mkdir()
    for name in ("ca.pem", "ca.key"):
        shutil.copyfile(str(site.pki / name), str(other / name))
    issue(other, "server", "serverAuth", "subjectAltName=DNS:another-name.example.com\n")
    site.pki = other
    site.start()
    rc, out, err = site.login()
    assert rc == 1 and out == "" and "ecrlogin: refused: credentials-unreachable:" in err and "SSLCertVerificationError" in err
    assert site.creds is not None and site.creds.requests == [] and site.ecr is not None and site.ecr.requests == []
    assert site.docker_log() == [] and not [s for s in SECRETS if s in err]


def credentials_made(site: Site, monkeypatch: pytest.MonkeyPatch) -> Tuple[List[Tuple[str, Tuple[Any, ...], Dict[str, Any]]], Any]:
    """`credentials()` run with `https` replaced by a function that answers with credentials: (what was asked of the ssl module to build
    the TLS context, the context that went to `https`). Recorded: the call that makes the context, the loads of trust anchors made on
    it afterwards and every assignment of a minimum protocol version."""
    events: List[Tuple[str, Tuple[Any, ...], Dict[str, Any]]] = []
    real = ssl.create_default_context
    prop: Any = ssl.SSLContext.__dict__["minimum_version"]               # the property the module's assignment goes through

    def watch(context: ssl.SSLContext, name: str) -> None:
        orig = getattr(context, name)

        def wrapped(*a: Any, **k: Any) -> Any:
            events.append((name, a, k))
            return orig(*a, **k)
        setattr(context, name, wrapped)

    def spy(*args: Any, **kwargs: Any) -> ssl.SSLContext:
        context = real(*args, **kwargs)
        events.append(("create_default_context", args, kwargs))
        for name in ("load_default_certs", "load_verify_locations", "set_default_verify_paths"):
            watch(context, name)
        return context

    def set_minimum(self: ssl.SSLContext, value: ssl.TLSVersion) -> None:
        events.append(("minimum_version", (value,), {}))
        prop.fset(self, value)

    got: List[Any] = []

    def https(host: str, method: str, path: str, headers: Dict[str, str], body: bytes, context: ssl.SSLContext,
              address: Optional[Tuple[str, int]]) -> Tuple[int, bytes]:
        got.append(context)
        return 200, credentials_answer({})[1]

    monkeypatch.setattr(EL.ssl, "create_default_context", spy)
    monkeypatch.setattr(ssl.SSLContext, "minimum_version", property(prop.fget, set_minimum))
    monkeypatch.setattr(EL, "https", https)
    creds = EL.credentials(ENDPOINT, {name: str(site.device / name) for name in EL.DEVICE_FILES})
    assert creds == {"accessKeyId": KEY_ID, "secretAccessKey": SECRET, "sessionToken": SESSION} and len(got) == 1
    return events, got[0]


def test_the_credential_providers_server_is_held_to_the_device_directorys_ca_alone_by_name_and_by_chain(site: Site,
                                                                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    """verify#26 and #27 (the settings): the context is made from that CA file and from nothing else (no system store, loaded at
    creation or after it), requires a verified certificate and checks the host name."""
    events, context = credentials_made(site, monkeypatch)
    assert [e for e in events if e[0] != "minimum_version"] == [("create_default_context", (), {"cafile": str(site.device / "ca.pem")})]
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname is True


def test_the_credential_providers_connection_asks_for_tls_1_2_at_least_whatever_the_pythons_default(site: Site,
                                                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    """verify#28: the minimum protocol version is set by this module, and not left to the Python's or OpenSSL's default."""
    events, context = credentials_made(site, monkeypatch)
    assert [e for e in events if e[0] == "minimum_version"] == [("minimum_version", (ssl.TLSVersion.TLSv1_2,), {})]
    assert context.minimum_version == ssl.TLSVersion.TLSv1_2


@POSIX
def test_a_docker_directory_that_is_not_mode_0700_is_refused_before_anything_is_sent(site: Site) -> None:
    os.chmod(str(site.docker_dir), 0o755)
    site.start()
    rc, _out, err = site.login()
    assert rc == 1 and "ecrlogin: refused: docker-config-not-0700:" in err
    assert site.creds is not None and site.creds.requests == [] and site.docker_log() == []
    shutil.rmtree(str(site.docker_dir))
    rc, _out, err = site.login()
    assert rc == 1 and "ecrlogin: refused: docker-config-not-0700:" in err


@POSIX
@pytest.mark.parametrize("key,value", [("role_alias", "another-alias"), ("registry", "registry.example.com"),
                                       ("credential_endpoint", "credentials.example.com"), ("region", "Europe"),
                                       ("extra", "an-unknown-keys-value"),
                                       # verify#25: a registry in its form, in a region other than the file's (us-east-1)
                                       ("registry", "123456789012.dkr.ecr.eu-west-1.amazonaws.com")])
def test_the_hosts_file_is_held_to_its_four_keys_and_their_forms_and_a_refusal_names_the_key_only(site: Site, key: str, value: str) -> None:
    doc = json.loads(site.config.read_text(encoding="ascii"))
    doc[key] = value
    site.config.write_text(json.dumps(doc), encoding="ascii")
    site.start()
    rc, out, err = site.login()
    assert rc == 1 and "ecrlogin: refused: config-refused:" in err and value not in err
    assert site.creds is not None and site.creds.requests == []


@POSIX
def test_a_device_file_that_is_missing_is_refused_by_its_name(site: Site) -> None:
    (site.device / "device.key").unlink()
    site.start()
    rc, _out, err = site.login()
    assert rc == 1 and "ecrlogin: refused: device-file-missing: device.key" in err and str(site.base) not in err


@POSIX
def test_a_docker_login_that_fails_is_said_by_its_exit_and_nothing_of_its_words(site: Site) -> None:
    (site.stand_in / "docker-fails").write_text("", encoding="ascii")
    site.start()
    rc, out, err = site.login()
    assert rc == 1 and "ecrlogin: refused: docker-login-failed: docker exited 1" in err and "stand-in fails" not in err


@POSIX
def test_logout_runs_dockers_for_each_registry_in_its_file_removes_the_file_and_prints_no_host(site: Site) -> None:
    site.start()
    assert site.login()[0] == 0
    rc, out, err = run(["logout", "--docker-config", str(site.docker_dir), "--docker", site.docker()])
    assert (rc, err) == (0, "") and out == "ecrlogin: logged out; docker's file in the directory is removed\n"
    assert site.docker_log()[-1]["argv"] == ["--config", str(site.docker_dir), "logout", REGISTRY]
    assert not (site.docker_dir / "config.json").exists() and site.docker_dir.is_dir()
    rc, out, err = run(["logout", "--docker-config", str(site.docker_dir), "--docker", site.docker()])
    assert rc == 0 and out == "ecrlogin: nothing to log out of: docker's file is not in the directory\n"


@POSIX
def test_a_logout_whose_docker_fails_still_removes_dockers_file_and_still_exits_1(site: Site) -> None:
    """verify#2: `docker logout` is asked for each registry, and the file that holds the login is removed whatever docker answered:
    a failed logout is said (exit 1, by its exit code) and leaves no token behind in the directory."""
    site.start()
    assert site.login()[0] == 0 and (site.docker_dir / "config.json").is_file()
    (site.stand_in / "docker-fails").write_text("", encoding="ascii")
    rc, out, err = run(["logout", "--docker-config", str(site.docker_dir), "--docker", site.docker()])
    assert rc == 1 and out == "" and "ecrlogin: refused: docker-logout-failed: docker exited 1" in err and "stand-in fails" not in err
    assert site.docker_log()[-1]["argv"] == ["--config", str(site.docker_dir), "logout", REGISTRY]
    assert not (site.docker_dir / "config.json").exists() and site.docker_dir.is_dir()
    assert not [s for s in SECRETS if s in err]


def test_the_default_docker_directory_is_the_updaters_and_an_error_no_check_names_prints_its_kind_only(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: Dict[str, Any] = {}

    def fake(config: str, device: str, docker_config: str, docker: List[str], **hooks: Any) -> str:
        seen.update(config=config, docker_config=docker_config, docker=docker)
        raise RuntimeError("words that hold " + SECRET)

    monkeypatch.setattr(EL, "login", fake)
    rc, out, err = run(["login", "--config", "c.json", "--device", "d"])
    assert seen == {"config": "c.json", "docker_config": "/run/sdv-local/ota/docker", "docker": ["docker"]}
    assert rc == 1 and out == "" and err == "ecrlogin: stopped on an error no check names (RuntimeError); nothing was written but what docker wrote\n"
