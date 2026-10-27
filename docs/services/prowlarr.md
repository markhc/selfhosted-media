# Prowlarr

[Prowlarr](https://prowlarr.com/) manages indexers for the
[media stack](../media-stack.md) in one place and syncs them to every
[Sonarr](sonarr.md) and [Radarr](radarr.md) instance. It runs on the NAS
behind [Caddy](caddy.md) with the
[hotio image](https://hotio.dev/containers/prowlarr/). Sonarr and Radarr then
search through Prowlarr at `http://prowlarr:9696`, so indexers, credentials,
and rate limits are configured only once.

## Enable

```yaml
# group_vars/all.yml
prowlarr_hostname: prowlarr.example.com

# group_vars/nas.yml
caddy_enabled: true

prowlarr_enabled: true

# Encrypted vault (make vault-edit). `openssl rand -hex 16` prints a 32-character key.
prowlarr_api_key: "REPLACE_WITH_32_LOWERCASE_HEX_CHARACTERS"
```

Prowlarr requires Caddy on the same host. Complete the
[Caddy HTTPS setup](caddy.md#set-up-private-https) for the hostname before
deploying. The hostname must not be used by another service. Prowlarr handles
no media files, so it does not need `selfhosted_data_path`.

| Variable | Default | Purpose |
| --- | --- | --- |
| `prowlarr_hostname` | none | HTTPS hostname served by Caddy |
| `prowlarr_api_key` | none | Vaulted API key, 32 lowercase hexadecimal characters |
| `prowlarr_address` | `127.10.0.3` | Loopback address; see [Names and loopback addresses](../media-stack.md#names-and-loopback-addresses) |
| `prowlarr_port` | `9696` | Port on that address |
| `prowlarr_log_level` | `info` | `info`, `debug`, or `trace` |
| `prowlarr_image_repository` / `_tag` / `_digest` | hotio image, pinned | See [Container images](../operations.md#container-images) |

Prowlarr runs as `selfhosted_data_uid:selfhosted_data_gid`, like the rest of
the media stack.

## Managed settings

Prowlarr keeps its settings in `config.xml` and its database, which Ansible
never creates or overwrites. The container environment overrides these
settings on every start, so changing them in the web UI has no effect:

- Bind address and port: `prowlarr_address` and `prowlarr_port`.
- SSL off and an empty URL base, because Caddy terminates TLS and proxies the
  hostname's root.
- Allowed hosts: `prowlarr_hostname`, `prowlarr`, and its address.
- Authentication required for every address. Caddy connects from loopback, so
  exempting local addresses would let everyone in.
- The API key from the vault, through a root-only `api.env` file.
- The log level.

Everything else, including the login, indexers, applications, download
clients, and indexer proxies, is set in the web UI.

## Set up

1. Deploy, then visit `prowlarr_hostname` from a Tailscale-connected device
   or a [LAN client](caddy.md#optional-lan-access).
2. When asked to set up authentication, choose **Forms (Login Page)** and
   create the account. Do this right after the first deployment: until then,
   anyone who can reach the hostname can configure Prowlarr.
3. Add indexers under **Indexers → Add Indexer**.
4. [Connect each Sonarr and Radarr instance](#connect-applications).

### Connect applications

Under **Settings → Apps**, add one application for each Sonarr and Radarr
instance:

- **Sync Level**: **Full Sync**, so Prowlarr adds, updates, and removes the
  instance's indexers.
- **Prowlarr Server**: `http://prowlarr:9696`. The instance searches through
  this address, which every media container resolves.
- **Sonarr Server** or **Radarr Server**: `http://sonarr-<name>:8989` or
  `http://radarr-<name>:7878`, for example `http://sonarr-anime:8989`.
- **API Key**: the instance's key from the vaulted `sonarr_api_keys` or
  `radarr_api_keys`.
- **Sync Categories**: the categories the instance should search. For an anime
  instance, also set the anime categories, for example `TV/Anime` (5070).

**Test** each application, save it, and run **Sync App Indexers** from the
**Indexers** page. Each instance then lists the indexers with a
`(Prowlarr)` suffix.

Prowlarr needs no download client, since Sonarr and Radarr send their own
grabs. To grab releases from Prowlarr's search page too, add a **qBittorrent**
client through a separate [qui client proxy](qui.md#set-up) key: **Host**
`qui`, **Port** `7476`, and **URL Base** set to the `/proxy/<client key>`
path, with a category of its own.

## Migrate an existing Prowlarr

The hotio and linuxserver images both keep `config.xml`, `prowlarr.db`, and
custom indexer definitions in `/config`, so a copy of that directory works
with this deployment. The general steps are in
[Migrating an existing stack](../media-stack.md#migrating-an-existing-stack).

1. Check the old version under **System → Status** and set
   `prowlarr_image_tag` to a hotio `release-` tag of the same or a newer
   version.
2. Copy the old API key into the vault as `prowlarr_api_key`. Every synced
   indexer in Sonarr and Radarr stores it, so a new key would break them:

   ```bash
   sudo grep -o '<ApiKey>[^<]*' <old-config-directory>/config.xml
   ```

3. Stop the old container and keep it from restarting:

   ```bash
   sudo docker update --restart=no <old-container>
   sudo docker stop <old-container>
   ```

4. Copy its `/config` host directory, including `prowlarr.db-wal` and
   `prowlarr.db-shm` if present, into place and give it to the shared
   UID/GID:

   ```bash
   sudo install -d -o root -g root -m 0700 /opt/selfhosted/prowlarr
   sudo cp -a <old-config-directory> /opt/selfhosted/prowlarr/config
   sudo chown -R 1000:1000 /opt/selfhosted/prowlarr/config
   ```

   Use your `selfhosted_data_uid:selfhosted_data_gid` if they differ.
5. Run `make deploy-prowlarr` and sign in with the old account.
6. Under **Settings → Apps**, update each application to the addresses in
   [Connect applications](#connect-applications), for example
   `http://sonarr:8989` to `http://sonarr-tv:8989`. If the old Prowlarr used a
   URL base, the **Prowlarr Server** address changes too; a full sync then
   updates the indexers in each instance.

Sonarr and Radarr instances still running in the old stack cannot reach the
new Prowlarr, which listens only on loopback, so their synced indexers fail
until they are migrated. Move them right after Prowlarr.

## Deploy

```bash
make deploy            # Recommended when adding Prowlarr: Sonarr and Radarr learn its name
make deploy-prowlarr   # Docker and Prowlarr only; Caddy must be deployed
```

To upgrade, change `prowlarr_image_tag` to a newer hotio `release-` tag and
redeploy; see [Container images](../operations.md#container-images). In-app
updates are disabled by the image. Prowlarr migrates its database on start and
cannot go back, so take a backup first.

## Network exposure

Prowlarr uses host networking without Docker port publishing:

- It listens only on `prowlarr_address`, port `9696`. Caddy publishes it at
  `prowlarr_hostname` on its private listeners; see
  [Caddy network exposure](caddy.md#network-exposure).
- It accepts requests only for `prowlarr_hostname`, `prowlarr`, and its
  address, plus `localhost` and the NAS's own hostname, which blocks DNS
  rebinding. Other `Host` headers get HTTP 400.
- The web UI requires the login, and the API requires the vaulted API key,
  also for requests from the NAS itself.
- Indexer searches leave from the NAS's own internet connection; no VPN is
  configured.

## Data

| Path | Contents |
| --- | --- |
| `/opt/selfhosted/prowlarr/config` | `config.xml`, the `prowlarr.db` database, custom indexer definitions, logs, and scheduled backups |
| `/opt/selfhosted/prowlarr/api.env` | The vaulted API key, readable only by root |

Prowlarr writes backups to `config/Backups` and needs no other state. The
image's init starts as root with only the capabilities it needs to run
Prowlarr as `selfhosted_data_uid:selfhosted_data_gid`.

Disabling Prowlarr leaves its container and Caddy site running, and the
indexers it synced keep pointing at it. To remove it, delete the synced
indexers in each instance, stop its project, and delete its site, then run
`make deploy-caddy`:

```bash
sudo docker compose --project-directory /opt/selfhosted/prowlarr \
  --project-name selfhosted-prowlarr down
sudo rm /opt/selfhosted/caddy/conf/sites/prowlarr.caddy
```

See also [Service selection and removal](../operations.md#service-selection-and-removal).

## Troubleshooting

- **Container unhealthy after deployment**: another process, such as an old
  container publishing `9696` on all addresses, may hold the port. Check the
  logs:

  ```bash
  sudo docker compose --project-directory /opt/selfhosted/prowlarr \
    --project-name selfhosted-prowlarr logs prowlarr
  ```

- **HTTP 400 in the browser**: the hostname is not `prowlarr_hostname`. Fix
  the inventory and redeploy.
- **An application test fails with a name resolution error**: containers
  learn peer names only when they are created. Run `make deploy`, not only
  `make deploy-prowlarr`, after selecting Prowlarr or adding an instance.
- **Synced indexers fail in Sonarr or Radarr**: the **Prowlarr Server**
  address must be `http://prowlarr:9696`, and `prowlarr_api_key` must match
  the key the indexers were synced with. Run **Sync App Indexers** after
  changing either.
- **Forgotten password**: stop Prowlarr, set `AuthenticationMethod` to `None`
  in its `config.xml`, start it again, and create new credentials when
  prompted.
