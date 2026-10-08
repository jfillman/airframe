# Cloud targets: stand up what a cloud deploy needs, on demand

Glidepath's three cloud deploy targets (`deploy.target: aws-lambda`, `aws-ecs` and
`azure-container-apps`) only ever *update* something that already exists: a Lambda function's image,
an ECS service's task definition, a Container App's image. Until 2026-10-08 the function, the
service and the app had to be made by hand before the first deploy. Three catalog XRDs now stand that
minimum infrastructure up, and tear it down, on request:

| XRD | Stands up | For |
|---|---|---|
| `AwsLambdaTarget` | ECR repository, execution role, the function (image-packaged, seeded with a public Lambda base image), a public Function URL | a `LambdaFunction` app |
| `AwsEcsTarget` | execution role, a small dedicated public network (or your own), ECS cluster, task definition, Fargate service with a public IP | any app with `deploy.target: aws-ecs` |
| `AzureContainerAppTarget` | resource group, Container Apps environment, the app with public ingress (seeded with the Azure Functions base image) | an `AzureFunction` app, or any app deploying to Container Apps |

They are **stand-alone and disposable**: create the XR to get the infrastructure, delete it to remove
all of it (repositories with their images, the resource group with everything in it). Nothing an app
XR owns is touched either way. That is the shape for a smoke app you only want to pay for while it is
being tested.

## Prerequisites (once per cluster)

- The AWS and Azure providers on the dev cluster (`gitops-cluster-dev/10-crds-operators/crossplane/providers.yaml`).
- Credentials for them, as two secrets in the `platform-cicd-kind-dev` Infisical project (what the
  `platform-secret-store` reads): `provider-aws-creds`, an AWS credentials file
  (`[default]\naws_access_key_id = ...\naws_secret_access_key = ...`) for an identity allowed to
  manage ECR, IAM roles, Lambda, ECS and EC2 networking; and `provider-azure-creds`, a JSON document
  `{"clientId":"...","clientSecret":"...","subscriptionId":"...","tenantId":"..."}` for a service
  principal with Contributor on the subscription. Until they exist the ExternalSecrets in that
  directory stay unsynced and every target reports `TargetReady: False` with the provider's own
  "cannot get credentials" error on its managed resources.
- For a Lambda target, the app's own `aws-access-key-id` / `aws-secret-access-key` secrets (the ones
  Glidepath's deploy step already needs), planted in the app's Infisical project: the target's
  bootstrap Job pushes the placeholder image with them. Its pod waits, Pending, until the
  `app-secrets` Secret exists.

## Requesting one

Commit the XR into the app's own `tenants/<app>/xr-requests/` in the dev cluster's tenants repo, next
to the app's other requests, so it lands in `app-<app>-cicd` (where `app-secrets` lives):

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
  appName: smoke-ecs                 # cluster smoke-ecs, service and family smoke-ecs-dev, container smoke-ecs
  env: dev
  containerPort: 8080
```

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
app's `cicd.yaml` needs, including the deploy block as text:

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
so it must not be a group that exists for anything else. ECS has no app XRD, so an `AwsEcsTarget`
is always stand-alone.

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
