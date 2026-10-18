"""Bearer-token auth (auth.py, and its wiring in main.py): 401 without a valid Dex token, 200 with
one, health paths open. Uses a locally generated RSA key standing in for Dex's."""
import importlib
import json
import os
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer

import jwt
import mongomock
from cryptography.hazmat.primitives.asymmetric import rsa

from auth import OPEN_PATHS, Unauthorized, Verifier

ISSUER = "http://skyport-auth.app-skyport-auth-dev.svc.cluster.local:5556/dex"
TRUSTED = rsa.generate_private_key(public_exponent=65537, key_size=2048)
UNTRUSTED = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeJWKClient:
    """Stands in for PyJWKClient: knows one key id, like a JWKS with one key."""

    class _Key:
        def __init__(self, key):
            self.key = key

    def get_signing_key_from_jwt(self, token):
        kid = jwt.get_unverified_header(token).get("kid")
        if kid != "test":
            raise jwt.PyJWKClientError('Unable to find a signing key that matches: "%s"' % kid)
        return self._Key(TRUSTED.public_key())


def token(key=TRUSTED, iss=ISSUER, exp_in=300, kid="test", **claims):
    now = int(time.time())
    body = {"iss": iss, "sub": "board-oauth", "aud": "board-oauth", "iat": now, "exp": now + exp_in, **claims}
    return jwt.encode(body, key, algorithm="RS256", headers={"kid": kid})


class VerifierTest(unittest.TestCase):
    def setUp(self):
        self.v = Verifier(issuer=ISSUER, jwk_client=FakeJWKClient())

    def test_valid_token(self):
        self.assertEqual(self.v.check("Bearer " + token())["sub"], "board-oauth")

    def test_missing_or_not_bearer(self):
        for h in (None, "", "Basic abc", "bearer x"):
            with self.assertRaises(Unauthorized):
                self.v.check(h)

    def test_wrong_key_expired_issuer_garbage(self):
        bad = [token(key=UNTRUSTED), token(exp_in=-600), token(iss="http://elsewhere/dex"),
               token(kid="other"), "not-a-jwt"]
        for t in bad:
            with self.assertRaises(Unauthorized, msg=t[:20]):
                self.v.check("Bearer " + t)

    def test_issuer_is_optional(self):
        v = Verifier(jwk_client=FakeJWKClient())
        self.assertTrue(v.check("Bearer " + token(iss="anything")))

    def test_disabled_without_jwks(self):
        v = Verifier.from_env({})
        self.assertFalse(v.enabled)
        self.assertFalse(v.requires_auth("/api/bags"))

    def test_open_paths(self):
        self.assertEqual(OPEN_PATHS, {"/", "/healthz", "/api/whoami"})
        self.assertFalse(self.v.requires_auth("/healthz"))
        self.assertTrue(self.v.requires_auth("/api/bags"))
        self.assertTrue(self.v.requires_auth("/api/events/status"))


class HttpTest(unittest.TestCase):
    """main.py's handler over real HTTP, MongoDB faked, auth enforced with the local key."""

    @classmethod
    def setUpClass(cls):
        os.environ["MONGODB_URI"] = "mongodb://unused"
        import baggage
        baggage.connect = lambda uri: mongomock.MongoClient().db
        sys.modules.pop("main", None)
        cls.main = importlib.import_module("main")
        cls.main.AUTH = Verifier(issuer=ISSUER, jwk_client=FakeJWKClient())
        cls.server = HTTPServer(("127.0.0.1", 0), cls.main.Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def get(self, path, tok=None):
        req = urllib.request.Request(self.base + path)
        if tok:
            req.add_header("Authorization", "Bearer " + tok)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.headers, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, e.headers, json.loads(e.read())

    def test_api_without_token_is_401_with_bearer_challenge(self):
        status, headers, body = self.get("/api/bags")
        self.assertEqual(status, 401)
        self.assertTrue(headers["WWW-Authenticate"].startswith("Bearer"))
        self.assertEqual(body, {"error": "unauthorized"})

    def test_api_with_valid_token_is_200(self):
        self.assertEqual(self.get("/api/bags", token())[0], 200)
        self.assertEqual(self.get("/api/events/status", token())[0], 200)

    def test_api_with_forged_token_is_401(self):
        self.assertEqual(self.get("/api/reroutes", token(key=UNTRUSTED))[0], 401)

    def test_health_and_whoami_stay_open(self):
        self.assertEqual(self.get("/healthz")[0], 200)
        self.assertEqual(self.get("/api/whoami")[0], 200)


if __name__ == "__main__":
    unittest.main()
