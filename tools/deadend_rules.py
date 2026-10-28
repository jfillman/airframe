"""AF-4b: the dead-end rules (L4 policy, L5 conventions, part of L6 references). Each function takes
the parsed values file and returns a list of (loc, rule, message, hint, severity) tuples - severity is
"error" or "warning". Static only (no cluster, no helm) so these run under --no-render too.

Each rule id here corresponds to a documented "dead end" - a mistake this catalog has actually hit or
anticipates, listed in the handoff/roadmap's own dead-ends sections and hangar/docs/autopilot/
airframe-ai-friendly.md's AF-4 seed-rule table.
"""
import re

PIPELINE_STAGE_NAMES = {"build", "test", "deploy", "release"}

# High-precision secret-shape patterns only (AF-SECRET-001) - deliberately no generic entropy
# heuristic, which would false-positive on ordinary config strings (URLs, image tags, hashes used as
# non-secret identifiers). Each pattern here is a real, unambiguous secret format.
SECRET_PATTERNS = [
    (re.compile(r"^AKIA[0-9A-Z]{16}$"), "an AWS access key id"),
    (re.compile(r"^gh[pousr]_[A-Za-z0-9]{36,}$"), "a GitHub token"),
    (re.compile(r"^xox[baprs]-[A-Za-z0-9-]{10,}$"), "a Slack token"),
    (re.compile(r"^sk-[A-Za-z0-9]{20,}$"), "an API secret key"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "a private key"),
    (re.compile(r"^eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$"), "a JWT"),
]


def _known_component_kinds(schema):
    return set((schema.get("properties", {}).get("componentKinds", {}).get("default") or {}))


def cluster_rule(data):
    """AF-CLUSTER-001: devClusterName was removed (2026-10-16). The chart no longer compares cluster names; the
    dev-vs-upper decision is clusterType, the cluster's registry `type`. A file still setting it is a dead end:
    the schema rejects the key, and this says what replaced it."""
    out = []
    if "devClusterName" in data:
        out.append(("/devClusterName", "AF-CLUSTER-001", "devClusterName was removed: the chart compares no cluster names",
                     "delete it; the platform sets clusterType (dev | upper, from the cluster registry) and cluster", "error"))
    return out


def env_name_rule(data):
    out = []
    v = data.get("envName")
    if isinstance(v, str) and v.lower() in PIPELINE_STAGE_NAMES:
        out.append(("/envName", "AF-ENV-001", f"envName '{v}' looks like a pipeline stage, not an environment",
                     "name the environment (dev, staging, prod, or a PR number), not a stage of the release process", "error"))
    return out


def component_kind_rule(data, schema):
    out = []
    known = _known_component_kinds(schema)
    for i, c in enumerate(data.get("components") or []):
        if not isinstance(c, dict):
            continue
        kind = c.get("type")
        if kind is not None and kind not in known:
            out.append((f"/components/{i}/type", "AF-COMP-001", f"unknown component type '{kind}'",
                         "one of: " + ", ".join(sorted(known)), "error"))
    return out


def _looks_like_secret(value):
    if not isinstance(value, str):
        return None
    for pattern, label in SECRET_PATTERNS:
        if pattern.search(value):
            return label
    return None


def secret_literal_rule(data):
    out = []
    for i, e in enumerate(data.get("env") or []):
        if isinstance(e, dict) and isinstance(e.get("value"), str):
            label = _looks_like_secret(e["value"])
            if label:
                out.append((f"/env/{i}/value", "AF-SECRET-001", f"looks like {label}",
                             "secrets are references (valueFrom/fromComponent to Infisical or a component's own Secret), never literal values", "error"))
    for i, cm in enumerate(data.get("configMaps") or []):
        if not isinstance(cm, dict):
            continue
        for k, v in (cm.get("data") or {}).items():
            label = _looks_like_secret(v)
            if label:
                out.append((f"/configMaps/{i}/data/{k}", "AF-SECRET-001", f"looks like {label}",
                             "ConfigMaps are not for secrets - use `secrets:` (Infisical) or a component's own output instead", "error"))
    return out


