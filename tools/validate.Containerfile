# The image CI runs to enforce `airframe-validate` on env files (decision D10: enforce now).
# Owned by Airframe so that Glidepath, which only runs "a validator image against changed files", stays
# installable without Airframe. Build context is the repo root:
#   container build -f tools/validate.Containerfile -t airframe-validate:dev .
# Usage: validate-values [--app NAME] FILE...   (exit 0 = all valid, 1 = a problem; see tools/airframe-validate)
# (the image's default entrypoint is airframe-validate itself, so `<image> FILE...` works too)
FROM python:3.13-alpine
ARG TARGETARCH
ARG HELM_VERSION=3.21.3
RUN apk upgrade --no-cache && apk add --no-cache bash ca-certificates curl \
 && ARCH="${TARGETARCH:-$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')}" \
 && curl -fsSL "https://get.helm.sh/helm-v${HELM_VERSION}-linux-${ARCH}.tar.gz" | tar -xz -C /tmp \
 && mv "/tmp/linux-${ARCH}/helm" /usr/local/bin/helm && rm -rf /tmp/linux-* \
 && apk del curl \
 && pip install --no-cache-dir pyyaml jsonschema \
 && pip uninstall -y setuptools pip
# The chart, the XRDs and the tool, at the version this image is tagged with. airframe-validate finds them
# relative to itself, so the validator always matches the chart that will render the files.
COPY charts/airframe-application /opt/airframe/charts/airframe-application
COPY xrds /opt/airframe/xrds
COPY tools/airframe-validate /opt/airframe/tools/airframe-validate
COPY tools/airframe_schema.py /opt/airframe/tools/airframe_schema.py
COPY tools/component_outputs.py /opt/airframe/tools/component_outputs.py
COPY tools/sidecars.py /opt/airframe/tools/sidecars.py
COPY tools/deadend_rules.py /opt/airframe/tools/deadend_rules.py
# Glidepath's values-check gate runs `validate-values [--app NAME] FILE...`; that name is the whole contract.
RUN ln -s /opt/airframe/tools/airframe-validate /usr/local/bin/validate-values && adduser -D -u 10001 validator
USER 10001
ENTRYPOINT ["/opt/airframe/tools/airframe-validate"]
