# Audiobookshelf

[Audiobookshelf](https://github.com/advplyr/audiobookshelf) is a private,
authenticated audiobook and podcast server on the NAS, served through
[Caddy](caddy.md). It streams to web browsers and the Audiobookshelf mobile
apps, syncs listening progress, and can download podcast episodes.

## Enable

```yaml
# group_vars/nas.yml
caddy_enabled: true

audiobookshelf_enabled: true
audiobookshelf_hostname: audiobooks.example.com
audiobookshelf_libraries:
  - name: audiobooks
    path: /srv/media/audiobooks
  - name: podcasts
    path: /srv/media/podcasts
    read_only: false
```

Audiobookshelf requires Caddy on the same host and needs no vault variables of
its own. Replace the placeholder hostname and paths in your local inventory,
and complete the [Caddy HTTPS setup](caddy.md#set-up-private-https) for the
hostname before deploying. The hostname must not be used by another service.

| Variable | Default | Purpose |
| --- | --- | --- |
| `audiobookshelf_hostname` | none | HTTPS hostname served by Caddy |
| `audiobookshelf_libraries` | `[]` | Media directories to mount (see below) |
| `audiobookshelf_uid` / `_gid` | `1000` | Non-root container user and data owner |
| `audiobookshelf_port` | `13378` | Loopback port behind Caddy |

### Media libraries

Each library entry bind-mounts an **existing** NAS directory into the
container at `/media/<name>`:

- `name`: lowercase letters, digits, `-`, or `_`; unique per entry.
- `path`: absolute host path without a trailing slash. It must already exist;
  deployment fails rather than creating an empty directory. Paths that
  contain or are inside the deployment root (`/opt/selfhosted`) are rejected
  so the container can never read another service's credentials.
- `read_only`: defaults to `true`. Set it to `false` for libraries that
  Audiobookshelf writes to, such as podcast downloads, web uploads, or
  embedded metadata and covers.

The container runs as `audiobookshelf_uid:audiobookshelf_gid`,
so that user or group needs read access (and write access for writable
libraries) to the media. Adjust the IDs to match your NAS's media owner instead
of loosening permissions on the media.

## Set up

1. Deploy, then visit your HTTPS hostname from a Tailscale-connected device or
   a [LAN client](caddy.md#optional-lan-access).
2. Create the root (administrator) account when prompted. Do this immediately
   after the first deployment: until a root user exists, anyone who can reach
   the hostname can claim it.
3. Under **Settings → Libraries**, add a library for each mounted folder using
   its container path, for example `/media/audiobooks`.
4. Create regular accounts for other listeners under **Settings → Users**.

The mobile apps connect with the same `https://` hostname as the browser.

## Deploy

```bash
make deploy-audiobookshelf   # Docker and Audiobookshelf; Caddy must be deployed
make deploy                  # The full selected stack
```

To upgrade, change `audiobookshelf_image_tag` to a newer release and
redeploy; see [Container images](../operations.md#container-images). Audiobookshelf migrates its database on start; take a backup first.

## Network exposure

Audiobookshelf uses host networking but binds only to
`127.0.0.1:13378`, without Docker port publishing. Caddy is the only listener
reachable from the tailnet or LAN, on the Tailscale IPv4 and the optional
`caddy_lan_ip`; see [Caddy network exposure](caddy.md#network-exposure).
The supplied tailnet policy lets only tailnet administrators reach the NAS; see
[Tailnet setup and policy](../tailnet.md#prerequisites) to admit other
listeners.

## Data

| Path | Contents |
| --- | --- |
| `/opt/selfhosted/audiobookshelf/config` | Database: users, libraries, progress, settings |
| `/opt/selfhosted/audiobookshelf/metadata` | Covers, cache, logs, and Audiobookshelf's own backups |

Media stays in the library directories you mount; Ansible never creates,
changes ownership of, or deletes them. Back up the config and metadata
directories securely and do not delete them on redeployment. Disabling
Audiobookshelf stops managing it but leaves its container and Caddy site
running; see [Service selection and removal](../operations.md#service-selection-and-removal). See [Operations](../operations.md) for general guidance.

## Troubleshooting

- **Deployment says a library must point to an existing directory**: create
  or fix the host `path`, or remove the entry.
- **Library scans find nothing or podcast downloads fail**: check that the
  configured UID/GID can read the directory (and write to it if
  `read_only: false`), for example with
  `sudo -u '#1000' ls /srv/media/audiobooks`.
- **Container unhealthy**: inspect the logs on the NAS:

  ```bash
  sudo docker compose --project-directory /opt/selfhosted/audiobookshelf \
    --project-name selfhosted-audiobookshelf logs audiobookshelf
  ```
