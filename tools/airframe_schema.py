"""AF-2: the compiled schema and the values.yaml generator.

values.schema.json (charts/airframe-application/values.schema.json) is the ONE hand-authored
source: shape, defaults and descriptions. Everything else is derived from it plus the XRDs:

- compiled_schema(): the base schema with a discriminated union spliced into components[].items
  for every component type that has a real XRD (redis, postgresql, rabbitmq today), generated
  fresh from xrds/*.yaml every call - never hand-copied, so it can't drift from the XRD.
  additionalProperties:false is already baked into the base schema by hand (AF-2's "one source"
  means no second runtime strictify() pass; this module only ADDS the component arms, it never
  loosens or tightens anything the base schema already says).
- generate_values_yaml(): walks the base schema's own properties/defaults/descriptions and
  emits values.yaml text. Run via `python3 tools/gen_airframe_schema.py --write-values` (or
  --check, for CI) - never hand-edit values.yaml.
"""
import copy
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CHART = ROOT / "charts" / "airframe-application"
SCHEMA_PATH = CHART / "values.schema.json"
VALUES_PATH = CHART / "values.yaml"


def load_base_schema():
    return json.loads(SCHEMA_PATH.read_text())


def _strict_copy(node):
    """additionalProperties:false on every object that lists properties and doesn't already say
    otherwise - used only for a component's spec sub-schema, pulled fresh from its XRD."""
    node = copy.deepcopy(node)

    def go(n):
        if isinstance(n, dict):
            if isinstance(n.get("properties"), dict) and "additionalProperties" not in n \
                    and "patternProperties" not in n:
                n["additionalProperties"] = False
            for v in n.values():
                go(v)
        elif isinstance(n, list):
            for v in n:
                go(v)
    go(node)
    return node


def component_arms():
    """component `type` (lowercase kind) -> strict spec schema, read fresh from xrds/*.yaml."""
    out = {}
    for f in (ROOT / "xrds").glob("*.yaml"):
        d = yaml.safe_load(f.read_text())
        kind = d.get("spec", {}).get("names", {}).get("kind")
        versions = d.get("spec", {}).get("versions")
        if not kind or not versions:
            continue
        props = versions[0]["schema"]["openAPIV3Schema"]["properties"].get("spec")
        if not isinstance(props, dict) or "properties" not in props:
            continue
        spec = _strict_copy(props)
        # environmentRef is stamped by airframe-application's own components.yaml renderer -
        # a developer never writes it in a components[] entry's spec, so it's dropped from the
        # arm a real values file is validated against (it stays real and required in the XRD
        # itself, which the rendered XR is validated against separately).
        spec["properties"].pop("environmentRef", None)
        if "required" in spec:
            spec["required"] = [r for r in spec["required"] if r != "environmentRef"]
        out[kind.lower()] = spec
    return out


def compiled_schema():
    """The base schema with components[].items given a discriminated union on `type`, one arm
    per component that has a real XRD. Unlisted types keep the base schema's loose `spec`
    (their contract doesn't exist yet - see componentKinds' own description)."""
    schema = load_base_schema()
    arms = component_arms()
    item = schema["properties"]["components"]["items"]
    item["allOf"] = [
        {
            "if": {"properties": {"type": {"const": kind}}},
            "then": {"properties": {"spec": spec}},
        }
        for kind, spec in sorted(arms.items())
    ]
    return schema


VALUES_HEADER = """\
# airframe-application default values.
#
# GENERATED FILE - do not hand-edit. Source of truth: values.schema.json (AF-2).
# Regenerate with: python3 tools/gen_airframe_schema.py --write-values
# CI runs the same generator with --check and fails if this file would change.
"""


def _yaml_scalar(value):
    text = yaml.safe_dump(value, default_flow_style=True, width=10**9)
    text = text.strip()
    if text.endswith("..."):
        text = text[:-3].strip()
    return text or "null"


DEFINITIONS_CACHE = {}


def _resolve(node, schema):
    if "$ref" in node:
        ref = node["$ref"]
        assert ref.startswith("#/definitions/"), ref
        return schema["definitions"][ref.split("/")[-1]]
    return node


def _types(node):
    t = node.get("type")
    if t is None:
        return set()
    return {t} if isinstance(t, str) else set(t)


def _emit(lines, name, node, indent, schema):
    node = _resolve(node, schema)
    pad = "  " * indent
    desc = node.get("description")
    if desc:
        for chunk in _wrap(desc):
            lines.append(f"{pad}# {chunk}")
    types = _types(node)
    has_default = "default" in node
    default = node.get("default")

    if "properties" in node and not has_default:
        # An object with declared sub-fields and no fixed default of its own: build the
        # default from its children's own defaults, recursively.
        lines.append(f"{pad}{name}:")
        for child_name, child in node["properties"].items():
            _emit(lines, child_name, child, indent + 1, schema)
        return

    if has_default:
        lines.append(f"{pad}{name}: {_yaml_scalar(default)}")
        return

    # No default declared anywhere: fall back by JSON type, never guess null for an
    # object/array/string just because it wasn't spelled out (that changes chart behavior).
    if "object" in types:
        lines.append(f"{pad}{name}: {{}}")
    elif "array" in types:
        lines.append(f"{pad}{name}: []")
    elif "string" in types:
        lines.append(f"{pad}{name}: ''")
    elif "boolean" in types:
        lines.append(f"{pad}{name}: false")
    else:
        lines.append(f"{pad}{name}: null")


def _wrap(text, width=100):
    words = text.split()
    out, cur = [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            out.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        out.append(cur)
    return out


def generate_values_yaml(schema=None):
    schema = schema or load_base_schema()
    lines = [VALUES_HEADER.rstrip("\n")]
    for name, node in schema["properties"].items():
        lines.append("")
        _emit(lines, name, node, 0, schema)
    return "\n".join(lines) + "\n"


def description_coverage(schema=None):
    """(described, total) node count, walking every properties/items dict in the schema."""
    schema = schema or load_base_schema()
    described = total = 0

    def go(n):
        nonlocal described, total
        if isinstance(n, dict):
            if "type" in n or "properties" in n or "$ref" in n:
                total += 1
                if n.get("description"):
                    described += 1
            for k, v in n.items():
                if k in ("properties", "definitions"):
                    for cv in v.values():
                        go(cv)
                elif k == "items":
                    go(v)
                elif k in ("if", "then", "allOf"):
                    pass  # discriminator/conditional scaffolding, not a value node
        elif isinstance(n, list):
            for v in n:
                go(v)
    go(schema)
    return described, total
