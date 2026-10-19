# SecretStore Composition: render cases

`cases.yaml` lists every render case: an XR, the cluster-registry and other lookup fixtures it
sees, and observed resources that stand in for a later reconcile. Each case renders through the
real functions and is compared with `expected/<case>.yaml`. From the repo root:

```shell
python3 tools/build-compositions secretstore              # after any change to ../templates/
python3 tools/test_compositions.py secretstore            # check
python3 tools/test_compositions.py --update secretstore   # regenerate expected/, then review the diff
```

| Case | XR | What it shows |
|---|---|---|
| `checkout-api-new-project` | `xr-checkout-api.yaml` | Shared mode on a cluster that doesn't run Infisical: a new project and universal auth. |
| `checkout-api-adopted` | `xr-checkout-api.yaml` | The same, adopting an existing project through `secretstore-provisioner.yaml`. |
| `checkout-api-staging` | `xr-checkout-api-staging.yaml` | Per-environment mode: one environment and a store limited to `app-checkout-api-staging`. No project. |
| `checkout-api-kubernetes-auth` | `xr-checkout-api.yaml` | Shared mode on the cluster that runs Infisical: Kubernetes auth, plus the credentials Secret once the Identity is observed. |
| `checkout-api-universal-creds` | `xr-checkout-api.yaml` | Universal auth once the client secret is observed: the credentials Secret and its server-side copy of the secret. |
| `registry-url-universal-auth`, `registry-url-kubernetes-auth` | `xr-checkout-api.yaml` | Infisical's address and org id taken from the registry record, for each auth method. |
| `registry-keys-missing` | `xr-checkout-api.yaml` | A registry record without `infisicalUrl`/`infisicalOrgId`: the render fails and nothing is applied. |

## Adopting an existing project

A new app needs nothing: its project is created. To adopt a project that already exists in
Infisical, so its secrets stay where they are, add an entry for its slug (`<app>-<cluster>`) to
the `secretstore-provisioner` ConfigMap with its `projectId`, `sharedEnvId` and `envIds` (format
in `secretstore-provisioner.yaml` and `../templates/02-provisioner-gate.yaml`). The provider's
machine identity must already be an `admin` member of that project, or every read is a 403.

## Deleting a SecretStore keeps the Infisical project

`Project` and `ProjectEnvironment` have `managementPolicies: [Create, Observe, Update,
LateInitialize]`, with no `Delete`. Deleting the XR, or ArgoCD pruning the file that declares
it, removes the Kubernetes objects and leaves the project, its environments and their secrets.
The identity, its auth config and its client secrets keep `Delete`, so credentials are still
revoked.

A decommissioned app's project therefore keeps its slug. Before onboarding an app with the same
name, adopt the leftover project (above) or delete it in Infisical.
