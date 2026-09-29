# baggage-api
Skyport baggage handling: consumes flights.events from the broker and re-routes bags when a gate changes

## What it does
Consumes `flights.events` from the shared Skyport broker (`flight.#`, queue `baggage.flight-events`).
The concourse letter of a flight's gate picks its carousel (A=1, B=2, C=3, ...). When a `GATE_CHANGED`
event arrives the flight's bags are re-routed to the new gate's carousel and the move is recorded.
State persists in MongoDB (Skyport phase 3), via the `bag-db` MongoDB component.

| Endpoint | Purpose |
|---|---|
| `GET /api/bags` | Every flight seen: gate, carousel, bag count, re-route count |
| `GET /api/bags/{flight}` | One flight |
| `GET /api/reroutes` | Recent re-routes, newest first |
| `GET /api/events/status` | Broker consumer: `off`, `connecting` or `connected`, and messages received |
| `GET /api/whoami`, `/healthz` | Version and pod; liveness |

Broker settings come from the `bag-mq` RabbitMQ component (`RABBITMQ_HOST`, `RABBITMQ_VHOST`,
`RABBITMQ_USER`, `RABBITMQ_PASSWORD`). Without `RABBITMQ_HOST` the app runs with the consumer off.

## Tests
`./test.sh` (12 unit tests, no broker needed).

Built and deployed by the Hangar pipeline (cicd.yaml: build, then deploy to dev, then release to staging).

<!-- pipeline exercise: release.image writer -->
