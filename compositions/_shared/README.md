# Shared partials for the application compositions

The six application compositions (`nodejsapplication`, `springbootapplication`, `pythonapplication`,
`goapplication`, `lambdafunction`, `azurefunction`) compose the same onboarding resources in the
same way: the dev-cluster registry gate, the SecretStore request committed to the tenants repo, the
TektonCICD child, and the status step that proxies the child's conditions. Until 2026-10-09 each
composition carried its own copy of those four templates; review C3 found the "identical" copies
had grown four to five variants (only NodeJS forwarded `extraGitopsRepos`), and nothing rendered
them in CI.

Now there is one file per partial here, and each composition's `templates/<step>/<file>` is a
**symlink** to it:

```
_shared/render-github-resources/00-devcluster-gate.yaml   defines $xrName $spec $devCluster $clusterOk $tenantsRepo; the ExtraResources request
_shared/render-github-resources/secretstore-xr.yaml       the SecretStore xr-request RepositoryFile
_shared/render-github-resources/tekton-cicd-child.yaml    the TektonCICD child (gitopsRepoUrl only when $hasGitopsRepo)
_shared/cicd-onboarding-status/status.yaml                DevClusterReady / CicdOnboarded proxy, plus TargetReady when $targetResourceName is set
```

Per-composition differences enter through variables, not copies. Each step directory has a
`00-inputs.yaml` that only defines variables and renders nothing:

```
render-github-resources/00-inputs.yaml     <<- $hasGitopsRepo := true|false >>
cicd-onboarding-status/00-inputs.yaml      <<- $targetResourceName := "aws-lambda-target"|"" >>  <<- $targetKind := "AwsLambdaTarget"|"" >>
```

This works because `tools/build-compositions` concatenates a step's files, in name order, into ONE
Go template: a variable defined in an earlier file is visible in every later file of the same step
(and only that step). `00-inputs.yaml` sorts after `00-devcluster-gate.yaml` and before everything
that consumes it. A missing variable is a template parse error, so a composition that forgets its
inputs fails to render in `tools/test_compositions.py` rather than silently rendering less.

To change a partial: edit it here, run `tools/build-compositions` (CI runs `--check`), then
`tools/test_compositions.py --update` and review the `example/expected/` diff of every composition
that links it. That diff is the behaviour change. To add a partial, add the file here, symlink it from
each composition (`ln -s ../../../_shared/<step>/<file> compositions/<x>/templates/<step>/<file>`),
and give every linking composition whatever inputs it needs.

The symlinks are relative and committed as symlinks; `git`, the builder and the GitHub runner all
read through them. Templates that genuinely differ per stack (`src-repo.yaml`, `cicd-yaml.yaml`,
`gitops-repo.yaml`, `target-child.yaml`) stay per composition.

## Readiness rules (`readiness-context.yaml`)

function-auto-ready decides when a composed resource is ready: it knows the standard kinds (Secret,
ConfigMap, ServiceAccount, Service, Job, Deployment, ...) and otherwise expects a `Ready` condition.
Kinds that have neither (Role, RoleBinding, NetworkPolicy, MongoDBCommunity, RabbitmqCluster, Sloth's
PrometheusServiceLevel) used to be hand-marked in each template with
`gotemplating.fn.crossplane.io/ready`, and every missing or wrong mark was found live (review C7).

`readiness-context.yaml` declares those rules once, as CEL over the observed object keyed
`<group>_<version>_<kind>`, inside a `Context` document. A composition that composes one of these kinds
symlinks the file into its render step (`templates/00-readiness-context.yaml` in the flat layout) and
points its `detect-ready` step at the context:

```yaml
- step: detect-ready
  functionRef: {name: function-auto-ready}
  input:
    apiVersion: autoready.fn.crossplane.io/v1alpha1
    kind: Input
    celHealthCheckCustomizationFrom: "[hangar.io/readiness].rules"
```

The function's `CELHealthcheckCustomizations` feature gate must be on: the clusters' `function-auto-ready`
DeploymentRuntimeConfig passes `--feature-gates=CELHealthcheckCustomizations=true`, and so do the render
tools (`tools/render-pipeline` header, the `compositions` CI job). A rule that errors or returns a
non-boolean counts as not ready and raises a Warning on the XR: loud, never a false Ready. Never add a
`gotemplating.fn.crossplane.io/ready` annotation to a template again; add a rule here and a `ready` case
with an observed fixture to the composition's `example/`.
