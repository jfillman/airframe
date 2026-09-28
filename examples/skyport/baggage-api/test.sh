#!/bin/sh
# Owns its own dependency install (same convention boarding-api's `node --test`/flight-api's
# `mvnw test` already give for free via their own package managers) - pymongo (real MongoDB
# driver, requirements.txt) is never actually exercised by these tests (baggage.py's own
# connect() imports it lazily, only when a real MONGODB_URI is configured), but mongomock
# (requirements-test.txt, test-only - never shipped in the runtime image, see Containerfile)
# gives BaggageStore's real Mongo-backed logic something to run against without a cluster.
set -e
pip install --quiet -r requirements.txt -r requirements-test.txt
python3 -m unittest -v
