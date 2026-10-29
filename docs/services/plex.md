# Plex

[Plex Media Server](https://www.plex.tv/) streams the movie, TV, and music
libraries under the [shared data root](../media-stack.md#shared-data-layout)
to the Plex apps and browsers. It runs on the NAS behind [Caddy](caddy.md)
with the [hotio image](https://hotio.dev/containers/plex/), optionally with a
GPU for [hardware transcoding](#hardware-transcoding).

## Enable

```yaml
# group_vars/nas.yml
caddy_enabled: true
selfhosted_data_path: /srv/data

plex_enabled: true
plex_hostname: plex.example.com
# Optional GPU transcoding: dri or nvidia. Without it, Plex transcodes on the CPU.
# plex_hardware_acceleration: dri
```

Plex requires Caddy on the same host and the shared `selfhosted_data_path`,
and needs no vault variables. A GPU is optional; see
[Hardware transcoding](#hardware-transcoding). Complete the
[Caddy HTTPS setup](caddy.md#set-up-private-https) for the hostname before
deploying. The hostname must not be used by another service.

| Variable | Default | Purpose |
| --- | --- | --- |
| `plex_hostname` | none | HTTPS hostname served by Caddy and advertised to Plex clients |
| `plex_address` | `127.10.0.5` | Loopback address of port `32400`; see [Names and loopback addresses](../media-stack.md#names-and-loopback-addresses) |
| `plex_hardware_acceleration` | `none` | `none`, `dri`, or `nvidia`; see [Hardware transcoding](#hardware-transcoding) |
| `plex_data_read_only` | `true` | Mount the shared data root read-only |
| `plex_remote_access_port` | `0` (off) | NAS port the router forwards for [remote access](#remote-access) |
| `plex_remote_access_address` | `caddy_lan_ip` | RFC1918 LAN address that port is published on |
| `plex_image_repository` / `_tag` / `_digest` | hotio image, pinned | See [Container images](../operations.md#container-images) |

Plex runs as `selfhosted_data_uid:selfhosted_data_gid` and sees the shared data
root at `selfhosted_data_container_path`, `/data` by default, like the rest of
the [media stack](../media-stack.md). The mount is read-only, so Plex can never
change the libraries that Sonarr and Radarr manage. Set `plex_data_read_only:
false` only to let Plex delete media or store optimized versions next to it.

## Hardware transcoding

Plex transcodes when a client cannot play a file as it is. A GPU does this much
faster and with less CPU than software transcoding. Hardware transcoding needs
an active [Plex Pass](https://www.plex.tv/plex-pass/) on the account that owns
the server. Choose the GPU type with `plex_hardware_acceleration`:

| Value | GPU | What the container gets |
| --- | --- | --- |
| `none` | None; software transcoding | Nothing |
| `dri` | Intel Quick Sync or AMD VA-API | The `/dev/dri` device nodes |
| `nvidia` | NVIDIA NVENC and NVDEC | Every NVIDIA GPU, through the NVIDIA Container Toolkit |

Changing the value recreates the container on the next deployment.

### Intel and AMD (`dri`)

1. Make sure the NAS's kernel driver for the GPU (Intel `i915` or `xe`, AMD
   `amdgpu`) is loaded, so render nodes exist:

   ```bash
   ls -l /dev/dri   # Expect renderD128 and one cardN per GPU
   ```

   On Debian, the GPU firmware comes from the `non-free-firmware` component,
   for example `firmware-misc-nonfree` (Intel) or `firmware-amd-graphics`
   (AMD). Plex ships its own VA-API drivers, so the host needs no user-space
   video packages.
2. Deploy. Deployment fails if the NAS has no `/dev/dri/renderD*` device. On
   each start, the image adds the Plex user to the groups that own the
   devices, so no host group changes are needed.

### NVIDIA (`nvidia`)

1. Install the NVIDIA driver on the NAS, then the
   [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
   for Docker. Ansible installs neither: the driver must match the kernel and
   GPU.
2. Check that Docker can use the GPU:

   ```bash
   sudo docker run --rm --gpus all ubuntu nvidia-smi
   ```

3. Deploy. Deployment fails if the toolkit's `nvidia-container-runtime-hook`
   is missing. Plex gets every NVIDIA GPU with the `compute`, `utility`, and
   `video` driver capabilities that NVENC and NVDEC need.

### Turn it on in Plex

After [setup](#set-up), open **Settings → Transcoder**, show the advanced
settings, and enable **Use hardware acceleration when available** and
**Use hardware-accelerated video encoding**. With several GPUs, choose one
under **Hardware transcoding device**. While a client transcodes, the
dashboard marks the stream with `(hw)`.

## Managed settings

Plex keeps its settings in `Preferences.xml` and its databases, which Ansible
never creates or overwrites. On every start, the image sets
**Custom server access URLs** to `https://<plex_hostname>:443`, so Plex
publishes that address through plex.tv and clients connect through Caddy.
On its first start, it also puts the transcoder's temporary files in
`config/Temp`. Everything else, including the sign-in, libraries, and users, is
set in the web UI.

## Set up

1. Deploy, then visit `https://<plex_hostname>/web` from a Tailscale-connected
   device or a [LAN client](caddy.md#optional-lan-access).
2. Sign in with your Plex account and claim the server when asked. Do this
   right after the first deployment: until the server is claimed, anyone who
   can reach the hostname can claim it.
3. Add libraries with their container paths, for example `/data/media/tv` and
   `/data/media/movies`.
4. Under **Settings → Network**:
   - Keep **List of IP addresses and networks that are allowed without auth**
     empty. Every request reaches Plex from the same Docker gateway address,
     so an entry that covers it lets everyone in without signing in.
   - Turn off **Enable Relay**, so streams never go through Plex's relay
     servers on the internet.
   - **Secure connections** can be **Required**, because Caddy serves a
     trusted certificate.
5. Leave **Settings → Remote Access** disabled unless you set up
   [remote access](#remote-access). Without it, Plex is reachable only through
   Caddy, not from the internet.
6. [Turn on hardware transcoding](#turn-it-on-in-plex) if you selected a GPU.

### Connect Sonarr and Radarr

Sonarr and Radarr can tell Plex to scan a folder as soon as they import a file.
In each instance, under **Settings → Connect**, add **Plex Media Server**:

- **Host**: `plex`; **Port**: `32400`; **Use SSL**: off.
- **Authenticate with Plex.tv** with the account that owns the server.
- **Update Library**: on.

Both see the media at the same `/data` paths as Plex, so no path mapping is
needed. The instances learn the `plex` name only when they are recreated, so
run `make deploy` after enabling Plex.

## Remote access

By default, Plex is reachable only through Caddy, from the tailnet or the LAN.
Plex Remote Access lets Plex apps anywhere on the internet connect directly,
for example on a phone without Tailscale or for friends you share libraries
with. It is opt-in, because it exposes Plex itself to the internet: every
connection still needs a Plex sign-in and uses Plex's own TLS, but the port is
public.

1. Check that the router has a public IPv4 address: the **Public** address in
   **Settings → Remote Access** must match the router's WAN address. Behind
   carrier-grade NAT (a WAN address in `100.64.0.0/10` or a private range),
   port forwarding cannot work; use Tailscale or ask the ISP for a public
   address.
2. Choose a port, for example `12345`, and set it in `group_vars/nas.yml`. It
   is published on `caddy_lan_ip`, so that must be set; use
   `plex_remote_access_address` for a different LAN address of the NAS:

   ```yaml
   plex_remote_access_port: 12345
   ```

3. Run `make deploy-plex`. Docker now also publishes Plex on
   `<caddy_lan_ip>:12345`, never on the Tailscale or other addresses.
4. On the router, forward external TCP port `12345` to `<caddy_lan_ip>:12345`.
5. In **Settings → Remote Access**, enable remote access, select
   **Manually specify public port**, enter `12345`, and select **Retry**. The
   status turns green once plex.tv reaches the server.

Plex sees remote clients at their real addresses, so the remote streaming
quality settings apply to them. To turn remote access off, disable it in Plex,
remove the router forward, set `plex_remote_access_port: 0`, and redeploy.

## Migrate an existing Plex

Plex keeps its server identity, sign-in token, databases, and metadata in its
`Plex Media Server` directory. The hotio image uses its `/config` directly as
that directory, while the official and linuxserver images keep it under
`/config/Library/Application Support/Plex Media Server`.

1. Check the old version under **Settings → General** and set
   `plex_image_tag` to a hotio `release-` tag of the same or a newer version.
2. Stop the old container and keep it from restarting:

   ```bash
   sudo docker update --restart=no <old-container>
   sudo docker stop <old-container>
   ```

3. Copy the contents of its `Plex Media Server` directory into place and give
   them to the shared UID/GID. `Cache` can be left out to save time:

   ```bash
   sudo install -d -o root -g root -m 0700 /opt/selfhosted/plex
   sudo install -d -o 1000 -g 1000 -m 0700 /opt/selfhosted/plex/config
   sudo cp -a '<old-config-directory>/Library/Application Support/Plex Media Server/.' \
     /opt/selfhosted/plex/config/
   sudo chown -R 1000:1000 /opt/selfhosted/plex/config
   ```

   Use your `selfhosted_data_uid:selfhosted_data_gid` if they differ.
4. Run `make deploy` and sign in. The server keeps its claim, libraries, and
   watch history.
5. If the old container mounted the media at other paths, edit each library's
   folders to the new `/data` paths before the next scan. Plex then matches the
   existing items by file instead of adding them again.

## Deploy

```bash
make deploy        # Recommended when adding Plex: Sonarr and Radarr learn its name
make deploy-plex   # Docker and Plex only; Caddy must be deployed
```

To upgrade, change `plex_image_tag` to a newer hotio `release-` tag and
redeploy; see [Container images](../operations.md#container-images). The image
runs the Plex release it ships, so ignore Plex's own update notices. Plex
migrates its databases on start and cannot go back, so take a backup
first.

## Network exposure

Plex cannot choose the address it listens on, so unlike the rest of the media
stack it does not use host networking:

- It runs in the Compose project's own network, `selfhosted-plex_default`, and
  Docker publishes port `32400` only on `plex_address`. Caddy publishes it at
  `plex_hostname` on its private listeners; see
  [Caddy network exposure](caddy.md#network-exposure).
- With [remote access](#remote-access), Docker also publishes it on
  `plex_remote_access_address` at `plex_remote_access_port`, which the router
  forwards from the internet. Docker's published ports bypass host firewalls
  such as `ufw`.
- There is no LAN discovery (GDM), DLNA, or direct connection to the NAS's LAN
  address. Clients find the server through your Plex account and connect to the
  advertised `https://<plex_hostname>:443`.
- Plex sees every client that connects through Caddy at the Docker gateway
  address and treats it as being on the local network, so the local quality
  settings apply to those streams.
- Every request needs a Plex sign-in, also from the NAS itself, unless
  **List of IP addresses and networks that are allowed without auth** is set.
- Plex connects to plex.tv for sign-in and metadata from the NAS's own
  internet connection.

The supplied tailnet policy lets only tailnet administrators reach the NAS; see
[Tailnet setup and policy](../tailnet.md#prerequisites) to admit other
viewers.

## Data

| Path | Contents |
| --- | --- |
| `/opt/selfhosted/plex/config` | `Preferences.xml` with the server identity and token, databases, metadata, logs, and transcoder temporary files in `Temp` |

The metadata can grow to tens of gigabytes for large libraries. Plex backs up
its databases to `config/Plug-in Support/Databases` every few days; back up the
whole directory securely, because `Preferences.xml` holds the server's sign-in
token. The image's init starts as root with only the capabilities it needs to
run Plex as `selfhosted_data_uid:selfhosted_data_gid`, add it to the GPU
device groups, and update `Preferences.xml`.

Disabling Plex leaves its container and Caddy site running. To remove it, stop
its project and delete its site, then run `make deploy-caddy`. Remove the
server from your Plex account under **Settings → Authorized Devices** on
plex.tv:

```bash
sudo docker compose --project-directory /opt/selfhosted/plex \
  --project-name selfhosted-plex down
sudo rm /opt/selfhosted/caddy/conf/sites/plex.caddy
```

See also [Service selection and removal](../operations.md#service-selection-and-removal).

## Troubleshooting

- **Container unhealthy after deployment**: check the logs:

  ```bash
  sudo docker compose --project-directory /opt/selfhosted/plex \
    --project-name selfhosted-plex logs plex
  ```

- **Apps say the server is unavailable**: the app must reach
  `plex_hostname`. Check that the hostname resolves to Caddy for that device,
  for example through [Pi-hole](pihole.md) or the DNS record in
  [Caddy's setup](caddy.md#set-up-private-https). Apps may first try the
  container's internal address and fall back after a few seconds.
- **Libraries are empty**: the shared UID/GID must be able to read the media,
  for example `sudo -u '#1000' ls /srv/data/media/tv`.
- **Transcodes are not marked `(hw)`**: check the Plex Pass, the
  [Transcoder settings](#turn-it-on-in-plex), and the devices inside the
  container. Plex's log mentions the GPUs it found:

  ```bash
  sudo docker exec selfhosted-plex-plex-1 ls -l /dev/dri   # dri
  sudo docker exec selfhosted-plex-plex-1 nvidia-smi       # nvidia
  ```

- **Remote access stays red**: check each hop from the outside in: the public
  address matches the router's WAN address, the router forwards the port to
  `plex_remote_access_address`, and the NAS listens on it
  (`sudo ss -ltn | grep 12345`). Test from outside the LAN, for example on
  mobile data, because many routers do not loop connections back to their own
  public address.
- **`could not select device driver "nvidia"`**: the NVIDIA Container Toolkit
  is missing or Docker was not restarted after installing it.
- **Sonarr or Radarr cannot reach `plex`**: run `make deploy`, not only
  `make deploy-plex`, so the instances learn the name.
