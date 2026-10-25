# qui

[qui](https://github.com/autobrr/qui) is a fast web interface for
[qBittorrent](qbittorrent.md) in the [media stack](../media-stack.md). It runs
on the NAS with the official image, behind [Caddy](caddy.md), and talks to
qBittorrent at `http://qbittorrent:8080`. Its client proxy also lets Sonarr and
Radarr reach qBittorrent through qui without qBittorrent credentials. The
qBittorrent WebUI stays published at its own hostname as a fallback.

## Enable

```yaml
# group_vars/all.yml
qui_hostname: qui.example.com

# group_vars/nas.yml
selfhosted_data_path: /srv/data
caddy_enabled: true

qui_enabled: true
```

qui requires Caddy on the same host and needs no vault variables. Its login
is created in the web UI, and the qBittorrent credentials it stores are the
vaulted `qbittorrent_webui_username` and `_password`. Complete the
[Caddy HTTPS setup](caddy.md#set-up-private-https) for the hostname before
deploying. The hostname must not be used by another service.

| Variable | Default | Purpose |
| --- | --- | --- |
| `qui_hostname` | none | HTTPS hostname served by Caddy |
| `qui_address` | `127.10.0.2` | Loopback address; see [Names and loopback addresses](../media-stack.md#names-and-loopback-addresses) |
| `qui_port` | `7476` | Port on that address |
| `qui_mounts` | `qbittorrent_mounts` | Additional host directories to mount; see [Filesystem access](#filesystem-access) |
| `qui_log_level` | `INFO` | `ERROR`, `WARN`, `INFO`, `DEBUG`, or `TRACE` |
| `qui_image_repository` / `_tag` / `_digest` | official image, pinned | See [Container images](../operations.md#container-images) |

### Filesystem access

Orphan scans, hardlink detection, and cross-seed hardlinks need qui to see
torrent files at the same paths as qBittorrent. qui therefore mounts the
[shared data root](../media-stack.md#shared-data-layout) at
`selfhosted_data_container_path` and, by default, the same
[`qbittorrent_mounts`](qbittorrent.md#additional-mounts), and runs as the
shared UID/GID with the shared umask. Set `qui_mounts` only to give qui
different mounts; they follow the same rules. Orphan scans delete files, so
qui can write wherever qBittorrent can.

## Set up

1. Deploy, then visit the HTTPS hostname from a Tailscale-connected device or
   a [LAN client](caddy.md#optional-lan-access).
2. Create the account when prompted. Do this right after the first deployment:
   until an account exists, anyone who can reach the hostname can claim it.
3. Under **Settings → Instances**, click **Add Instance**:
   - **URL**: `http://qbittorrent:8080`.
   - **qBittorrent Authentication**: **Username and Password**, with the
     vaulted `qbittorrent_webui_username` and `qbittorrent_webui_password`.
   - **Local Filesystem Access**: on.
4. For each Sonarr or Radarr instance, create a key under
   **Settings → Client Proxy** and copy the proxy URL, which qui shows only
   once. Enter it as described in
   [Service connections](../media-stack.md#service-connections).

## Migrate an existing qui

qui keeps its state in `config.toml`, which holds the `sessionSecret` that
encrypts the stored qBittorrent passwords and API keys, and in the `qui.db`
SQLite database. Ansible never creates or overwrites either one. The general
steps are in
[Migrating an existing stack](../media-stack.md#migrating-an-existing-stack).

1. Check the old version, for example with
   `sudo docker exec <old-container> qui version`, and set `qui_image_tag` to
   the same or a newer tag.
2. Stop the old container and keep it from restarting:

   ```bash
   sudo docker update --restart=no <old-container>
   sudo docker stop <old-container>
   ```

3. Copy its `/config` host directory, including `qui.db-wal` and
   `qui.db-shm` if present, into place and give it to the shared UID/GID:

   ```bash
   sudo install -d -o root -g root -m 0700 /opt/selfhosted/qui
   sudo cp -a <old-config-directory> /opt/selfhosted/qui/config
   sudo chown -R 1000:1000 /opt/selfhosted/qui/config
   ```

   Use your `selfhosted_data_uid:selfhosted_data_gid` if they differ from
   `1000`. If the old container set `QUI__SESSION_SECRET`, add that value to
   `config.toml` as `sessionSecret`; otherwise the stored credentials can no
   longer be decrypted.
4. Run `make deploy-qui` and sign in with the old account.
5. Edit the qBittorrent instance if its URL is not `http://qbittorrent:8080`.
   Existing client proxy keys keep working; only the host and port that Sonarr
   and Radarr use change, to `qui` and `7476`.

## Deploy

```bash
make deploy       # Recommended when adding qui: qBittorrent learns the qui name
make deploy-qui   # Docker and qui; Caddy and qBittorrent must be deployed
```

To upgrade, change `qui_image_tag` to a newer release and redeploy; see
[Container images](../operations.md#container-images). The in-app updater is
disabled because the tag pins the version. qui migrates its database on
start and cannot go back, so take a backup first.

## Network exposure

qui uses host networking without Docker port publishing:

- It listens only on `127.10.0.2:7476`. Caddy publishes it at `qui_hostname`
  on its private listeners; see [Caddy network exposure](caddy.md#network-exposure).
- It accepts requests only for `qui_hostname`, the `qui` name, and its
  loopback address (plus `localhost`), which blocks DNS rebinding. Other
  `Host` headers get HTTP 400.
- Its session cookie is HTTPS-only, so sign in through the hostname, not the
  loopback address.
- The client proxy under `/proxy/` accepts requests with a valid client key
  only, including through Caddy.

## Data

| Path | Contents |
| --- | --- |
| `/opt/selfhosted/qui/config` | `config.toml` with the session secret, `qui.db`, backups, themes, and tracker icons |
| `selfhosted_data_path` and `qui_mounts` paths | Media; never created, re-owned, or deleted by Ansible |

Back up the configuration directory securely; a copy without `config.toml`
cannot decrypt the stored credentials. The container runs as
`selfhosted_data_uid:selfhosted_data_gid` with a read-only root filesystem.
Disabling qui leaves its container and Caddy site running; see
[Service selection and removal](../operations.md#service-selection-and-removal).

## Troubleshooting

- **Container unhealthy after deployment**: another process, such as an old
  container publishing `7476` on all addresses, may hold the port. Check the
  logs:

  ```bash
  sudo docker compose --project-directory /opt/selfhosted/qui \
    --project-name selfhosted-qui logs qui
  ```

- **qui cannot reach `qbittorrent`**: the container learns peer names only
  when it is created. Run `make deploy`, not only `make deploy-qui`, after
  selecting qBittorrent.
- **Orphan scan or hardlinks fail**: turn on **Local Filesystem Access** for
  the instance, and check that qui mounts every directory qBittorrent saves
  into at the same container path.
- **Stored passwords stopped working after a migration**: the session secret
  changed. Restore the old `config.toml`, or enter the credentials again.
- **Forgotten password**:
  `sudo docker exec -it selfhosted-qui-qui-1 qui change-password --username <user>`.
