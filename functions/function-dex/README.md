# function-dex

Crossplane Composition Function (Python), SP-4 (M2). The sole pipeline step on the `Dex`
XRD (`catalog.hangar.io`, see [`../../xrds/dex.yaml`](../../xrds/dex.yaml) /
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

kiac-dev is arm64, kind-prod is amd64 (`feedback_multiarch_amd64_arm64.md`), and function-dex
has to be installed on whichever cluster hosts a `Dex` XR (server or attach) - so it needs a
real build for both. Uses `container` (Apple's CLI, `reference_container_cli_over_podman.md`)
plus `skopeo` to bridge two real gaps found live, both worth knowing about before touching this:

1. `container build`'s own tarball/OCI export flags (`-o type=tar`, `-o type=oci,dest=...`)
   either produce a bare rootfs (not an image archive at all) or hit a real file-move bug
   writing to a custom `dest`. The reliable path: build with no `dest` (loads into `container`'s
   own local image store), then `container image save` (produces a real OCI-layout tarball).
2. `crossplane xpkg build --embed-runtime-image-tarball` wants classic **docker-archive**
   format (`manifest.json`), not OCI-layout (`oci-layout`/`index.json`/`blobs/`) - `skopeo copy
   --override-arch <arch> --override-os linux oci-archive:IN.tar docker-archive:OUT.tar:TAG`
   converts between them. `--override-arch`/`--override-os` are required, or skopeo picks the
   *host's* platform (`darwin/arm64`) out of the multi-platform index `container image save`
   always produces, not the one you actually built.

```shell
for arch in arm64 amd64; do
  container build --arch $arch -o type=oci -t function-dex-$arch .
  container image save function-dex-$arch:latest -o /tmp/function-dex-$arch.tar
  skopeo copy --override-arch $arch --override-os linux \
    oci-archive:/tmp/function-dex-$arch.tar \
    docker-archive:/tmp/function-dex-$arch-docker.tar:ghcr.io/jfillman/function-dex:<tag>
  crossplane xpkg build --package-root=package \
    --embed-runtime-image-tarball=/tmp/function-dex-$arch-docker.tar \
    --package-file=/tmp/function-dex-$arch.xpkg
done

# crossplane xpkg push -f accepts multiple .xpkg files under ONE tag and genuinely combines
# them into a real multi-platform OCI manifest list (verified: `skopeo inspect --raw` on the
# pushed tag shows both linux/amd64 and linux/arm64 platform entries) - one Function object,
# one tag, works on both clusters. No docker daemon needed for push either: crossplane xpkg
# push reads ~/.docker/config.json directly as a pure HTTP client. If it's stale/expired
# (`DENIED`) and there's no real docker on the machine to `docker login` with, `gh auth token`
# + a manual base64(user:token) write into ~/.docker/config.json's `auths` map works just as
# well - `gh auth refresh -s write:packages` first if the token lacks that scope.
crossplane xpkg push --package-files=/tmp/function-dex-amd64.xpkg,/tmp/function-dex-arm64.xpkg \
  ghcr.io/jfillman/function-dex:<tag>
```

New packages default to **private** on ghcr.io - Crossplane's package pull then fails with
`UNAUTHORIZED`, and there's no `packagePullSecrets` configured for this package (unlike
`function-rollout-watcher`, which is public). Flip visibility to public once, via the web UI
(`https://github.com/users/<owner>/packages/container/package/function-dex` → Package
settings) - the REST API's own visibility-update endpoint 404s for this package type, at least
as of this writing.
