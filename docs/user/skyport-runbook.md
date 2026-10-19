# Skyport runbook: all of it, on freshly built clusters

How to stand up the whole [Skyport](skyport-demo.md) demo on two new clusters: what has to be true
first, what to clean up from a previous run, the order of the seven walkthroughs, and how to replay
every check at the end.

**Names.** `<dev-cluster>` and `<prod-cluster>` are the names chosen when the clusters were built (in
the owner's lab this time, `hangar-dev` and `hangar-prod`). Each is a record's `name:` in the fleet's
`clusters.yaml` (in the hub cluster repo, the dev cluster's) and, by the one-name rule, also the cluster's
`kubectl` context. Nothing in these guides assumes a particular name. Infisical projects are
`<app>-<cluster>`; `<github-owner>` is the GitHub owner of the app repos. Each cluster has its own
**tenants repo**, chosen when it was set up with Apron: the guides call it "the cluster's tenants
repo", its `tenantsRepo` in `clusters.yaml`.

## Configure

Set the names once. Every guide uses them as placeholders, and `tools/walkthrough-runner` needs them to
replay the checks; there are no defaults. Create `.walkthrough.env` in your Airframe checkout (the runner
reads it from the current directory, or from `--env-file PATH`; real environment variables win over it):

```bash
# .walkthrough.env - your lab's names; not committed
HANGAR_GITHUB_OWNER=<github-owner>
HANGAR_CLUSTERS_FILE=<hub-cluster-repo>/clusters.yaml   # the hub repo's clusters.yaml: dev = control-plane, prod = upper/workloads
# or name them directly instead of HANGAR_CLUSTERS_FILE:
# HANGAR_DEV_CLUSTER=<dev-cluster>
# HANGAR_PROD_CLUSTER=<prod-cluster>
# Contexts default to the cluster names (one-name rule); set these only if yours differ:
# HANGAR_DEV_CONTEXT=...
# HANGAR_PROD_CONTEXT=...
```

The GitHub owner can also come from `scm.owner`: at the top level of `clusters.yaml` if it has one, or
from an Apron `cluster.yaml` given with `--cluster-config PATH` (`HANGAR_CLUSTER_CONFIG`). Check the
configuration renders before going further:

```bash
tools/walkthrough-runner docs/walkthroughs/part6-gate-api.yaml --render /tmp/check.md && grep -m3 context /tmp/check.md
```

A missing value stops a replay with exit 2 and names the setting.

## Before you start: leftovers from a previous run

A rebuilt cluster forgets everything; GitHub, GHCR and the tenants repos do not. Anything below that
survives from an earlier run collides with the new one (a repo that already exists, an image tag that
already exists, a tenants file that recreates an old XR). [decommission-app.md](decommission-app.md) is
the full procedure for one app on a live cluster; with the old clusters gone, only its manual parts
apply:

| Leftover | Where | What to do |
|---|---|---|
| Source repos | GitHub `<github-owner>/boarding-api`, `flight-api`, `baggage-api`, `gate-api`, `checkin-api` | Delete, or rename/archive to keep history. **Irreversible if deleted.** Back up issues/PRs you want. |
| GitOps repos | `<github-owner>/gitops-boarding-api`, `gitops-flight-api`, `gitops-baggage-api`, `gitops-gate-api`, `gitops-checkin-api`, `gitops-infra-skyport-broker`, `gitops-infra-skyport-auth` | Same. They hold the old cluster's `<old-cluster>/<env>/` folders and release records. |
| Container images | GHCR packages `ghcr.io/<github-owner>/<app>` for the five apps | Delete the packages (or accept that old tags stay; new tags carry new SHAs). |
| Old tenants repos | the previous clusters' tenants repos | Each rebuilt cluster gets a **new** tenants repo, so the old ones are not read again. Archive them; just make sure no new cluster's `tenantsRepo` points at one (it would recreate the old XRs, with the old cluster names, at once). |
| Adoption ids | the prod cluster repo's `10-crds-operators/crossplane/secretstore-provisioner.yaml` | No `<app>-<cluster>` keys from old projects. A stale key makes a new app adopt a dead project. |
| Infisical projects | the Infisical org | Starting from a fresh Infisical, there are none. If an org is reused, delete `<app>-<old-cluster>` for every app. |
| Dex client registrations | the old Dex servers' sqlite volumes | Gone with the old clusters. |
| Local checkouts | your machine | Move `./boarding-api`, `./flight-api`, `./baggage-api`, `./gate-api`, `./checkin-api` aside: every guide's `git clone` fails into an existing directory. |

Check with:

```bash
for r in boarding-api flight-api baggage-api gate-api checkin-api; do
  gh repo view <github-owner>/$r --json name -q .name 2>/dev/null && echo "still exists: $r"
  gh repo view <github-owner>/gitops-$r --json name -q .name 2>/dev/null && echo "still exists: gitops-$r"
done
for r in gitops-infra-skyport-broker gitops-infra-skyport-auth; do
  gh repo view <github-owner>/$r --json name -q .name 2>/dev/null && echo "still exists: $r"
done
```

> **Not yet verified:** what a Bootstrap XR does when its repo already exists on GitHub (adopt it, or
> fail to create it). Clean first rather than finding out.

## Prerequisites

### The platform (once, for every part)

- **Both clusters built and their root apps synced** from their cluster repos (made from Apron's template),
  per those repos' and [Apron](https://github.com/jfillman/apron)'s
  bootstrap steps.
- **`clusters.yaml` records** for both names (`zone`, `roles`, `tenantsRepo`, `serviceAccountIssuer`,
  `glidepath.relaySecretName: cluster-<prod-cluster>-relay-token` on the prod record), the
  `cluster-registry` Application synced (manual by design), and the readiness flags flipped by a person
  only after checking each live ([apron docs/clusters-file.md](https://github.com/jfillman/apron/blob/main/docs/clusters-file.md)):
  - dev: `cicdReady: true` once the Glidepath control plane runs; `infisicalHost: true` (a role: the
    cluster that runs Infisical); `autopilotReady` only after the netpol canary passes (not needed for
    Skyport).
  - prod: `crossplaneReady: true` once Crossplane composes there. `ApplicationEnvironment` refuses a
    cluster without it (`ClusterReady: False`).
- **A fresh Infisical**: after its first-run setup, put the new org id in `clusters.yaml`'s `infisical:`
  block (with `url: http://<dev-cluster>.local:31800/api` and the in-cluster URL). Then plant, by hand, in
  the control plane's project `glidepath-<dev-cluster>` (Glidepath
  [secrets-management.md](https://github.com/jfillman/glidepath/blob/main/docs/admin/secrets-management.md)):
  `github-application-id`, `github-private-key`, `github-installation-id`, `github-webhook-secret`,
  `provider-github-creds` (a PAT with `repo` + `delete_repo`: Crossplane creates and deletes the app
  repos), `provider-infisical-creds`, `registry-credentials-dockerconfigjson` (GHCR read/write), and
  `relay-token-<prod-cluster>`; the same relay token in the prod cluster's own project. Never commit or
  paste these values.
- **The GitHub App** installed on every repo the apps will have (or on the whole account), with its
  webhook pointing at the dev cluster's Pipelines-as-Code endpoint and the same webhook secret as
  `github-webhook-secret`. Check that a push reaches the cluster before part 1: when the delivery path
  is down, pushes trigger nothing and nothing says so (Glidepath known gap 8).
- **Tower is up as the `backstage` app's prod environment.** Tower (Backstage) is redeployed as an
  Airframe `NodeJSApplication` named `backstage`, with its prod environment on the prod cluster. That app
  itself is onboarded by a **git PR** to the dev cluster's tenants repo (`tenantsRepo` in `clusters.yaml`), not through Tower (there is no Tower yet to
  use). Its deployment is prepared in
  [jfillman/backstage `deploy/airframe/`](https://github.com/jfillman/backstage/tree/airframe-app/deploy/airframe)
  (branch `airframe-app`). Every step that uses Tower needs it first: the Create forms (parts 1 to 5, 7),
  the App Configuration and Environments tabs, the Pull Requests tab and its gate view, and all of part 7.
  Part 6 does not need it.
- **Dex on both clusters.** The dev cluster's repo installs `function-dex` and the `Dex` XRD; on the prod
  cluster they come from **Apron's prod profile** (Dex's XRD, composition and function). Part 5 needs
  both; `ghcr.io/jfillman/function-dex` must be a public package.
- **gitsign** on the machine you commit from: `git config gpg.x509.program gitsign`,
  `git config gpg.format x509`, `git config commit.gpgsign true`, and your signing address in each app's
  `governance.allowedCommitSigners`
  ([commit-signing.md](https://github.com/jfillman/glidepath/blob/main/docs/admin/commit-signing.md)).

### The gotchas every part shares

- **The scaffold's starter `cicd.yaml`** writes `deploy.environments` with ground dev only (and
  `target: aws-ecs` when the app was created with that deploy target); add flight envs as each part shows.
- **Merge release PRs by fast-forwarding the signed commit**, never with GitHub's button (all three
  strategies create an unsigned commit and `provenance` fails).
- **PR pipelines need the `preview` label.**
- **`configMapGenerator` off** on every `ApplicationEnvironment` (no config files to mount).
- **Python images**: alpine base and `pip uninstall -y setuptools pip`, or the image-scan gate fails.
- **Spring liveness on `/actuator/health/liveness`**, never `/readiness`.
- **`provider-helm` components (Redis) report `Ready=False` for about ten minutes** after any change.
- **One container file per repo**, named `Containerfile`.

### Per part

| Part | Needs on the dev cluster | Needs on the prod cluster | Needs before it |
|---|---|---|---|
| [6 gate-api](quickstart-gate-api.md) | platform only | platform only | nothing (the smallest app: run it first, as a smoke test of the whole path) |
| [1 boarding-api](quickstart.md) | `provider-helm`, `Redis` XRD | the same | Tower |
| [2 flight-api](quickstart-flight-api.md) | CloudNativePG, `PostgreSQL` XRD | the same | part 1 (boarding-api calls it) |
| [3 skyport-broker](quickstart-broker.md) | RabbitMQ cluster + messaging-topology operators, cert-manager, `RabbitMQ` XRD | the same | parts 1 and 2 (the publisher and the first consumer) |
| [4 baggage-api](quickstart-baggage-api.md) | MongoDB Controllers for Kubernetes, `MongoDB` XRD | the same, and a node kernel check | part 3's broker, with `app-baggage-api-<env>` in `allowedNamespaces` |
| [5 skyport-auth](quickstart-skyport-auth.md) | `function-dex` (public GHCR package), `Dex` XRD | the same, **from the Apron prod profile** (Dex's XRD, composition and function on prod) | parts 1, 2 and 4 on the `dex-tokens` app branches (enforcement code) |
| [7 checkin-api](quickstart-checkin-api.md) | platform only | platform only | Tower; part 6 is the same path in the terminal |

All of these operators and XRDs are in the two cluster repos (`10-crds-operators/` and
`20-service-catalog/idp-service-catalog`); the table says what each part depends on, so you know what
to check when one fails. A quick check per cluster:

```bash
for ctx in <dev-cluster> <prod-cluster>; do
  kubectl --context $ctx get xrd redis.catalog.hangar.io postgresqls.catalog.hangar.io \
    rabbitmqs.catalog.hangar.io mongodbs.catalog.hangar.io 2>&1 | sed "s/^/$ctx: /"
done
for ctx in <dev-cluster> <prod-cluster>; do
  kubectl --context $ctx get xrd dexes.catalog.hangar.io
  kubectl --context $ctx get function function-dex
done
```

## The order

1. **Part 6, gate-api** (terminal). No components, no Tower: if this reaches a canary on the prod cluster,
   the platform works end to end (onboarding, PaC, build, ground deploy, flight env, gates, signed
   release, Argo CD on the prod cluster).
2. **Tower** comes up (the `backstage` app, above) if it isn't already.
3. **Part 1, boarding-api** + Redis, ground and flight.
4. **Part 2, flight-api** + PostgreSQL; point boarding-api at it.
5. **Part 3, skyport-broker**; attach flight-api (publisher) and boarding-api (consumer). List
   `app-baggage-api-<env>` in `allowedNamespaces` now.
6. **Part 4, baggage-api** + MongoDB, consuming the broker; staging needs the broker's staging env first.
7. **Part 5, skyport-auth** on both clusters (Dex on prod is from the Apron prod profile): the server,
   a client per app, then the apps' `dex-tokens` code, boarding-api first so the gate board keeps
   working. From here on `flight-api` and `baggage-api` refuse API calls without a token. Only
   boarding-api calls them; gate-api and checkin-api call no other service.
8. **Part 7, checkin-api**, through Tower.

## Replaying every check

Each part has an executable walkthrough in [`../walkthroughs/`](../walkthroughs/README.md). With
`.walkthrough.env` in place ([Configure](#configure)), run them all:

```bash
tools/walkthrough-runner --all
```

or give everything on the command line:

```bash
tools/walkthrough-runner --all --clusters <hub-repo>/clusters.yaml --github-owner <github-owner>
# kubectl contexts default to the cluster names; override with --dev-context / --prod-context
```

Each file reports PASS/FAIL per step, then one summary line (`7/7 walkthroughs replay green`). Every
step is read-only. A part you haven't done yet fails, which is the point: the replay is the definition
of done. One part alone: `tools/walkthrough-runner docs/walkthroughs/part4-baggage-api.yaml --clusters ...`.
