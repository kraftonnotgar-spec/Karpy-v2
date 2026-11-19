# Infrastructure module (optional, off by default)

Small projects need only PostgreSQL, Redis and (when services exchange events) RabbitMQ. Bigger
organisation projects can switch on an **`infrastructure` admin plugin** that shows monitoring pages in
the admin. It is **planned, not built**: this page is the plan so it is added the same way everywhere.

Rule: the module never changes product behaviour — removing it or turning pages off has no effect.
Instrumentation in core stays behind a flag (`feature.telemetry`, default off), so projects without the
module pay nothing.

## Local stack today

```bash
docker compose --profile observability up -d   # otel-collector (4317/4318), Jaeger UI (16686), Prometheus (9090)
```

Configs: `services/observability/otel-collector.yaml`, `services/observability/prometheus.yml`.
Point the backend and services at the collector with `OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318`.

## Plugin plan

1. **Deploy** the monitoring services on a private network only (no public ports):
   `deploy/infrastructure/docker-compose.monitoring.yml` (collector, Prometheus, Grafana, Jaeger,
   Alertmanager, exporters for Postgres/Redis/node, RabbitMQ Prometheus plugin).
2. **Configure** env (secrets only in env): see the table.
3. **Activate**: `python -m karpy_platform plugin:activate infrastructure`. The plugin registers an
   admin section "Infrastructure" through `get_admin_sections()` and Overview widgets (service health,
   error rate, queue depth) through `get_overview_widgets()` — exactly like any other plugin.
4. **Switch pages on** one by one (`infrastructure.<page>.enabled`, default off). A page whose service
   is not configured shows "Not set up" with the steps, never an error. Each page has its own permission
   (`infrastructure.<page>.view`); only Super Admin / technical roles get them.

All calls to the tools are **server-side** with read-only credentials; tokens never reach the browser.

| Page | Shows | Needs | Env |
|---|---|---|---|
| Monitoring | health summary + links | whatever pages are on | — |
| OpenTelemetry | collector status, pipelines, which services report | otel-collector; FastAPI/SQLAlchemy/httpx and Next.js instrumentation | `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME`, `INFRA_OTEL_CONFIG_PATH` |
| Prometheus | request rate, errors, p95 latency, DB/Redis/RabbitMQ health | Prometheus; app `/metrics`; exporters | `INFRA_PROMETHEUS_URL`, `INFRA_PROMETHEUS_TOKEN` |
| Grafana | provisioned dashboards (JSON in the repo) | Grafana | `INFRA_GRAFANA_INTERNAL_URL`, `INFRA_GRAFANA_SERVICE_ACCOUNT_TOKEN`, `NEXT_PUBLIC_INFRA_GRAFANA_PUBLIC_URL` |
| Traces | services, recent traces, search by trace id | Jaeger | `INFRA_JAEGER_URL`, `INFRA_JAEGER_TOKEN` |
| Queues | queues, depth, consumers, dead letters | RabbitMQ management with a **monitoring-only** user | `RABBITMQ_MANAGEMENT_URL`, `RABBITMQ_MONITOR_USERNAME`, `RABBITMQ_MONITOR_PASSWORD` |
| Service health | per-service up/down, `/readyz`, version | Prometheus `up` + health endpoints | — |
| Application logs | recent errors, redacted | log snapshot or Loki | `INFRA_LOG_SNAPSHOT_PATH` or `INFRA_LOKI_URL` |
| Alerts & incidents | firing alerts, history, link to `core/support/incidents.py` | Alertmanager (rules in the repo) | `INFRA_ALERTMANAGER_URL` |
| Service communication | who calls whom, contracts | traces + `services/contracts/` | — |

Nothing in this table is required for a project to run.
