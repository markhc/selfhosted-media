# Operations

General guidance for running and maintaining deployed services. Each
[service guide](../README.md#services) lists its own data paths and caveats.

## Service selection and removal

Disabled services are skipped, not uninstalled. Turning off a
`<service>_enabled` flag stops Ansible from managing that
service but leaves any existing deployment, data, and timers in place; stop
them explicitly with Compose on the host if they were already deployed.

- Every service is a separate Compose project named `selfhosted-<service>` in
  `/opt/selfhosted/<service>`, so disabling one never touches another. Each
  Sonarr and Radarr instance is its own project, such as `selfhosted-sonarr-tv`
  with the Caddy site `sonarr-tv.caddy`, and removing it from the instance
  list leaves it running in the same way.
- These projects share the external `selfhosted` bridge; see the
  [shared-network evaluation](shared-network-experiment.md). Tailscale remains
  host-networked.
- Disabling a web service leaves its container and its Caddy site running. To
  remove it, stop its project, delete
  `/opt/selfhosted/caddy/conf/sites/<service>.caddy`, and run
  `make deploy-caddy` to reload Caddy.
- Disabling Pi-hole leaves it answering DNS on the LAN; point the router to
  another DNS server before stopping it.
- Disabling ZNC leaves an existing bouncer container and renewal timer running.

For example, to stop and unpublish Audiobookshelf while keeping its data:

```bash
sudo docker compose --project-directory /opt/selfhosted/audiobookshelf \
  --project-name selfhosted-audiobookshelf down
sudo rm /opt/selfhosted/caddy/conf/sites/audiobookshelf.caddy
```

## Container images

Every service runs a pinned image. The example group files set each image's
repository and tag in its service's section, with the same values as the role
defaults; an inventory without them uses those defaults. The variables are
named after these prefixes:

| Image | Prefix |
| --- | --- |
| [Tailscale](services/tailscale.md) | `tailscale` |
| [Caddy](services/caddy.md) base images | `caddy` |
| [The Lounge](services/thelounge.md) | `thelounge` |
| [Audiobookshelf](services/audiobookshelf.md) | `audiobookshelf` |
| [qBittorrent](services/qbittorrent.md) | `qbittorrent` |
| [qui](services/qui.md) | `qui` |
| [autobrr](services/autobrr.md) | `autobrr` |
| [Prowlarr](services/prowlarr.md) | `prowlarr` |
| [Sonarr](services/sonarr.md) | `sonarr` |
| [Radarr](services/radarr.md) | `radarr` |
| [Plex](services/plex.md) | `plex` |
| [Pi-hole](services/pihole.md) | `pihole` |
| [ZNC](services/znc.md) | `znc` |
| ZNC certificate renewal | `znc_acme` |

- `<prefix>_image_repository` is the image name, including a registry for a
  mirror, for example `registry.example.com/mirror/qbittorrent-nox`.
- `<prefix>_image_tag` is the tag. Quote it, because YAML reads `5.3` as a
  number. `latest` and an empty tag are refused unless a digest is set.
- `<prefix>_image_digest` optionally pins the exact image as
  `sha256:<64 hex digits>`. Docker then ignores the tag, which only records
  the version. Use the digest that
  `docker buildx imagetools inspect <repository>:<tag>` prints on its
  `Digest:` line, which is valid on every architecture.

```yaml
# Placeholder digest; use the one printed for your image.
qbittorrent_image_tag: "5.2.4-1"
qbittorrent_image_digest: "sha256:0000000000000000000000000000000000000000000000000000000000000000"
```

Caddy is built on the NAS from the official builder and base images, so
`caddy_version` is both their tag (`2.11.7-builder` and `2.11.7`) and the Caddy
release that is compiled. `caddy_image_digest` and `caddy_builder_image_digest`
pin the two base images, and `caddy_cloudflare_version` the DNS plugin.

- A replacement must work like the default image: the same paths, user,
  environment variables, and commands. A different image family, such as a
  hotio or linuxserver image instead of the official qBittorrent one, uses
  other paths and user handling and does not work by changing the repository.
- To upgrade, change the tag (and digest) and run `make deploy-<service>`;
  Compose pulls the new image and recreates the container. Tags set in the
  local inventory stay where they are when this repository raises a default,
  so compare them with the example inventory after updating. Most services
  migrate their data forward only, so back up first and do not downgrade.

## Persistent data and backups

| Path | Contents |
| --- | --- |
| `/opt/selfhosted/tailscale/state` | Tailscale node state |
| `/opt/selfhosted/caddy/` | Caddy certificates, ACME accounts, and published sites |
| `/opt/selfhosted/thelounge/data` | Lounge accounts, history, and uploads |
| `/opt/selfhosted/audiobookshelf/` | Audiobookshelf database and metadata |
| `/opt/selfhosted/qbittorrent/config` | qBittorrent configuration and torrent resume data |
| `/opt/selfhosted/qui/config` | qui configuration, session secret, and database |
| `/opt/selfhosted/autobrr/config` | autobrr configuration, database, backups, and stored credentials |
| `/opt/selfhosted/prowlarr/config` | Prowlarr configuration, database, and backups |
| `/opt/selfhosted/sonarr-<instance>/config` | Sonarr configuration, database, and backups, per instance |
| `/opt/selfhosted/radarr-<instance>/config` | Radarr configuration, database, and backups, per instance |
| `/opt/selfhosted/plex/config` | Plex server identity and token, databases, and metadata |
| `/opt/selfhosted/pihole/etc-pihole` | Pi-hole configuration, lists, and query log |
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
