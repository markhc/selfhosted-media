# Operations

General guidance for running and maintaining deployed services. Each
[service guide](../README.md#services) lists its own data paths and caveats.

## Service selection and removal

Disabled services are skipped, not uninstalled. Turning off a
`selfhosted_services.<name>.enabled` flag stops Ansible from managing that
service but leaves any existing deployment, data, and timers in place; stop
them explicitly with Compose on the host if they were already deployed.

- If Caddy remains enabled while The Lounge is disabled, Compose removes the old
  Lounge container but preserves its data.
- Disabling both web services skips that project entirely; explicitly stop the
  project if it was already deployed.
- Disabling ZNC leaves an existing bouncer container and renewal timer running.

## Persistent data and backups

| Path | Contents |
| --- | --- |
| `/opt/selfhosted/tailscale/state` | Tailscale node state |
| `/opt/selfhosted/web/` | Lounge accounts/history/uploads, Caddy certificates and ACME accounts |
| `/opt/selfhosted/znc/` | ZNC data, managed config, TLS material, and ACME state |

Back these up securely; do not commit or delete them on redeployment. Keep the
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
