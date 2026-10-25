# ZNC

ZNC keeps the upstream IRC connections on an existing, more reliable VM while
The Lounge remains on the NAS. When the home connection drops, ZNC continues
buffering; The Lounge reconnects to ZNC over Tailscale and receives playback.
CGNAT alone does not disconnect an outbound IRC connection, but ISP outages,
router restarts, and NAT session resets can. This separates those failures
from the upstream IRC connections, not from The Lounge's own availability.

No VM is provisioned by this repository.

## Select and enroll the host

1. Prepare a Debian/Ubuntu VM with SSH, sudo, Python 3, systemd, and
   `/dev/net/tun`. Its public IP is needed only for initial SSH; **do not open
   public IRC ports**. The default certificate mode needs no public DNS name,
   Caddy, or Cloudflare credential. Keep the cloud firewall restrictive; allow
   outbound IRC TLS, DNS, and Tailscale connectivity. UDP 41641 inbound can
   improve Tailscale direct connectivity but is not required for its relay
   fallback.
2. Add the host under `irc_bouncers` in the ignored local `hosts.yml` using the
   commented example. Do not put it in `nas`. Copy
   `ansible/inventories/example/group_vars/irc_bouncers.yml` to your local
   `group_vars/` if upgrading an existing inventory; `make configure` never
   overwrites an existing local inventory. Set `tailscale_hostname` per host
   for multiple VMs.
3. In that local group file, explicitly enable both services:

   ```yaml
   selfhosted_services:
     tailscale:
       enabled: true
     znc:
       enabled: true
     caddy:
       enabled: false
     thelounge:
       enabled: false
   nas_tailscale_auth_key_tags: ["tag:irc"]
   tailscale_hostname: example-irc
   ```

