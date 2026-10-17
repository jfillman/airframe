# Airframe quickstart, part 5: a shared OIDC provider (Dex) and enforced tokens

Skyport has one token issuer for the platform: `skyport-auth`. This part builds it on both clusters
and turns it on:

- the shared **Dex** server as an `InfraService` (like the broker in [part 3](quickstart-broker.md)),
  in Ground (dev) and Flight (staging on the prod cluster);
- a machine-to-machine **OAuth2 client** per app, attached to it;
- **enforcement**: `flight-api` and `baggage-api` refuse API calls without a valid Dex-issued JWT, and
  `boarding-api` mints a token and sends it when it calls `flight-api`.

> The checkable version - real commands, replayed against the live clusters - is
> [`../walkthroughs/part5-skyport-auth.yaml`](../walkthroughs/part5-skyport-auth.yaml) (run it with
> `tools/walkthrough-runner`).

Cluster names: `<dev-cluster>` and `<prod-cluster>` are the names chosen when the clusters were built
(for example `hangar-dev` and `hangar-prod`), as explained at the top of [part 1](quickstart.md).
`<github-owner>` is the GitHub owner of the app repos.

**What has and hasn't been verified.**
- **Verified by test:** `function-dex` (the Composition's only step) against an in-process gRPC server
  implementing Dex's own API (`functions/function-dex/tests/test_fn.py`).
- **Verified live, in the previous lab:** the Dex server on the dev cluster (its version history records
  the live fixes: a placeholder connector Dex needs to start, the `/dex/healthz` probe path, Dex v2.46.0
  for `client_credentials`).
- **Verified by the apps' own tests** (branch `dex-tokens` in each repo): `baggage-api` (22 tests,
  10 for auth, run with PyJWT and a locally generated RSA key) and `boarding-api` (27 tests, 9 for the
  token client) pass. **`flight-api`'s security code and tests were written but not compiled or run**:
  Maven Central was unreachable from where they were written. Run `./test.sh` on the branch before
  merging it.
- **Not yet verified:** any of it on a live cluster: attach clients against a live server, Dex on the
  prod cluster, and enforcement end to end. The walkthrough's checks are the definition of done.

## 01 — What you're building

```
                       app-skyport-auth-<env>                       crossplane-system
                      ┌──────────────────────────┐   gRPC 5557     ┌────────────────┐
                      │ skyport-auth (Dex server)│◀──────────────  │ function-dex   │
                      │ issuer .../dex           │  CreateClient   └────────────────┘
                      │ grant: client_credentials│
                      └─────▲──────────▲─────────┘
            token (5556)    │          │ JWKS (5556)
  ┌─────────────────────────┴──┐    ┌──┴───────────────────────────────┐
  │ boarding-api               │    │ flight-api   (checks the JWT)    │
  │ board-oauth: client id +   │───▶│ flight-oauth: issuer + JWKS URL   │
  │ secret, mints a token      │JWT │ baggage-api  (checks the JWT)    │
  └────────────────────────────┘    │ bag-oauth:   issuer + JWKS URL    │
                                    └──────────────────────────────────┘
```

- **One server per cluster/env, shared.** `mode: server` renders a Dex Deployment
  (`ghcr.io/dexidp/dex:v2.46.0`), its Service, config and a PVC, and a NetworkPolicy: port **5556**
  (token, JWKS, discovery) only from the namespaces in `allowedNamespaces`, port **5557** (Dex's gRPC
  Admin API) only from `crossplane-system`.
- **The only grant is `client_credentials`**: service-to-service tokens, no browser, no login page.
- **One client per app, attached.** `mode: attach` registers a confidential client through Dex's Admin
  API and writes `<name>-oauth-credentials` in the app's namespace: `client-id`, `client-secret`,
  `issuer`, `token-url`, `jwks-url` (outputs `clientId`, `clientSecret`, `issuer`, `tokenUrl`, `jwksUrl`).
- **A resource server needs only `issuer` and `jwksUrl`**; a caller needs `tokenUrl`, `clientId`,
  `clientSecret`. Every app gets its own attach entry either way, so each has its own identity.
- **The issuer is in-cluster:** `http://skyport-auth.app-skyport-auth-<env>.svc.cluster.local:5556/dex`.

