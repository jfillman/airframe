# Governance and security policy: who decides, where it is enforced

Airframe is the policy layer of Hangar. Enterprise architects and security teams decide what a
compliant service is; the platform team implements those decisions **here, once**, as XRD schemas,
compositions, management policies, provider identities and pre-merge checks; every service in the
fleet then inherits them. A developer, a Tower form or an AI agent never configures compliance. They
ask for a kind (`PythonApplication`, `PostgreSQL`, `AwsLambdaTarget`) with a few fields, and what
they get is compliant because the only way to get it is through this layer.

This page is the map: which role owns which decision, where in this repository each kind of
decision lives, which controls are enforced by machinery today and which are still convention, and
how a policy change ships.

## Who owns what

| Role | Owns | Where it lands in this repo |
|---|---|---|
| **Enterprise architects** | The menu and the standards: which service kinds exist and which do not (there is no "raw VM" kind on purpose), approved regions and clusters, sizing tiers, naming and tagging conventions, tenancy (dedicated vs shared), the environment model (Ground on the dev cluster, Flight on upper clusters), which escape hatches exist at all. | The XRD: its kinds, fields, enums, patterns and defaults are the menu. The cluster registry (`gitops-cluster-dev/00-bootstrap/cluster-registry/`) is the list of places a request may land. |
| **Security team** | The must-list: identity and least privilege, network exposure, secrets handling, encryption, image provenance, deletion and data protection, audit trail, what an agent may touch. Each "must" maps to one enforcement point below, or is written down as not yet enforced. | The composition (every setting the requester never sees), management policies, provider `ClusterProviderConfig`s, `airframe-validate` rules, `AGENTS.md`. |
| **Platform team** | Implementation and change control: turning both of the above into schema, templates and checks; releasing them as tagged versions pinned per cluster; keeping the contract bundle and docs truthful so humans and agents know the rules. | `xrds/`, `compositions/`, `charts/`, `tools/`, `contract/`, this guide. |
| **Application teams and agents** | Consumption. They request kinds, set the fields the schema exposes, and propose exceptions as pull requests against this repo. They do not work around a guard; a guard that blocks a legitimate need is a policy bug to raise, not an obstacle to route around (see `AGENTS.md`, Errors). | `tenants/<app>/xr-requests/`, `glidepath/envs/`, `gitops-<app>/`. |

