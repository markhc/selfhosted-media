# Media Stack

The download and library-management services share one contract so they can
reach each other and hand files over without copying:
[qBittorrent](services/qbittorrent.md), [qui](services/qui.md),
[autobrr](services/autobrr.md), [Prowlarr](services/prowlarr.md),
[Sonarr](services/sonarr.md), and
[Radarr](services/radarr.md). Each one remains an independently
selectable service with its own role; Sonarr and Radarr also run as
[several instances](#multiple-instances). This guide covers only what they
share.

## Names and loopback addresses

Every service in the stack runs on the NAS with host networking. Instead of
sharing `127.0.0.1`, each service and instance listens on its own address in
the loopback range on the application's default port, and the media
containers resolve each other by name. Services therefore reach each other at
addresses such as `http://sonarr-anime:8989`. There is no shared Docker
network, and only Caddy and qBittorrent's peer port listen beyond loopback, so
all of them must be selected on the same host.

| Name | Default address | Port | Published through Caddy |
| --- | --- | --- | --- |
| `qbittorrent` ([guide](services/qbittorrent.md)) | `127.10.0.1` | `8080` | Yes, also as a fallback next to qui |
| `qui` ([guide](services/qui.md)) | `127.10.0.2` | `7476` | Yes |
| `prowlarr` ([guide](services/prowlarr.md)) | `127.10.0.3` | `9696` | Yes |
| `autobrr` ([guide](services/autobrr.md)) | `127.10.0.4` | `7474` | Yes |
| `sonarr-<instance>` ([guide](services/sonarr.md)) | per instance, e.g. `127.10.1.1` | `8989` | Yes, one hostname each |
| `radarr-<instance>` ([guide](services/radarr.md)) | per instance, e.g. `127.10.2.1` | `7878` | Yes, one hostname each |

- Override a single-instance service's address with `<service>_address`, for
  example `qbittorrent_address` or `prowlarr_address`. Sonarr and Radarr
  instances set `address` in their [instance list](#multiple-instances).
- Every address must be unique and in `127.0.0.0/8` outside `127.0.0.0/16`,
  which holds `127.0.0.1`, systemd-resolved's `127.0.0.53`, and Debian's
  `127.0.1.1` hostname entry. Linux routes the whole range to the loopback
  interface, so no host configuration is needed.
- Each media container gets the names of the media services and instances
  selected on its host as `extra_hosts`; the host's own `/etc/hosts` is not
  changed. A container learns new names only when it is recreated, so after
  adding a service or instance run `make deploy` rather than only
  `make deploy-<service>`.
- qBittorrent is the exception: it only accepts connections from the others,
  so it gets no `extra_hosts`. Adding a service or instance therefore never
  recreates it, which would stop it and reload every torrent. Its "Run external
  program" commands must use peer addresses rather than names.
- Caddy proxies each published web UI at the same address and port.

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
      address: 127.10.1.1
      hostname: sonarr.example.com
    - name: anime
      address: 127.10.1.2
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
container path, `/data` by default. A path reported by qBittorrent, such as
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

## Migrating an existing stack

Migration is manual; Ansible never imports or overwrites existing service
state. It only creates missing directories and enforces the settings listed in
each service guide. Move one service at a time, in this order: qBittorrent,
qui, Prowlarr, Sonarr, Radarr, autobrr. For each service:

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