**What is enforced.** Any valid token from this server: signed by a key in its JWKS, not expired, from
the configured issuer. Dex's `client_credentials` grant has no per-client scopes, so there is no finer
rule (who may call what) yet.

| App | Protected | Always open |
|---|---|---|
| `flight-api` | `/api/flights` and everything under it, every method | `/api/whoami`, `/actuator/health/**` (probes) |
| `baggage-api` | every path except the open ones (`/api/bags`, `/api/reroutes`, `/api/events/status`, ...) | `/`, `/healthz`, `/api/whoami` |

Enforcement turns on when `OAUTH_JWKS_URL` is set; with it unset an app enforces nothing and logs a
warning at startup, so the code still runs outside the cluster. Both apps fetch the key set on the first
protected request, not at startup, so Dex being down doesn't stop them (protected calls get 401 until
it answers).

## 02 — Before you start

- **`function-dex` and the `Dex` XRD on both clusters.** On the dev cluster they are in its cluster repo
  (`10-crds-operators/crossplane/functions.yaml`, `idp-service-catalog`); on the prod cluster they come
  from **Apron's prod profile** (Dex's XRD, composition and function on prod). The package
  `ghcr.io/jfillman/function-dex` must be **public** on GHCR, or the pull fails `UNAUTHORIZED`
  (`functions/function-dex/README.md`). Its `v0.1.7` manifest has both `linux/amd64` and `linux/arm64`.

  ```bash
  for ctx in <dev-cluster> <prod-cluster>; do
    kubectl --context $ctx get function function-dex
    kubectl --context $ctx get xrd dexes.catalog.hangar.io
  done
  ```
- **The apps' `dex-tokens` branches.** The enforcement code is on branch `dex-tokens` of
  `flight-api`, `baggage-api` and `boarding-api` (and mirrored in `examples/skyport/`). Merge them, or
  copy the files in section 05, after the clients exist (section 04).
