#!/usr/bin/env python3
"""Sidecar drift test (review A3): every xrds/<kind>.meta.yaml must agree with what its composition
actually renders.

The sidecars are the contract the chart's fromComponent, the contract bundle and airframe-verify trust
for a kind's names. Nothing used to compare them with the compositions, so a renamed Secret in a
template would have left the chart pointing apps at a Secret that no longer exists. This test reads the
committed composition renders (compositions/<c>/example/expected/*.yaml, which tools/test_compositions.py
in turn holds equal to a real render in CI) and checks, per sidecar:

  sources     every object an output or verify step names has a source, and the source is in the render:
              createdBy composition  the object itself is composed (provider-kubernetes Objects unwrapped),
                                     and every output key is in its data/stringData when those are visible
              createdBy operator     the composed resource that makes the operator create it (`from`) is
                                     composed under that name, with `field` set (and `equals` when given)
              createdBy crossplane   as operator, plus `keysFrom`: every output key is a connection key
              createdBy function     `checkedBy` names a real test in the function's own suite
  outputs     a secretKeyRef/configMapKeyRef output names a declared source; a literal with `at` equals
              that field of a composed resource
  verify      named Secrets/ConfigMaps/Services are declared sources; condition steps use declared types
              and reasons; {spec.*}/{status.*} templates exist in the XRD schema
  conditions  every custom condition the renders produce is declared, with the rendered reason in its
              closed set
  coverage    every XRD has a sidecar

    python3 tools/test_sidecars.py
"""
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sidecars import ROOT, Unresolved, dig, load_sidecars, render, when_matches  # noqa: E402

GENERIC_CONDITIONS = {"Ready", "Synced", "Responsive"}
NAMED_RUN_FIELDS = {"secretKeys": ("Secret", "secret"), "configMapKeys": ("ConfigMap", "configMap"),
                    "tcp": ("Service", "service"), "http": ("Service", "service"),
                    "oauthClientCredentials": ("Secret", "secret")}


def xrd_for(kind):
    for f in sorted((ROOT / "xrds").glob("*.yaml")):
        if f.name.endswith(".meta.yaml"):
            continue
        d = yaml.safe_load(f.read_text())
        if d and d.get("kind") == "CompositeResourceDefinition" and d["spec"]["names"]["kind"] == kind:
            return d
    return None


def schema_has(xrd, path):
    """Does `spec.a.b` / `status.a.b` exist in the XRD's openAPIV3Schema?"""
    node = xrd["spec"]["versions"][0]["schema"]["openAPIV3Schema"]
    for part in path.split("."):
        props = node.get("properties") or {}
        if part not in props:
            return False
        node = props[part]
    return True


def composition_dir(kind):
    for f in sorted((ROOT / "compositions").glob("*/composition.yaml")):
        if f.parent.name.startswith("_") or f.parent.name.endswith("-hangar"):
            continue
        for d in yaml.safe_load_all(f.read_text()):
            if d and d.get("kind") == "Composition" and (d["spec"].get("compositeTypeRef") or {}).get("kind") == kind:
                return f.parent
    return None


def load_cases(comp):
    """[(case name, fixture XR, normalized render)] for every non-fatal case with an expectation."""
    out = []
    if comp is None or not (comp / "example" / "cases.yaml").exists():
        return out
    for c in (yaml.safe_load((comp / "example" / "cases.yaml").read_text()) or {}).get("cases") or []:
        if (c.get("expect") or {}).get("fatal"):
            continue
        exp = comp / "example" / "expected" / f"{c['name']}.yaml"
        if not exp.exists():
            continue
        xr = yaml.safe_load((comp / "example" / c["xr"]).read_text())
        out.append((c["name"], xr, yaml.safe_load(exp.read_text())))
    return out


def effective(rendered):
    """Composed resources, plus the manifest inside every provider-kubernetes Object."""
    for r in rendered.get("resources") or []:
        yield r
        manifest = dig(r, "spec.forProvider.manifest")
        if r.get("kind") == "Object" and isinstance(manifest, dict):
            yield manifest


