# Sonarr

[Sonarr](https://sonarr.tv/) finds, downloads, and organizes TV series in the
[media stack](../media-stack.md). It runs on the NAS behind [Caddy](caddy.md)
with the [hotio image](https://hotio.dev/containers/sonarr/), as one or more
[instances](../media-stack.md#multiple-instances), for example `tv` for TV
shows and `anime` for anime with its own release profiles and naming. Each
instance sends downloads to [qBittorrent](qbittorrent.md) through
[qui's client proxy](qui.md#set-up) and imports them from the shared data
root as hardlinks.

## Enable

```yaml
# group_vars/nas.yml
selfhosted_data_path: /srv/data
caddy_enabled: true

sonarr_enabled: true
sonarr_instances:
  - name: tv
    address: 127.10.1.1
    hostname: sonarr.example.com
  - name: anime
    address: 127.10.1.2
    hostname: anime.example.com

# Encrypted vault (make vault-edit). `openssl rand -hex 16` prints a 32-character key.
sonarr_api_keys:
  tv: "REPLACE_WITH_32_LOWERCASE_HEX_CHARACTERS"
  anime: "REPLACE_WITH_32_LOWERCASE_HEX_CHARACTERS"
```

Sonarr requires Caddy on the same host. Complete the
[Caddy HTTPS setup](caddy.md#set-up-private-https) for every instance hostname
before deploying; no hostname may be used by another service or instance.

Each instance needs:

- `name`: lowercase letters, digits, and `-`, unique. The instance is called
  `sonarr-<name>`, for example `sonarr-anime`, which is also the name other
  media services use to reach it.
- `address`: a unique loopback address; see
  [Names and loopback addresses](../media-stack.md#names-and-loopback-addresses).
- `hostname`: the HTTPS hostname served by Caddy.
- An API key under its name in the vaulted `sonarr_api_keys`: 32 lowercase
  hexadecimal characters, different for each instance.

| Variable | Default | Purpose |
| --- | --- | --- |
| `sonarr_instances` | `[]` | Instances to deploy, at least one |
| `sonarr_api_keys` | none | Vaulted API key of each instance, keyed by name |
| `sonarr_port` | `8989` | Port of every instance on its own address |
| `sonarr_log_level` | `info` | `info`, `debug`, or `trace` |
| `sonarr_image_repository` / `_tag` / `_digest` | hotio image, pinned | See [Container images](../operations.md#container-images) |

Sonarr mounts the [shared data root](../media-stack.md#shared-data-layout) at
`selfhosted_data_container_path` and runs as the shared UID/GID with the
shared umask.

## Managed settings

Sonarr keeps its settings in `config.xml` and its database, which Ansible
never creates or overwrites. The container environment overrides these
settings on every start, so changing them in the web UI has no effect:

- Bind address and port: the instance's `address` and `sonarr_port`.
- SSL off and an empty URL base, because Caddy terminates TLS and proxies the
  hostname's root.
- Allowed hosts: the instance's hostname, `sonarr-<name>`, and its address.
- Authentication required for every address. Caddy connects from loopback, so
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
   `/data/media/<category>`, for example `/data/media/tv` or
   `/data/media/anime`. Leave **Use Hardlinks instead of Copy** on.
4. Create a client proxy key for the instance in
   [qui](qui.md#set-up). Then, under **Settings → Download Clients**, add a
   **qBittorrent** client with **Show Advanced** on:
   - **Host** `qui`, **Port** `7476`, and **URL Base** set to the
     `/proxy/<client key>` path of the proxy URL. Leave the username and
     password empty; qui supplies the qBittorrent credentials.
   - **Category**: the instance's own category, for example `tv` or `anime`.
     In qui or the qBittorrent WebUI, give that category the save path
     `/data/torrents/<category>`.
5. Add indexers, or connect Prowlarr to `http://sonarr-<name>:8989` with the
   instance's API key; see
   [Service connections](../media-stack.md#service-connections).

Each instance must use its own category and folders, so instances never
import each other's downloads.

## Migrate an existing Sonarr

Move one instance at a time. The hotio and linuxserver images both keep
`config.xml` and `sonarr.db` at the root of `/config`, so a copy of that
directory works with this deployment. The general steps are in
[Migrating an existing stack](../media-stack.md#migrating-an-existing-stack).

1. Check the old version under **System → Status** and set `sonarr_image_tag`
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

4. Copy its `/config` host directory, including `sonarr.db-wal` and
   `sonarr.db-shm` if present, into place and give it to the shared UID/GID:

   ```bash
   sudo install -d -o root -g root -m 0700 /opt/selfhosted/sonarr-tv
   sudo cp -a <old-config-directory> /opt/selfhosted/sonarr-tv/config
   sudo chown -R 1000:1000 /opt/selfhosted/sonarr-tv/config
   ```

   Use the instance's directory and your
   `selfhosted_data_uid:selfhosted_data_gid` if they differ.
5. Run `make deploy-sonarr` and sign in with the old account. Root folders
   and history keep working when `selfhosted_data_container_path` matches the
   old container's data path.
6. Check the download client. A connection to `http://qbittorrent:8080` keeps
   working; change it to qui's client proxy as in [Set up](#set-up) if you
   prefer. If the old instance used a URL base, remove it from Prowlarr and
   other clients.

## Deploy

```bash
make deploy          # Recommended when adding Sonarr or an instance: peers learn its name
make deploy-sonarr   # Docker and every listed instance; Caddy must be deployed
```

To upgrade, change `sonarr_image_tag` to a newer hotio `release-` tag and
redeploy; see [Container images](../operations.md#container-images). In-app
updates are disabled by the image. Sonarr migrates its database on start and
cannot go back, so take a backup first.

## Network exposure

Each instance uses host networking without Docker port publishing:

- It listens only on its own address, port `8989`. Caddy publishes it at the
  instance hostname on its private listeners; see
  [Caddy network exposure](caddy.md#network-exposure).
- It accepts requests only for its hostname, `sonarr-<name>`, and its address,
  plus `localhost` and the NAS's own hostname, which blocks DNS rebinding.
  Other `Host` headers get HTTP 400.
- The web UI requires the login, and the API requires the instance's API key,
  also for requests from the NAS itself.

## Data

| Path | Contents |
| --- | --- |
| `/opt/selfhosted/sonarr-<name>/config` | `config.xml`, the `sonarr.db` database, logs, and scheduled backups |
| `/opt/selfhosted/sonarr-<name>/api.env` | The vaulted API key, readable only by root |
| `selfhosted_data_path` | Media; never created, re-owned, or deleted by Ansible |

Sonarr writes backups to `config/Backups` and needs no other state. The
image's init starts as root with only the capabilities it needs to run Sonarr
as `selfhosted_data_uid:selfhosted_data_gid`.

Disabling Sonarr, or removing an instance from `sonarr_instances`, leaves its
container and Caddy site running. To remove an instance, stop its project and
delete its site, then run `make deploy-caddy`:

```bash
sudo docker compose --project-directory /opt/selfhosted/sonarr-anime \
  --project-name selfhosted-sonarr-anime down
sudo rm /opt/selfhosted/caddy/conf/sites/sonarr-anime.caddy
```

See also [Service selection and removal](../operations.md#service-selection-and-removal).

## Troubleshooting

- **Container unhealthy after deployment**: another process, such as an old
  container publishing `8989` on all addresses, may hold the port. Check the
  logs:

  ```bash
  sudo docker compose --project-directory /opt/selfhosted/sonarr-tv \
    --project-name selfhosted-sonarr-tv logs sonarr
  ```

- **HTTP 400 in the browser**: the hostname is not the instance's `hostname`.
  Fix the inventory and redeploy.
- **Sonarr cannot reach `qui` or `qbittorrent`**: the container learns peer
  names only when it is created. Run `make deploy`, not only
  `make deploy-sonarr`, after selecting a new service.
- **Imports are copies, not hardlinks**: `torrents/` and `media/` are on
  different filesystems, or the download client's save path is not under
  `/data`; see [Shared data layout](../media-stack.md#shared-data-layout).
- **Forgotten password**: stop the instance, set `AuthenticationMethod` to
  `None` in its `config.xml`, start it again, and create new credentials when
  prompted.
