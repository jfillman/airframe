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

# release.image (the new key) renders the workload; it wins over the deprecated rollout.image.
expect_present release-image       Rollout RolloutWatch Service
expect_present release-image-wins  Rollout
helm template t . -f tests/fixtures/release-image.yaml | grep -q "image: registry.example/guard-test:v2" || { echo "FAIL: release.image not used by the Rollout"; fail=1; }
helm template t . -f tests/fixtures/release-image-wins.yaml | grep -q "image: registry.example/new:v2" || { echo "FAIL: release.image did not win over rollout.image"; fail=1; }
helm template t . -f tests/fixtures/release-image-wins.yaml | grep -q "registry.example/old" && { echo "FAIL: deprecated rollout.image leaked into the render"; fail=1; }
helm template t . -f tests/fixtures/release-image-jobs.yaml | grep -A60 "kind: CronJob" | grep -q "image: registry.example/guard-test:v3" || { echo "FAIL: cronJob did not fall back to release.image"; fail=1; }

# the empty-image render must never contain the ':' image
if helm template t . -f tests/fixtures/no-image.yaml | grep -qE "image: '?\"?:'?\"?$"; then
  echo "FAIL: image ':' rendered"; fail=1
fi

# AF-3: fromComponent resolves for all three output kinds (literal, secretKeyRef, configMapKeyRef)
# and fails loudly on a reference nothing declares.
out=$(helm template t . -f tests/fixtures/from-component.yaml 2>&1)
echo "$out" | grep -q "value: cache-master.default.svc.cluster.local" || { echo "FAIL: fromComponent literal (redis host) did not resolve"; fail=1; }
echo "$out" | grep -A4 "name: CACHE_PASSWORD" | grep -q "name: cache-connection" || { echo "FAIL: fromComponent secretKeyRef (redis password) did not resolve to cache-connection"; fail=1; }
echo "$out" | grep -A4 "name: DB_URI" | grep -q "name: db-app" || { echo "FAIL: fromComponent secretKeyRef (postgresql uri) did not resolve to db-app"; fail=1; }
echo "$out" | grep -A4 "name: MQ_HOST" | grep -q "name: mq-connection" || { echo "FAIL: fromComponent configMapKeyRef (rabbitmq host) did not resolve to mq-connection"; fail=1; }
helm template t . -f tests/fixtures/from-component-bad-name.yaml 2>&1 | grep -q "no components\[\] entry named 'nonexistent'" || { echo "FAIL: fromComponent did not reject an unknown component name"; fail=1; }
helm template t . -f tests/fixtures/from-component-bad-output.yaml 2>&1 | grep -q "has no output 'bogus'" || { echo "FAIL: fromComponent did not reject an unknown output name"; fail=1; }

# AF-4a: airframe validate rejects the typo cases and accepts a real file.
V=../../tools/airframe-validate
for f in typo-top-level-key typo-nested-key bad-component-size typo-release-key.release; do
  $V --no-render "tests/validate/$f.yaml" >/dev/null 2>&1 && { echo "FAIL: validate accepted $f"; fail=1; }
done
$V --no-render tests/validate/good.release.yaml >/dev/null 2>&1 || { echo "FAIL: validate rejected the good release file"; fail=1; }
$V --no-render tests/validate/good-boarding-api-dev.yaml >/dev/null 2>&1 || { echo "FAIL: validate rejected the good file"; fail=1; }

# AF-4b: dead-end rules, each with its own seeded failing fixture.
for f in bad-cluster-name bad-env-name unknown-component-type secret-literal; do
  $V --no-render "tests/validate/$f.yaml" >/dev/null 2>&1 && { echo "FAIL: validate accepted $f"; fail=1; }
done
$V --no-render tests/validate/bad-cluster-name.yaml 2>&1 | grep -q AF-CLUSTER-001 || { echo "FAIL: AF-CLUSTER-001 did not fire"; fail=1; }
$V --no-render tests/validate/bad-env-name.yaml 2>&1 | grep -q AF-ENV-001 || { echo "FAIL: AF-ENV-001 did not fire"; fail=1; }
$V --no-render tests/validate/unknown-component-type.yaml 2>&1 | grep -q AF-COMP-001 || { echo "FAIL: AF-COMP-001 did not fire"; fail=1; }
$V --no-render tests/validate/secret-literal.yaml 2>&1 | grep -q AF-SECRET-001 || { echo "FAIL: AF-SECRET-001 did not fire"; fail=1; }
# AF-COMP-003 is an advisory warning, not a failure - the boarding-api fixture (real hand-written names) proves it fires without blocking.
$V --no-render tests/validate/good-boarding-api-dev.yaml 2>&1 | grep -q "warn.*AF-COMP-003" || { echo "FAIL: AF-COMP-003 advisory did not fire on the boarding-api fixture"; fail=1; }
$V --no-render --format json tests/validate/good-boarding-api-dev.yaml | python3 -c "import json,sys; json.load(sys.stdin)" || { echo "FAIL: --format json did not produce valid JSON"; fail=1; }

[ $fail -eq 0 ] && echo "ok" || exit 1
