"""function-dex (SP-4)

Single-step Composition pipeline for the `Dex` XRD (`xrds/dex.yaml`), both modes:

  server  renders the shared Dex OIDC Deployment/Service/ConfigMap/PVC (pure templating -
          no live call needed). ComponentReady is computed from the observed Deployment's
          own availableReplicas, same "read the real composed resource's status" pattern
          function-rollout-watcher already uses for its Rollout.

  attach  registers a confidential OAuth2 client on the shared server for the
          client_credentials grant. This is the one piece that genuinely needs a custom
          function rather than pure templating: Dex has no CRD a Composition can render for
          "register a client" (its own internal storage CRDs are keyed by a nonstandard
          FNV-64 hash of the client ID, not a stable interface to build on - see
          hangar's project_sp4_oauth_dex_investigation.md), so registration goes through
          Dex's real gRPC Admin API (api/v2, CreateClient) instead. CreateClient is
          idempotent by Dex's own design (CreateClientResp.already_exists), so this function
          calls it on every reconcile with the same (id, secret) pair - the secret itself is
          generated once and reused thereafter, the same stable-secret pattern
          compositions/mongodb/templates/password.yaml already established for this catalog.

NOTE ON SDK ERGONOMICS: follows the same patterns as ../function-rollout-watcher/function/fn.py
(this repo's other custom function) - see that file's own header for the SDK-version caveat.
"""

import base64
import secrets as pysecrets

import grpc
from crossplane.function import logging, resource, response
from crossplane.function.proto.v1 import run_function_pb2 as fnv1
from crossplane.function.proto.v1 import run_function_pb2_grpc as grpcv1

from function import dex_api_pb2 as dexpb
from function import dex_api_pb2_grpc as dexgrpc

GRPC_PORT = 5557
HTTP_PORT = 5556
DEX_CALL_TIMEOUT_SECONDS = 5.0

SIZES = {
    "small": {"cpu_req": "50m", "mem_req": "64Mi", "cpu_lim": "200m", "mem_lim": "128Mi"},
    "medium": {"cpu_req": "100m", "mem_req": "128Mi", "cpu_lim": "500m", "mem_lim": "256Mi"},
    "large": {"cpu_req": "250m", "mem_req": "256Mi", "cpu_lim": "1", "mem_lim": "512Mi"},
}


def safe_get(d, *keys, default=None):
    """Nested [] access that tolerates missing keys/None on Struct-like or dict objects.

    Same rationale as function-rollout-watcher's identical helper: the underlying protobuf
    Struct/Value wrapper raises ValueError ("Value not set"), not KeyError, for a schema field
    that exists but hasn't been populated yet.
    """
    cur = d
    for k in keys:
        try:
            cur = cur[k]
        except (KeyError, TypeError, IndexError, ValueError):
            return default
    return cur


def hangar_labels(xr):
    """Every `hangar.io/`-prefixed label on the XR, passed through to composed resources -
    same convention every other Composition in this catalog uses (see e.g.
    compositions/rabbitmq/templates/*.yaml)."""
    out = {}
    for k, v in (safe_get(xr, "metadata", "labels", default={}) or {}).items():
        if k.startswith("hangar.io/"):
            out[k] = v
    return out


def dex_host(ref):
    """The shared Dex server's in-cluster DNS name, from a serverRef {name, namespace} - same
    deterministic-from-a-Ref construction RabbitMQ's attach mode already uses for its broker
    (compositions/rabbitmq/composition.yaml's ConfigMap `host` field), no live lookup needed."""
    return f"{ref['name']}.{ref['namespace']}.svc.cluster.local"


def dex_grpc_address(ref):
    return f"{dex_host(ref)}:{GRPC_PORT}"


def dex_issuer(ref):
    return f"http://{dex_host(ref)}:{HTTP_PORT}/dex"


