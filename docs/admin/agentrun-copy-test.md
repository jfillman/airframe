# AgentRun copy-test on hangar-dev (AP-A3 live test plan)

The first live use of AgentRun: a person runs this on the dev cluster after the merges below. Nothing in it is
automated, and every step says what you should see. Stop at the first step whose output differs, and report it.

Every command names `--context hangar-dev`. Never run any of it against hangar-prod.

```shell
export K="kubectl --context hangar-dev"
export PROVIDER=system:serviceaccount:crossplane-system:provider-kubernetes
export CLEARANCE=system:serviceaccount:platform-system:clearance
export CROSSPLANE=system:serviceaccount:crossplane-system:crossplane
```

## 0. Before you start

1. Merged, in this order: airframe `ap-a3-agentrun`, apron `ap-a3-agentrun`, gitops-hangar-dev#45 (the
   `autopilotReady` flag) and the gitops-hangar-dev `ap-a3-agentrun` PR, then autopilot `ap-a3-agentrun-pointer`.
2. The ghcr.io package `function-agentrun` is **public** (GitHub, Packages, function-agentrun, Package settings).
   A new package is private, and Crossplane's pull then fails `UNAUTHORIZED`.
3. The `cluster-registry` Application synced by hand (it has no automated sync; that sync is the attestation).
4. A local airframe checkout at the merged commit: `git -C ~/tech/airframe fetch && git -C ~/tech/airframe log -1 origin/main`.

## 1. Install checks

```shell
$K -n argocd get applications agent-sandbox autopilot-agentrun-grants crossplane-packages cluster-registry \
  -o custom-columns=NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status
```
Expect all four `Synced` and `Healthy`.

```shell
$K -n agent-sandbox-system get deploy agent-sandbox-controller \
  -o jsonpath='{.status.readyReplicas}/{.spec.replicas} {.spec.template.spec.containers[0].image}{"\n"}'
$K get crd sandboxes.agents.x-k8s.io -o jsonpath='{.status.conditions[?(@.type=="Established")].status}{"\n"}'
$K get ns agent-sandbox-system -o jsonpath='{.metadata.labels.pod-security\.kubernetes\.io/enforce}{"\n"}'
```
Expect `1/1 registry.k8s.io/agent-sandbox/agent-sandbox-controller:v1.0.8@sha256:e1d96312487eba7d8f001e848a9d4e644b7deea8c2a4564ccc318abb729be731`,
then `True`, then `restricted`.

provider-kubernetes on its stable service account, and the old grants still working:
```shell
$K -n crossplane-system get deploy -l pkg.crossplane.io/provider=provider-kubernetes \
  -o jsonpath='{.items[0].spec.template.spec.serviceAccountName} {.items[0].status.readyReplicas}{"\n"}'
$K get clusterrolebinding -o json | python3 -c 'import json,sys
for b in json.load(sys.stdin)["items"]:
    for s in b.get("subjects") or []:
        if s.get("name","").startswith("provider-kubernetes"): print(b["metadata"]["name"], s["name"])'
$K get objects.kubernetes.m.crossplane.io -A -o json | python3 -c 'import json,sys
items = json.load(sys.stdin)["items"]
bad = [o["metadata"]["name"] for o in items if any(c["type"] in ("Synced", "Ready") and c["status"] != "True"
       for c in o.get("status", {}).get("conditions", []))]
print(len(items), "objects;", "not Synced/Ready:", bad or "none")'
```
Expect `provider-kubernetes 1`; the bindings `crossplane:provider:provider-kubernetes-<hash>:system`,
`provider-kubernetes-applied-resources` and `hangar-agentrun-objects`, each with subject `provider-kubernetes` (no
`provider-kubernetes-f6665ef36536` left); and `27 objects; not Synced/Ready: none` (the ClusterSecretStores and Secrets that exist today). If any
Object went `Synced=False` after the provider restarted, stop: the binding change broke an existing grant.

function-agentrun, and the registry flag:
```shell
$K get functions.pkg.crossplane.io function-agentrun -o jsonpath='{.status.conditions[?(@.type=="Healthy")].status} {.spec.package}{"\n"}'
$K -n crossplane-system get deploy -l pkg.crossplane.io/function=function-agentrun \
  -o jsonpath='{.items[0].spec.template.spec.containers[0].env}{"\n"}'
$K -n crossplane-system get cm hangar-dev -o jsonpath='{.data.type} {.data.autopilotReady}{"\n"}'
```
Expect `True ghcr.io/jfillman/function-agentrun@sha256:cf9f288c45b4722fd7e94ecc565e884234e4719d6c55b48c9ff36fb6fbb51935`,
`[{"name":"HANGAR_CLUSTER_NAME","value":"hangar-dev"}]`, and `dev true`.

