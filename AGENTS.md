# AGENTS.md: Airframe

Airframe is Hangar's service catalog: Crossplane XRDs, compositions and the `airframe-application`
Helm chart. This file says what is true **today**; items marked *(planned)* do not exist yet
(see hangar/docs/autopilot/airframe-ai-friendly.md, workstreams AF-1 to AF-10).

## Start here
1. [`llms.txt`](llms.txt): the index - what to read first, in what order, for a cold start.
2. `contract/airframe-contract.json` (AF-1b): every chart field, every XRD's shape and summary, every component's real outputs, in one generated file. Query it with `tools/airframe-capabilities <components|component|xrds|xrd|field|output> ...` instead of grepping source - that's the whole point of the bundle. Regenerate with `python3 tools/gen_contract.py` after changing any of its sources (never hand-edit it); CI's `--check` fails if it drifts.
3. `charts/airframe-application/values.schema.json`: the single source of truth for every chart field, its type, default and description (AF-2). `values.yaml` is GENERATED from it - never hand-edit `values.yaml`; edit the schema and run `python3 tools/gen_airframe_schema.py --write-values`. CI runs the same generator with `--check` and fails if `values.yaml` would change.
4. `xrds/*.yaml`: the XRDs (bootstrap tier, environments, components) with their schemas, each carrying a `hangar.io/agent-summary` annotation (AF-1b). `xrds/<type>.meta.yaml` (redis, postgresql, rabbitmq, mongodb today, AF-3/SP-3) declares that component's real outputs - Secret/ConfigMap names and keys, or a literal - for `fromComponent` to resolve against.
5. `docs/user/`: the Skyport quickstarts, worked end to end.
6. `tools/airframe-validate` (built: schema + discriminated `components[]` union + `tools/deadend_rules.py`'s AF-4b convention/policy rules, in one pass; `--format json` for tooling). *(planned)* `airframe.plan`, `airframe.explain`.

## The model in five lines
- **Bootstrap tier** (`NodeJSApplication`, `PythonApplication`, `SpringBootApplication`, `GoApplication`, `InfraService`): creates repos and onboarding. Not a Deployment.
- **Function XRDs** (`LambdaFunction`, `AzureFunction`): a repo, CI/CD and a handler for a container-image function that Glidepath deploys to an existing AWS Lambda function or Azure Container App. No chart, no Ground/Flight environments. *Not usable end to end yet*: Glidepath cannot push to ECR (Lambda needs it), and neither deploy target has run against a real account.
- **Ground** environment: `platform/envs/<env>.yaml` in the app repo, dev cluster only.
- **Flight** environment: an `ApplicationEnvironment` XR, rendering `gitops-<app>/<cluster>/<env>/values.yaml`.
- **Components** (Redis, PostgreSQL, RabbitMQ, MongoDB, ...) are entries in `components:` of an environment's values.
- One GitOps write path. Nothing is applied with `kubectl`.

## Do
- Validate before you open a PR: `helm template` the chart with your values file, and run `charts/airframe-application/tests/run.sh` if you changed the chart. The chart itself still silently ignores an unknown key (e.g. `rolout` or `replcas`) - `values.schema.json` is what rejects it, and `airframe-validate` is the enforced check on gitops PRs (Glidepath's values-validation gate), so run `tools/airframe-validate FILE` on your file.
- Changed `values.schema.json`? Run `python3 tools/gen_airframe_schema.py --write-values` and commit the regenerated `values.yaml` in the same change - CI's `--check` fails otherwise.
- Reference a component's connection details with `env: [{name: ..., fromComponent: {name: <components[] entry>, output: <name>}}]` (AF-3). Never hand-write derived names such as `cache-master` or `<name>-connection` - see that component's `xrds/<type>.meta.yaml` for its real output names. `airframe-validate` rejects a `fromComponent` reference to a component or output that doesn't exist (AF-COMP-002).
- Set `devCluster` from the cluster registry: it is `kind-dev` even though the cluster is called `kiac-dev`.
- Leave `release` (the image) and `releaseTracking` to the pipeline (Glidepath writes them). Change only what a human owns: config, env vars, scaling, components.
- Read the failure message, change the file, retry at most three times, then stop and report.
- Notice a `warn ... AF-COMP-003` on a file you're already touching? Migrate that reference to `fromComponent` while you're there - it's the exact gap AF-3 exists to close, just not yet enforced fleet-wide.

## Do not
- Hand-edit `release` (the image), `releaseTracking` or the deprecated `rollout.image` in a live env file. `airframe-validate` rejects it (AF-OWNER-001, error since AF-5b) when they appear in a human-owned file, or anything else in a release file.
- Use `extraManifests`, `networkPolicy` or `httpRoute` without a human's approval.
- Put a secret value in `env` or `configMaps`. Secrets are references to Infisical keys.
- Name an environment after a pipeline stage (`build`, `test`, `deploy`, `release`).
- Change a shared XRD or composition in place; ArgoCD self-heal reverts it. Test a copy through one XR's `spec.crossplane.compositionRef`.
- Commit, tag or push to a shared checkout without checking the branch and using a worktree. Humans cut tags.

## Rollout before an image exists
The chart renders no Rollout, RolloutWatch, Service or ServiceMonitor until both `release.image.repository`
and `release.image.tag` are set (the deprecated `rollout.image` still counts). A new app is safe to configure before its first build. Tests:
`charts/airframe-application/tests/run.sh`.

## Verify
A green pipeline is not verification; the service is. Check that pods are Ready and the endpoint answers,
and quote what you saw. *(planned: `airframe.verify` runs each component's verify contract.)*
- Redis, PostgreSQL and RabbitMQ each carry a custom `ComponentReady` condition (AF-6a), separate from
  Crossplane's own generic `Ready`/`Synced` - `kubectl get <kind> <name> -o jsonpath='{.status.conditions}'`
  gives a closed-set `reason` (e.g. `RedisReady`, `PostgreSQLDegraded`, `RabbitMQAttachProvisioning`) with a
  stable meaning, listed in that component's `xrds/<type>.meta.yaml` under `conditions`. Prefer this over
  the generic `Ready` condition when diagnosing why a component isn't up.

## Errors
If a chart guard or a check blocks you and you believe it is wrong, say so in the PR. Do not work around it.
