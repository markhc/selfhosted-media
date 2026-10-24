# Self Hosted Media

Reusable infrastructure-as-code for a private, self-hosted media stack. Each
service is independently selectable. Ansible installs Docker Engine on a Debian
or Ubuntu NAS and manages Tailscale, Caddy, and The Lounge with Docker Compose.
No Tailscale SSH server is enabled.

## Tailscale prerequisite

Tailscale creates a tailnet when you sign up. This repository configures
machines inside that existing tailnet; it cannot create the identity-provider
account itself.

1. Create or select a tailnet in the Tailscale admin console.
2. Review and apply [`tailscale/policy.hujson`](tailscale/policy.hujson) once in
   the admin console to define `tag:nas`. Tailscale requires the tag to exist
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
port 443 only. It does not grant SSH or other service access. Review before
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
must be restricted to `tag:nas`; Ansible cannot use it to enroll devices under
another tag. **The policy permission can rewrite the entire tailnet policy**,
not just that tag, so keep this credential on the controller and never supply it
to a NAS container.

Run `make vault-edit` and set `tailscale_oauth_client_id` and
`tailscale_oauth_client_secret` in the encrypted local vault. The same
credential is used for policy operations and automatic NAS enrollment, but
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
adjust `ansible/inventories/local/group_vars/all.yml` as needed. Use
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

## Validate changes

Validation uses the non-routable example inventory and does not contact a NAS:

```bash
make check
```