The policy, the role and Clearance's role:
```shell
$K get validatingadmissionpolicy,validatingadmissionpolicybinding autopilot-agentrun-provider-confinement autopilot-agentrun-object-origin
$K auth can-i create namespaces --as=$PROVIDER                    # yes
$K auth can-i create sandboxes.agents.x-k8s.io -n default --as=$PROVIDER   # yes (RBAC; the policy is what refuses it, step 2)
$K auth can-i create jobs -n default --as=$PROVIDER               # no
$K auth can-i create pods -n default --as=$PROVIDER               # no
$K auth can-i create agentruns.catalog.hangar.io -n autopilot-runs --as=$CLEARANCE   # yes
$K auth can-i patch agentruns.catalog.hangar.io -n autopilot-runs --as=$CLEARANCE    # yes
$K auth can-i create agentruns.catalog.hangar.io -n default --as=$CLEARANCE          # no
$K auth can-i create sandboxes.agents.x-k8s.io -n autopilot-runs --as=$CLEARANCE     # no
```
(`agentruns` answers `no` with a warning until step 3 installs the XRD; re-run those three after step 3.)

## 2. The policy refuses what D15 forbids

Server-side dry runs as the provider's service account (admission runs; nothing is stored).

```shell
$K create job vap-probe --image=busybox -n default --dry-run=server --as=$PROVIDER
```
Expect `Error from server (Forbidden): jobs.batch is forbidden: User "system:serviceaccount:crossplane-system:provider-kubernetes" cannot create resource "jobs" in API group "batch" in the namespace "default"`.

```shell
cat <<'EOF' | $K create -f - --dry-run=server --as=$PROVIDER
apiVersion: agents.x-k8s.io/v1beta1
kind: Sandbox
metadata: {name: vap-probe, namespace: default}
spec:
  podTemplate:
    spec:
      serviceAccountName: run
      automountServiceAccountToken: false
      containers: [{name: c, image: busybox}]
EOF
```
Expect `... ValidatingAdmissionPolicy 'autopilot-agentrun-provider-confinement' with binding 'autopilot-agentrun-provider-confinement' denied request: provider-kubernetes may manage sandboxes only as or inside Autopilot run namespaces (agent-r-*), not default`.

```shell
$K label ns kube-system vap-probe=1 --dry-run=server --as=$PROVIDER
$K label ns kube-system pod-security.kubernetes.io/enforce- --dry-run=server --as=$PROVIDER
$K create ns agent-r-0b0b0b --dry-run=server --as=$PROVIDER
```
Expect each refused by the same policy: `... namespaces only as or inside Autopilot run namespaces (agent-r-*), not kube-system`
(twice), then a refusal of `agent-r-0b0b0b` naming `hangar.io/agent-run` (the right name, but not a run namespace). The pod-security change on a
live run namespace is in step 4.

### 2b. Only Crossplane, for an AgentRun, may make a run-kind Object

