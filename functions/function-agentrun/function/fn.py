"""Thin protobuf wrapper around compose(). Every decision lives in compose.py.

What this file adds to the pure function:
  - which cluster it runs on: HANGAR_CLUSTER_NAME, from the Function's DeploymentRuntimeConfig (the gitops repo's
    10-crds-operators/crossplane/function-agentrun-runtime.yaml). The Composition is shared by every cluster, so the
    name cannot live there. Unset means Rejected.
  - the cluster registry record: a required-resources lookup of ConfigMap <cluster> in crossplane-system, the same
    record every Airframe composition's cluster gate reads (charts/cluster-registry). Until Crossplane has resolved
    the lookup, the function renders nothing and decides nothing; Crossplane calls it again in the same reconcile
    with the record, and only that answer is applied.
  - what is observed: the Sandbox as provider-kubernetes reports it (status.atProvider.manifest), and each Object's
    Ready condition, which becomes that composed resource's readiness.
"""
from __future__ import annotations

import datetime
import os

import grpc
from crossplane.function import logging, request, resource, response
from crossplane.function.proto.v1 import run_function_pb2 as fnv1
from crossplane.function.proto.v1 import run_function_pb2_grpc as grpcv1

from function.compose import ClusterConfig, compose

REGISTRY_REQUIREMENT = "cluster-registry"
CLUSTER_ENV = "HANGAR_CLUSTER_NAME"


def _object_ready(observed: fnv1.Resource) -> bool:
    for c in resource.struct_to_dict(observed.resource).get("status", {}).get("conditions", []) or []:
        if c.get("type") == "Ready":
            return c.get("status") == "True"
    return False


class FunctionRunner(grpcv1.FunctionRunnerService):
    def __init__(self, cluster: str | None = None) -> None:
        self.log = logging.get_logger()
        self.cluster = cluster if cluster is not None else os.environ.get(CLUSTER_ENV, "")

    async def RunFunction(self, req: fnv1.RunFunctionRequest, _: grpc.aio.ServicerContext) -> fnv1.RunFunctionResponse:
        rsp = response.to(req)
        xr = resource.struct_to_dict(req.observed.composite.resource)
        try:
            cfg = ClusterConfig.from_input(resource.struct_to_dict(req.input) if req.HasField("input") else {})
        except (ValueError, KeyError, TypeError) as e:
            response.fatal(rsp, f"function-agentrun: bad Composition input: {e}")
            return rsp

        if self.cluster:
            # Always declare the requirement: Crossplane treats requirements as satisfied once they are stable
            # between calls (crossplane.function.request.get_required_resources).
            response.require_resources(rsp, REGISTRY_REQUIREMENT, "v1", "ConfigMap",
                                       match_name=self.cluster, namespace=cfg.registry_namespace)
            if REGISTRY_REQUIREMENT not in req.required_resources:
                response.normal(rsp, "waiting for the cluster registry lookup")
                return rsp

        record = request.get_required_resource(req, REGISTRY_REQUIREMENT) if self.cluster else None
        observed: dict = {"status": xr.get("status", {}), "cluster": self.cluster,
                          "registry": (record or {}).get("data") if record is not None else None,
                          "objects": {name: _object_ready(r) for name, r in req.observed.resources.items()}}
        sb = req.observed.resources.get("sandbox")
        if sb is not None and sb.HasField("resource"):
            # provider-kubernetes reports the applied object, status included, under atProvider.
            observed["sandbox"] = (resource.struct_to_dict(sb.resource).get("status", {})
                                   .get("atProvider", {}).get("manifest"))

        comp = compose(xr, observed, datetime.datetime.now(datetime.timezone.utc), cfg)
        for name, manifest in comp.resources.items():
            rsp.desired.resources[name].resource.update(manifest)
            if comp.ready.get(name):
                rsp.desired.resources[name].ready = fnv1.READY_TRUE
        rsp.desired.composite.resource.update({"status": comp.status})
        typ, status, reason, message = comp.condition
        response.set_conditions(rsp, resource.Condition(typ=typ, status=status, reason=reason, message=message or None))
        # Status refresh only. Crossplane re-invokes about every 60 s whatever this says (roadmap U2); the deadline
        # is the Sandbox's shutdownTime.
        rsp.meta.ttl.FromTimedelta(datetime.timedelta(seconds=comp.ttl_seconds))
        phase = comp.status.get("phase")
        if phase == "Rejected":
            response.warning(rsp, f"AgentRun rejected: {comp.status.get('reason')}")
        else:
            response.normal(rsp, f"AgentRun {xr['metadata']['name']} phase={phase}")
        return rsp
