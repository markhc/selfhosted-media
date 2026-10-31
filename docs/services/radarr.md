# Radarr

[Radarr](https://radarr.video/) finds, downloads, and organizes movies in the
[media stack](../media-stack.md). It runs on the NAS behind [Caddy](caddy.md)
with the [hotio image](https://hotio.dev/containers/radarr/), as one or more
[instances](../media-stack.md#multiple-instances), for example `hd` for 1080p
movies and `uhd` for 4K movies with their own quality profiles. Each
instance sends downloads to [qBittorrent](qbittorrent.md) through
[qui's client proxy](qui.md#set-up) and imports them from the shared data
root as hardlinks.

## Enable

```yaml
# group_vars/nas.yml
selfhosted_data_path: /srv/data
caddy_enabled: true

radarr_enabled: true
  radarr_instances:
  - name: hd
    hostname: radarr.example.com
  - name: uhd
    hostname: radarr-uhd.example.com

# Encrypted vault (make vault-edit). `openssl rand -hex 16` prints a 32-character key.
radarr_api_keys:
  hd: "REPLACE_WITH_32_LOWERCASE_HEX_CHARACTERS"
  uhd: "REPLACE_WITH_32_LOWERCASE_HEX_CHARACTERS"
```

Radarr requires Caddy on the same host. Complete the
[Caddy HTTPS setup](caddy.md#set-up-private-https) for every instance hostname
before deploying; no hostname may be used by another service or instance.

Each instance needs:

- `name`: lowercase letters, digits, and `-`, unique. The instance is called
  `radarr-<name>`, for example `radarr-uhd`, which is also the name other
  media services use to reach it.
- `hostname`: the HTTPS hostname served by Caddy.
- An API key under its name in the vaulted `radarr_api_keys`: 32 lowercase
  hexadecimal characters, different for each instance.

| Variable | Default | Purpose |
| --- | --- | --- |
| `radarr_instances` | `[]` | Instances to deploy, at least one |
| `radarr_api_keys` | none | Vaulted API key of each instance, keyed by name |
| `radarr_port` | `7878` | Internal port of every instance on the shared network |
| `radarr_log_level` | `info` | `info`, `debug`, or `trace` |
| `radarr_image_repository` / `_tag` / `_digest` | hotio image, pinned | See [Container images](../operations.md#container-images) |

Radarr mounts the [shared data root](../media-stack.md#shared-data-layout) at
`selfhosted_data_container_path` and runs as the shared UID/GID with the
shared umask.

## Managed settings

Radarr keeps its settings in `config.xml` and its database, which Ansible
never creates or overwrites. The container environment overrides these
settings on every start, so changing them in the web UI has no effect:

- Bind address `0.0.0.0` inside the container and port `radarr_port`.
- SSL off and an empty URL base, because Caddy terminates TLS and proxies the
  hostname's root.
- Allowed hosts: the instance's hostname and `radarr-<name>`.
- Authentication required for every address. Caddy connects from the bridge, so
  exempting local addresses would let everyone in.
- The API key from the vault, through a root-only `api.env` file.
- The log level.

Everything else, including the login, root folders, download clients, and
indexers, is set in the web UI.

## Set up

Repeat these steps for each instance.

1. Deploy, then visit the instance's HTTPS hostname from a
   Tailscale-connected device or a [LAN client](caddy.md#optional-lan-access).
2. When asked to set up authentication, choose **Forms (Login Page)** and
   create the account. Do this right after the first deployment: until then,
   anyone who can reach the hostname can configure the instance.
3. Under **Settings → Media Management**, add the root folder
   `/data/media/<category>`, for example `/data/media/movies` or
   `/data/media/movies-uhd`. Leave **Use Hardlinks instead of Copy** on.
4. Create a client proxy key for the instance in
   [qui](qui.md#set-up). Then, under **Settings → Download Clients**, add a
   **qBittorrent** client with **Show Advanced** on:
   - **Host** `qui`, **Port** `7476`, and **URL Base** set to the
     `/proxy/<client key>` path of the proxy URL. Leave the username and
     password empty; qui supplies the qBittorrent credentials.
   - **Category**: the instance's own category, for example `movies` or
     `movies-uhd`. In qui or the qBittorrent WebUI, give that category the
     save path `/data/torrents/<category>`.
5. Add indexers, or connect the instance in Prowlarr as described in
   [Connect applications](prowlarr.md#connect-applications).

Each instance must use its own category and folders, so instances never
import each other's downloads.

## Migrate an existing Radarr

Move one instance at a time. The hotio and linuxserver images both keep
`config.xml` and `radarr.db` at the root of `/config`, so a copy of that
directory works with this deployment. The general steps are in
[Migrating an existing stack](../media-stack.md#migrating-an-existing-stack).

1. Check the old version under **System → Status** and set `radarr_image_tag`
   to a hotio `release-` tag of the same or a newer version.
2. Copy the old API key into the vault under the instance name, so Prowlarr
   and other clients keep working:

   ```bash
   sudo grep -o '<ApiKey>[^<]*' <old-config-directory>/config.xml
   ```

3. Stop the old container and keep it from restarting:

   ```bash
   sudo docker update --restart=no <old-container>
   sudo docker stop <old-container>
   ```

4. Copy its `/config` host directory, including `radarr.db-wal` and
   `radarr.db-shm` if present, into place and give it to the shared UID/GID:

   ```bash
   sudo install -d -o root -g root -m 0700 /opt/selfhosted/radarr-hd
   sudo cp -a <old-config-directory> /opt/selfhosted/radarr-hd/config
   sudo chown -R 1000:1000 /opt/selfhosted/radarr-hd/config
   ```

   Use the instance's directory and your
   `selfhosted_data_uid:selfhosted_data_gid` if they differ.
5. Run `make deploy-radarr` and sign in with the old account. Root folders
   and history keep working when `selfhosted_data_container_path` matches the
   old container's data path.
6. Check the download client. A connection to `http://qbittorrent:8080` keeps
   working; change it to qui's client proxy as in [Set up](#set-up) if you
   prefer. If the old instance used a URL base, remove it from Prowlarr and
   other clients.

## Deploy

```bash
make deploy          # Recommended when adding Radarr or an instance: peers learn its name
make deploy-radarr   # Docker and every listed instance; Caddy must be deployed
```

To upgrade, change `radarr_image_tag` to a newer hotio `release-` tag and
redeploy; see [Container images](../operations.md#container-images). In-app
updates are disabled by the image. Radarr migrates its database on start and
cannot go back, so take a backup first.

## Network exposure

Each instance joins the shared bridge without publishing a host port:

- It is reachable as `radarr-<name>:7878`. Caddy publishes it at the
  instance hostname on its private listeners; see
  [Caddy network exposure](caddy.md#network-exposure).
- It accepts requests only for its hostname, `radarr-<name>`, `localhost`, and
  the NAS's own hostname, which blocks DNS rebinding.
  Other `Host` headers get HTTP 400.
- The web UI requires the login, and the API requires the instance's API key,
  also for requests from the NAS itself.

## Data

| Path | Contents |
| --- | --- |
| `/opt/selfhosted/radarr-<name>/config` | `config.xml`, the `radarr.db` database, logs, and scheduled backups |
| `/opt/selfhosted/radarr-<name>/api.env` | The vaulted API key, readable only by root |
| `selfhosted_data_path` | Media; never created, re-owned, or deleted by Ansible |

Radarr writes backups to `config/Backups` and needs no other state. The
image's init starts as root with only the capabilities it needs to run Radarr
as `selfhosted_data_uid:selfhosted_data_gid`.

Disabling Radarr, or removing an instance from `radarr_instances`, leaves its
container and Caddy site running. To remove an instance, stop its project and
delete its site, then run `make deploy-caddy`:

```bash
sudo docker compose --project-directory /opt/selfhosted/radarr-uhd \
  --project-name selfhosted-radarr-uhd down
sudo rm /opt/selfhosted/caddy/conf/sites/radarr-uhd.caddy
```

See also [Service selection and removal](../operations.md#service-selection-and-removal).

## Troubleshooting

- **Container unhealthy after deployment**: another process, such as an old
  container publishing `7878` on all addresses, may hold the port. Check the
  logs:

  ```bash
  sudo docker compose --project-directory /opt/selfhosted/radarr-hd \
    --project-name selfhosted-radarr-hd logs radarr
  ```

- **HTTP 400 in the browser**: the hostname is not the instance's `hostname`.
  Fix the inventory and redeploy.
- **Radarr cannot reach `qui` or `qbittorrent`**: the container learns peer
  names only when it is created. Run `make deploy`, not only
  `make deploy-radarr`, after selecting a new service.
- **Imports are copies, not hardlinks**: `torrents/` and `media/` are on
  different filesystems, or the download client's save path is not under
  `/data`; see [Shared data layout](../media-stack.md#shared-data-layout).
- **Forgotten password**: stop the instance, set `AuthenticationMethod` to
  `None` in its `config.xml`, start it again, and create new credentials when
  prompted.
