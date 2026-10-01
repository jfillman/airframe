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
    """A minimal, real gRPC server for CreateClient - not a mock of fn.py's own call, a real
    server the real generated stub talks to over a real (loopback) socket."""

    def __init__(self):
        self.created = {}

    def CreateClient(self, request, context):  # noqa: N802 - gRPC's own method name.
        c = request.client
        already = c.id in self.created
        self.created[c.id] = c
        return dexpb.CreateClientResp(already_exists=already, client=c)


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
            req = fnv1.RunFunctionRequest(
                observed=fnv1.State(
                    composite=fnv1.Resource(resource=xr(
                        "attach", serverRef={"name": "srv", "namespace": "srv-ns"},
                    )),
                ),
            )
            orig = fn.dex_grpc_address
            fn.dex_grpc_address = lambda ref: server.address  # noqa: ARG005
            try:
                r1 = await fn.FunctionRunner().RunFunction(req, None)
                r2 = await fn.FunctionRunner().RunFunction(req, None)
            finally:
                fn.dex_grpc_address = orig
            self.assertEqual(r1.conditions[0].reason, "DexAttachReady")
            self.assertEqual(r2.conditions[0].reason, "DexAttachReady")
            self.assertEqual(len(server.servicer.created), 1)  # one client, registered twice

    async def test_attach_mode_reports_failure_when_the_server_is_unreachable(self):
        req = fnv1.RunFunctionRequest(
            observed=fnv1.State(
                composite=fnv1.Resource(resource=xr(
                    "attach", serverRef={"name": "nope", "namespace": "nowhere"},
                )),
            ),
        )
        orig = fn.dex_grpc_address
        fn.dex_grpc_address = lambda ref: "127.0.0.1:1"  # nothing listens here
        try:
            rsp = await asyncio.wait_for(fn.FunctionRunner().RunFunction(req, None), timeout=10)
        finally:
            fn.dex_grpc_address = orig
        self.assertEqual(rsp.conditions[0].reason, "DexAttachFailed")
        self.assertEqual(rsp.conditions[0].status, fnv1.STATUS_CONDITION_FALSE)
        self.assertNotIn("oauth-credentials", rsp.desired.resources)


if __name__ == "__main__":
    unittest.main()
