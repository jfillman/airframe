#!/usr/bin/env python3
"""Render every Composition's fixtures and compare with its committed expectations (review C3).

Each composition with an example/ directory declares its cases in example/cases.yaml:

    cases:
      - name: defaults                       # -> example/expected/defaults.yaml
        xr: xr-defaults.yaml
        required: [cluster-registry-dev-ready.yaml]   # extra resources the pipeline asks for (optional)
        observed: [observed-repository.yaml]          # composed resources as Crossplane would observe them (optional)
        expect:                                       # optional, readable assertions on top of the golden file
          conditions: {TargetReady: AwsLambdaTargetReady}   # condition type -> reason
          fatal: false                                      # true: the pipeline must return a fatal result

The render is normalized (composed resources sorted by composition-resource-name with apiVersion,
kind, metadata.name/namespace/labels/annotations minus what Crossplane adds, and spec; the XR's
conditions and status) and compared with example/expected/<case>.yaml. A difference is a failure,
with the diff. `--update` rewrites the expectations after a deliberate template change; review that
diff like code, it IS the behaviour change.

Two renderers produce the same normalized output:
  crossplane render   (default when the `crossplane` CLI and a Docker daemon are present: CI)
  tools/render-pipeline   (no Docker: the functions run locally under the `container` CLI, see its header)
Pick one with --renderer; the output names which one ran, and `--update` records it in the file.
Either way function-auto-ready must run with --feature-gates=CELHealthcheckCustomizations=true: the
catalog's readiness rules (compositions/_shared/readiness-context.yaml) are CEL. With crossplane render
set AIRFRAME_RENDER_TARGETS=function-go-templating=localhost:9443,function-auto-ready=localhost:9444 and
start both functions yourself (see the CI job); the Docker runtime cannot pass the flag.

    python3 tools/test_compositions.py               # all compositions, check mode
    python3 tools/test_compositions.py slo redis     # some
    python3 tools/test_compositions.py --update slo  # regenerate slo's expectations
"""
import argparse
import copy
import difflib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
COMPOSITIONS = ROOT / "compositions"
RENDER_PIPELINE = ROOT / "tools" / "render-pipeline"
DROP_ANNOTATIONS = {"crossplane.io/composition-resource-name", "crossplane.io/composite",
                    "crossplane.io/external-create-pending", "crossplane.io/external-create-succeeded",
                    "crossplane.io/external-create-failed"}
DROP_LABELS = {"crossplane.io/composite", "crossplane.io/claim-name", "crossplane.io/claim-namespace"}
STATUS_WORDS = {"STATUS_CONDITION_TRUE": "True", "STATUS_CONDITION_FALSE": "False", "STATUS_CONDITION_UNKNOWN": "Unknown"}
# Conditions `crossplane render` synthesizes identically for every render (not part of what a
# composition says about itself): dropped from both renderers' output. Ready is kept: it carries
# function-auto-ready's verdict ("Unready resources: ...") and the pipeline renderer rebuilds it the
# same way Crossplane does.
SYNTHETIC_CONDITIONS = {"Synced", "Responsive"}


class RenderError(Exception):
    pass


# ---- renderers ----------------------------------------------------------------------------------
def docker_available() -> bool:
    return shutil.which("docker") is not None and subprocess.run(["docker", "info"], capture_output=True).returncode == 0


def pick_renderer(name: str) -> str:
    if name != "auto":
        return name
    if shutil.which("crossplane") and docker_available():
        return "crossplane"
    return "render-pipeline"


