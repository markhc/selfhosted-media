# Loki

[Loki](https://grafana.com/oss/loki/) is the optional local store for
centralized container logs. This role deliberately deploys a bounded,
single-process configuration for one NAS.

## Enable

Set both `loki_enabled: true` and `alloy_enabled: true`; Grafana is the query
interface. Resource choices and tradeoffs are documented under
[Resource-conscious logs](../monitoring.md#resource-conscious-logs). Loki
defaults to `127.20.0.5:3100`, seven-day retention, and a 512 MiB memory limit.
Use `loki_retention_period`, `loki_memory_limit`,
`loki_ingestion_rate_mb`, and `loki_ingestion_burst_size_mb` to tune it. Image
variables use the `loki` prefix.

## Deploy

Run `make deploy`; Loki converges before Alloy and Grafana.

## Network exposure

Loki is loopback-only, has no authentication, and is never published through
Caddy. Do not change its address to a non-loopback interface.

## Data

Logs and the TSDB index live in `/opt/selfhosted/loki/data`. The compactor
deletes data beyond retention asynchronously. Treat logs as sensitive: they
may contain filenames, URLs, account names, or accidental credentials.

## Troubleshooting

An exit with an out-of-memory status means the configured ceiling is too low
for ingestion or query load. First shorten the Grafana query range and reduce
log volume; raise `loki_memory_limit` only after checking host capacity.
