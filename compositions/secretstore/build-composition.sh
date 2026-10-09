#!/usr/bin/env bash
# Thin shim kept for muscle memory and the example READMEs: composition.yaml's inline template
# blocks are regenerated from templates/ by the one builder shared by every composition,
# tools/build-compositions (`--check` runs in CI). Everything the per-composition script used to
# say in its header now lives in composition.yaml itself, which the builder leaves untouched.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${HERE}/../../tools/build-compositions" "$(basename "${HERE}")" "$@"
