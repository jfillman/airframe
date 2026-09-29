# function-dex

Crossplane Composition Function (Python), SP-4 (M2). The sole pipeline step on the `Dex`
XRD (`catalog.idp.io`, see [`../../xrds/dex.yaml`](../../xrds/dex.yaml) /
[`../../compositions/dex`](../../compositions/dex)):

- **`mode: server`** renders the shared Dex OIDC Deployment/Service/ConfigMap/PVC/NetworkPolicy.
  Pure templating - safe to re-render identically every reconcile.
- **`mode: attach`** registers a confidential OAuth2 client for the `client_credentials` grant
  (machine-to-machine, no browser/redirect/interactive login) on an existing shared server, via
  Dex's real gRPC Admin API (`api/v2`, `CreateClient` - vendored proto in
  `function/dex_api.proto`).

## Why a custom function, not pure templating

Every other component in this catalog (Redis, PostgreSQL, RabbitMQ, MongoDB) registers a
per-app credential by rendering a real operator CRD - `function-go-templating` alone is
enough. Dex has no such CRD to render for "register a client":

- Its own internal storage CRDs (`oauth2clients.dex.coreos.com`) key the object's
  `metadata.name` on a nonstandard FNV-64 hash of the client ID (Go's `hash.Hash.Sum`
  semantics, not what it looks like at a glance) - verified against Dex's real source, not
  assumed, and rejected as too fragile to build a catalog component on. See this project's
  `project_sp4_oauth_dex_investigation.md` memory for the full writeup.
- A static-`staticClients`-config-plus-restart approach avoids that, but creates a real
  multi-writer problem: every attach XR would need to render into the *same* shared Dex
  ConfigMap, which Crossplane's per-XR composition model doesn't do cleanly.

Dex's real, documented, stable interface for dynamic client registration is its gRPC Admin
API (`CreateClient`/`GetClient`/`DeleteClient`, `api/v2/api.proto`) - and `CreateClient` is
idempotent by Dex's own design (`CreateClientResp.already_exists`), so this function calls it
on every reconcile with the same `(id, secret)` pair; the secret itself is generated once and
reused thereafter (`reused_or_generated_secret` - the same stable-secret pattern
`compositions/mongodb/templates/password.yaml` already established for this catalog).

## Testing philosophy

`tests/test_fn.py` runs a real, in-process gRPC server implementing Dex's own `DexServicer`
interface, rather than mocking `create_dex_client` - it exercises the real generated stub, the
real proto wire format, and the real `grpc.aio` async path. This caught two real bugs before
any cluster ever saw this code: `fnv1.Resource` (a real protobuf message: `.resource`,
`.ready` as attributes) was being accessed with `[]` like a `Struct` (`.resource` is itself a
`Struct` and supports `[]`, the outer `Resource` wrapper does not) - both `server_component_ready`
and `reused_or_generated_secret` had this bug, both caught by tests that check the actual
resulting behavior (readiness flips True, a secret is genuinely reused) rather than the call
succeeding.

## Build and push

Base recipe is the same as [`../function-rollout-watcher`](../function-rollout-watcher) (see
that README's own build section for the full docker/podman and crossplane-CLI gotchas) - but
that function only ever shipped a single amd64 build (it only needs to run on kind-prod).
**This one needs both**: kiac-dev is arm64, kind-prod is amd64
(`feedback_multiarch_amd64_arm64.md`), and function-dex has to be installed on whichever
cluster hosts a `Dex` XR (server or attach). Each cluster's `Function` object names its own
image tag independently (same per-cluster-pin pattern this project already uses elsewhere,
e.g. `platform-cicd-toolbox`), so the simplest correct path is two single-arch builds under
two tags - not a combined multi-arch manifest list, which `crossplane xpkg`'s tooling doesn't
cleanly support yet as of this writing (verify against the current CLI before assuming
otherwise; this was not tested against a real push in this pass):

```shell
docker build . --platform=linux/amd64 --tag runtime-amd64
crossplane xpkg build --package-root=package --embed-runtime-image=runtime-amd64 \
  --package-file=function-dex-amd64.xpkg
crossplane xpkg push --package-files=function-dex-amd64.xpkg ghcr.io/jfillman/function-dex:<tag>-amd64

docker build . --platform=linux/arm64 --tag runtime-arm64
crossplane xpkg build --package-root=package --embed-runtime-image=runtime-arm64 \
  --package-file=function-dex-arm64.xpkg
crossplane xpkg push --package-files=function-dex-arm64.xpkg ghcr.io/jfillman/function-dex:<tag>-arm64
```

kind-prod's `Function` object names the `-amd64` tag, kiac-dev's names the `-arm64` tag.
