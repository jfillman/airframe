# Cloud targets: stand up what a cloud deploy needs, on demand

Glidepath's three cloud deploy targets (`deploy.target: aws-lambda`, `aws-ecs` and
`azure-container-apps`) only ever *update* something that already exists: a Lambda function's image,
an ECS service's task definition, a Container App's image. Until 2026-10-08 the function, the
service and the app had to be made by hand before the first deploy. Three catalog XRDs now stand that
minimum infrastructure up, and tear it down, on request:

| XRD | Stands up | For |
|---|---|---|
| `AwsLambdaTarget` | ECR repository, execution role, the function (image-packaged, seeded with a public Lambda base image), a public Function URL | a `LambdaFunction` app |
| `AwsEcsTarget` | execution role, ECR repository and deploy role, a small dedicated public network (or your own), ECS cluster, task definition, Fargate service with a public IP | any app with `deploy.target: aws-ecs` |
| `AzureContainerAppTarget` | resource group, Container Apps environment, the app with public ingress (seeded with the Azure Functions base image) | an `AzureFunction` app, or any app deploying to Container Apps |

They are **stand-alone and disposable**: create the XR to get the infrastructure, delete it to remove
all of it (repositories with their images, the resource group with everything in it). Nothing an app
XR owns is touched either way. That is the shape for a smoke app you only want to pay for while it is
being tested.

## Prerequisites (once per cluster)

- The AWS and Azure providers on the dev cluster (`gitops-cluster-dev/10-crds-operators/crossplane/providers.yaml`).
- Credentials for them: the `hangar-crossplane` identity in each cloud. On AWS it's an IAM role that the
  providers assume with the cluster's own ServiceAccount tokens (web identity federation), so nothing is
  planted. On Azure it's still a secret, `provider-azure-creds` in the `platform-cicd-<dev-cluster>` Infisical
  project (what the `platform-secret-store` reads).
  [docs/admin/cloud-credentials.md](../admin/cloud-credentials.md) has the policies, the trust, the secret
  format and the checks, and explains why that identity is not the one Glidepath deploys with. Without
  them, every target reports `TargetReady: False`, with the provider's own credentials error on its managed
  resources.
- For a Lambda target, **web identity**: the cluster registry must carry the AWS account, the permissions
  boundary and the cluster's `serviceAccountIssuer`. The target then creates `glidepath-deploy-<functionName>`,
  an IAM role trusted only by the ServiceAccount `glidepath-cloud-deployer` in the app's `-cicd` namespace and
  allowed only this repository and this function's code. The bootstrap Job that pushes the placeholder image
  assumes it, and so does Glidepath's deploy step. The ServiceAccount comes from the app's Glidepath chart; the
  Job's pod can't start until it exists. No AWS key is stored anywhere. On a cluster without those three
  registry fields the target creates the repository and the execution role, then stops with
  `TargetReady: AwsLambdaTargetNeedsWebIdentity`. (Until v0.3.147 the Job could use an access key from
  `spec.credentialsSecret` instead; that mode is gone, because Glidepath can't deploy to a function bootstrapped
  that way.)
- For an ECS target, the same **web identity**: the target creates an ECR repository named after the service
  (`<appName>-<env>`) and `glidepath-deploy-ecs-<appName>-<env>`, a role trusted only by `glidepath-cloud-deployer`
  in the app's `-cicd` namespace and allowed only to push to that repository, register task definitions, update
  that one service and pass its execution role to ECS. Glidepath's `deploy-ecs` copies each build from `ghcr.io`
  into the repository (so a private package deploys) and assumes the role; no AWS key is stored. Without the three
  registry fields the infrastructure is still created, but `TargetReady` stops at
  `AwsEcsTargetNeedsWebIdentity` and nothing can deploy.

## What a target never does

