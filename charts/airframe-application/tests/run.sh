#!/usr/bin/env bash
# Render-level tests for the chart. No cluster needed; requires helm.
# Usage: charts/airframe-application/tests/run.sh
set -u
cd "$(dirname "$0")/.."
# helm template takes its default namespace from the ambient kube context (found 2026-10-06: a
# context set to app-gate-api-cicd made the fromComponent host assertion fail). The render must not
# depend on whatever cluster the person running this happens to be pointed at.
export KUBECONFIG=/dev/null
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
$V --no-render tests/validate/good-boarding-api-dev.release.yaml >/dev/null 2>&1 || { echo "FAIL: validate rejected the good file's release companion"; fail=1; }

# AF-5b: AF-OWNER-001 is an error (promoted from warning once the release-file split landed for
# real) - a release key in a human file, or anything else in a release file, both fail.
$V --no-render tests/validate/bad-owner-release-key-in-human-file.yaml >/dev/null 2>&1 && { echo "FAIL: AF-OWNER-001 did not reject a release key in a human file"; fail=1; }
$V --no-render tests/validate/bad-owner-non-release-key-in-release-file.release.yaml >/dev/null 2>&1 && { echo "FAIL: AF-OWNER-001 did not reject a non-release key in a release file"; fail=1; }

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

