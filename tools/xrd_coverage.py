#!/usr/bin/env python3
"""XRD-level OpenAPI schema description coverage (AF-2's M1 exit-bar follow-on: the strict
chart schema went 5% -> 100% described, but the XRD layer itself - the schema an XR's own author
fills in, not the chart's values.yaml - was never swept and stayed at the M0 baseline.

Usage:
    tools/xrd_coverage.py --coverage           print described/total across all XRDs
    tools/xrd_coverage.py --list-missing        print every undescribed field, file by file
"""
import argparse
import pathlib
import sys

import yaml

XRDS_DIR = pathlib.Path(__file__).resolve().parent.parent / "xrds"


def _walk(node, path, missing):
    """Same traversal airframe_schema.py's description_coverage() uses for the chart schema -
    ported here rather than imported, since that function is hardwired to the chart's single
    values.schema.json (load_base_schema()) and this needs to run over N separate XRD files.

    Excludes two structural nodes every single XRD shares, the same way that function's own
    if/then/allOf exclusion skips "conditional scaffolding, not a value node": the bare root
    openAPIV3Schema object (path "") and the top-level `spec` wrapper immediately under it (path
    "spec") - every XRD's `spec` is just "this resource's spec", self-evident from Kubernetes'
    own convention, not a real field a human fills in. Describing it 14 times over would be
    boilerplate, not information - real coverage is about the fields INSIDE spec/status.
    """
    described = total = 0
    if isinstance(node, dict):
        if ("type" in node or "properties" in node or "$ref" in node) and path not in ("", "spec"):
            total += 1
            if node.get("description"):
                described += 1
            elif missing is not None:
                missing.append(path)
        for k, v in node.items():
            if k == "properties":
                for name, cv in v.items():
                    d, t = _walk(cv, f"{path}/{name}" if path else name, missing)
                    described += d
                    total += t
            elif k == "items":
                d, t = _walk(v, f"{path}[]", missing)
                described += d
                total += t
            # x-kubernetes-preserve-unknown-fields / additionalProperties schemas (e.g.
            # RepositoryFile's free-form spec) are deliberately not walked - they document that
            # they're intentionally open-ended, not a field this sweep should demand a
            # description for.
    elif isinstance(node, list):
        for v in node:
            d, t = _walk(v, path, missing)
            described += d
            total += t
    return described, total


def xrd_files():
    return sorted(p for p in XRDS_DIR.glob("*.yaml"))


def coverage_for(path, missing=None):
    doc = yaml.safe_load(path.read_text())
    described = total = 0
    for version in doc.get("spec", {}).get("versions", []):
        schema = version.get("schema", {}).get("openAPIV3Schema", {})
        d, t = _walk(schema, "", missing)
        described += d
        total += t
    return described, total


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--coverage", action="store_true")
    ap.add_argument("--list-missing", action="store_true")
    a = ap.parse_args()
    if not (a.coverage or a.list_missing):
        ap.error("pass --coverage or --list-missing")

    total_described = total_total = 0
    for path in xrd_files():
        missing = [] if a.list_missing else None
        d, t = coverage_for(path, missing)
        total_described += d
        total_total += t
        if a.list_missing and missing:
            print(f"{path.name}: {d}/{t} described")
            for field in missing:
                print(f"  MISSING description: {field}")

    pct = 100 * total_described / total_total if total_total else 0
    print(f"{total_described}/{total_total} XRD fields described ({pct:.1f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