def run_crossplane_render(comp_dir: Path, case: dict) -> dict:
    """crossplane render -> {xr, resources, results}. Needs example/functions.yaml and Docker."""
    ex = comp_dir / "example"
    functions = ex / "functions.yaml"
    if not functions.exists():
        raise RenderError(f"{comp_dir.name}: example/functions.yaml is required for crossplane render")
    # crossplane render's Docker runtime pulls every function image on every run by default
    # ("Always"); 42 cases × 2 images timed out on a cold CI runner. Reuse what is already local.
    # AIRFRAME_RENDER_TARGETS="function-go-templating=localhost:9443,function-auto-ready=localhost:9444"
    # points crossplane render at functions already running (its Development runtime) instead of
    # letting it start Docker containers: CI starts them itself so function-auto-ready can run with
    # --feature-gates=CELHealthcheckCustomizations=true, which the Docker runtime cannot pass.
    targets = dict(kv.split("=", 1) for kv in os.environ.get("AIRFRAME_RENDER_TARGETS", "").split(",") if "=" in kv)
    fdocs = []
    for d in yaml.safe_load_all(functions.read_text()):
        if isinstance(d, dict) and d.get("kind") == "Function":
            ann = d.setdefault("metadata", {}).setdefault("annotations", {})
            if d["metadata"].get("name") in targets:
                ann["render.crossplane.io/runtime"] = "Development"
                ann["render.crossplane.io/runtime-development-target"] = targets[d["metadata"]["name"]]
            else:
                ann["render.crossplane.io/runtime-docker-pull-policy"] = "IfNotPresent"
            fdocs.append(d)
    tmp = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    yaml.safe_dump_all(fdocs, tmp); tmp.close()
    cmd = ["crossplane", "render", str(ex / case["xr"]), str(comp_dir / "composition.yaml"), tmp.name,
           "--include-full-xr", "--include-function-results", "--timeout=5m"]
    for f in case.get("required", []):
        cmd += ["--required-resources", str(ex / f)]          # repeatable
    obs_dir = None
    if case.get("observed"):
        # --observed-resources takes ONE path (a file or a directory; a repeated flag keeps only the
        # last), so the case's observed fixtures go into one temporary directory.
        obs_dir = tempfile.mkdtemp()
        for f in case["observed"]:
            shutil.copy(ex / f, Path(obs_dir) / Path(f).name)
        cmd += ["--observed-resources", obs_dir]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    os.unlink(tmp.name)
    if obs_dir:
        shutil.rmtree(obs_dir, ignore_errors=True)
    if r.returncode != 0 and not r.stdout.strip():
        raise RenderError(f"crossplane render failed: {r.stderr.strip()[-800:]}")
    docs = [d for d in yaml.safe_load_all(r.stdout) if isinstance(d, dict)]
    xr_in = yaml.safe_load((ex / case["xr"]).read_text())
    xr, resources, results = None, [], []
    for d in docs:
        if d.get("kind") == "Result" and str(d.get("apiVersion", "")).startswith("render.crossplane.io"):
            results.append({"severity": d.get("severity", ""), "message": d.get("message", "")})
        elif d.get("apiVersion") == xr_in.get("apiVersion") and d.get("kind") == xr_in.get("kind") and xr is None:
            xr = d
        else:
            resources.append(d)
    if r.returncode != 0:
        results.append({"severity": "SEVERITY_FATAL", "message": r.stderr.strip()[-800:]})
    return {"xr": xr or {}, "resources": resources, "results": results}


