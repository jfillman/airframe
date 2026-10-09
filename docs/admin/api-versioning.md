# Airframe API versioning and deprecation

Every Airframe kind is `catalog.hangar.io/v1alpha1`. This page says what that promises, how a kind's
schema may change, and how a breaking change ships. It exists because Airframe's XRDs are consumed by
machines (agents, Glidepath, Tower, the tenants-repo validator) as well as by people (review C13).

## What v1alpha1 promises today

- **Additive changes ship without a version bump.** A new optional field, a new enum value, a new status
  field, a new printer column, a looser constraint. Existing XR requests stay valid.
- **Tightening is a breaking change**, even inside v1alpha1: a new required field, a removed field or
  enum value, a narrower pattern or length limit, a new CEL rule. Before one ships, every live XR request
  on every cluster must already satisfy it (check with `tools/airframe-validate --xr` over both tenants
  repos and the live XRs), because the API server applies the new schema to every later update of an
  existing object.
- **Field names never change meaning.** Rename by adding the new field, reading both in the composition,
  migrating requests, then removing the old one as a tightening change.
- **The composition is not the API.** A composition may change freely as long as the sidecar contract
  (`xrds/<kind>.meta.yaml`: outputs, conditions, verify) still holds; `tools/test_sidecars.py` enforces
  that in CI.

## Shipping a new version (v1beta1, v1)

Crossplane XRDs support several versions at once but have no conversion webhook: every served version
must share one schema shape. So a version bump is a rename-free promotion, never a reshape:

1. Add the new version to the XRD with the same schema, `served: true`, `referenceable: false`.
2. Release, pin, and let `tools/airframe-validate --xr` accept both apiVersions.
3. Flip `referenceable` to the new version (the storage version), and mark the old one
   `deprecated: true` with a `deprecationWarning` that names the replacement. The API server then warns
   every client that still writes it.
4. Migrate every XR request in the tenants repos and every chart template to the new apiVersion.
5. Stop serving the old version (`served: false`) one release later, then remove it.

A real reshape (moving or retyping fields) is a new kind or a new group, migrated with the
delete-old/create-new recipe the Tier 2 domain rename used; see
`hangar/docs/` and the RepositoryFile safety rules in each composition's AGENTS.md before any prune.

## Constraints every kind carries

- `defaultCompositionRef` names the kind's one Composition, so an XR that names none is deterministic.
- `metadata.name` is length-limited where a derived name would overflow a 63-character Kubernetes name
  or label (Helm release names, `<name>-tektoncicd`, CloudNativePG Jobs, operator StatefulSets). Each limit
  states its reason in the XRD; the ApplicationEnvironment and TektonCICD specs carry CEL rules for the
  `app-<app>-<env>` and `app-<app>-cicd` namespaces they derive.
- Printer columns show each kind's custom condition (`kubectl get <kind>` shows ComponentReady,
  TargetReady, CicdOnboarded, ClusterReady/AppResolved or the rollout phase).
- Attach-mode kinds (RabbitMQ, Dex) compose a Crossplane `Usage` that blocks deleting the broker or
  server they attach to while they exist.

## Checking a change before it ships

- `python3 tools/test_xr_validate.py` lints every XRD for the structural-schema rules the API server
  enforces (a schema it refuses leaves the live CRD frozen while the XRD still reports Established).
- After the pin syncs, compare the XRD with its CRD:
  `kubectl get events --field-selector involvedObject.name=<plural>.catalog.hangar.io,reason=EstablishComposite`.
