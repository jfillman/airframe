#!/usr/bin/env python3
"""airframe-validate --xr: the XR write path rejects typos (review finding A2).

A misspelled field in an XR request is pruned silently by the API server (client-side apply, no strict
field validation from Argo CD), so the tenants repo needs the check before merge. This proves the mode
against (1) the real XR examples the compositions ship, (2) every live XR request in the tenants repos
when they are checked out, and (3) a mutation set: every mutation MUST be rejected with the rule and
the hint the docstring promises.
    python3 tools/test_xr_validate.py
"""
import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
TECH = ROOT.parent
TENANT_REPOS = [TECH / "gitops-cluster-dev-tenants", TECH / "gitops-cluster-kind-prod-tenants"]

GOOD = {
    "apiVersion": "catalog.hangar.io/v1alpha1", "kind": "ApplicationEnvironment",
    "metadata": {"name": "parachute-kind-prod-staging", "namespace": "app-parachute-cicd"},
    "spec": {"appName": "parachute", "cluster": "kind-prod", "env": "staging", "configMapGenerator": False},
}


def run(files, fmt="json"):
    r = subprocess.run([sys.executable, str(TOOLS / "airframe-validate"), "--xr", "--format", fmt, *map(str, files)],
                       capture_output=True, text=True)
    return r.returncode, (json.loads(r.stdout) if fmt == "json" else r.stdout)


def check_doc(doc):
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        yaml.safe_dump(doc, f)
    code, out = run([f.name])
    return code, out[0]["problems"]


def mutations():
    out = []
    d = copy.deepcopy(GOOD); d["spec"]["configMapGenerater"] = True
    out.append(("misspelled key", d, "AF-SCHEMA-001", "did you mean 'configMapGenerator'?"))
    d = copy.deepcopy(GOOD); d["spec"]["replicas"] = 3
    out.append(("unknown key, no close match", d, "AF-SCHEMA-001", "no such field"))
    d = copy.deepcopy(GOOD); d["spec"]["configMapGenerator"] = "yes"
    out.append(("wrong type", d, "AF-SCHEMA-002", "xrds/applicationenvironment.yaml"))
    d = copy.deepcopy(GOOD); d["apiVersion"] = "catalog.idp.io/v1alpha1"
    out.append(("retired group", d, "AF-XR-001", "renamed to catalog.hangar.io"))
    d = copy.deepcopy(GOOD); d["kind"] = "ApplicationEnviroment"
    out.append(("misspelled kind", d, "AF-XR-002", "did you mean 'ApplicationEnvironment'?"))
    d = copy.deepcopy(GOOD); del d["metadata"]["name"]
    out.append(("no name", d, "AF-XR-003", "metadata.name"))
    d = copy.deepcopy(GOOD); del d["spec"]["appName"]
    out.append(("missing required", d, "AF-SCHEMA-002", "xrds/applicationenvironment.yaml"))
    d = copy.deepcopy(GOOD); d["spec"]["crossplane"] = {"compositionUpdatePolcy": "Automatic"}
    out.append(("typo inside the Crossplane block", d, "AF-SCHEMA-001", "did you mean 'compositionUpdatePolicy'?"))
    d = {"apiVersion": "catalog.hangar.io/v1alpha1", "kind": "AwsLambdaTarget",
         "metadata": {"name": "f", "namespace": "app-f-cicd"},
         "spec": {"functionName": "glidepath-f", "region": "us-east-1", "architecture": "arm", "runtime": "nodejs22"}}
    out.append(("enum violation on a target", d, "AF-SCHEMA-002", "xrds/awslambdatarget.yaml"))
    return out


def main():
    failures = []
    # 1. a good document is ok, with and without the spec.crossplane block Crossplane adds to every XR
    code, problems = check_doc(GOOD)
    if code != 0 or problems:
        failures.append(f"GOOD rejected: {problems}")
    with_xp = copy.deepcopy(GOOD); with_xp["spec"]["crossplane"] = {"compositionUpdatePolicy": "Automatic", "compositionRef": {"name": "x"}}
    code, problems = check_doc(with_xp)
    if code != 0 or problems:
        failures.append(f"spec.crossplane rejected (the scaffolder writes it): {problems}")
    # 2. every mutation is rejected with the promised rule and hint
    for label, doc, rule, hint in mutations():
        code, problems = check_doc(doc)
        rules = {p["rule"] for p in problems}
        hints = " ".join(p["hint"] + " " + p["message"] for p in problems)
        if code == 0 or rule not in rules or hint not in hints:
            failures.append(f"{label}: expected {rule} with {hint!r}, got {problems}")
    # 2b. a missing namespace is a warning, not an error: the xr-requests Application supplies it
    d = copy.deepcopy(GOOD); del d["metadata"]["namespace"]
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        yaml.safe_dump(d, f)
    code, out = run([f.name])
    if code != 0 or out[0]["problems"] or [w["rule"] for w in out[0]["warnings"]] != ["AF-XR-004"]:
        failures.append(f"missing namespace should be the AF-XR-004 warning only, got {out[0]}")
    # 3. the compositions' own XR examples are valid
    examples = sorted(ROOT.glob("compositions/*/example/xr-*.yaml"))
    if examples:
        code, out = run(examples)
        bad = [o for o in out if not o["valid"]]
        if bad:
            failures.append("composition examples rejected: " + json.dumps(bad, indent=1)[:800])
    # 4. the live fleet's XR requests are valid (only when the repos are checked out)
    fleet = [p for repo in TENANT_REPOS if repo.exists() for p in sorted(repo.glob("tenants/*/xr-requests/*.yaml"))]
    if fleet:
        code, out = run(fleet)
        bad = [o for o in out if not o["valid"]]
        if bad:
            failures.append("live XR requests rejected: " + json.dumps(bad, indent=1)[:1200])
    n_mut = len(mutations())
    if failures:
        print("\n".join(failures))
        print(f"\nFAIL: {len(failures)} problem(s)")
        return 1
    print(f"ok: 1 good document accepted, {n_mut}/{n_mut} mutations rejected with the right rule and hint, "
          f"{len(examples)} composition examples valid, {len(fleet)} live XR requests valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
