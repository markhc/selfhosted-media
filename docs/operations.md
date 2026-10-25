# Operations

General guidance for running and maintaining deployed services. Each
[service guide](../README.md#services) lists its own data paths and caveats.

## Service selection and removal

Disabled services are skipped, not uninstalled. Turning off a
`selfhosted_services.<name>.enabled` flag stops Ansible from managing that
service but leaves any existing deployment, data, and timers in place; stop
them explicitly with Compose on the host if they were already deployed.

- Every service is a separate Compose project named `selfhosted-<service>` in
  `/opt/selfhosted/<service>`, so disabling one never touches another.
- Disabling a web service leaves its container and its Caddy site running. To
  remove it, stop its project, delete
  `/opt/selfhosted/caddy/conf/sites/<service>.caddy`, and run
  `make deploy-caddy` to reload Caddy.
- Disabling ZNC leaves an existing bouncer container and renewal timer running.

For example, to stop and unpublish Audiobookshelf while keeping its data:

```bash
sudo docker compose --project-directory /opt/selfhosted/audiobookshelf \
  --project-name selfhosted-audiobookshelf down
sudo rm /opt/selfhosted/caddy/conf/sites/audiobookshelf.caddy
```

## Persistent data and backups

| Path | Contents |
| --- | --- |
| `/opt/selfhosted/tailscale/state` | Tailscale node state |
| `/opt/selfhosted/caddy/` | Caddy certificates, ACME accounts, and published sites |
| `/opt/selfhosted/thelounge/data` | Lounge accounts, history, and uploads |
| `/opt/selfhosted/audiobookshelf/` | Audiobookshelf database and metadata |
| `/opt/selfhosted/qbittorrent/config` | qBittorrent configuration and torrent resume data |
| `/opt/selfhosted/znc/` | ZNC data, managed config, TLS material, and ACME state |

Back these up securely; do not commit or delete them on redeployment. The
shared [media data root](media-stack.md#shared-data-layout) is never created,
re-owned, or deleted by Ansible. Keep the
encrypted vault and its password in secure backups too.

## Credentials on hosts

Credential env files on hosts are mode `0600` and stay outside Git. The
Tailscale auth key is cleared after enrollment; the Cloudflare token remains
available for certificate renewal. Controller OAuth credentials never leave the
controller. Docker administrators can inspect container environments; restrict
Docker access.

## Reboots

Containers restart after reboot. Verify tailnet reachability and HTTPS after a
NAS reboot.