def find(rendered, kind, name):
    return [r for r in effective(rendered) if r.get("kind") == kind and (r.get("metadata") or {}).get("name") == name]


def matches_value(actual, want):
    return want in actual if isinstance(actual, list) else actual == want


def check_sidecar(key, sc):
    problems = []
    p = lambda msg: problems.append(f"{sc['_file']}: {msg}")  # noqa: E731
    kind = sc["kind"]
    xrd = xrd_for(kind)
    if xrd is None:
        p(f"no XRD with kind {kind}")
        return problems
    comp = composition_dir(kind)
    cases = load_cases(comp)
    sources = sc.get("sources") or []
    outputs = sc.get("outputs") or {}
    declared_conditions = {c["type"]: {r["reason"] for r in c["reasons"]} for c in sc.get("conditions") or []}

    def output_keys_for(obj):
        field = "secret" if obj["kind"] == "Secret" else "configMap"
        return {o["key"] for o in outputs.values() if o.get(field) == obj["name"]}

    # ---- sources against the renders
    for s in sources:
        obj = s["object"]
        label = f"source {obj['kind']} {obj['name']}"
        applicable = [(n, xr, r) for n, xr, r in cases if when_matches(s.get("when"), xr)]
        by = s["createdBy"]
        if by == "function":
            path, _, test = s["checkedBy"].partition("::")
            f = ROOT / path
            if not f.exists() or f"def {test}(" not in f.read_text():
                p(f"{label}: checkedBy {s['checkedBy']} does not name a test that exists")
            continue
        look_kind = obj["kind"] if by == "composition" else s["from"]["kind"]
        relevant = [(n, xr, r) for n, xr, r in applicable if any(x.get("kind") == look_kind for x in effective(r))]
        if not relevant:
            p(f"{label}: no render case composes a {look_kind}{' for ' + str(s.get('when')) if s.get('when') else ''} - add one to compositions/{comp.name if comp else '?'}/example/")
            continue
        for n, xr, r in relevant:
            if by == "composition":
                hit = find(r, obj["kind"], render(obj["name"], xr))
                if not hit:
                    p(f"{label}: case {n} composes no {obj['kind']} named {render(obj['name'], xr)}")
                    continue
                data = {**(hit[0].get("data") or {}), **(hit[0].get("stringData") or {})}
                if data:
                    missing = output_keys_for(obj) - set(data)
                    if missing:
                        p(f"{label}: case {n}: output keys {sorted(missing)} not in the composed object")
            else:
                frm = s["from"]
                hit = find(r, frm["kind"], render(frm["name"], xr))
                if not hit:
                    p(f"{label}: case {n} composes no {frm['kind']} named {render(frm['name'], xr)} (the resource that should make it)")
                    continue
                if frm.get("field"):
                    v = dig(hit[0], frm["field"])
                    if v in (None, []):
                        p(f"{label}: case {n}: {frm['kind']} {render(frm['name'], xr)} has no {frm['field']}")
                    elif "equals" in frm and not matches_value(v, render(frm["equals"], xr)):
                        p(f"{label}: case {n}: {frm['field']} is {v!r}, sidecar expects {render(frm['equals'], xr)!r}")
                if s.get("keysFrom"):
                    have = dig(hit[0], s["keysFrom"]) or []
                    missing = output_keys_for(obj) - set(have if isinstance(have, list) else [have])
                    if missing:
                        p(f"{label}: case {n}: output keys {sorted(missing)} are not connection keys ({s['keysFrom']})")

    def has_source(kind_, name_tpl):
        return any(s["object"]["kind"] == kind_ and s["object"]["name"] == name_tpl for s in sources)

    # ---- outputs
    for oname, o in outputs.items():
        if o["kind"] == "secretKeyRef" and not has_source("Secret", o["secret"]):
            p(f"output {oname}: Secret {o['secret']} has no sources entry")
        if o["kind"] == "configMapKeyRef" and not has_source("ConfigMap", o["configMap"]):
            p(f"output {oname}: ConfigMap {o['configMap']} has no sources entry")
        at = o.get("at")
        if o["kind"] == "literal" and at:
            applicable = [(n, xr, r) for n, xr, r in cases if when_matches(o.get("when"), xr)
                          and any(x.get("kind") == at["kind"] for x in effective(r))]
            if not applicable:
                p(f"output {oname}: no render case composes a {at['kind']} to check `at` against")
            # at least one case: a scaffold file (values.yaml) legitimately leaves the render once the
            # ledger records it, and the value is a deterministic template, so a rename breaks every case
            seen = []
            for n, xr, r in applicable:
                want = render(str(o["value"]), xr)
                vals = [dig(x, at["field"]) for x in effective(r) if x.get("kind") == at["kind"]]
                seen.append((n, want, vals))
                if any(matches_value(v, want) for v in vals if v is not None):
                    break
            else:
                if seen:
                    n, want, vals = seen[0]
                    p(f"output {oname}: no case has a {at['kind']} with {at['field']} == {want!r} (case {n} has {vals})")

    # ---- verify steps
    for v in sc.get("verify") or []:
        run = v["run"]
        rk = run["kind"]
        if rk in NAMED_RUN_FIELDS and run.get(NAMED_RUN_FIELDS[rk][1]):
            k_, field = NAMED_RUN_FIELDS[rk]
            if not has_source(k_, run[field]):
                p(f"verify {v['id']}: {k_} {run[field]} has no sources entry")
        if rk == "resource" and not any(s["object"]["name"] == run["name"] for s in sources):
            p(f"verify {v['id']}: {run['resource']} {run['name']} has no sources entry")
        if rk == "condition":
            if run["type"] not in declared_conditions and run["type"] not in GENERIC_CONDITIONS:
                p(f"verify {v['id']}: condition {run['type']} is not declared under conditions")
            extra = set(run.get("reasons") or []) - declared_conditions.get(run["type"], set())
            if extra and run["type"] not in GENERIC_CONDITIONS:
                p(f"verify {v['id']}: reasons {sorted(extra)} not in {run['type']}'s declared set")
        for val in [x for x in run.values() if isinstance(x, str)] + [a for a in run.get("args") or [] if isinstance(a, str)] + [run.get("path") if rk == "xrField" else None]:
            if not val:
                continue
            for ref in __import__("re").findall(r"\{((?:spec|status)\.[\w.]+)\}", val) + ([val] if rk == "xrField" and val == run.get("path") else []):
                if not schema_has(xrd, ref):
                    p(f"verify {v['id']}: {ref} is not in the {kind} XRD schema")
        if v.get("when") and not schema_has(xrd, v["when"]["field"]):
            p(f"verify {v['id']}: when field {v['when']['field']} is not in the XRD schema")

    # ---- conditions the renders produce
    for n, xr, r in cases:
        for c in r["xr"].get("conditions") or []:
            if c["type"] in GENERIC_CONDITIONS:
                continue
            if c["type"] not in declared_conditions:
                p(f"case {n} renders condition {c['type']} that the sidecar does not declare")
            elif c.get("reason") not in declared_conditions[c["type"]]:
                p(f"case {n} renders {c['type']} reason {c.get('reason')} outside the declared set {sorted(declared_conditions[c['type']])}")

    # literal templates must resolve against a fixture XR (catches {spec.typo})
    for n, xr, r in cases[:1]:
        for oname, o in outputs.items():
            if o["kind"] == "literal" and when_matches(o.get("when"), xr):
                try:
                    render(str(o["value"]), xr)
                except Unresolved as e:
                    if not schema_has(xrd, str(e).strip("'")):
                        p(f"output {oname}: template {e} is not in the XRD schema")
    return problems


