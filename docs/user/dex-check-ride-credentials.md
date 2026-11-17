# Dex credentials for a check ride

An app that attaches the `Dex` component (`mode: attach`) gets an OAuth client and a Secret,
`<name>-oauth-credentials`, in its environment namespace. The app's API then wants a bearer token. The
app's check ride (the integration test Glidepath's test stage runs through Testkube) needs a token too,
and it cannot read the environment namespace. This page is how it gets the credentials without anyone
creating or copying a Secret.

## What you declare

One block on the Dex component of the environment whose test stage runs the check ride (the dev
environment, normally):

```yaml title="baggage-api: glidepath/envs/dev.yaml"
components:
  - type: dex
    name: dex
    spec:
      mode: attach
      serverRef: { name: skyport-auth, namespace: infra-skyport-auth-dev }
      checkRide:
        namespace: app-baggage-api-cicd      # the app's CI namespace: app-<app>-cicd
```

It is off unless `checkRide` is set. Set it on one environment per CI namespace: two Dex components
would write the same Secret. If two do (dev and qa), the one with the lowest `namespace/name` publishes and the
other publishes nothing and raises a Warning event naming the winner, so they never fight; remove `checkRide`
from the one you do not want.

## What Airframe does

Next to `<name>-oauth-credentials`, `function-dex` composes a provider-kubernetes `Object`,
`<name>-check-ride-credentials`. It keeps a Secret `dex-check-ride-credentials` in the CI namespace equal to
the environment's credentials:

| Key in `dex-check-ride-credentials` | Copied from `<name>-oauth-credentials` |
| --- | --- |
| `DEX_TOKEN_URL` | `token-url` |
| `DEX_CLIENT_ID` | `client-id` |
| `DEX_CLIENT_SECRET` | `client-secret` |

- The values are copied by provider-kubernetes at apply time (`references.patchesFrom`). They are never in a
  manifest, a function payload or git.
- Rotation: when the credentials Secret changes (the function adopts the Dex server's secret, or the client is
  recreated), the copy follows on the Object's next reconcile. Nobody acts.
- Removal: detaching the Dex component, or removing `checkRide`, removes the Object and with it the copy.
- A Dex outage keeps the copy, as it keeps the credentials Secret.
- The only namespace it will write to is `app-<app>-cicd`, where `<app>` comes from the `hangar.io/app` label
  airframe-application stamps on the XR (from the platform-owned `appName`, which Glidepath injects), never
  from anything in `spec`. App names contain hyphens, so the name is not parsed out of the namespace: the target
  must equal `app-<label>-cicd`, and the XR's own namespace must equal `app-<label app>-<label env>`. Anything
  else publishes nothing and raises a Warning event on the XR. An app cannot aim it at another app. An XR that
  was not rendered by the chart (no labels) publishes nothing.

## What Glidepath does

The test stage already copies `app-secrets` into the Testkube namespace as `<app>-app-secrets`. It now also
copies `dex-check-ride-credentials` if it exists (Glidepath's `run-testworkflow` Task, and one more
`resourceNames` entry on `pipeline-runner`). The check ride reads `DEX_TOKEN_URL`, `DEX_CLIENT_ID` and
`DEX_CLIENT_SECRET` from `<app>-app-secrets` as before, each optional. Where a key is in both Secrets, the
Dex one wins.

## Migrating an app that has a hand-made `app-secrets`

`flight-api` on the dev cluster has an `app-secrets` Secret in `app-flight-api-cicd` that was created by hand
to hold these three values. Once the pieces above are live:

1. Add `checkRide` to flight-api's dev Dex component, and wait for the Secret `dex-check-ride-credentials` to
   appear in `app-flight-api-cicd`.
2. Run the test stage once and confirm the check ride passes.
3. The owner deletes the hand-made `app-secrets` (`kubectl -n app-flight-api-cicd delete secret app-secrets`).
   It is not owned by anything, so nothing recreates it. If it holds keys other than the three Dex ones, first
   move those into the app's Infisical project and declare them under `secrets:` in `cicd.yaml`, so the
   `app-secrets` ExternalSecret owns that name.

Do not delete it before step 2: until then it is what the check ride reads.

## Why not push to Infisical

Glidepath's `app-secrets` ExternalSecret reads from the app's Infisical project, so pushing the credentials
there (an External Secrets `PushSecret`) was the first idea. It does not work with what Airframe builds: the
app's `ClusterSecretStore` logs in with an identity that has the `viewer` role on the project
(`compositions/secretstore/templates/infisicalproject.yaml`), and nothing in this catalog composes a
`PushSecret`. Making the store read-write would give every namespace the store serves write access to the
app's secrets.
