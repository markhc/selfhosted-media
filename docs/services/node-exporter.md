# node_exporter

[node_exporter](https://github.com/prometheus/node_exporter) exposes host CPU,
memory, filesystem, and network metrics to Prometheus. It mounts the host root
filesystem read-only, drops every capability, and listens only on its dedicated
loopback address.

Grafana automatically provisions both the compact project dashboard and
[Node Exporter Full dashboard 1860](https://grafana.com/grafana/dashboards/1860-node-exporter-full/).
The full dashboard is pinned to a specific revision and checksum. The
`processes` and `tcpstat` collectors it uses are explicitly enabled; panels for
collectors unavailable inside a container, such as systemd, remain empty.

## Enable

Set `node_exporter_enabled: true`; normally also select Prometheus and Grafana
as shown in the [monitoring guide](../monitoring.md#choose-the-components). Its
defaults are `127.20.0.3:9100`; override `node_exporter_address` or
`node_exporter_port` when necessary. Image variables use the `node_exporter`
prefix.

## Deploy

Run `make deploy` when first adding the exporter so Prometheus also receives
the target. `make deploy-node_exporter` updates only the exporter.

## Network exposure

The metrics endpoint is loopback-only and is not published through Caddy.

## Data

node_exporter is stateless. Disabling it leaves the container running until it
is removed manually; see [service removal](../operations.md#service-selection-and-removal).

## Troubleshooting

Check Prometheus's `node` target and the container logs. Filesystem metrics use
the host paths even though the exporter runs in a container.
