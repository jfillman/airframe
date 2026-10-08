# AwsEcsTarget Composition - local render examples

Offline check of this Composition's templates: the execution role, dedicated public network (create mode), ECS cluster, task definition and Fargate service, the gating between
them (resources that need an observed sibling appear only once the fixture for it is passed), the
`TargetReady` reasons and the published status, including the `status.cicd` deploy block.

`crossplane composition render` needs a Docker daemon, which this machine does not run, so use
`tools/render-pipeline` (its header says how to start the two functions with the `container` CLI):

```shell
# fresh XR: nothing observed yet
tools/render-pipeline example/xr-defaults.yaml composition.yaml

# later lifecycle stages: pass the observed-*.yaml fixtures in this directory, cumulatively
tools/render-pipeline example/xr-defaults.yaml composition.yaml --observed example/observed-*.yaml
```

Each `observed-*.yaml` is a composed resource as Crossplane would observe it (the
`crossplane.io/composition-resource-name` annotation names its slot). The managed resources this
renders were validated against the real Upbound provider CRD schemas (unknown fields and types)
when the Composition was written; none of this talks to a cloud account. The live path needs the
providers and credentials described in docs/user/cloud-targets.md.

If you edit `templates/`, run `./build-composition.sh` first to regenerate `composition.yaml`.