# Extra labels and annotations (rollout.labels/annotations, podLabels/podAnnotations, serviceLabels/serviceAnnotations):
# each lands on its own object, chart-owned labels and checksum annotations are reserved and fail the render naming the key,
# and a values file that sets none renders exactly as before.
out=$(helm template t . -f tests/fixtures/labels-annotations.yaml 2>&1)
render_ok() { python3 -c "
import sys, yaml
docs = [d for d in yaml.safe_load_all(sys.stdin.read()) if d]
by = lambda kind, name=None: [d for d in docs if d['kind'] == kind and (name is None or d['metadata']['name'] == name)]
ro = by('Rollout')[0]; svc = by('Service', 'guard-test')[0]; prev = by('Service', 'guard-test-preview')[0]
tmpl = ro['spec']['template']['metadata']
checks = {
  'rollout labels': ro['metadata']['labels'].get('team') == 'platform',
  'rollout annotations': ro['metadata'].get('annotations') == {'owner': 'ops@example.com'},
  'pod labels': tmpl['labels'].get('tier') == 'backend',
  'pod annotations': tmpl['annotations'].get('prometheus.io/scrape') == 'true' and tmpl['annotations'].get('prometheus.io/port') == '8080',
  'checksum kept next to pod annotations': 'checksum/configmaps' in tmpl['annotations'],
  'service labels': svc['metadata']['labels'].get('exposure') == 'internal',
  'service annotations': svc['metadata'].get('annotations') == {'example.com/lb': 'internal'},
  'preview service too': prev['metadata']['labels'].get('exposure') == 'internal' and prev['metadata'].get('annotations') == {'example.com/lb': 'internal'},
  'selector untouched': ro['spec']['selector']['matchLabels'] == {'app.kubernetes.io/name': 'guard-test', 'app.kubernetes.io/instance': 't'},
  'pod labels do not leak to the service': 'tier' not in svc['metadata']['labels'],
}
bad = [k for k, v in checks.items() if not v]
print('; '.join(bad)); sys.exit(1 if bad else 0)
"; }
echo "$out" | render_ok || { echo "FAIL: extra labels/annotations ($(echo "$out" | render_ok 2>&1 | tail -1))"; fail=1; }
helm template t . -f tests/fixtures/labels-reserved-label.yaml 2>&1 | grep -q "rollout.podLabels must not set 'app.kubernetes.io/name'" || { echo "FAIL: a reserved app.kubernetes.io label was accepted"; fail=1; }
helm template t . -f tests/fixtures/labels-reserved-hangar.yaml 2>&1 | grep -q "rollout.labels must not set 'hangar.io/env'" || { echo "FAIL: a reserved hangar.io label was accepted"; fail=1; }
helm template t . -f tests/fixtures/labels-reserved-checksum.yaml 2>&1 | grep -q "rollout.podAnnotations must not set 'checksum/secrets'" || { echo "FAIL: a chart-owned checksum annotation was accepted"; fail=1; }
# No new fields set: the rendered objects have no annotations block they did not have before.
helm template t . -f tests/fixtures/with-image.yaml | python3 -c "
import sys, yaml
for d in (x for x in yaml.safe_load_all(sys.stdin.read()) if x):
    if d['kind'] in ('Rollout', 'Service'):
        assert 'annotations' not in d['metadata'], d['kind']
" || { echo "FAIL: an empty annotations block is rendered when none is set"; fail=1; }

# ADR-0021: release identity on the Rollout's own metadata, only when releaseTracking.releaseId is set.
ro() { helm template t . -f "tests/fixtures/$1.yaml" --show-only templates/workload/rollout.yaml 2>&1; }
meta() { ro "$1" | awk '/^kind: Rollout/{f=1} f&&/^spec:/{exit} f'; }
meta release-tracking-id | grep -q 'hangar.io/release-id: "chain1:kind-prod/staging"' || { echo "FAIL: release-id annotation missing"; fail=1; }
meta release-tracking-id | grep -q 'hangar.io/app-namespace: "app-guard-test-cicd"' || { echo "FAIL: app-namespace annotation missing"; fail=1; }
meta release-tracking-id | grep -q 'hangar.io/release-tracked: "true"' || { echo "FAIL: release-tracked label missing"; fail=1; }
ro release-tracking-id | awk '/^  template:/{f=1} f' | grep -q 'hangar.io/release-id' && { echo "FAIL: release-id leaked into the pod template (would force a new ReplicaSet)"; fail=1; }
helm template t . -f tests/fixtures/release-tracking-id-with-user-meta.yaml --show-only templates/workload/rollout.yaml | python3 -c "
import sys, yaml
m = yaml.safe_load(sys.stdin.read())['metadata']
ok = (m['annotations'].get('hangar.io/release-id') == 'chain1:kind-prod/staging' and m['annotations'].get('owner') == 'sre'
      and m['labels'].get('team') == 'payments' and m['labels'].get('hangar.io/release-tracked') == 'true')
sys.exit(0 if ok else 1)" || { echo "FAIL: release identity and rollout.labels/annotations did not merge into one labels and one annotations block"; fail=1; }
for fx in release-tracking-no-id release-image; do
  meta "$fx" | grep -qE 'release-id|release-tracked' && { echo "FAIL: $fx rendered release identity without a releaseId"; fail=1; }
done

# ADR-0021 phase 3b: the PreSync/PostSync/SyncFail hook Jobs are gone, and release tracking with no
# Rollout fails the render instead of silently reporting nothing.
helm template t . -f tests/fixtures/release-tracking-id.yaml | grep -q 'platform-outcome\|argocd.argoproj.io/hook' && { echo "FAIL: an outcome hook Job rendered"; fail=1; }
out=$(helm template t . -f tests/fixtures/release-tracking-no-rollout.yaml 2>&1)
echo "$out" | grep -q 'releaseTracking is set but this release has no Rollout' || { echo "FAIL: releaseTracking without a Rollout must fail the render"; fail=1; }
helm template t . -f tests/fixtures/rollout-null.yaml >/dev/null 2>&1 || { echo "FAIL: a rollout-null release with no releaseTracking must still render"; fail=1; }

# Fast-track rollback (glidepath ADR-0021 phase 4): on by default with the last 3 revisions, off with null.
ro release-image | grep -A1 '^  rollbackWindow:' | grep -q 'revisions: 3' || { echo "FAIL: rollbackWindow {revisions: 3} is not the default"; fail=1; }
ro rollback-window-off | grep -q 'rollbackWindow' && { echo "FAIL: rollbackWindow: null did not turn it off"; fail=1; }

[ $fail -eq 0 ] && echo "ok" || exit 1
