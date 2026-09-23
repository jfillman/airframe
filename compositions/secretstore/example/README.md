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

## Provider vs. operator (universal-auth clusters)

On a universal-auth cluster (not the Infisical host) the Composition renders the old
`InfisicalProject`/`InfisicalEnvironment` CRs **unless** the app opts in through
`secretstore-provisioner.yaml` (a ConfigMap in `crossplane-system`, one key per
`<app>-<cluster>` slug). On opt-in it renders the provider-infisical chain instead
(`Project`, `ProjectEnvironment`, `Identity`, `IdentityUniversalAuth`,
`IdentityUniversalAuthClientSecret`, `ProjectIdentity`, and the same
`<slug>-infisical-creds` Secret the operator wrote), optionally adopting existing
project/environment ids. The Infisical host cluster always uses the provider.

The offline render used to verify this (real Go `text/template`, stub function map) is
described in `hangar/docs/service-catalog-design.md`'s Round 2026-09-18 playbook.