def build_server_config(issuer):
    """Dex's own config.yaml - sqlite storage (no external DB for this scope), the
    client_credentials grant enabled cluster-wide (real, documented Dex feature -
    server/grants/clientcredentials.go - not per-client), gRPC Admin API enabled on
    GRPC_PORT for function-dex's own CreateClient calls.

    The `connectors` entry is a real Dex requirement, not a design choice: Dex's own
    server.go refuses to start with zero connectors ("server: no connectors specified"),
    even though this server only ever issues client_credentials tokens and no interactive
    login ever reaches it - confirmed live (a real Dex pod crashed on exactly this before
    the connector was added). `mockCallback` is Dex's own placeholder connector for this
    situation (its real examples/grpc-client/config.yaml, a Dex-authored example of gRPC
    client management, uses the same connector for the same reason) - it's a real Dex
    connector type, but nothing ever drives it, since nothing here initiates a browser login
    flow."""
    return f"""\
issuer: {issuer}
storage:
  type: sqlite3
  config:
    file: /var/dex/dex.db
web:
  http: 0.0.0.0:{HTTP_PORT}
grpc:
  addr: 0.0.0.0:{GRPC_PORT}
oauth2:
  grantTypes:
    - client_credentials
staticClients: []
connectors:
  - type: mockCallback
    id: unused-placeholder
    name: Unused placeholder (this server only issues client_credentials tokens)
"""


def build_server_resources(xr_name, xr_namespace, spec, labels):
    """server mode: Deployment + Service + ConfigMap + PVC. Pure templating - safe to
    re-render identically every reconcile, no live state needed."""
    size = safe_get(spec, "size", default="small") or "small"
    sizing = SIZES[size]
    storage_size = safe_get(spec, "storageSize", default="1Gi") or "1Gi"
    issuer = dex_issuer({"name": xr_name, "namespace": xr_namespace})

    resources = {}

    resources["config"] = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": f"{xr_name}-config", "namespace": xr_namespace, "labels": labels},
        "data": {"config.yaml": build_server_config(issuer)},
    }

    resources["pvc"] = {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "metadata": {"name": f"{xr_name}-data", "namespace": xr_namespace, "labels": labels},
        "spec": {
            "accessModes": ["ReadWriteOnce"],
            "resources": {"requests": {"storage": storage_size}},
        },
    }

    resources["deployment"] = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": xr_name, "namespace": xr_namespace, "labels": labels},
        "spec": {
            "replicas": 1,  # sqlite storage - a second replica would corrupt the file; a
                            # real HA story needs a shared DB backend, out of scope here.
            "selector": {"matchLabels": {"app.kubernetes.io/name": xr_name}},
            "template": {
                "metadata": {"labels": {**labels, "app.kubernetes.io/name": xr_name}},
                "spec": {
                    "containers": [{
                        "name": "dex",
                        "image": "ghcr.io/dexidp/dex:v2.43.1",
                        "args": ["dex", "serve", "/etc/dex/config.yaml"],
                        "ports": [
                            {"name": "http", "containerPort": HTTP_PORT},
                            {"name": "grpc", "containerPort": GRPC_PORT},
                        ],
                        "volumeMounts": [
                            {"name": "config", "mountPath": "/etc/dex"},
                            {"name": "data", "mountPath": "/var/dex"},
                        ],
                        "resources": {
                            "requests": {"cpu": sizing["cpu_req"], "memory": sizing["mem_req"]},
                            "limits": {"cpu": sizing["cpu_lim"], "memory": sizing["mem_lim"]},
                        },
                        # /dex/healthz (issuer-path-prefixed, verified live against a real
                        # pod - server.go registers /healthz on the same router as every
                        # issuer-prefixed route, not at bare root; there's no separate
                        # /ready or /live variant on this port, only cmd/dex/serve.go's
                        # own "telemetry" listener has those, on a different port this
                        # Deployment doesn't expose).
                        "readinessProbe": {
                            "httpGet": {"path": "/dex/healthz", "port": HTTP_PORT},
                            "initialDelaySeconds": 5,
                        },
                        "livenessProbe": {
                            "httpGet": {"path": "/dex/healthz", "port": HTTP_PORT},
                            "initialDelaySeconds": 10,
                        },
                    }],
                    "volumes": [
                        {"name": "config", "configMap": {"name": f"{xr_name}-config"}},
                        {"name": "data", "persistentVolumeClaim": {"claimName": f"{xr_name}-data"}},
                    ],
                },
            },
        },
    }

    resources["service"] = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": xr_name, "namespace": xr_namespace, "labels": labels},
        "spec": {
            "selector": {"app.kubernetes.io/name": xr_name},
            "ports": [
                {"name": "http", "port": HTTP_PORT, "targetPort": HTTP_PORT},
                {"name": "grpc", "port": GRPC_PORT, "targetPort": GRPC_PORT},
            ],
        },
    }

    allowed = safe_get(spec, "allowedNamespaces", default=[]) or []
    ingress_rules = [
        # The gRPC Admin port is for function-dex's own CreateClient calls only - it runs
        # centrally in crossplane-system, never in an app namespace.
        {
            "from": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "crossplane-system"}}}],
            "ports": [{"protocol": "TCP", "port": GRPC_PORT}],
        },
    ]
    if allowed:
        ingress_rules.append({
            "from": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": n}}} for n in allowed],
            "ports": [{"protocol": "TCP", "port": HTTP_PORT}],
        })
    resources["networkpolicy"] = {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {"name": f"{xr_name}-dex-access", "namespace": xr_namespace, "labels": labels},
        "spec": {
            "podSelector": {"matchLabels": {"app.kubernetes.io/name": xr_name}},
            "policyTypes": ["Ingress"],
            "ingress": ingress_rules,
        },
    }

    return resources


