#!/usr/bin/env python3
"""AF-2 generator CLI.

    tools/gen_airframe_schema.py --write-values   regenerate values.yaml from values.schema.json
    tools/gen_airframe_schema.py --check          exit 1 if values.yaml would change (CI)
    tools/gen_airframe_schema.py --coverage       print description coverage (schema precision gate)
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from airframe_schema import VALUES_PATH, description_coverage, generate_values_yaml


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-values", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--coverage", action="store_true")
    a = ap.parse_args()
    if not (a.write_values or a.check or a.coverage):
        ap.error("pass --write-values, --check or --coverage")

    if a.coverage:
        described, total = description_coverage()
        pct = 100 * described / total if total else 0
        print(f"{described}/{total} nodes described ({pct:.1f}%)")
        if a.check and pct < 95:
            print("FAIL: below the 95% AF-2 gate")
            return 1

    if a.write_values or a.check:
        rendered = generate_values_yaml()
        if a.check:
            current = VALUES_PATH.read_text() if VALUES_PATH.exists() else ""
            if current != rendered:
                print("FAIL: values.yaml is stale - run with --write-values and commit the result")
                return 1
            print("ok: values.yaml matches values.schema.json")
        else:
            VALUES_PATH.write_text(rendered)
            print(f"wrote {VALUES_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
