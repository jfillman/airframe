# Airframe quickstart part 5: skyport-auth (shared Dex) and enforced tokens

Converted from [`../user/quickstart-skyport-auth.md`](../user/quickstart-skyport-auth.md).

Placeholders: `<dev-context>`, `<prod-cluster>`, `<prod-context>` are the names chosen when the clusters were built (render with `--dev-cluster` etc. to fill them in).

## function-dex is installed and healthy, and the Dex XRD is established, on both clusters

```bash
kubectl --context "<dev-context>" get function function-dex
kubectl --context "<prod-context>" get function function-dex
kubectl --context "<dev-context>" get xrd dexes.catalog.hangar.io
kubectl --context "<prod-context>" get xrd dexes.catalog.hangar.io
```

**Expected:** on each cluster the Function is Installed=True Healthy=True and the XRD is Established=True (prod's come from the Apron prod profile)

## skyport-auth is a synced, ready InfraService

```bash
tools/airframe-verify infraservice infra-skyport-auth-cicd/skyport-auth --context "<dev-context>"
```

**Expected:** xr-synced, dev-cluster-ready, cicd-onboarded and gitops-repo pass

## Ground: the Dex server passes its verify contract (DexServerReady, OIDC discovery answers)

```bash
tools/airframe-verify dex infra-skyport-auth-dev/skyport-auth --context "<dev-context>"
```

**Expected:** COMPONENT DexServerReady; server-discovery gets 200 from /dex/.well-known/openid-configuration on 5556

## Ground: the server's NetworkPolicy opens 5556 to all three apps' dev namespaces, 5557 only to crossplane-system

```bash
kubectl --context "<dev-context>" get networkpolicy skyport-auth-dex-access -n infra-skyport-auth-dev -o yaml
```

**Expected:** an ingress rule on 5556 from app-flight-api-dev, app-baggage-api-dev and app-boarding-api-dev; 5557 from crossplane-system only

## Ground: each app's attach client is registered and mints a token the JWKS verifies

```bash
tools/airframe-verify dex app-flight-api-dev/flight-oauth --context "<dev-context>"
tools/airframe-verify dex app-baggage-api-dev/bag-oauth --context "<dev-context>"
tools/airframe-verify dex app-boarding-api-dev/board-oauth --context "<dev-context>"
```

**Expected:** DexAttachReady for each; client-id/client-secret present; token-issuance passes (RS256 signature checked, token never printed)

## Ground: the resource servers have OAUTH_JWKS_URL and the caller has its client settings

```bash
kubectl --context "<dev-context>" get rollout flight-api -n app-flight-api-dev -o jsonpath='{.spec.template.spec.containers[0].env[*].name}'
```

**Expected:** flight-api and baggage-api carry OAUTH_ISSUER and OAUTH_JWKS_URL; boarding-api carries OAUTH_TOKEN_URL, OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET

## Ground: flight-api refuses /api/flights without a token (401) and serves it with one (200); probes stay open

```bash
. docs/walkthroughs/lib/dex.sh
tok="$(dex_token "<dev-context>" app-boarding-api-dev board-oauth)"
expect_enforced "<dev-context>" app-flight-api-dev flight-api 8080 /api/flights/AC123 "$tok"
```

**Expected:** without a token 401, with a token 200; /actuator/health/liveness 200 without a token

## Ground: baggage-api refuses /api/bags without a token (401) and serves it with one (200); /healthz stays open

```bash
. docs/walkthroughs/lib/dex.sh
tok="$(dex_token "<dev-context>" app-boarding-api-dev board-oauth)"
expect_enforced "<dev-context>" app-baggage-api-dev baggage-api 8080 /api/bags "$tok"
```

**Expected:** without a token 401, with a token 200; /healthz 200 without a token

## Ground: boarding-api's own lookups reach the enforcing flight-api (it sends a valid token)

```bash
kubectl --context "<dev-context>" -n app-boarding-api-dev port-forward svc/boarding-api 8080:8080 &
curl -s localhost:8080/api/boarding/AC123
```

**Expected:** 200 with "source": "flight-api". With flight-api enforcing, that answer needs boarding-api to have fetched a token from Dex in-cluster and flight-api to have checked it against Dex's JWKS. A cached answer (3 minutes) only proves a lookup succeeded earlier, so the check tries seeded flights until one answers uncached.

## Flight: the staging Dex server on the prod cluster passes its verify contract

```bash
kubectl --context "<dev-context>" get applicationenvironment skyport-auth-<prod-cluster>-staging -n infra-skyport-auth-cicd
tools/airframe-verify dex infra-skyport-auth-staging/skyport-auth --context "<prod-context>"
```

**Expected:** the ApplicationEnvironment is Synced/Ready; DexServerReady and discovery 200 on the prod cluster

## Flight: each app's staging attach client is registered and mints a verifiable token

```bash
tools/airframe-verify dex app-boarding-api-staging/board-oauth --context "<prod-context>"
```

**Expected:** DexAttachReady and token-issuance pass for flight-oauth, bag-oauth and board-oauth in staging

## Flight: flight-api and baggage-api on the prod cluster answer 401 without a token and 200 with one

```bash
. docs/walkthroughs/lib/dex.sh
tok="$(dex_token "<prod-context>" app-boarding-api-staging board-oauth)"
expect_enforced "<prod-context>" app-flight-api-staging flight-api 8080 /api/flights/AC123 "$tok"
expect_enforced "<prod-context>" app-baggage-api-staging baggage-api 8080 /api/bags "$tok"
```

**Expected:** without a token 401, with a token 200, for both; health paths stay open

## A token from the dev cluster's Dex is refused on the prod cluster

```bash
tok="$(dex_token "<dev-context>" app-boarding-api-dev board-oauth)"
http_status "<prod-context>" app-flight-api-staging flight-api 8080 /api/flights/AC123 "$tok"
```

**Expected:** 401: each cluster's Dex has its own keys and issuer

