#!/usr/bin/env bash
# Render-level tests for the chart. No cluster needed; requires helm.
# Usage: charts/airframe-application/tests/run.sh
set -u
cd "$(dirname "$0")/.."
# helm template takes its default namespace from the ambient kube context; the render must not depend on
# whatever cluster the person running this is pointed at. An empty, private file (not /dev/null, which
# makes helm warn on stderr and break the assertions that parse 2>&1 output).
KUBECONFIG=$(mktemp); export KUBECONFIG
trap 'rm -f "$KUBECONFIG"' EXIT
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
# ADR-0029: release.image.digest pins what runs (Rollout and batch fallback); source is never rendered.
D=sha256:53de992b7d3b3f5965a10695b5b04a02cc0558807c0ad3a8f1c10971c3bd762d
out=$(helm template t . -f tests/fixtures/release-image-digest.yaml 2>&1)
[ "$(echo "$out" | grep -c "image: registry.example/flight/guard-test:v4@$D")" -eq 2 ] || { echo "FAIL: digest not rendered as repository:tag@digest in both the Rollout and the CronJob"; fail=1; }
echo "$out" | grep -q "registry.example/ground" && { echo "FAIL: release.image.source leaked into the render"; fail=1; }
helm template t . -f tests/fixtures/release-image.yaml | grep -q "image: registry.example/guard-test:v2$" || { echo "FAIL: no digest must still render repository:tag"; fail=1; }

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
$V --no-render tests/validate/good-digest.release.yaml >/dev/null 2>&1 || { echo "FAIL: validate rejected a release file with digest and source"; fail=1; }
$V --no-render tests/validate/bad-digest.release.yaml >/dev/null 2>&1 && { echo "FAIL: validate accepted a digest that is not sha256:<hex>"; fail=1; }
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

# Dev-vs-upper secret layout comes from clusterType (the cluster's registry type), never from the cluster's name.
es() { helm template t . -f "tests/fixtures/$1.yaml" --show-only templates/config/external-secret.yaml 2>&1; }
es secrets-dev-cluster | python3 -c "
import sys, yaml
s = yaml.safe_load(sys.stdin.read())['spec']; d = {e['secretKey']: e for e in s['data']}
ok = (s['secretStoreRef']['name'] == 'guard-test-example-dev' and d['API_KEY']['remoteRef']['key'] == 'pr-12/API_KEY'
      and d['SLACK_URL']['remoteRef']['key'] == 'SLACK_URL' and 'sourceRef' not in d['SLACK_URL'])
sys.exit(0 if ok else 1)" || { echo "FAIL: clusterType dev did not read the shared store with an env prefix"; fail=1; }
es secrets-upper-cluster | python3 -c "
import sys, yaml
s = yaml.safe_load(sys.stdin.read())['spec']; d = {e['secretKey']: e for e in s['data']}
ok = (s['secretStoreRef']['name'] == 'guard-test-example-prod-staging' and d['API_KEY']['remoteRef']['key'] == 'API_KEY'
      and d['SLACK_URL']['sourceRef']['storeRef']['name'] == 'guard-test-example-prod')
sys.exit(0 if ok else 1)" || { echo "FAIL: clusterType upper did not read the per-env store"; fail=1; }
helm template t . -f tests/fixtures/secrets-no-cluster-type.yaml 2>&1 | grep -q "clusterType is empty" || { echo "FAIL: secrets: without clusterType rendered instead of failing"; fail=1; }

# ADR-0021: release identity on the Rollout's own metadata, only when releaseTracking.releaseId is set.
ro() { helm template t . -f "tests/fixtures/$1.yaml" --show-only templates/workload/rollout.yaml 2>&1; }
meta() { ro "$1" | awk '/^kind: Rollout/{f=1} f&&/^spec:/{exit} f'; }
meta release-tracking-id | grep -q 'hangar.io/release-id: "chain1:example-prod/staging"' || { echo "FAIL: release-id annotation missing"; fail=1; }
meta release-tracking-id | grep -q 'hangar.io/app-namespace: "app-guard-test-cicd"' || { echo "FAIL: app-namespace annotation missing"; fail=1; }
meta release-tracking-id | grep -q 'hangar.io/release-tracked: "true"' || { echo "FAIL: release-tracked label missing"; fail=1; }
ro release-tracking-id | awk '/^  template:/{f=1} f' | grep -q 'hangar.io/release-id' && { echo "FAIL: release-id leaked into the pod template (would force a new ReplicaSet)"; fail=1; }
helm template t . -f tests/fixtures/release-tracking-id-with-user-meta.yaml --show-only templates/workload/rollout.yaml | python3 -c "
import sys, yaml
m = yaml.safe_load(sys.stdin.read())['metadata']
ok = (m['annotations'].get('hangar.io/release-id') == 'chain1:example-prod/staging' and m['annotations'].get('owner') == 'sre'
      and m['labels'].get('team') == 'payments' and m['labels'].get('hangar.io/release-tracked') == 'true')
