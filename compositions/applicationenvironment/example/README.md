# ApplicationEnvironment Composition — local render examples

Fast offline check of the templates' Go-template syntax and branching logic, no
cluster needed. Because the Composition uses `source: Inline` (see
`../build-composition.sh`), `../composition.yaml` is directly renderable as-is — no
wrapper script needed.

```shell
# Gate-pass: cluster registered, type: upper, crossplaneReady: "true"
crossplane render xr-staging.yaml ../composition.yaml functions.yaml -x -r \
  --required-resources cluster-registry-ready.yaml

# Gate-fail: no --required-resources at all, simulating "not found yet" (same
# rendered shape as a registered-but-not-ready or type: dev entry - the Composition
# doesn't distinguish those cases, see 00-cluster-gate.yaml)
crossplane render xr-staging.yaml ../composition.yaml functions.yaml -x -r

# App-kind resolution: with no app-kind fixture, none of the five lookups resolve, so no
# app-usage Usage is composed and the status step reports AppResolved: False / AppNotFound
# (00-app-kind-gate.yaml, status/status.yaml) - exercised by either command above already.
# Add one of the *-app-exists.yaml fixtures to prove that stack's own branch instead
# (a composed Usage of that kind, AppResolved: True):
crossplane render xr-staging.yaml ../composition.yaml functions.yaml -x -r \
  --required-resources cluster-registry-ready.yaml \
  --required-resources springboot-app-exists.yaml   # or pythonapp-exists.yaml / goapp-exists.yaml
```

Requires Docker (`crossplane render` pulls and runs `function-go-templating` /
`function-auto-ready` in containers by default).

**If you edit `../templates/render-github-resources/*.yaml` or
`../templates/status/*.yaml`**, run `../build-composition.sh` first to regenerate
`../composition.yaml` from them before re-running these examples — the templates are
the maintainable source, `composition.yaml` is generated and GitOps-tracked.

`cluster-registry-ready.yaml` is a `--required-resources` fixture simulating the real
cluster-registry `ConfigMap`
(`gitops-cluster-dev/00-bootstrap/cluster-registry/kind-prod.yaml`) once a cluster
admin has verified the scoped Crossplane+Attached-tier install there for real and
flipped `crossplaneReady` to `"true"`.

These fixtures only exercise the Composition's template logic (rendered
`RepositoryFile` shapes including the delete-excluding `managementPolicies` on
`cluster-identity-yaml`, the
extra-resources gate branching, the `ClusterReady`/`AppResolved` status patch) —
they never call the real GitHub API or fetch a real cluster resource.
`crossplane render` treats every `provider-github` managed resource as spec-only
output, and `--required-resources` is a local file standing in for what Crossplane's
core would actually fetch; nothing here proves the resources reconcile against
GitHub or that a real `ConfigMap` on `kind-dev` gets found the same way. That needs a
real cluster with `provider-github` installed and a real credential — see
`idp/docs/service-catalog-design.md` §0 and this repo's own top-level README for the
live-verification path.
