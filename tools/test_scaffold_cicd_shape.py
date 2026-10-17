#!/usr/bin/env python3
"""Every cicd.yaml an app composition scaffolds uses Glidepath's current environment shape.

Glidepath's glidepath-app chart refuses the pre-ADR-0019 keys (deploy.lowerEnvironments, upperEnvironments,
promotionOrder) with a render error, so a scaffold still writing them leaves a brand-new app's <app>-cicd Argo CD
application unable to sync (found 2026-10-17 on smoke-ecs: every app scaffold still wrote them). This reads the
cicd.yaml content out of each composition's committed render expectations (example/expected/*.yaml, kept in step with
the templates by test_compositions.py) and checks deploy.environments: a non-empty list, in promotion order, of
{name, tier: ground|flight}, and none of the retired keys. A stub with no `deploy` block at all (InfraService: an
infrastructure repo deploys nothing) is fine.
"""
import glob
import sys

import yaml

RETIRED = ("lowerEnvironments", "upperEnvironments", "promotionOrder")


def scaffolded_cicd_files():
    for path in sorted(glob.glob("compositions/*/example/expected/*.yaml")):
        doc = yaml.safe_load(open(path)) or {}
        for r in doc.get("resources", []):
            res = r.get("resource", r)
            fp = (res.get("spec") or {}).get("forProvider") or {}
            if fp.get("file") == "cicd.yaml" and fp.get("content"):
                yield f"{path} ({r.get('name')})", fp["content"]


def problems(content):
    cicd = yaml.safe_load(content) or {}
    if "deploy" not in cicd:
        return []
    deploy = cicd.get("deploy") or {}
    out = [f"deploy.{k} is retired (ADR-0019); use deploy.environments" for k in RETIRED if k in deploy]
    envs = deploy.get("environments")
    if not isinstance(envs, list) or not envs:
        out.append("deploy.environments is missing or empty")
    else:
        for i, e in enumerate(envs):
            if not isinstance(e, dict) or not e.get("name") or e.get("tier") not in ("ground", "flight"):
                out.append(f"deploy.environments[{i}] needs a name and tier: ground|flight, got {e!r}")
    return out


def main():
    checked = failed = 0
    for where, content in scaffolded_cicd_files():
        checked += 1
        for p in problems(content):
            failed += 1
            print(f"FAIL {where}: {p}")
    if checked == 0:
        sys.exit("no scaffolded cicd.yaml found in any expectation - the test would be vacuous")
    print(f"{checked} scaffolded cicd.yaml checked, {failed} problems")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