def run_all(sidecars):
    problems = []
    for key, sc in sorted(sidecars.items()):
        problems += check_sidecar(key, sc)
    kinds_with = {sc["kind"] for sc in sidecars.values()}
    for f in sorted((ROOT / "xrds").glob("*.yaml")):
        if f.name.endswith(".meta.yaml"):
            continue
        d = yaml.safe_load(f.read_text())
        if d and d.get("kind") == "CompositeResourceDefinition" and d["spec"]["names"]["kind"] not in kinds_with:
            problems.append(f"{f.name}: {d['spec']['names']['kind']} has no xrds/*.meta.yaml sidecar")
    return problems


def _verify_step(sc, id_):
    return next(v for v in sc["verify"] if v["id"] == id_)


def _source(sc, kind, name):
    return next(s for s in sc["sources"] if s["object"]["kind"] == kind and s["object"]["name"] == name)


# Each mutation is a drift this test exists to catch; every one MUST produce a problem mentioning `expect`.
MUTATIONS = [
    ("output names a Secret nobody creates", "postgresql",
     lambda sc: sc["outputs"]["uri"].update(secret="{name}-appx"), "no sources entry"),
    ("operator would write a different Secret", "mongodb",
     lambda sc: _source(sc, "Secret", "{name}-app")["from"].update(equals="{name}-creds"), "sidecar expects"),
    ("output key is not a connection key", "redis",
     lambda sc: sc["outputs"]["password"].update(key="redis-password"), "not connection keys"),
    ("output key is not in the composed ConfigMap", "rabbitmq",
     lambda sc: sc["outputs"]["host"].update(key="hostname"), "not in the composed object"),
    ("literal output disagrees with the render", "nodejsapplication",
     lambda sc: sc["outputs"]["gitopsRepo"].update(value="{name}-gitops-repo"), "no case has a Repository"),
    ("a rendered reason is missing from the closed set", "postgresql",
     lambda sc: sc["conditions"][0].update(reasons=[r for r in sc["conditions"][0]["reasons"] if r["reason"] != "PostgreSQLProvisioning"]),
     "outside the declared set"),
    ("verify template names a status field the XRD lacks", "awslambdatarget",
     lambda sc: _verify_step(sc, "function-exists")["run"]["args"].__setitem__(3, "{status.fnName}"), "not in the AwsLambdaTarget XRD schema"),
    ("checkedBy points at a test that does not exist", "dex",
     lambda sc: sc["sources"][0].update(checkedBy="functions/function-dex/tests/test_fn.py::test_nope"), "does not name a test"),
    ("tcp step names a Service with no source", "postgresql",
     lambda sc: _verify_step(sc, "reachable")["run"].update(service="{name}-primary"), "Service {name}-primary has no sources entry"),
    ("composed object renamed", "slo",
     lambda sc: _source(sc, "ConfigMap", "{name}-slo-dashboard")["object"].update(name="{name}-dashboard"), "composes no ConfigMap named"),
]


