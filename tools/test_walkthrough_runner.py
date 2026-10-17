#!/usr/bin/env python3
"""AF-7a's own acceptance test for the runner's mechanics (not the live clusters): a step whose
verify exits 0 is reported PASS, one that exits non-zero is FAIL and the overall exit code is 1,
and --render produces the command/expected text without running anything. Live-cluster proof that
a real walkthrough replays green lives in docs/walkthroughs/*.yaml themselves, run by hand against
the dev and prod clusters - this test never touches a real cluster.

Also covers the cluster placeholders: ${DEV_CONTEXT}-style substitution in verify (and as exported env
vars), --render output, flags over env vars, --clusters picking names from a fleet clusters.yaml, a
clear exit 2 when a name is needed but unset, and --all over a directory.

    python3 tools/test_walkthrough_runner.py
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNNER = str(ROOT / "tools" / "walkthrough-runner")

FIXTURE = """\
title: "Fixture walkthrough"
sourceDoc: nowhere.md
steps:
  - id: passes
    title: a step that passes
    command: "echo hi"
    expected: "hi"
    verify: "true"
  - id: fails
    title: a step that fails
    command: "false"
    expected: "never"
    verify: "false"
"""

ALL_PASS = """\
title: "All-pass fixture"
steps:
  - id: a
    title: a
    command: "echo a"
    expected: "a"
    verify: "true"
"""

PLACEHOLDERS = """\
title: "Placeholder fixture"
steps:
  - id: subst
    title: braces are substituted
    command: "kubectl --context ${DEV_CONTEXT} get ns app-x-${PROD_CLUSTER}"
    expected: "x"
    verify: 'test "${DEV_CONTEXT}" = "ctx-dev" && test "${PROD_CLUSTER}" = "c-prod"'
  - id: envvar
    title: plain $VAR works through the exported environment
    command: "echo $GITHUB_OWNER"
    expected: "x"
    verify: 'test "$PROD_CONTEXT" = "c-prod" && test "$GITHUB_OWNER" = "acme" && test "$(printenv DEV_CLUSTER)" = "c-dev" && test -x "$AIRFRAME_ROOT/tools/airframe-verify"'
"""

CLUSTERS = """\
clusters:
  - name: lab-dev
    zone: lower
    roles: [control-plane, workloads]
  - name: lab-prod
    zone: upper
    roles: [workloads, platform-services]
"""

AMBIGUOUS = """\
clusters:
  - name: lab-dev
    zone: lower
    roles: [control-plane]
  - name: up-a
    zone: upper
    roles: [workloads]
  - name: up-b
    zone: upper
    roles: [workloads]
"""

CLUSTER_CHECK = """\
title: "clusters.yaml fixture"
steps:
  - id: names
    title: names come from clusters.yaml, contexts follow them
    command: "true"
    verify: 'test "$DEV_CLUSTER" = lab-dev && test "$DEV_CONTEXT" = lab-dev && test "$PROD_CONTEXT" = lab-prod'
"""


OWNER_CHECK = """\
title: "owner fixture"
steps:
  - id: owner
    title: the GitHub owner is substituted
    command: "gh api repos/${GITHUB_OWNER}/x"
    verify: 'test "$GITHUB_OWNER" = acme'
