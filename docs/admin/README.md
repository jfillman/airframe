# Airframe: admin guide

Documentation for people **running** this catalog — understanding the composition
graph, the plumbing each XRD talks to, and why it's built the way it is. If you're
an application developer using an already-running catalog, see
[../user/](../user/) instead.

## Start here

| Doc | Read this when... |
|---|---|
| [architecture.md](architecture.md) | You want the current-state system overview: every XRD's inputs/outputs, the composition graph, tiering, and the plumbing underneath. |
| [governance.md](governance.md) | You are an architect or security reviewer asking where a policy is enforced, or a platform engineer turning one into catalog code: who owns which decision, the enforcement ladder from XRD schema to management policies, what is enforced today versus convention, and how a policy change ships. |
| [cloud-credentials.md](cloud-credentials.md) | You are creating or rotating the cloud identities behind the cloud targets: the Crossplane provider identity versus the Glidepath deployer in AWS and Azure, the exact IAM policy or Azure role each gets, where each secret lives, who can read it, and what each one can and cannot do. |

The full design history and open decisions live in `hangar`'s own
[`docs/service-catalog-design.md`](https://github.com/jfillman/hangar/blob/main/docs/service-catalog-design.md)
and [`docs/gitops-strategy.md`](https://github.com/jfillman/hangar/blob/main/docs/gitops-strategy.md) — this repo's
`architecture.md` is the as-built distillation of those, kept in sync with what's
actually in `xrds/` and `compositions/`, not the running design log.

## Illustrated version

The same architecture, as a fully illustrated interactive reference with worked
diagrams:
**[Airframe Service Catalog](https://claude.ai/artifact/TBhiiN1TPjAbiwTTcctnK2)**
