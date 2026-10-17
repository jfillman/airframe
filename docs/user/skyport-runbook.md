# Skyport runbook: all of it, on freshly built clusters

How to stand up the whole [Skyport](skyport-demo.md) demo on two new clusters: what has to be true
first, what to clean up from a previous run, the order of the seven walkthroughs, and how to replay
every check at the end.

**Names.** `<dev-cluster>` and `<prod-cluster>` are the names chosen when the clusters were built (in
the owner's lab this time, `hangar-dev` and `hangar-prod`). Each is a record's `name:` in the fleet's
`clusters.yaml` (in the hub repo, `gitops-cluster-dev`) and, by the one-name rule, also the cluster's
`kubectl` context. Nothing in these guides assumes a particular name. Infisical projects are
`<app>-<cluster>`; `<owner>` is the GitHub owner of the app repos.

## Before you start: leftovers from a previous run

A rebuilt cluster forgets everything; GitHub, GHCR and the tenants repos do not. Anything below that
survives from an earlier run collides with the new one (a repo that already exists, an image tag that
already exists, a tenants file that recreates an old XR). [decommission-app.md](decommission-app.md) is
the full procedure for one app on a live cluster; with the old clusters gone, only its manual parts
apply:

| Leftover | Where | What to do |
|---|---|---|
| Source repos | GitHub `<owner>/boarding-api`, `flight-api`, `baggage-api`, `gate-api`, `checkin-api` | Delete, or rename/archive to keep history. **Irreversible if deleted.** Back up issues/PRs you want. |
| GitOps repos | `<owner>/gitops-boarding-api`, `gitops-flight-api`, `gitops-baggage-api`, `gitops-gate-api`, `gitops-checkin-api`, `gitops-infra-skyport-broker`, `gitops-infra-skyport-auth` | Same. They hold the old cluster's `<old-cluster>/<env>/` folders and release records. |
| Container images | GHCR packages `ghcr.io/<owner>/<app>` for the five apps | Delete the packages (or accept that old tags stay; new tags carry new SHAs). |
| Tenants files | `tenants/<app>/` in each cluster's tenants repo: its `tenantsRepo` in `clusters.yaml`, else `gitops-cluster-<name>-tenants`. In the old lab these were `gitops-cluster-dev-tenants` and `gitops-cluster-kind-prod-tenants`; GitHub repo names don't change when clusters are renamed, so set `tenantsRepo` if the default no longer matches. | `git rm -r tenants/<app>` for every Skyport app **before** the new cluster's `xr-requests` ApplicationSet syncs, or it recreates the old XRs, with the old cluster names, at once. |
| Adoption ids | the prod cluster repo's `10-crds-operators/crossplane/secretstore-provisioner.yaml` | No `<app>-<cluster>` keys from old projects. A stale key makes a new app adopt a dead project. |
| Infisical projects | the Infisical org | Starting from a fresh Infisical, there are none. If an org is reused, delete `<app>-<old-cluster>` for every app. |
| Dex client registrations | the old Dex server's sqlite volume | Gone with the old cluster. |
| Local checkouts | your machine | Move `./boarding-api`, `./flight-api`, `./baggage-api`, `./gate-api`, `./checkin-api` aside: every guide's `git clone` fails into an existing directory. |

Check with:

```bash
for r in boarding-api flight-api baggage-api gate-api checkin-api; do
  gh repo view <owner>/$r --json name -q .name 2>/dev/null && echo "still exists: $r"
  gh repo view <owner>/gitops-$r --json name -q .name 2>/dev/null && echo "still exists: gitops-$r"
done
for r in gitops-infra-skyport-broker gitops-infra-skyport-auth; do
  gh repo view <owner>/$r --json name -q .name 2>/dev/null && echo "still exists: $r"
done
```

> **Not yet verified:** what a Bootstrap XR does when its repo already exists on GitHub (adopt it, or
> fail to create it). Clean first rather than finding out.

## Prerequisites

### The platform (once, for every part)

- **Both clusters built and their root apps synced** from `gitops-cluster-dev` (dev) and
  `gitops-cluster-kind-prod` (prod), per those repos' and [Apron](https://github.com/jfillman/apron)'s
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
  block (with `url: http://dev.<lab-domain>:31800/api` and the in-cluster URL). Then plant, by hand, in
  the control plane's project `platform-cicd-<dev-cluster>` (Glidepath
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
  itself is onboarded by a **git PR** to the tenants repo, not through Tower (there is no Tower yet to
  use). Its deployment is prepared in
  [jfillman/backstage `deploy/airframe/`](https://github.com/jfillman/backstage/tree/airframe-app/deploy/airframe)
  (branch `airframe-app`). Every step that uses Tower needs it first: the Create forms (parts 1 to 5, 7),
  the App Configuration and Environments tabs, the Pull Requests tab and its gate view, and all of part 7.
  Part 6 does not need it.
- **gitsign** on the machine you commit from: `git config gpg.x509.program gitsign`,
  `git config gpg.format x509`, `git config commit.gpgsign true`, and your signing address in each app's
  `governance.allowedCommitSigners`
  ([commit-signing.md](https://github.com/jfillman/glidepath/blob/main/docs/admin/commit-signing.md)).

### The gotchas every part shares

- **The scaffold's starter `cicd.yaml` fails `preflight`** (it still writes the removed
  `lowerEnvironments` keys): replace it in each app's first push. Each guide shows the replacement.
- **Merge release PRs by fast-forwarding the signed commit**, never with GitHub's button (all three
  strategies create an unsigned commit and `provenance` fails).
- **PR pipelines need the `preview` label.**
- **`configMapGenerator` off** on every `ApplicationEnvironment` (Airframe known gap 1).
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
| [5 skyport-auth](quickstart-skyport-auth.md) | `function-dex` (public GHCR package), `Dex` XRD | **not installed**: dev only | parts 2 and 4 (the apps that attach) |
| [7 checkin-api](quickstart-checkin-api.md) | platform only | platform only | Tower; part 6 is the same path in the terminal |

All of these operators and XRDs are in the two cluster repos (`10-crds-operators/` and
`20-service-catalog/idp-service-catalog`); the table says what each part depends on, so you know what
to check when one fails. A quick check per cluster:

```bash
for ctx in <dev-cluster> <prod-cluster>; do
  kubectl --context $ctx get xrd redis.catalog.hangar.io postgresqls.catalog.hangar.io \
    rabbitmqs.catalog.hangar.io mongodbs.catalog.hangar.io 2>&1 | sed "s/^/$ctx: /"
done
kubectl --context <dev-cluster> get xrd dexes.catalog.hangar.io
kubectl --context <dev-cluster> get function function-dex
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
7. **Part 5, skyport-auth** (dev only); attach flight-api and baggage-api. Stops before token enforcement,
   which is not built.
8. **Part 7, checkin-api**, through Tower.

## Replaying every check

Each part has an executable walkthrough in [`../walkthroughs/`](../walkthroughs/README.md). Run them all,
reading the cluster names from the fleet's `clusters.yaml`:

```bash
tools/walkthrough-runner --all --clusters ../gitops-cluster-dev/clusters.yaml
```

or name them directly:

```bash
tools/walkthrough-runner --all --dev-cluster <dev-cluster> --prod-cluster <prod-cluster>
# kubectl contexts default to the cluster names; override with --dev-context / --prod-context
```

Each file reports PASS/FAIL per step, then one summary line (`7/7 walkthroughs replay green`). Every
step is read-only. A part you haven't done yet fails, which is the point: the replay is the definition
of done. One part alone: `tools/walkthrough-runner docs/walkthroughs/part4-baggage-api.yaml --clusters ...`.
