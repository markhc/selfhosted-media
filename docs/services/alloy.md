# Alloy

[Grafana Alloy](https://grafana.com/oss/alloy-opentelemetry-collector/) discovers
every local Docker container and forwards its stdout/stderr logs to Loki. It is
the supported replacement for Promtail.

## Enable

Set `alloy_enabled: true` and explicitly set `loki_enabled: true`. Alloy refuses
deployment without selected Loki. Defaults are `127.20.0.6:12345` for its local
diagnostics UI and a 256 MiB memory limit. Override these with `alloy_address`,
`alloy_port`, and `alloy_memory_limit`. Image variables use the `alloy` prefix.

## Deploy

Run `make deploy`; Loki starts first. New containers are discovered without an
Ansible redeployment.

## Network exposure

The diagnostics listener is loopback-only and not published. Alloy connects to
Loki over its loopback endpoint.

## Data and host access

Read positions live in `/opt/selfhosted/alloy/data`. Alloy mounts the Docker
socket read-only, but that does not restrict Docker API methods; socket access
is effectively root-equivalent host access. The container runs as Alloy's
non-root UID/GID 473 with the host socket's group added at deployment time. It
has all Linux capabilities dropped and a read-only root filesystem; the data
directory is its only persistent writable path.

`loki.source.docker` decodes the Docker API log stream itself and forwards log
entries directly to Loki. Do not add a `stage.docker` processing stage: that
stage is for Docker JSON log files and can turn API-sourced entries into empty
log lines.

## Troubleshooting

If a container is absent from Grafana, check Alloy's logs and confirm that the
container uses a Docker logging driver whose logs are available through the
Docker API. Search by the Compose service or project labels to distinguish
containers recreated under new IDs.
