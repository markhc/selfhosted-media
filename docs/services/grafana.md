# Grafana

[Grafana](https://grafana.com/oss/grafana/) is the private dashboard and query
interface for the monitoring stack. Ansible provisions selected Prometheus and
Loki data sources plus starter dashboards.

## Enable

```yaml
caddy_enabled: true
grafana_enabled: true
grafana_hostname: grafana.example.com
```

Set `grafana_admin_password` in the encrypted vault to at least 8 characters.
The default admin user is `admin`; change `grafana_admin_user` before the first
deployment if wanted. Grafana defaults to `127.20.0.1:3000`. Image variables use
the `grafana` prefix. Complete [private HTTPS setup](caddy.md#set-up-private-https)
for the hostname.

The password initializes a new database. Changing the vault value does not
reset an administrator password already stored in Grafana; use Grafana's
password-reset workflow for an existing deployment.

## Deploy

Run `make deploy` after changing selected monitoring components so data sources
and dashboards match. Use `make deploy-grafana` for Grafana-only changes.

## Network exposure

Grafana listens only on loopback and Caddy publishes it on the private HTTPS
listeners. Anonymous access and account signup are disabled.

Grafana 13.2 and later package the Prometheus and Loki data sources as
standalone plugins bundled in the Grafana image. Because the container has a
read-only root filesystem, the role disables in-place updates of these bundled
plugins. Update them by changing the pinned Grafana image version instead.

## Data

`/opt/selfhosted/grafana/data` contains users, UI-created dashboards, alerting
configuration, and settings. Provisioned dashboards are read-only; copy one in
the UI before customizing it. Back up the data directory if UI-managed content
matters.

## Troubleshooting

- A missing dashboard means its backing service is not selected: node_exporter
  for Host overview, cAdvisor for Container overview, or Loki for Container logs.
- If **Node Exporter Full** cannot be installed, verify that the NAS can reach
  Grafana.com. The role downloads pinned dashboard 1860 revision 45 and refuses
  content that does not match its recorded SHA-256 checksum.
- A `plugin.backgroundinstaller` error that mentions a read-only filesystem
  means plugin auto-updates were enabled. Redeploy the role to restore the
  managed setting that disables them.
- A data source error usually means its backend container is stopped or its
  loopback address was changed without a full deployment. If Grafana reports a
  missing data source plugin, check its container logs and verify access to
  Grafana's plugin catalog, then run `make deploy-grafana` again.
- A redirect to the wrong hostname means `grafana_hostname` does not match the
  URL used through Caddy.
