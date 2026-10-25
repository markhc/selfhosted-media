# Getting Started

This guide covers the controller setup, local inventory, and deployment
workflow shared by every service. Service-specific steps live in the
[service guides](../README.md#services).

## Requirements

- A controller with Python 3.12+.
- SSH access to a Debian or Ubuntu host account with sudo privileges, Python 3,
  systemd, and `/dev/net/tun`.
- An existing tailnet and controller OAuth credential if Tailscale is selected;
  see [Tailnet setup and policy](tailnet.md).

Docker Engine and its Compose plugin are installed from Docker's official apt
repository; an existing conflicting Docker/containerd installation must be
resolved manually rather than removed automatically.

## Configure the controller

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

## Edit the local inventory

Edit `ansible/inventories/local/hosts.yml` with the host connection details and
adjust the group variables:

| File | Purpose |
| --- | --- |
| `group_vars/all.yml` | Settings for every host, such as the timezone |
| `group_vars/nas.yml` | NAS service selections and settings, one section per service |
| `group_vars/irc_bouncers.yml` | Optional bouncer host service selections and settings |
| `vault.yml` | Encrypted credentials; edit with `make vault-edit` |

Keep service flags out of `all.yml`: a flag there would select the service on
every host. Service settings such as hostnames may stay in an existing
`all.yml`, but new examples keep them in their service's section of the group
file. `make configure` never overwrites an existing
local inventory, so copy new example group files manually when upgrading. Use
`make vault-edit` whenever a token changes. The entire local inventory is
ignored by Git because it can identify private infrastructure.

When upgrading an existing vault, replace `nas_tailscale_auth_key` and the old
`tailnet_policy_client_*` values with the single `tailscale_oauth_client_id` and
`tailscale_oauth_client_secret` pair. Deployments from the former combined web
stack must follow [Migrate from the combined web stack](operations.md#migrate-from-the-combined-web-stack).

## Select services

Each service has its own `<service>_enabled` flag, kept at the top of that
service's section in the group file next to its other settings, for example:

```yaml
# --- The Lounge ---
thelounge_enabled: true
thelounge_hostname: lounge.example.com

# --- ZNC ---
znc_enabled: false
```

The keys are `tailscale`, `caddy`, `thelounge`, `audiobookshelf`,
`qbittorrent`, and `znc`; an unset flag means disabled. Set a flag to `false`
to skip the service without changing the playbook. Values must be YAML booleans
(`true`/`false`), not quoted strings. A service runs on every host whose group
or host variables enable it, so keep NAS and bouncer selections in their own
group files.

Inventories from before this layout used a `selfhosted_services` map
(`selfhosted_services.caddy.enabled`). `make deploy` refuses to run while that
map is defined; replace each entry with the matching flag, such as
`caddy_enabled: true`. Review each
selected service's guide for its prerequisites and dependencies before
deploying; for example, the web services require the
[Caddy DNS steps](services/caddy.md#set-up-private-https). Disabling a service
skips management rather than uninstalling it; see
[Operations](operations.md#service-selection-and-removal).

## Set the timezone

Service containers receive a `TZ` environment variable, which sets the
timezone for log timestamps and in-app times. It defaults to `UTC`; set an
IANA timezone name in `group_vars/all.yml`:

```yaml
selfhosted_timezone: America/Sao_Paulo
```

To override one service, set `<service>_timezone`, for example
`znc_timezone` in a bouncer's host variables. The setting applies to Caddy,
The Lounge, Audiobookshelf, qBittorrent, and ZNC. Tailscale is excluded because its image
has no timezone data, so it always logs in UTC. Changing the value recreates
the affected containers on the next deployment.

## Deploy

Deploy all services enabled in the local inventory:

```bash
make deploy
```

Deploy one service, plus Docker, with `make deploy-<service>`, where
`<service>` is its selection key:

```bash
make deploy-tailscale
make deploy-caddy
make deploy-audiobookshelf
```

Each service is its own Ansible role and Docker Compose project under
`/opt/selfhosted/<service>`. Web services such as The Lounge and
Audiobookshelf require Caddy to be deployed first; `make deploy` orders this
automatically. The download and library services share the data layout in
[Media stack](media-stack.md). Only `deploy-tailscale` on a host without Tailscale state needs
to create an enrollment key.

Append `ASK_BECOME_PASS=1` to a target if sudo requires a password. Initial
enrollment should use LAN SSH, not a Tailscale connection that may be
interrupted. Advanced Ansible options can be supplied through `ANSIBLE_ARGS`,
for example `ANSIBLE_ARGS='--limit example_host'` to deploy a single host.
Deployment targets reject `--check`/`-C` because check mode creates no
containers; use [`make check`](validation.md) for repository validation
instead. If `ANSIBLE_ARGS` was exported previously, clear it with
`unset ANSIBLE_ARGS`.
