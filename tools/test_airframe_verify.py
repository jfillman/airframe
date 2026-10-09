#!/usr/bin/env python3
"""Offline tests for tools/airframe-verify: a fake kubectl and a fake Dex token endpoint, no cluster.

Covers what the live runs cannot all reach: the oauthClientCredentials step end to end (token, JWKS kid
and, when python cryptography is installed, the RS256 signature), failure paths, `when` skips, stale
observedGeneration, unresolved templates, and that no Secret value ever appears in the output.

    python3 tools/test_airframe_verify.py
"""
import base64
import importlib.machinery
import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
loader = importlib.machinery.SourceFileLoader("airframe_verify", str(TOOLS / "airframe-verify"))
spec = importlib.util.spec_from_loader("airframe_verify", loader)
av = importlib.util.module_from_spec(spec)
loader.exec_module(av)

SECRET_VALUE = "s3cr3t-value-that-must-never-print"
CLIENT_SECRET = "client-secret-that-must-never-print"


def b64(s):
    return base64.b64encode(s.encode()).decode()


def b64url(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


class FakeForward:
    def __init__(self, port):
        self.local_port = port

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def errors(self, wait=0.0):
        return []


class FakeKube:
    def __init__(self, objects, http_port=None):
        self.objects = objects
        self.http_port = http_port
        self.forwards = []

    def get(self, *args):
        key = tuple(a for a in args if a != "-n")
        if key not in self.objects:
            raise av.StepError(f"Error from server (NotFound): {' '.join(key)}")
        return self.objects[key]

    def port_forward(self, ns, svc, port):
        self.forwards.append((ns, svc, port))
        return FakeForward(self.http_port)


def make_dex(sign):
    """A tiny Dex: POST /dex/token (client_credentials, Basic auth) and GET /dex/keys."""
    key = None
    jwk = {"kty": "RSA", "kid": "k1", "alg": "RS256", "use": "sig", "n": b64url(b"\x01" * 256), "e": "AQAB"}
    if sign:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        nums = key.public_key().public_numbers()
        jwk.update(n=b64url(nums.n.to_bytes(256, "big")), e=b64url(nums.e.to_bytes(3, "big")))

    def token():
        head = b64url(json.dumps({"alg": "RS256", "kid": "k1"}).encode())
        body = b64url(json.dumps({"sub": "my-client"}).encode())
        sig = key.sign(f"{head}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256()) if key else b"x"
        return f"{head}.{body}.{b64url(sig)}"

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):  # noqa: N802
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            ok = self.path == "/dex/token" and self.headers.get("Authorization") == "Basic " + b64(f"my-client:{CLIENT_SECRET}")
            body = json.dumps({"access_token": token(), "token_type": "bearer"} if ok else {"error": "invalid_client"}).encode()
            self.send_response(200 if ok else 401)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            self.send_response(200 if self.path == "/dex/keys" else 404)
            self.end_headers()
            self.wfile.write(json.dumps({"keys": [jwk]}).encode())

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def xr(mode="attach", generation=1, observed=1, reason="DexAttachReady"):
    return {"apiVersion": "catalog.hangar.io/v1alpha1", "kind": "Dex",
            "metadata": {"name": "my-client", "namespace": "app-x-dev", "generation": generation},
            "spec": {"mode": mode},
            "status": {"conditions": [{"type": "ComponentReady", "status": "True", "reason": reason, "observedGeneration": observed},
                                      {"type": "Synced", "status": "True", "reason": "ReconcileSuccess"}]}}


def contract_dex():
    contract = json.loads((TOOLS.parent / "contract" / "airframe-contract.json").read_text())
    return av.find_kind(contract, "dex")


def run(objects, http_port=None, name="my-client", mode_xr=None):
    sc, xrd = contract_dex()
    kube = FakeKube({**objects, (f"{xrd['plural']}.{xrd['group']}", "app-x-dev", name): mode_xr or xr()}, http_port)
    orig = av.Kube
    av.Kube = lambda ctx: kube  # noqa: ARG005
    try:
        return av.verify(sc, xrd, "app-x-dev", name, None), kube
    finally:
        av.Kube = orig


def creds(client_secret=CLIENT_SECRET):
    issuer = "http://dex.dex-ns.svc.cluster.local:5556/dex"
    return {("secret", "app-x-dev", "my-client-oauth-credentials"): {"data": {
        "client-id": b64("my-client"), "client-secret": b64(client_secret),
        "issuer": b64(issuer), "token-url": b64(issuer + "/token"), "jwks-url": b64(issuer + "/keys")}}}


def main():
    failures = []

    def expect(label, cond, extra=""):
        if not cond:
            failures.append(f"{label} {extra}")

    try:
        import cryptography  # noqa: F401
        sign = True
    except ImportError:
        sign = False
    dex = make_dex(sign)
    port = dex.server_address[1]

    # 1. attach: everything passes, the token is checked against the JWKS, forwarded to dex.dex-ns:5556
    results, kube = run(creds(), port)
    by = {r["id"]: r for r in results}
    expect("attach xr-ready passes", by["xr-ready"]["status"] == "pass", by["xr-ready"])
    expect("attach secret-exists passes", by["secret-exists"]["status"] == "pass", by["secret-exists"])
    expect("token-issuance passes", by["token-issuance"]["status"] == "pass", by["token-issuance"])
    expect("token-issuance port-forwards to the Dex Service from the token URL", ("dex-ns", "dex", 5556) in kube.forwards, kube.forwards)
    if sign:
        expect("signature verified", "RS256 signature verified" in by["token-issuance"]["detail"], by["token-issuance"]["detail"])
    expect("server-discovery skipped for attach", by["server-discovery"]["status"] == "skip", by["server-discovery"])
    out = json.dumps(results)
    expect("no client secret in output", CLIENT_SECRET not in out)

    # 2. a wrong client secret fails the token step, and still never prints the secret
    results, _ = run(creds("wrong-" + CLIENT_SECRET), port)
    tok = next(r for r in results if r["id"] == "token-issuance")
    expect("wrong secret fails", tok["status"] == "fail" and "401" in tok["detail"], tok)
    expect("wrong secret not printed", CLIENT_SECRET not in json.dumps(results))

    # 3. missing Secret fails secret-exists with the kubectl error, other steps still run
    results, _ = run({}, port)
    by = {r["id"]: r for r in results}
    expect("missing Secret fails", by["secret-exists"]["status"] == "fail" and "NotFound" in by["secret-exists"]["detail"], by["secret-exists"])
    expect("xr-ready still evaluated", by["xr-ready"]["status"] == "pass")

    # 4. a condition with the wrong reason fails; a stale observedGeneration is called out
    results, _ = run(creds(), port, mode_xr=xr(reason="DexAttachFailed", generation=3, observed=2))
    r0 = next(r for r in results if r["id"] == "xr-ready")
    expect("wrong reason fails", r0["status"] == "fail", r0)
    expect("stale generation reported", "observedGeneration 2 < generation 3" in r0["detail"], r0)

    # 5. secretKeys with an empty value fails and lists key names only
    s = {("secret", "app-x-dev", "my-client-oauth-credentials"): {"data": {"client-id": b64("my-client"), "client-secret": b64(""), "x": b64(SECRET_VALUE)}}}
    results, _ = run(s, port)
    se = next(r for r in results if r["id"] == "secret-exists")
    expect("empty key fails", se["status"] == "fail" and "client-secret" in se["detail"], se)
    expect("other values never printed", SECRET_VALUE not in json.dumps(results))

    # 6. unresolved {status.*} template fails with a clear message (cloud target, no status yet)
    contract = json.loads((TOOLS.parent / "contract" / "airframe-contract.json").read_text())
    sc, xrd = av.find_kind(contract, "awslambdatarget")
    bare = {"metadata": {"name": "fn", "namespace": "ns"}, "spec": {}, "status": {"conditions": []}}
    kube = FakeKube({(f"{xrd['plural']}.{xrd['group']}", "ns", "fn"): bare})
    orig = av.Kube
    av.Kube = lambda ctx: kube  # noqa: ARG005
    try:
        results = av.verify(sc, xrd, "ns", "fn", None)
    finally:
        av.Kube = orig
    fe = next(r for r in results if r["id"] == "function-exists")
    expect("unresolved status template fails clearly", fe["status"] == "fail" and "status.functionName" in fe["detail"], fe)

    # 7. Synced=False is classified: a CNPG webhook outage is named, an unknown cause is quoted, True passes (C8)
    sc, xrd = av.find_kind(contract, "postgresql")
    pg_msg = next(k for k in sc["knownFailures"] if k["id"] == "CNPGWebhookUnavailable")["example"]
    for msg, want in ((pg_msg, "CNPGWebhookUnavailable"),
                      ('cannot apply composed resource "x": failed calling webhook "vexternalsecret.kb.io": connection refused', "AdmissionWebhookUnavailable"),
                      ("cannot compose resources: something new", None)):
        x = {"metadata": {"name": "db", "namespace": "ns"}, "spec": {},
             "status": {"conditions": [{"type": "Synced", "status": "False", "reason": "ReconcileError", "message": msg},
                                       {"type": "ComponentReady", "status": "True", "reason": "PostgreSQLReady"}]}}
        r0 = av.check_synced(sc, x)
        expect(f"synced classification {want}", r0["status"] == "fail" and r0.get("knownFailure") == want
               and (want is not None or "something new" in r0["detail"]), r0)
    ok0 = av.check_synced(sc, {"status": {"conditions": [{"type": "Synced", "status": "True"}]}})
    expect("Synced=True passes", ok0["status"] == "pass", ok0)
    results, _ = run(creds(), port)
    expect("xr-synced runs first", results[0]["id"] == "xr-synced", results[0])

    # 8. every kind resolves by key, Kind and plural
    for key, sc in {**contract["components"], **contract["targets"], **contract["kinds"]}.items():
        plural = contract["xrds"][sc["kind"]]["plural"]
        for name in (key, sc["kind"], plural):
            expect(f"find_kind({name})", av.find_kind(contract, name)[0] is sc)

    dex.shutdown()
    if failures:
        print("\n".join(failures))
        print(f"\nFAIL: {len(failures)}")
        return 1
    print(f"ok: airframe-verify offline checks passed (signature check {'on' if sign else 'skipped: no cryptography'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