4. Review the updated policy, then use `make policy-preview` and the appropriate
   explicit [policy apply/replacement target](../tailnet.md#preview-then-explicitly-apply).
   Extend the controller OAuth credential's **Auth Keys — Write** permission to
   include `tag:irc` first. Keep each service tag's self-ownership entry from
   the supplied `tagOwners`: the shared multi-tag client needs it to request a
   single-tag enrollment key. Policy deployment remains separate; a service
   deployment never rewrites it. The existing `nas_tailscale` role also enrolls
   bouncer hosts despite its historical name. State stays on each host, keys
   remain one-off and are cleared after enrollment, and OAuth credentials stay
   on the controller.

If enrollment fails at **Stop if a valid enrollment key was not created**, see
[Troubleshooting single-tag enrollment](../tailnet.md#troubleshooting-single-tag-enrollment).

## Manage private IRC configuration

Run `make vault-edit` and populate `znc_instances` using the commented structure
in `ansible/inventories/example/vault.example.yml`. Each key must match the
inventory alias (for example, `znc_vm`), not the MagicDNS name. This supports
different users and networks on different hosts without copying another
host's configuration to the VM. Existing vaults need this new section added
manually; enabling ZNC without it fails closed.

- Generate a ZNC login hash with `znc --makepass`. If ZNC is not installed on
  the controller, use the pinned image interactively:

  ```bash
  docker run --rm -it --network none --entrypoint /opt/znc/bin/znc \
    znc:1.10.3-slim --makepass
  ```

  Store the **Hash** value from its Argon2id block as `password_hash` in the
  vault; keep the matching login password in your password manager. This is
  distinct from upstream network passwords.
- Each network supports a list of TLS servers, optional server passwords,
  optional SASL username/password, and initial channels with optional keys.
  Upstream TLS certificate validation is enforced. Configured SASL uses PLAIN
  inside that TLS connection and requires authentication to succeed.
- Choose a stable, random `savebuff_password` of at least 20 characters. Keep
  it in the vault and in secure backups; changing it makes existing saved
  buffers unreadable. Do not rotate it as an ordinary login credential.
- Keep all user/network/channel details inside the encrypted vault, not public
  inventory, shell arguments, or committed files. Secret-bearing validation,
  templates, and Compose operations use `no_log` and suppress config diffs.

## Deploy

Deploy only this host (replace the fake inventory alias as needed):

```bash
make deploy ANSIBLE_ARGS='--limit znc_vm'
# Later, configure/redeploy only ZNC, assuming Tailscale is already enrolled:
make deploy-znc ANSIBLE_ARGS='--limit znc_vm'
```

## Container and network exposure

The single ZNC service uses the pinned official `1.10.3-slim` image, a non-root
UID/GID, no Linux capabilities, a read-only root filesystem, bounded logs, and
a default 128 MiB memory ceiling. No build toolchain or scripting runtimes are
installed on the host for ZNC. Override `znc_memory_limit` for larger workloads;
the limit is not a guarantee that every configuration fits in 128 MiB.

ZNC binds **only the discovered Tailscale IPv4**, never the public or LAN
interface, using host networking without Docker port publishing. TCP 6697 is
IRC-only, **requires TLS**, and exposes no web administration interface.
Tailscale adds authenticated, encrypted transport underneath IRC TLS. Public
upstream IRC connections also require TLS. Changing `znc_port` also requires
a reviewed policy change.

## Listener certificates

Choose `znc_tls_mode: self_signed` (the default) or explicitly opt in to
`znc_tls_mode: cloudflare` for a publicly trusted Let's Encrypt certificate.
Neither mode exposes public ports or depends on Caddy.

### Default: self-signed

Ansible generates a self-signed P-256 certificate and private key on the ZNC
host using OpenSSL already present in the pinned image. A restricted, temporary
container performs generation without network access; no extra host packages,
public DNS, ACME account, or Cloudflare credential are needed. The running ZNC
container mounts `/opt/selfhosted/znc/tls` **read-only**. Both `server.crt` and
`server.key` have mode `0600`; private keys never reach the controller or clients.

The certificate always includes the discovered Tailscale IPv4 as an IP SAN.
To connect by name, set `znc_tls_hostname` to the **full** MagicDNS or custom DNS
name in the ignored host/group variables before deploying; that name becomes
an additional DNS SAN. The name must resolve to the bouncer's Tailscale address.
Leave it empty to connect by Tailscale IPv4 instead.

Certificates default to 365 days. Every `make deploy` / `make deploy-znc` checks
validity, identity, matching private key, and the 30-day renewal window, renewing
when needed and restarting ZNC to load the changed certificate. Ordinary reruns
keep the existing certificate and key. `znc_tls_certificate_days` and
`znc_tls_renew_before_days` control these periods. **Renewal happens on deployment,
not in a background scheduler**; arrange regular deployment runs before expiry.
The private key is preserved on renewal, but clients trusting the old self-signed
certificate may still need the renewed certificate installed in their trust store.

Self-signed certificates are not publicly trusted. Retrieve **only the public
certificate** over an authenticated SSH connection and install it in the IRC
client's trust store; never distribute `server.key`. On the bouncer host:

```bash
sudo docker compose --project-directory /opt/selfhosted/znc \
  --project-name selfhosted-znc exec -T znc \
  openssl x509 -in /znc-tls/server.crt -outform PEM
```

For The Lounge, supply that trusted public certificate (or a bundle for multiple
bouncers) to its Node.js process using `NODE_EXTRA_CA_CERTS`, referencing a
read-only mounted certificate file. Restart The Lounge after installing or
updating this trust bundle. Keep certificate verification enabled; do not
globally disable TLS verification to work around a missing trust configuration.
The deployment health check also verifies the generated certificate and IP.

### Optional: Let's Encrypt with Cloudflare DNS-01

This mode uses the pinned `certbot/dns-cloudflare:v5.8.0` image on the bouncer.
Only outbound DNS/HTTPS access is needed for issuance: **do not open public
ports 80, 443, or 6697**. ZNC remains bound only to its Tailscale IPv4.
Enabling this mode accepts the [Let's Encrypt subscriber terms](https://letsencrypt.org/repository/).

1. Choose a hostname under a public domain whose authoritative DNS is hosted
   by Cloudflare, such as `irc.example.com`. It must resolve to the bouncer's
   Tailscale IPv4 for clients: create a **DNS-only** A record (not orange-cloud
   proxied), or use private/split DNS. The role manages only the temporary
   `_acme-challenge` TXT record, not the A record. DNS-01 issuance itself does
   not require a public A record. MagicDNS-only `.ts.net` names cannot use
   your Cloudflare zone. The certificate hostname will be public in
   Certificate Transparency logs, even if its address is private.
2. Create a dedicated Cloudflare API token with **Zone → DNS → Edit** scoped
   only to the relevant zone. Do not use a Global API Key or Cloudflare Origin
   CA certificate (IRC clients do not normally trust Origin CA). Through
   `make vault-edit`, add the token to the existing host entry without
   replacing its users or savebuff password:

   ```yaml
   znc_instances:
     znc_vm:
       cloudflare_api_token: "REPLACE_WITH_A_ZONE_SCOPED_DNS_EDIT_TOKEN"
       # Keep the existing savebuff_password and users here too.
   ```

   This token is independent of `caddy_cloudflare_api_token`; Caddy does
   not need to be selected. Only this bouncer's token is copied to its private
   `acme/cloudflare.ini` (mode `0600`). It is never included in Compose,
   environment variables, image builds, process arguments, or ZNC mounts.
3. In ignored local `host_vars/znc_vm.yml` (replace the fake alias), set:

   ```yaml
   znc_tls_mode: cloudflare
   znc_tls_hostname: irc.example.com
   znc_acme_email: operator@example.com
   znc_acme_dns_propagation_seconds: 60
   ```

   Then deploy the explicitly selected bouncer:

   ```bash
   make deploy-znc ANSIBLE_ARGS='--limit znc_vm'
   ```

Issuance completes and validates the public CA chain, hostname, expiry and
matching key before switching ZNC to the public certificate. Failure aborts
deployment; it never silently falls back to self-signed TLS. The full chain
and key are installed atomically as `tls/acme.pem`, mode `0600`, owned by the
ZNC UID/GID and mounted read-only. ZNC's health check uses the system CA trust
store and verifies `znc_tls_hostname`, not the Tailscale IP. Use that hostname
in Irssi/The Lounge with TLS and ordinary certificate verification enabled;
no self-signed trust bundle is required.

After successful deployment, `selfhosted-znc-acme.timer` checks twice daily
with randomized delay and catches up after downtime. Certbot keeps certificates
that are not due, and hostname changes request a replacement. Successful
certificate changes restart an already-running ZNC container; this briefly
interrupts upstream IRC connections. Unchanged checks do not restart ZNC,
failed issuance leaves existing TLS files untouched, and failed restarts are
retried on the next check. An intentionally stopped bouncer is not started.
No Docker socket is mounted into either helper container. The public key,
private key and ACME account state stay on the bouncer; only the public
certificate is presented to clients. Monitor renewal failures and certificate
expiry; automation does not replace alerting.

On the bouncer, inspect or manually trigger the renewal service:

```bash
sudo systemctl list-timers selfhosted-znc-acme.timer
sudo systemctl start selfhosted-znc-acme.service
sudo systemctl status selfhosted-znc-acme.service
```

The journal reports generic failures only; sensitive Certbot diagnostics stay
under `/opt/selfhosted/znc/acme/logs` and must not be pasted or committed
unredacted. Back up `acme/config` securely along with TLS and ZNC data. ACME
state and credentials are not mounted into the long-running ZNC service.
Switching back to `self_signed` and redeploying disables the ACME timer/service
and removes the managed Cloudflare credential, but preserves ACME account/key
state for deliberate reuse. Disabling ZNC altogether still skips management:
an existing container **and renewal timer** remain until explicitly stopped.

## Connect The Lounge

In [The Lounge](thelounge.md), replace each direct IRC server connection with
the VM's Tailscale IPv4 (self-signed mode only) or the full name configured in
`znc_tls_hostname`, port **6697**, and **TLS enabled**, trusting the certificate
as described in [Listener certificates](#listener-certificates). Existing
plaintext ZNC connections must be updated when deploying this change. Use
`exampleuser/example_network` as the username and the ZNC login password as the
server password, or the ZNC-compatible combined server password
`exampleuser/example_network:LOGIN_PASSWORD`. NickServ/SASL credentials for the
upstream network belong in ZNC, not the Lounge connection to ZNC. Test playback
before removing your old direct connection.

## Buffers and retention

The default rolling history is 1,000 lines **per channel/query**, with at most
50 query buffers per network. `AutoClearChanBuffer` and `AutoClearQueryBuffer` are
disabled so a half-open connection during a home outage cannot silently clear
unseen messages. Reconnecting can therefore repeat already-seen messages.
Tune `znc_buffer_size` (1–10,000) and `znc_max_query_buffers` (1–1,000) to suit
expected outage length and VM memory; old messages beyond those limits are
discarded. This is bounded playback, not an unlimited archive.

The bundled `savebuff` module saves encrypted channel and query buffers every
minute and on graceful shutdown. A crash can lose messages since the last
save; upstream IRC/network outages still cause gaps. Savebuff encryption is
not a substitute for encrypted VM disks and backups: its key and upstream
credentials are necessarily available to the running service.

## Data and configuration lifecycle

Persistent data lives under `/opt/selfhosted/znc/data`; Ansible's authoritative
configuration is under `/opt/selfhosted/znc/managed`; TLS keys and certificates
are under `/opt/selfhosted/znc/tls`. The project directory is
root-only, child directories are `0700`, and configuration files are `0600`.
The container can read but not alter the managed directory. On every start it
copies the source to a writable runtime config (ZNC requires this for locking)
and provisions SASL registries. **Runtime config changes are discarded on
restart**: manage users, servers, credentials, and desired channels in the
vault instead. No webadmin/controlpanel/chansaver modules are enabled.
Configuration changes recreate ZNC and briefly interrupt upstream connections;
unchanged runs do not restart it. Saved buffers and module state are preserved.

Back up the entire project and vault securely, restrict Docker/root access,
and treat runtime configs, module registries, buffers, and container logs as
sensitive. They must never be committed. Disabling ZNC skips management; it
does not stop an existing bouncer or delete its data. Use an explicit Compose
stop on the host when decommissioning it. A ZNC-only host can also be an
existing NAS, but its identity and policy must explicitly allow clients to
reach that host's ZNC port; the supplied `tag:irc` grant targets separate VMs.
