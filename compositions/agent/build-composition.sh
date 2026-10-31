#!/usr/bin/env bash
# Thin wrapper: the one builder for every Composition's inline templates is tools/build-compositions.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${HERE}/../../tools/build-compositions" "$(basename "${HERE}")" "$@"
