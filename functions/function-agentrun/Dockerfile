# syntax=docker/dockerfile:1

# It's important that this is Debian 12 to match the distroless image.
FROM debian:12-slim AS build

RUN --mount=type=cache,target=/var/lib/apt/lists \
    --mount=type=cache,target=/var/cache/apt \
    rm -f /etc/apt/apt.conf.d/docker-clean \
    && apt-get update \
    && apt-get install --no-install-recommends --yes python3-venv git

# Don't write .pyc bytecode files. These speed up imports when the program is
# loaded. There's no point doing that in a container where they'll never be
# persisted across restarts.
ENV PYTHONDONTWRITEBYTECODE=true

# Build the wheel via pip's own PEP517 isolated build (which invokes
# hatchling, our [build-system].requires backend, in its own throwaway venv
# that pip manages itself) rather than `hatch build` directly. Hit a real,
# reproducible bug here: hatch 1.16.5's own build-env creation
# (hatch/env/virtual.py's activate(), which now goes through an "expose_uv"
# path) silently fails to produce a usable venv on this Debian 12 base image -
# `Creating environment: hatch-build` prints, then immediately "OSError:
# Unable to locate executables directory" - even though a plain `python3 -m
# venv` in the same image works fine, confirmed directly. Sidesteps hatch's
# own environment-management code entirely; hatchling still does the actual
# building either way, since pyproject.toml's build-system.requires names it.
WORKDIR /build
COPY . .
# Deliberately COPY, not the upstream function-template-python's `RUN --mount=target=.` -
# Apple's `container` CLI build engine (this project's own build tool,
# reference_container_cli_over_podman.md) doesn't pass the real build context through that
# BuildKit mount syntax (confirmed live: "transferring context: 2B done", then "Directory '.'
# is not installable" - reproduced identically against function-rollout-watcher's own
# Dockerfile, so this is a generic container-CLI/BuildKit-mount incompatibility, not something
# specific to this function). COPY is slightly less cache-efficient but portable.
RUN --mount=type=cache,target=/root/.cache/pip \
    python3 -m venv /venv/build \
    && /venv/build/bin/pip wheel . --no-deps --wheel-dir /whl

# Create a fresh venv and install only the function wheel into it.
RUN --mount=type=cache,target=/root/.cache/pip \
    python3 -m venv /venv/fn \
    && /venv/fn/bin/pip install /whl/*.whl

# Copy the function venv to our runtime stage. It's important that the path be
# the same as in the build stage, to avoid shebang paths and symlinks breaking. 
FROM gcr.io/distroless/python3-debian12 AS image
WORKDIR /
COPY --from=build /venv/fn /venv/fn
EXPOSE 9443
USER nonroot:nonroot
ENTRYPOINT ["/venv/fn/bin/function"]
