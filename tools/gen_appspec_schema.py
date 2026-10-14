#!/usr/bin/env python3
"""AppSpec's config block IS the chart's values contract.

contract/appspec.schema.json is hand-authored except for `$defs.chartValues` and the `$defs.chart.*`
definitions it references. Those are generated here from compiled_schema() (values.schema.json plus
the components[] union from the XRDs - the same schema airframe-validate enforces), so an AppSpec can
set anything a human may set in an environment's values file, and nothing else:

- every top-level chart key whose x-hangar-owner is `human` is in, with its x-hangar-risk kept as an
  annotation so the planner and Clearance can gate on it;
- platform-owned keys (appName, cluster, envName, ...) and release-owned keys (release,
  releaseTracking) are out: the platform or the release pipeline writes them, never an AppSpec;
- APPSPEC_DECIDES are human-owned in the chart but fixed by the AppSpec itself;
- RELEASE_ONLY are nested fields of a human-owned key that only the release pipeline may write.

    tools/gen_appspec_schema.py            regenerate contract/appspec.schema.json in place
    tools/gen_appspec_schema.py --check    exit 1 if it would change (CI)
"""
import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from airframe_schema import compiled_schema

ROOT = Path(__file__).resolve().parent.parent
APPSPEC_PATH = ROOT / "contract" / "appspec.schema.json"

# Human-owned in the chart, but an AppSpec always describes an app workload: `appType: infra` would
# scaffold a stack and then render no Rollout for it.
APPSPEC_DECIDES = {"appType": "an AppSpec always describes an app workload; its stack decides this"}
# rollout.image is the deprecated pre-release-file image location: an image set in an AppSpec would
# deploy around the release pipeline (and its digest pin and guardrails). Images come from releases.
RELEASE_ONLY = {("rollout", "image")}
DEF_PREFIX = "chart."


def _rewrite_refs(node):
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if k == "$ref" and isinstance(v, str) and v.startswith("#/definitions/"):
                out[k] = "#/$defs/" + DEF_PREFIX + v.split("/")[-1]
            else:
                out[k] = _rewrite_refs(v)
        return out
    if isinstance(node, list):
        return [_rewrite_refs(v) for v in node]
    return node


def _refs(node, found):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "$ref" and isinstance(v, str):
                found.add(v)
            else:
                _refs(v, found)
    elif isinstance(node, list):
        for v in node:
            _refs(v, found)
    return found


def chart_defs():
    """{"chartValues": ..., "chart.<definition>": ...} for the AppSpec's $defs."""
    chart = compiled_schema()
    props = {}
    for key, node in chart["properties"].items():
        if node.get("x-hangar-owner") != "human" or key in APPSPEC_DECIDES:
            continue
        props[key] = _rewrite_refs(copy.deepcopy(node))
        for parent, child in RELEASE_ONLY:
            if parent == key:
                props[key]["properties"].pop(child, None)
    out = {"chartValues": {
        "type": "object",
        "additionalProperties": False,
        "description": "The airframe-application chart's values that a person may set, generated from "
                       "charts/airframe-application/values.schema.json (every top-level key with "
                       "x-hangar-owner: human). Platform- and release-owned keys are not settable here.",
        "properties": props,
    }}
    used = {r.split("/")[-1][len(DEF_PREFIX):] for r in _refs(props, set()) if r.startswith("#/$defs/" + DEF_PREFIX)}
    for name in sorted(used):
        out[DEF_PREFIX + name] = _rewrite_refs(copy.deepcopy(chart["definitions"][name]))
    return out


def render(current: dict) -> str:
    schema = copy.deepcopy(current)
    defs = {k: v for k, v in (schema.get("$defs") or {}).items()
            if k != "chartValues" and not k.startswith(DEF_PREFIX)}
    defs.update(chart_defs())
    schema["$defs"] = defs
    return json.dumps(schema, indent=2) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    current = APPSPEC_PATH.read_text()
    rendered = render(json.loads(current))
    if a.check:
        if current != rendered:
            print("FAIL: contract/appspec.schema.json's chart $defs are stale - run tools/gen_appspec_schema.py and commit the result")
            return 1
        print("ok: contract/appspec.schema.json's chart $defs match values.schema.json")
        return 0
    APPSPEC_PATH.write_text(rendered)
    print(f"wrote {APPSPEC_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
