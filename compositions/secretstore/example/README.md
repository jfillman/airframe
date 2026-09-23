# SecretStore Composition — local render example

Fast offline check of the templates' Go-template syntax, no cluster needed.
Because the Composition uses `source: Inline` (see `../build-composition.sh`),
`../composition.yaml` is directly renderable as-is — no wrapper script needed.

```shell
crossplane render xr-checkout-api.yaml ../composition.yaml functions.yaml -x -r
```

Requires Docker (`crossplane render` pulls and runs `function-go-templating` /
`function-auto-ready` in containers by default).

`xr-checkout-api.yaml` exercises `"shared"` mode (the default, `environmentSlug`
omitted) targeting kind-dev - renders an `InfisicalProject` + a Kubernetes-Auth
`ClusterSecretStore`. `xr-checkout-api-staging.yaml` exercises the per-environment
mode (`environmentSlug: staging`, `cluster: kind-prod`) added in Item 8's
multi-cluster revision - renders an `InfisicalEnvironment` + a narrowed,
Universal-Auth `ClusterSecretStore` instead, with NO `InfisicalProject` (deliberate -
per-environment XRs reference an already-existing project, never create one). Run
either the same way, swapping the XR filename.

**If you edit `../templates/*.yaml`**, run `../build-composition.sh` first to
regenerate `../composition.yaml` from them before re-running this example.

This fixture only exercises the Composition's own rendering (both resources'
field values, deterministic naming) — it doesn't exercise
`infisical-secretstore-operator`'s own reconciliation against a real Infisical
API, which only happens on a real cluster (see that operator's own README).

## Adopting an existing project

The Composition always provisions through provider-infisical (`Project`,
`ProjectEnvironment`, `Identity`, `IdentityUniversalAuth` / `IdentityKubernetesAuth`,
`ProjectIdentity`, and the `<slug>-infisical-creds` Secret). The old
`infisical-secretstore-operator` path was removed on 2026-09-23 once every kind-prod
project had been migrated; the operator is retired.

A NEW app needs nothing: its project is created fresh. To **adopt** a project that already
exists in Infisical (so its secrets stay put), add an entry to the
`secretstore-provisioner` ConfigMap (see `secretstore-provisioner.yaml`) with its
`projectId`, `sharedEnvId` and `envIds`, and make sure the provider's machine identity is
already an `admin` member of that project - otherwise every read is a 403. The old
`provisioner: provider` key is ignored.

## Deleting a SecretStore does not delete the Infisical project

The Composition renders the `Project` and `ProjectEnvironment` managed resources with
`managementPolicies: [Create, Observe, Update, LateInitialize]` - **no `Delete`**. Deleting
the SecretStore XR, or ArgoCD pruning the file that declares it, removes the Kubernetes
objects but leaves the Infisical project, its environments and every secret in them. The
identity, its auth config and its client secrets keep `Delete`, so credentials are still
revoked.

The catch: a decommissioned app's project is left behind and keeps its slug. Onboarding an
app with the same slug later would try to create a colliding project. Either **adopt** the
leftover (an entry in the `secretstore-provisioner` ConfigMap, see above) or delete the
project in Infisical by hand once you are sure the secrets are not wanted.
