"""function-dex tests.

Prefers a real, in-process gRPC server implementing Dex's own DexServicer interface over
mocking fn.create_dex_client - this exercises the real client stub, the real proto wire
format, and the real async grpc.aio.insecure_channel path, only faking the one thing that's
actually external (the real Dex binary). See feedback_dont_mock_database-style guidance in
this project: a mock of the exact call we're testing would hide a real wire-format bug the
way a mocked DB hid a real migration bug elsewhere in this project's history.
"""

import asyncio
import base64
import unittest

import grpc

from crossplane.function import logging, resource
from crossplane.function.proto.v1 import run_function_pb2 as fnv1

from function import dex_api_pb2 as dexpb
from function import dex_api_pb2_grpc as dexgrpc
from function import fn


class FakeDexServicer(dexgrpc.DexServicer):
    """A minimal, real gRPC server for CreateClient/GetClient - not a mock of fn.py's own call,
    a real server the real generated stub talks to over a real (loopback) socket.

    Mirrors real Dex's semantics (server/apiserver/clients.go), which an earlier version of
    this fake got wrong by overwriting the stored client on every CreateClient: a known id
    answers already_exists=true with NO client and leaves the stored secret untouched, and
    GetClient returns the stored client, secret included."""

    def __init__(self):
        self.created = {}
        self.get_client_error = None  # (grpc.StatusCode, detail) to make GetClient fail

    def CreateClient(self, request, context):  # noqa: N802 - gRPC's own method name.
        c = request.client
        if c.id in self.created:
            return dexpb.CreateClientResp(already_exists=True)
        self.created[c.id] = dexpb.Client()
        self.created[c.id].CopyFrom(c)
        return dexpb.CreateClientResp(client=c)

    def GetClient(self, request, context):  # noqa: N802 - gRPC's own method name.
        if self.get_client_error:
            context.abort(*self.get_client_error)
        c = self.created.get(request.id)
        if c is None:
            context.abort(grpc.StatusCode.NOT_FOUND, f"client {request.id} not found")
        return dexpb.GetClientResp(client=c)


class FakeDexServer:
    """Starts/stops the fake servicer on an ephemeral loopback port."""

    async def __aenter__(self):
        self.servicer = FakeDexServicer()
        self.server = grpc.aio.server()
        dexgrpc.add_DexServicer_to_server(self.servicer, self.server)
        self.port = self.server.add_insecure_port("127.0.0.1:0")
        await self.server.start()
        return self

    async def __aexit__(self, *exc):
        await self.server.stop(None)

    @property
    def address(self):
        return f"127.0.0.1:{self.port}"


def xr(mode, **spec_extra):
    spec = {"mode": mode, "environmentRef": {"name": "env-1"}, **spec_extra}
    return resource.dict_to_struct({
        "apiVersion": "catalog.hangar.io/v1alpha1",
        "kind": "Dex",
        "metadata": {"name": "my-dex", "namespace": "app-x-dev", "labels": {"hangar.io/app": "x"}},
        "spec": spec,
    })


def secret_data(string_values):
    """An observed oauth-credentials Secret's `data` block from plain values (base64, like the API server stores them)."""
    return {"data": {k: base64.b64encode(v.encode()).decode() for k, v in string_values.items()}}


def rendered_secret(rsp):
    return resource.struct_to_dict(rsp.desired.resources["oauth-credentials"].resource)["stringData"]


def warnings_of(rsp):
    return [r.message for r in rsp.results if r.severity == fnv1.SEVERITY_WARNING]


async def run_attach(server, observed=None, address=None):
    """One attach reconcile against the fake server (or an explicit address), optionally with an
    observed oauth-credentials Secret (a dict with a `data` block, see secret_data)."""
    resources = {}
    if observed is not None:
        resources["oauth-credentials"] = fnv1.Resource(resource=resource.dict_to_struct(observed))
    req = fnv1.RunFunctionRequest(
        observed=fnv1.State(
            composite=fnv1.Resource(resource=xr("attach", serverRef={"name": "srv", "namespace": "srv-ns"})),
            resources=resources,
        ),
    )
    target = address or server.address
    orig = fn.dex_grpc_address
    fn.dex_grpc_address = lambda ref: target  # noqa: ARG005 - point at the fake instead of the DNS-derived address
    try:
        return await asyncio.wait_for(fn.FunctionRunner().RunFunction(req, None), timeout=10)
    finally:
        fn.dex_grpc_address = orig


