#!/usr/bin/env python3
"""The AppSpec contract (contract/appspec.schema.json) is a real Draft 2020-12 schema, accepts the
parachute example, rejects a mutation set, and names only stacks that have a Bootstrap-tier XRD here.

The schema is owned here because AppSpec is `apiVersion: airframe/v1`: it describes an Airframe app.
The autopilot repo's planner vendors a byte-identical copy (schemas/appspec.schema.json) and its own
test fails when the two drift.
    python3 tools/test_appspec_schema.py
"""
import copy
import json
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "contract" / "appspec.schema.json").read_text())
EXAMPLE = yaml.safe_load((ROOT / "contract" / "examples" / "parachute.appspec.yaml").read_text())

# AppSpec.stack -> the Bootstrap-tier XRD kind that scaffolds it.
STACK_KINDS = {
    "nodejs": "NodeJSApplication",
    "springboot": "SpringBootApplication",
    "go": "GoApplication",
    "python": "PythonApplication",
}


def mutations():
    def m(desc, fn):
        doc = copy.deepcopy(EXAMPLE)
        fn(doc)
        return desc, doc

    return [
        m("unknown top-level key", lambda d: d.__setitem__("enviroments", d["environments"])),
        m("unknown stack", lambda d: d.__setitem__("stack", "ruby")),
        m("wrong apiVersion", lambda d: d.__setitem__("apiVersion", "airframe/v2")),
        m("missing ground", lambda d: d["environments"].pop("ground")),
        m("empty ground", lambda d: d["environments"].__setitem__("ground", [])),
        m("bad app name", lambda d: d.__setitem__("app", "Parachute")),
        m("unknown flight key", lambda d: d["environments"]["flight"][0].__setitem__("clster", "x")),
        m("rollout typo", lambda d: d["config"].__setitem__("rolout", {})),
        m("unknown strategy", lambda d: d["config"]["rollout"].__setitem__("strategy", "linear")),
        m("env without value", lambda d: d["config"]["env"][0].pop("value")),
        m("bad env name", lambda d: d["config"]["env"][0].__setitem__("name", "1URL")),
    ]


def main():
    failures = []
    Draft202012Validator.check_schema(SCHEMA)
    v = Draft202012Validator(SCHEMA)

    errs = [e.message for e in v.iter_errors(EXAMPLE)]
    if errs:
        failures.append(f"parachute example rejected: {errs}")

    for desc, doc in mutations():
        if v.is_valid(doc):
            failures.append(f"mutation accepted: {desc}")

    kinds = set()
    for f in sorted((ROOT / "xrds").glob("*.yaml")):
        if f.name.endswith(".meta.yaml"):
            continue
        for d in yaml.safe_load_all(f.read_text()):
            if isinstance(d, dict) and d.get("kind") == "CompositeResourceDefinition":
                kinds.add(d["spec"]["names"]["kind"])
    stacks = SCHEMA["properties"]["stack"]["enum"]
    for s in stacks:
        if STACK_KINDS.get(s) not in kinds:
            failures.append(f"stack {s!r} has no Bootstrap-tier XRD (expected {STACK_KINDS.get(s)})")

    for f in failures:
        print(f"FAIL: {f}")
    if failures:
        return 1
    print(f"ok: AppSpec schema valid; parachute accepted; {len(mutations())} mutations rejected; "
          f"{len(stacks)} stacks map to XRDs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
