# Self Hosted Media

Reusable infrastructure-as-code for a private, self-hosted media stack. Each
service is independently selectable. Ansible installs Docker Engine on a Debian
or Ubuntu hosts and manages Tailscale, Caddy, The Lounge, and optional ZNC with
Docker Compose. ZNC can live on a separate cloud VM; no VM is provisioned by
this repository. No Tailscale SSH server is enabled.

## Tailscale prerequisite

Tailscale creates a tailnet when you sign up. This repository configures
machines inside that existing tailnet; it cannot create the identity-provider
account itself.

1. Create or select a tailnet in the Tailscale admin console.
2. Review and apply [`tailscale/policy.hujson`](tailscale/policy.hujson) once in
   the admin console to define `tag:nas` (and `tag:irc` for optional ZNC hosts).
   Tailscale requires the tag to exist
   before it can restrict an OAuth client's auth-key permission to that tag.
3. Create the single controller OAuth credential described below and store it
   in the encrypted local Ansible Vault created by `make configure`.

For a fresh NAS, Ansible uses the controller OAuth credential to generate a
10-minute, one-off, non-ephemeral, pre-approved auth key restricted to
`tag:nas`. Only this generated key reaches the NAS. After enrollment, Ansible
clears it from the NAS environment and recreates the container without it,
verifying that saved state works. Ordinary reruns and restarts make no API
request for an auth key while valid state remains in
`/opt/selfhosted/tailscale/state`. Do not delete state just to rotate the OAuth
credential.

If you deployed an earlier auth-key or device-side OAuth configuration, preserve
the existing state and run the normal deployment. Ansible will not mint a new
key for an already-enrolled NAS. After verifying connectivity, revoke obsolete
credentials.

See Tailscale's [auth-key documentation](https://tailscale.com/docs/features/access-control/auth-keys).

The supplied policy permits tailnet administrators to access the NAS on HTTPS
port 443 only, and permits the NAS and administrators to reach `tag:irc` on
TCP 6697 for ZNC. It grants no access from the bouncer back into the NAS and
does not grant SSH. Review before
replacing an existing policy: unrelated grants will be removed.

## Automate the tailnet policy

