#!/usr/bin/env bash
set -euo pipefail

# Regenerates composition.yaml's `source: Inline` template blocks from templates/*/*.yaml. Run this
# any time you add/edit/remove a template - composition.yaml is the committed, GitOps-tracked
# artifact; templates/ is the maintainable source. Same Inline-mode pattern as every other
# Composition in this catalog (compositions/slo/build-composition.sh's header has the "why Inline").

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
  # template: | sits at column 10 under inline: - block content must be indented MORE than that.
  printf '%s\n' "$combined" | sed 's/^/            /; s/^ *$//'
}

RESOURCES="$(render_dir "${SCRIPT_DIR}/templates/render-target-resources")"
STATUS="$(render_dir "${SCRIPT_DIR}/templates/target-status")"

cat > "$OUT" <<HEADER
# GENERATED FILE - do not hand-edit the pipeline's \`input.inline.template\` blocks below. Edit
# templates/render-target-resources/*.yaml or templates/target-status/*.yaml instead, then run
# ./build-composition.sh to regenerate this file.
#
# AwsLambdaTarget: the minimum AWS infrastructure a container-image Lambda function deploys into
# (ECR repository, execution role, a bootstrap Job that seeds the repository, the function, a public
# Function URL) - see xrds/awslambdatarget.yaml's header. Two function-go-templating steps around
# function-auto-ready, the same shape as every Bootstrap-tier Composition in this catalog.
#
# Delimiters: << >> instead of Go's default {{ }}, matching every other Composition in this catalog.
apiVersion: apiextensions.crossplane.io/v1
kind: Composition
metadata:
  name: awslambdatargets.catalog.hangar.io
spec:
  compositeTypeRef:
    apiVersion: catalog.hangar.io/v1alpha1
    kind: AwsLambdaTarget
  mode: Pipeline
  pipeline:
    - step: render-target-resources
      functionRef:
        name: function-go-templating
      input:
        apiVersion: gotemplating.fn.crossplane.io/v1beta1
        kind: GoTemplate
        source: Inline
        inline:
          template: |
${RESOURCES}
        delims:
          left: "<<"
          right: ">>"
    - step: detect-ready
      functionRef:
        name: function-auto-ready
    - step: target-status
      functionRef:
        name: function-go-templating
      input:
        apiVersion: gotemplating.fn.crossplane.io/v1beta1
        kind: GoTemplate
        source: Inline
        inline:
          template: |
${STATUS}
        delims:
          left: "<<"
          right: ">>"
HEADER

echo "Wrote $OUT"
