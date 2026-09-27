#!/usr/bin/env python3
"""AF-3 generator CLI.

    tools/gen_component_outputs.py            regenerate charts/airframe-application/files/component-outputs.yaml
    tools/gen_component_outputs.py --check     exit 1 if it would change (CI)
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from component_outputs import GENERATED_PATH, gen_component_outputs_yaml


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    before = GENERATED_PATH.read_text() if GENERATED_PATH.exists() else None
    gen_component_outputs_yaml()
    after = GENERATED_PATH.read_text()
    if a.check:
        if before != after:
            print("FAIL: component-outputs.yaml is stale - run without --check and commit the result")
            return 1
        print("ok: component-outputs.yaml matches xrds/*.meta.yaml")
    else:
        print(f"wrote {GENERATED_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
