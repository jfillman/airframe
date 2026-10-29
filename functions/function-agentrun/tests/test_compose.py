"""compose() without a cluster: rendering, network modes, expiry, failing closed, lifecycle. Run from
functions/function-agentrun: python3 -m unittest tests.test_compose tests.test_fn (CI: the compositions job of
.github/workflows/airframe-chart-ci.yaml)."""
import copy
import json
import unittest
from datetime import datetime, timedelta, timezone

from function.compose import (FINAL_PHASES, REASONS, ClusterConfig, ComputeClassCfg, compose, iso, sandbox_phase)

T0 = datetime(2026, 9, 26, 12, 0, 0, tzinfo=timezone.utc)
DIGEST = "ghcr.io/jfillman/agent-x@sha256:" + "0" * 64
READY_REGISTRY = {"type": "dev", "autopilotReady": "true", "cicdReady": "true"}
OBSERVED = {"cluster": "example-dev", "registry": READY_REGISTRY}


def xr(name="r-1a2b3c", namespace="autopilot-runs", **spec):
    base = {
        "agent": "coding-agent", "image": DIGEST, "framework": "generic", "sandbox": "standard", "compute": "small",
        "network": {"mode": "clearance+model"}, "expiresAt": iso(T0 + timedelta(minutes=30)),
        "taskId": "t-1a2b3c", "sessionId": "s-1a2b3c",
        "limits": {"toolCalls": 100, "githubCalls": 50, "modelTokens": 1000},
    }
    base.update(spec)
    return {"apiVersion": "catalog.hangar.io/v1alpha1", "kind": "AgentRun",
            "metadata": {"name": name, "namespace": namespace, "creationTimestamp": iso(T0)},
            "spec": base}


def sandbox(ready=None, finished=None, at=None):
    conds = []
    if ready is not None:
        conds.append({"type": "Ready", "status": "True" if ready else "False",
                      "reason": "DependenciesReady" if ready else "DependenciesNotReady"})
    if finished:
        conds.append({"type": "Finished", "status": "True", "reason": finished, "lastTransitionTime": iso(at)})
    return {"apiVersion": "agents.x-k8s.io/v1beta1", "kind": "Sandbox", "status": {"conditions": conds}}


def run(x=None, observed=None, now=T0, cfg=None):
    obs = {**OBSERVED, **(observed or {})}
    return compose(x or xr(), obs, now, cfg or ClusterConfig())


def manifest(comp, key):
    return comp.resources[key]["spec"]["forProvider"]["manifest"]


def pod(comp):
    return manifest(comp, "sandbox")["spec"]["podTemplate"]["spec"]


def env(comp):
    return {e["name"]: e["value"] for e in pod(comp)["containers"][0]["env"]}


