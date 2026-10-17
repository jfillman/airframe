# Airframe quickstart, part 5: a shared OIDC provider (Dex)

Skyport's design has one token issuer for the platform: `skyport-auth`, whose tokens `flight-api` and
`baggage-api` validate. This part builds what exists of that today: the shared **Dex** server as an
`InfraService` (like the broker in [part 3](quickstart-broker.md)), and a machine-to-machine **OAuth2
client** per app, attached to it, that can mint real signed tokens.

> **Where this stops.** Neither `flight-api` nor `baggage-api` checks a token yet: neither has any
> token-validation code (no Spring Security / OAuth2 resource-server dependency in `flight-api`'s
> `pom.xml`, nothing in `baggage-api`), and `boarding-api` sends none. Section 06 is marked **not built
> yet**. Everything before it is real: the server, the clients, and token issuance you can check.

> The checkable version - real commands, replayed against the live clusters - is
> [`../walkthroughs/part5-skyport-auth.yaml`](../walkthroughs/part5-skyport-auth.yaml) (run it with
> `tools/walkthrough-runner`).

Cluster names: `<dev-cluster>` and `<prod-cluster>` are the names chosen when the clusters were built
(for example `hangar-dev` and `hangar-prod`), as explained at the top of [part 1](quickstart.md).