class TestFunctionDex(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        logging.configure(level=logging.Level.DISABLED)

    async def test_server_mode_renders_deployment_service_configmap_pvc_networkpolicy(self):
        req = fnv1.RunFunctionRequest(observed=fnv1.State(composite=fnv1.Resource(resource=xr("server"))))
        rsp = await fn.FunctionRunner().RunFunction(req, None)
        names = set(rsp.desired.resources.keys())
        self.assertEqual(names, {"config", "pvc", "deployment", "service", "networkpolicy"})
        deploy = resource.struct_to_dict(rsp.desired.resources["deployment"].resource)
        self.assertEqual(deploy["kind"], "Deployment")
        self.assertEqual(deploy["spec"]["replicas"], 1)
        conditions = list(rsp.conditions)
        self.assertEqual(len(conditions), 1)
        self.assertEqual(conditions[0].reason, "DexServerProvisioning")  # no observed Deployment yet

    async def test_server_mode_marks_non_deployment_resources_explicitly_ready(self):
        # config/pvc/service/networkpolicy have no status.conditions for
        # function-auto-ready's generic detection - without this the XR's generic Ready
        # condition sticks at False forever (caught live: real pod Running, ComponentReady
        # True, but Ready stayed "Creating").
        req = fnv1.RunFunctionRequest(observed=fnv1.State(composite=fnv1.Resource(resource=xr("server"))))
        rsp = await fn.FunctionRunner().RunFunction(req, None)
        for name in ("config", "pvc", "service", "networkpolicy"):
            self.assertEqual(rsp.desired.resources[name].ready, fnv1.READY_TRUE, name)
        self.assertNotEqual(rsp.desired.resources["deployment"].ready, fnv1.READY_TRUE)

    async def test_server_mode_config_has_at_least_one_connector(self):
        # Real Dex requirement, not style: server.go refuses to start with zero connectors,
        # even for a client_credentials-only deployment - caught live (a real pod crashed on
        # this before the fix). Regression guard so it can't silently come back.
        import yaml as _yaml

        req = fnv1.RunFunctionRequest(observed=fnv1.State(composite=fnv1.Resource(resource=xr("server"))))
        rsp = await fn.FunctionRunner().RunFunction(req, None)
        cm = resource.struct_to_dict(rsp.desired.resources["config"].resource)
        config = _yaml.safe_load(cm["data"]["config.yaml"])
        self.assertTrue(config.get("connectors"), "Dex config must declare at least one connector")

    async def test_server_mode_pins_a_release_and_lists_client_credentials(self):
        # Dex v2.46.0 enables client_credentials only when oauth2.grantTypes lists it (its
        # default list adds it behind a feature flag), and :master floats - guard both.
        import yaml as _yaml

        req = fnv1.RunFunctionRequest(observed=fnv1.State(composite=fnv1.Resource(resource=xr("server"))))
        rsp = await fn.FunctionRunner().RunFunction(req, None)
        cm = resource.struct_to_dict(rsp.desired.resources["config"].resource)
        config = _yaml.safe_load(cm["data"]["config.yaml"])
        self.assertIn("client_credentials", config["oauth2"]["grantTypes"])
        deploy = resource.struct_to_dict(rsp.desired.resources["deployment"].resource)
        image = deploy["spec"]["template"]["spec"]["containers"][0]["image"]
        self.assertRegex(image, r"^ghcr\.io/dexidp/dex:v\d+\.\d+\.\d+$")

    async def test_server_mode_ready_once_deployment_has_available_replicas(self):
        req = fnv1.RunFunctionRequest(
            observed=fnv1.State(
                composite=fnv1.Resource(resource=xr("server")),
                resources={
                    "deployment": fnv1.Resource(resource=resource.dict_to_struct(
                        {"status": {"availableReplicas": 1}},
                    )),
                },
            ),
        )
        rsp = await fn.FunctionRunner().RunFunction(req, None)
        self.assertEqual(rsp.conditions[0].reason, "DexServerReady")
        self.assertEqual(rsp.conditions[0].status, fnv1.STATUS_CONDITION_TRUE)

    async def test_attach_mode_registers_a_real_client_over_a_real_grpc_call(self):
        async with FakeDexServer() as server:
            req = fnv1.RunFunctionRequest(
                observed=fnv1.State(
                    composite=fnv1.Resource(resource=xr(
                        "attach", serverRef={"name": "srv", "namespace": "srv-ns"},
                    )),
                ),
            )
            # Point the function at our fake server instead of the real DNS-derived address.
            orig = fn.dex_grpc_address
            fn.dex_grpc_address = lambda ref: server.address  # noqa: ARG005
            try:
                rsp = await fn.FunctionRunner().RunFunction(req, None)
            finally:
                fn.dex_grpc_address = orig

            self.assertEqual(rsp.conditions[0].reason, "DexAttachReady")
            secret = resource.struct_to_dict(rsp.desired.resources["oauth-credentials"].resource)
            self.assertEqual(secret["stringData"]["client-id"], "my-dex")
            self.assertTrue(secret["stringData"]["client-secret"])
            self.assertIn("my-dex", server.servicer.created)
            self.assertFalse(server.servicer.created["my-dex"].public)

    async def test_attach_declares_a_server_usage_even_when_the_server_is_down(self):
        # C13: deleting the server must be blocked while an attacher exists; the Usage is declared
        # before any gRPC call, so an unreachable server never prunes it.
        for reachable in (True, False):
            if reachable:
                async with FakeDexServer() as server:
                    rsp = await run_attach(server)
            else:
                rsp = await run_attach(None, address="127.0.0.1:1")
            usage = resource.struct_to_dict(rsp.desired.resources["server-usage"].resource)
            self.assertEqual(usage["kind"], "Usage")
            self.assertEqual(usage["spec"]["of"]["resourceRef"], {"name": "srv", "namespace": "srv-ns"})
            self.assertEqual(usage["spec"]["by"]["resourceRef"], {"name": "my-dex"})
            self.assertEqual(usage["metadata"]["namespace"], "app-x-dev")

    async def test_sidecar_secret_and_service_match_the_function(self):
        # xrds/dex.meta.yaml is what the chart's fromComponent, the contract bundle and airframe-verify
        # trust for this kind's names; tools/test_sidecars.py points its `checkedBy` here because this
        # function, not a go-template, renders them. Every secretKeyRef output must name a key the
        # attach Secret really carries, and the server-discovery verify step must hit a real port.
        import pathlib

        import yaml as _yaml

        sidecar = _yaml.safe_load((pathlib.Path(__file__).resolve().parents[3] / "xrds" / "dex.meta.yaml").read_text())
        name = "my-dex"
        async with FakeDexServer() as server:
            rsp = await run_attach(server)
        secret = resource.struct_to_dict(rsp.desired.resources["oauth-credentials"].resource)
        source = next(s["object"] for s in sidecar["sources"] if s["object"]["kind"] == "Secret")
        self.assertEqual(secret["metadata"]["name"], source["name"].replace("{name}", name))
        for out, spec in sidecar["outputs"].items():
            self.assertEqual(spec["secret"].replace("{name}", name), secret["metadata"]["name"], out)
            self.assertTrue(secret["stringData"].get(spec["key"]), f"output {out}: key {spec['key']} missing")

        req = fnv1.RunFunctionRequest(observed=fnv1.State(composite=fnv1.Resource(resource=xr("server"))))
        rsp = await fn.FunctionRunner().RunFunction(req, None)
        svc = resource.struct_to_dict(rsp.desired.resources["service"].resource)
        source = next(s["object"] for s in sidecar["sources"] if s["object"]["kind"] == "Service")
        self.assertEqual(svc["metadata"]["name"], source["name"].replace("{name}", name))
        step = next(v["run"] for v in sidecar["verify"] if v["id"] == "server-discovery")
        self.assertIn(step["port"], [p["port"] for p in svc["spec"]["ports"]])

    async def test_attach_mode_reuses_the_observed_secret_instead_of_rotating_it(self):
        async with FakeDexServer() as server:
            observed_secret_data = {"client-secret": base64.b64encode(b"already-set-secret").decode()}
            req = fnv1.RunFunctionRequest(
                observed=fnv1.State(
                    composite=fnv1.Resource(resource=xr(
                        "attach", serverRef={"name": "srv", "namespace": "srv-ns"},
                    )),
                    resources={
                        "oauth-credentials": fnv1.Resource(resource=resource.dict_to_struct(
                            {"data": observed_secret_data},
                        )),
                    },
                ),
            )
            orig = fn.dex_grpc_address
            fn.dex_grpc_address = lambda ref: server.address  # noqa: ARG005
            try:
                rsp = await fn.FunctionRunner().RunFunction(req, None)
            finally:
                fn.dex_grpc_address = orig

            secret = resource.struct_to_dict(rsp.desired.resources["oauth-credentials"].resource)
            self.assertEqual(secret["stringData"]["client-secret"], "already-set-secret")

    async def test_attach_mode_calling_create_client_twice_is_idempotent(self):
        async with FakeDexServer() as server:
            r1 = await run_attach(server)
            s1 = rendered_secret(r1)
            # Second reconcile sees the Secret it wrote: confirmed, same secret, no rotation.
            r2 = await run_attach(server, observed=secret_data(s1))
            self.assertEqual(r1.conditions[0].reason, "DexAttachReady")
            self.assertEqual(r2.conditions[0].reason, "DexAttachReady")
            self.assertEqual(rendered_secret(r2)["client-secret"], s1["client-secret"])
            self.assertEqual(len(server.servicer.created), 1)  # one client, registered twice
            self.assertEqual(server.servicer.created["my-dex"].secret, s1["client-secret"])
            self.assertFalse(warnings_of(r2))

    async def test_attach_mode_adopts_the_servers_secret_when_the_secret_is_gone_but_the_client_remains(self):
        # The C1 scenario: the XR (or just its Secret) is deleted and recreated while the client
        # stays registered. Real Dex answers already_exists and keeps its secret; before this fix
        # the function wrote a fresh secret the server would never accept and reported Ready.
        async with FakeDexServer() as server:
            r1 = await run_attach(server)
            original = rendered_secret(r1)["client-secret"]
            r2 = await run_attach(server)  # no observed Secret this time
            self.assertEqual(r2.conditions[0].reason, "DexAttachReady")
            self.assertEqual(r2.conditions[0].status, fnv1.STATUS_CONDITION_TRUE)
            self.assertEqual(rendered_secret(r2)["client-secret"], original)
            self.assertEqual(server.servicer.created["my-dex"].secret, original)
            self.assertIn("adopted", r2.conditions[0].message)
            self.assertTrue(any("adopted" in w for w in warnings_of(r2)))

    async def test_attach_mode_converges_a_drifted_secret_back_to_the_server(self):
        async with FakeDexServer() as server:
            server.servicer.created["my-dex"] = dexpb.Client(id="my-dex", secret="server-held", name="my-dex")
            rsp = await run_attach(server, observed=secret_data({"client-id": "my-dex", "client-secret": "stale"}))
            self.assertEqual(rsp.conditions[0].reason, "DexAttachReady")
            self.assertEqual(rendered_secret(rsp)["client-secret"], "server-held")
            self.assertTrue(any("adopted" in w for w in warnings_of(rsp)))

    async def test_attach_mode_confirms_a_matching_secret_without_a_warning(self):
        async with FakeDexServer() as server:
            server.servicer.created["my-dex"] = dexpb.Client(id="my-dex", secret="same", name="my-dex")
            rsp = await run_attach(server, observed=secret_data({"client-id": "my-dex", "client-secret": "same"}))
            self.assertEqual(rsp.conditions[0].reason, "DexAttachReady")
            self.assertEqual(rendered_secret(rsp)["client-secret"], "same")
            self.assertFalse(warnings_of(rsp))

    async def test_attach_mode_fails_closed_when_the_existing_client_has_no_secret(self):
        async with FakeDexServer() as server:
            server.servicer.created["my-dex"] = dexpb.Client(id="my-dex", public=True, name="someone-elses")
            rsp = await run_attach(server)
            self.assertEqual(rsp.conditions[0].reason, "DexAttachFailed")
            self.assertEqual(rsp.conditions[0].status, fnv1.STATUS_CONDITION_FALSE)
            self.assertNotIn("oauth-credentials", rsp.desired.resources)

    async def test_attach_mode_fails_closed_when_getclient_fails_after_already_exists(self):
        async with FakeDexServer() as server:
            server.servicer.created["my-dex"] = dexpb.Client(id="my-dex", secret="server-held", name="my-dex")
            server.servicer.get_client_error = (grpc.StatusCode.INTERNAL, "storage down")
            rsp = await run_attach(server)
            self.assertEqual(rsp.conditions[0].reason, "DexAttachFailed")
            self.assertIn("storage down", rsp.conditions[0].message)
            self.assertNotIn("oauth-credentials", rsp.desired.resources)

    async def test_attach_mode_reports_failure_when_the_server_is_unreachable(self):
        rsp = await run_attach(None, address="127.0.0.1:1")  # nothing listens here
        self.assertEqual(rsp.conditions[0].reason, "DexAttachFailed")
        self.assertEqual(rsp.conditions[0].status, fnv1.STATUS_CONDITION_FALSE)
        self.assertNotIn("oauth-credentials", rsp.desired.resources)

    async def test_attach_mode_keeps_the_observed_secret_declared_when_the_server_is_unreachable(self):
        # A transient admin-API failure must not prune the credentials an app is using: the
        # observed Secret is re-declared byte-for-byte (the WHOLE object - Crossplane applies
        # with server-side apply), only the condition goes False.
        observed = secret_data({
            "client-id": "my-dex", "client-secret": "in-use", "issuer": "http://srv/dex",
            "token-url": "http://srv/dex/token", "jwks-url": "http://srv/dex/keys",
        })
        rsp = await run_attach(None, address="127.0.0.1:1", observed=observed)
        self.assertEqual(rsp.conditions[0].reason, "DexAttachFailed")
        kept = resource.struct_to_dict(rsp.desired.resources["oauth-credentials"].resource)
        self.assertEqual(kept["data"], observed["data"])
        self.assertEqual(kept["metadata"]["name"], "my-dex-oauth-credentials")
        self.assertEqual(rsp.desired.resources["oauth-credentials"].ready, fnv1.READY_TRUE)


if __name__ == "__main__":
    unittest.main()
