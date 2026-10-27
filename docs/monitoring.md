# Monitoring

The monitoring components are independent services. The recommended baseline
is [node_exporter](services/node-exporter.md),
[Prometheus](services/prometheus.md), and [Grafana](services/grafana.md).
[cAdvisor](services/cadvisor.md) adds per-container resource metrics. For
centralized container logs, [Alloy](services/alloy.md) discovers local Docker
containers and sends their standard output and error streams to
[Loki](services/loki.md), where Grafana can query them.

## Choose the components

```yaml
# group_vars/nas.yml
caddy_enabled: true

node_exporter_enabled: true
prometheus_enabled: true
grafana_enabled: true
grafana_hostname: grafana.example.com

# Optional container metrics. This grants cAdvisor privileged host access.
cadvisor_enabled: false

# Optional centralized Docker logs. Select both or neither.
loki_enabled: false
alloy_enabled: false
```

Add `grafana_admin_password` (at least 8 characters) to the encrypted vault.
No other monitoring component needs a credential because only Grafana is
published. Complete [Caddy's HTTPS setup](services/caddy.md#set-up-private-https)
for `grafana_hostname` before deployment.

All components use distinct host-loopback addresses and are inaccessible from
the LAN or tailnet directly:

| Component | Default address | Port | Published |
| --- | --- | --- | --- |
| Grafana | `127.20.0.1` | `3000` | Through Caddy |
| Prometheus | `127.20.0.2` | `9090` | No |
| node_exporter | `127.20.0.3` | `9100` | No |
| cAdvisor | `127.20.0.4` | `8080` | No |
| Loki | `127.20.0.5` | `3100` | No |
| Alloy diagnostics | `127.20.0.6` | `12345` | No |

Override an address with `<component>_address`. Every selected address must be
unique and in `127.0.0.0/8` outside `127.0.0.0/16`.

## Resource-conscious logs

Loki is optional because metrics alone are substantially lighter. This
deployment deliberately uses a small, single-process Loki rather than the
distributed stack:

- local filesystem storage and one replica;
- seven-day retention (`loki_retention_period: 168h`);
- a 32 MiB embedded query cache;
- conservative ingestion and query concurrency;
- a hard 512 MiB container memory ceiling (`loki_memory_limit: 512m`);
- no pattern ingester, ruler, object store, or additional gateway.

Alloy has a separate 256 MiB ceiling and replaces the deprecated Promtail. It
labels logs by host, container, Compose project, and Compose service. It reads
the Docker socket, which is effectively root-equivalent host access: a
read-only bind does not make Docker API methods read-only. Keep the diagnostics
listener on loopback and do not publish it.

If this still costs too much, disable both `loki_enabled` and `alloy_enabled`.
Metrics and the host dashboard continue to work. A later deployment can point
collectors at a remote log backend, but this initial role intentionally does
not send private logs off the NAS.

Loki retention does not rotate Docker's own source log files. Docker log
rotation is a separate host-runtime concern and should be introduced carefully
because changing the daemon default only affects newly created containers.

## Deploy and use

```bash
make deploy
```

Use a full deployment when changing selected exporters or backends so
Prometheus targets and Grafana data sources are refreshed. `make
deploy-<service>` remains useful for an image or settings change isolated to
one component.

Grafana provisions up to four read-only dashboards in the **Self-hosted**
folder:

- **Host overview** and **Node Exporter Full**, when node_exporter is selected;
- **Container overview**, when cAdvisor is selected;
- **Container logs**, when Loki is selected.

**Node Exporter Full** is
[Grafana.com dashboard 1860](https://grafana.com/grafana/dashboards/1860-node-exporter-full/),
pinned to revision 45 and verified by SHA-256 during deployment. Keeping the
dashboard revision in the role prevents an upstream edit from silently
changing the installation. Updating it requires changing both the revision and
checksum in the Grafana role defaults.

Grafana also provisions selected Prometheus and Loki data sources. Dashboards
created in the UI remain in Grafana's database and are not managed by Ansible.

## Data and recovery

Prometheus defaults to 15 days and 5 GB; whichever bound is reached first
wins. Loki defaults to seven days. These data stores are rebuildable telemetry
and normally do not need backup. Back up `/opt/selfhosted/grafana/data` if UI
dashboards, users, or alerting configuration are important. Alloy's state only
tracks log positions and is also rebuildable.

Monitoring can report failures but cannot preserve service state. The backup
work should treat the application paths in
[Persistent data and backups](operations.md#persistent-data-and-backups) as the
source of truth rather than relying on Prometheus or Loki retention.
