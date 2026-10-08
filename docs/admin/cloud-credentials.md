# Cloud credentials: four identities, what each one can reach

Two clouds, two jobs each. **Airframe** (Crossplane, this catalog) builds and tears down the
infrastructure a cloud deploy needs: the `AwsLambdaTarget`, `AwsEcsTarget` and `AzureContainerAppTarget`
compositions in [cloud-targets.md](../user/cloud-targets.md). **Glidepath** (the pipelines) ships images
into it. Each job runs as its own identity with its own key, its own permissions and its own blast
radius, and the two are never shared:

| | Airframe: the Crossplane provider identity | Glidepath: the deployer identity |
|---|---|---|
| **Who holds it** | The AWS or Azure provider pods in `crossplane-system`, through the provider's `ClusterProviderConfig` | Every pipeline TaskRun of one application, in that app's `app-<app>-cicd` namespace |
| **What it may do** | Create, observe and delete the resources the three compositions describe: repositories, execution roles, functions and URLs, clusters, task definitions, services, a small VPC; resource groups, environments, container apps | Push an image and roll the deploy surface that image belongs to: `UpdateFunctionCode`, a new task-definition revision plus `UpdateService`, `az containerapp update` |
| **What it must never do** | Deploy code: no `UpdateFunctionCode`, no `UpdateFunctionConfiguration`, no `ecs:UpdateService`. Grant itself more: only the two managed policies the compositions attach, only on `*-exec` roles. Leave its region. | Create or delete anything. Change a function's role, memory or configuration. Touch IAM beyond passing an `*-ecs-exec` role to ECS. Leave its region. |
| **Why the split** | A composition bug or a wrong management policy can only create, observe or delete; it can never roll a function back to the placeholder | Anyone who can merge to the app's repository can run code in its pipeline namespace; that trust boundary must not reach infrastructure or IAM |
| **Where the secret lives** | Infisical project `platform-cicd-kind-dev`, environment `shared`, path `/`, keys `provider-aws-creds` and `provider-azure-creds` | The app's own Infisical project `<app>-<devCluster>` (for example `smoke-fn-kind-dev`), environment `shared`, keys `aws-access-key-id` + `aws-secret-access-key` or `azure-client-id` + `azure-client-secret` + `azure-tenant-id` |
| **How it reaches the cluster** | `platform-secret-store` (ClusterSecretStore) → ExternalSecret `provider-aws-creds` / `provider-azure-creds` → Secret of the same name, key `credentials`, in `crossplane-system` → `ClusterProviderConfig default` | The app's own ClusterSecretStore → the `app-secrets` ExternalSecret that `airframe-application` renders from the app's `cicd.yaml` `secrets:` list → Secret `app-secrets` in `app-<app>-cicd` |
| **Who can read the Kubernetes Secret** | Cluster admins, Argo CD's application controller, External Secrets, the provider pods. No tenant namespace, not Tower's read identity | Cluster admins, Argo CD, External Secrets, and every pod that runs in that app's cicd namespace: the deploy TaskRuns and, for a Lambda target, the composition's bootstrap Job |

The names below (`hangar-crossplane`, `glidepath-deployer`) are conventions: the cluster only
cares about the Infisical keys and the Secret names in the last two rows. Keep the names anyway; the
cloud's audit log (CloudTrail, the Azure Activity Log) is the only place the two jobs are told apart.