class Rendering(unittest.TestCase):
    def test_a_normal_run_renders_six_objects_and_is_provisioning_until_the_sandbox_is_ready(self):
        c = run()
        self.assertEqual(set(c.resources), {"namespace", "quota", "netpol-default-deny", "netpol-egress",
                                            "serviceaccount", "sandbox"})
        self.assertEqual(c.status["phase"], "Provisioning")
        self.assertEqual(c.condition[:3], ("RunReady", "False", "AgentRunProvisioning"))
        for r in c.resources.values():
            self.assertEqual((r["apiVersion"], r["kind"]), ("kubernetes.m.crossplane.io/v1alpha1", "Object"))
            self.assertEqual(r["spec"]["providerConfigRef"], {"kind": "ClusterProviderConfig", "name": "default"})
        c2 = run(observed={"sandbox": sandbox(ready=True)})
        self.assertEqual(c2.status["phase"], "Running")
        self.assertEqual(c2.condition[:3], ("RunReady", "True", "AgentRunRunning"))

    def test_the_sandbox_carries_the_hard_deadline_and_deletes_itself(self):
        sb = manifest(run(), "sandbox")
        self.assertEqual((sb["apiVersion"], sb["kind"]), ("agents.x-k8s.io/v1beta1", "Sandbox"))
        self.assertEqual(sb["spec"]["shutdownTime"], iso(T0 + timedelta(minutes=30)))
        self.assertEqual(sb["spec"]["shutdownPolicy"], "Delete")
        self.assertEqual(sb["spec"]["failedPodPolicy"], "Retain")
        self.assertIs(sb["spec"]["service"], False)
        self.assertEqual(run().resources["sandbox"]["spec"]["readiness"], {"policy": "DeriveFromObject"})

    def test_namespace_is_pod_security_restricted_and_never_carries_the_pr_sweep_label(self):
        ns = manifest(run(), "namespace")
        self.assertEqual(ns["metadata"]["name"], "agent-r-1a2b3c")
        self.assertEqual(ns["metadata"]["labels"]["pod-security.kubernetes.io/enforce"], "restricted")
        self.assertNotIn("hangar.io/ephemeral-env", ns["metadata"]["labels"], "the PR TTL sweep would reap live runs")
        self.assertEqual(ns["metadata"]["labels"]["hangar.io/agent-run"], "true")
        for r in run().resources.values():
            self.assertNotIn("hangar.io/ephemeral-env", json.dumps(r))

    def test_default_deny_always_present_and_quota_forbids_secrets_services_jobs(self):
        c = run()
        self.assertEqual(manifest(c, "netpol-default-deny")["spec"]["policyTypes"], ["Ingress", "Egress"])
        hard = manifest(c, "quota")["spec"]["hard"]
        self.assertEqual((hard["count/secrets"], hard["count/services"], hard["count/jobs.batch"]), ("0", "0", "0"))
        self.assertEqual(hard["count/sandboxes.agents.x-k8s.io"], "1")
        self.assertEqual(hard["persistentvolumeclaims"], "0")

    def test_quota_covers_the_sidecars_or_the_pod_would_be_refused(self):
        hard = manifest(run(xr(sidecars=[{"name": "tools", "image": DIGEST}, {"name": "mcp", "image": DIGEST}])),
                        "quota")["spec"]["hard"]
        # small: 250m/512Mi requests, 1/1Gi limits; each sidecar 50m/64Mi requests, 500m/512Mi limits
        self.assertEqual((hard["requests.cpu"], hard["requests.memory"]), ("350m", "640Mi"))
        self.assertEqual((hard["limits.cpu"], hard["limits.memory"]), ("2", "2Gi"))
        alone = manifest(run(), "quota")["spec"]["hard"]
        self.assertEqual((alone["limits.cpu"], alone["limits.memory"]), ("1", "1Gi"))

    def test_pod_is_locked_down(self):
        p = pod(run())
        ctr = p["containers"][0]
        self.assertEqual(p["serviceAccountName"], "run")
        self.assertIs(p["automountServiceAccountToken"], False)
        self.assertEqual(p["restartPolicy"], "Never")
        sc = ctr["securityContext"]
        self.assertTrue(sc["runAsNonRoot"] and sc["readOnlyRootFilesystem"])
        self.assertEqual(sc["capabilities"], {"drop": ["ALL"]})
        self.assertIs(sc["allowPrivilegeEscalation"], False)
        self.assertEqual(sc["seccompProfile"], {"type": "RuntimeDefault"})
        self.assertNotIn("runtimeClassName", p)
        self.assertTrue(ctr["image"].endswith("@sha256:" + "0" * 64))
        self.assertFalse(any("KEY" in e["name"] or "SECRET" in e["name"] for e in ctr["env"]))
        sa = manifest(run(), "serviceaccount")
        self.assertEqual((sa["metadata"]["name"], sa["automountServiceAccountToken"]), ("run", False))

    def test_env_contract(self):
        e = env(run())
        for k in ("HANGAR_RUN_ID", "HANGAR_TASK_ID", "HANGAR_SESSION_ID", "HANGAR_AGENT", "HANGAR_EXPIRES_AT",
                  "HANGAR_OUTPUT_DIR", "HANGAR_WORKSPACE", "HANGAR_LIMITS", "CLEARANCE_URL", "MODEL_PROXY_URL"):
            self.assertIn(k, e)
        self.assertEqual(json.loads(e["HANGAR_LIMITS"])["toolCalls"], 100)
        self.assertEqual(e["CLEARANCE_URL"], "http://clearance.autopilot-system.svc:8080")

    def test_numbers_that_came_through_protobuf_as_doubles_stay_integers(self):
        x = xr(limits={"toolCalls": 100.0, "githubCalls": 50.0, "modelTokens": 1000.0}, input={"n": 3.0, "f": 0.5})
        e = env(run(x))
        self.assertEqual(e["HANGAR_LIMITS"], '{"githubCalls":50,"modelTokens":1000,"toolCalls":100}')
        self.assertEqual(e["HANGAR_INPUT"], '{"f":0.5,"n":3}')
        cfg = ClusterConfig.from_input({"clearance_port": 8080.0, "max_ttl_minutes": 60.0})
        self.assertEqual(env(run(cfg=cfg))["CLEARANCE_URL"], "http://clearance.autopilot-system.svc:8080")

    def test_output_is_deterministic(self):
        self.assertEqual(json.dumps(run().resources, sort_keys=True), json.dumps(run().resources, sort_keys=True))
        later = run(now=T0 + timedelta(minutes=10))
        self.assertEqual(json.dumps(run().resources, sort_keys=True), json.dumps(later.resources, sort_keys=True),
                         "the template must not change between reconciles, or provider-kubernetes updates it every minute")

    def test_object_readiness_comes_from_the_observed_objects(self):
        c = run(observed={"objects": {"namespace": True, "sandbox": False}})
        self.assertTrue(c.ready["namespace"])
        self.assertFalse(c.ready["sandbox"])
        self.assertFalse(c.ready["quota"])


