# Airframe quickstart part 3: skyport-broker (shared RabbitMQ)

Converted from [`../user/quickstart-broker.md`](../user/quickstart-broker.md).

Placeholders: `<dev-context>` are the names chosen when the clusters were built (render with `--dev-cluster` etc. to fill them in).

## skyport-broker is a synced, ready InfraService with a real RabbitMQ cluster behind it

```bash
kubectl --context "<dev-context>" get infraservice skyport-broker -n infra-skyport-broker-cicd
kubectl --context "<dev-context>" get rabbitmqcluster skyport-broker -n infra-skyport-broker-dev
```

**Expected:** the InfraService XR is Synced/Ready; the RabbitmqCluster reports AllReplicasReady=True

## flight-api is attached to the broker as a publisher (its own mq credentials exist)

```bash
kubectl --context "<dev-context>" get secret flight-mq-user-credentials -n app-flight-api-dev
```

**Expected:** a flight-mq-user-credentials Secret exists with username/password keys

## boarding-api is attached as a consumer and is genuinely receiving events over the broker

```bash
curl -s http://localhost:18080/api/whoami
```

**Expected:** "events":"connected" and eventsReceived > 0 - proof events actually flow flight-api -> broker -> boarding-api, not just that both sides have credentials

