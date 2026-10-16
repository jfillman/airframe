# Keyless cloud deploys: diagrams

The figures in [cloud-credentials.md](../../cloud-credentials.md). Each one is a standalone HTML file (the source,
Hangar's diagram-design profile) with a 2x PNG rendered from it; the docs embed the PNGs because TechDocs won't serve
standalone HTML.

| File | Shows |
|---|---|
| `01-before` | The two long-lived AWS keys and everywhere they were copied |
| `02-token-exchange` | How a pod's ServiceAccount token becomes a one-hour AWS session |
| `03-trust-chain` | Issuer, published keys, IAM identity provider and roles, with the permissions boundary |
| `04-guardrails` | The six independent checks on a keyless deploy |
| `05-deploy-credentials` | How Glidepath's deploy step chooses between the role and the stored key |
| `06-incident` | 2026-10-16: the federation switch deleted and re-created smoke-fn's function |

Regenerate: `python3 gen.py <out-dir>` writes the HTML files; render PNGs with any headless browser at
`deviceScaleFactor: 2`, screenshotting the `<svg>` element.