class NetworkModes(unittest.TestCase):
    @staticmethod
    def egress(c):
        return manifest(c, "netpol-egress")["spec"]["egress"] if "netpol-egress" in c.resources else []

    @staticmethod
    def audiences(c):
        return [s["serviceAccountToken"]["audience"] for v in pod(c)["volumes"] if "projected" in v
                for s in v["projected"]["sources"]]

    def test_none_has_no_egress_and_no_urls_or_tokens(self):
        c = run(xr(network={"mode": "none"}))
        self.assertNotIn("netpol-egress", c.resources)
        self.assertEqual(self.audiences(c), [])
        self.assertFalse({"CLEARANCE_URL", "MODEL_PROXY_URL"} & set(env(c)))

    def test_clearance_reaches_dns_and_the_gateway_only(self):
        c = run(xr(network={"mode": "clearance"}))
        self.assertEqual(len(self.egress(c)), 2)
        self.assertEqual(self.audiences(c), ["clearance"])
        self.assertNotIn("MODEL_PROXY_URL", env(c))

    def test_clearance_model_adds_the_model_proxy_and_its_token(self):
        c = run()
        self.assertEqual(len(self.egress(c)), 3)
        self.assertEqual(self.audiences(c), ["clearance", "model-proxy"])

    def test_allowlist_adds_only_the_listed_cidrs(self):
        c = run(xr(network={"mode": "allowlist", "allowCidrs": ["203.0.113.0/24"]}))
        self.assertEqual(self.egress(c)[-1], {"to": [{"ipBlock": {"cidr": "203.0.113.0/24"}}]})

    def test_bad_network_requests_are_rejected_and_render_nothing(self):
        for net in ({"mode": "allowlist"}, {"mode": "allowlist", "allowCidrs": []},
                    {"mode": "allowlist", "allowCidrs": ["0.0.0.0/0"]}, {"mode": "allowlist", "allowCidrs": ["127.0.0.0/8"]},
                    {"mode": "allowlist", "allowCidrs": ["169.254.0.0/16"]}, {"mode": "clearance", "allowCidrs": ["10.0.0.0/8"]}):
            with self.subTest(net=net):
                c = run(xr(network=net))
                self.assertEqual((c.status["phase"], c.resources), ("Rejected", {}))


