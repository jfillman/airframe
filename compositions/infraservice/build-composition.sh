#!/usr/bin/env bash
set -euo pipefail

# Regenerates composition.yaml's two `source: Inline` template blocks from
# templates/render-infra-resources/*.yaml and templates/cicd-onboarding-status/*.yaml.
# Run this any time you add/edit/remove a file in either directory - composition.yaml is
# the committed, GitOps-tracked artifact; the templates/ files are the maintainable
# source. Same split-by-pipeline-step generation approach as
# compositions/nodejsapplication/build-composition.sh, copied wholesale (only the
# directory names/Composition name differ).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="${SCRIPT_DIR}/composition.yaml"

render_dir() {
  local dir="$1"
  local combined
  combined="$(
    for f in "${dir}"/*.yaml; do
      cat "$f"
      echo "---"
    done
  )"
  # template: | sits at column 10 under inline: - block content must be indented MORE
  # than that, not from column 0, or YAML parses it as leaving the scalar (same gotcha
  # documented in compositions/slo/build-composition.sh).
  printf '%s\n' "$combined" | sed 's/^/            /; s/^ *$//'
}

INFRA_RESOURCES="$(render_dir "${SCRIPT_DIR}/templates/render-infra-resources")"
CICD_STATUS="$(render_dir "${SCRIPT_DIR}/templates/cicd-onboarding-status")"

cat > "$OUT" <<HEADER
# GENERATED FILE - do not hand-edit the pipeline's \`input.inline.template\` blocks
# below. Edit templates/render-infra-resources/*.yaml or
# templates/cicd-onboarding-status/*.yaml instead, then run ./build-composition.sh to
# regenerate this file.
#
# Two function-go-templating steps, not one (compositions/nodejsapplication's own
# pattern, copied here): render-infra-resources composes the real provider-github
# managed resources plus the composed TektonCICD child, cicd-onboarding-status
# patches the XR's own status afterward to proxy DevClusterReady/CicdOnboarded from
# that child. Both share the ONE already-installed function-go-templating Function
# via source: Inline - registering a second Function package pointing at the same
# reference corrupted Crossplane's shared dependency-lock graph cluster-wide, a real
# bug hit live building the SLO Composition (see compositions/slo/build-composition.sh's
# own header) - never repeat that here.
#
# Delimiters: << >> instead of Go's default {{ }}, matching every other Composition
# in this catalog.
apiVersion: apiextensions.crossplane.io/v1
kind: Composition
metadata:
  name: infraservices.catalog.idp.io
spec:
  compositeTypeRef:
    apiVersion: catalog.idp.io/v1alpha1
    kind: InfraService
  mode: Pipeline
  pipeline:
    - step: render-infra-resources
      functionRef:
        name: function-go-templating
      input:
        apiVersion: gotemplating.fn.crossplane.io/v1beta1
        kind: GoTemplate
        source: Inline
        inline:
          template: |
${INFRA_RESOURCES}
        delims:
          left: "<<"
          right: ">>"
    - step: detect-ready
      functionRef:
        name: function-auto-ready
    - step: cicd-onboarding-status
      functionRef:
        name: function-go-templating
      input:
        apiVersion: gotemplating.fn.crossplane.io/v1beta1
        kind: GoTemplate
        source: Inline
        inline:
          template: |
${CICD_STATUS}
        delims:
          left: "<<"
          right: ">>"
HEADER

echo "Wrote $OUT"
