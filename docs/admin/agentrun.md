# AgentRun: Autopilot's sandboxed agent runs

`AgentRun` (`catalog.hangar.io/v1alpha1`, namespaced) is one bounded, disposable run of an Autopilot agent. Clearance,
Autopilot's tool gateway, creates it through the Kubernetes API in `autopilot-runs`; nothing else is meant to. It is
the one Airframe kind that is not requested from git, because a run lives for minutes and no person reviews it
(Autopilot design, "Durable writes are commits; ephemeral runs are direct requests").

**Status: built, not installed.** The XRD, the composition and function-agentrun are in this repo with unit and
render tests. They are not in any cluster's `airframe-service-catalog` include list: the first live use is a copy-test
on the dev cluster (a second Composition, one scratch XR pointing at it).

## What a run gets

| | |
|---|---|
| Its own namespace | `agent-<name>`, pod security `restricted`, default-deny NetworkPolicy, a quota with room for one Sandbox and no Secrets, Services, Jobs or PVCs |
| One pod | an agent-sandbox `Sandbox` running the agent image (by digest) as non-root, read-only root filesystem, no capabilities, service account `run` with no token mounted |
| Egress by mode | `none` (nothing), `clearance` (DNS + Clearance), `clearance+model` (+ the model proxy), `allowlist` (+ listed CIDRs) |
| Identity | projected tokens for the `clearance` and `model-proxy` audiences only, never a key |
| The runtime contract | `HANGAR_RUN_ID`, `_TASK_ID`, `_SESSION_ID`, `_AGENT`, `_EXPIRES_AT`, `_LIMITS`, `_INPUT`, `_OUTPUT_DIR`, `_WORKSPACE`, `CLEARANCE_URL`, `MODEL_PROXY_URL`; `/workspace`, `/run/output`, tokens under `/var/run/hangar` |

## Guardrails

- **A hard deadline nobody has to enforce.** `spec.expiresAt` becomes the Sandbox's `shutdownTime` with
  `shutdownPolicy: Delete`: the agent-sandbox controller deletes the pod at that instant. The pod's
  `activeDeadlineSeconds` is a kubelet-enforced backstop. Past the deadline the composition renders nothing and
  Crossplane removes the namespace. Clearance, Crossplane and the function can all be down and the pod still ends on
  time.
- **The deadline can't move.** The XRD makes every spec field immutable except `frozen`, which can go from false to
  true only (Clearance's breaker). Nobody, Clearance included, can extend a run, widen its network or raise its limits.
- **Fail closed.** No `airframe.autopilotReady` on this cluster's registry record, a `hardened` sandbox without a
  runtime class, an unknown compute class, a TTL over the cap (240 minutes), an allowlist of `/0`, loopback or
  link-local, or an input over 4 KiB: `Rejected`, nothing created, never downgraded. The upper cluster can't carry
  the flag (the registry chart refuses it).
- **No PR-sweep label.** The run namespace never carries `hangar.io/ephemeral-env`; the PR-namespace TTL sweep would
  delete it. A test asserts it, and the cluster's admission policy refuses it.
- **Final phases are final.** `Expired`, `Drained` and `Rejected` never render again, so a finished run can't restart.
- **A narrow caller.** Clearance's permission is one namespaced Role on `agentruns` in `autopilot-runs`. It passes no
  manifest: the schema constrains every field and the composition decides what is created.
- **A confined provider.** provider-kubernetes's grant for these kinds is confined by a ValidatingAdmissionPolicy to
  `agent-r-*` run namespaces, with no pod-security label changes and only `serviceAccountName: run` (cluster repo
  `55-autopilot/agentrun-grants/`, decision D15).

## Lifecycle

`Provisioning` (objects created, Sandbox not Ready) → `Running` (Sandbox Ready) → `Succeeded` / `Failed` (kept for a
5-minute grace period) → `Drained`. `Frozen` cuts egress and keeps the pod for forensics until `freezeHoldMinutes`,
then `Expired`. The phase is `status.phase` and the `RunReady` condition's reason (closed set in
[`xrds/agentrun.meta.yaml`](../../xrds/agentrun.meta.yaml)). Read `RunReady`, not `Ready`: with nothing composed
(Expired, Drained, Rejected) Crossplane's `Ready` is True.

## Installing it on a cluster

Everything below is in the cluster repo (apron renders it with `components.autopilot`, control-plane clusters only):

| Path | What |
|---|---|
| `55-autopilot/agent-sandbox/` | the agent-sandbox controller, chart and image pinned (v1.0.8, commit + digest) |
| `55-autopilot/agentrun-grants/` | provider-kubernetes's ClusterRole, its confinement policy, Clearance's Role |
| `10-crds-operators/crossplane/provider-kubernetes-runtime.yaml` | a stable service account name for provider-kubernetes |
| `10-crds-operators/crossplane/functions.yaml`, `function-agentrun-runtime.yaml` | the Function, with `HANGAR_CLUSTER_NAME` |

Then the XRD and Composition (`xrds/agentrun.yaml`, `compositions/agentrun/composition.yaml`) go into
`airframe-service-catalog`'s include list, after the copy-test.

Verify a live run: `tools/airframe-verify agentrun autopilot-runs/<name>`. Egress is proven by Autopilot's
`tools/netpol_canary.py`, which renders the same policies with this function's `compose()`.

Function internals, the expiry clocks and the shared-grant caveat: [functions/function-agentrun/README.md](../../functions/function-agentrun/README.md).