def self_test(sidecars):
    import copy
    failures = []
    for label, key, mutate, expect in MUTATIONS:
        mutated = copy.deepcopy(sidecars)
        mutate(mutated[key])
        found = [p for p in run_all(mutated) if expect in p]
        if not found:
            failures.append(f"mutation not caught: {label} ({key}; expected a problem containing {expect!r})")
    gone = copy.deepcopy(sidecars)
    gone.pop("secretstore")
    if not any("SecretStore has no xrds/*.meta.yaml sidecar" in p for p in run_all(gone)):
        failures.append("mutation not caught: a kind with no sidecar")
    return failures


def main():
    sidecars = load_sidecars()
    problems = run_all(sidecars)
    if problems:
        print("\n".join(problems))
        print(f"\nFAIL: {len(problems)} problem(s) across {len(sidecars)} sidecars")
        return 1
    failures = self_test(sidecars)
    if failures:
        print("\n".join(failures))
        print(f"\nFAIL: the drift test missed {len(failures)} of {len(MUTATIONS) + 1} seeded drifts")
        return 1
    n_sources = sum(len(s.get("sources") or []) for s in sidecars.values())
    n_verify = sum(len(s.get("verify") or []) for s in sidecars.values())
    print(f"ok: {len(sidecars)} sidecars, {n_sources} sources and {n_verify} verify steps agree with the composition renders; "
          f"{len(MUTATIONS) + 1}/{len(MUTATIONS) + 1} seeded drifts caught")
    return 0


if __name__ == "__main__":
    sys.exit(main())
