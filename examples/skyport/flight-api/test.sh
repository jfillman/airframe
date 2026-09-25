#!/usr/bin/env sh
# Unit tests only: no database needed. FlightRepositoryIT is skipped unless TEST_DB_URL is set.
# Uses the Maven Wrapper because the CI Java agent image is a plain JDK with no Maven.
set -eu
cd "$(dirname "$0")"
exec ./mvnw -B -ntp test