def hand_written_component_ref_rule(data):
    """AF-COMP-003 (advisory): a valueFrom.secretKeyRef/configMapKeyRef name matches the naming
    convention a real components[] entry's own output would produce - the exact shape of the gap
    AF-3's fromComponent closes. Warning, not an error: the fleet isn't fully migrated yet."""
    out = []
    comp_names = {c["name"] for c in (data.get("components") or []) if isinstance(c, dict) and c.get("name")}
    if not comp_names:
        return out
    suffixes = ("-connection", "-user-credentials", "-app")
    for i, e in enumerate(data.get("env") or []):
        if not isinstance(e, dict):
            continue
        vf = e.get("valueFrom") or {}
        for ref_kind in ("secretKeyRef", "configMapKeyRef"):
            ref = vf.get(ref_kind)
            if not isinstance(ref, dict):
                continue
            name = ref.get("name", "")
            for suf in suffixes:
                if name.endswith(suf) and name[: -len(suf)] in comp_names:
                    out.append((f"/env/{i}/valueFrom/{ref_kind}", "AF-COMP-003",
                                 f"'{name}' looks like component '{name[: -len(suf)]}'s own output, hand-written",
                                 "use fromComponent instead - see that component's xrds/<type>.meta.yaml for its output names", "warning"))
    return out



# A hand-written in-cluster Service host: <service>.<namespace>.svc[.cluster.local]. A superset of the hangar scorecard's
# `svc\.cluster\.local` literal check (tools/airframe-scorecard/scorecard.py), so anything it counts, this names.
SERVICE_HOST = re.compile(r"(?:(?P<scheme>[a-z][a-z0-9+.-]*)://)?(?P<svc>[a-z0-9]([-a-z0-9]*[a-z0-9])?)\."
                          r"(?P<ns>[a-z0-9]([-a-z0-9]*[a-z0-9])?)\.svc(?P<local>\.cluster\.local)?(?![a-z0-9.-])"
                          r"(?::(?P<port>[0-9]+))?(?P<rest>\S*)")


def _from_service_suggestion(m, env_name):
    """The fromService that renders the same URL, or None when the URL has more than fromService expresses (a path)
    or its namespace is not an <app|infra>-<app>-<env> one."""
    if m.group("rest") or not m.group("port") or m.start() != 0:
        return None
    svc, ns = m.group("svc"), m.group("ns")
    for kind in ("app", "infra"):
        if not ns.startswith(kind + "-"):
            continue
        rest = ns[len(kind) + 1:]
        # The service is usually the app's own name; otherwise the namespace's env is this file's envName.
        if rest.startswith(svc + "-"):
            app, env, service = svc, rest[len(svc) + 1:], None
        elif env_name and rest.endswith("-" + env_name):
            app, env, service = rest[: -len(env_name) - 1], env_name, svc
        else:
            continue
        ref = {"app": app, "port": int(m.group("port"))}
        if (m.group("scheme") or "http") != "http":
            ref["scheme"] = m.group("scheme")
        if kind != "app":
            ref["type"] = kind
        if env != env_name:
            ref["env"] = env
        if service:
            ref["service"] = service
        return "{" + ", ".join(f"{k}: {v}" for k, v in ref.items()) + "}"
    return None


def hand_written_service_url_rule(data):
    """AF-SVC-001 (advisory): an env value hand-writes another app's in-cluster Service URL, so it relies on the
    platform's namespace convention (<type>-<app>-<env>) instead of letting the platform resolve it - the gap
    env[].fromService closes. Warning, not an error: fromService needs the platform to pass
    serviceNamespacePattern, which lands per cluster after the chart; and a URL into a namespace outside the
    convention (a shared platform service) is legitimate. Promote it once the fleet is migrated."""
    out = []
    env_name = data.get("envName") if isinstance(data.get("envName"), str) else None
    comp_names = {c["name"] for c in (data.get("components") or []) if isinstance(c, dict) and c.get("name")}
    for i, e in enumerate(data.get("env") or []):
        if not isinstance(e, dict) or not isinstance(e.get("value"), str):
            continue
        m = SERVICE_HOST.search(e["value"])
        if not m:
            continue
        svc = m.group("svc")
        comp = next((c for c in sorted(comp_names) if svc == c or svc.startswith(c + "-")), None)
        sugg = None if comp else _from_service_suggestion(m, env_name)
        if comp:
            hint = f"this looks like component '{comp}'s own Service: use fromComponent (see its xrds/<type>.meta.yaml outputs)"
        elif sugg:
            hint = f"use fromService: {sugg}"
        else:
            hint = ("if it is another app's or an InfraService's Service, use fromService: {app, port} (scheme, type, env, "
                    "service as needed); a platform service outside the <type>-<app>-<env> namespaces can stay a value")
        out.append((f"/env/{i}/value", "AF-SVC-001",
                    f"'{m.group(0)}' is a hand-written in-cluster Service URL", hint, "warning"))
    return out

def all_deadend_problems(data, schema):
    problems = []
    problems.extend(cluster_rule(data))
    problems.extend(env_name_rule(data))
    problems.extend(component_kind_rule(data, schema))
    problems.extend(secret_literal_rule(data))
    problems.extend(hand_written_component_ref_rule(data))
    problems.extend(hand_written_service_url_rule(data))
    return problems
