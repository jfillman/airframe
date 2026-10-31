# Agent: the pin that makes a definition live

`Agent` (`catalog.hangar.io/v1alpha1`, namespaced) is the durable half of an Autopilot agent, as a **pin**: which
commit of the agent's definition file, in the app's own repository, Clearance loads. The ephemeral half is
[AgentRun](agentrun.md). Autopilot M4.

**Status: built 2026-10-31**, ships through `airframe-service-catalog` on clusters rendered with `components.autopilot`
(the include list, like AgentRun). Clearance v0.17.0 loads pins; the Backstage templates open them.

## What an agent is made of

| | Where | Reviewed by |
|---|---|---|
| The **definition** (`agents/<name>.yaml`: kind, identity, tier ceiling, tools, repos, models, limits, image, instructions, triggers; schema `agent-definition.schema.json` in the clearance repo) | the app's own repository | the app's team, as any change to their code |
| The **pin** (this XR: repo, path, commit, owner) | `tenants/<app>/xr-requests/<name>.yaml` in the control-plane tenants repo, so it lands in `app-<app>-cicd` beside the app's other requests | the platform's gitops review, like every other request |
| The **run** ([AgentRun](agentrun.md)) | created by Clearance in `autopilot-runs` | nobody: it lives for minutes under the definition's limits |

Clearance lists Agent XRs (its airframe reader may list every `catalog.hangar.io` kind), fetches each pinned file
through the agents' GitHub App (Glidepath's broker, which issues a read token for an onboarded app's own repositories
and nothing else), validates it, and loads it beside the platform's bundled definitions. A pin names a **commit**: what
Clearance loads cannot change without a change here. Moving an agent to a new definition is a new commit in the pin.

## Guardrails

- **Admission refuses a bad pin.** `commit` is a full 40-hex SHA (a branch or a tag is not a pin); `path` is a YAML file
  inside the repository; `repo` is the app's own (`<app>`, `gitops-<app>` or `gitops-infra-<app>`: the broker's rule,
  mirrored so a wrong pin fails before Clearance ever asks); `app` can't change after creation.
- **Clearance refuses a pin that disagrees with its file.** The file's `name` must be the XR's name and its `owner` the
  XR's `spec.owner`; a workload identity must be `autopilot-runs/<name>`; a name that is a bundled platform
  definition's is never taken; two pins naming one agent load neither. A refused pin is listed by clearance-api
  (`GET /v1/agents`, `rejected`) with the reason, and recorded as `definition.reject` evidence. Nothing is written back
  to the XR: Clearance's one Kubernetes write stays AgentRun.
- **Nothing is composed.** An agent needs no in-cluster object until it runs. The composition publishes the pin as
  status (`repo`, `path`, `commit`, `shortCommit`, `pin`) and one condition, `AgentPinned`, so `kubectl get agents` and
  the catalog show what is pinned. `Ready=True` means the pin is well-formed, not that Clearance loaded it.
- **Every change is evidence, once.** `definition.load` (new or re-pinned), `definition.unload` (pin removed),
  `definition.reject`, each with the pin as target, principal `pin:<namespace>/<name>`. An auditor reads which
  definition was live when from the chain, not from git archaeology.
- **Tightening is immediate.** A running session resolves its definition by name on every call, so re-pinning to a
  tighter definition applies to runs in flight. Raising authority is the reviewed pin plus the reviewed file.

## Where definitions live

- **A prompt-only agent** (its code is one of Autopilot's shared runtime images) lives in a team's
  **`AgentRepository`**: a repo of `agents/<name>.yaml` files with a checks-only `cicd.yaml`, registered with Glidepath
  through its TektonCICD child, so Glidepath runs its PR checks and the agent release and builds nothing. Its pins land
  in `tenants/<repo>/xr-requests/`.
- **A code agent** (its own source and image) is an app: onboard it with an application kind. Its `agents/` files get
  the same checks and release.
- Either way, Glidepath's `agent-release` opens the pin PR on merge (glidepath `docs/admin/agent-definitions.md`).

## How a pin is made

Two Backstage templates (the backstage repo, `templates/autopilot/`), not the generated XRD form (the XRD carries
`add-to-catalog: "false"`: the form could not open the definition PR and would ask for a namespace by hand):

- **New agent**: the definition file (and a Preflight starter, and the agent's catalog Component) as a PR on the app's
  repository, then this pin, at that PR's commit, as a PR on the tenants repo. Autopilot's *New agent profile* page
  (Backstage, `/autopilot?view=new`) opens the template with the form filled in.
- **Pin agent**: a new commit for an existing agent (after the definition changed), as a PR on the tenants repo.

Agent XRs are ingested into the catalog as **Resources** (backstage `ingestAsResourcesKinds`), never Components: the
definition PR carries the agent's Component, and a same-named ingested one would collide with it (the RolloutWatch
lesson).

## Verify a live pin

`tools/airframe-verify agent app-<app>-cicd/<name>` checks `AgentPinned` and `status.commit`; whether Clearance loaded
it is `GET /v1/agents` on clearance-api (the agent's `source.commit` equals the pin, and it is not under `rejected`),
which the Autopilot plugin's Agents page shows.

## Installing it on a cluster

| Path (cluster repo, rendered by apron with `components.autopilot`) | What |
|---|---|
| `20-service-catalog/airframe-service-catalog/` | `xrds/agent.yaml` and `compositions/agent/composition.yaml` in the include list |
| `02-argocd-apps/xr-requests/appproject.yaml` | `Agent` in the `airframe-onboarding` project's namespace resource whitelist, so a tenant's xr-requests may carry one |
| `55-autopilot/clearance/` | the gateway with `GITHUB_PR_ENABLED=1` (the loader reads through the same broker token) and the agents' App installed on the app repositories that hold definitions |
