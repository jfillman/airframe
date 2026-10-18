#!/usr/bin/env python3
"""The AppSpec contract (contract/appspec.schema.json) is a real Draft 2020-12 schema, accepts every
example in contract/examples/, rejects a mutation set, names only stacks that have a Bootstrap-tier XRD
here, and its config block is exactly the chart's human-owned values (no more, no less).

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
EXAMPLES = {f.name: yaml.safe_load(f.read_text()) for f in sorted((ROOT / "contract" / "examples").glob("*.appspec.yaml"))}
EXAMPLE = EXAMPLES["parachute.appspec.yaml"]
CHART_SCHEMA = json.loads((ROOT / "charts" / "airframe-application" / "values.schema.json").read_text())

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
        m("env without name", lambda d: d["config"]["env"][0].pop("name")),
        m("unknown env key", lambda d: d["config"]["env"][0].__setitem__("vaule", "x")),
        # config is the chart's values: its own strictness and types apply
        m("chart typo in config", lambda d: d["config"].__setitem__("autoscalling", {"enabled": True})),
        m("chart type error", lambda d: d["config"].__setitem__("autoscaling", {"enabled": "yes"})),
        m("chart conditional (route without hostnames)",
          lambda d: d["config"].__setitem__("httpRoute", {"enabled": True, "parentRefs": [{"name": "hangar"}]})),
        m("bad component spec", lambda d: d["config"].__setitem__("components", [{"type": "redis", "name": "c", "spec": {"sise": "x"}}])),
        # platform- and release-owned chart keys are not an AppSpec's to set
        m("platform-owned key (cluster)", lambda d: d["config"].__setitem__("cluster", "example-prod")),
        m("platform-owned key (envName)", lambda d: d["config"].__setitem__("envName", "prod")),
        m("release-owned key (release)", lambda d: d["config"].__setitem__("release", {"image": {"tag": "x"}})),
        m("image outside a release (rollout.image)",
          lambda d: d["config"]["rollout"].__setitem__("image", {"repository": "ghcr.io/x/y", "tag": "1"})),
        m("AppSpec-decided key (appType)", lambda d: d["config"].__setitem__("appType", "infra")),
        # overrides are validated like config
        m("chart typo in an override", lambda d: d.__setitem__("overrides", {"prod": {"replcas": 3}})),
        m("bad override env name", lambda d: d.__setitem__("overrides", {"Prod": {}})),
    ]


def main():
    failures = []
    Draft202012Validator.check_schema(SCHEMA)
    v = Draft202012Validator(SCHEMA)

    for name, doc in EXAMPLES.items():
        errs = [f"{'/'.join(map(str, e.absolute_path))}: {e.message}" for e in v.iter_errors(doc)]
        if errs:
            failures.append(f"example {name} rejected: {errs}")

    # config's keys are exactly the chart's human-owned keys, less the ones the AppSpec itself decides
    human = {k for k, n in CHART_SCHEMA["properties"].items() if n.get("x-hangar-owner") == "human"}
    settable = set(SCHEMA["$defs"]["chartValues"]["properties"])
    if settable != human - {"appType"}:
        failures.append(f"config keys != the chart's human-owned keys: extra {sorted(settable - human)}, "
                        f"missing {sorted(human - {'appType'} - settable)}")

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
    print(f"ok: AppSpec schema valid; {len(EXAMPLES)} examples accepted; {len(mutations())} mutations rejected; "
          f"config = {len(settable)} human-owned chart keys; {len(stacks)} stacks map to XRDs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