Both identities are long-lived access keys today. [Hardening](#hardening-next) says what replaces them.

## AWS: `hangar-crossplane` (Crossplane)

**Created by:** an account administrator, once per AWS account (IAM user `hangar-crossplane`, policy
`HangarCrossplaneCloudTargets`).
**Used by:** `provider-aws-iam`, `provider-aws-ecr`, `provider-aws-lambda`, `provider-aws-ecs`,
`provider-aws-ec2` on the dev cluster, through `ClusterProviderConfig default`
(`aws.m.upbound.io/v1beta1`, in `gitops-cluster-dev/10-crds-operators/crossplane/provider-aws-config.yaml`).

### What it does, per target

| Target | Creates and deletes | Observes |
|---|---|---|
| `AwsLambdaTarget` | ECR repository (force-deleted with its images), IAM role `<functionName>-exec` + attachment of `AWSLambdaBasicExecutionRole`, Lambda function (container image), Function URL + the public `lambda:InvokeFunctionUrl` permission | the same |
| `AwsEcsTarget` | IAM role `<app>-<env>-ecs-exec` + attachment of `AmazonECSTaskExecutionRolePolicy` + inline `logs:CreateLogGroup`; ECS cluster, task definition, Fargate service; with `network.mode: create`, a VPC, one public subnet, internet gateway, route table + default route + association, a security group with one ingress and one egress rule | the same |

Nothing in either composition updates a function, a task definition or a service in place
(their `managementPolicies` omit `Update`), so the policy omits every update call on purpose.

### The policy

The region is a hard boundary: ECR and Lambda through the resource ARN, ECS and EC2 through
`aws:RequestedRegion`. IAM is global, so it is bounded by the role-name pattern instead.

```bash
export AWS_PAGER=""
REGION=us-east-1
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)

cat > hangar-crossplane-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ExecutionRoles",
      "Effect": "Allow",
      "Action": [
        "iam:CreateRole", "iam:DeleteRole", "iam:GetRole", "iam:UpdateRole",
        "iam:UpdateRoleDescription", "iam:UpdateAssumeRolePolicy",
        "iam:TagRole", "iam:UntagRole", "iam:ListRoleTags",
        "iam:PutRolePolicy", "iam:GetRolePolicy", "iam:DeleteRolePolicy", "iam:ListRolePolicies",
        "iam:ListAttachedRolePolicies", "iam:ListInstanceProfilesForRole"
      ],
      "Resource": "arn:aws:iam::${ACCOUNT}:role/*-exec"
    },
    {
      "Sid": "AttachOnlyTheTwoManagedPolicies",
      "Effect": "Allow",
      "Action": ["iam:AttachRolePolicy", "iam:DetachRolePolicy"],
      "Resource": "arn:aws:iam::${ACCOUNT}:role/*-exec",
      "Condition": {
        "ArnEquals": {
          "iam:PolicyARN": [
            "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
            "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
          ]
        }
      }
    },
    {
      "Sid": "PassExecutionRolesToLambdaAndEcs",
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": "arn:aws:iam::${ACCOUNT}:role/*-exec",
      "Condition": {
        "StringEquals": {
          "iam:PassedToService": ["lambda.amazonaws.com", "ecs-tasks.amazonaws.com"]
        }
      }
    },
    {
      "Sid": "EcrRepositories",
      "Effect": "Allow",
      "Action": [
        "ecr:CreateRepository", "ecr:DeleteRepository", "ecr:DescribeRepositories",
        "ecr:PutImageTagMutability", "ecr:PutImageScanningConfiguration",
        "ecr:ListTagsForResource", "ecr:TagResource", "ecr:UntagResource",
        "ecr:GetRepositoryPolicy", "ecr:SetRepositoryPolicy",
        "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"
      ],
      "Resource": "arn:aws:ecr:${REGION}:${ACCOUNT}:repository/*"
    },
    {
      "Sid": "LambdaFunctionsNoCodeOrConfigUpdates",
      "Effect": "Allow",
      "Action": [
        "lambda:CreateFunction", "lambda:DeleteFunction",
        "lambda:Get*", "lambda:List*",
        "lambda:AddPermission", "lambda:RemovePermission",
        "lambda:CreateFunctionUrlConfig", "lambda:UpdateFunctionUrlConfig", "lambda:DeleteFunctionUrlConfig",
        "lambda:TagResource", "lambda:UntagResource"
      ],
      "Resource": "arn:aws:lambda:${REGION}:${ACCOUNT}:function:*"
    },
    {
      "Sid": "EcsClustersServicesTaskDefinitions",
      "Effect": "Allow",
      "Action": [
        "ecs:CreateCluster", "ecs:DeleteCluster", "ecs:DescribeClusters",
        "ecs:RegisterTaskDefinition", "ecs:DescribeTaskDefinition",
        "ecs:DeregisterTaskDefinition", "ecs:DeleteTaskDefinitions",
        "ecs:CreateService", "ecs:DescribeServices", "ecs:DeleteService",
        "ecs:ListTagsForResource", "ecs:TagResource", "ecs:UntagResource"
      ],
      "Resource": "*",
      "Condition": { "StringEquals": { "aws:RequestedRegion": "${REGION}" } }
    },
    {
      "Sid": "EcsTargetNetwork",
      "Effect": "Allow",
      "Action": [
        "ec2:CreateVpc", "ec2:DeleteVpc", "ec2:DescribeVpcs", "ec2:ModifyVpcAttribute", "ec2:DescribeVpcAttribute",
        "ec2:CreateSubnet", "ec2:DeleteSubnet", "ec2:DescribeSubnets", "ec2:ModifySubnetAttribute",
        "ec2:CreateInternetGateway", "ec2:DeleteInternetGateway", "ec2:DescribeInternetGateways",
        "ec2:AttachInternetGateway", "ec2:DetachInternetGateway",
        "ec2:CreateRouteTable", "ec2:DeleteRouteTable", "ec2:DescribeRouteTables",
        "ec2:CreateRoute", "ec2:DeleteRoute", "ec2:ReplaceRoute",
        "ec2:AssociateRouteTable", "ec2:DisassociateRouteTable", "ec2:ReplaceRouteTableAssociation",
        "ec2:CreateSecurityGroup", "ec2:DeleteSecurityGroup", "ec2:DescribeSecurityGroups", "ec2:DescribeSecurityGroupRules",
        "ec2:AuthorizeSecurityGroupIngress", "ec2:RevokeSecurityGroupIngress",
        "ec2:AuthorizeSecurityGroupEgress", "ec2:RevokeSecurityGroupEgress",
        "ec2:CreateTags", "ec2:DeleteTags", "ec2:DescribeTags",
        "ec2:DescribeAvailabilityZones", "ec2:DescribeNetworkAcls", "ec2:DescribeNetworkInterfaces",
        "ec2:DescribeAccountAttributes"
      ],
      "Resource": "*",
      "Condition": { "StringEquals": { "aws:RequestedRegion": "${REGION}" } }
    }
  ]
}
EOF

# catches a mistyped action, a literal "${REGION}" or a malformed ARN before an identity ever runs with it
aws accessanalyzer validate-policy --policy-type IDENTITY_POLICY \
  --policy-document file://hangar-crossplane-policy.json      # expect: "findings": []

aws iam create-policy \
  --policy-name HangarCrossplaneCloudTargets \
  --description "Crossplane provider-aws on the Hangar dev cluster: what AwsLambdaTarget and AwsEcsTarget compose, one region, no Lambda code or config updates" \
  --policy-document file://hangar-crossplane-policy.json

aws iam create-user --user-name hangar-crossplane \
  --tags Key=hangar.io/component,Value=hangar-crossplane

aws iam attach-user-policy --user-name hangar-crossplane \
  --policy-arn "arn:aws:iam::${ACCOUNT}:policy/HangarCrossplaneCloudTargets"

aws iam create-access-key --user-name hangar-crossplane --output json
```

To change the policy of an identity that already exists (a tightened or corrected document), publish a
new default version instead of recreating anything; the key keeps working:

```bash
aws iam create-policy-version --set-as-default \
  --policy-arn "arn:aws:iam::${ACCOUNT}:policy/HangarCrossplaneCloudTargets" \
  --policy-document file://hangar-crossplane-policy.json
# IAM keeps five versions; delete an old one with `aws iam delete-policy-version --version-id vN` when it refuses
```

Lines that look wider than the compositions need, and why they are there:

| Grant | Reason |
|---|---|
| `ecr:BatchGetImage`, `ecr:GetDownloadUrlForLayer` | `CreateFunction` validates the container image with the caller's permissions, not the execution role's. |
| `ecr:GetRepositoryPolicy`, `ecr:SetRepositoryPolicy` | Lambda itself pulls the image later, as `lambda.amazonaws.com`. For a same-account repository with no policy, Lambda adds the retrieval statement to the repository policy at `CreateFunction`, which it can only do if the caller holds these two. |
| `lambda:Get*`, `lambda:List*` | The provider's observe step reads the function, its code-signing config, its policy, its URL config and its tags; read-only. |
| `ec2:RevokeSecurityGroupEgress` | The provider revokes AWS's default allow-all egress rule on every security group it creates; the composition then adds its own explicit egress rule. |
| `ec2:DescribeNetworkAcls`, `ec2:DescribeRouteTables` | The provider's observe of a VPC looks up the default network ACL and main route table ids. |
| `iam:ListInstanceProfilesForRole` | The provider checks for instance profiles before deleting a role. |

Deliberately absent: `lambda:UpdateFunctionCode`, `lambda:UpdateFunctionConfiguration`,
`lambda:PublishVersion`, `ecs:UpdateService` (the service is composed with `forceDelete: true`, so
deletion never has to scale it to zero), `iam:CreatePolicy`, any `iam:*` on a role that does not end in
`-exec`, any ECR push call, `sts:AssumeRole`, anything outside the region.

### The secret

The Upbound provider reads an AWS shared-credentials file, so the Infisical secret is this multi-line
value, built from the two fields of the last command above:

```
[default]
aws_access_key_id = AKIA...
aws_secret_access_key = ...
```

Plant it as `provider-aws-creds` in the `platform-cicd-kind-dev` project, `shared` environment, root
path: the project `platform-secret-store` reads. Multi-line values are fine. The ExternalSecret in
`gitops-cluster-dev/10-crds-operators/crossplane/provider-aws-creds-external-secret.yaml` maps the whole
value to the `credentials` key of Secret `provider-aws-creds` in `crossplane-system`, refreshed hourly.

### Confirming it

```bash
# don't wait for the hourly refresh
kubectl annotate externalsecret provider-aws-creds -n crossplane-system force-sync=$(date +%s) --overwrite
kubectl get externalsecret provider-aws-creds -n crossplane-system        # STATUS SecretSynced, READY True
kubectl get secret provider-aws-creds -n crossplane-system -o jsonpath='{.data.credentials}' | base64 -d | grep -c aws_access_key_id
```

Then the real test is a target: [cloud-targets.md](../user/cloud-targets.md#requesting-one). The Argo CD
`crossplane-packages` Application goes from Degraded to Healthy once both credential ExternalSecrets
sync. If the policy is too tight, the provider says exactly what it was refused, on the managed
resource:

```bash
kubectl describe repository.ecr.aws.m.upbound.io -n app-<app>-cicd <xr>-repo | grep -A2 'Synced'
# ... AccessDenied ... User: arn:aws:iam::...:user/hangar-crossplane is not authorized to perform: ecr:Something on resource: ...
```

## AWS: `glidepath-deployer` (Glidepath)

**Created by:** an account administrator, once per AWS account (IAM user `glidepath-deployer`, policy
`GlidepathDeployer`).
**Used by:** Glidepath's `deploy-lambda` and `deploy-ecs` Tasks, and the `AwsLambdaTarget` bootstrap
Job, all in the app's `app-<app>-cicd` namespace, reading `aws-access-key-id` and
`aws-secret-access-key` from the `app-secrets` Secret. The Crossplane identity never pushes an image;
the deployer never creates infrastructure.

### What it does

| Step | Calls |
|---|---|
| `deploy-lambda`: log in to ECR, copy the built image into the function's repository, update the function | `ecr:GetAuthorizationToken`; the layer upload calls and `ecr:PutImage`; `lambda:GetFunction`, `lambda:UpdateFunctionCode`, then `lambda:GetFunctionConfiguration` until the update lands |
| `deploy-ecs`: read the current task definition, register a revision with the new image, point the service at it | `ecs:DescribeTaskDefinition`, `ecs:RegisterTaskDefinition` (+ `ecs:TagResource` for the tags it carries over, `iam:PassRole` for the execution role it names), `ecs:UpdateService`, then `ecs:DescribeServices` until stable |
| `AwsLambdaTarget` bootstrap Job: seed the new repository with the public Lambda base image so the function can be created | `ecr:GetAuthorizationToken` and the same push calls |

### The policy

```bash
export AWS_PAGER=""
REGION=us-east-1
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)

cat > glidepath-deployer-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EcrLogin",
      "Effect": "Allow",
      "Action": "ecr:GetAuthorizationToken",
      "Resource": "*"
    },
    {
      "Sid": "EcrPushAndReadFunctionImages",
      "Effect": "Allow",
      "Action": [
        "ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer",
        "ecr:DescribeImages", "ecr:DescribeRepositories", "ecr:GetRepositoryPolicy",
        "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:PutImage"
      ],
      "Resource": "arn:aws:ecr:${REGION}:${ACCOUNT}:repository/*"
    },
    {
      "Sid": "LambdaUpdateCode",
      "Effect": "Allow",
      "Action": ["lambda:GetFunction", "lambda:GetFunctionConfiguration", "lambda:UpdateFunctionCode"],
      "Resource": "arn:aws:lambda:${REGION}:${ACCOUNT}:function:*"
    },
    {
      "Sid": "EcsTaskDefinitions",
      "Effect": "Allow",
      "Action": ["ecs:DescribeTaskDefinition", "ecs:RegisterTaskDefinition", "ecs:TagResource"],
      "Resource": "*"
    },
    {
      "Sid": "EcsUpdateService",
      "Effect": "Allow",
      "Action": ["ecs:DescribeServices", "ecs:UpdateService"],
      "Resource": "arn:aws:ecs:${REGION}:${ACCOUNT}:service/*/*"
    },
    {
      "Sid": "PassEcsExecutionRoles",
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": "arn:aws:iam::${ACCOUNT}:role/*-ecs-exec",
      "Condition": { "StringEquals": { "iam:PassedToService": "ecs-tasks.amazonaws.com" } }
    }
  ]
}
EOF

aws accessanalyzer validate-policy --policy-type IDENTITY_POLICY --policy-document file://glidepath-deployer-policy.json
aws iam create-policy --policy-name GlidepathDeployer \
  --description "Glidepath deploy steps: push to ECR, UpdateFunctionCode, new ECS task-definition revision + UpdateService; one region; nothing created or deleted" \
  --policy-document file://glidepath-deployer-policy.json
aws iam create-user --user-name glidepath-deployer --tags Key=hangar.io/component,Value=glidepath-deployer
aws iam attach-user-policy --user-name glidepath-deployer --policy-arn "arn:aws:iam::${ACCOUNT}:policy/GlidepathDeployer"
aws iam create-access-key --user-name glidepath-deployer --output json
```

`ecr:BatchGetImage` and `ecr:GetDownloadUrlForLayer` are here for the same reason as above:
`UpdateFunctionCode` validates the image as the caller. `ecs:RegisterTaskDefinition` cannot be
narrowed by ARN (a new revision has no ARN yet) and `ecs:DescribeTaskDefinition` takes `*` as well.

### The secret

Two keys in the app's own Infisical project (`<app>-<devCluster>`, `shared` environment), named exactly
as the app's `cicd.yaml` `secrets:` list names them: `aws-access-key-id` and `aws-secret-access-key`.
`airframe-application` renders the `app-secrets` ExternalSecret from that list; Glidepath documents the
mechanism in its `docs/admin/app-secrets.md`. One access key can serve several apps' projects; the
policy is the same for all of them, and nothing in it is per-app. Keep per-app keys if the audit log
needs to say which app's pipeline pushed.

### The exposure, spelled out

Whoever can run a pipeline in `app-<app>-cicd` can read this key: that is every person who can merge
to the app's repository, plus cluster admins and Argo CD. With it they can push any image to any
repository in the region and roll any function or service in the region to it, including other apps'.
They cannot create a repository, a function or a role, delete anything, change a function's memory,
timeout or role, or read any other secret. That ceiling is what makes the key safe to hand to a
pipeline; widening it is a security-team decision ([governance.md](governance.md#5-identity-who-acts)).

## Azure: `hangar-crossplane` (Crossplane)

**Created by:** a subscription owner, once per subscription. The Azure CLI needs an interactive login
for this tenant (security defaults), so these run on a workstation, not from a pipeline.
**Used by:** `provider-family-azure` and `provider-azure-containerapp` through `ClusterProviderConfig
default` (`azure.m.upbound.io/v1beta1`, `provider-azure-config.yaml` in the same directory).

### What it does

An `AzureContainerAppTarget` creates and later deletes a resource group named by the request (default
`<appName>-rg`), a Container Apps environment in it and one Container App with external ingress; with
`registry` set, the app's registry secret as well. Deleting the group is what makes the target
disposable, so the identity needs delete on the group and on everything the composition puts in it,
and nothing else.

### The role and the service principal

A custom role at subscription scope, because resource groups are created at that scope. Everything
inside the group is `Microsoft.App`. `listSecrets` is included because the provider reads the app's
secrets back on every observe; the deployer below does not get it.

```bash
SUB=$(az account show --query id -o tsv)

cat > hangar-crossplane-role.json <<EOF
{
  "Name": "Hangar Crossplane Cloud Targets",
  "Description": "Crossplane provider-azure on the Hangar dev cluster: resource groups, Container Apps environments and apps that AzureContainerAppTarget composes",
  "Actions": [
    "Microsoft.Resources/subscriptions/resourceGroups/read",
    "Microsoft.Resources/subscriptions/resourceGroups/write",
    "Microsoft.Resources/subscriptions/resourceGroups/delete",
    "Microsoft.App/managedEnvironments/*",
    "Microsoft.App/containerApps/*",
    "Microsoft.App/locations/*/read"
  ],
  "NotActions": [],
  "AssignableScopes": ["/subscriptions/${SUB}"]
}
EOF

az role definition create --role-definition @hangar-crossplane-role.json

az ad sp create-for-rbac --name hangar-crossplane \
  --role "Hangar Crossplane Cloud Targets" --scopes "/subscriptions/${SUB}" --output json
# -> appId (clientId), password (clientSecret), tenant (tenantId)
```

The subscription must have the `Microsoft.App` resource provider registered (`az provider register
--namespace Microsoft.App`, once, by an owner); a subscription that already runs a Container App has it.

### The secret

The provider reads a JSON document with these four fields (the shape `az ad sp create-for-rbac
--sdk-auth` used to print; assemble it by hand, the flag is deprecated):

```json
{
  "clientId": "<appId>",
  "clientSecret": "<password>",
  "tenantId": "<tenant>",
  "subscriptionId": "<SUB>"
}
```

Plant it as `provider-azure-creds` in `platform-cicd-kind-dev` (`shared`, `/`). It reaches
`crossplane-system` as Secret `provider-azure-creds`, key `credentials`, through
`provider-azure-creds-external-secret.yaml`; confirm it the same way as the AWS secret, with the Azure
names.

## Azure: `glidepath-deployer` (Glidepath)

**Used by:** Glidepath's `deploy-azure-container-apps` Task, which logs in with
`az login --service-principal` and runs `az containerapp update --image`, `az containerapp show` and
`az containerapp revision show` until the new revision is `Running`.

A custom role scoped to the resource group that holds the app (one assignment per target resource
group; `hangar` for the existing smoke app):

```bash
SUB=$(az account show --query id -o tsv)
RG=hangar

cat > glidepath-container-app-deployer-role.json <<EOF
{
  "Name": "Glidepath Container App Deployer",
  "Description": "Glidepath deploy step: update a Container App's image and watch the revision; no create, delete or secret reads",
  "Actions": [
    "Microsoft.App/containerApps/read",
    "Microsoft.App/containerApps/write",
    "Microsoft.App/containerApps/revisions/read",
    "Microsoft.App/locations/*/read"
  ],
  "NotActions": [],
  "AssignableScopes": ["/subscriptions/${SUB}"]
}
EOF

az role definition create --role-definition @glidepath-container-app-deployer-role.json

az ad sp create-for-rbac --name glidepath-deployer \
  --role "Glidepath Container App Deployer" \
  --scopes "/subscriptions/${SUB}/resourceGroups/${RG}" --output json
```

If a deploy fails on `Microsoft.App/containerApps/listSecrets/action`, the CLI version in the Task
needed to read secrets to build its update; add that one action rather than switching to the built-in
`Container Apps Contributor`, which also grants create and delete. The built-in role is the acceptable
shortcut only for a throwaway subscription.

Plant `azure-client-id`, `azure-client-secret` and `azure-tenant-id` in the app's own Infisical project,
as its `cicd.yaml` `secrets:` list names them. The exposure is the AWS deployer's, narrowed further: the
key can change the image of Container Apps in one resource group and nothing else.

## Rotation

Both platform identities: create the new key, replace the Infisical value, force the ExternalSecret
(the `annotate` above), confirm the provider still reconciles (`kubectl get managed -A` shows every
resource `SYNCED True`), then delete the old key in the cloud. The provider pods read the Secret on each
reconcile; no restart. The deployer: replace the value in each app project that carries it, run one
deploy, delete the old key.

`aws iam create-access-key` refuses a third key per user, so rotation is always new-then-delete-old.

## Hardening next

- **No long-lived keys.** Both Upbound providers accept federated identity (`credentials.source:
  WebIdentity` / IRSA on AWS, Workload Identity on Azure) from a cluster with a public OIDC issuer. A
  kind cluster has none; publishing its discovery document (an S3 bucket is enough) removes every key in
  this document for the Crossplane identity. Glidepath's TaskRuns can use the same projected
  ServiceAccount tokens.
- **Region as an organisation rule, not a policy line:** a service control policy or Azure Policy
  denying every region but the one in use, so a wider policy written in a hurry cannot cross it.
- **Attribution:** CloudTrail and the Activity Log already split the two identities. Alerting on the
  Crossplane identity calling anything outside the policy above, or on the deployer being used outside
  a pipeline's source IP range, is the cheap detective control.
- **Per-app deployer keys** if the audit log must name the app, and `ecr` resource ARNs narrowed to
  `repository/<functionName>` per app if two apps must not be able to push to each other.