def server_component_ready(req):
    """AF-6a: server mode's ComponentReady, from the observed Deployment's own
    availableReplicas - same "read the real composed resource, not a proxy" reasoning as
    every other component's status.yaml in this catalog."""
    deploy = req.observed.resources.get("deployment")
    # fnv1.Resource is a real protobuf message (.resource, .ready are attributes), not a
    # Struct - only the Struct itself (deploy.resource) supports [] access. Same distinction
    # crossplane.function.resource.get_condition's own docstring calls out.
    available = safe_get(deploy.resource, "status", "availableReplicas", default=0) if deploy else 0
    available = available or 0
    if available >= 1:
        return resource.Condition(
            typ="ComponentReady", status="True", reason="DexServerReady",
            message="The Dex Deployment has at least one available replica.",
        )
    return resource.Condition(
        typ="ComponentReady", status="False", reason="DexServerProvisioning",
        message="The Dex Deployment has not reported an available replica yet.",
    )


def reused_or_generated_secret(req, xr_name):
    """The stable-secret pattern: reuse the observed Secret's own client-secret if it
    already exists, generate fresh only the first time - same reasoning as
    compositions/mongodb/templates/password.yaml (re-generating on every reconcile would
    rotate a real credential on every sync)."""
    existing = req.observed.resources.get("oauth-credentials")
    existing_b64 = safe_get(existing.resource, "data", "client-secret") if existing else None
    if existing_b64:
        return base64.b64decode(existing_b64).decode()
    return pysecrets.token_urlsafe(32)


async def create_dex_client(grpc_address, client_id, client_secret, name):
    """The one live side effect in this function: register (or confirm) a confidential
    OAuth2 client on the shared Dex server via its real Admin gRPC API. Idempotent by
    Dex's own design (CreateClientResp.already_exists) - calling this every reconcile with
    the same (id, secret) is always a no-op after the first success, so no separate
    GetClient check is needed."""
    async with grpc.aio.insecure_channel(grpc_address) as channel:
        stub = dexgrpc.DexStub(channel)
        req = dexpb.CreateClientReq(
            client=dexpb.Client(id=client_id, secret=client_secret, public=False, name=name),
        )
        return await stub.CreateClient(req, timeout=DEX_CALL_TIMEOUT_SECONDS)


