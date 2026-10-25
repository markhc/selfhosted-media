# qBittorrent

[qBittorrent](https://github.com/qbittorrent/qBittorrent) is the BitTorrent
client of the [media stack](../media-stack.md). It runs headless on the NAS
with the official
[qbittorrent-nox image](https://github.com/qbittorrent/docker-qbittorrent-nox),
downloads into the shared data root, and exposes its WebUI and API on its own
loopback address as `qbittorrent:8080` to the other media services. When qui is selected on the same host, qui is the web interface;
otherwise Caddy publishes the qBittorrent WebUI.

## Enable

```yaml
# group_vars/nas.yml
selfhosted_data_path: /srv/data
caddy_enabled: true   # Required only while qui is not selected

qbittorrent_enabled: true
qbittorrent_confirm_legal_notice: true
qbittorrent_hostname: torrents.example.com   # Used only while qui is not selected
```

```yaml
# vault.yml (make vault-edit)
qbittorrent_webui_username: exampleuser
qbittorrent_webui_password: "REPLACE_WITH_A_LONG_RANDOM_PASSWORD"
```

Set `qbittorrent_confirm_legal_notice` to `true` only after reading
qBittorrent's legal notice: "qBittorrent is a file sharing program. When you
run a torrent, its data will be made available to others by means of upload.
Any content you share is your sole responsibility."

Without qui, complete the [Caddy HTTPS setup](caddy.md#set-up-private-https)
for the hostname before deploying. See
[Shared data layout](../media-stack.md#shared-data-layout) for
`selfhosted_data_path` and the shared UID, GID, and umask.

| Variable | Default | Purpose |
| --- | --- | --- |
| `qbittorrent_webui_username` / `_password` | none | Vaulted WebUI login; the password needs at least 8 characters |
| `qbittorrent_hostname` | none | HTTPS hostname, used only while qui is not selected |
| `qbittorrent_address` | `127.10.0.1` | Loopback address of the WebUI and API; see [Names and loopback addresses](../media-stack.md#names-and-loopback-addresses) |
| `qbittorrent_webui_port` | `8080` | WebUI and API port |
| `qbittorrent_torrenting_port` | `6881` | Peer port on every interface (TCP and UDP) |
| `qbittorrent_mounts` | `[]` | Additional host directories to mount; see [Additional mounts](#additional-mounts) |
| `qbittorrent_image_repository` / `_tag` / `_digest` | official image, pinned | See [Container images](../operations.md#container-images) |

### Additional mounts

Everything qBittorrent downloads belongs under the shared data root. To give it
other existing NAS directories, such as a watch folder or a separate
cross-seed tree, list them in `qbittorrent_mounts`:

```yaml
qbittorrent_mounts:
  - path: /srv/watch          # Existing host directory
    target: /watch            # Absolute path inside the container
    read_only: false          # Optional; mounts are read-only by default
```

Each `path` must already exist as a directory outside `/opt/selfhosted`;
Ansible never creates or re-owns it, so the shared UID/GID needs access to it.
Each `target` must be unique and must not be a system directory, `/config`,
`/tmp`, or at, inside, or above `selfhosted_data_container_path` or another
target. Hardlinks and instant moves work only within one filesystem, so keep
directories that the other media services import from under the shared data
root.

## Managed settings

qBittorrent rewrites its configuration file at runtime, so Ansible seeds
`qBittorrent.conf` only when none exists. On later deployments it enforces
only these WebUI settings, stopping the container first if any of them
changed:

- `Address` from `qbittorrent_address` and `Port` from `qbittorrent_webui_port`.
- `LocalHostAuth=true` and `AuthSubnetWhitelistEnabled=false`. Caddy and qui
  connect from loopback, so a loopback or subnet bypass would remove the login.
- `ReverseProxySupportEnabled=true` with `TrustedReverseProxiesList=127.0.0.1`.
  Failed logins are then banned by client address instead of banning Caddy.
- `Username` and `Password_PBKDF2` from the vault. Only the PBKDF2 hash reaches
  the NAS. Changing the vaulted password changes the WebUI login.

qBittorrent 5.3 moved these keys from `[Preferences] WebUI\*` to a `[WebUI]`
section, so Ansible writes them where the version in `qbittorrent_image_tag`
reads them and removes the copies in the other location. Otherwise an older
release would ignore the enforced values, and 5.3 would move stale copies over
them on its first start. The tag must therefore name an official release of
5.0 or newer, such as `"5.2.4-1"`, even when a digest pins the image.
Any other setting changed in the WebUI is kept. A new configuration starts
downloads in `torrents/` under the
[data container path](../media-stack.md#shared-data-layout) (`/data/torrents`
by default), with automatic torrent management on, so each category gets its
own subfolder.

## Set up

1. Deploy, then sign in with the vaulted credentials: in qui, or at the HTTPS
   hostname while qui is not selected.
2. Under **Options → Downloads**, check that the default save path is under
   `/data/torrents`, or `torrents/` under your `selfhosted_data_container_path`.
3. Decide how peers reach the NAS. UPnP / NAT-PMP is on by default under
   **Options → Connection**, so qBittorrent asks the router to forward
   `qbittorrent_torrenting_port` (TCP and UDP) automatically. Turn it off to
   forward the port manually, or to accept outgoing connections only.

## Migrate an existing qBittorrent

This assumes the old container also uses the official image and sees all of
its downloads under one mounted directory; the general steps are in
[Migrating an existing stack](../media-stack.md#migrating-an-existing-stack).

1. Check the old version, for example with
   `sudo docker exec <old-container> qbittorrent-nox --version`, and set
   `qbittorrent_image_tag` to the same or a newer tag.
2. Set `selfhosted_data_path` to the host directory the old container mounts,
   `selfhosted_data_container_path` to where it mounts it (for example
   `/downloads`), and the vaulted credentials. They replace the old WebUI
   login.
3. Stop the old container with a long timeout so it finishes writing resume
   data, and keep it from restarting:

   ```bash
   sudo docker update --restart=no <old-container>
   sudo docker stop --time 1800 <old-container>
   ```

4. Copy the old `/config` host directory, which contains
   `qBittorrent/config/qBittorrent.conf` and the `qBittorrent/data/BT_backup/`
   resume files, into place and give it to the shared UID/GID:

   ```bash
   sudo install -d -o root -g root -m 0700 /opt/selfhosted/qbittorrent
   sudo cp -a <old-config-directory> /opt/selfhosted/qbittorrent/config
   sudo chown -R 1000:1000 /opt/selfhosted/qbittorrent/config
   ```

   Use your `selfhosted_data_uid:selfhosted_data_gid` if they differ from
   `1000`.

5. Run `make deploy-qbittorrent`. Torrents keep their state and save paths.
6. Once qui is deployed, point it and any other client at
   `http://qbittorrent:8080`. Clients that used that Docker name before keep
   working unchanged.

## Deploy

```bash
make deploy-qbittorrent   # Docker and qBittorrent; Caddy first while qui is not selected
make deploy               # The full selected stack
```

To upgrade, change `qbittorrent_image_tag` to a newer release and redeploy; see
[Container images](../operations.md#container-images).
The container gets up to 30 minutes to stop so it can save resume data.

## Network exposure

qBittorrent uses host networking without Docker port publishing:

- The WebUI and API listen only on `127.10.0.1:8080`. While qui is not
  selected, Caddy publishes them at `qbittorrent_hostname` on its private
  listeners; see [Caddy network exposure](caddy.md#network-exposure).
- Once qui is selected on the host, the next qBittorrent deployment removes
  the qBittorrent site from Caddy.
- The peer port listens on every host interface. It is reachable from the
  internet when the router forwards it, which UPnP / NAT-PMP requests by
  default. Peer traffic does not go through Tailscale or a VPN.

## Data

| Path | Contents |
| --- | --- |
| `/opt/selfhosted/qbittorrent/config/qBittorrent/config` | `qBittorrent.conf`, categories, and watched folders |
| `/opt/selfhosted/qbittorrent/config/qBittorrent/data` | `BT_backup/` torrent and resume files, RSS data, and logs |
| `selfhosted_data_path` | Downloads; never created, re-owned, or deleted by Ansible |
| `qbittorrent_mounts` paths | Additional directories; never created, re-owned, or deleted by Ansible |

Back up the configuration directory securely. The container runs as
`selfhosted_data_uid:selfhosted_data_gid` with a read-only root filesystem.
Disabling qBittorrent leaves its container and any Caddy site running; see
[Service selection and removal](../operations.md#service-selection-and-removal).

## Troubleshooting

- **Container unhealthy after deployment**: another process, such as a
  not-yet-stopped old container publishing `8080` on all addresses, may hold
  the port. Check the logs:

  ```bash
  sudo docker compose --project-directory /opt/selfhosted/qbittorrent \
    --project-name selfhosted-qbittorrent logs qbittorrent
  ```

- **Downloads fail with permission errors**: the shared UID/GID needs write
  access to `selfhosted_data_path`, for example
  `sudo -u '#1000' touch /srv/data/torrents/.write-test`.
- **Migrated torrents show missing files**: the old container saw the
  downloads at a different host or container path than the new mount. Set
  `selfhosted_data_path` and `selfhosted_data_container_path` to the host
  directory the old container mounted and the path where it mounted it.
- **Login fails after deployment**: the vaulted credentials replaced the old
  ones. Too many failures ban the client address for a while; see the logs.
