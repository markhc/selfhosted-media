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
| `group_vars/all.yml` | Shared settings |
| `group_vars/nas.yml` | NAS service selections |
| `group_vars/irc_bouncers.yml` | Optional bouncer host service selections |
| `vault.yml` | Encrypted credentials; edit with `make vault-edit` |

Existing local inventories with NAS service selections in `all.yml` continue to
work; move those selections to `nas.yml` before adding other hosts so they do
not inherit NAS-specific settings. `make configure` never overwrites an existing
local inventory, so copy new example group files manually when upgrading. Use
`make vault-edit` whenever a token changes. The entire local inventory is
ignored by Git because it can identify private infrastructure.

When upgrading an existing vault, replace `nas_tailscale_auth_key` and the old
`tailnet_policy_client_*` values with the single `tailscale_oauth_client_id` and
`tailscale_oauth_client_secret` pair.

## Select services

Each service has its own `selfhosted_services.<name>.enabled` setting in the
inventory, for example:

```yaml
selfhosted_services:
  tailscale:
    enabled: true
  caddy:
    enabled: true
  thelounge:
    enabled: true
  znc:
    enabled: false
```

Set a service to `false` to skip it without changing the playbook. Review each
selected service's guide for its prerequisites and dependencies before
deploying; for example, the web services require the
[Caddy DNS steps](services/caddy.md#set-up-private-https). Disabling a service
skips management rather than uninstalling it; see
[Operations](operations.md#service-selection-and-removal).

## Deploy

Deploy all services enabled in the local inventory:

```bash
make deploy
```

Focused targets deploy a subset:

| Target | Deploys |
| --- | --- |
| `make deploy-tailscale` | Docker and Tailscale only |
| `make deploy-web` | Docker, Caddy, and The Lounge only (no Tailscale auth key is needed) |
| `make deploy-znc` | Docker and selected ZNC instances only |

Append `ASK_BECOME_PASS=1` to a target if sudo requires a password. Initial
enrollment should use LAN SSH, not a Tailscale connection that may be
interrupted. Advanced Ansible options can be supplied through `ANSIBLE_ARGS`,
for example `ANSIBLE_ARGS='--limit example_host'` to deploy a single host.
Deployment targets reject `--check`/`-C` because check mode creates no
containers; use [`make check`](validation.md) for repository validation
instead. If `ANSIBLE_ARGS` was exported previously, clear it with
`unset ANSIBLE_ARGS`.