class FunctionRunner(grpcv1.FunctionRunnerService):
    """A FunctionRunner handles gRPC RunFunctionRequests."""

    def __init__(self):
        self.log = logging.get_logger()

    async def RunFunction(  # noqa: N802 - gRPC requires this PascalCase name.
        self, req: fnv1.RunFunctionRequest, _: grpc.aio.ServicerContext
    ) -> fnv1.RunFunctionResponse:
        log = self.log.bind(tag=req.meta.tag)
        rsp = response.to(req)

        xr = req.observed.composite.resource
        xr_name = safe_get(xr, "metadata", "name")
        xr_namespace = safe_get(xr, "metadata", "namespace")
        spec = safe_get(xr, "spec", default={}) or {}
        mode = safe_get(spec, "mode")
        labels = hangar_labels(xr)

        if mode == "server":
            # config/pvc/service/networkpolicy have no status.conditions for
            # function-auto-ready's generic detection to find - same gotcha
            # function-rollout-watcher's own ServiceAccount hit (see that file's
            # build_diagnosis_service_account docstring). Only the Deployment has a real
            # Available condition auto-ready can read, so it's the one resource left for
            # auto-ready to judge.
            for name, manifest in build_server_resources(xr_name, xr_namespace, spec, labels).items():
                rsp.desired.resources[name].resource.update(manifest)
                if name != "deployment":
                    rsp.desired.resources[name].ready = fnv1.READY_TRUE
            response.set_conditions(rsp, server_component_ready(req))
            response.normal(rsp, f"Dex server {xr_name} rendered")
            log.info("rendered dex server", xr=xr_name)
            return rsp

        if mode == "attach":
            server_ref = safe_get(spec, "serverRef", default={}) or {}
            client_id = safe_get(spec, "clientId") or xr_name
            client_secret = reused_or_generated_secret(req, xr_name)

            try:
                dex_resp = await create_dex_client(
                    dex_grpc_address(server_ref), client_id, client_secret, xr_name,
                )
                log.info(
                    "registered dex client", xr=xr_name, client_id=client_id,
                    already_exists=dex_resp.already_exists,
                )
            except grpc.RpcError as e:
                response.set_conditions(rsp, resource.Condition(
                    typ="ComponentReady", status="False", reason="DexAttachFailed",
                    message=f"CreateClient to the Dex server's gRPC Admin API failed: {e.details() if hasattr(e, 'details') else e}",
                ))
                response.warning(rsp, f"failed to register Dex client {client_id}: {e}")
                log.info("dex createclient failed", xr=xr_name, error=str(e))
                return rsp

            issuer = dex_issuer(server_ref)
            secret_manifest = {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {
                    "name": f"{xr_name}-oauth-credentials",
                    "namespace": xr_namespace,
                    "labels": labels,
                },
                "type": "Opaque",
                "stringData": {
                    "client-id": client_id,
                    "client-secret": client_secret,
                    "issuer": issuer,
                    "token-url": f"{issuer}/token",
                    "jwks-url": f"{issuer}/keys",
                },
            }
            rsp.desired.resources["oauth-credentials"].resource.update(secret_manifest)
            # Explicit ready=True: a plain Secret has no status.conditions for Crossplane's
            # default readiness auto-detection - same gotcha function-rollout-watcher's own
            # ServiceAccount hit (see that file's build_diagnosis_service_account docstring).
            rsp.desired.resources["oauth-credentials"].ready = fnv1.READY_TRUE
            response.set_conditions(rsp, resource.Condition(
                typ="ComponentReady", status="True", reason="DexAttachReady",
                message="The Dex server confirmed the client is registered.",
            ))
            response.normal(rsp, f"Dex client {client_id} registered")
            log.info("dex attach ready", xr=xr_name, client_id=client_id)
            return rsp

        response.fatal(rsp, f"unknown Dex mode {mode!r}; must be 'server' or 'attach'")
        log.info("unknown mode", xr=xr_name, mode=mode)
        return rsp
