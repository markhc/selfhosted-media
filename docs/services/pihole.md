# Pi-hole

[Pi-hole](https://pi-hole.net) is a network-wide ad-blocking DNS server for the
LAN. It also answers for every hostname that [Caddy](caddy.md) serves with
Caddy's LAN address, so LAN clients reach the web services directly instead of
through Tailscale. Its web interface is served through Caddy.

## Enable

```yaml
# group_vars/nas.yml
caddy_enabled: true
caddy_lan_ip: "192.168.50.10"

pihole_enabled: true
pihole_hostname: pihole.example.com
```

```yaml
# vault.yml (make vault-edit)
pihole_webui_password: "REPLACE_WITH_A_WEB_INTERFACE_PASSWORD"
```

Pi-hole requires Caddy on the same host with
[LAN access](caddy.md#optional-lan-access) configured: `caddy_lan_ip` is both
the address Pi-hole answers DNS on and the address its local records point to.
Complete the [Caddy HTTPS setup](caddy.md#set-up-private-https) for
`pihole_hostname`, like any other web service.

| Variable | Default | Purpose |
| --- | --- | --- |
| `pihole_hostname` | none | HTTPS hostname of the web interface, served by Caddy |
| `pihole_webui_password` | none (vault) | Web interface password, at least 8 characters |
| `pihole_upstreams` | `[1.1.1.1, 1.0.0.1]` | Upstream resolvers: IP addresses with an optional `#port` |
| `pihole_dns_address` | `caddy_lan_ip` | Fixed RFC1918 LAN IPv4 that answers DNS |
| `pihole_uid` / `_gid` | `1000` | Non-root user that runs the DNS server and owns its data |
| `pihole_port` | `8053` | Loopback port of the web interface behind Caddy |

## Local DNS records

Each deployment reads the sites in `/opt/selfhosted/caddy/conf/sites/` and
adds one record that resolves all of their hostnames, plus
`pihole_hostname`, to `caddy_lan_ip`. Sites of disabled services that are
still published keep their record. AAAA queries for those names get an empty
answer, so clients never fall back to a public IPv6 address.

A site published after Pi-hole, for example by `make deploy-<service>` for a
new service or instance, needs `make deploy-pihole` to get its record;
`make deploy` deploys Pi-hole after every web service, so a full deployment
is always complete.

Clients outside the LAN keep using the public DNS records that point to the
Tailscale address; see [Caddy HTTPS setup](caddy.md#set-up-private-https).

## Set up

1. Deploy, then sign in at `https://<pihole_hostname>/admin/` with the vaulted
   password.
2. Allow LAN clients to reach UDP and TCP port 53 on the NAS firewall. Never
   forward port 53 from the internet: Pi-hole answers every client that
   reaches the LAN address.
3. In the router's DHCP settings, hand out the NAS LAN address as the only DNS
   server. A second, public DNS server would let clients bypass both the ad
   blocking and the local records. If the router advertises its own IPv6 DNS
   server, disable that too, or clients may prefer it.
4. Renew a client's DHCP lease and check the answer, for example
   `dig +short sonarr.example.com @192.168.50.10`.

Blocklists, allow and deny lists, and your own local DNS records are managed
in the web interface and kept across deployments. The upstream resolvers,
listening settings, and the Caddy record set are enforced on every deployment
and are read-only in the web interface; change them in the inventory.

## Deploy

```bash
make deploy-pihole   # Docker and Pi-hole; Caddy must be deployed
make deploy          # The full selected stack
```

The first start downloads the blocklists before Pi-hole reports healthy. To
upgrade, change `pihole_image_tag` to a newer release and redeploy; see
[Container images](../operations.md#container-images).

## Network exposure

Pi-hole joins the shared bridge and publishes only DNS:

- Docker publishes UDP/TCP 53 only on `pihole_dns_address`, never on the
  Tailscale address or wildcard host interfaces, so it does not collide with
  systemd-resolved's loopback listener.
- The web interface listens on port `8053` inside the bridge over plain HTTP, without
  Pi-hole's own HTTPS listener; Caddy is the only listener reachable from the
  tailnet or LAN. See [Caddy network exposure](caddy.md#network-exposure).
- Pi-hole's NTP server and clock synchronization are disabled, and DHCP stays
  off.

The container drops every capability except those its start script needs;
the DNS server itself runs as `pihole_uid` with only the capability to bind
port 53. The supplied tailnet policy is unchanged: tailnet clients reach
only the web interface, through Caddy on port 443.

## Data

| Path | Contents |
| --- | --- |
| `/opt/selfhosted/pihole/etc-pihole` | Configuration, blocklists, lists database, and query log |
| `/opt/selfhosted/pihole/webpassword` | Web interface password, mode `0600` |

Back up `etc-pihole` securely and do not delete it on redeployment. The
password file reaches the container as a Compose secret, never as an
environment variable. Disabling Pi-hole stops managing it but leaves its
container, DNS service, and Caddy site running; see
[Service selection and removal](../operations.md#service-selection-and-removal).
Point the router back to another DNS server before stopping it.

## Troubleshooting

- **Container never becomes healthy**: another DNS server on the NAS may hold
  port 53 on the LAN address. Check with `sudo ss -lunp 'sport = :53'`, and
  inspect the logs:

  ```bash
  sudo docker compose --project-directory /opt/selfhosted/pihole \
    --project-name selfhosted-pihole logs pihole
  ```

- **A hostname resolves to the Tailscale address on the LAN**: the client
  still uses another DNS server, or the site was published after the last
  Pi-hole deployment; run `make deploy-pihole`.
- **The web interface shows a 404 page**: open `/admin/` on exactly
  `pihole_hostname`; Pi-hole serves its interface only on that name.
