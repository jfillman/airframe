# function-agentrun

Crossplane composition function (Python) for Autopilot's `AgentRun` XRD (AP-A3, decision D2): the sole pipeline
step of [`compositions/agentrun`](../../compositions/agentrun/composition.yaml), schema
[`xrds/agentrun.yaml`](../../xrds/agentrun.yaml), contract [`xrds/agentrun.meta.yaml`](../../xrds/agentrun.meta.yaml).

An `AgentRun` is one bounded, disposable run of an agent. Clearance creates it through the Kubernetes API in
`autopilot-runs`; this function turns it into provider-kubernetes `Object`s (a namespaced XR cannot compose the
cluster-scoped run Namespace directly):

| Object | What it is |
|---|---|
| `namespace` | `agent-<name>`, pod security `restricted`, labelled `hangar.io/agent-run=true`, **never** `hangar.io/ephemeral-env` (the PR-namespace sweep would reap it) |
| `quota` | one Sandbox, no Secrets, Services, Jobs or PVCs; CPU and memory for the agent plus its sidecars |
| `netpol-default-deny` | ingress and egress denied |
| `netpol-egress` | the network mode's exceptions: DNS + Clearance, + the model proxy, + allowlisted CIDRs (none for `none`, and none while frozen) |
| `serviceaccount` | `run`, no token automount |
| `sandbox` | a [kubernetes-sigs/agent-sandbox](https://github.com/kubernetes-sigs/agent-sandbox) `Sandbox` (`agents.x-k8s.io/v1beta1`) running the agent pod |

All logic is the pure `compose(xr, observed, now, cfg)` in [`function/compose.py`](function/compose.py);
[`function/fn.py`](function/fn.py) is the gRPC wrapper (registry lookup, observed state, readiness, the `RunReady`
condition).

## Expiry: three independent clocks

1. **The Sandbox.** `spec.shutdownTime = spec.expiresAt`, `shutdownPolicy: Delete`. The agent-sandbox controller
   deletes the pod (and then the Sandbox) at that instant; measured within about a second on the dev cluster (U11).
   Nothing in Hangar has to be alive for this.
2. **The kubelet.** The pod template's `activeDeadlineSeconds` is `expiresAt - creationTimestamp`, so if the
   agent-sandbox controller is down the kubelet still ends the pod (late by at most the pod's scheduling delay).
   Anchored to the XR's creation, so the template is byte-identical on every reconcile.
3. **The function.** Past `expiresAt` it renders nothing, and Crossplane deletes every Object, the namespace with
   them. Crossplane re-runs the function about every 60 s whatever the response TTL says (U2: realtime compositions
   are off), so this is cleanup and status refresh, not the deadline.

With the function pod down, (1) and (2) still end the run; the namespace waits until the function is back.

**Known churn after expiry.** Between the controller deleting the Sandbox and the function's next run (up to about a
minute), provider-kubernetes still holds the Sandbox Object and re-creates the Sandbox. The controller sees a
shutdownTime in the past before it creates any pod (`Reconcile` checks expiry first) and deletes it again, so no pod
starts; you may see a few short-lived Sandbox objects and `Sandbox has expired` events. `shutdownPolicy: Retain` would
avoid that (the controller deletes the pod but keeps the object) at the cost of the Sandbox outliving its deadline
until the function's cleanup; D15/U11 chose Delete.

## Failing closed

`Rejected`, nothing rendered, never downgraded, for: no `HANGAR_CLUSTER_NAME`; no registry record for it; a record
that is not `type: dev` or lacks `autopilotReady: "true"`; an XR not named `r-<hex>` or not in `autopilot-runs`; a TTL
over `max_ttl_minutes`; `hardened` with no runtime class; a compute class the input lacks; an allowlist that is empty,
`/0`, loopback or link-local; `allowCidrs` outside allowlist mode; an input over 4 KiB.

`Expired`, `Drained` and `Rejected` are **final**: read back from the XR's status, they never render again. (After a
drain the Sandbox is gone; without this the next reconcile would look like a run that had not started yet and run the
agent a second time.)

## Which cluster am I on?