sys.exit(0 if ok else 1)" || { echo "FAIL: release identity and rollout.labels/annotations did not merge into one labels and one annotations block"; fail=1; }
for fx in release-tracking-no-id release-image; do
  meta "$fx" | grep -qE 'release-id|release-tracked' && { echo "FAIL: $fx rendered release identity without a releaseId"; fail=1; }
done

# ADR-0021 phase 3b: the PreSync/PostSync/SyncFail hook Jobs are gone, and release tracking with no
# Rollout fails the render instead of silently reporting nothing.
helm template t . -f tests/fixtures/release-tracking-id.yaml | grep -q 'platform-outcome\|argocd.argoproj.io/hook' && { echo "FAIL: an outcome hook Job rendered"; fail=1; }
out=$(helm template t . -f tests/fixtures/release-tracking-no-rollout.yaml 2>&1)
echo "$out" | grep -q 'releaseTracking is set but this environment runs no workload' || { echo "FAIL: releaseTracking on a rollout: null environment must fail the render"; fail=1; }
helm template t . -f tests/fixtures/rollout-null.yaml >/dev/null 2>&1 || { echo "FAIL: a rollout-null release with no releaseTracking must still render"; fail=1; }

# rollout.enabled (2026-10-10): false means no service even with an image; no rollout: key means the chart
# default (a service); releaseTracking on a disabled environment fails with a message naming the setting.
expect_absent  workload-disabled          Rollout RolloutWatch Service ServiceMonitor
expect_present no-rollout-key-with-image  Rollout RolloutWatch Service
helm template t . -f tests/fixtures/workload-disabled-tracking.yaml 2>&1 | grep -q 'runs no workload (rollout.enabled: false' || { echo "FAIL: releaseTracking with rollout.enabled: false must fail the render, naming the setting"; fail=1; }

# Fast-track rollback (glidepath ADR-0021 phase 4): on by default with the last 3 revisions, off with null.
ro release-image | grep -A1 '^  rollbackWindow:' | grep -q 'revisions: 3' || { echo "FAIL: rollbackWindow {revisions: 3} is not the default"; fail=1; }
ro rollback-window-off | grep -q 'rollbackWindow' && { echo "FAIL: rollbackWindow: null did not turn it off"; fail=1; }

# Non-root by default as UID/GID 65532, Tower's break-glass debug UID, so process access can read the app's files.
# Keys a release sets merge onto the default; null drops it.
ro release-image | grep -A7 '^      securityContext:' | grep -q 'runAsUser: 65532' || { echo "FAIL: pod securityContext runAsUser 65532 is not the default"; fail=1; }
ro release-image | grep -q 'runAsNonRoot: true' || { echo "FAIL: runAsNonRoot is not the default"; fail=1; }
ro release-image | grep -A4 '^        securityContext:' | grep -q 'allowPrivilegeEscalation: false' || { echo "FAIL: container securityContext default missing"; fail=1; }
ro security-context-off | grep -q 'securityContext' && { echo "FAIL: securityContext null did not drop the default"; fail=1; }
ro security-context-merge | grep -q 'runAsUser: 1000' || { echo "FAIL: podSecurityContext override not applied"; fail=1; }
ro security-context-merge | grep -q 'runAsNonRoot: true' || { echo "FAIL: podSecurityContext override did not merge onto the default"; fail=1; }
ro security-context-merge | grep -q 'readOnlyRootFilesystem: true' || { echo "FAIL: containerSecurityContext override not applied"; fail=1; }
ro security-context-merge | grep -q 'allowPrivilegeEscalation: false' || { echo "FAIL: containerSecurityContext override did not merge onto the default"; fail=1; }

# serviceAccount.projectedTokens: one projected volume per entry (audience, expirationSeconds default 600, path token),
# mounted read-only on the main container and every Job, alongside the chart's own volumes; none rendered by default.
helm template t . -f tests/fixtures/projected-token.yaml | python3 -c "
import sys, yaml
docs = [d for d in yaml.safe_load_all(sys.stdin.read()) if d]
ro = [d for d in docs if d['kind'] == 'Rollout'][0]['spec']['template']['spec']
job = [d for d in docs if d['kind'] == 'Job'][0]['spec']['template']['spec']
sa = [d for d in docs if d['kind'] == 'ServiceAccount'][0]
for spec, what in ((ro, 'rollout'), (job, 'job')):
    vols = {v['name']: v for v in spec['volumes']}
    src = vols['peer-token']['projected']['sources'][0]['serviceAccountToken']
    assert src == {'audience': 'peer-cluster', 'expirationSeconds': 600, 'path': 'token'}, (what, src)
    assert vols['long-token']['projected']['sources'][0]['serviceAccountToken']['expirationSeconds'] == 3600, what
    assert 'settings' in vols, what + ': chart volumes kept'
    mounts = {m['name']: m for m in spec['containers'][0]['volumeMounts']}
    assert mounts['peer-token'] == {'name': 'peer-token', 'mountPath': '/var/run/secrets/hangar/peer', 'readOnly': True}, (what, mounts)
    assert spec['serviceAccountName'] == 'guard-reader', what
