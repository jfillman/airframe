# Analysis catalog

ClusterAnalysisTemplates for Argo Rollouts canary analysis, one copy per cluster. Each cluster installs them with its
own `analysis-catalog` Application (`20-service-catalog/analysis-catalog/application.yaml` in the cluster's gitops repo,
`path: analysis`), pinned separately from `idp-service-catalog` so a new template does not drag a composition bump along:
bump that Application's `targetRevision` when the catalog gains a template. An app uses one from its values with
`clusterScope: true` (Tower's Release tab lists the templates a cluster has and warns about a reference it lacks).

| Template | Passes while | Data it needs |
|---|---|---|
| `pod-health-check` | every pod of the app is Ready | kube-state-metrics |
| `no-restarts-check` | no container restarted in the last 2 minutes | kube-state-metrics |
| `no-oom-check` | no container was OOM-killed | kube-state-metrics |
| `probe-success-check` | the kubelet's liveness/readiness probes succeed | kubelet `prober_probe_total` |
| `error-rate-check` | 5xx share < `max-error-rate` (0.05) | Traefik request metrics (not scraped yet) |
| `success-rate-check` | non-5xx share >= `min-success-rate` (0.95) | Traefik request metrics (not scraped yet) |
| `latency-check` | p95 < `max-p95-seconds` (0.5) | Traefik request metrics (not scraped yet) |

Every template takes `namespace` and `app` (the pod-name prefix). A query with no data passes rather than blocks, so a
template whose metrics are not being collected is inert, not a failed rollout. The Prometheus address is the
kube-prometheus-stack service every cluster uses; kind-prod has no Prometheus yet, so there the templates exist and
query nothing.
