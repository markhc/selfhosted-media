# Prometheus

[Prometheus](https://prometheus.io/) stores local metrics and automatically
scrapes whichever of node_exporter and cAdvisor are selected on the NAS.

## Enable

Set `prometheus_enabled: true` and select at least one exporter. See the
[monitoring guide](../monitoring.md#choose-the-components). The service defaults
to `127.20.0.2:9090`, 30-second scrapes, 15-day retention, and a 5 GB storage
ceiling. Configure these with `prometheus_address`, `prometheus_port`,
`prometheus_scrape_interval`, `prometheus_retention_time`, and
`prometheus_retention_size`. Image variables use the `prometheus` prefix.

## Deploy

Run `make deploy` after changing exporter selections. `make deploy-prometheus`
updates only Prometheus and uses the selections already in inventory.

## Network exposure

Prometheus is loopback-only and has no authentication because it is not
published. Grafana queries it server-side.

## Data

Metrics live in `/opt/selfhosted/prometheus/data`. They are rebuildable and are
deleted by Prometheus according to both retention bounds. Disabling Prometheus
does not remove its container or data.

## Troubleshooting

Use Grafana's Prometheus data source or inspect `http://127.20.0.2:9090/targets`
from the NAS. A missing target usually means the exporter was enabled after an
isolated `make deploy-prometheus` or has not converged successfully.
