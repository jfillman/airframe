#!/usr/bin/env python3
"""AF-1b generator CLI.

    tools/gen_contract.py            regenerate contract/airframe-contract.json
    tools/gen_contract.py --check    exit 1 if it would change (CI)
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from contract import CONTRACT_PATH, build_contract
import json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    rendered = json.dumps(build_contract(), indent=2, sort_keys=True) + "\n"
    if a.check:
        current = CONTRACT_PATH.read_text() if CONTRACT_PATH.exists() else ""
        if current != rendered:
            print("FAIL: contract/airframe-contract.json is stale - run without --check and commit the result")
            return 1
        print("ok: contract/airframe-contract.json matches its sources")
        return 0
    CONTRACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONTRACT_PATH.write_text(rendered)
    print(f"wrote {CONTRACT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
