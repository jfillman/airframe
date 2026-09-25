#!/usr/bin/env bash
set -euo pipefail

# Regenerates composition.yaml's `source: Inline` template block from
# templates/*.yaml. Run this any time you add/edit/remove a file in
# templates/ - composition.yaml is the committed, GitOps-tracked artifact;
# the templates/ files are the maintainable source. Same Inline-mode pattern
# as every other Composition in this catalog (compositions/slo/
# build-composition.sh's own header has the full "why Inline" writeup) -
# not repeated here.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="${SCRIPT_DIR}/composition.yaml"

COMBINED="$(
  for f in "${SCRIPT_DIR}"/templates/*.yaml; do
    cat "$f"
    echo "---"
  done
)"
# template: | sits at column 10 under inline: - block content must be
# indented MORE than that, not from column 0, or YAML parses it as leaving
# the scalar (same gotcha documented in compositions/slo/build-composition.sh).
INDENTED="$(printf '%s\n' "$COMBINED" | sed 's/^/            /; s/^ *$//')"

cat > "$OUT" <<HEADER
# GENERATED FILE - do not hand-edit the pipeline's \`input.inline.template\`
# block below. Edit templates/*.yaml instead, then run ./build-composition.sh
# to regenerate this file.
#
# Component Composition (Item 7, Round 2026-09-24)
# (service-catalog-design.md). Single function-go-templating step: renders
# a CloudNativePG Cluster and a NetworkPolicy for its operator - see
# templates/cluster.yaml's own header for the full mapping/reasoning.
#
# Delimiters: << >> instead of Go's default {{ }}, matching every other
# Composition in this catalog.
apiVersion: apiextensions.crossplane.io/v1
kind: Composition
metadata:
  name: postgresql.catalog.idp.io
spec:
  compositeTypeRef:
    apiVersion: catalog.idp.io/v1alpha1
    kind: PostgreSQL
  mode: Pipeline
  pipeline:
    - step: render-postgresql-resources
      functionRef:
        name: function-go-templating
      input:
        apiVersion: gotemplating.fn.crossplane.io/v1beta1
        kind: GoTemplate
        source: Inline
        inline:
          template: |
${INDENTED}
        delims:
          left: "<<"
          right: ">>"
    - step: detect-ready
      functionRef:
        name: function-auto-ready
HEADER

echo "Wrote $OUT"