assert sa['metadata']['name'] == 'guard-reader'
" || { echo "FAIL: serviceAccount.projectedTokens did not render a projected volume and mount on the Rollout and Job"; fail=1; }
helm template t . -f tests/fixtures/release-image.yaml | grep -q 'serviceAccountToken' && { echo "FAIL: a projected token rendered with no projectedTokens set"; fail=1; }
# rollout.maxSurge/maxUnavailable (canary): rendered when set, absent by default, both 0 and blueGreen refused.
ro surge-zero | grep -A3 '^    canary:' | grep -q 'maxSurge: 0' || { echo "FAIL: rollout.maxSurge 0 not rendered"; fail=1; }
ro surge-zero | grep -A4 '^    canary:' | grep -q 'maxUnavailable: 1' || { echo "FAIL: rollout.maxUnavailable not rendered"; fail=1; }
ro release-image | grep -qE 'maxSurge|maxUnavailable' && { echo "FAIL: maxSurge/maxUnavailable rendered by default"; fail=1; }
helm template t . -f tests/fixtures/surge-both-zero.yaml 2>&1 | grep -q 'cannot both be 0' || { echo "FAIL: maxSurge and maxUnavailable both 0 must fail the render"; fail=1; }
helm template t . -f tests/fixtures/surge-bluegreen.yaml 2>&1 | grep -q 'canary strategy only' || { echo "FAIL: maxSurge on blueGreen must fail the render"; fail=1; }
# Schema: the same fields validate (and a bad mountPath / percent string is refused) - airframe-validate, no render.
$V --no-render tests/validate/good-projected-token-surge.yaml >/dev/null 2>&1 || { echo "FAIL: validate rejected projectedTokens / rollout.maxSurge"; fail=1; }
out=$($V --no-render tests/validate/bad-projected-token.yaml 2>&1)
for p in /serviceAccount/projectedTokens/0/mountPath /serviceAccount/projectedTokens/0/expirationSeconds /rollout/maxSurge; do
  echo "$out" | grep -q "$p" || { echo "FAIL: validate did not reject $p"; fail=1; }
done
# observability: Prometheus admitted on the scrape port, OTel inject annotation for nodejs/java/python only, the
# OTLP egress rule only when egress is already restricted, and nothing at all when the keys are empty.
np() { helm template t . -f "tests/fixtures/$1.yaml" --show-only templates/networking/networkpolicy.yaml 2>&1; }
np observability-scrape | grep -B3 -A4 'kubernetes.io/metadata.name: observability' | grep -q 'port: http' || { echo "FAIL: observability.namespace did not admit Prometheus on the scrape port"; fail=1; }
expect_present observability-scrape ServiceMonitor
# The scrape is opt-in: apps send metrics over OTLP, and a scrape of an app with no /metrics is a target always down.
expect_absent  observability ServiceMonitor
np observability | grep -q 'kubernetes.io/metadata.name: observability' && { echo "FAIL: Prometheus admitted with the scrape off"; fail=1; }
np release-image | grep -q 'observability' && { echo "FAIL: observability rule rendered with no observability.namespace"; fail=1; }
ro observability | grep -q 'instrumentation.opentelemetry.io/inject-python: "observability/hangar"' || { echo "FAIL: inject-python annotation missing"; fail=1; }
ro observability | grep -q 'resource.opentelemetry.io/deployment.environment.name: "dev"' || { echo "FAIL: deployment.environment.name annotation missing"; fail=1; }
ro release-image | grep -q 'instrumentation.opentelemetry.io' && { echo "FAIL: inject annotation rendered with no observability keys"; fail=1; }
ro observability-go-egress | grep -q 'instrumentation.opentelemetry.io' && { echo "FAIL: go must not be injected"; fail=1; }
np observability | grep -q 'port: 4317' && { echo "FAIL: OTLP egress rule rendered while egress is open"; fail=1; }
np observability-egress | grep -q 'port: 4317' || { echo "FAIL: OTLP egress rule missing while egress is restricted"; fail=1; }
np observability-go-egress | grep -q 'port: 4317' && { echo "FAIL: OTLP egress rule rendered with nothing injected"; fail=1; }
[ $fail -eq 0 ] && echo "ok" || exit 1