class Expiry(unittest.TestCase):
    """The dead-man property: nothing but the clock and the XR decides when a run ends."""

    def test_expiry_renders_nothing_so_crossplane_removes_everything(self):
        e = T0 + timedelta(minutes=30)
        self.assertTrue(run(now=e - timedelta(seconds=1)).resources)
        c = run(now=e)
        self.assertEqual((c.resources, c.status["phase"]), ({}, "Expired"))
        self.assertEqual(c.condition[:3], ("RunReady", "False", "AgentRunExpired"))
        self.assertEqual(run(now=e + timedelta(days=3)).resources, {})

    def test_expiry_needs_nothing_observed(self):
        """No gateway, no Sandbox status, no registry answer: an XR nobody is tending still dies on schedule."""
        c = compose(xr(), {}, T0 + timedelta(hours=1), ClusterConfig())
        self.assertEqual(c.resources, {})

    def test_pod_deadline_is_anchored_to_creation_so_it_does_not_drift(self):
        a = pod(run(now=T0))["activeDeadlineSeconds"]
        b = pod(run(now=T0 + timedelta(minutes=10)))["activeDeadlineSeconds"]
        self.assertEqual((a, b), (1800, 1800))

    def test_ttl_over_the_cluster_cap_is_rejected(self):
        c = run(xr(expiresAt=iso(T0 + timedelta(minutes=241))))
        self.assertEqual((c.status["phase"], c.resources), ("Rejected", {}))
        self.assertIn("cap", c.status["reason"])
        self.assertTrue(run(xr(expiresAt=iso(T0 + timedelta(minutes=240)))).resources)

    def test_response_ttl_is_bounded_and_shrinks_near_expiry(self):
        self.assertEqual(run().ttl_seconds, 60)
        self.assertEqual(run(now=T0 + timedelta(minutes=29, seconds=52)).ttl_seconds, 10)


class FailClosed(unittest.TestCase):
    def test_no_autopilot_ready_flag_is_rejected(self):
        for reg, word in (({"type": "dev"}, "autopilotReady"), ({"type": "upper", "autopilotReady": "true"}, "control-plane"),
                          (None, "no cluster registry record")):
            with self.subTest(reg=reg):
                c = run(observed={"registry": reg})
                self.assertEqual((c.status["phase"], c.resources), ("Rejected", {}))
                self.assertIn(word, c.status["reason"])
                self.assertEqual(c.condition[:3], ("RunReady", "False", "AgentRunRejected"))

    def test_an_unknown_cluster_name_is_rejected(self):
        c = run(observed={"cluster": ""})
        self.assertEqual(c.status["phase"], "Rejected")
        self.assertIn("HANGAR_CLUSTER_NAME", c.status["reason"])

    def test_hardened_without_a_runtime_class_is_rejected_never_downgraded(self):
        c = run(xr(sandbox="hardened"))
        self.assertEqual((c.status["phase"], c.resources), ("Rejected", {}))
        self.assertIn("runtime class", c.status["reason"])

    def test_hardened_with_a_runtime_class_sets_it(self):
        cfg = ClusterConfig(runtime_classes={"hardened": "gvisor"})
        self.assertEqual(pod(run(xr(sandbox="hardened"), cfg=cfg))["runtimeClassName"], "gvisor")

    def test_a_compute_class_the_cluster_lacks_is_rejected(self):
        self.assertEqual(run(xr(compute="gpu")).status["phase"], "Rejected")
        cfg = ClusterConfig()
        cfg.compute["gpu"] = ComputeClassCfg({"cpu": "4", "memory": "16Gi"}, {"cpu": "8", "memory": "32Gi"},
                                             {"nvidia.com/gpu.present": "true"},
                                             [{"key": "nvidia.com/gpu", "operator": "Exists"}])
        p = pod(run(xr(compute="gpu"), cfg=cfg))
        self.assertEqual(p["nodeSelector"], {"nvidia.com/gpu.present": "true"})
        self.assertTrue(p["tolerations"])

    def test_oversized_input_is_rejected_and_small_input_is_passed(self):
        self.assertEqual(run(xr(input={"blob": "x" * 5000})).status["phase"], "Rejected")
        self.assertEqual(json.loads(env(run(xr(input={"q": "hello"})))["HANGAR_INPUT"]), {"q": "hello"})

    def test_wrong_name_or_namespace_is_rejected(self):
        self.assertEqual(run(xr(name="my-run")).status["phase"], "Rejected")
        self.assertEqual(run(xr(namespace="default")).status["phase"], "Rejected")

    def test_rejection_takes_precedence_and_nothing_is_created(self):
        c = run(xr(sandbox="hardened", compute="gpu"))
        self.assertEqual((c.resources, c.status["phase"]), ({}, "Rejected"))

    def test_an_unknown_input_key_fails_loudly(self):
        with self.assertRaises(ValueError):
            ClusterConfig.from_input({"max_ttl_minute": 10})
        self.assertEqual(ClusterConfig.from_input({"apiVersion": "x", "kind": "Config", "max_ttl_minutes": 10}).max_ttl_minutes, 10)


