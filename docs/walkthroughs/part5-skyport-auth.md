# Airframe quickstart part 5: skyport-auth (shared Dex OIDC provider)

Converted from [`../user/quickstart-skyport-auth.md`](../user/quickstart-skyport-auth.md).

Placeholders: `<dev-context>` are the names chosen when the clusters were built (render with `--dev-cluster` etc. to fill them in).

## function-dex is installed and healthy on the dev cluster, and the Dex XRD is established

```bash
kubectl --context "<dev-context>" get function function-dex
kubectl --context "<dev-context>" get xrd dexes.catalog.hangar.io
```

**Expected:** the Function is INSTALLED=True HEALTHY=True; the XRD is Established=True

## skyport-auth is a synced, ready InfraService

```bash
kubectl --context "<dev-context>" get infraservice skyport-auth -n app-skyport-auth-cicd
```

**Expected:** Synced/Ready True; DevClusterReady and CicdOnboarded True

## The Dex server passes its verify contract (DexServerReady, OIDC discovery answers)

```bash
kubectl --context "<dev-context>" get dexes.catalog.hangar.io skyport-auth -n app-skyport-auth-dev
tools/airframe-verify dex app-skyport-auth-dev/skyport-auth --context "<dev-context>"
```

**Expected:** COMPONENT DexServerReady; server-discovery gets 200 from /dex/.well-known/openid-configuration on 5556

## The server's NetworkPolicy opens 5556 to flight-api's and baggage-api's dev namespaces

```bash
kubectl --context "<dev-context>" get networkpolicy skyport-auth-dex-access -n app-skyport-auth-dev -o yaml
```

**Expected:** an ingress rule on 5556 from app-flight-api-dev and app-baggage-api-dev; 5557 only from crossplane-system

## flight-api's attach client is registered and mints a token the JWKS verifies

```bash
tools/airframe-verify dex app-flight-api-dev/flight-oauth --context "<dev-context>"
```

**Expected:** DexAttachReady; flight-oauth-oauth-credentials has client-id/client-secret; token-issuance passes (signature checked against the JWKS, token never printed)

## baggage-api's attach client is registered and mints a token the JWKS verifies

```bash
tools/airframe-verify dex app-baggage-api-dev/bag-oauth --context "<dev-context>"
```

**Expected:** DexAttachReady; bag-oauth-oauth-credentials has client-id/client-secret; token-issuance passes

## flight-api's pod spec carries OAUTH_ISSUER and OAUTH_JWKS_URL from the attach Secret

```bash
kubectl --context "<dev-context>" get rollout flight-api -n app-flight-api-dev -o jsonpath='{.spec.template.spec.containers[0].env[*].name}'
```

**Expected:** OAUTH_ISSUER and OAUTH_JWKS_URL are listed (present, not yet used by the code: enforcement is not built)