`autopilot-agentrun-object-origin` covers the other side: who may create a provider-kubernetes `Object` whose
manifest is a run kind. A helper prints one (a run Namespace, with Crossplane's owner reference to an AgentRun unless
told otherwise):
```shell
obj() { # obj NAME [owner|none] [Namespace|Secret]  -> an Object on stdout
  local owner='ownerReferences: [{apiVersion: catalog.hangar.io/v1alpha1, kind: AgentRun, name: r-0b0b0b, uid: 00000000-0000-0000-0000-000000000000, controller: true}]'
  [ "${2:-owner}" = none ] && owner=''
  local m='{apiVersion: v1, kind: Namespace, metadata: {name: agent-r-0b0b0b}}'
  [ "${3:-}" = Secret ] && m='{apiVersion: v1, kind: Secret, metadata: {name: vap-probe, namespace: default}}'
  printf '%s\n' "apiVersion: kubernetes.m.crossplane.io/v1alpha1" "kind: Object" "metadata:" "  name: $1" \
    "  namespace: autopilot-runs" "  labels: {crossplane.io/composite: r-0b0b0b}" "  $owner" "spec:" \
    "  forProvider: {manifest: $m}" "  providerConfigRef: {kind: ClusterProviderConfig, name: default}"
}
obj vap-admin | $K create -f - --dry-run=server
obj vap-xp-noowner none | $K create -f - --dry-run=server --as=$CROSSPLANE
obj vap-xp | $K create -f - --dry-run=server --as=$CROSSPLANE
obj vap-secret none Secret | $K create -f - --dry-run=server
obj vap-clearance | $K create -f - --dry-run=server --as=$CLEARANCE
```
Expect, in order:
1. You (cluster admin) are refused: `... ValidatingAdmissionPolicy 'autopilot-agentrun-object-origin' ... denied request: only Crossplane core may create or change a provider-kubernetes Object whose manifest is a run kind ...`.
2. Crossplane's identity without the AgentRun owner reference is refused: `... must belong to an AgentRun: in autopilot-runs, with a controller ownerReference ...`.
3. With the owner reference it is admitted: `object.kubernetes.m.crossplane.io/vap-xp created (server dry run)`.
4. A Secret manifest (SecretStore's shape) is admitted for you, untouched by the policy: `... vap-secret created (server dry run)`.
5. Clearance is refused by RBAC before the policy: `... cannot create resource "objects" in API group "kubernetes.m.crossplane.io" ...`.

None of the replies may say `resulted in error` or `fails to evaluate` (a CEL error in this fail-closed policy would
refuse every run-kind Object). The existing Objects are never in scope: they stay as step 1 left them
(`27 objects; not Synced/Ready: none`), and Crossplane has logged no refusal from this policy:
```shell
$K -n crossplane-system logs deploy/crossplane --since=1h | grep -c autopilot-agentrun-object-origin
```
Expect `0`.

## 3. Install the copy

The XRD and a second Composition under another name, applied by hand (not in `airframe-service-catalog` yet):
```shell
git -C ~/tech/airframe show origin/main:xrds/agentrun.yaml | $K apply -f -
$K wait xrd agentruns.catalog.hangar.io --for=condition=Established --timeout=120s
git -C ~/tech/airframe show origin/main:compositions/agentrun/composition.yaml \
  | sed 's/^  name: agentruns.catalog.hangar.io$/  name: agentruns-copy.catalog.hangar.io/' | $K apply -f -
$K get composition agentruns-copy.catalog.hangar.io -o jsonpath='{.spec.pipeline[0].functionRef.name}{"\n"}'
```
Expect `condition met` and `function-agentrun`. Re-run the three Clearance `can-i` checks from step 1 (yes, yes, no).

## 4. A run reaches Running, under pod security restricted

The test agent is `registry.k8s.io/pause:3.10` by digest (it runs until signalled, as UID 65535), in network mode
`clearance`, the mode the canary tests.
```shell
export PAUSE=registry.k8s.io/pause@sha256:ee6521f290b2168b6e0935a181d4cff9be1ac3f505666ef0e3c98fae8199917a
run() { # run NAME MINUTES [extra spec yaml lines]
  local exp; exp=$(date -u -v+"$2"M +%Y-%m-%dT%H:%M:%SZ)
  cat <<EOF | $K apply -f -
apiVersion: catalog.hangar.io/v1alpha1
kind: AgentRun
metadata: {name: $1, namespace: autopilot-runs}
spec:
  crossplane: {compositionRef: {name: ${COMP:-agentruns-copy.catalog.hangar.io}}}
  agent: copy-test
  image: $PAUSE
  sandbox: ${SANDBOX:-standard}
  compute: small
  network: {mode: clearance}
  expiresAt: "$exp"
  taskId: t-${1#r-}
  sessionId: s-${1#r-}
  limits: {toolCalls: 1, githubCalls: 0, modelTokens: 0}
$3
EOF
  echo "expiresAt $exp"
}
run r-c0de01 10
$K -n autopilot-runs get agentrun r-c0de01 -w
```
Expect `PHASE` `Provisioning` then `Running` (`RUN` `AgentRunRunning`) within about a minute (the image pull is the
wait). Then:
```shell
$K get ns agent-r-c0de01 --show-labels
$K -n agent-r-c0de01 get sandbox,pod,sa,resourcequota,networkpolicy
$K -n agent-r-c0de01 get sandbox agent -o jsonpath='{.spec.shutdownTime} {.spec.shutdownPolicy} {.status.conditions[?(@.type=="Ready")].status}{"\n"}'
$K -n agent-r-c0de01 get pod agent -o jsonpath='{.spec.serviceAccountName} {.spec.automountServiceAccountToken} {.spec.activeDeadlineSeconds} {.spec.containers[0].securityContext.runAsNonRoot}{"\n"}'
tools/airframe-verify agentrun autopilot-runs/r-c0de01 --context hangar-dev
```
Expect: labels include `hangar.io/agent-run=true`, `pod-security.kubernetes.io/enforce=restricted`, and **no**
`hangar.io/ephemeral-env`; one Sandbox `agent`, pod `agent` `1/1 Running`, ServiceAccount `run`, ResourceQuota `run`,
NetworkPolicies `default-deny` and `allow-egress`; `<expiresAt> Delete True`; `run false <about 600> true` (activeDeadlineSeconds is the TTL counted from the XR's
creation, a few seconds under 600); airframe-verify
passes `xr-run-ready`, `phase-live`, `run-namespace`, `sandbox-ready`, `default-deny` and reports `egress-enforced` as
manual.

Pod security is enforced in the run namespace (a privileged pod is refused):
```shell
$K -n agent-r-c0de01 run psa-probe --image=busybox --dry-run=server --overrides='{"spec":{"serviceAccountName":"run"}}'
```
Expect `Error from server (Forbidden): pods "psa-probe" is forbidden: violates PodSecurity "restricted:latest": ...`
(if the quota answers first instead, `must specify limits`; either way nothing is admitted).

The policy refuses a pod-security change on this live run namespace, and the PR-sweep label:
```shell
$K label ns agent-r-c0de01 pod-security.kubernetes.io/enforce=privileged --overwrite --dry-run=server --as=$PROVIDER
$K label ns agent-r-c0de01 hangar.io/ephemeral-env=true --dry-run=server --as=$PROVIDER
```
Expect `... provider-kubernetes may not add, change or remove pod-security.kubernetes.io/* labels on a namespace` and
`... provider-kubernetes may never set hangar.io/ephemeral-env ...`.

## 5. The NetworkPolicies are the canary's

The run's live policies equal what the canary renders with the same `compose()` for the same mode:
```shell
cd ~/tech/autopilot && python3 - <<'EOF'
import json, subprocess, sys
from datetime import datetime, timezone
sys.path.insert(0, "tools")
import netpol_canary as nc
want = {d["metadata"]["name"]: d["spec"] for d in nc.render_run("r-c0de01", "clearance", "autopilot-system", datetime.now(timezone.utc))
        if d["kind"] == "NetworkPolicy"}
live = json.loads(subprocess.check_output(["kubectl", "--context", "hangar-dev", "get", "netpol", "-n", "agent-r-c0de01", "-o", "json"]))
got = {i["metadata"]["name"]: i["spec"] for i in live["items"]}
print("MATCH" if want == got else json.dumps({"want": want, "got": got}, indent=1))
EOF
python3 tools/netpol_canary.py --context hangar-dev
```
Expect `MATCH`, then the canary's `16/16` and exit 0 (it renders through the vendored compose() now, with the new
quota; this re-attests the flag on the new code).