Once a target has created its function (or service), the function stays for as long as the XR exists. Deleting
the bootstrap Job to retry it, or a change in how credentials are set up, never removes it: the composition only
decides when to create things, and keeps everything that already exists (v0.3.144, after the 2026-10-16 incident in
[cloud-credentials.md](../admin/cloud-credentials.md#a-rule-for-composition-authors-never-gate-what-already-exists)).
Deleting the XR is the only way to remove the function, its URL and its roles.

## Requesting one

Commit the XR into the app's own `tenants/<app>/xr-requests/` in the dev cluster's tenants repo, next
to the app's other requests, so it lands in `app-<app>-cicd` (whose `glidepath-cloud-deployer` ServiceAccount the deploy role trusts):

```yaml
apiVersion: catalog.hangar.io/v1alpha1
kind: AwsLambdaTarget
metadata:
  name: smoke-fn
  namespace: app-smoke-fn-cicd
spec:
  functionName: glidepath-smoke-fn   # = deploy.lambda.functionName in the app's cicd.yaml
  region: us-east-1
  architecture: arm64                # = the LambdaFunction app's spec.architecture
  runtime: nodejs22
```

```yaml
apiVersion: catalog.hangar.io/v1alpha1
kind: AwsEcsTarget
metadata:
  name: smoke-ecs
  namespace: app-smoke-ecs-cicd
spec:
  appName: smoke-ecs                 # cluster, service and family smoke-ecs-dev; container smoke-ecs
  env: dev
  containerPort: 8080
```

**One target per environment.** For a second environment, request a second `AwsEcsTarget` with the same
`appName` and another `env`, e.g. `env: prod`: it gets its own cluster and service (`smoke-ecs-prod`), network, ECR
repository and deploy role (`glidepath-deploy-ecs-smoke-ecs-prod`), so dev and prod share nothing in AWS. Then add the
environment to `cicd.yaml` with the block from the new target's `status.cicd`, typically as `tier: flight` so it is
deployed only through a release pin PR. (Until 2026-10-17 the cluster was named `<appName>` and a second target
would have claimed the first one's cluster; a target created before then keeps its cluster's name.)

```yaml
apiVersion: catalog.hangar.io/v1alpha1
kind: AzureContainerAppTarget
metadata:
  name: smoke-az-fn
  namespace: app-smoke-az-fn-cicd
spec:
  appName: smoke-az-fn               # = deploy.azureContainerApps.appName
  resourceGroup: smoke-az-fn-rg      # created and owned by this XR
  location: eastus
```

Then watch the XR: `TargetReady` goes `True` with a reason from a closed set (each
`xrds/<kind>.meta.yaml` lists them with their meaning), and the XR's status carries everything the
app's `cicd.yaml` needs, including the deploy block as text. `tools/airframe-verify awslambdatarget
app-smoke-fn-cicd/smoke-fn` checks the condition, the function (read-only `aws lambda get-function`) and its URL:

```
$ kubectl get awslambdatarget smoke-fn -n app-smoke-fn-cicd -o jsonpath='{.status.cicd}'
deploy:
  target: aws-lambda
  lambda:
    functionName: glidepath-smoke-fn
    region: us-east-1
```

Paste that into the app's `cicd.yaml` (the scaffolded `LambdaFunction`/`AzureFunction` apps already
carry a matching block), push, and the next pipeline run deploys the real image over the placeholder.
`status.functionUrl` (Lambda) and `status.url` (Container Apps) are what to curl afterwards; an ECS
task's public IP comes from `aws ecs describe-tasks` for `status.cluster`/`status.service`.

Delete the XR when done. Every target composes its deploy surface (the function, the service and
task definition, the Container App) **without** the Update management policy, so Glidepath's deploys
are never reverted to the placeholder; deletion still removes them.

## Letting the app own it instead

`LambdaFunction` and `AzureFunction` can compose the matching target themselves: set
`spec.target.enabled: true` on the app XR and it composes an `AwsLambdaTarget` /
`AzureContainerAppTarget` child named `<app>-target` from its own `functionName`/`region`/
`architecture`/`runtime` (or `appName`/`resourceGroup`), the same values it scaffolds into
`cicd.yaml`, and proxies the child's `TargetReady` onto itself. The infrastructure then lives as
long as the app. For Azure that means the app's `resourceGroup` is created and owned by the child,
so it must not be a group that exists for anything else.

The container apps (`GoApplication`, `NodejsApplication`, `PythonApplication`, `SpringBootApplication`) choose
where they deploy when they are created: `spec.deployTarget: aws-ecs` (default `kubernetes`), set once and
immutable. With `aws-ecs` the app composes an `AwsEcsTarget` for dev named `<app>-dev` (`spec.ecs.region`,
`spec.ecs.architecture`, its own `port`) and scaffolds a `cicd.yaml` whose `dev` environment already deploys there,
building only that architecture. There is no Kubernetes dev environment to remove first. More environments are more
`AwsEcsTarget`s, as above.

## The policy baked into a target

A target is where the platform's cloud policy is enforced, not where it is chosen. What a request
gets, whatever fields it sets:

- **Identity.** The Lambda execution role carries only `AWSLambdaBasicExecutionRole`; the ECS execution
  role only `AmazonECSTaskExecutionRolePolicy` plus `logs:CreateLogGroup`. Everything is created with the
  platform's own cloud credential from the provider's `ClusterProviderConfig`; the XR never holds one.
- **Exposure.** An ECS security group opens exactly `containerPort` inbound and everything outbound; a Lambda Function URL and its public
  invoke permission exist only while `functionUrl` is true; a Container App's ingress is external on the
  one target port.
- **Provenance.** Placeholder images come from `public.ecr.aws/lambda/*` and `mcr.microsoft.com/azure-functions/*`
  only; nothing but Glidepath deploys a built image.
- **Ownership.** The function, the task definition and service and the Container App are composed
  without the Update policy, so the pipeline's deploys are never reverted. Every cloud resource carries
  `hangar.io/target`, `hangar.io/component`, `hangar.io/app` and `hangar.io/env` tags on AWS; on Azure the same
  tags are `hangar-target`, `hangar-component` and `hangar-app`, because Azure forbids `/` in a tag name.
- **Disposability.** The ECR repository is force-deleted with its images and the Azure resource group is
  created and owned, so deleting the XR removes everything. That is the policy for a smoke target; a
  persistent target is the same composition with those two settings flipped.

Changing any of these is a change to the XRD or the composition, reviewed and released as a catalog
version, never a field on one request: [docs/admin/governance.md](../admin/governance.md) says who owns
which decision and how such a change ships.

## What a target does not do

- No load balancer in front of an ECS service, no custom domain on a Container App, no Log
  Analytics workspace, no VPC for Lambda: minimum infrastructure, by design. Each is a small
  addition to the composition if a real workload needs it.
- No multi-environment targets: one XR is one function, one service or one app. Two environments
  are two XRs with different names (and, for Lambda, two function names).
- No image push beyond the placeholder: Glidepath's pipeline is the only thing that deploys.

## Checking the compositions offline

`tools/render-pipeline` renders any composition in this repo through the real
`function-go-templating` and `function-auto-ready` without a cluster or Docker; each target's
`example/` directory has the XR and the observed-state fixtures for every lifecycle stage. See the
tool's header for how to start the two functions.
