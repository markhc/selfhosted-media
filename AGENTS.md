# Repository Guidance

## Project intent

- This is a reusable, public infrastructure-as-code project for self-hosted private-media services, primarily using Ansible and Terraform.
- Treat every service (including Tailscale, Plex, Jellyfin, and qBittorrent) as optional. Changes must preserve explicit service selection and must not provision or configure an unselected service.
- Keep user- and environment-specific values in inputs, inventories, or local configuration rather than embedding them in reusable modules, roles, or playbooks.

## Public-repository safety

- Never commit credentials, API/auth keys, private keys, passwords, cookies, real domains, email addresses, usernames, hostnames, public IPs, account/device IDs, or identifying media/library data. Examples must use unmistakably fake placeholders.
- Do not commit Terraform state, saved plans, `.terraform/`, Ansible vault passwords, SSH material, gathered facts, or inventories/variable files containing real infrastructure details. Add generated and local-only artifacts to `.gitignore` when their tooling is introduced.
- Do not put real secrets in example files, defaults, tests, fixtures, command output, comments, or documentation. Reference environment variables or a documented external secret source instead.

## Ansible workflow

- Use `make configure` for controller dependencies, local inventory, and encrypted vault setup. Use `make deploy` for the selected stack and the focused deployment/policy targets in the Makefile when needed.
- Validate with `make check`.
- `ansible/inventories/example/` is the public template; operators copy it to the ignored `ansible/inventories/local/`, which is the default inventory in `ansible.cfg`.
- Prefer Docker for all services. `docker_runtime` installs the shared host runtime before `nas_tailscale`, then `web_stack`; tags are `tailscale` and `web_stack` (the latter assumes an enrolled NAS).
- Tailscale runs with host networking, kernel TUN, persistent state, and `TS_AUTH_ONCE=true`; never run native `tailscaled` alongside it. For a fresh NAS, the controller uses the vaulted OAuth credential to generate a 10-minute, one-off, non-ephemeral `tag:nas` auth key. Only the generated key reaches the NAS and it is cleared after enrollment; preserve state for keyless restarts and keep Tailscale SSH disabled.
- Caddy also uses host networking: bind HTTPS only to the discovered Tailscale IP and the optional, explicitly configured RFC1918 LAN IPv4 in `web_stack_lan_ip`; disable automatic HTTP redirects (otherwise Caddy can open a wildcard port 80 listener). The Lounge must stay on loopback with private mode and `reverseProxy: true`.
- Cloudflare DNS-01 requires the pinned plugin build and the vaulted `web_stack_cloudflare_api_token`; keep the token out of templates/build contexts and preserve `caddy.dockerignore`. A custom hostname needs a separate DNS-only A record; Caddy does not create it.
- Service flags skip management, not uninstall. With Caddy enabled, removing The Lounge from Compose removes its container but preserves data; disabling the whole web project leaves an existing deployment running.
- `ansible/playbooks/tailnet.yml` is controller-only and separate from `site.yml`: preview by default, write only with `tailnet_policy_apply=true`, and non-default replacement only with `tailnet_policy_replace_existing=true`. Preserve the default-policy/ETag guards, failed-test detection even on HTTP 200, and `no_log` on all policy/API data. The vaulted `tailscale_oauth_client_id`/`tailscale_oauth_client_secret` are shared by policy and enrollment controller tasks but must never be copied to the NAS.
