'use strict';
// Service-to-service tokens from Skyport's shared Dex server (skyport-auth), for calling
// flight-api. OAuth2 client_credentials (RFC 6749 4.4): POST the token URL with this app's
// client id and secret (HTTP Basic), get back a signed JWT access token, send it as
// `Authorization: Bearer ...`.
//
// The four values come from this app's Dex attach component (airframe xrds/dex.meta.yaml,
// outputs clientId/clientSecret/tokenUrl), wired in glidepath/envs/<env>.yaml with fromComponent:
//   OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET, OAUTH_TOKEN_URL
//
// The token is cached and reused until shortly before it expires (expires_in, minus a margin),
// and one refresh is shared by concurrent callers. A failed fetch is not cached: the next call
// tries again.

class TokenError extends Error {}

function clientCredentials({ tokenUrl, clientId, clientSecret, fetchImpl = fetch, now = Date.now,
  marginMs = 30_000, timeoutMs = 3000 } = {}) {
  if (!tokenUrl || !clientId || !clientSecret) {
    throw new TokenError('clientCredentials needs tokenUrl, clientId and clientSecret');
  }
  const basic = Buffer.from(`${encodeURIComponent(clientId)}:${encodeURIComponent(clientSecret)}`).toString('base64');
  let cached = null; // { token, expiresAt }
  let inflight = null;

  async function fetchToken() {
    let res;
    try {
      res = await fetchImpl(tokenUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded', Authorization: `Basic ${basic}` },
        body: 'grant_type=client_credentials',
        signal: AbortSignal.timeout(timeoutMs),
      });
    } catch (err) {
      throw new TokenError(`token endpoint unreachable: ${err.message}`);
    }
    if (!res.ok) throw new TokenError(`token endpoint answered ${res.status}`);
    const body = await res.json();
    if (!body.access_token) throw new TokenError('token endpoint answered without an access_token');
    const ttlMs = (Number(body.expires_in) > 0 ? Number(body.expires_in) : 60) * 1000;
    cached = { token: body.access_token, expiresAt: now() + Math.max(ttlMs - marginMs, 0) };
    return cached.token;
  }

  async function token() {
    if (cached && now() < cached.expiresAt) return cached.token;
    if (!inflight) inflight = fetchToken().finally(() => { inflight = null; });
    return inflight;
  }
  token.clear = () => { cached = null; };
  return token;
}

// The token source from the environment, or null when no client is configured (the app then
// calls flight-api without a token, which an enforcing flight-api refuses with 401).
function tokenFromEnv(env = process.env) {
  const { OAUTH_TOKEN_URL: tokenUrl, OAUTH_CLIENT_ID: clientId, OAUTH_CLIENT_SECRET: clientSecret } = env;
  if (!tokenUrl && !clientId && !clientSecret) return null;
  return clientCredentials({ tokenUrl, clientId, clientSecret });
}

module.exports = { clientCredentials, tokenFromEnv, TokenError };
