# Caddy

Caddy is the private HTTPS reverse proxy for web services such as
[The Lounge](thelounge.md) and [Audiobookshelf](audiobookshelf.md). It obtains
public certificates through Cloudflare DNS-01 without opening port 80 or
forwarding router ports. Each web service is deployed separately and publishes
its own hostname to Caddy; see [How services publish a site](#how-services-publish-a-site).

## Enable

```yaml
caddy_enabled: true
```

Caddy requires the containerized [Tailscale](tailscale.md) host to be enrolled,
either by the same run or a previous run. Every web service that uses Caddy
requires it to be selected on the same host and deployed first; `make deploy`
orders this automatically.

## Set up private HTTPS

1. Replace the placeholder hostname of each selected service in your local
   `group_vars/nas.yml` (`thelounge_hostname`, `audiobookshelf_hostname`) with
   a hostname in a Cloudflare-managed zone you control. The example domain
   cannot obtain a certificate for your deployment.
2. Create a Cloudflare API token scoped to that zone with **Zone / Zone / Read**
   and **Zone / DNS / Edit** permissions. Store it as
   `caddy_cloudflare_api_token` with `make vault-edit`.
3. Deploy Tailscale first (`make deploy-tailscale`) and obtain its address on
   the NAS:

   ```bash
   sudo docker compose --project-directory /opt/selfhosted/tailscale \
     --project-name selfhosted-tailscale exec -T tailscale tailscale ip -4
   ```

4. Create a **DNS-only** (not Cloudflare-proxied) A record for each hostname
   pointing to that Tailscale IPv4 address. Remove any conflicting AAAA record.
   DNS creation is manual: Caddy manages ACME challenge TXT records, not the A
   record. MagicDNS does not automatically resolve custom domains. If your DNS
   resolver blocks private-address responses, configure a split-DNS override.
5. Run `make deploy` for the full selected stack, or `make deploy-caddy`
   followed by `make deploy-<service>` for each web service.

Then continue with [The Lounge account setup](thelounge.md#create-an-account)
or [Audiobookshelf setup](audiobookshelf.md#set-up).

Caddy is built from a versioned official image with a versioned Cloudflare DNS
plugin. DNS-01 issues and renews public certificates without opening port 80 or
forwarding any router ports. Hostnames appear in public certificate-transparency
logs; a public DNS A record also discloses the Tailscale address. Use private
split DNS instead if you do not want to publish the A record.

## Optional LAN access

For LAN access without Tailscale on the client, set `caddy_lan_ip` in
`ansible/inventories/local/group_vars/nas.yml` to the NAS's fixed RFC1918 LAN
IPv4 address, then run `make deploy-caddy`. For example (placeholder address):

```yaml
caddy_lan_ip: "192.168.50.10"
```

On your router/local DNS server, override each service hostname to that LAN
IP, or add entries in the client's hosts file. [Pi-hole](pihole.md) does this
automatically for every hostname Caddy serves. Keep their external DNS
resolution pointing to the Tailscale IP. Use the same `https://` hostname on
both networks; the existing certificates work for both. Allow LAN clients to
reach TCP 443 on the NAS firewall; no router port forwarding is needed. LAN
access relies on each service's own login and is not governed by Tailscale's
access policy. Leave `caddy_lan_ip: ""` for Tailscale-only access.

## How services publish a site

Caddy's own Caddyfile defines the private listener and certificate settings
once, as the `selfhosted_private` snippet, and imports every file in
`/opt/selfhosted/caddy/conf/sites/`. A web service role starts its loopback-only
container, then calls the caddy role's `site` tasks with a site name, hostname,
and loopback upstream: usually `127.0.0.1:<port>`, or the service's own
[media stack address](../media-stack.md#names-and-loopback-addresses).

```yaml
- name: Publish Example through Caddy
  ansible.builtin.include_role:
    name: caddy
    tasks_from: site
  vars:
    caddy_site_name: example
    caddy_site_hostname: "{{ example_hostname }}"
    caddy_site_upstream: "127.0.0.1:{{ example_port }}"
```

This writes `sites/<name>.caddy`, which always imports the private listener,
and gracefully reloads Caddy. A reload that fails, for example because two
services use the same hostname, fails the deployment and leaves the previous
configuration running. Adding a web service never requires changing the
Caddy role.

A role that stops publishing a site it owns calls the `unpublish` tasks with
the same `caddy_site_name`. They delete `sites/<name>.caddy` and
reload Caddy only if the file exists.

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

Caddy certificates and ACME accounts are stored under
`/opt/selfhosted/caddy/data`. The Cloudflare token remains in the mode `0600`
`/opt/selfhosted/caddy/cloudflare.env` for certificate renewal; the image build
context contains only the Dockerfile. See [Operations](../operations.md) for backup and
credential guidance.
