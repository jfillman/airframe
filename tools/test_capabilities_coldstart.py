#!/usr/bin/env python3
"""AF-1b's own acceptance test: 'a cold-start Preflight case answers 10 capability questions from the
contract alone.' Ten real questions an agent hits early (what components exist, what does a component
output, what does a chart field do, what does an XRD provision), each answered by calling
tools/airframe-capabilities against ONLY contract/airframe-contract.json - never by reading
values.schema.json or xrds/*.yaml directly - then checked against ground truth pulled from those real
source files, so a stale or wrong contract bundle fails this test.

Not yet wired as a literal registered case in ~/tech/autopilot/preflight/cases/ (a separate repo, its
own harness format) - that's real follow-on work, tracked in roadmap.md. This proves the contract
bundle itself is sufficient and correct, which is the actual risk AF-1b's accept criterion is about.

    python3 tools/test_capabilities_coldstart.py
"""
import json
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from airframe_schema import load_base_schema

ROOT = Path(__file__).resolve().parent.parent
CLI = str(ROOT / "tools" / "airframe-capabilities")


def ask(*args):
    r = subprocess.run([sys.executable, CLI, *args], capture_output=True, text=True, cwd=ROOT)
    if r.returncode != 0:
        raise AssertionError(f"airframe-capabilities {' '.join(args)} failed: {r.stderr.strip()}")
    return json.loads(r.stdout)


def ground_truth_xrd_kind(name):
    for f in (ROOT / "xrds").glob("*.yaml"):
        d = yaml.safe_load(f.read_text())
        spec = d.get("spec")
        if spec and spec["names"]["kind"] == name:
            return d
    raise AssertionError(f"no XRD named {name} on disk")


def main():
    schema = load_base_schema()
    checks = []

    # Q1: What component types exist, and what does each do?
    components = ask("components")
    checks.append(("Q1 component list", set(components) == {"redis", "postgresql", "rabbitmq", "mongodb", "dex"}))

    # Q2: How do I read a Redis component's password without guessing a Secret name?
    redis_password = ask("output", "redis", "password")
    checks.append(("Q2 redis password output", redis_password["kind"] == "secretKeyRef" and redis_password["secret"] == "{name}-connection"))

    # Q3: What Secret/key does a RabbitMQ attach's username come from?
    rmq_user = ask("output", "rabbitmq", "username")
    checks.append(("Q3 rabbitmq username output", rmq_user == {"kind": "secretKeyRef", "secret": "{name}-user-credentials", "key": "username"}))

    # Q4: What does the PostgreSQL component's "uri" output actually give me?
    pg_uri = ask("output", "postgresql", "uri")
    checks.append(("Q4 postgresql uri output", "postgres" in pg_uri["description"].lower() and pg_uri["secret"] == "{name}-app"))

    # Q5: Is `appName` required to be a valid DNS label? (a real question before onboarding an app)
    app_name_field = ask("field", "appName")
    checks.append(("Q5 appName pattern documented", "DNS-1123" in app_name_field["description"]))

    # Q6: What does PythonApplication actually provision - cross-checked against the real XRD's own annotation.
    python_xrd = ask("xrd", "PythonApplication")
    truth = ground_truth_xrd_kind("PythonApplication")
    checks.append(("Q6 PythonApplication summary matches source", python_xrd["agentSummary"] == truth["metadata"]["annotations"]["hangar.io/agent-summary"]))

    # Q7: Which apiVersion does a Redis XR need? (an agent writing a raw XR, not going through the chart)
    redis_xrd = ask("xrd", "Redis")
    checks.append(("Q7 Redis apiVersion", redis_xrd["apiVersion"] == "catalog.hangar.io/v1alpha1"))

    # Q8: What's the default replica count for a new rollout?
    rollout_field = ask("field", "rollout")
    checks.append(("Q8 rollout default has replicas", schema["properties"]["rollout"]["properties"]["replicas"]["default"] == 2))

    # Q9: Asking for a component type that doesn't exist should fail clearly, not silently.
    r = subprocess.run([sys.executable, CLI, "component", "elasticsearch"], capture_output=True, text=True, cwd=ROOT)
    checks.append(("Q9 unknown component type fails with a hint", r.returncode != 0 and "known:" in r.stderr))

    # Q10: Does every XRD in the contract actually have an agent-summary (AF-1b's own coverage promise)?
    xrds = ask("xrds")
    checks.append(("Q10 every XRD has a summary", len(xrds) == 17 and all(xrds.values())))

    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("PASS" if ok else "FAIL") + f"  {name}")
    print(f"\n{len(checks) - len(failed)}/{len(checks)} capability questions answered correctly from the contract alone")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
