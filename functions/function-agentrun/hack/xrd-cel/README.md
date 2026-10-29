# AgentRun XRD CEL rules against a real kube-apiserver

Not part of CI (it needs Go and the envtest binaries). Run it after changing `xrds/agentrun.yaml`'s schema or rules.

1. `go run . ../../../../xrds/agentrun.yaml > /tmp/agentrun.crd.yaml` prints the CRD Crossplane itself would generate
   (crossplane-runtime v2.3.3 `pkg/xcrd`, the version Crossplane v2.3.4 uses). Drop `metadata.ownerReferences` before
   applying it outside Crossplane.
2. Start an envtest kube-apiserver (`setup-envtest use 1.36.2 -p path`; apron's `tests/policy/test_agentrun_grants.py`
   shows the flags), apply the CRD, create the namespace `autopilot-runs`.
3. `python3 test_xrd_cel.py <kubeconfig>`: 18 checks (name pattern, digest-only image, allowlist rules, /0, sidecar
   name, immutable spec fields, Crossplane can still write `spec.crossplane`, freeze but never unfreeze).

Last run 2026-10-28 on kube-apiserver v1.36.2: 18/18, and the CRD's CEL cost estimate was accepted.
