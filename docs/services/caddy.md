# Caddy

Caddy is the private HTTPS reverse proxy for web services on the NAS (currently
[The Lounge](thelounge.md)). It obtains public certificates through Cloudflare
DNS-01 without opening port 80 or forwarding router ports.

## Enable

```yaml
selfhosted_services:
  caddy:
    enabled: true
```

Caddy requires the containerized [Tailscale](tailscale.md) host to be enrolled,
either by the same run or a previous run.

## Set up private HTTPS

1. Replace `thelounge_hostname: lounge.example.com` in your local inventory
   with a hostname in a Cloudflare-managed zone you control. The example domain
   cannot obtain a certificate for your deployment.
2. Create a Cloudflare API token scoped to that zone with **Zone / Zone / Read**
   and **Zone / DNS / Edit** permissions. Store it as
   `web_stack_cloudflare_api_token` with `make vault-edit`.
3. Deploy Tailscale first (`make deploy-tailscale`) and obtain its address on
   the NAS:

   ```bash
   sudo docker compose --project-directory /opt/selfhosted/tailscale \
     --project-name selfhosted-tailscale exec -T tailscale tailscale ip -4
   ```

4. Create a **DNS-only** (not Cloudflare-proxied) A record for your hostname
   pointing to that Tailscale IPv4 address. Remove any conflicting AAAA record.
   DNS creation is manual: Caddy manages ACME challenge TXT records, not the A
   record. MagicDNS does not automatically resolve custom domains. If your DNS
   resolver blocks private-address responses, configure a split-DNS override.
5. Run `make deploy-web`, or use `make deploy` for the full selected stack.

Then continue with [The Lounge account setup](thelounge.md#create-an-account).

Caddy is built from a versioned official image with a versioned Cloudflare DNS
plugin. DNS-01 issues and renews public certificates without opening port 80 or
forwarding any router ports. Hostnames appear in public certificate-transparency
logs; a public DNS A record also discloses the Tailscale address. Use private
split DNS instead if you do not want to publish the A record.

## Optional LAN access

For LAN access without Tailscale on the client, set `web_stack_lan_ip` in
`ansible/inventories/local/group_vars/all.yml` to the NAS's fixed RFC1918 LAN
IPv4 address, then run `make deploy-web`. For example (placeholder address):

```yaml
web_stack_lan_ip: "192.168.50.10"
```

On your router/local DNS server, override the Lounge hostname to that LAN IP,
or add an entry in the client's hosts file. Keep its external DNS resolution
pointing to the Tailscale IP. Use the same `https://` hostname on both networks;
the existing certificate works for both. Allow LAN clients to reach TCP 443 on
the NAS firewall; no router port forwarding is needed. LAN access uses The
Lounge's login and is not governed by Tailscale's access policy. Leave
`web_stack_lan_ip: ""` for Tailscale-only access.

## Network exposure

Host networking is deliberate: Caddy binds to the discovered Tailscale IPv4
and, if configured, the explicit LAN IPv4 on 443, without Docker port
publishing. Automatic HTTP redirects are disabled so no wildcard port 80
listener is opened. Caddy handles WebSockets automatically. Its admin API binds
only to localhost. These bindings do not replace the NAS's existing firewall for
unrelated services.

Containers restart after reboot; Caddy retries if Tailscale's interface is not
ready yet. Verify tailnet reachability and HTTPS after a NAS reboot.

## Data and credentials

Caddy certificates and ACME accounts are stored under `/opt/selfhosted/web/`.
The Cloudflare token remains in a mode `0600` env file on the NAS for
certificate renewal. See [Operations](../operations.md) for backup and
credential guidance.