"""

CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith("HANGAR_")}


def run(*args, env=None):
    e = dict(CLEAN_ENV)
    e.update(env or {})
    return subprocess.run([sys.executable, RUNNER, *args], capture_output=True, text=True, cwd=ROOT, env=e)


def main():
    failed = 0
    with tempfile.TemporaryDirectory() as td:
        mixed = Path(td) / "mixed.yaml"
        mixed.write_text(FIXTURE)
        r = run(str(mixed))
        if "PASS passes" not in r.stdout:
            print("FAIL: passing step not reported PASS"); failed = 1
        if "FAIL fails" not in r.stdout:
            print("FAIL: failing step not reported FAIL"); failed = 1
        if r.returncode != 1:
            print(f"FAIL: exit code should be 1 with a failing step, got {r.returncode}"); failed = 1
        if "1/2 steps passed" not in r.stdout:
            print("FAIL: summary line wrong"); failed = 1

        allpass = Path(td) / "allpass.yaml"
        allpass.write_text(ALL_PASS)
        r = run(str(allpass))
        if r.returncode != 0:
            print(f"FAIL: exit code should be 0 with no failing steps, got {r.returncode}"); failed = 1
        if "replays green" not in r.stdout:
            print("FAIL: all-pass run should say 'replays green'"); failed = 1

        rendered = Path(td) / "out.md"
        r = run(str(mixed), "--render", str(rendered))
        if r.returncode != 0:
            print("FAIL: --render should exit 0"); failed = 1
        text = rendered.read_text()
        if "echo hi" not in text or "**Expected:** hi" not in text:
            print("FAIL: rendered markdown missing command/expected text"); failed = 1
        if "a step that fails" not in text:
            print("FAIL: rendering should document every step, including ones that would fail"); failed = 1

        # --- cluster placeholders ---
        ph = Path(td) / "ph.yaml"
        ph.write_text(PLACEHOLDERS)
        flags = ["--dev-cluster", "c-dev", "--prod-cluster", "c-prod", "--dev-context", "ctx-dev",
                 "--github-owner", "acme"]
        r = run(str(ph), *flags)
        if r.returncode != 0 or "2/2 steps passed" not in r.stdout:
            print(f"FAIL: placeholders not substituted/exported: {r.stdout} {r.stderr}"); failed = 1

        r = run(str(ph), env={"HANGAR_DEV_CLUSTER": "c-dev", "HANGAR_PROD_CLUSTER": "c-prod",
                              "HANGAR_DEV_CONTEXT": "ctx-dev", "HANGAR_GITHUB_OWNER": "acme"})
        if r.returncode != 0:
            print(f"FAIL: env vars should supply the names: {r.stdout} {r.stderr}"); failed = 1

        r = run(str(ph), "--dev-context", "ctx-dev", "--github-owner", "acme",
                env={"HANGAR_DEV_CLUSTER": "c-dev", "HANGAR_PROD_CLUSTER": "wrong"}, )
        r2 = run(str(ph), "--prod-cluster", "c-prod", "--dev-context", "ctx-dev", "--github-owner", "acme",
                 env={"HANGAR_DEV_CLUSTER": "c-dev", "HANGAR_PROD_CLUSTER": "wrong"})
        if r.returncode != 1 or r2.returncode != 0:
            print(f"FAIL: a flag should win over its env var ({r.returncode}, {r2.returncode})"); failed = 1

        r = run(str(ph))
        if r.returncode != 2 or "DEV_CLUSTER is not set" not in r.stderr or "--dev-cluster" not in r.stderr:
            print(f"FAIL: unset cluster names must exit 2 with a clear message: {r.returncode} {r.stderr}"); failed = 1

        r = run(str(mixed))
        if r.returncode != 1:
            print("FAIL: a walkthrough with no placeholders must still run without any cluster names"); failed = 1

        out = Path(td) / "ph.md"
        r = run(str(ph), "--render", str(out))
        txt = out.read_text() if out.exists() else ""
        if r.returncode != 0 or "--context <dev-context>" not in txt or "app-x-<prod-cluster>" not in txt:
            print(f"FAIL: --render without names should print readable placeholders: {txt}"); failed = 1
        r = run(str(ph), "--render", str(out), *flags)
        txt = out.read_text()
        if "--context ctx-dev get ns app-x-c-prod" not in txt or "<dev-" in txt:
            print(f"FAIL: --render with names should substitute them: {txt}"); failed = 1

        cl = Path(td) / "clusters.yaml"
        cl.write_text(CLUSTERS)
        cc = Path(td) / "cc.yaml"
        cc.write_text(CLUSTER_CHECK)
        r = run(str(cc), "--clusters", str(cl))
        if r.returncode != 0:
            print(f"FAIL: --clusters should pick lab-dev/lab-prod: {r.stdout} {r.stderr}"); failed = 1

        amb = Path(td) / "amb.yaml"
        amb.write_text(AMBIGUOUS)
        r = run(str(cc), "--clusters", str(amb))
        if r.returncode != 2 or "up-a, up-b" not in r.stderr:
            print(f"FAIL: an ambiguous clusters.yaml must exit 2 naming the candidates: {r.stderr}"); failed = 1
        r = run(str(cc), "--clusters", str(amb), "--prod-cluster", "lab-prod")
        if r.returncode != 0:
            print(f"FAIL: a flag should resolve an ambiguous clusters.yaml: {r.stdout} {r.stderr}"); failed = 1

        # --- GitHub owner: required, no default; from flag, env, env file, clusters.yaml or cluster.yaml ---
        own = Path(td) / "own.yaml"
        own.write_text(OWNER_CHECK)
        r = run(str(own))
        if r.returncode != 2 or "GITHUB_OWNER is not set" not in r.stderr or "--github-owner" not in r.stderr:
            print(f"FAIL: an unset GitHub owner must exit 2 with a clear message: {r.stderr}"); failed = 1
        r = run(str(own), env={"GITHUB_OWNER": "acme"})
        if r.returncode != 2:
            print("FAIL: plain GITHUB_OWNER must not be read (HANGAR_GITHUB_OWNER is the variable)"); failed = 1
        r = run(str(own), env={"HANGAR_GITHUB_OWNER": "acme"})
        if r.returncode != 0:
            print(f"FAIL: HANGAR_GITHUB_OWNER should supply the owner: {r.stderr}"); failed = 1
        clo = Path(td) / "clusters-owner.yaml"
        clo.write_text("scm: {host: github.com, owner: acme}\n" + CLUSTERS)
        r = run(str(own), "--clusters", str(clo))
        if r.returncode != 0:
            print(f"FAIL: scm.owner in clusters.yaml should supply the owner: {r.stderr}"); failed = 1
        cfg = Path(td) / "cluster.yaml"
        cfg.write_text("clusterName: x\nscm:\n  host: github.com\n  owner: acme\n")
        r = run(str(own), "--cluster-config", str(cfg))
        if r.returncode != 0:
            print(f"FAIL: scm.owner in an Apron cluster.yaml should supply the owner: {r.stderr}"); failed = 1
        envf = Path(td) / "wt.env"
        envf.write_text("# lab settings\nexport HANGAR_GITHUB_OWNER=acme\nHANGAR_CLUSTERS_FILE=%s\n" % cl)
        r = run(str(cc), "--env-file", str(envf))
        r2 = run(str(own), "--env-file", str(envf))
        if r.returncode != 0 or r2.returncode != 0:
            print(f"FAIL: --env-file should supply the owner and the clusters file: {r.stderr} {r2.stderr}"); failed = 1
        r = run(str(own), "--env-file", str(envf), env={"HANGAR_GITHUB_OWNER": "other"})
        if r.returncode != 1:
            print("FAIL: a real env var should win over the env file"); failed = 1
        r = run(str(own), "--env-file", str(Path(td) / "missing.env"))
        if r.returncode != 2:
            print("FAIL: a missing --env-file must exit 2"); failed = 1

        # --all over a directory: every part*.yaml, one summary line
        d = Path(td) / "wt"
        d.mkdir()
        (d / "part1-a.yaml").write_text(ALL_PASS)
        (d / "part2-b.yaml").write_text(ALL_PASS)
        (d / "notes.yaml").write_text(FIXTURE)
        r = run("--all", "--dir", str(d))
        if r.returncode != 0 or "2/2 walkthroughs replay green" not in r.stdout:
            print(f"FAIL: --all should run every part*.yaml: {r.stdout} {r.stderr}"); failed = 1
        (d / "part3-c.yaml").write_text(FIXTURE)
        r = run("--all", "--dir", str(d), "--format", "json")
        if r.returncode != 1 or json.loads(r.stdout)["ok"] is not False:
            print("FAIL: --all with a failing part should exit 1 and report ok: false"); failed = 1

    if failed:
        print("FAILED")
        return 1
    print("ok: walkthrough-runner mechanics")
    return 0


if __name__ == "__main__":
    sys.exit(main())