- **Leftovers:** the repo `gitops-infra-skyport-auth` and the Infisical projects
  `skyport-auth-<cluster>`, if a previous run left them
  ([runbook](skyport-runbook.md#before-you-start-leftovers-from-a-previous-run)). Client registrations
  live in each server's sqlite volume, so a fresh server starts with none.

## 03 — Ground: create the server

**Tower → Create → InfraService.**

| Field | Value |
|---|---|
| Name | `skyport-auth` |
| `devCluster` | `<dev-cluster>` |
| `description` | Skyport shared OIDC identity provider (Dex) |
| `visibility` | `private` |

Merge the PR. This creates `gitops-infra-skyport-auth` with a README and a stub `cicd.yaml`. Add
**`glidepath/envs/dev.yaml`** there and push it to `main`:

```yaml
appType: infra
envName: dev
rollout: { enabled: false }   # no workload of our own: the OIDC provider is the component below

components:
  - type: dex
    name: skyport-auth        # also the Deployment/Service name: skyport-auth.app-skyport-auth-dev.svc
    spec:
      mode: server
      size: small
      storageSize: 1Gi
      # Namespaces whose pods may reach the token/JWKS port (5556). An app that is not listed gets
      # credentials but can't use them: a caller can't mint, a resource server can't fetch the keys.
      allowedNamespaces: [app-flight-api-dev, app-baggage-api-dev, app-boarding-api-dev]
```

```bash
kubectl --context <dev-cluster> get dexes.catalog.hangar.io -n app-skyport-auth-dev   # COMPONENT: DexServerReady
tools/airframe-verify dex app-skyport-auth-dev/skyport-auth --context <dev-cluster>
```

`airframe-verify` runs the server's contract: `xr-synced`, `xr-ready` and `server-discovery` (GET
`/dex/.well-known/openid-configuration` on 5556, expecting 200).

## 04 — Ground: attach a client per app

Add one `dex` component, `mode: attach`, to each app's `glidepath/envs/dev.yaml`, and hand its outputs to
the app with `fromComponent`. All three are on the apps' `dex-tokens` branches.

**`flight-api`** (resource server):

```yaml
components:
  # ... flight-db and flight-mq stay as they are ...
  - type: dex
    name: flight-oauth
    spec:
      mode: attach
      serverRef: { name: skyport-auth, namespace: app-skyport-auth-dev }
env:
  # ... the existing entries stay ...
  - { name: OAUTH_ISSUER,   fromComponent: { name: flight-oauth, output: issuer } }
  - { name: OAUTH_JWKS_URL, fromComponent: { name: flight-oauth, output: jwksUrl } }
```

**`baggage-api`** (resource server): the same with `name: bag-oauth`.

**`boarding-api`** (caller):

```yaml
components:
  # ... cache and board-mq stay as they are ...
  - type: dex
    name: board-oauth
    spec:
      mode: attach
      serverRef: { name: skyport-auth, namespace: app-skyport-auth-dev }
env:
  # ... the existing entries stay ...
  - { name: OAUTH_TOKEN_URL,     fromComponent: { name: board-oauth, output: tokenUrl } }
  - { name: OAUTH_CLIENT_ID,     fromComponent: { name: board-oauth, output: clientId } }
  - { name: OAUTH_CLIENT_SECRET, fromComponent: { name: board-oauth, output: clientSecret } }
```

- **`clientId`** defaults to the XR's name (`flight-oauth`). Set it only if two attach XRs would collide.
- **`scopes`** is recorded, not enforced.
- **Deleting an attach XR does not delete the client on the server** (functions don't run on deletion).
  Recreating it adopts the server's secret; the condition message says *adopted*.

```bash
kubectl --context <dev-cluster> get dexes.catalog.hangar.io -A          # DexAttachReady for each client
tools/airframe-verify dex app-boarding-api-dev/board-oauth --context <dev-cluster>
```

`airframe-verify`'s `token-issuance` step mints a real token with the client's id and secret through a
port-forward and checks its RS256 signature against the JWKS, without printing either. `DexAttachFailed`
means the Admin API call failed: check that the server is Ready and that `function-dex` reaches 5557.

## 05 — Ground: turn enforcement on

Merge the `dex-tokens` branches (or copy from `examples/skyport/`: `flight-api`'s `SecurityConfig.java`,
`pom.xml` and `application.properties`; `baggage-api`'s `auth.py`, `main.py`, `requirements.txt` and
`Containerfile`; `boarding-api`'s `auth.js`, `reservations.js` and `index.js`). Each merge builds and
deploys to dev as usual.

**Order matters, briefly.** Once `flight-api` enforces, a `boarding-api` without its client gets `401`
from `flight-api` and answers lookups with `502` (it never invents an answer). Deploy `boarding-api`'s
change first, or accept a few minutes of 502s on the gate board.

What each app does:

- **`flight-api`**: Spring Security's OAuth2 resource server (`spring-boot-starter-oauth2-resource-server`).
  Missing, malformed, forged, expired or wrong-issuer token: `401` with `WWW-Authenticate: Bearer`.
  Stateless: no sessions, no CSRF.
- **`baggage-api`**: PyJWT with its `PyJWKClient` (keys cached five minutes, RS256 only, `exp` required,
  `aud` not checked: Dex sets it to the caller's own client id). Same `401` behaviour.
- **`boarding-api`**: fetches a `client_credentials` token (HTTP Basic, as Dex expects), caches it until
  30 seconds before `expires_in`, shares one refresh between concurrent lookups, and never caches a
  failure. A `401` from `flight-api` drops the cached token, so the next lookup gets a fresh one.

Nothing else in Skyport calls `flight-api` or `baggage-api`: `gate-api` and `checkin-api` call no other
service, and `baggage-api` only consumes broker events (the broker path has its own credentials).

## 06 — Ground: check it (401 without a token, 200 with one)

```bash
kubectl --context <dev-cluster> -n app-flight-api-dev port-forward svc/flight-api 8081:8080 &
curl -s -o /dev/null -w '%{http_code}\n' localhost:8081/api/flights/AC123    # 401
curl -s -o /dev/null -w '%{http_code}\n' localhost:8081/actuator/health/liveness   # 200: probes stay open
```

With a token (this mints one with `boarding-api`'s client and never prints it):

```bash
. docs/walkthroughs/lib/dex.sh
tok="$(dex_token <dev-cluster> app-boarding-api-dev board-oauth)"
expect_enforced <dev-cluster> app-flight-api-dev flight-api 8080 /api/flights/AC123 "$tok"
expect_enforced <dev-cluster> app-baggage-api-dev baggage-api 8080 /api/bags "$tok"
```

Each prints `without a token 401, with a token 200`. Then the real caller: the gate board still answers
from `flight-api`, which now means `boarding-api` sent a valid token:

```bash
kubectl --context <dev-cluster> -n app-boarding-api-dev port-forward svc/boarding-api 8080:8080 &
curl -s localhost:8080/api/boarding/AC123     # 200, "source": "flight-api"
```

A port-forward goes straight to the pod, around NetworkPolicy, so it proves the apps check tokens, not
that their namespaces can reach Dex. The gate board's `"source": "flight-api"` answer is the in-cluster
proof: `boarding-api` reached Dex on 5556 and `flight-api` fetched its keys.

## 07 — Flight: the same on the prod cluster

The flight environment works as in [part 3, section 08](quickstart-broker.md#08--flight-the-same-on-the-prod-cluster)
for the broker. The prod cluster has its own Dex server: tokens from the dev server are not valid there
(different keys, different issuer), which is what you want.

1. **Tower → Create → ApplicationEnvironment**: `Name` `skyport-auth-<prod-cluster>-staging`,
   `Namespace` `app-skyport-auth-cicd`, `appName` `skyport-auth`, `cluster` `<prod-cluster>`, `env`
   `staging`, **`appType` `infra`**, `configMapGenerator` off. Merge it.
2. In the PR that adds `gitops-infra-skyport-auth/<prod-cluster>/staging/values.yaml`, keep the identity
   keys Crossplane wrote and add:

   ```yaml
   rollout: { enabled: false }
   components:
     - type: dex
       name: skyport-auth
       spec:
         mode: server
         size: small
         storageSize: 1Gi
         allowedNamespaces: [app-flight-api-staging, app-baggage-api-staging, app-boarding-api-staging]
   ```
3. In each app's staging values (`gitops-<app>/<prod-cluster>/staging/values.yaml`, through a PR), add
   the same attach component and `env` entries as section 04, with
   `serverRef: { name: skyport-auth, namespace: app-skyport-auth-staging }`.
4. Release the apps' enforcing images to staging (fast-forward the signed release commits, as always).

Check it the same way, against the prod cluster:

```bash
tools/airframe-verify dex app-skyport-auth-staging/skyport-auth --context <prod-cluster>
tools/airframe-verify dex app-boarding-api-staging/board-oauth --context <prod-cluster>
tok="$(dex_token <prod-cluster> app-boarding-api-staging board-oauth)"
expect_enforced <prod-cluster> app-flight-api-staging flight-api 8080 /api/flights/AC123 "$tok"
expect_enforced <prod-cluster> app-baggage-api-staging baggage-api 8080 /api/bags "$tok"
```

## Not yet verified

- `flight-api`'s `SecurityConfig` and its tests have not been compiled (no Maven access where they were
  written). The design is standard Spring Boot 3.5 resource-server configuration; the first `./test.sh`
  on the branch is its first run.
- A live attach client, Dex on the prod cluster, and enforcement end to end on either cluster.
- That Dex v2.46.0's `client_credentials` access tokens carry `iss` equal to the issuer URL in the attach
  Secret (both apps check it when `OAUTH_ISSUER` is set). If a live check shows `401` with a valid token
  and an "iss" error in the app's log, unset `OAUTH_ISSUER` and report it.

## Cheat sheet

- **Dex is a component** (`type: dex`): `mode: server` in an `InfraService`, `mode: attach` in each app.
- **Attach outputs:** Secret `<name>-oauth-credentials`: `client-id`, `client-secret`, `issuer`,
  `token-url`, `jwks-url`. Resource servers use `issuer` + `jwksUrl`; callers use the other three.
- **`allowedNamespaces` on the server** opens 5556 to an app's namespace, callers and resource servers alike.
- **`OAUTH_JWKS_URL` set = enforcing.** Probes and `/api/whoami` stay open.
- **One server per cluster/env**; tokens don't cross clusters.
- **`kubectl get dexes.catalog.hangar.io`**: `DexServerReady` / `DexAttachReady` / `DexAttachFailed`.
- **`docs/walkthroughs/lib/dex.sh`**: `dex_token` and `expect_enforced`, for checking by hand.
- **Registrations outlive attach XRs.** Clean them on the server by hand.