The division is deliberate: the people who write policy rarely write Crossplane, and the people who
write Crossplane should not be deciding the policy. A policy is only "done" when it is encoded at one
of the enforcement points below and the row in [What is enforced today](#what-is-enforced-today)
says so.

## The enforcement ladder

A request passes through these layers in order. Each one answers a different question, and a policy
belongs at the lowest layer that can enforce it.

### 1. The XRD schema: what may be asked for

Enforced by the Kubernetes API server at admission, before anything is created. Enums, patterns,
bounds, defaults, required fields and CEL cross-field rules (`x-kubernetes-validations`) are policy:

- `Redis.spec.size` is `small | medium | large`, nothing else; the presets map to vetted CPU and
  memory, and a bigger tier is a catalog change, not a per-app override.
- `AwsLambdaTarget.spec.region` and `AwsEcsTarget.spec.region` are pattern-constrained today and are
  the natural place for an approved-region enum.
- `NodeJSApplication.spec.visibility` defaults to `private`; a public repository is an explicit choice.
- `RabbitMQ` refuses `mode: attach` without `brokerRef` and `vhost`; `AwsEcsTarget` refuses
  `network.mode: existing` without subnet and security-group ids; `SLO` refuses an availability
  indicator without `errorFilter`. These are CEL rules, and they fail the request with the message
  written next to the rule.
- `ApplicationEnvironment.spec.cluster` is checked live against the cluster registry: only a
  registered `type: upper` cluster with `crossplaneReady: "true"` is a valid Flight destination, and a
  dev cluster is a structural rejection.

What this layer cannot do today: reject an unknown field. The API server prunes it silently, so a
misspelled field is accepted and ignored (roadmap item U1). Until an `--xr` mode of
`airframe-validate` or server-side apply with strict field validation lands on the `xr-requests`
ApplicationSets, a typo in an XR is a policy gap, and this page says so rather than pretending.

### 2. Pre-merge validation: what may be committed

Enforced by `tools/airframe-validate`, which Glidepath's `values` release guardrail runs as a
required check on the gitops repositories, and by the chart's own render guards. Rules have stable
ids and fix hints, so an agent can retry against them deterministically:

- `AF-SECRET-001`: a value that looks like a credential (an AWS key id, a GitHub or Slack token, a
  private key, a JWT) in `env` or `configMaps` fails the check. Secrets are references to Infisical,
  never values.
- `AF-OWNER-001`: a release-owned key (`release`, `releaseTracking`) in a human-owned file, or
  anything else in a release file, fails. Humans and the release pipeline never edit the same keys.
- `AF-COMP-001/002`: an unknown component type, or a `fromComponent` reference to an output the
  component does not declare, fails.
- Chart guards: a developer label that would override a chart-owned identity label, a `podSpec`
  that replaces the container list, `releaseTracking` on a release with no Rollout, each fail the
  render with a message naming the key.

The strict values schema (`additionalProperties: false` everywhere but the documented
passthroughs) is itself policy: the chart accepts exactly the fields the catalog describes.

### 3. The composition: how it is built

Enforced by Crossplane rendering what the template says, every reconcile. This is where most
security policy lives, because it is everything the requester never sees. Examples that exist today:

- **Least privilege.** The Lambda execution role carries `AWSLambdaBasicExecutionRole` and nothing
  else; the ECS execution role carries `AmazonECSTaskExecutionRolePolicy` plus `logs:CreateLogGroup`.
  The Infisical machine identity per app is `no-access` at the organization and `viewer` on its own
  project only. Kubernetes Auth for Infisical is scoped to External Secrets' own ServiceAccount.
- **Network exposure.** An ECS target's security group opens exactly `containerPort`; a PostgreSQL
  component's NetworkPolicy admits only the operator namespace; a Dex server's admin port is
  reachable only from `crossplane-system`; every app namespace carries the chart's baseline
  NetworkPolicy, which admits ingress only from the namespace itself and the ingress controller.
- **Tenancy and isolation.** Databases and caches are dedicated per application environment; a
  shared broker admits only the namespaces its `allowedNamespaces` list names, and each attacher
  gets a user whose permissions are generated from names, never written as raw regexes. Per-env
  Infisical environments are read through a `ClusterSecretStore` narrowed to one namespace.
- **Provenance.** Placeholder images come from `public.ecr.aws/lambda/*` and
  `mcr.microsoft.com/azure-functions/*`; every component pins its upstream chart or image version;
  Glidepath's pipeline is the only thing that ever deploys a built image.
- **Tags and names.** Every cloud resource a target composes carries `hangar.io/target`,
  `hangar.io/component`, `hangar.io/app` and `hangar.io/env` tags; every Kubernetes object a
  component composes carries the XR's `hangar.io/*` labels, so ownership and cost are queryable.
- **Secrets.** Database passwords are generated by the operator (CloudNativePG, RabbitMQ) or once by
  the composition and never rotated by accident (MongoDB, Dex); a Container App's registry token is a
  Secret reference the XR names, never a value in the XR.

### 4. Management policies: what the platform may do to what it made

Enforced by Crossplane per managed resource. These are data-protection and ownership policy:

- **Never delete developer data.** Scaffolded repository files (`cicd.yaml`, the boilerplate, a
  README) and the Infisical project and environments carry no `Delete` policy: removing the
  Kubernetes object never removes the file or the secrets. A `Delete` policy on these once destroyed
  `cicd.yaml` in five repositories and two apps' Infisical projects; the policy is the fix.
- **Never overwrite what someone else owns.** Scaffold files carry no `Update` policy and
  `overwriteOnCreate: false`; the deploy surfaces of every cloud target (the Lambda function, the ECS
  task definition and service, the Container App) carry no `Update` policy because Glidepath owns
  the image after the first deploy.
- **Disposable by design where that is the policy.** A cloud target's ECR repository is
  `forceDelete: true` and its Azure resource group is created and owned, so deleting the XR removes
  everything, including images and data. That is the right policy for a smoke target and the wrong
  one for a persistent environment; a persistent variant is the same composition with those two
  settings flipped.

### 5. Identity: who acts

Enforced by provider configuration and the secrets topology:

- The platform acts on GitHub, Infisical, AWS and Azure through **one platform-owned credential per
  system**, held in a `ClusterProviderConfig`'s Secret in `crossplane-system`, delivered by External
  Secrets from the platform's own Infisical project, never present in an XR, a composition or git.
  Scoping that credential (a GitHub App instead of a PAT, an AWS identity limited to the five services
  the targets use) is a security-team decision and a one-file change.
- Applications never hold a platform credential. They read their own secrets from their own
  Infisical project through their own store; the cloud credentials Glidepath deploys with are the
  app's own, listed in its `cicd.yaml`.
- No cluster holds a credential to another cluster's API: Flight environments are created by a
  commit the target cluster's own Argo CD acts on.
- Agents are meant to act through Clearance (Autopilot): tool tiers, budgets and a field-level
  allow and deny list over the files they may change, with CEL rules that carry stable ids and hints,
  the same shape as `airframe-validate`. Clearance is built and tested but not deployed yet; today an
  agent's limits are `AGENTS.md` and the same pre-merge checks a human faces.

### 6. The write path: who approves

Enforced by GitOps: nothing is applied with `kubectl`. A new service, environment or cloud target
is a commit into `tenants/<app>/xr-requests/` that a human merges; an upper-environment
configuration change is a pull request a human merges; a catalog change is a pull request here, a
tag, and a pin bumped per cluster. Argo CD's self-heal reverts a hand edit to a shared XRD or
composition, which is why a risky composition change is tested through a copy
pointed at one XR's `compositionRef` first. The lower and upper `AppProject`s keep an app's
Ground-tier identity from reaching Flight-tier destinations.

### 7. Evidence: how anyone can tell

Every XRD reports standard `Ready`/`Synced` conditions plus catalog-specific conditions with a
closed reason set (`ComponentReady`, `TargetReady`, `ClusterReady`, `AppResolved`, `CicdOnboarded`),
listed with their meaning in each `xrds/<kind>.meta.yaml` and the contract bundle. The AI-friendliness
scorecard (`hangar/tools/airframe-scorecard`) runs in CI when the fleet read token is present and fails
on regression. Glidepath records
every release with provenance and signatures. What the catalog does not yet produce is a compliance
report per XR; the conditions and tags are the raw material for one.

## What is enforced today

| Control | Enforced | By |
|---|---|---|
| Field values, enums, bounds, cross-field rules on every XR | Yes | XRD schema and CEL at admission |
| Unknown fields on an XR | **No** (pruned silently) | planned: `airframe-validate --xr`, strict server-side apply |
| Values-file strictness, secret-looking literals, ownership split | Yes on gitops repos | `airframe-validate` as a required check (Glidepath `values` guardrail) |
| The same on app repos (`glidepath/envs/`) and the tenants repo | **No** (convention) | roadmap AF-4b |
| Least-privilege roles, network rules, tenancy, tags | Yes | compositions |
| No deletion of developer data and secrets; no overwrite of pipeline-owned fields | Yes | management policies |
| Platform credentials outside git and XRs; per-app secret isolation | Yes | provider configs, External Secrets, per-env stores |
| `extraManifests`, `networkPolicy`, `httpRoute` require a human | **No** (convention) | `AGENTS.md`; the Clearance field deny list is built, not deployed |
| Image signatures and provenance | At release, by Glidepath | not yet at admission on the cluster |
| Composition changes reviewed by security | **No** (convention) | a reviewer from the security team on `xrds/` and `compositions/` is the natural gate; not enforced |

## Turning a policy into catalog code

| Policy, as written by its owner | Layer | The change |
|---|---|---|
| "AWS workloads run only in us-east-1 and eu-west-1." | 1 | Replace the `region` pattern on `AwsLambdaTarget`, `AwsEcsTarget` and `LambdaFunction` with an enum. |
| "A Lambda function is private unless a ticket says otherwise." | 1 + 3 | `AwsLambdaTarget.spec.functionUrl` defaults to `false`; the Function URL and its public permission already render only when it is `true`. |
| "No internet-facing ECS task." | 3 | Drop the `0.0.0.0/0` ingress rule and `assignPublicIp`; put an internal load balancer in the composition, or require `network.mode: existing` with security-approved subnets and groups. |
| "Every cloud resource carries a cost center." | 1 + 3 | A required `costCenter` field on the target XRDs, rendered into every resource's `tags`. |
| "Container images come only from the organization's registry." | 1 + 2 | A pattern on `bootstrapImage`; Glidepath's `image-repo`; a new `airframe-validate` rule for any image literal in a values file. |
| "A decommissioned app keeps its database for 30 days." | 4 | No `Delete` policy on the CloudNativePG `Cluster`, and a documented, separate cleanup action. |
| "Developers size caches, but only within tiers security has reviewed." | 1 | The `size` enum is the review; widen it, never bypass it. |
| "Agents may change replicas, never network policy." | 5 | `AGENTS.md` today; the field deny list in the agent's Clearance definition (`/networkPolicy`, `/httpRoute`, `/extraManifests`) once Clearance is deployed. |

In every row the requester's experience does not change: the same kind, the same few fields. The
policy is in what those fields are allowed to be and in what the composition does with them.

## How a policy change ships

1. The owner writes the policy down in this page's terms: the layer it belongs to and the row in the
   table above it changes.
2. The platform team changes the XRD or the composition in a pull request. Templates are rendered
   offline through the real functions (`tools/render-pipeline` with each composition's `example/`
   fixtures), the chart tests, `airframe-validate` and the contract generator run in CI, and
   `AGENTS.md` and the field descriptions are updated so humans and agents see the new rule.
3. A change to an already-composed managed resource is a fleet-wide write even without an
   `Update` policy; it is planned as a migration, tested through a copy of the composition on one
   XR, never as a default flip.
4. The change is tagged and the pin is bumped per cluster, dev first. A tag is the unit of policy:
   "every cluster at v0.3.121 or later refuses X" is a checkable statement.

The parts of this page that say "convention" are the backlog. They are listed so that a reader never
mistakes a documented rule for an enforced one.
