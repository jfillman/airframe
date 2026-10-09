# Airframe architecture

The Crossplane-based service catalog behind Hangar. Eleven XRDs turn a git commit
into a running, CI/CD-onboarded, secret-provisioned service — **without any
cluster ever holding credentials for another cluster's API.** This is the wiring
underneath: what each catalog object takes in and gives back, how the pieces
compose, and what actually moves when a developer asks for a service.

> A diagram-led version of this document — architecture, entity-relationship, and
> sequence diagrams — is published at
> [Airframe Service Catalog](https://claude.ai/artifact/TBhiiN1TPjAbiwTTcctnK2).

## Everything routes through git

Airframe has no API server and no webhook receiver. A request to the catalog *is*
a commit — a manifest written into a tenant's `xr-requests/` folder. ArgoCD is the
only thing watching that commit; Crossplane is the only thing allowed to act on
what ArgoCD syncs. Everything downstream — repos, CI/CD onboarding, secrets, the
running workload — is a side effect of that one XR existing on a cluster.

The engine itself is permanently centralized on one dev cluster, because its only
two levers — `provider-upjet-github` and a GitOps commit — never need a
credential to any other cluster's API.

- **argocd-platform** — cluster-admin scoped, installs the catalog itself
- **argocd-apps** — app-owner facing, one `AppProject` per app
- Watched-repo sets never overlap between the two

## The catalog: eleven XRDs, one composition graph

All eleven kinds share the group `catalog.hangar.io`, are namespaced
(`apiextensions.crossplane.io/v2`), and rely on the standard `Ready`/`Synced`
conditions plus catalog-specific custom conditions layered on top. Only
`RolloutWatch` publishes a real `status.properties` schema.

| Kind | Tier | Key spec fields (inputs) | Status outputs | Composes / requests |
|---|---|---|---|---|
| `NodeJSApplication` | Bootstrap | `devCluster`\*, description, `nodeVersion` (18\|20\|22), `packageManager` (npm\|pnpm\|yarn), port, visibility | DevClusterReady, CicdOnboarded, Ready | → TektonCICD (direct) · → SecretStore *shared* (xr-requests) |
| `SpringBootApplication` | Bootstrap | `devCluster`\*, `javaVersion` (17\|21), `buildTool` (maven\|gradle), `groupId`, port, visibility | DevClusterReady, CicdOnboarded, Ready | → TektonCICD (direct) · → SecretStore *shared* |
| `GoApplication` | Bootstrap | `devCluster`\*, `goVersion` (1.22–1.24), port, visibility *(module path derived, not typed)* | DevClusterReady, CicdOnboarded, Ready | → TektonCICD (direct) · → SecretStore *shared* |
| `PythonApplication` | Bootstrap | `devCluster`\*, `pythonVersion` (3.11–3.13), `packageManager` (pip\|poetry\|uv), port, visibility | DevClusterReady, CicdOnboarded, Ready | → TektonCICD (direct) · → SecretStore *shared* |
| `InfraService` | Bootstrap | `devCluster`\*, description, visibility — NodeJSApplication minus src-repo/boilerplate, for shared infra with no app code | DevClusterReady, CicdOnboarded, Ready | → TektonCICD `type: infra` · → SecretStore *shared* |
| `ApplicationEnvironment` | Bootstrap | `appName`\*, `cluster`\* (live-gated: `type: upper`, `crossplaneReady`), `env`\*, `configMapGenerator`, `chart` (non-default chart for this env, written into identity.yaml; set by Glidepath flight-chart-sync, ADR-0023) | ClusterReady, AppResolved, Ready | → SecretStore *per-env* · `Usage` blocks parent deletion |
| `TektonCICD` | Bootstrap-adjacent | `appName`\*, `type` (app\|infra), `registerPipelinesAsCode`, `gitopsRepoUrl`\*, `appRepoUrl`\*, `devCluster`\* | DevClusterReady, CicdOnboarded | Composed only — never developer-created directly |
| `SecretStore` | Attached *(auto)* | `appRef.name`\*, `cluster`\*, `environmentSlug` (default `shared`) | Ready | Requested only, via xr-requests |
| `Redis` | Attached | `environmentRef.name`\* *(auto-stamped)*, `size` (small\|medium\|large), `persistence` | Ready | Rendered from a `components:` block |
| `SLO` | Attached | `environmentRef.name`\*, `service`\*, `objective`\* (0–100), `indicator`\* (availability\|latency) | Ready | Rendered from a `slos:` block; wraps Sloth |
| `RolloutWatch` | Attached | `environmentRef.name`\*, `appName`\*, `cluster`\*, `env`\*, `notifications.slack` | rolloutPhase, lastDiagnosisRevision, lastDiagnosisJob, lastDiagnosisTime | Rendered unconditionally alongside any release with a `rollout:` |
| `AwsLambdaTarget` | Cloud target | `functionName`, `region`, `architecture`, `runtime`, `memorySize`, `timeout`, `functionUrl`, `credentialsSecret` | TargetReady; status.functionUrl, repositoryUrl, roleArn, cicd | ECR Repository · IAM Role · bootstrap Job · Lambda Function (no Update) · FunctionURL + Permission |
| `AwsEcsTarget` | Cloud target | `appName`, `env`, `region`, `architecture`, `cpu`, `memory`, `containerPort`, `desiredCount`, `network` (create \| existing) | TargetReady; status.cluster, service, taskDefinitionFamily, containerName, subnetIds, securityGroupIds, cicd | IAM Role · VPC/Subnet/IGW/RouteTable/Route/SG (create mode) · ECS Cluster · TaskDefinition + Service (no Update) |
| `AzureContainerAppTarget` | Cloud target | `appName`, `resourceGroup`, `location`, `containerPort`, `bootstrapImage`, `size`, `minReplicas`, `maxReplicas`, `registry` | TargetReady; status.url, resourceGroup, environment, cicd | ResourceGroup · Container Apps Environment · ContainerApp (no Update) · optional registry Secret |

\* required field

### Composition graph

Every Bootstrap-tier app stack composes a `TektonCICD` child **directly** — a
normal in-process composition, safe because `TektonCICD` only ever calls the
GitHub API. `ApplicationEnvironment` composes a `Usage` directly, blocking parent
deletion while the environment exists.

`SecretStore` is the one deliberate exception: both the app stacks and
`ApplicationEnvironment` create `SecretStore` XRs by **committing a manifest via
`xr-requests/`** rather than composing it in-process, because `SecretStore`'s own
composed `ClusterSecretStore` has to land on the *target* cluster's API, and
Bootstrap-tier XRs are `provider-github`-only, centralized on one dev cluster,
with no credential to any other cluster's API. `TektonCICD` doesn't need this
indirection because it never touches a target cluster's API at all.

## Tiering

The tier isn't a UI grouping — it's the mechanism.

| Tier | Members | Mechanism | Lifecycle |
|---|---|---|---|
| **Bootstrap** | 5 app stacks, ApplicationEnvironment *(TektonCICD is Bootstrap-adjacent)* | A commit into `xr-requests/`, reconciled by `provider-github` — no live API call, no K8s credential | Creates a new addressable git location — a repo, or a `<cluster>/<env>/values.yaml` |
| **Cloud target** | AwsLambdaTarget, AwsEcsTarget, AzureContainerAppTarget | A stand-alone XR in the app's xr-requests (or, for the two function stacks, a child composed by the app XR with `spec.target.enabled`) | The cloud infrastructure a `deploy.target` deploy updates; disposable, lives only while the XR does |
| **Attached** | SLO, Redis, RolloutWatch · SecretStore (auto) · *planned, unbuilt: OAuthServer, Database, Queue, mongodb, nginx* | A `components:`/`slos:` block inside an env's own `values.yaml` | Independent lifecycle, but only expressible inside an existing environment's file |
| **Embedded** | config maps, secrets, HPA, PodDisruptionBudget, AnalysisTemplate, resource limits, volumes, networkPolicy | Plain fields on the same `values.yaml` — no XR at all | 1:1 with the single workload the release owns |

Bootstrap-tier is permanently centralized on one dev cluster, regardless of fleet
size. Attached-tier must run per-cluster — it composes native in-cluster
resources directly.

## The plumbing

Every Composition is a `function-go-templating` pipeline (inline source — a
second registered Function package once corrupted Crossplane's shared
dependency-lock graph cluster-wide) plus a `function-auto-ready` step.

- **GitHub** — `provider-upjet-github`, a classic PAT (`repo` + `delete_repo`).
  Creates `Repository` + `RepositoryFile` resources: the src repo, boilerplate
  (including a minimal, real, build-only `cicd.yaml` matching the stack's own
  version field — added 2026-09-21, see Glidepath's ADR-0017; every Bootstrap
  app stack scaffolds one now, so onboarding is self-service end to end
  instead of stopping one manual step short of a runnable pipeline), the
  empty `gitops-<app>` repo, `identity.yaml`, release `values.yaml`.
  Scaffold files (anything the developer owns after the first write: source
  boilerplate, `cicd.yaml`, READMEs, the bootstrap `values.yaml`) are composed
  only until they are observed Ready, then recorded in the XR's
  `status.scaffold.done` and retired as managed resources while the GitHub file
  stays ("scaffold once, reconcile never"; `compositions/_shared/README.md`).
  Only the platform-owned files (`identity.yaml`, the SecretStore XR requests,
  `cluster-identity.yaml`) remain managed and drift-corrected.
- **Secrets** — `provider-infisical` + ESO. `Project`/`ProjectEnvironment`/
  `Identity`/`ProjectIdentity` managed resources, wrapped through
  `provider-kubernetes` into a real ESO `ClusterSecretStore`. Kubernetes Auth on
  the Infisical-hosting cluster, Universal Auth elsewhere.
- **Compute** — `provider-helm`. `Redis` composes a `Release` of a
  Bitnami-derived chart — the only Component XRD with a real workload behind it
  today.
- **Observability** — `SLO` renders a Sloth `PrometheusServiceLevel`.
  `RolloutWatch` matches the live Rollout via a Crossplane extra-resources
  lookup and, on `Degraded`, dispatches a diagnosis Job to a per-cluster
  HolmesGPT service, which can open a fix PR back into the GitOps repo.

## Request flow, end to end

1. Developer/Tower commits an XR into `tenants/<app>/xr-requests/<kind>.yaml`.
2. ArgoCD syncs the namespace and the XR manifest in one operation.
3. Crossplane's Composition Function pipeline renders the desired managed
   resources; `provider-upjet-github` creates the repos/files; a `TektonCICD`
   child is composed in the same pipeline; a `SecretStore` XR is committed via
   `xr-requests` for the shared-mode Infisical store.
4. `DevClusterReady` and `CicdOnboarded` surface as custom conditions.
5. An `ApplicationEnvironment` request follows the same `xr-requests` pattern,
   gated by `ClusterReady`. It commits `<cluster>/<env>/values.yaml` (initially
   `rollout: null`) and a tenant-onboarding entry into the target cluster's own
   tenants repo — no cross-cluster credential ever used.
6. The target cluster's own tenant-onboarding `ApplicationSet` picks up the
   entry and creates the namespace/`Application`/`AppProject` on its own.
7. A real CI/CD pipeline run eventually produces a PR setting `rollout.image`;
   once merged, `airframe-application` renders the real `Rollout`/Service and
   any `components:`/`slos:` blocks. Whether that workload is up is the target
   cluster's Rollout and Argo CD `Application` status, read there (Tower, the
   walkthroughs); the `ApplicationEnvironment` XR on the dev cluster cannot observe it
   and no longer pretends to (the old `WorkloadDeployed` condition was computed from
   the bootstrap seed and stayed `False` forever). Its own conditions are
   `ClusterReady` (the registry gate) and `AppResolved` (`spec.appName` names a real
   app XR; `AppNotFound` is the typo/ordering signal).
8. `RolloutWatch` watches the live Rollout; on `Degraded` it dispatches a
   diagnosis Job, closing the AI-triage loop.

## Where policy lives

Everything above is also the enforcement map for governance and security: the XRD schema is what may
be asked for, the composition is how it is built, management policies are what the platform may do to
what it made, the provider configs are who acts, and the GitOps write path is who approves.
Enterprise architects and security teams own those decisions; the platform team encodes them here,
once, and every service inherits them. [governance.md](governance.md) walks the ladder layer by
layer, lists what is enforced by machinery today versus still convention, and shows how a written
policy becomes a change to an XRD or a composition.

## Not yet built — don't read these as live

- `OAuthServer`, `Database`/postgresql, `Queue`/rabbitmq, mongodb, nginx — zero
  XRDs exist
- `BranchProtection` — deliberately deferred (needs real CI status-check names)
- Platform default canary steps — the chart ships an inert single-step placeholder
- `ClusterAnalysisTemplate` golden-path library — belongs in `idp-cluster-baseline`,
  not built there yet
- A second real dev cluster — the registry gate exists, nothing has exercised it
- Env-deletion / ArgoCD-prune deadlock — downgraded to monitor-only, not proven
  resolved
