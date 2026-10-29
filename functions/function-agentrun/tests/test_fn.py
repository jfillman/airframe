"""The gRPC wrapper on the real SDK: the registry requirement round trip, observed Sandbox and Object readiness,
status and the RunReady condition. xrds/agentrun.meta.yaml names this file as the check for function-made objects."""
import unittest
from datetime import datetime, timedelta, timezone

from crossplane.function import logging, resource
from crossplane.function.proto.v1 import run_function_pb2 as fnv1

from function import fn

DIGEST = "ghcr.io/x/y@sha256:" + "0" * 64


def ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def request(expires_in_minutes=30, registry="ready", sandbox=None, objects=None, status=None):
    now = datetime.now(timezone.utc)
    xr = {
        "apiVersion": "catalog.hangar.io/v1alpha1", "kind": "AgentRun",
        "metadata": {"name": "r-1a2b3c", "namespace": "autopilot-runs", "creationTimestamp": ts(now - timedelta(minutes=1))},
        "spec": {"agent": "coding-agent", "image": DIGEST, "sandbox": "standard", "compute": "small",
                 "network": {"mode": "clearance"}, "expiresAt": ts(now + timedelta(minutes=expires_in_minutes)),
                 "taskId": "t-1a2b3c", "sessionId": "s-1a2b3c",
                 "limits": {"toolCalls": 1, "githubCalls": 1, "modelTokens": 1}},
    }
    if status:
        xr["status"] = status
    req = fnv1.RunFunctionRequest(observed=fnv1.State(composite=fnv1.Resource(resource=resource.dict_to_struct(xr))))
    if registry is not None:
        items = []
        if registry == "ready":
            items = [fnv1.Resource(resource=resource.dict_to_struct({
                "apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "example-dev", "namespace": "crossplane-system"},
                "data": {"type": "dev", "autopilotReady": "true"}}))]
        elif registry == "not-ready":
            items = [fnv1.Resource(resource=resource.dict_to_struct({
                "apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "example-dev", "namespace": "crossplane-system"},
                "data": {"type": "dev"}}))]
        req.required_resources["cluster-registry"].CopyFrom(fnv1.Resources(items=items))
    for name, ready in (objects or {}).items():
        o = {"apiVersion": "kubernetes.m.crossplane.io/v1alpha1", "kind": "Object",
             "status": {"conditions": [{"type": "Ready", "status": "True" if ready else "False"}]}}
        if name == "sandbox" and sandbox is not None:
            o["status"]["atProvider"] = {"manifest": sandbox}
        req.observed.resources[name].CopyFrom(fnv1.Resource(resource=resource.dict_to_struct(o)))
    return req


def status_of(rsp):
    return resource.struct_to_dict(rsp.desired.composite.resource)["status"]


def condition(rsp, typ="RunReady"):
    return [c for c in rsp.conditions if c.type == typ]


class TestFn(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        logging.configure(level=logging.Level.DISABLED)
        self.runner = fn.FunctionRunner(cluster="example-dev")

    async def test_first_call_asks_for_the_registry_record_and_renders_nothing(self):
        rsp = await self.runner.RunFunction(request(registry=None), None)
        sel = rsp.requirements.resources["cluster-registry"]
        self.assertEqual((sel.api_version, sel.kind, sel.match_name, sel.namespace),
                         ("v1", "ConfigMap", "example-dev", "crossplane-system"))
        self.assertEqual(len(rsp.desired.resources), 0)
        self.assertFalse(condition(rsp))

    async def test_live_run_desires_the_sandbox_and_sets_status(self):
        rsp = await self.runner.RunFunction(request(), None)
        self.assertEqual(set(rsp.desired.resources), {"namespace", "quota", "netpol-default-deny", "netpol-egress",
                                                      "serviceaccount", "sandbox"})
        st = status_of(rsp)
        self.assertEqual((st["phase"], st["namespace"], st["cluster"]), ("Provisioning", "agent-r-1a2b3c", "example-dev"))
        c = condition(rsp)[0]
        self.assertEqual((c.status, c.reason), (fnv1.STATUS_CONDITION_FALSE, "AgentRunProvisioning"))
        self.assertLessEqual(rsp.meta.ttl.seconds, 60)
        # the requirement is still declared, so Crossplane sees it stable between calls
        self.assertIn("cluster-registry", rsp.requirements.resources)

    async def test_observed_sandbox_ready_is_running_and_objects_carry_readiness(self):
        sb = {"apiVersion": "agents.x-k8s.io/v1beta1", "kind": "Sandbox",
              "status": {"conditions": [{"type": "Ready", "status": "True", "reason": "DependenciesReady"}]}}
        rsp = await self.runner.RunFunction(request(sandbox=sb, objects={"namespace": True, "sandbox": True, "quota": False}), None)
        self.assertEqual(status_of(rsp)["phase"], "Running")
        self.assertEqual(rsp.desired.resources["namespace"].ready, fnv1.READY_TRUE)
        self.assertEqual(rsp.desired.resources["sandbox"].ready, fnv1.READY_TRUE)
        self.assertNotEqual(rsp.desired.resources["quota"].ready, fnv1.READY_TRUE)
        self.assertEqual(condition(rsp)[0].reason, "AgentRunRunning")

    async def test_expired_run_desires_nothing(self):
        rsp = await self.runner.RunFunction(request(-5), None)
        self.assertEqual(len(rsp.desired.resources), 0)
        self.assertEqual(status_of(rsp)["phase"], "Expired")
        self.assertEqual(condition(rsp)[0].reason, "AgentRunExpired")

    async def test_a_cluster_without_autopilot_ready_is_rejected(self):
        for reg in ("not-ready", "missing"):
            with self.subTest(registry=reg):
                rsp = await self.runner.RunFunction(request(registry=reg), None)
                self.assertEqual(len(rsp.desired.resources), 0)
                self.assertEqual(status_of(rsp)["phase"], "Rejected")
                self.assertEqual(condition(rsp)[0].reason, "AgentRunRejected")
                self.assertTrue(any(r.severity == fnv1.SEVERITY_WARNING for r in rsp.results))

    async def test_no_cluster_name_is_rejected_without_a_lookup(self):
        rsp = await fn.FunctionRunner(cluster="").RunFunction(request(registry=None), None)
        self.assertNotIn("cluster-registry", rsp.requirements.resources)
        self.assertEqual(status_of(rsp)["phase"], "Rejected")
        self.assertIn("HANGAR_CLUSTER_NAME", status_of(rsp)["reason"])

    async def test_a_drained_run_stays_drained_with_its_sandbox_gone(self):
        rsp = await self.runner.RunFunction(request(status={"phase": "Drained", "reason": "agent succeeded"}), None)
        self.assertEqual(len(rsp.desired.resources), 0)
        self.assertEqual(status_of(rsp)["phase"], "Drained")

    async def test_bad_input_is_fatal(self):
        req = request()
        req.input.update({"max_ttl_minute": 5})
        rsp = await self.runner.RunFunction(req, None)
        self.assertTrue(any(r.severity == fnv1.SEVERITY_FATAL for r in rsp.results))


if __name__ == "__main__":
    unittest.main()
