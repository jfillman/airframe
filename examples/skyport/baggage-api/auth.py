"""Bearer-token auth for baggage-api's API (Skyport part 5).

Tokens are JWTs issued by Skyport's shared Dex server (skyport-auth) with the client_credentials
grant. A request is let through when its `Authorization: Bearer <jwt>` header carries a token that
is signed by a key in Dex's published key set (JWKS), has not expired, and (when configured) comes
from the expected issuer. Dex's client_credentials grant has no per-client scopes, so any valid Dex
token is accepted.

Configuration, from this app's Dex attach component (airframe xrds/dex.meta.yaml outputs jwksUrl and
issuer, wired with fromComponent):
    OAUTH_JWKS_URL   required to enforce; unset means nothing is enforced (logged at startup)
    OAUTH_ISSUER     checked when set

Open, always: /healthz (the probes), /api/whoami (version and pod), and the root endpoint list.

The key set is fetched on the first request that needs it and cached (PyJWT's PyJWKClient), so
Dex being down at startup doesn't stop the app; such requests are refused until it answers.
"""
import logging

import jwt

log = logging.getLogger("auth")

OPEN_PATHS = frozenset({"/", "/healthz", "/api/whoami"})
ALGORITHMS = ["RS256"]  # what Dex signs with


class Unauthorized(Exception):
    """The request is not authenticated; the message says why (never echoes the token)."""


class Verifier:
    def __init__(self, jwks_url=None, issuer=None, jwk_client=None, leeway=30):
        self.enabled = bool(jwks_url) or jwk_client is not None
        self.issuer = issuer or None
        self.leeway = leeway
        self._jwks = jwk_client or (jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=300) if jwks_url else None)

    @classmethod
    def from_env(cls, env):
        v = cls(env.get("OAUTH_JWKS_URL"), env.get("OAUTH_ISSUER"))
        if not v.enabled:
            log.warning("OAUTH_JWKS_URL is not set: the API is NOT protected")
        return v

    def requires_auth(self, path):
        return self.enabled and path not in OPEN_PATHS

    def check(self, authorization):
        """Returns the token's claims, or raises Unauthorized."""
        if not authorization or not authorization.startswith("Bearer "):
            raise Unauthorized("missing bearer token")
        token = authorization[len("Bearer "):].strip()
        try:
            key = self._jwks.get_signing_key_from_jwt(token).key
        except jwt.PyJWKClientError as e:
            raise Unauthorized("signing key not found: %s" % e) from e
        except jwt.InvalidTokenError as e:
            raise Unauthorized("malformed token: %s" % e) from e
        options = {"require": ["exp"], "verify_aud": False}  # Dex sets aud to the caller's own client id
        try:
            return jwt.decode(token, key, algorithms=ALGORITHMS, issuer=self.issuer, leeway=self.leeway,
                              options=options)
        except jwt.InvalidTokenError as e:
            raise Unauthorized("invalid token: %s" % e) from e
