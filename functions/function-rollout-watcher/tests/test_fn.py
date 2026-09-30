"""Behavioural tests for the RolloutWatch function's diagnosis-Job handling.

Replaces the untouched function-template test (it asserted an S3 Bucket output and
could never pass against this function).
"""

import datetime
import unittest

from crossplane.function import logging, resource
from crossplane.function.proto.v1 import run_function_pb2 as fnv1

from function import fn

JOB_KEY = "diagnosis-job-7466d56885"


def make_req(  # noqa: PLR0913
    phase,
    revision="7466d56885",
    last_revision=None,
    last_job=None,
    last_time=None,
    job_observed=False,
):
    status = {}
    if last_revision:
        status["lastDiagnosisRevision"] = last_revision
    if last_job:
        status["lastDiagnosisJob"] = last_job
    if last_time:
        status["lastDiagnosisTime"] = last_time
    xr = {
        "apiVersion": "catalog.hangar.io/v1alpha1",
        "kind": "RolloutWatch",
        "metadata": {"name": "baggage-api", "namespace": "app-baggage-api-staging"},
        "spec": {"appName": "baggage-api", "cluster": "kind-prod", "env": "staging"},
        "status": status,
    }
    rollout = {
        "apiVersion": "argoproj.io/v1alpha1",
        "kind": "Rollout",
        "metadata": {"name": "baggage-api"},
        "status": {"phase": phase, "currentPodHash": revision},
    }
    req = fnv1.RunFunctionRequest(
        observed=fnv1.State(
            composite=fnv1.Resource(resource=resource.dict_to_struct(xr))
        ),
        required_resources={
            fn.ROLLOUT_REQUIREMENT_NAME: fnv1.Resources(
                items=[fnv1.Resource(resource=resource.dict_to_struct(rollout))]
            )
        },
    )
    if job_observed:
        req.observed.resources[JOB_KEY].CopyFrom(
            fnv1.Resource(
                resource=resource.dict_to_struct(
                    {
                        "apiVersion": "batch/v1",
                        "kind": "Job",
                        "metadata": {"name": "diagnosis-baggage-api-7466d56885"},
                        "spec": {"template": {"spec": {"containers": [{"name": "x"}]}}},
                    }
                )
            )
        )
    return req


def ago(seconds):
    t = datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=seconds)
    return t.isoformat()


class TestDiagnosisJobHandling(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        logging.configure(level=logging.Level.DISABLED)
        self.runner = fn.FunctionRunner()

    async def run_fn(self, req):
        return await self.runner.RunFunction(req, None)

    async def test_first_degraded_revision_dispatches_a_full_job(self) -> None:
        rsp = await self.run_fn(make_req("Degraded"))
        job = resource.struct_to_dict(rsp.desired.resources[JOB_KEY].resource)
        # A newly dispatched Job carries a real pod template.
        self.assertTrue(job["spec"]["template"]["spec"]["containers"])
        self.assertEqual(job["spec"]["template"]["spec"]["restartPolicy"], "Never")

    async def test_degraded_same_revision_keeps_an_observed_job(self) -> None:
        req = make_req(
            "Degraded",
            last_revision="7466d56885",
            last_job="diagnosis-baggage-api-7466d56885",
            last_time=ago(3600),
            job_observed=True,
        )
        rsp = await self.run_fn(req)
        self.assertIn(JOB_KEY, rsp.desired.resources)
        job = resource.struct_to_dict(rsp.desired.resources[JOB_KEY].resource)
        # Bare identity only: no spec, so the immutable template is never re-submitted.
        self.assertNotIn("spec", job)

    async def test_degraded_same_revision_does_not_redeclare_a_vanished_job(
        self,
    ) -> None:
        # The Job was dispatched long ago and has since been removed (TTL / GC).
        # Re-declaring a spec-less Job would wedge the XR at "containers: Required value".
        req = make_req(
            "Degraded",
            last_revision="7466d56885",
            last_job="diagnosis-baggage-api-7466d56885",
            last_time=ago(3600),
            job_observed=False,
        )
        rsp = await self.run_fn(req)
        self.assertNotIn(JOB_KEY, rsp.desired.resources)
        # Nothing re-dispatches for an already-diagnosed revision.
        status = resource.struct_to_dict(rsp.desired.composite.resource)["status"]
        self.assertEqual(status["lastDiagnosisRevision"], "7466d56885")
        self.assertEqual(status["rolloutPhase"], "Degraded")

    async def test_just_dispatched_job_is_kept_even_if_not_yet_observed(self) -> None:
        # Crossplane prunes a composed resource the instant it stops being declared, so a
        # lagging observed read right after dispatch must not delete a live Job.
        req = make_req(
            "Degraded",
            last_revision="7466d56885",
            last_job="diagnosis-baggage-api-7466d56885",
            last_time=ago(10),
            job_observed=False,
        )
        rsp = await self.run_fn(req)
        self.assertIn(JOB_KEY, rsp.desired.resources)

    async def test_grace_window_expires(self) -> None:
        req = make_req(
            "Degraded",
            last_revision="7466d56885",
            last_job="diagnosis-baggage-api-7466d56885",
            last_time=ago(fn.DISPATCH_GRACE_SECONDS + 30),
            job_observed=False,
        )
        rsp = await self.run_fn(req)
        self.assertNotIn(JOB_KEY, rsp.desired.resources)

    async def test_recovery_clears_tracking_and_drops_the_job(self) -> None:
        req = make_req(
            "Healthy",
            last_revision="7466d56885",
            last_job="diagnosis-baggage-api-7466d56885",
            last_time=ago(3600),
            job_observed=True,
        )
        rsp = await self.run_fn(req)
        self.assertNotIn(JOB_KEY, rsp.desired.resources)
        status = resource.struct_to_dict(rsp.desired.composite.resource)["status"]
        self.assertNotIn("lastDiagnosisRevision", status)
        self.assertNotIn("lastDiagnosisJob", status)

    async def test_new_degraded_revision_after_an_old_one_dispatches_again(
        self,
    ) -> None:
        req = make_req(
            "Degraded",
            revision="newhash123",
            last_revision="7466d56885",
            last_job="diagnosis-baggage-api-7466d56885",
            last_time=ago(3600),
        )
        rsp = await self.run_fn(req)
        self.assertIn("diagnosis-job-newhash123", rsp.desired.resources)
        job = resource.struct_to_dict(
            rsp.desired.resources["diagnosis-job-newhash123"].resource
        )
        self.assertTrue(job["spec"]["template"]["spec"]["containers"])


class TestRecentlyDispatched(unittest.TestCase):
    def test_missing_or_garbage_timestamp_is_not_recent(self) -> None:
        self.assertFalse(fn.recently_dispatched({}))
        self.assertFalse(fn.recently_dispatched({"lastDiagnosisTime": "not-a-time"}))

    def test_naive_timestamp_is_treated_as_utc(self) -> None:
        naive = (
            datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=5)
        ).replace(tzinfo=None)
        self.assertTrue(fn.recently_dispatched({"lastDiagnosisTime": naive.isoformat()}))


if __name__ == "__main__":
    unittest.main()