**What has and hasn't been verified.**
- **Verified by test:** `function-dex` (the Composition's only step) against an in-process gRPC server
  implementing Dex's own API (`functions/function-dex/tests/test_fn.py`), including adopting the
  server's secret on `already_exists`.
- **Verified live, in the previous lab:** the server mode. `skyport-auth`'s dev environment ran this
  section's server entry (`gitops-infra-skyport-auth/glidepath/envs/dev.yaml`), and `function-dex`'s
  version history records the live fixes (a placeholder connector Dex needs to start, the
  `/dex/healthz` probe path, Dex v2.46.0 for `client_credentials`).
- **Not yet verified:** an app's `attach` client against a live server. When the previous lab was
  last read, no app had attached (the server's `allowedNamespaces` listed only its own namespace).
  Section 04 is written from the XRD, the sidecar contract and the function's source.
- **Not built:** the prod cluster has no Dex XRD and no `function-dex`; only the dev cluster lists them.
  So this part is **dev cluster only** (section 07).

## 01 — What you're building

```
   app-flight-api-dev                   app-skyport-auth-dev                 crossplane-system
   ┌──────────────────────┐   token    ┌──────────────────────────┐  gRPC    ┌────────────────┐
   │ flight-oauth (attach)│──────────▶ │ skyport-auth (Dex server)│◀──5557── │ function-dex   │
   │ Secret:              │  :5556     │ issuer .../dex           │          │ CreateClient   │
   │ flight-oauth-oauth-  │            │ sqlite on a 1Gi PVC      │          └────────────────┘
   │ credentials          │            │ grant: client_credentials│
   └──────────────────────┘            └──────────────────────────┘
```

- **One server, shared.** `mode: server` renders a Dex Deployment (`ghcr.io/dexidp/dex:v2.46.0`), its
  Service, config and a PVC, plus a NetworkPolicy: port **5556** (token, JWKS, discovery) only from the
  namespaces in `allowedNamespaces`, port **5557** (Dex's gRPC Admin API) only from `crossplane-system`.
- **The only grant is `client_credentials`**: service-to-service tokens, no browser, no login page. The
  config carries a `mockCallback` connector only because Dex refuses to start with none; nothing uses it.
- **One client per app, attached.** `mode: attach` registers a confidential client through Dex's Admin API
  (`CreateClient`) and writes `<name>-oauth-credentials` in the app's namespace: `client-id`,
  `client-secret`, `issuer`, `token-url`, `jwks-url`.
- **The issuer is in-cluster:** `http://skyport-auth.app-skyport-auth-<env>.svc.cluster.local:5556/dex`.
  Plain HTTP inside the cluster, not reachable from outside it.

## 02 — Before you start

- **`function-dex` installed** on the dev cluster: `gitops-cluster-dev`'s
  `10-crds-operators/crossplane/functions.yaml` pins `ghcr.io/jfillman/function-dex:v0.1.7`. The package
  must be **public** on GHCR (new packages default to private and the pull fails `UNAUTHORIZED`; see
  `functions/function-dex/README.md`).
- **The `Dex` XRD**: `xrds/dex.yaml` + `compositions/dex/composition.yaml` in the dev cluster's
  `idp-service-catalog` include list.

  ```bash
  kubectl --context <dev-cluster> get function function-dex
  kubectl --context <dev-cluster> get xrd dexes.catalog.hangar.io
  ```
- **Leftovers:** the repo `gitops-infra-skyport-auth`, the Infisical project `skyport-auth-<dev-cluster>`,
  and `tenants/skyport-auth/` in the tenants repo, if a previous run left them
  ([runbook](skyport-runbook.md#before-you-start-leftovers-from-a-previous-run)). Client registrations
  live in the server's sqlite volume, so a fresh server starts with none.

## 03 — Create the server

**Tower → Create → InfraService.**

| Field | Value |
|---|---|
| Name | `skyport-auth` |
| `devCluster` | `<dev-cluster>` |
| `description` | Skyport shared OIDC identity provider (Dex) |
| `visibility` | `private` |

Merge the PR. This creates `gitops-infra-skyport-auth` with a README and a stub `cicd.yaml`, as for the
broker. Add **`glidepath/envs/dev.yaml`** there and push it to `main`:

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
      # Namespaces whose pods may reach the token/JWKS port (5556). An attached app that is not
      # listed gets credentials but cannot use them.
      allowedNamespaces: [app-flight-api-dev, app-baggage-api-dev]
```

(The previous lab's file had `rollout: null`; `rollout: { enabled: false }` is the form since chart
v0.3.140, the same as part 3's broker.)

```bash
kubectl --context <dev-cluster> get dexes.catalog.hangar.io -n app-skyport-auth-dev
# COMPONENT: DexServerReady
tools/airframe-verify dex app-skyport-auth-dev/skyport-auth --context <dev-cluster>
```

`airframe-verify` runs the server's contract: `xr-synced`, `xr-ready` and `server-discovery` (GET
`/dex/.well-known/openid-configuration` on 5556 through a port-forward, expecting 200).

## 04 — Attach a client per app

In **`flight-api`'s `glidepath/envs/dev.yaml`**, add a component and hand its outputs to the app:

```yaml
components:
  # ... flight-db and flight-mq stay as they are ...
  - type: dex
    name: flight-oauth          # credentials land in Secret flight-oauth-oauth-credentials
    spec:
      mode: attach
      serverRef: { name: skyport-auth, namespace: app-skyport-auth-dev }

env:
  # ... the existing entries stay ...
  - { name: OAUTH_ISSUER,   fromComponent: { name: flight-oauth, output: issuer } }
  - { name: OAUTH_JWKS_URL, fromComponent: { name: flight-oauth, output: jwksUrl } }
```

The same in **`baggage-api`'s** file, with `name: bag-oauth`.

- **`clientId`** defaults to the XR's name (`flight-oauth`). Set it only if two attach XRs would
  collide on the same server.
- **`scopes`** is recorded but not enforced: Dex's `client_credentials` grant does not gate scopes per
  client.
- **A resource server needs only `issuer` and `jwksUrl`** to check tokens. `clientId`/`clientSecret` are
  for a caller that mints tokens; nothing in Skyport mints them in its own code yet.
- **Deleting an attach XR does not delete the client on the server** (functions don't run on deletion).
  Recreating it adopts the server's existing secret, and the condition message says *adopted*.

```bash
kubectl --context <dev-cluster> get dexes.catalog.hangar.io -n app-flight-api-dev
# COMPONENT: DexAttachReady
tools/airframe-verify dex app-flight-api-dev/flight-oauth --context <dev-cluster>
```

> **Not yet verified:** an attach XR against the live server. Expected from the sidecar contract:
> `xr-ready` (DexAttachReady), `secret-exists` (`client-id`, `client-secret`) and `token-issuance`.
> `DexAttachFailed` means the Admin API call failed: check that the server is Ready and that
> `function-dex` can reach port 5557 from `crossplane-system`.

## 05 — Mint and check a token

`airframe-verify`'s `token-issuance` step is the check: it port-forwards to the Dex Service, POSTs
`grant_type=client_credentials` with the client's id and secret to `token-url`, and verifies the
returned `access_token`'s signature against the key published at `jwks-url`. It never prints the token
or the secret.

```bash
tools/airframe-verify dex app-flight-api-dev/flight-oauth --context <dev-cluster> --only token-issuance
```

What it proves: the client is registered, its secret is the one the server holds, and Dex signs tokens
with a key a resource server can fetch. What it doesn't: that an app's pod can reach port 5556 (a
port-forward goes straight to the pod, around NetworkPolicy; `allowedNamespaces` governs the real path).

## 06 — Enforce tokens in flight-api and baggage-api: **not built yet**

What would have to exist, none of which does today:

- **`flight-api`:** an OAuth2 resource-server dependency (for example
  `spring-boot-starter-oauth2-resource-server`) and a security config that requires a valid token on
  `PUT /api/flights/**` (and leaves `/actuator/health/**` open for the probes), reading the issuer and
  JWKS URL from `OAUTH_ISSUER` / `OAUTH_JWKS_URL`.
- **`baggage-api`:** token validation on its API (a JWT library and the JWKS fetch), same two settings.
- **`boarding-api`:** a client of its own (`board-oauth`, attach) that mints a token with its
  `client-id`/`client-secret` and sends it to `flight-api`.
- **A walkthrough check** that a request without a token is refused (401) and one with a token succeeds.

Until then the `OAUTH_*` variables from section 04 are present in the pods and unused. Don't add them
expecting protection.

## 07 — Flight: not available yet

The prod cluster's catalog Application does not include `xrds/dex.yaml`, and `function-dex` is not
installed there, so a `type: dex` component in a staging values file would be rejected (no such kind).
Adding both is a change to the prod cluster repo, with the multi-arch package (both `linux/amd64` and
`linux/arm64` are in the `v0.1.7` manifest, per its pin comment). Not done, not verified.

## Cheat sheet

- **Dex is a component** (`type: dex`): `mode: server` in an `InfraService`, `mode: attach` in each app.
- **Attach outputs:** Secret `<name>-oauth-credentials`, keys `client-id`, `client-secret`, `issuer`,
  `token-url`, `jwks-url`. Use `fromComponent`.
- **`allowedNamespaces` on the server** opens 5556 to an app's namespace. 5557 is crossplane-system only.
- **`kubectl get dexes.catalog.hangar.io`**; COMPONENT shows `DexServerReady` / `DexAttachReady` / `DexAttachFailed`.
- **`tools/airframe-verify dex <ns>/<name>`** mints a real token and checks its signature, read-only.
- **Registrations outlive attach XRs.** Clean them on the server by hand.
- **No app enforces tokens yet.**
