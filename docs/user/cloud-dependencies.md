# Cloud dependencies: queues, object storage and managed PostgreSQL

Three kinds give an app a managed cloud service. You request them the way you request a
[cloud target](cloud-targets.md), and delete them the same way:

| Kind | AWS | Azure | What you get |
|---|---|---|---|
| `MessageQueue` | Amazon SQS queue + dead-letter queue | Service Bus (Basic) namespace + queue | A durable queue; on AWS it can trigger a Lambda target |
| `ObjectStorage` | S3 bucket | Storage Account + blob container | Private, encrypted object storage |
| `ManagedPostgreSQL` | RDS for PostgreSQL in its own VPC | Flexible Server | One PostgreSQL database, TLS only, reachable only from the networks you list |

`spec.cloud` (`aws`, the default, or `azure`) picks the implementation and can't change later. Every other
field means the same thing on both clouds, and the XRD says where one doesn't apply.

**Status.** AWS has been verified live (see [What was verified](#what-was-verified)). The Azure
compositions are render-tested and schema-checked against the provider CRDs, but they have never run
against a real subscription, and the dev cluster doesn't have the Azure providers for them installed yet
([Azure](#azure)).

## Guardrails you get without asking

- **Private by default, with no way to turn it off.** An S3 bucket has Block Public Access on in all four
  settings and BucketOwnerEnforced ownership (no ACLs). An Azure account allows no public blobs. A database
  admits no network until you list one in `allowedCidrs`.
- **Encrypted at rest.** SQS-owned keys, SSE-S3, RDS storage encryption. Azure always encrypts.
- **TLS only.** RDS for PostgreSQL 16 and 17 sets `rds.force_ssl` by default. Azure Flexible Server requires
  secure transport. Storage accepts HTTPS with TLS 1.2 or later only.
- **No access keys on AWS.** A Lambda consumer gets an inline IAM policy on its own execution role, scoped to
  that one queue or bucket. Every role the compositions touch carries the `HangarCloudTargetBoundary`
  permissions boundary, so no grant can exceed it.
- **Data isn't deleted by accident.** An S3 bucket that still holds objects isn't deleted unless
  `emptyOnDelete: true`. An Azure `ObjectStorage` must say `emptyOnDelete: true` to be accepted at all,
  because Azure always deletes an account together with its contents. `ManagedPostgreSQL` takes
  `protect: true` (AWS only), which turns on deletion protection and a final snapshot.

## Request one

Put the manifest in `tenants/<app>/xr-requests/` of the dev cluster's tenants repo, in namespace
`app-<app>-cicd` (or `infra-<app>-cicd`). Like cloud targets, these are not `components:` entries: the chart
renders components on every environment's own cluster, and only the dev cluster has the cloud providers.

```yaml
apiVersion: catalog.hangar.io/v1alpha1
kind: MessageQueue
metadata:
  name: orders
  namespace: app-orders-api-cicd
spec:
  lockSeconds: 60             # at least the function's timeout when it is a trigger
  consumers:
    - awsLambdaTarget: orders-worker   # an AwsLambdaTarget in the same namespace
      access: receive
      trigger: true                    # the queue invokes the function
---
apiVersion: catalog.hangar.io/v1alpha1
kind: ObjectStorage
metadata:
  name: orders-exports
  namespace: app-orders-api-cicd
spec:
  bucketName: orders-exports-700017004810   # S3 names are global; add something unique
  consumers:
    - awsLambdaTarget: orders-worker
      access: readWrite
---
apiVersion: catalog.hangar.io/v1alpha1
kind: ManagedPostgreSQL
metadata:
  name: orders-db
  namespace: app-orders-api-cicd
spec:
  size: small                 # db.t4g.micro / B_Standard_B1ms
  allowedCidrs:
    - 203.0.113.0/24
```

Wait for `DependencyReady`. Its reason is a closed set, documented in each kind's `xrds/<kind>.meta.yaml`:

```bash
kubectl -n app-orders-api-cicd get messagequeue,objectstorage,managedpostgresql
tools/airframe-verify managedpostgresql app-orders-api-cicd/orders-db --context <dev-cluster>
```

A queue or bucket is ready in under a minute. A new database takes 5 to 15 minutes.

## What an app reads

Each XR writes the same two objects into its own namespace:

- **ConfigMap `<name>-connection`**: everything that isn't secret. For a queue, `queueName` and `endpoint`
  (the queue URL, or `sb://<namespace>.servicebus.windows.net/`), plus `queueArn`, `region` and
  `deadLetterQueueUrl` on AWS. For storage, `bucketName` and `endpoint`, plus `bucketArn` or
  `storageAccount`. For a database, `host`, `port`, `database`, `username` and `sslmode`.
- **Secret `<name>-credentials`**, written by the cloud provider, not by the composition. For a database,
  `password` (generated, never in Git). For an Azure queue or account, `attribute.primary_connection_string`.
  AWS queues and buckets have no Secret: access is the consumer's IAM role.

The XR's `status` repeats the non-secret values (`status.url`, `status.arn`, `status.host`, ...).

## Consumers and triggers (AWS)

`consumers[]` names `AwsLambdaTarget` XRs in the same namespace. For each one, the composition writes an
inline policy named `hangar-queue-<namespace>-<name>` or `hangar-storage-<namespace>-<name>` onto the
target's execution role (`<functionName>-exec`):

| Kind | `access` | Actions on this queue or bucket only |
|---|---|---|
| MessageQueue | `send` | `SendMessage` |
| | `receive` | `ReceiveMessage`, `DeleteMessage`, `ChangeMessageVisibility` |
| | `sendReceive` (default) | both |
| ObjectStorage | `read` | `ListBucket`, `GetBucketLocation`, `GetObject` |
| | `readWrite` (default) | also `PutObject`, `DeleteObject`, multipart uploads |

(Every queue grant also includes `GetQueueAttributes` and `GetQueueUrl`.)

With `trigger: true`, a Lambda event source mapping makes the queue invoke the function with batches of up
to `batchSize` messages. A message the handler fails on is delivered again after `lockSeconds`, and after
`deadLetter.maxReceiveCount` failed deliveries it moves to `<queueName>-dlq`. Removing a consumer removes its
grant and trigger. A consumer that names no target, or a target in another region, gets nothing, and
`DependencyReady` says `MessageQueueConsumerUnresolved` or `ObjectStorageConsumerUnresolved`.

ECS services are not consumers yet: `AwsEcsTarget` has no task role for the app's own code, only the
execution role ECS itself uses. A Kubernetes app reads `<name>-connection` today but has no cloud identity to
use a queue or bucket with.

## Managed PostgreSQL networking

The server has a public endpoint that admits only `allowedCidrs` on 5432. On AWS, that means a VPC of its own
(`vpcCidr`, default `10.43.0.0/16`), two public subnets in two availability zones, and one security group rule
per CIDR. On Azure, it means one firewall rule per CIDR (a CIDR becomes its first-to-last address range).

A Lambda function outside a VPC has no fixed source address, so reaching a database from one means listing
`0.0.0.0/0`. The password and TLS are then the only protection. That is a deliberate trade for now. Private
networking, with the function inside the database's VPC, is not built.

The admin user `hangar_admin` owns the database. There is no separate application role yet.

**Cost.** A small RDS instance is about $13 a month plus storage (32 GiB of gp3 is about $3), and an Azure
B1ms is about the same. You pay while the XR exists. Queues and buckets cost next to nothing at test volumes.

## Deleting

Delete the manifest from the tenants repo. Everything the XR created goes with it:

- Queues are deleted with their messages.
- A bucket is deleted only if it's empty or `emptyOnDelete: true`. Otherwise the XR waits, and the bucket's
  `Synced` condition says why.
- Azure deletes the resource group and everything in it.
- A database with `protect: false` (the default) is deleted with no final snapshot. With `protect: true`, the
  deletion fails until you set it back to `false`.

The database password Secret is created by the provider, not composed, so it survives. Delete it by hand.

## Azure

The Azure compositions need three providers that the dev cluster doesn't run yet:
`provider-azure-servicebus`, `provider-azure-storage` and `provider-azure-dbforpostgresql` (v2.8.0). Their
kinds also need to be listed in the cluster's ManagedResourceActivationPolicy. The commented block in
gitops-<dev-cluster> `10-crds-operators/crossplane/providers.yaml` has both. Install them once an Azure
identity exists ([cloud-credentials.md](../admin/cloud-credentials.md)). Each provider pod costs about 250 MB.

The Azure queue and account connection strings are shared keys. Managed identities for Azure consumers are
not modelled yet.

## What was verified

Offline (CI): every composition branch is render-tested (`example/cases.yaml`), and every rendered managed
resource was checked against its provider's CRD schema with unknown fields rejected.

Live: not yet. The AWS run needs the IAM policy additions in
[cloud-credentials.md](../admin/cloud-credentials.md#cloud-dependencies-2026-10-24) published first.
