#!/usr/bin/env bash
# Render-level tests for the chart. No cluster needed; requires helm.
# Usage: charts/airframe-application/tests/run.sh
set -u
cd "$(dirname "$0")/.."
fail=0

kinds() { helm template t . -f "tests/fixtures/$1.yaml" 2>&1 | grep -E '^kind:|^Error' | sort -u | tr '\n' ' '; }

expect_absent() { # fixture kind...
  local out; out=$(kinds "$1"); shift
  case "$out" in *Error*) echo "FAIL $out"; fail=1; return;; esac
  [ -n "$out" ] || { echo "FAIL vacuous: nothing rendered"; fail=1; return; }
  for k in "$@"; do
    case "$out" in *"kind: $k "*) echo "FAIL: $k rendered ($out)"; fail=1;; esac
  done
}
expect_present() {
  local out; out=$(kinds "$1"); shift
  for k in "$@"; do
    case "$out" in *"kind: $k "*) ;; *) echo "FAIL: $k missing ($out)"; fail=1;; esac
  done
}

# AF-10a: no workload until rollout.image is set.
expect_absent  no-image     Rollout RolloutWatch Service ServiceMonitor
expect_absent  rollout-null Rollout RolloutWatch Service ServiceMonitor
expect_present with-image   Rollout RolloutWatch Service

# the empty-image render must never contain the ':' image
if helm template t . -f tests/fixtures/no-image.yaml | grep -qE "image: '?\"?:'?\"?$"; then
  echo "FAIL: image ':' rendered"; fail=1
fi

# AF-4a: airframe validate rejects the typo cases and accepts a real file.
V=../../tools/airframe-validate
for f in typo-top-level-key typo-nested-key bad-component-size; do
  $V --no-render "tests/validate/$f.yaml" >/dev/null 2>&1 && { echo "FAIL: validate accepted $f"; fail=1; }
done
$V --no-render tests/validate/good-boarding-api-dev.yaml >/dev/null 2>&1 || { echo "FAIL: validate rejected the good file"; fail=1; }

[ $fail -eq 0 ] && echo "ok" || exit 1
