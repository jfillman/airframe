# AgentRepository render fixtures

Cases for `tools/test_compositions.py` (see `../../../tools/test_compositions.py` and the catalog-wide
`compositions/*/example/` convention). `gate-fail` renders with no cluster-registry entry, so the
dev-cluster gate holds everything back; `defaults` passes the gate with `cluster-registry-dev-ready.yaml`
(a registered, cicdReady `example-dev`) and renders the repo, its four scaffold files and the TektonCICD child. The `scaffold-*` cases exercise the scaffold ledger
(`compositions/_shared/render-github-resources/00-scaffold-done.yaml`): the four create-once files are
composed until observed Ready, recorded in `status.scaffold.done`, then never rendered again.