## 6. Expiry with Clearance absent

Clearance is not deployed, so every run in this plan already proves this. Watch r-c0de01's deadline:
```shell
EXP=$($K -n autopilot-runs get agentrun r-c0de01 -o jsonpath='{.spec.expiresAt}'); echo "deadline $EXP"
while true; do printf '%s  ' "$(date -u +%H:%M:%S)"; $K -n agent-r-c0de01 get pod agent --no-headers 2>&1 | head -1; sleep 1; done
```
Expect `Running` until the deadline, then `Terminating` or `NotFound` within about 2 s of it (pause exits on
SIGTERM). Ctrl-C, then:
```shell
$K -n agent-r-c0de01 get events --sort-by=.lastTimestamp | tail -5
$K -n autopilot-runs get agentrun r-c0de01 -w            # PHASE Expired within ~60-90 s of the deadline
$K get ns agent-r-c0de01                                  # NotFound shortly after
```
You may see one or more short-lived `Sandbox agent` objects re-created after the deadline (provider-kubernetes
re-applies its Object until the function stops rendering it) and deleted again at once, with no pod: that is the
churn the function README describes. A pod that starts after the deadline is a failure.

## 7. Expiry with the function pod deleted mid-run

```shell
run r-c0de02 6
$K -n autopilot-runs get agentrun r-c0de02 -w     # wait for Running, then Ctrl-C
EXP=$($K -n autopilot-runs get agentrun r-c0de02 -o jsonpath='{.spec.expiresAt}'); echo "deadline $EXP"
# keep function-agentrun down from now until 90 s past the deadline
END=$(( $(date -j -u -f %Y-%m-%dT%H:%M:%SZ "$EXP" +%s) + 90 ))
while [ "$(date -u +%s)" -lt "$END" ]; do
  $K -n crossplane-system delete pod -l pkg.crossplane.io/function=function-agentrun --wait=false >/dev/null 2>&1
  printf '%s  ' "$(date -u +%H:%M:%S)"; $K -n agent-r-c0de02 get pod agent --no-headers 2>&1 | head -1
  sleep 2
done
```
Expect the agent pod `Running` until the deadline and gone (`Terminating`/`NotFound`) within about 2 s of it, while
the function has no ready pod. During the loop `$K -n autopilot-runs get agentrun r-c0de02` still says `Running` (its
status is stale, `SYNCED` may go `False` with a function connection error) and `agent-r-c0de02` still exists: the
namespace waits for the function. After the loop, within about 90 s: `PHASE Expired`, and the namespace is deleted.

