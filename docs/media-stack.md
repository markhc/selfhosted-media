# Media Stack

The download and library-management services share one contract so they can
reach each other and hand files over without copying:
[qBittorrent](services/qbittorrent.md), [qui](services/qui.md),
[autobrr](services/autobrr.md), [Prowlarr](services/prowlarr.md),
[Sonarr](services/sonarr.md),
[Radarr](services/radarr.md), and [Plex](services/plex.md). Each one remains an independently
selectable service with its own role; Sonarr and Radarr also run as
[several instances](#multiple-instances). This guide covers only what they
share.

## Names on the shared network

Every application container joins the external `selfhosted` Docker bridge.
Docker DNS makes services reachable by name on their normal internal ports,
for example `http://sonarr-anime:8989`. Caddy uses the same names as its
upstreams. The web ports are not published on the host.

| Name | Port | Published through Caddy |
| --- | --- | --- |
| `qbittorrent` ([guide](services/qbittorrent.md)) | `8080` | Yes, also as a fallback next to qui |
| `qui` ([guide](services/qui.md)) | `7476` | Yes |
| `prowlarr` ([guide](services/prowlarr.md)) | `9696` | Yes |
| `autobrr` ([guide](services/autobrr.md)) | `7474` | Yes |
| `sonarr-<instance>` ([guide](services/sonarr.md)) | `8989` | Yes, one hostname each |
| `radarr-<instance>` ([guide](services/radarr.md)) | `7878` | Yes, one hostname each |
| `plex` ([guide](services/plex.md)) | `32400` | Yes |

Only ports that must accept host traffic are published: Caddy HTTPS,
qBittorrent TCP/UDP peer traffic, Pi-hole DNS, ZNC IRC, and optional Plex
[remote access](services/plex.md#remote-access). Tailscale remains in host mode
because it owns the host TUN interface. See the
[shared-network evaluation](shared-network-experiment.md) for the tradeoffs.

## Multiple instances

Sonarr and Radarr each handle only one kind of library well, so the stack
supports several instances of each, for example:

| Instance | Library |
| --- | --- |
| Sonarr `tv` | TV shows |
| Sonarr `anime` | Anime, with its own release profiles and naming |
| Radarr `hd` | 1080p movies |
| Radarr `uhd` | 4K movies |

The roles follow these rules:

- Each app keeps one role and one selection key (`sonarr`, `radarr`).
  `make deploy-sonarr` deploys every Sonarr instance listed in the inventory,
  for example:

  ```yaml
  sonarr_instances:
    - name: tv
      hostname: sonarr.example.com
    - name: anime
      hostname: anime.example.com
  ```

  The instances above are `sonarr-tv` and `sonarr-anime`, both on port `8989`.

- Each instance is its own Compose project (`selfhosted-sonarr-tv` in
  `/opt/selfhosted/sonarr-tv`) with its own Caddy site. Removing an instance
  from the list stops managing it but leaves it running, like disabling a
  service.
- Each instance has its own vaulted API key, keyed by instance name, for
  example `sonarr_api_keys.anime`.
- Each instance uses its own qBittorrent category and folders,
  `/data/torrents/<category>` and `/data/media/<category>`, so instances never
  import each other's downloads.

## Shared data layout

Services that handle media files mount one existing host directory at the same
container path, `/data` by default; Plex mounts it read-only. A path reported by qBittorrent, such as
`/data/torrents/tv/Example.Show.S01`, is then valid in every other service, and
imports are hardlinks or instant moves instead of copies. The examples in these
guides use the default `/data`.

```text
/data
├── torrents/   # qBittorrent downloads, one subfolder per category (tv/, anime/, movies/, movies-uhd/)
└── media/      # Imported libraries, one subfolder per instance (tv/, anime/, movies/, movies-uhd/)
```

Set the shared variables in `group_vars/nas.yml`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `selfhosted_data_path` | none | Existing host directory mounted in every media container |
| `selfhosted_data_container_path` | `/data` | Path of that directory inside the containers |
| `selfhosted_data_uid` / `_gid` | `1000` | Container user and group of every service that writes to it |
| `selfhosted_data_umask` | `"002"` | Quoted umask; group-writable so the services can modify each other's files |

- Keep `torrents/` and `media/` on **one filesystem**. Hardlinks cannot cross
  filesystems, so separate disks or datasets turn every import into a copy.
- Ansible requires the path to exist and never creates, re-owns, or deletes
  it. Create the subdirectories yourself, owned by the shared UID/GID.
- The path must be outside the `/opt/selfhosted` deployment root, so no
  container can read another service's credentials.
- Choose the container path once. The services store absolute paths, such as
  qBittorrent save paths and Sonarr root folders, so changing it later breaks
  them. It must be absolute and outside system directories, `/config`, and
  `/tmp`.

## Service connections

Connections are configured in each service's web UI for now. Each service
guide lists the values to enter.

| From | To | Address |
| --- | --- | --- |
| qui | qBittorrent | `http://qbittorrent:8080` with the vaulted WebUI credentials; see [Set up](services/qui.md#set-up) |
| autobrr | qBittorrent | `http://qbittorrent:8080` with the vaulted WebUI credentials; see [Set up](services/autobrr.md#set-up) |
| autobrr | A Sonarr or Radarr instance | `http://sonarr-<instance>:8989` or `http://radarr-<instance>:7878` with that instance's API key |
| Each Sonarr and Radarr instance | qBittorrent, through qui's client proxy | Host `qui`, port `7476`, URL base `/proxy/<client key>`, one key per instance |
| Prowlarr | Each Sonarr and Radarr instance | `http://sonarr-<instance>:8989` or `http://radarr-<instance>:7878` with that instance's API key; see [Connect applications](services/prowlarr.md#connect-applications) |
| Each Sonarr and Radarr instance | Prowlarr, for synced indexers | `http://prowlarr:9696`, entered in Prowlarr as its server address |
| Each Sonarr and Radarr instance | Plex, to scan imported files | Host `plex`, port `32400`; see [Connect Sonarr and Radarr](services/plex.md#connect-sonarr-and-radarr) |

## Migrating an existing stack

Migration is manual; Ansible never imports or overwrites existing service
state. It only creates missing directories and enforces the settings listed in
each service guide. Move one service at a time, in this order: qBittorrent,
qui, Prowlarr, Sonarr, Radarr, autobrr, Plex. For each service:

1. Check the running version. The pinned image in this repository must be the
   same or newer, because database and configuration migrations only run
   forward.
2. Point `selfhosted_data_path` at the host directory the old containers
   mount, and set `selfhosted_data_container_path` to the path where they
   mount it, for example `/downloads`, so stored paths remain valid.
3. Stop the old container and keep it from restarting. Its ports would
   otherwise collide with the new deployment on the same NAS.
4. Copy its configuration into `/opt/selfhosted/<service>/` (for an instance,
   `/opt/selfhosted/<service>-<instance>/`) as described in the service guide,
   owned by the shared UID/GID.
5. Run `make deploy-<service>` and verify the service before moving the next.

Connections stored in the old databases usually use Docker DNS names. Those
that match the names above, such as `http://qbittorrent:8080`, keep working;
change the others, for example `http://sonarr:8989` to
`http://sonarr-tv:8989`.
