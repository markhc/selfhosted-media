# Self Hosted Media

Reusable infrastructure-as-code for a private, self-hosted media stack. Each
service is independently selectable. Ansible installs Docker Engine on Debian
or Ubuntu hosts and manages every selected service with Docker Compose.
Optional services such as ZNC can live on a separate cloud VM; no VM is
provisioned by this repository. No Tailscale SSH server is enabled.

## Quick start

```bash
make configure   # Install tools, create the local inventory, initialize the vault
make vault-edit  # Add credentials for the selected services
make deploy      # Deploy every service enabled in the local inventory
make check       # Validate the repository offline
```

Read [Getting started](docs/getting-started.md) before the first deployment.

## General guides

- [Getting started](docs/getting-started.md): controller requirements, local
  inventory, service selection, and deployment targets.
- [Tailnet setup and policy](docs/tailnet.md): tailnet prerequisites, the
  controller OAuth credential, and the explicit policy workflow.
- [Operations](docs/operations.md): disabling services, persistent data,
  backups, and credentials on hosts.
- [Validation](docs/validation.md): offline checks and container smoke tests.
- [Media stack](docs/media-stack.md): shared data layout, loopback endpoints,
  and migration for the download and library services.

## Services

| Service | Selection key | Typical host | Purpose |
| --- | --- | --- | --- |
| [Tailscale](docs/services/tailscale.md) | `tailscale` | Every host | Private network enrollment and access |
| [Caddy](docs/services/caddy.md) | `caddy` | NAS | Private HTTPS reverse proxy with DNS-01 certificates |
| [The Lounge](docs/services/thelounge.md) | `thelounge` | NAS | Private web IRC client |
| [Audiobookshelf](docs/services/audiobookshelf.md) | `audiobookshelf` | NAS | Private audiobook and podcast server |
| [qBittorrent](docs/services/qbittorrent.md) | `qbittorrent` | NAS | BitTorrent client for the media stack |
| [qui](docs/services/qui.md) | `qui` | NAS | Web interface and client proxy for qBittorrent |
| [ZNC](docs/services/znc.md) | `znc` | Cloud VM | IRC bouncer with bounded, encrypted playback |

Enable each service with its `<key>_enabled` flag in the local inventory; see [Select services](docs/getting-started.md#select-services).
