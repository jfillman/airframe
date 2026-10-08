"""AF-1b: the contract bundle. One generated JSON artifact, contract/airframe-contract.json, that
answers "what can I do with Airframe" without reading any source file - the chart schema, every XRD's
shape and summary, and every component's real outputs, all in one place, all derived from the same
files the chart/validator themselves use (values.schema.json, xrds/*.yaml, xrds/*.meta.yaml). Nothing
here is hand-copied: regenerate with tools/gen_contract.py whenever any of those sources changes.
"""
import json
from pathlib import Path

import yaml

from airframe_schema import load_base_schema
from component_outputs import load_all as load_component_meta

ROOT = Path(__file__).resolve().parent.parent
XRDS = ROOT / "xrds"
CONTRACT_PATH = ROOT / "contract" / "airframe-contract.json"


def _describe_node(node):
    """A compact {type, description, default, enum} summary for one schema node - enough for an
    agent to know what a field is without pulling the whole schema tree."""
    out = {}
    if "type" in node:
        out["type"] = node["type"]
    if node.get("description"):
        out["description"] = node["description"]
    if "default" in node:
        out["default"] = node["default"]
    if node.get("enum"):
        out["enum"] = node["enum"]
    return out


def chart_fields():
    """Every top-level values.schema.json field, compact."""
    schema = load_base_schema()
    return {name: _describe_node(node) for name, node in schema["properties"].items()}


def xrd_summaries():
    """kind -> {group, apiVersion, plural, agentSummary, fieldsDescribed, fieldsTotal}, for every
    real XRD in xrds/*.yaml (not the *.meta.yaml sidecars)."""
    out = {}
    for f in sorted(XRDS.glob("*.yaml")):
        d = yaml.safe_load(f.read_text())
        spec = d.get("spec")
        if not spec or "versions" not in spec:
            continue
        kind = spec["names"]["kind"]
        version = spec["versions"][0]
        schema_spec = version["schema"]["openAPIV3Schema"]["properties"].get("spec", {})
        described = total = 0

        def walk(n):
            nonlocal described, total
            if isinstance(n, dict):
                if "type" in n or "$ref" in n:
                    total += 1
                    if n.get("description"):
                        described += 1
                for k, v in n.items():
                    if k == "properties":
                        for cv in v.values():
                            walk(cv)
                    elif k == "items":
                        walk(v)
        walk(schema_spec)
        out[kind] = {
            "group": spec["group"],
            "apiVersion": f"{spec['group']}/{version['name']}",
            "plural": spec["names"]["plural"],
            "agentSummary": (d.get("metadata", {}).get("annotations", {}) or {}).get("hangar.io/agent-summary"),
            "fieldsDescribed": described,
            "fieldsTotal": total,
            "file": f.name,
        }
    return out


def component_contracts():
    """component type -> {summary, outputs, verify, owner}, from xrds/*.meta.yaml."""
    return load_component_meta()


def target_contracts():
    """cloud target type -> {summary, conditions, verify, owner}, from the xrds/*.meta.yaml sidecars
    marked `component: false` (AwsLambdaTarget, AwsEcsTarget, AzureContainerAppTarget): what an agent
    needs to stand one up and tell whether it worked, without reading the XRD or the Composition."""
    return {k: {kk: vv for kk, vv in v.items() if kk != "outputs"} for k, v in load_component_meta(targets=True).items()}


def build_contract():
    return {
        "$schema": "airframe-contract/v1",
        "generated_by": "tools/gen_contract.py",
        "chart": {
            "name": "airframe-application",
            "fields": chart_fields(),
        },
        "xrds": xrd_summaries(),
        "components": component_contracts(),
        "targets": target_contracts(),
    }


def write_contract():
    CONTRACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONTRACT_PATH.write_text(json.dumps(build_contract(), indent=2, sort_keys=True) + "\n")
