# Airframe

The structural core: what a compliant service is, defined once.

Crossplane XRDs, Compositions, Composition Functions, and the
`airframe-application` Helm chart for [Hangar](https://github.com/jfillman/hangar)
— the service catalog a Backstage-driven Crossplane plugin turns into self-service
templates.

- **New here?** Start with the [user guide](user/README.md) — create a service,
  give it environments, attach it to Redis.
- **Running or extending the catalog?** See the [admin guide](admin/README.md)
  for the composition graph and the plumbing underneath.
- **Architect or security reviewer?** [governance.md](admin/governance.md) is the
  map of who decides what, where each policy is enforced, and what is still convention;
  [cloud-credentials.md](admin/cloud-credentials.md) is the identity map behind the cloud targets.
- **Design history and open decisions** live in `hangar`'s own
  [`docs/service-catalog-design.md`](https://github.com/jfillman/hangar/blob/main/docs/service-catalog-design.md).
