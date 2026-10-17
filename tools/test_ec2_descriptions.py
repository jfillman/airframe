#!/usr/bin/env python3
"""Every EC2 resource description a composition renders uses only the characters EC2 accepts.

EC2 refuses a security group or rule description with any character outside a-z A-Z 0-9, space and
._-:/()#,@[]+=&;{}!$* (InvalidParameterValue), and the managed resource then never becomes ready. On 2026-10-17 an
apostrophe in AwsEcsTarget's egress rule description ("the app's own calls") stopped smoke-ecs's network from coming
up. This scans the committed render expectations (compositions/*/example/expected/*.yaml, kept in step with the
templates by test_compositions.py) for ec2.aws resources and checks every `description` in their forProvider.
"""
import glob
import re
import sys

import yaml

ALLOWED = re.compile(r"^[a-zA-Z0-9. _\-:/()#,@\[\]+=&;{}!$*]{0,255}$")


def descriptions(node, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "description" and isinstance(v, str):
                yield f"{path}.{k}", v
            else:
                yield from descriptions(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from descriptions(v, f"{path}[{i}]")


def main():
    checked = failed = 0
    for f in sorted(glob.glob("compositions/*/example/expected/*.yaml")):
        doc = yaml.safe_load(open(f)) or {}
        for r in doc.get("resources", []):
            res = r.get("resource", r)
            if not str(res.get("apiVersion", "")).startswith("ec2.aws"):
                continue
            for where, text in descriptions((res.get("spec") or {}).get("forProvider") or {}, "forProvider"):
                checked += 1
                if not ALLOWED.match(text):
                    failed += 1
                    bad = sorted({c for c in text if not ALLOWED.match(c)})
                    print(f"FAIL {f} {r.get('name')} {where}: characters EC2 refuses {bad}: {text!r}")
    if checked == 0:
        sys.exit("no EC2 descriptions found in any expectation - the test would be vacuous")
    print(f"{checked} EC2 descriptions checked, {failed} invalid")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
