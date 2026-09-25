# flight-api

The system of record for flights and gates: a Spring Boot service backed by PostgreSQL.
Phase 1 of [Skyport](../../../docs/user/skyport-demo.md). The walkthrough that deploys it
through Airframe is [quickstart part 2](../../../docs/user/quickstart-flight-api.md).

| | |
|---|---|
| Stack | `SpringBootApplication` — Java 21, Maven, Spring Boot 3.3.4 |
| Package | `io.skyport.flight` — set `groupId` to this in Tower's form; the scaffold uses it as the one Java package |
| Component | `postgresql` — a dedicated CloudNativePG cluster in the app's own namespace |
| Port | 8080 |

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/flights` | All 24 seeded departures from YVR |
| `GET /api/flights/{flight}` | One flight: gate, status, scheduled and estimated departure, capacity, boarding group |
| `GET /api/flights/{flight}/events` | The change log for that flight, newest first |
| `PUT /api/flights/{flight}/gate` | `{"gate":"B7"}` — move it |
| `PUT /api/flights/{flight}/delay` | `{"minutes":30}` — 0 clears it |
| `GET /api/whoami` | Version and pod (what the canary board polls) |
| `GET /actuator/health/readiness` | Ready only when the database answers |

`flight`, `gate`, `destination`, `departs`, `capacity` and `group` are exactly what
boarding-api's built-in lookup returns, so the gate board can use this service in its place.

## The database

Flyway runs `db/migration/V*.sql` on startup: `V1` creates `flights` and `flight_events`,
`V2` seeds 24 flights. Every change to a flight is written **together with its event, in one
transaction**, so the log can never disagree with the table. That log is what Phase 2's broker
will publish from.

A simulator (`SIMULATOR_ENABLED`, default `true`, every `SIMULATOR_INTERVAL_MS`, default
30 s) moves a random flight to another gate or grows/clears a delay, so the demo has something
moving. It goes through the same service as an API caller, so it obeys the same rules.

## Configuration

| Variable | Default | Comes from, in the cluster |
|---|---|---|
| `DB_HOST` `DB_PORT` `DB_NAME` `DB_USER` `DB_PASSWORD` | `localhost` `5432` `flight_db` `flight_db` *(empty)* | The `flight-db-app` Secret the `postgresql` component creates (`host`, `port`, `dbname`, `username`, `password`) |
| `SIMULATOR_ENABLED` / `SIMULATOR_INTERVAL_MS` | `true` / `30000` | plain `env:` |
| `PORT` | `8080` | — |

Flyway retries the connection for about two and a half minutes, so the pod can start before
its database does.

## Tests

```bash
./test.sh                       # 17 unit tests, no database
```

`test.sh` uses the Maven Wrapper because the platform's Java build agent is a plain JDK with no
Maven. It was run in that exact image (`eclipse-temurin:21-jdk`) to check.

`FlightRepositoryIT` runs the real migrations and queries against a real Postgres and is skipped
unless `TEST_DB_URL` is set:

```bash
container run -d --name pg -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=flight_db -e POSTGRES_USER=flight_db postgres:16
TEST_DB_URL=jdbc:postgresql://<container ip>:5432/flight_db TEST_DB_USER=flight_db TEST_DB_PASSWORD=pw \
  ./mvnw -Dtest=FlightRepositoryIT test
```

## Architectures

Java bytecode is architecture-neutral and every image involved (`eclipse-temurin`, the
scaffold's Containerfile) is multi-arch, so this builds for `linux/arm64` and `linux/amd64`
with no changes. Leave `build.platforms` alone.
