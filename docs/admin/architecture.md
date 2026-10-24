# Airframe architecture

The Crossplane-based service catalog behind Hangar. Twenty XRDs turn a git commit into a
running, CI/CD-onboarded, secret-provisioned service, **without any cluster ever holding
credentials for another cluster's API.** This page covers what each catalog kind takes in and
gives back, how the kinds compose, and what moves when a developer asks for a service.

> A diagram-led version of this document is published at
> [Airframe Service Catalog](https://claude.ai/artifact/TBhiiN1TPjAbiwTTcctnK2).

## Everything routes through git

Airframe has no API server and no webhook receiver. A request to the catalog *is* a commit: a
manifest written into a tenant's `xr-requests/` folder. ArgoCD is the only thing watching that
commit, and Crossplane is the only thing allowed to act on what ArgoCD syncs. Everything
downstream (repos, CI/CD onboarding, secrets, the running workload) follows from that one XR
existing on a cluster.

App stacks are composed on one dev cluster, because their only two levers,
`provider-upjet-github` and a GitOps commit, never need a credential to any other cluster's API.
Two ArgoCD instances split the work, and their watched-repo sets never overlap:

- **argocd-platform**: cluster-admin scoped, installs the catalog itself
- **argocd-apps**: app-owner facing, one `AppProject` per app

## The catalog: twenty XRDs

All twenty kinds share the group `catalog.hangar.io`, are namespaced
(`apiextensions.crossplane.io/v2`), and report the standard `Ready`/`Synced` conditions plus
custom conditions with closed reason sets. Each kind's outputs, conditions and verify steps are
listed in its `xrds/<kind>.meta.yaml` sidecar and in the generated
[contract](../../contract/airframe-contract.json).

| Kind | Role | Key spec fields | Status | Composes or requests |
|---|---|---|---|---|
| `NodeJSApplication` | Bootstrap | `devCluster`\*, `nodeVersion`, `packageManager`, `deployTarget` (kubernetes\|aws-ecs), `ecs`, `port`, `visibility`, `extraGitopsRepos` | DevClusterReady, CicdOnboarded, `status.scaffold` | Repos and scaffold files · TektonCICD (direct) · SecretStore *shared* (xr-requests) · AwsEcsTarget when `deployTarget: aws-ecs` |
| `SpringBootApplication` | Bootstrap | `devCluster`\*, `javaVersion`, `buildTool`, `groupId`, `deployTarget`, `ecs`, `port`, `visibility` | same | same |
| `GoApplication` | Bootstrap | `devCluster`\*, `goVersion`, `deployTarget`, `ecs`, `port`, `visibility` | same | same |
| `PythonApplication` | Bootstrap | `devCluster`\*, `pythonVersion`, `packageManager`, `deployTarget`, `ecs`, `port`, `visibility` | same | same |
| `InfraService` | Bootstrap | `devCluster`\*, `description`, `visibility`: a gitops-infra repo for shared infrastructure with no app code | DevClusterReady, CicdOnboarded | gitops-infra repo · TektonCICD `type: infra` · SecretStore *shared* |
| `LambdaFunction` | Bootstrap | `devCluster`\*, `runtime`, `architecture`, `region`, `functionName`, `target` | DevClusterReady, CicdOnboarded, TargetReady | Source repo and scaffold · TektonCICD · SecretStore *shared* · AwsLambdaTarget when `target.enabled` |
| `AzureFunction` | Bootstrap | `devCluster`\*, `resourceGroup`\*, `runtime`, `appName`, `target` | same | same, with AzureContainerAppTarget |
| `ApplicationEnvironment` | Environment | `appName`\*, `cluster`\* (registry-gated), `env`\*, `appType`, `configMapGenerator`, `chart` | ClusterReady, AppResolved, `status.scaffold` | `<cluster>/<env>/values.yaml` and `identity.yaml` · tenant entry in the target cluster's tenants repo · SecretStore *shared* and *per-env* (xr-requests) · `Usage` blocking app deletion |
| `TektonCICD` | Platform | `appName`\*, `appRepoUrl`\*, `devCluster`\*, `type` (app\|infra), `gitopsRepoUrl`, `registerPipelinesAsCode`, `extraGitopsRepos` | DevClusterReady, CicdOnboarded | `tenants/<app>/identity.yaml` · composed only, never created directly |
| `SecretStore` | Platform | `appRef.name`\*, `cluster`\*, `environmentSlug` (default `shared`) | Ready | Infisical project, environment and identity · ESO `ClusterSecretStore` · requested only, via xr-requests |
| `Redis` | Component | `environmentRef`\*, `size`, `persistence` | ComponentReady | provider-helm `Release` of Bitnami's chart |
| `PostgreSQL` | Component | `environmentRef`\*, `size`, `instances`, `storageSize`, `databaseName` | ComponentReady | CloudNativePG `Cluster` · NetworkPolicy |
| `RabbitMQ` | Component | `environmentRef`\*, `mode`\* (broker\|attach); broker: `size`, `instances`, `vhosts`; attach: `brokerRef`, `vhost`, `queuePrefix`, `publish`, `consume` | ComponentReady | broker: `RabbitmqCluster`, a `Vhost` per entry, NetworkPolicy; attach: `User`, `Permission`, `Usage` on the broker |
| `MongoDB` | Component | `environmentRef`\*, `members`, `storageSize`, `mongoVersion`, `databaseName` | ComponentReady | `MongoDBCommunity` replica set and its RBAC |
| `Dex` | Component | `environmentRef`\*, `mode`\* (server\|attach); server: `size`, `allowedNamespaces`; attach: `serverRef`, `clientId`, `scopes` | ComponentReady | server: the shared Dex server; attach: an OAuth2 client, through `function-dex` |
| `SLO` | Observability | `environmentRef`\*, `service`\*, `objective`\*, `indicator`\* | Ready | Sloth `PrometheusServiceLevel` |
| `RolloutWatch` | Observability | `environmentRef`\*, `appName`\*, `cluster`\*, `env`\*, `notifications.slack` | `rolloutPhase`, `lastDiagnosis*` | A diagnosis Job on `Degraded`, through `function-rollout-watcher` |
| `AwsLambdaTarget` | Cloud target | `functionName`, `region`, `architecture`, `runtime`, `memorySize`, `timeout`, `functionUrl` | TargetReady; `functionUrl`, `repositoryUrl`, `roleArn`, `cicd` | ECR repository · execution and deploy roles · Lambda function · Function URL |
| `AwsEcsTarget` | Cloud target | `appName`, `env`, `region`, `architecture`, `cpu`, `memory`, `containerPort`, `desiredCount`, `network` (create\|existing) | TargetReady; `cluster`, `service`, `subnetIds`, `cicd`, ... | ECR repository · IAM roles · VPC and subnets (create mode) · ECS cluster, task definition and service |
| `MessageQueue` | Cloud dependency | `cloud` (aws\|azure), `queueName`, `fifo`, `lockSeconds`, `retentionSeconds`, `deadLetter`, `consumers[]` (AwsLambdaTarget, access, trigger) | DependencyReady; `url`, `arn`, `namespace`, `consumers` | SQS queue + dead-letter queue · role grants · Lambda event source mappings / Service Bus namespace, queue, SAS rule |
| `ObjectStorage` | Cloud dependency | `cloud`, `bucketName`, `versioning`, `emptyOnDelete`, `consumers[]` | DependencyReady; `arn`, `endpoint`, `storageAccount` | S3 bucket + public access block, ownership, encryption, versioning · role grants / Storage Account + container |
| `ManagedPostgreSQL` | Cloud dependency | `cloud`, `serverName`, `version`, `size`, `storageGiB`, `databaseName`, `allowedCidrs`, `protect` | DependencyReady; `host`, `port`, `database`, `username` | VPC, subnets, security group, RDS instance / Flexible Server, database, firewall rules |
| `AzureContainerAppTarget` | Cloud target | `appName`, `resourceGroup`, `location`, `containerPort`, `size`, `minReplicas`, `maxReplicas`, `registry` | TargetReady; `url`, `environment`, `cicd` | Resource group · Container Apps environment · Container App |

\* required field

### Composition graph

Every Bootstrap app stack composes a `TektonCICD` child **directly**: a normal in-process
composition, safe because `TektonCICD` only ever calls the GitHub API. `ApplicationEnvironment`
composes a `Usage` directly, blocking deletion of the app XR while the environment exists. An
app stack with `deployTarget: aws-ecs`, and a function stack with `target.enabled`, composes its
cloud target the same way.

`SecretStore` is the one deliberate exception: the app stacks and `ApplicationEnvironment` create
`SecretStore` XRs by **committing a manifest via `xr-requests/`** rather than composing it
in-process. A `SecretStore`'s `ClusterSecretStore` has to land on the *target* cluster's API, and
the dev cluster that composes app stacks has no credential to any other cluster's API.

## Tiering

The tier isn't a UI grouping; it decides where a kind runs and how it is asked for.

| Tier | Members | Mechanism | Lifecycle |
|---|---|---|---|
| **Bootstrap** | 7 app and function stacks, ApplicationEnvironment, TektonCICD | A commit into `xr-requests/`, reconciled on the dev cluster by `provider-upjet-github`, with no Kubernetes credential to another cluster | Creates a new addressable git location: a repo, or a `<cluster>/<env>/` folder |
| **Cloud target** | AwsLambdaTarget, AwsEcsTarget, AzureContainerAppTarget | A stand-alone XR in the app's xr-requests, or a child composed by its app XR | The cloud infrastructure a non-Kubernetes deploy updates; lives only while the XR does |
| **Cloud dependency** | MessageQueue, ObjectStorage, ManagedPostgreSQL | A stand-alone XR in the app's xr-requests, on the dev cluster where the cloud providers run | A managed cloud service an app uses; lives only while the XR does |
| **Attached** | Redis, PostgreSQL, RabbitMQ, MongoDB, Dex, SLO, RolloutWatch · SecretStore (requested automatically) | A `components:` or `slos:` block in an environment's `values.yaml`, rendered as XRs by the chart | Its own lifecycle, but only expressible inside an existing environment |
| **Embedded** | config maps, secrets, HPA, PodDisruptionBudget, AnalysisTemplate, resource limits, volumes, networkPolicy | Plain fields in the same `values.yaml`, no XR | 1:1 with the one workload the release owns |

Bootstrap-tier kinds are composed on one dev cluster however large the fleet is. Attached-tier
kinds run on each cluster, because they compose in-cluster resources directly.

## The plumbing

Most Compositions are an inline `function-go-templating` pipeline plus a `function-auto-ready`
step. Every composition shares the one registered `function-go-templating`: a second Function
object for the same package corrupts Crossplane's package dependency graph for every function on
the cluster. `Dex` and `RolloutWatch` run their own functions from `functions/`.

- **GitHub**: `provider-upjet-github`. Creates `Repository` and `RepositoryFile` resources: the
  src repo and its scaffold (including a build-only `cicd.yaml` matching the stack's version
  field), the empty `gitops-<app>` repo, `identity.yaml`, and the environment `values.yaml`.
  Scaffold files (anything the developer owns after the first write) are composed only until they
  are observed Ready, then recorded in the XR's `status.scaffold.done` and retired as managed
  resources while the GitHub file stays ([`compositions/_shared/README.md`](../../compositions/_shared/README.md)).
  Only the platform-owned files (`identity.yaml`, the SecretStore XR requests,
  `cluster-identity.yaml`) remain managed and drift-corrected.
- **Secrets**: `provider-infisical` and ESO. `Project`, `ProjectEnvironment`, `Identity` and
  auth resources, plus a `ClusterSecretStore` through `provider-kubernetes`. Kubernetes auth on
  the cluster that hosts Infisical, universal auth elsewhere.
- **Components**: `Redis` composes a `provider-helm` `Release`; `PostgreSQL`, `RabbitMQ` and
  `MongoDB` compose the custom resources of their operators (CloudNativePG, the RabbitMQ cluster
  and topology operators, the MongoDB Community operator); `Dex` renders its server or registers a
  client through `function-dex`.
- **Cloud**: the Upbound AWS and Azure providers. Every composed IAM role carries the fleet's
  permissions boundary, and AWS deploys assume a role with a ServiceAccount token instead of a
  stored key ([cloud-credentials.md](cloud-credentials.md)).
- **Observability**: `SLO` renders a Sloth `PrometheusServiceLevel`. `RolloutWatch` reads the
  live Rollout through an extra-resources lookup and, on `Degraded`, dispatches a diagnosis Job
  to a per-cluster HolmesGPT service, which can open a fix PR back into the GitOps repo. Canary
  analysis templates live in [`analysis/`](../../analysis/README.md).
- **Cluster facts**: every composition reads cluster names, roles, the GitHub owner and the
  Infisical address from the cluster registry (`charts/cluster-registry`), never from a literal.

## Request flow, end to end

1. A developer or Tower commits an XR into `tenants/<app>/xr-requests/<kind>.yaml`.
2. ArgoCD syncs the namespace and the XR manifest in one operation.
3. The composition renders the desired managed resources; `provider-upjet-github` creates the
   repos and files; a `TektonCICD` child is composed in the same pipeline; a `SecretStore` XR is
   committed via `xr-requests` for the shared Infisical store.
4. `DevClusterReady` and `CicdOnboarded` surface as custom conditions.
5. An `ApplicationEnvironment` request follows the same `xr-requests` pattern, gated by
   `ClusterReady`. It commits `<cluster>/<env>/values.yaml` (identity only; nothing renders until
   a release sets an image) and a tenant-onboarding entry into the target cluster's own tenants
   repo, without using any cross-cluster credential.
6. The target cluster's tenant-onboarding `ApplicationSet` picks up the entry and creates the
   namespace, `Application` and `AppProject` itself.
7. A pipeline run produces a PR setting `release.image`; once merged, `airframe-application`
   renders the `Rollout`, Service and any `components:`/`slos:` blocks. Whether the workload is up
   is read on the target cluster (its Rollout and ArgoCD `Application`, or Tower). The
   `ApplicationEnvironment` XR on the dev cluster cannot observe it; its conditions are
   `ClusterReady` (the registry gate) and `AppResolved` (`spec.appName` names a real app XR;
   `AppNotFound` means a typo or an environment requested before its app).
8. `RolloutWatch` watches the live Rollout; on `Degraded` it dispatches a diagnosis Job.

## Where policy lives

Everything above is also the enforcement map for governance and security: the XRD schema is what
may be asked for, the composition is how it is built, management policies are what the platform
may do to what it made, the provider configs are who acts, and the GitOps write path is who
approves. Enterprise architects and security teams own those decisions; the platform team encodes
them here, once, and every service inherits them. [governance.md](governance.md) walks the ladder
layer by layer, lists what is enforced by machinery today versus still convention, and shows how
a written policy becomes a change to an XRD or a composition.

## Not built

- `BranchProtection`: deferred until CI status-check names are stable.
- Platform default canary steps: `rollout.strategy: canary` renders a single inert
  `setWeight: 100` step unless the values give steps.
- Azure deploys against a real subscription: `AzureFunction` and `AzureContainerAppTarget` are
  render-tested only. Lambda and ECS deploys have run end to end.
- A second dev cluster: the registry gate supports it, nothing has exercised it.
- Environment deletion: a possible deadlock with ArgoCD pruning is monitored, not proven resolved.

Known issues found in use are in [known-gaps.md](known-gaps.md).