This is a separate, explicit controller-only workflow. It never connects to the
NAS, uses sudo, installs Docker, or runs as part of `site.yml`. Complete the
Python dependency setup under [Configure the NAS](#configure-the-nas) first;
no NAS inventory or Galaxy collection is required for the policy playbook.

### Create the controller OAuth credential

In the Tailscale admin console's **Trust credentials** page, select
**Credential → OAuth**. Grant:

| Permission | Scope |
| --- | --- |
| Auth Keys — Write, restricted to `tag:nas` | `auth_keys` |
| Policy file — Write | `policy_file` |
| Devices / Posture attributes — Write | `devices:posture_attributes` |
| Devices / Core — Read | `devices:core:read` |

The latter two are Tailscale's required dependencies for policy-write access.
No device-core write, DNS, or `all` scope is needed. The `auth_keys` permission
must be restricted to `tag:nas`, plus `tag:irc` if deploying a separate bouncer.
Each generated enrollment key still carries only its host's selected tag.
Tailscale requires generated auth-key tags to exactly match all client tags,
unless tag ownership explicitly permits a subset. The supplied policy therefore
makes `tag:nas` and `tag:irc` each their own owner, in addition to administrator
ownership. Without those entries in the **live** policy, adding both tags to
the OAuth client is not sufficient to enroll a host with only one of them.
**The policy permission can rewrite the entire tailnet policy**,
not just that tag, so keep this credential on the controller and never supply it
to a NAS container.

Run `make vault-edit` and set `tailscale_oauth_client_id` and
`tailscale_oauth_client_secret` in the encrypted local vault. The same
credential is used for policy operations and automatic host enrollment, but
each operation requests only the scope it needs.

The credential identifies its own tailnet; no tailnet domain or account ID
needs to be saved in the repository.

### Preview, then explicitly apply

```bash
# Read the current policy and validate the candidate, without applying it.
make policy-preview

# Applies only when the live policy is still Tailscale's untouched default.
make policy-apply
```

Without `tailnet_policy_apply=true`, the playbook only previews—even without
`--check`. With `--check`, it never applies, regardless of either apply flag.
Preview requires network access and the OAuth credential: it exchanges a
short-lived token and uses Tailscale's non-mutating validation API, including
the candidate's policy tests. It is not an offline syntax check.

For an existing customized tailnet, review its live policy in the admin console
and explicitly acknowledge **whole-policy replacement**:

```bash
make policy-replace
```

The replacement acknowledgment is required for subsequent changes to an already
managed policy too. There is no implicit adoption or automatic merging. The
playbook uses Tailscale's `If-Match: "ts-default"` guard for initial bootstrap;
acknowledged replacements use the live policy's fetched `ETag`. A concurrent
edit fails without retrying or overwriting it. An unchanged policy is a no-op;
comparison ignores surrounding whitespace, but edits to formatting/comments
inside the file count as changes.

The default source is the public `tailscale/policy.hujson`. If your complete
policy needs real user identities or other private details, keep a reviewed
copy under the ignored local inventory directory and select it with
`make policy-preview POLICY_FILE=/absolute/path/to/private-policy.hujson` (and
the same option on an apply target). Never commit that copy, an export of the
live policy, or credentials. API responses, policy contents, and tokens are
hidden even with `--diff`; the preview reports only validation success and
whether a change is needed. For a validation failure, inspect the candidate
using the Tailscale policy editor rather than enabling secret logging.

Later policy changes remain explicit and reviewed through this controller
workflow. NAS enrollment keys are generated automatically only when persistent
Tailscale state is absent.

## Configure the NAS

Requirements on the controller are Python 3.12+ and SSH access to a Debian or
Ubuntu NAS account with sudo privileges, Python 3, systemd, and `/dev/net/tun`.
Docker Engine and its Compose plugin are installed from Docker's official apt
repository; an existing conflicting Docker/containerd installation must be
resolved manually rather than removed automatically.

Run the one-time setup from the repository root:

```bash
make configure
```

This creates `.venv`, installs the pinned Python and Galaxy dependencies,
copies the example inventory to the ignored `ansible/inventories/local/`, and
creates `ansible/inventories/local/vault.yml` with `ansible-vault`. The command
prompts for a vault password and opens the encrypted credential template in
your editor. A local ignored `.vault-password` file may be used to avoid repeat
prompts; otherwise every vault or deployment target asks for the password.
Never commit either file.

Edit `ansible/inventories/local/hosts.yml` with the NAS connection details and
adjust `ansible/inventories/local/group_vars/nas.yml` (service selections) and
`group_vars/all.yml` (shared settings) as needed. Existing local inventories with
NAS service selections in `all.yml` continue to work; move those selections to
`nas.yml` before adding other hosts so they do not inherit NAS-specific settings. Use
`make vault-edit` whenever a token changes. The entire local inventory is
ignored by Git because it can identify private infrastructure.

When upgrading an existing vault, replace `nas_tailscale_auth_key` and the old
`tailnet_policy_client_*` values with the single `tailscale_oauth_client_id` and
`tailscale_oauth_client_secret` pair.

Before deploying the web services, complete the DNS steps below. Then deploy
all services enabled in the local inventory:

```bash
make deploy
```

Set `selfhosted_services.tailscale.enabled` to `false` to skip Tailscale without
changing the playbook. Each service has its own
`selfhosted_services.<name>.enabled` setting in the inventory. The Lounge
requires Caddy; the web stack needs the containerized Tailscale NAS to be
enrolled, either by this run or a previous run.

Use `make deploy-tailscale` for Docker/Tailscale only, or `make deploy-web` for
Docker/Caddy/The Lounge only (no Tailscale auth key is needed for the latter).
Append `ASK_BECOME_PASS=1` to a target if sudo requires a password. Initial
enrollment should use LAN SSH, not a Tailscale connection that may be
interrupted. Advanced Ansible options can be supplied through `ANSIBLE_ARGS`.
Deployment targets reject `--check`/`-C` because check mode creates no
containers; use `make check` for repository validation instead. If
`ANSIBLE_ARGS` was exported previously, clear it with `unset ANSIBLE_ARGS`.

To confirm which tailnet accepted the NAS, run
`make tailscale-status ASK_BECOME_PASS=1`. It reports the machine name, active
tailnet, tags, and Tailscale addresses from the container. If the node is online
there but absent from the admin console, switch the console to the reported
tailnet; OAuth credentials always enroll into the tailnet that owns them.

Disabled services are skipped, not uninstalled. If Caddy remains enabled while
The Lounge is disabled, Compose removes the old Lounge container but preserves
its data. Disabling both web services skips that project entirely; explicitly
stop the project if it was already deployed.

## Private HTTPS and The Lounge

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
6. Create a Lounge account interactively **on the NAS**; the placeholder below
   is a local app username, not an IRC nick or an infrastructure credential:

   ```bash
   sudo docker compose --project-directory /opt/selfhosted/web \
     --project-name selfhosted-web exec --user 1000:1000 thelounge \
     thelounge add example-user
   ```

7. From a Tailscale-connected administrator device, visit your HTTPS hostname.

Caddy is built from a versioned official image with a versioned Cloudflare DNS
plugin. DNS-01 issues and renews public certificates without opening port 80 or
forwarding any router ports. Hostnames appear in public certificate-transparency
logs; a public DNS A record also discloses the Tailscale address. Use private
split DNS instead if you do not want to publish the A record.

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

Host networking is deliberate: Caddy binds to the discovered Tailscale IPv4
and, if configured, the explicit LAN IPv4 on 443; The Lounge binds only to
`127.0.0.1:9000`, and neither uses Docker
port publishing. Caddy handles WebSockets automatically. Its admin API binds
only to localhost. The Lounge is private/authenticated, not a public IRC relay.
These bindings do not replace the NAS's existing firewall for unrelated services.

Persistent state is under `/opt/selfhosted/tailscale/state` and
`/opt/selfhosted/web/` (Lounge accounts/history/uploads, Caddy certificates and
ACME accounts). Back it up securely; do not commit or delete it on redeployment.
Credential env files on the NAS are mode `0600` and stay outside Git. The
Tailscale auth key is cleared after enrollment; the Cloudflare token remains
available for certificate renewal. Docker administrators can inspect container
environments; restrict Docker access.

Do not run native `tailscaled` alongside its container. The playbook refuses an
active or boot-enabled native daemon and does not silently migrate existing
state. A fresh state directory registers a new device; plan migration separately
if already deployed.
Containers restart after reboot; Caddy retries if Tailscale's interface is not
ready yet. Verify tailnet reachability and HTTPS after a NAS reboot.

## Optional cloud ZNC bouncer

ZNC keeps the upstream IRC connections on an existing, more reliable VM while
The Lounge remains on the NAS. When the home connection drops, ZNC continues
buffering; The Lounge reconnects to ZNC over Tailscale and receives playback.
CGNAT alone does not disconnect an outbound IRC connection, but ISP outages,
router restarts, and NAT session resets can. This separates those failures
from the upstream IRC connections, not from The Lounge's own availability.

### Select and enroll the host

1. Prepare a Debian/Ubuntu VM with SSH, sudo, Python 3, systemd, and
   `/dev/net/tun`. Its public IP is needed only for initial SSH; **do not open
   public IRC ports**. The default certificate mode needs no public DNS name,
   Caddy, or Cloudflare credential. Keep the cloud firewall restrictive; allow outbound IRC TLS, DNS,
   and Tailscale connectivity. UDP 41641 inbound can improve Tailscale direct
   connectivity but is not required for its relay fallback.
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
   explicit policy apply/replacement target. Extend the controller OAuth
   credential's **Auth Keys — Write** permission to include `tag:irc` first.
   Keep each service tag's self-ownership entry from the supplied `tagOwners`:
   the shared multi-tag client needs it to request a single-tag enrollment key.
   Policy deployment remains separate; a service deployment never rewrites it.
   The existing `nas_tailscale` role also enrolls bouncer hosts despite its
   historical name. State stays on each host, keys remain one-off and are
   cleared after enrollment, and OAuth credentials stay on the controller.

### Manage private IRC configuration

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

Deploy only this host (replace the fake inventory alias as needed):

```bash
make deploy ANSIBLE_ARGS='--limit znc_vm'
# Later, configure/redeploy only ZNC, assuming Tailscale is already enrolled:
make deploy-znc ANSIBLE_ARGS='--limit znc_vm'
```

If enrollment fails at **Stop if a valid enrollment key was not created** while
the OAuth client already has both tags, check the live policy contains:

```json
"tagOwners": {
  "tag:nas": ["autogroup:admin", "tag:nas"],
  "tag:irc": ["autogroup:admin", "tag:irc"]
}
```

Review with `make policy-preview`, then explicitly apply the complete reviewed
policy using the policy workflow above (an already customized policy requires
`make policy-replace`). Do not work around this by tagging both hosts with both
service identities: that would mix their access privileges. The enrollment error
reports only the HTTP status and safe guidance, never tokens or response bodies.

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

### Listener certificates

Choose `znc_tls_mode: self_signed` (the default) or explicitly opt in to
`znc_tls_mode: cloudflare` for a publicly trusted Let's Encrypt certificate.
Neither mode exposes public ports or depends on Caddy.

#### Default: self-signed

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

#### Optional: Let's Encrypt with Cloudflare DNS-01

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

   This token is independent of `web_stack_cloudflare_api_token`; Caddy does
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

### Connect The Lounge and understand retention

In The Lounge, replace each direct IRC server connection with the VM's
Tailscale IPv4 (self-signed mode only) or the full name configured in `znc_tls_hostname`, port
**6697**, and **TLS enabled**, trusting the certificate as described above.
Existing plaintext ZNC connections must be updated when deploying this change.
Use `exampleuser/example_network` as the username and
the ZNC login password as the server password, or the ZNC-compatible combined
server password `exampleuser/example_network:LOGIN_PASSWORD`. NickServ/SASL
credentials for the upstream network belong in ZNC, not the Lounge connection
to ZNC. Test playback before removing your old direct connection.

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

## Validate changes

Validation uses the non-routable example inventory and does not contact a NAS:

```bash
make check
```

The offline tests check host selection, secret redaction (including `--diff`),
input validation, and generated configuration. An additional local Docker
smoke test starts ZNC and a fake TLS IRC server in an isolated network namespace,
checks certificate generation/renewal, verified TLS, SASL, and missed-message
playback across disconnects and restarts. ACME tests use a local fake CA to
check atomic installation, key rotation, hostname/expiry/trust failures,
renewal restart retries, and secret redaction. Opt-in container checks also
verify the public-certificate configuration and non-root Certbot plugin
runtime without contacting a CA or DNS provider. No host ports are exposed:

```bash
ZNC_CONTAINER_TESTS=1 make test
```
