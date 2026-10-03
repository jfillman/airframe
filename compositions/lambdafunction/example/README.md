# lambdafunction Composition - local render examples

Offline check of the templates' syntax and branching, no cluster. `../composition.yaml` is
generated: run `../build-composition.sh` after editing anything under `../templates/`.

```shell
crossplane render xr-defaults.yaml ../composition.yaml functions.yaml -x -r -e cluster-registry-dev-ready.yaml
crossplane render xr-python.yaml ../composition.yaml functions.yaml -x -r -e cluster-registry-dev-ready.yaml
```

`crossplane render` needs Docker. Without it, build `function-go-templating` v0.12.3 and the
Crossplane core binary from source and use `--crossplane-binary` with a function annotated
`render.crossplane.io/runtime: Development`.

These fixtures only exercise template logic; they never call GitHub, and the composed TektonCICD
child is rendered spec-only.

**Open question these fixtures cannot answer:** TektonCICD requires `gitopsRepoUrl`, and this
Composition does not create a gitops repo (a function has no Flight environment). Whether anything
reads that URL for an app with no release stage is unverified; check on the first real onboarding.