## 8. Rejected cases (nothing is created)

Hardened sandbox on a cluster with no runtime class, and an input over 4 KiB:
```shell
SANDBOX=hardened run r-bad001 10
run r-bad002 10 "  input: {blob: \"$(head -c 5000 /dev/zero | tr '\0' x)\"}"
```
No autopilotReady, through a scratch registry: two more copies of the Composition that read the registry from a
scratch namespace, one with a record lacking the flag and one with no record at all.
```shell
$K create ns autopilot-scratch-registry
$K -n autopilot-scratch-registry create configmap hangar-dev --from-literal=type=dev --from-literal=cicdReady=true
for c in noflag:autopilot-scratch-registry norecord:autopilot-scratch-empty; do
  git -C ~/tech/airframe show origin/main:compositions/agentrun/composition.yaml | python3 -c "
import sys, yaml; d = yaml.safe_load(sys.stdin)
d['metadata']['name'] = 'agentruns-${c%%:*}.catalog.hangar.io'
d['spec']['pipeline'][0]['input']['registry_namespace'] = '${c#*:}'
print(yaml.safe_dump(d))" | $K apply -f -
done
COMP=agentruns-noflag.catalog.hangar.io run r-bad003 10
COMP=agentruns-norecord.catalog.hangar.io run r-bad004 10
sleep 60
$K -n autopilot-runs get agentrun r-bad001 r-bad002 r-bad003 r-bad004 \
  -o custom-columns=NAME:.metadata.name,PHASE:.status.phase,REASON:.status.reason
for n in bad001 bad002 bad003 bad004; do $K get ns agent-r-$n 2>&1 | tail -1; done
```
Expect all four `Rejected` with reasons `hardened sandbox requested but this cluster has no runtime class for it`,
`input is larger than 4 KiB; pass a reference instead`, `cluster 'hangar-dev' is not autopilotReady: ...` and
`no cluster registry record named 'hangar-dev': ...`; and four `NotFound` namespaces. The XRD itself refuses some
requests before the function sees them; check one:
```shell
cat <<'EOF' | $K apply -f - --dry-run=server
apiVersion: catalog.hangar.io/v1alpha1
kind: AgentRun
metadata: {name: my-run, namespace: autopilot-runs}
spec: {agent: copy-test, image: "busybox:latest", sandbox: standard, compute: small, network: {mode: allowlist, allowCidrs: ["0.0.0.0/0"]},
       expiresAt: "2099-01-01T00:00:00Z", taskId: t-0c0c0c, sessionId: s-0c0c0c, limits: {toolCalls: 1, githubCalls: 0, modelTokens: 0}}
EOF
$K -n autopilot-runs patch agentrun r-bad001 --type=merge -p '{"spec":{"expiresAt":"2099-01-01T00:00:00Z"}}'
```
Expect the dry run refused (the name rule, the image pattern and the `/0` pattern) and the patch refused with
`expiresAt can't change after creation: a run's deadline is never extended`.

## 9. Cleanup

```shell
$K -n autopilot-runs delete agentrun --all --wait=true
$K delete composition agentruns-copy.catalog.hangar.io agentruns-noflag.catalog.hangar.io agentruns-norecord.catalog.hangar.io
$K delete xrd agentruns.catalog.hangar.io
$K delete ns autopilot-scratch-registry
$K get ns | grep '^agent-r-' ; $K get sandboxes -A
```
Expect no `agent-r-*` namespaces and `No resources found`. The installed pieces (agent-sandbox, the grants, the
policy, function-agentrun) stay: they are GitOps-managed. Adding the XRD and Composition to `airframe-service-catalog`
is the next change, once this plan passed; record the run in the PR that does it.

## What this plan does not cover

- The kubelet backstop with the agent-sandbox controller also down (`activeDeadlineSeconds`): Argo CD self-heal
  restores the controller, so it needs the `agent-sandbox` Application's auto-sync paused first.
- A real agent image, Clearance (AP-A2) and the model proxy: the run reaches Clearance's address, but nothing answers.
- Signed-image admission for agent images (design section 3): not built; the image is only pinned by digest.