The Composition is shared by every cluster, so the cluster name comes from the Function's DeploymentRuntimeConfig
(`HANGAR_CLUSTER_NAME`, apron `templates/10-crds-operators/crossplane/function-agentrun-runtime.yaml`). The function
asks Crossplane for ConfigMap `crossplane-system/<name>` (the cluster registry every Airframe composition's gate reads)
and admits a run only if it says `type: dev` and `autopilotReady: "true"`. Every cluster carries every cluster's
record, so a gate that looked for "any record with the flag" would pass on the upper cluster too; the name is what
makes it this cluster's answer.

## Shared grant (decision D15)

provider-kubernetes needs a ClusterRole for these kinds (namespaces, resourcequotas, serviceaccounts,
networkpolicies, sandboxes), and it lands on the provider's one shared service account, so it covers every
provider-kubernetes Object, not only this function's. The cluster repo's `55-autopilot/agentrun-grants/` ships it only
together with a ValidatingAdmissionPolicy that confines the provider's requests for those kinds to `agent-r-*`
namespaces carrying `hangar.io/agent-run=true`, forbids pod-security label changes and the PR-sweep label, and admits
only `serviceAccountName: run` Sandboxes (tested against a real kube-apiserver in apron `tests/policy/`).

The policy keys on the provider's identity only, because a provider request carries nothing that says which Object
asked for it. What remains is: anyone who can create a provider-kubernetes Object can get a run-shaped namespace and
Sandbox made. Today that is Crossplane itself (only the SecretStore and AgentRun compositions render Objects, with
fixed kinds) and Crossplane admins (`crossplane-admin`/`crossplane-edit`, which the provider's aggregated roles join).
A run-shaped namespace gives a pod the identity `system:serviceaccount:agent-r-<id>:run`, which Clearance will treat
as a run principal once AP-A4 maps it. The Object-specific lever, not shipped here, is a second policy on
`objects.kubernetes.m.crossplane.io` admitting an Object whose manifest is one of these kinds only from
`system:serviceaccount:crossplane-system:crossplane` and only with an `AgentRun` owner reference.

## Tests

```shell
cd functions/function-agentrun
python3 -m unittest tests.test_compose tests.test_fn          # CI: the compositions job
HANGAR_CLUSTER_NAME=example-dev python3 -m function.main --insecure --address 127.0.0.1:9445 &
cd ../.. && python3 tools/test_compositions.py --renderer render-pipeline agentrun   # 13 golden render cases
```

[`hack/xrd-cel/`](hack/xrd-cel/README.md) checks the XRD's CEL rules on a real kube-apiserver (not in CI).

## Build and push

The dev cluster is arm64 and the upper cluster amd64, so build both, exactly as
[function-dex's README](../function-dex/README.md#build-and-push) explains (Apple `container` CLI, `skopeo` to
docker-archive, one `.xpkg` per arch, one multi-arch `crossplane xpkg push`; no Docker or podman):

```shell
TAG=0.1.0-dev.$(git rev-parse --short HEAD)
for arch in arm64 amd64; do
  container build --arch $arch -t function-agentrun-$arch .
  container image save function-agentrun-$arch:latest -o /tmp/function-agentrun-$arch.tar
  skopeo copy --override-arch $arch --override-os linux \
    oci-archive:/tmp/function-agentrun-$arch.tar \
    docker-archive:/tmp/function-agentrun-$arch-docker.tar:ghcr.io/jfillman/function-agentrun:$TAG
  crossplane xpkg build --package-root=package \
    --embed-runtime-image-tarball=/tmp/function-agentrun-$arch-docker.tar \
    --package-file=/tmp/function-agentrun-$arch.xpkg
done
crossplane xpkg push --package-files=/tmp/function-agentrun-amd64.xpkg,/tmp/function-agentrun-arm64.xpkg \
  ghcr.io/jfillman/function-agentrun:$TAG
```

A new ghcr.io package is private: make it public once in the GitHub UI, or Crossplane's pull fails `UNAUTHORIZED`.
Pin the Function by tag **and** digest in the cluster repo.
