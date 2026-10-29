# Self Hosted Media

Reusable infrastructure-as-code for a private, self-hosted media stack. Ansible installs Docker Engine on Debian
or Ubuntu hosts and manages every selected service with Docker Compose.

## Hosts

Currently we support deploying the media stack to a single NAS host, with optional Tailscale enrollment for remote access.

You can also optionally deploy the ZNC IRC bouncer to another host, such as a cloud VM, to keep IRC connected when the NAS is offline.

## TODO

These are planned features that are not yet implemented:

- Add Gluetun; There is no VPN support for outgoing traffic yet.
- Monitoring and alerting; Prometheus, Grafana, and Alertmanager.
- Backup and restore with restic
- Support alternatives to Plex, such as Jellyfin or Emby.

**Out of scope:**

- Will not support Windows, TrueNAS, or Synology hosts. The NAS must run a supported Linux distribution (preferably Debian).

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
  and migration for the download, library, and streaming services.

## Services

| Service | Selection key | Typical host | Purpose |
| --- | --- | --- | --- |
| [Tailscale](docs/services/tailscale.md) | `tailscale` | Every host | Private network enrollment and access |
| [Caddy](docs/services/caddy.md) | `caddy` | NAS | Private HTTPS reverse proxy with DNS-01 certificates |
| [The Lounge](docs/services/thelounge.md) | `thelounge` | NAS | Private web IRC client |
| [Audiobookshelf](docs/services/audiobookshelf.md) | `audiobookshelf` | NAS | Private audiobook and podcast server |
| [qBittorrent](docs/services/qbittorrent.md) | `qbittorrent` | NAS | BitTorrent client for the media stack |
| [qui](docs/services/qui.md) | `qui` | NAS | Web interface and client proxy for qBittorrent |
| [autobrr](docs/services/autobrr.md) | `autobrr` | NAS | Real-time release filtering and download automation |
| [Prowlarr](docs/services/prowlarr.md) | `prowlarr` | NAS | Indexer manager that syncs indexers to Sonarr and Radarr |
| [Sonarr](docs/services/sonarr.md) | `sonarr` | NAS | TV series management, one or more instances |
| [Radarr](docs/services/radarr.md) | `radarr` | NAS | Movie management, one or more instances |
| [Plex](docs/services/plex.md) | `plex` | NAS | Media server for the shared libraries, with optional GPU transcoding |
| [Pi-hole](docs/services/pihole.md) | `pihole` | NAS | LAN ad-blocking DNS that resolves the web services to Caddy's LAN address |
| [ZNC](docs/services/znc.md) | `znc` | Cloud VM | IRC bouncer with bounded, encrypted playback |

Enable each service with its `<key>_enabled` flag in the local inventory; see [Select services](docs/getting-started.md#select-services).