class Lifecycle(unittest.TestCase):
    def test_freeze_cuts_egress_keeps_the_run_for_forensics_then_expires(self):
        c = run(xr(frozen=True))
        self.assertEqual(c.status["phase"], "Frozen")
        self.assertNotIn("netpol-egress", c.resources)
        self.assertIn("sandbox", c.resources)
        self.assertTrue(manifest(c, "netpol-default-deny"))
        later = run(xr(frozen=True), observed={"status": {"frozenAt": c.status["frozenAt"]}},
                    now=T0 + timedelta(minutes=16))
        self.assertEqual((later.status["phase"], later.resources), ("Expired", {}))

    def test_a_finished_agent_drains_after_the_grace_period(self):
        done = {"sandbox": sandbox(ready=False, finished="PodSucceeded", at=T0 + timedelta(minutes=2))}
        c = run(observed=done, now=T0 + timedelta(minutes=3))
        self.assertEqual((c.status["phase"], c.status["outcome"]), ("Succeeded", "Succeeded"))
        self.assertTrue(c.resources)
        self.assertEqual(c.condition[:3], ("RunReady", "True", "AgentRunSucceeded"))
        d = run(observed=done, now=T0 + timedelta(minutes=8))
        self.assertEqual((d.status["phase"], d.resources, d.status["outcome"]), ("Drained", {}, "Succeeded"))

    def test_a_failed_agent_is_reported_and_drains(self):
        failed = {"sandbox": sandbox(ready=False, finished="PodFailed", at=T0 + timedelta(minutes=1))}
        self.assertEqual(run(observed=failed, now=T0 + timedelta(minutes=2)).status["phase"], "Failed")
        self.assertEqual(run(observed=failed, now=T0 + timedelta(minutes=7)).status["phase"], "Drained")

    def test_final_phases_never_render_again(self):
        """After a drain the Sandbox is gone; without this, the next reconcile would look like a new run."""
        for phase in FINAL_PHASES:
            with self.subTest(phase=phase):
                c = run(observed={"status": {"phase": phase, "reason": "earlier"}}, now=T0 + timedelta(minutes=1))
                self.assertEqual((c.status["phase"], c.resources), (phase, {}))

    def test_a_vanished_sandbox_after_finishing_keeps_the_outcome(self):
        prev = {"phase": "Succeeded", "finishedAt": iso(T0 + timedelta(minutes=2)), "outcome": "Succeeded"}
        c = run(observed={"status": prev, "sandbox": None}, now=T0 + timedelta(minutes=3))
        self.assertEqual(c.status["phase"], "Succeeded")
        self.assertEqual(run(observed={"status": prev}, now=T0 + timedelta(minutes=8)).status["phase"], "Drained")

    def test_sandbox_phase_mapping(self):
        self.assertEqual(sandbox_phase(None, T0)[0], "Provisioning")
        self.assertEqual(sandbox_phase(sandbox(ready=False), T0)[0], "Provisioning")
        self.assertEqual(sandbox_phase(sandbox(ready=True), T0)[0], "Running")

    def test_every_phase_has_a_reason_in_the_closed_set(self):
        self.assertEqual(set(REASONS), {"Provisioning", "Running", "Succeeded", "Failed", "Frozen", "Expired",
                                        "Drained", "Rejected"})
        self.assertEqual(len({r for r, _ in REASONS.values()}), len(REASONS))

    def test_sidecars_get_the_same_lockdown_and_no_agent_env(self):
        p = pod(run(xr(sidecars=[{"name": "tools", "image": DIGEST}])))
        sc = p["containers"][1]
        self.assertEqual(sc["name"], "tools")
        self.assertTrue(sc["securityContext"]["readOnlyRootFilesystem"])
        self.assertNotIn("env", sc)

    def test_the_xr_is_not_mutated(self):
        x = xr()
        before = copy.deepcopy(x)
        run(x)
        self.assertEqual(x, before)


if __name__ == "__main__":
    unittest.main()
