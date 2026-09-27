"""AF-3: the component outputs contract.

Each component type with a real XRD documents what it produces in a sidecar meta file,
`xrds/<kind-lowercase-plural-or-singular-matching-the-xrd-file>.meta.yaml` (matches the XRD file's own
basename), keyed by output name: `literal` (a template string/number with `{name}`/`{namespace}`
placeholders), `secretKeyRef` (a Secret name template + key), or `configMapKeyRef` (same, for a
ConfigMap). Verified against each component's real Composition when written - see each meta file's own
header for the composition it was checked against.

load_all() -> {component type (lowercase): {"summary":..., "outputs": {name: {...}}, ...}}
gen_component_outputs_yaml() renders charts/airframe-application/files/component-outputs.yaml, the
chart-bundled copy `templates/_lib/fromcomponent.tpl` reads via `.Files.Get` to resolve `fromComponent`
- generated, not hand-copied, so the chart can't drift from these meta files.
"""
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
XRDS = ROOT / "xrds"
GENERATED_PATH = ROOT / "charts" / "airframe-application" / "files" / "component-outputs.yaml"

VALID_OUTPUT_KINDS = {"literal", "secretKeyRef", "configMapKeyRef"}


def load_all():
    out = {}
    for f in XRDS.glob("*.meta.yaml"):
        d = yaml.safe_load(f.read_text())
        kind = d["kind"].lower()
        for name, spec in d.get("outputs", {}).items():
            if spec.get("kind") not in VALID_OUTPUT_KINDS:
                raise ValueError(f"{f}: output '{name}' has invalid kind {spec.get('kind')!r}")
        out[kind] = d
    return out


def gen_component_outputs_yaml():
    """A flat, chart-friendly rendering: {type: {output: {...}}}, no summary/verify prose (that stays
    only in the meta files themselves, for humans/agents reading xrds/, not for the chart)."""
    all_meta = load_all()
    flat = {kind: d.get("outputs", {}) for kind, d in all_meta.items()}
    GENERATED_PATH.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# GENERATED FILE - do not hand-edit. Source: xrds/*.meta.yaml (AF-3).\n"
        "# Regenerate with: python3 tools/gen_component_outputs.py\n"
    )
    GENERATED_PATH.write_text(header + yaml.safe_dump(flat, sort_keys=True, default_flow_style=False))


def known_outputs(kind):
    all_meta = load_all()
    d = all_meta.get(kind.lower())
    return set((d or {}).get("outputs", {}))
