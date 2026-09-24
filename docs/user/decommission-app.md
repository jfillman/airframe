# Decommissioning an application

There is no "delete app" button or single command. Decommissioning is deleting the
app's onboarding files from git and letting ArgoCD prune, then a few manual cleanups
for the things the platform deliberately (or accidentally) leaves behind.

> **Status: proven once, live, on `boarding-api` (2026-09-24), a Go app with one upper
> env (`kind-prod` staging) and one dev env.** The steps below are what actually
> happened, in order. Other stacks (Node, Spring Boot, Python) use the same
> mechanism but are untested for decommissioning.

## Read this first: what gets destroyed

Deleting the application XR (`GoApplication`, `NodeJSApplication`, ...) deletes, for real:

| Thing | Fate | Why |
|---|---|---|
| GitHub **source repo** `<app>` | **Deleted, irreversible** | `Repository` MR has `managementPolicies: [*]` |
| GitHub **gitops repo** `gitops-<app>` | **Deleted, irreversible** | same |
| Infisical identities, k8s Objects, RepositoryFiles in the source/gitops repos | Deleted | default/`Delete` policies |
| Infisical **Project** (`<app>-<cluster>`) | **Kept** (Delete-protected) | `managementPolicies` has no `Delete`; delete by hand |
| Files the composition wrote into the **tenants repos** (`identity.yaml`, `xr-requests/secretstore*.yaml`) | **Kept** | RepositoryFiles without `Delete`; delete by hand |

The GitHub deletion needs a PAT with `delete_repo`, otherwise the repo MR sticks in
`Terminating`. Issues, PRs and Actions history vanish with the repo; back up anything
you need first. Before starting, `git pull` your local checkout so it isn't behind.

Verify the policies live before you start, they are the source of truth, not this table:

```sh
kubectl --context kiac-dev get managed -A \
  -o custom-columns=K:.kind,N:.metadata.name,POL:.spec.managementPolicies | grep <app>
```

## Procedure

Every step is a git commit to a tenants repo. Commit and push as **separate**
commands; watch the cluster between steps.

### 1. Remove upper environments (`ApplicationEnvironment` XRs)

In `gitops-cluster-<dev>-tenants`, delete `tenants/<app>/xr-requests/<cluster>-<env>.yaml`
for each upper env. ArgoCD prunes the XR on its next refresh.

*Trial:* XR gone ~90 s after push. The `Usage` finalizer deadlock documented in
`hangar/docs/service-catalog-design.md` (§ xr-requests) **did not occur**.

### 2. Remove the app from each upper cluster's tenants repo

The env XR's files in `gitops-cluster-<upper>-tenants` are **not** removed by step 1.
`git rm -r tenants/<app>` there (identity files, `<env>/identity.yaml`, and the
`xr-requests/secretstore-*.yaml`). ArgoCD prunes the per-app AppProject, the env
Application, the SecretStore XRs, and their composed resources (~3 min).

Then check for the known ordering bug below, and delete the leftover empty
`app-<app>-xrs` namespace on the upper cluster (`kubectl get all,cm,secret -n` first;
only `kube-root-ca.crt` should exist).

### 3. Remove the application XR (**point of no return**)

In `gitops-cluster-<dev>-tenants`, `git rm -r tenants/<app>` (app XR, `secretstore.yaml`,
`identity.yaml`). Within ~100 s the XR, all managed resources and both GitHub repos are
gone (confirm with `gh api repos/<owner>/<app>` → 404). Then the dev-side ArgoCD
Applications go, again subject to the ordering bug.

### 4. Manual cleanup

- **`app-<app>-cicd` namespace** on the dev cluster survives, holding the per-app
  `registry-credentials`, `<app>-pr-generator-token` and `glidepath-backstage-notify`
  Secrets. Delete the namespace.
- **Infisical project(s)** `<app>-kind-dev`, `<app>-<upper>`: delete in the Infisical UI.
  The provider identity is not always a member, so its API view can't confirm deletion
  (a 404 is ambiguous: gone vs. not visible).
- **`secretstore-provisioner` ConfigMap** (`gitops-cluster-<upper>/10-crds-operators/
  crossplane/secretstore-provisioner.yaml`): remove the `<app>-<cluster>` key. It holds
  the project/env IDs used for *adoption*; a stale key makes a re-created app try to
  adopt a dead project.
- **Backstage catalog entry**: should disappear on its own as the ingestor re-reads XRs;
  not verified in the trial.
- **Local checkout and doc references** to the app.

## Known problem: AppProject is pruned before its Applications

Seen twice in the trial (kind-prod `boarding-api-staging`, kiac-dev `boarding-api-dev`,
plus a knock-on stall of `boarding-api-onboarding`). ArgoCD deletes the per-app
`AppProject` before an Application that references it. The Application is then stuck
with its `resources-finalizer` and:

```
DeletionError: error getting app project "<x>": appproject.argoproj.io "<x>" not found
InvalidSpecError: Application referencing project <x> which does not exist
```

Confirm the app's resources are already gone (its namespace no longer exists), then:

```sh
kubectl --context <cluster> patch application <name> -n argocd-apps \
  --type=merge -p '{"metadata":{"finalizers":[]}}'
```

Only clear the finalizer after verifying nothing is deployed, since it skips the
cascade. Root cause is unfixed: the AppProject and the Applications it governs are
siblings with no deletion ordering. A real fix would be an ArgoCD sync-wave / a
project-scoped ordering, or making the Application not depend on a pruned project.

## Not covered / open

- Decommissioning an app with a live prod env (this trial's env was staging only, never
  deployed). Expect real workload teardown and possibly the `Usage` deadlock.
- Making the source-repo deletion opt-in (e.g. a `retainRepositories` field). Today the
  only way to keep the source repo is to patch its `managementPolicies` live before
  step 3, which is untested against the composition re-reconciling it.
- Automating any of this (a Backstage "decommission" action would need the same
  authorization care as Tower's other write actions).
