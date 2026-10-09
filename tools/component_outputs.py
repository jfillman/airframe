"""AF-3: the component outputs contract (the sidecar format itself is documented in tools/sidecars.py).

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
from pathlib import Path

import yaml

from sidecars import load_sidecars

ROOT = Path(__file__).resolve().parent.parent
XRDS = ROOT / "xrds"
GENERATED_PATH = ROOT / "charts" / "airframe-application" / "files" / "component-outputs.yaml"


def _public(d):
    return {k: v for k, v in d.items() if not k.startswith("_")}


def load_all(targets=False):
    """Components (role: component) by default; targets=True returns the cloud targets (role: target)
    instead. Every sidecar is validated on load (tools/sidecars.py). Other roles (bootstrap,
    environment, platform, observability) come from load_by_role()."""
    want = "target" if targets else "component"
    return {k: _public(d) for k, d in load_sidecars().items() if d["role"] == want}


def load_by_role(*roles):
    return {k: _public(d) for k, d in load_sidecars().items() if d["role"] in roles}


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
