# autobrr

[autobrr](https://github.com/autobrr/autobrr) watches tracker IRC announce
channels and feeds, filters releases, and sends matches to download clients or
Arr applications. It runs on the NAS with the official image, behind
[Caddy](caddy.md), and reaches the other services by their
[media-stack names](../media-stack.md#names-and-loopback-addresses).

## Enable

```yaml
# group_vars/nas.yml
caddy_enabled: true

autobrr_enabled: true
autobrr_hostname: autobrr.example.com
```

autobrr requires Caddy on the same host and needs no vault variables. Its
account and all tracker, download-client, and application credentials are
created and stored by autobrr. Complete the
[Caddy HTTPS setup](caddy.md#set-up-private-https) for the hostname before
deploying. The hostname must not be used by another service.

| Variable | Default | Purpose |
| --- | --- | --- |
| `autobrr_hostname` | none | HTTPS hostname served by Caddy |
| `autobrr_address` | `127.10.0.4` | Loopback address; see [Names and loopback addresses](../media-stack.md#names-and-loopback-addresses) |
| `autobrr_port` | `7474` | Port on that address |
| `autobrr_log_level` | `INFO` | `ERROR`, `WARN`, `INFO`, `DEBUG`, or `TRACE` |
| `autobrr_image_repository` / `_tag` / `_digest` | official image, pinned | See [Container images](../operations.md#container-images) |

The role uses autobrr's SQLite database. It does not mount the shared media
path: API actions send a release to qBittorrent, Sonarr, or Radarr without
reading or writing the downloaded files. Watch-folder and custom-exec actions
that need additional host files are not configured by this role.

## Set up

1. Deploy, then visit the HTTPS hostname from a Tailscale-connected device or
   a [LAN client](caddy.md#optional-lan-access).
2. Create the account when prompted. Do this right after the first deployment:
   until an account exists, anyone who can reach the hostname can claim it.
3. Add indexers under **Settings → Indexers**. Tracker credentials and IRC
   details remain in autobrr's database, not in inventory.
4. Add the destinations needed by your filters under **Settings → Download
   Clients**:
   - **qBittorrent**: `http://qbittorrent:8080`, with the vaulted
     `qbittorrent_webui_username` and `qbittorrent_webui_password`.
   - **Sonarr**: `http://sonarr-<name>:8989`, with that instance's vaulted API
     key, for example `http://sonarr-anime:8989`.
   - **Radarr**: `http://radarr-<name>:7878`, with that instance's vaulted API
     key, for example `http://radarr-hd:7878`.
5. Create filters and assign an action for each destination. Avoid placing
   tracker passkeys or other credentials in filter names or logs.

## Migrate an existing autobrr

Ansible never creates or overwrites autobrr's `config.toml`, SQLite database,
or database backups. Follow the general steps in
[Migrating an existing stack](../media-stack.md#migrating-an-existing-stack):

1. Set `autobrr_image_tag` to the same or a newer version than the old
   installation. Database migrations only run forward.
2. Stop the old container and keep it from restarting:

   ```bash
   sudo docker update --restart=no <old-container>
   sudo docker stop <old-container>
   ```

3. Copy the entire old `/config` directory into place and give it to the
   configured UID/GID:

   ```bash
   sudo install -d -o root -g root -m 0700 /opt/selfhosted/autobrr
   sudo cp -a <old-config-directory> /opt/selfhosted/autobrr/config
   sudo chown -R 1000:1000 /opt/selfhosted/autobrr/config
   ```

   Use your `selfhosted_data_uid:selfhosted_data_gid` if they differ from
   `1000`.
4. Run `make deploy-autobrr`, sign in with the old account, and replace old
   Docker-network destination names with the media-stack names above.

## Deploy

```bash
make deploy           # Recommended when adding autobrr: every media service learns its name
make deploy-autobrr   # Docker and autobrr only; Caddy must already be deployed
```

To upgrade, change `autobrr_image_tag` to a newer release and redeploy; see
[Container images](../operations.md#container-images). The in-app update check
is disabled because the image tag pins the version. Back up the configuration
directory before upgrading and do not downgrade after a database migration.

## Network exposure

autobrr uses host networking without Docker port publishing:

- It listens only on `127.10.0.4:7474` by default. Caddy publishes it at
  `autobrr_hostname` on its private listeners; see
  [Caddy network exposure](caddy.md#network-exposure).
- Browser API requests are restricted to the HTTPS hostname by CORS.
- The container receives the selected media services as local host entries, so
  it can connect to them without exposing their loopback listeners.
- Tracker IRC and feed connections, notifications, and remote actions are
  outbound connections from the NAS.

## Data

| Path | Contents |
| --- | --- |
| `/opt/selfhosted/autobrr/config` | `config.toml`, SQLite database and backups, and stored service credentials |

Back up the configuration directory securely because it contains tracker and
download-client credentials. The container runs as
`selfhosted_data_uid:selfhosted_data_gid` with a read-only root filesystem;
only `/config` and temporary memory are writable. Disabling autobrr leaves its
container and Caddy site running; see
[Service selection and removal](../operations.md#service-selection-and-removal).

## Troubleshooting

- **Container unhealthy after deployment**: another process, such as an old
  container publishing `7474` on all addresses, may hold the port. Check logs:

  ```bash
  sudo docker compose --project-directory /opt/selfhosted/autobrr \
    --project-name selfhosted-autobrr logs autobrr
  ```

- **A destination name does not resolve**: containers learn peer names only
  when recreated. Run `make deploy`, not only `make deploy-autobrr`, after
  selecting or renaming a media service instance.
- **qBittorrent rejects the login**: use `http://qbittorrent:8080` and the
  vaulted WebUI username and password, not qui's account.
- **Sonarr or Radarr rejects an action**: use the instance-specific name and
  matching API key, such as `http://sonarr-tv:8989` with
  `sonarr_api_keys.tv`.
