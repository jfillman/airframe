# Executable walkthroughs (AF-7a)

A walkthrough is the prose quickstart's checkable skeleton: the same sections, but each one
reduced to a `verify` command whose exit code says whether that section's claim is still true
right now, against the real dev/prod clusters. It does not re-run one-time creation actions
(open a PR, merge it) - those already happened; the walkthrough checks their *lasting effect*
(the XR is Synced/Ready, the pod is Running, the endpoint answers) so it stays safely re-runnable
without recreating or tearing down anything.

## File format

```yaml
title: string                    # shown as the walkthrough's own heading
app: string                      # the app this walkthrough is about
sourceDoc: path                  # the prose quickstart this was converted from, relative to docs/user/
steps:
  - id: kebab-case-id            # stable; matches the source doc's section where practical
    title: string
    command: |                   # what a human/agent actually runs - documentation, not executed
      kubectl get pods -n app-boarding-api-dev
    expected: string             # prose: what you should see
    verify: |                    # a real, safe, idempotent shell command; exit 0 = this step's
      kubectl get pods -n app-boarding-api-dev  # claim still holds. Never destructive, never a
      # one-time creation action re-run.
```

## Running one

```
tools/walkthrough-runner docs/walkthroughs/part1-boarding-api.yaml
```

Runs every step's `verify` in order, reports PASS/FAIL per step (with the failing command's
stdout/stderr on failure), and exits non-zero if any step failed - "the walkthrough replays
green" means every step passed. `--render OUT.md` instead renders the walkthrough to markdown
(title, command, expected result per step) without running anything.

Needs real cluster access (`kubectl` configured for `kiac-dev`/`kind-prod`) and, for the HTTP
checks, a working `kubectl port-forward` (the runner starts and stops its own).
