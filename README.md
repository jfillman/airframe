<div align="center">
  <img src="docs/brand/airframe-tile.svg" width="88" height="88" alt="Airframe mark" />
  <h1>Airframe</h1>
  <p><i>The structural core: what a compliant service is, defined once.</i></p>
</div>

Hangar's service catalog: Crossplane XRDs, their Compositions, two custom Composition Functions,
and the `airframe-application` Helm chart every app environment installs. A request is one XR
manifest committed to git; Airframe turns it into repositories, CI onboarding, a secrets store,
environments on other clusters, and the running service with its components attached.

- **Building an app on Hangar?** Start with the [user guide](docs/user/README.md).
- **Running or extending the catalog?** Read the [admin guide](docs/admin/README.md), starting
  with [architecture.md](docs/admin/architecture.md).
- **An agent?** Read [AGENTS.md](AGENTS.md) and [llms.txt](llms.txt) first.

## The catalog

Twenty kinds in the `catalog.hangar.io` group, all namespaced. Each XRD's `role` is declared in
its `xrds/<kind>.meta.yaml` sidecar.

| Role | Kinds | What one gives you |
|---|---|---|
| Bootstrap | `NodeJSApplication`, `PythonApplication`, `GoApplication`, `SpringBootApplication`, `InfraService`, `LambdaFunction`, `AzureFunction` | An onboarded app: source and gitops repos with starter files, CI onboarding, and a shared secrets store |
| Environment | `ApplicationEnvironment` | A Flight environment on another cluster: its `values.yaml`, `identity.yaml` and tenant entry |
| Platform | `TektonCICD`, `SecretStore` | Composed or requested by the kinds above, never by hand |
| Component | `Redis`, `PostgreSQL`, `RabbitMQ`, `MongoDB`, `Dex` | A backing service for one environment, declared in its `components:` list |
| Observability | `RolloutWatch`, `SLO` | Rollout watching with AI triage on `Degraded`; SLO rules through Sloth |
| Cloud target | `AwsLambdaTarget`, `AwsEcsTarget`, `AzureContainerAppTarget` | The cloud infrastructure a non-Kubernetes deploy needs |
| Cloud dependency | `MessageQueue`, `ObjectStorage`, `ManagedPostgreSQL` | A managed queue, bucket or database on AWS or Azure, private by default, with IAM grants to Lambda targets |

How the kinds compose, what each takes and returns, and the tiering rules are in
[architecture.md](docs/admin/architecture.md). Every kind's outputs, conditions and verify steps
are in the generated [contract](contract/airframe-contract.json); query it with
`tools/airframe-capabilities`.

## Layout

```
xrds/                         one XRD per kind, plus its <kind>.meta.yaml sidecar
compositions/<kind>/
  templates/                  the Go templates (<< >> delimiters); edit these
  composition.yaml            generated from templates/ by tools/build-compositions
  example/                    render cases (cases.yaml), fixtures, expected/ output
compositions/_shared/         partials the application compositions symlink (see its README)
charts/airframe-application/  the app chart; values.schema.json is the source of truth
charts/cluster-registry/      one ConfigMap per cluster, from the fleet's clusters.yaml
functions/                    function-rollout-watcher and function-dex; diagnosis-holmes-dispatch, the triage Job
contract/                     generated: airframe-contract.json, appspec.schema.json
analysis/                     ClusterAnalysisTemplates for canary analysis
tools/                        builders, generators, validators and test runners
docs/                         user and admin guides; examples/skyport/ is the demo system
```

## Working in this repo

Change a composition, then rebuild it and review the render diff:

```shell
python3 tools/build-compositions <kind>                 # regenerate composition.yaml
python3 tools/test_compositions.py --update <kind>      # regenerate example/expected/
git diff compositions/<kind>/example/expected/          # this diff is the behaviour change
```

Add a case to `example/cases.yaml` for every new branch. `tools/render-pipeline` renders any
composition through the real functions offline, with no cluster.

Change the chart's `values.schema.json`, then run `python3 tools/gen_airframe_schema.py
--write-values` and commit the regenerated `values.yaml`. Run `charts/airframe-application/tests/run.sh`
for chart changes.

Change an XRD, a sidecar or the chart schema, then regenerate the contract with
`python3 tools/gen_contract.py` and `python3 tools/gen_appspec_schema.py`. Autopilot vendors
`contract/appspec.schema.json` byte for byte, so a change to it needs the same change there.

CI (`.github/workflows/airframe-chart-ci.yaml`) runs every generator with `--check`, every render
case, the sidecar and contract tests, and the chart tests.

Validate a values file or an XR request before opening a pull request:

```shell
tools/airframe-validate glidepath/envs/dev.yaml
tools/airframe-validate --xr tenants/<app>/xr-requests/<kind>.yaml
```

Never hard-code a cluster name, GitHub owner or Infisical address: compositions read them from
the cluster registry. The rules for people and agents are in [AGENTS.md](AGENTS.md).
