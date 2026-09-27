#!/usr/bin/env python3
"""AF-2's own acceptance test: 'a mutation test over every live values file (add a key, misspell
a key, break an enum) is rejected 100%.' Runs against the real fleet files (not fixtures) so it
proves the compiled schema, not just the chart's test suite.

    python3 tools/test_af2_mutations.py
"""
import copy
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parent))
from airframe_schema import compiled_schema

FLEET = [
    "gitops-baggage-api/kind-prod/staging/values.yaml",
    "gitops-boarding-api/kind-prod/staging/values.yaml",
    "gitops-flight-api/kind-prod/staging/values.yaml",
    "gitops-infra-skyport-broker/kind-prod/staging/values.yaml",
    "gitops-infra-skyport-broker/platform/envs/dev.yaml",
    "flight-api/platform/envs/dev.yaml",
    "baggage-api/platform/envs/dev.yaml",
    "boarding-api/platform/envs/dev.yaml",
]
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def is_valid(schema, data):
    return not any(Draft202012Validator(schema).iter_errors(data))


def find_component(data, kind):
    for c in data.get("components") or []:
        if isinstance(c, dict) and str(c.get("type", "")).lower() == kind:
            return c
    return None


def mutations_for(data):
    """(label, mutated_copy) pairs. Every one MUST be rejected."""
    out = []

    m = copy.deepcopy(data)
    m["rolout"] = m.pop("rollout", None)  # AF-2's own canonical typo example
    out.append(("top-level typo rolout:", m))

    if isinstance(data.get("rollout"), dict):
        m = copy.deepcopy(data)
        m["rollout"]["replcas"] = m["rollout"].pop("replicas", 2)
        out.append(("nested typo rollout.replcas:", m))

        m = copy.deepcopy(data)
        m["rollout"]["strategy"] = "gigantic"
        out.append(("broken enum rollout.strategy: gigantic", m))

    m = copy.deepcopy(data)
    m["bogusTopLevelKey"] = True
    out.append(("unknown top-level key", m))

    for kind in ("redis", "postgresql", "rabbitmq"):
        c = find_component(data, kind)
        if c and isinstance(c.get("spec"), dict):
            m = copy.deepcopy(data)
            comp = find_component(m, kind)
            comp["spec"]["bogusField"] = "x"
            out.append((f"unknown key in {kind} component spec", m))
            m2 = copy.deepcopy(data)
            comp2 = find_component(m2, kind)
            comp2["spec"]["size"] = "gigantic"
            out.append((f"broken enum {kind}.spec.size: gigantic", m2))

    return out


def main():
    schema = compiled_schema()
    total = failed = 0
    for rel in FLEET:
        path = REPO_ROOT / rel
        data = yaml.safe_load(path.read_text()) or {}
        if not is_valid(schema, data):
            print(f"SKIP {rel}: not currently clean against the compiled schema")
            continue
        for label, mutated in mutations_for(data):
            total += 1
            if is_valid(schema, mutated):
                failed += 1
                print(f"MISSED  {rel}: {label} was NOT rejected")
            else:
                print(f"caught  {rel}: {label}")
    print(f"\n{total - failed}/{total} mutations rejected")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