def run_render_pipeline(comp_dir: Path, case: dict) -> dict:
    """tools/render-pipeline --json -> the same shape."""
    ex = comp_dir / "example"
    cmd = [sys.executable, str(RENDER_PIPELINE), str(ex / case["xr"]), str(comp_dir / "composition.yaml"), "--json"]
    for f in case.get("required", []):
        cmd += ["--required", str(ex / f)]
    for f in case.get("observed", []):
        cmd += ["--observed", str(ex / f)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0 or not r.stdout.strip():
        raise RenderError(f"render-pipeline failed: {(r.stderr or r.stdout).strip()[-800:]}")
    out = json.loads(r.stdout)
    xr_in = yaml.safe_load((ex / case["xr"]).read_text()) or {}
    xr_ns = (xr_in.get("metadata") or {}).get("namespace")
    xr = {"status": dict(out.get("composite_status") or {})}
    conds = [{"type": c["type"], "status": STATUS_WORDS.get(c["status"], c["status"]), "reason": c.get("reason", ""),
              "message": c.get("message", "")} for c in out.get("conditions", [])]
    # What Crossplane's composer adds on top of the functions' output, so both renderers agree:
    # the XR's namespace on every composed resource of a namespaced XR, and the Ready condition
    # from function-auto-ready's per-resource verdicts (Creating + "Unready resources: a, b").
    resources, unready = [], []
    for name, entry in out.get("resources", {}).items():
        res = copy.deepcopy(entry.get("resource") or {})
        md = res.setdefault("metadata", {})
        md.setdefault("annotations", {})["crossplane.io/composition-resource-name"] = name
        if xr_ns and not md.get("namespace"):
            md["namespace"] = xr_ns
        if entry.get("ready") != "READY_TRUE":
            unready.append(name)
        resources.append(res)
    if unready:
        conds.append({"type": "Ready", "status": "False", "reason": "Creating", "message": "Unready resources: " + n_and_some_more(sorted(unready))})
    else:
        conds.append({"type": "Ready", "status": "True", "reason": "Available", "message": ""})
    xr["status"]["conditions"] = conds
    return {"xr": xr, "resources": resources, "results": out.get("results", [])}


def n_and_some_more(names: list[str], n: int = 3) -> str:
    """crossplane-runtime's FirstNAndSomeMore wording for the Ready condition, exactly: more than n
    names 'a, b, c, and 7 more'; exactly n 'a, b, and c'; fewer 'a, b' or 'a'."""
    if len(names) > n:
        return ", ".join(names[:n]) + f", and {len(names) - n} more"
    if len(names) == n:
        return ", ".join(names[:-1]) + ", and " + names[-1]
    return ", ".join(names)


# ---- normalization ------------------------------------------------------------------------------
def norm_resource(r: dict) -> dict:
    md = r.get("metadata") or {}
    ann = {k: v for k, v in (md.get("annotations") or {}).items() if k not in DROP_ANNOTATIONS}
    labels = {k: v for k, v in (md.get("labels") or {}).items() if k not in DROP_LABELS}
    out = {"name": (md.get("annotations") or {}).get("crossplane.io/composition-resource-name", md.get("name", "")),
           "apiVersion": r.get("apiVersion"), "kind": r.get("kind"), "metadata": {}}
    if md.get("name"):
        out["metadata"]["name"] = md["name"]
    if md.get("namespace"):
        out["metadata"]["namespace"] = md["namespace"]
    if labels:
        out["metadata"]["labels"] = labels
    if ann:
        out["metadata"]["annotations"] = ann
    for k in ("spec", "data", "stringData", "type"):
        if k in r:
            out[k] = r[k]
    return out


def integral_floats_to_int(obj):
    """The gRPC harness receives protobuf Structs, whose numbers are all doubles (8080.0); crossplane
    render prints the YAML the function emitted (8080). Both mean the same object."""
    if isinstance(obj, float) and obj.is_integer():
        return int(obj)
    if isinstance(obj, dict):
        return {k: integral_floats_to_int(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [integral_floats_to_int(v) for v in obj]
    return obj


def normalize(rendered: dict) -> dict:
    rendered = integral_floats_to_int(rendered)
    xr = rendered.get("xr") or {}
    status = copy.deepcopy(xr.get("status") or {})
    conds = []
    for c in status.pop("conditions", []) or []:
        if c.get("type") in SYNTHETIC_CONDITIONS:
            continue
        conds.append({k: c.get(k) for k in ("type", "status", "reason", "message") if c.get(k) not in (None, "")})
    for k in ("observedGeneration", "lastTransitionTime"):
        status.pop(k, None)
    resources = sorted((norm_resource(r) for r in rendered.get("resources", [])), key=lambda r: (r["name"], r["kind"]))
    return {"xr": {"conditions": sorted(conds, key=lambda c: c["type"]), "status": status}, "resources": resources}


def fatal(rendered: dict) -> bool:
    return any("FATAL" in str(r.get("severity", "")).upper() for r in rendered.get("results", []))


# ---- cases --------------------------------------------------------------------------------------
def load_cases(comp_dir: Path) -> list[dict]:
    f = comp_dir / "example" / "cases.yaml"
    if not f.exists():
        return []
    doc = yaml.safe_load(f.read_text()) or {}
    cases = doc.get("cases") or []
    names = [c["name"] for c in cases]
    if len(set(names)) != len(names):
        raise RenderError(f"{comp_dir.name}: duplicate case names in cases.yaml")
    return cases


def dump(obj) -> str:
    return yaml.safe_dump(obj, sort_keys=True, default_flow_style=False, width=120)


def check_case(comp_dir: Path, case: dict, renderer: str, update: bool) -> list[str]:
    """Returns a list of problems (empty = pass)."""
    run = run_crossplane_render if renderer == "crossplane" else run_render_pipeline
    expect = case.get("expect") or {}
    try:
        rendered = run(comp_dir, case)
    except RenderError as e:
        if expect.get("fatal"):
            return []
        return [f"{case['name']}: {e}"]
    problems = []
    if expect.get("fatal") and not fatal(rendered):
        problems.append(f"{case['name']}: expected a fatal result, got none")
    if not expect.get("fatal") and fatal(rendered):
        problems.append(f"{case['name']}: unexpected fatal result: " + "; ".join(r["message"][:200] for r in rendered["results"] if "FATAL" in str(r.get("severity", "")).upper()))
    actual = normalize(rendered)
    got = {c["type"]: c.get("reason") for c in actual["xr"]["conditions"]}
    for ctype, reason in (expect.get("conditions") or {}).items():
        if got.get(ctype) != reason:
            problems.append(f"{case['name']}: condition {ctype} reason is {got.get(ctype)!r}, expected {reason!r}")
    exp_file = comp_dir / "example" / "expected" / f"{case['name']}.yaml"
    text = f"# Generated by tools/test_compositions.py --update ({renderer}); do not hand-edit. A diff here IS a behaviour change.\n" + dump(actual)
    if update:
        exp_file.parent.mkdir(parents=True, exist_ok=True)
        exp_file.write_text(text)
        return problems
    if not exp_file.exists():
        problems.append(f"{case['name']}: no expectation file {exp_file.relative_to(ROOT)} (run with --update)")
        return problems
    expected = exp_file.read_text().split("\n", 1)[1] if exp_file.read_text().startswith("#") else exp_file.read_text()
    if expected != dump(actual):
        diff = difflib.unified_diff(expected.splitlines(), dump(actual).splitlines(), "expected", "rendered", lineterm="", n=2)
        problems.append(f"{case['name']}: rendered output differs from {exp_file.relative_to(ROOT)}\n" + "\n".join("    " + l for l in list(diff)[:60]))
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("names", nargs="*", help="composition directory names (default: all with example/cases.yaml)")
    ap.add_argument("--update", action="store_true", help="rewrite example/expected/*.yaml from this render")
    ap.add_argument("--renderer", choices=["auto", "crossplane", "render-pipeline"], default="auto")
    a = ap.parse_args()
    renderer = pick_renderer(a.renderer)
    dirs = [COMPOSITIONS / n for n in a.names] if a.names else sorted(p for p in COMPOSITIONS.iterdir() if p.is_dir() and not p.name.startswith("_"))
    total, failed, without = 0, 0, []
    for d in dirs:
        try:
            cases = load_cases(d)
        except RenderError as e:
            print(f"FAIL {e}"); failed += 1; continue
        if not cases:
            if (d / "composition.yaml").exists():
                without.append(d.name)
            continue
        for case in cases:
            total += 1
            problems = check_case(d, case, renderer, a.update)
            if problems:
                failed += 1
                print(f"FAIL {d.name}/{case['name']}")
                for p in problems:
                    print("  " + p)
            else:
                print(f"{'updated' if a.update else 'ok  '} {d.name}/{case['name']}")
    print(f"\n{total - failed}/{total} cases {'written' if a.update else 'pass'} with {renderer}"
          + (f"; no cases.yaml: {', '.join(without)}" if without else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
