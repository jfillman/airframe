# mongodb Composition - render fixtures

Cases in `cases.yaml`, expectations in `expected/`, run by `tools/test_compositions.py` (see its header
for the two renderers; function-auto-ready must run with `--feature-gates=CELHealthcheckCustomizations=true`
because the readiness rules in `compositions/_shared/readiness-context.yaml` are CEL). The observed-*
fixtures are the composed resources as Crossplane would observe them once the operator has acted; the
`ready` cases prove the readiness rules mark them ready and the composite turns `Ready: True`.
Nothing here talks to a cluster.
