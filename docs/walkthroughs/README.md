# Executable walkthroughs (AF-7a)

A walkthrough is the prose quickstart's checkable skeleton: the same sections, but each one
reduced to a `verify` command whose exit code says whether that section's claim is still true
right now, against the real dev/prod clusters. It does not re-run one-time creation actions
(open a PR, merge it) - those already happened; the walkthrough checks their *lasting effect*
(the XR is Synced/Ready, the pod is Running, the endpoint answers) so it stays safely re-runnable
without recreating or tearing down anything.

| File | Source guide |
|---|---|
| [part1-boarding-api.yaml](part1-boarding-api.yaml) | [quickstart.md](../user/quickstart.md) - NodeJS + Redis, ground and flight |
| [part2-flight-api.yaml](part2-flight-api.yaml) | [quickstart-flight-api.md](../user/quickstart-flight-api.md) - Spring Boot + PostgreSQL |
| [part3-broker.yaml](part3-broker.yaml) | [quickstart-broker.md](../user/quickstart-broker.md) - shared RabbitMQ, publisher and consumer |
| [part4-baggage-api.yaml](part4-baggage-api.yaml) | [quickstart-baggage-api.md](../user/quickstart-baggage-api.md) - Python + MongoDB, broker consumer |
| [part5-skyport-auth.yaml](part5-skyport-auth.yaml) | [quickstart-skyport-auth.md](../user/quickstart-skyport-auth.md) - shared Dex on both clusters, attached clients, enforced tokens (401/200) |
| [part6-gate-api.yaml](part6-gate-api.yaml) | [quickstart-gate-api.md](../user/quickstart-gate-api.md) - terminal path to a canary |
| [part7-checkin-api.yaml](part7-checkin-api.yaml) | [quickstart-checkin-api.md](../user/quickstart-checkin-api.md) - Tower path |

The order to do them in, and what each needs first, is the [Skyport runbook](../user/skyport-runbook.md).

## File format

```yaml
title: string                    # shown as the walkthrough's own heading
app: string                      # the app this walkthrough is about
sourceDoc: path                  # the prose quickstart this was converted from, relative to this folder
steps:
  - id: kebab-case-id            # stable; matches the source doc's section where practical
    title: string
    command: |                   # what a human/agent actually runs - documentation, not executed
      kubectl --context "${DEV_CONTEXT}" get pods -n app-boarding-api-dev
    expected: string             # prose: what you should see
    verify: |                    # a real, safe, idempotent shell command; exit 0 = this step's
      kubectl --context "${DEV_CONTEXT}" get pods -n app-boarding-api-dev
      # claim still holds. Never destructive, never a one-time creation action re-run.
```

### Cluster placeholders

Walkthroughs never name a cluster. They use placeholders, which the runner substitutes in `command` and
`verify` and also exports as environment variables to the `verify` shell (so `$DEV_CONTEXT` works as
well as `${DEV_CONTEXT}`):

| Placeholder | Meaning | Comes from |
|---|---|---|
| `${DEV_CLUSTER}` | the dev cluster's registry name (XR names like `<app>-<cluster>-<env>`, `devCluster`) | `--dev-cluster`, `HANGAR_DEV_CLUSTER`, or `--clusters` |
| `${PROD_CLUSTER}` | the prod (upper) cluster's registry name | `--prod-cluster`, `HANGAR_PROD_CLUSTER`, or `--clusters` |
| `${DEV_CONTEXT}` | kubectl context for the dev cluster | `--dev-context`, `HANGAR_DEV_CONTEXT`; default: the dev cluster's name |
| `${PROD_CONTEXT}` | kubectl context for the prod cluster | `--prod-context`, `HANGAR_PROD_CONTEXT`; default: the prod cluster's name |
| `${GITHUB_OWNER}` | owner of the app repos (required, no default) | `--github-owner`, `HANGAR_GITHUB_OWNER`, or `scm.owner` in the `--clusters` file or an Apron `--cluster-config` |

`--clusters PATH` (or `HANGAR_CLUSTERS_FILE`) reads the fleet's `clusters.yaml`: the dev cluster is the
one record with the `control-plane` role, the prod cluster the one `zone: upper` record with the
`workloads` role. More than one candidate is an error unless a flag or env var names it. Contexts
default to the cluster names (the one-name rule: a cluster's registry name is also its context). A run
that needs a name nobody gave exits 2 and says which.

All of these can live in an env file: `--env-file PATH`, `HANGAR_WALKTHROUGH_ENV`, or `./.walkthrough.env`
when it exists (`KEY=VALUE` lines with the `HANGAR_*` names; real environment variables win). See the
runbook's [Configure](../user/skyport-runbook.md#configure) step. Every `verify` also gets `AIRFRAME_ROOT`, this
checkout, for `"$AIRFRAME_ROOT/tools/airframe-verify" ...` and for
`. "$AIRFRAME_ROOT/docs/walkthroughs/lib/dex.sh"`: `dex_token` (mint a Dex `client_credentials` token
for an attach client, never printed), `http_status` / `http_body` (a GET through a port-forward, with
an optional bearer token) and `expect_enforced` (401 without a token, 200 with one).

## Running

```
tools/walkthrough-runner docs/walkthroughs/part1-boarding-api.yaml --clusters ../gitops-cluster-dev/clusters.yaml
tools/walkthrough-runner --all --dev-cluster <dev-cluster> --prod-cluster <prod-cluster>
```

Runs every step's `verify` in order, reports PASS/FAIL per step (with the failing command's
stdout/stderr on failure), and exits non-zero if any step failed - "the walkthrough replays
green" means every step passed. `--all` runs every `part*.yaml` in this folder (or `--dir`) and ends
with one summary line. `--render OUT.md` renders one walkthrough to markdown (title, command, expected
result per step) without running anything; without cluster names it prints `<dev-cluster>`-style
placeholders, with them it fills them in.

Needs real cluster access (`kubectl` with a context for each cluster), `gh` authenticated for the
GitHub checks, and, for the HTTP checks, a working `kubectl port-forward` (the runner's steps start and
stop their own).

The runner's own test, which never touches a cluster: `python3 tools/test_walkthrough_runner.py`.
