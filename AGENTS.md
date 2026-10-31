# Repository Guidance

## Scope and safety

- This is reusable, public Ansible infrastructure. Every service is optional; never configure, provision, or require an unselected service.
- Never commit real credentials, identities, domains, hostnames, IPs, account/device IDs, or media/library details. Use unmistakably fake values in examples, fixtures, output, and comments.
- `ansible/inventories/example/` is the public template. The default inventory, `ansible/inventories/local/`, is ignored and may contain private infrastructure; do not copy values from it into tracked files.
- Keep vault passwords, SSH material, gathered facts, and generated/local artifacts out of Git. Secret-bearing Ansible tasks must use `no_log: true`; suppress diffs when a file or template contains a secret.
- Disabling a service or removing a Sonarr/Radarr instance only stops Ansible management. It does not stop containers, remove Caddy sites, or delete data.

## Commands

- `make configure`: create `.venv`, install pinned Python/Galaxy dependencies, copy the example inventory if absent, and initialize the encrypted vault.
- `make check`: offline validation in the required `syntax -> lint -> test` order. It uses the example inventory and does not contact deployment hosts.
- Focus tests with `.venv/bin/python -m pytest ansible/tests/test_<service>.py` or append `::<Class>::<test>` for one test. `ZNC_CONTAINER_TESTS=1 make test` additionally runs isolated Docker smoke tests.
- `make deploy` deploys all enabled services; `make deploy-<service>` targets one service plus `docker_runtime`. Use `ANSIBLE_ARGS='--limit host'` and `ASK_BECOME_PASS=1` as needed. Deployment deliberately rejects `--check`/`-C`; use `make check` instead.
- Tailnet policy is a separate controller-only workflow: `make policy-preview`, then `make policy-apply` only for an untouched default policy. Replacing any existing policy requires the explicit `make policy-replace` target and replaces the whole policy.

## Service and role structure

- A service has one role, one flat boolean `<service>_enabled`, one same-named Ansible tag, and its own Compose project under `/opt/selfhosted`. Do not restore the former nested `selfhosted_services` map or combine services into one role/project.
- Register a new service in `selfhosted_service_names` and the ordered role list in `ansible/playbooks/site.yml`; add boolean flags to the correct example group file, not `group_vars/all.yml`. `docker_runtime` remains `always`-tagged and conditional on the targeted service being selected.
- NAS selections belong in `group_vars/nas.yml`; bouncer selections belong in `group_vars/irc_bouncers.yml`. An unset flag means disabled, and flags must be YAML booleans rather than quoted strings.
- Pin runtime images as `<prefix>_image_repository`, quoted `<prefix>_image_tag`, and optional `<prefix>_image_digest`, constructed with the shared `container_image` filter. Caddy instead uses `caddy_version` for its builder/base tags. Keep example pins equal to defaults; `latest` without a digest is invalid.
- Extend the offline role tests whenever validation or rendered configuration changes.

## Networking and publication

- Web services join the external `selfhosted` bridge and publish themselves after container convergence through `include_role: caddy` with `tasks_from: site`. Supply `caddy_site_name`, hostname, and a Docker DNS upstream; never hand-write Caddy site blocks or `bind` directives in service roles.
- Every generated site must import Caddy's `selfhosted_private` snippet. Docker publishes Caddy HTTPS only on the discovered Tailscale IP and optional RFC1918 `caddy_lan_ip`; keep automatic HTTP redirects disabled so it never opens port 80.
- Keep role order `tailscale`, `caddy`, dependent web services, then Pi-hole. Pi-hole must run after all web services because it derives DNS records from Caddy's generated site files.
- Every application Compose project joins the external `selfhosted` bridge created by `docker_runtime`; use unique service names and Docker DNS for peers. Tailscale remains host-networked because it owns the host TUN interface.
- Media-handling services mount the existing `selfhosted_data_path` at the same container path and run with the shared UID/GID/umask. Ansible must never create, re-own, migrate, or place that data inside `/opt/selfhosted`.

## State and service-specific traps

- Treat application databases and UI-managed settings as user state. Roles may enforce documented environment/network/security settings, but must not seed or overwrite existing application state unless the service guide explicitly says so.
- Sonarr and Radarr remain multi-instance roles: one selection key, an `<app>_instances` list, and one project, data directory, Caddy site, Docker DNS name, API key, and download category per instance.
- qBittorrent rewrites its config. Seed it only when absent, then enforce only documented WebUI/auth keys while stopped: `[Preferences] WebUI\*` before 5.3 and `[WebUI]` from 5.3, removing duplicates from the other section. Only its PBKDF2 password hash reaches the host; preserve the 30-minute stop grace period.
- qui's `config.toml`, `qui.db`, login, instances, and proxy keys are UI-managed; never seed them because `sessionSecret` encrypts stored credentials. Its mount paths must continue to match qBittorrent's.
- Sonarr, Radarr, and Prowlarr API keys live only in root-readable `api.env` files. Keep authentication required on the shared network—Caddy connects through it too—and do not manage their `config.xml`, databases, logins, indexers, or clients.
- Plex port 32400 stays internal to the shared bridge. Internet Remote Access is opt-in and may bind only an explicit RFC1918 address, never wildcard or Tailscale. Do not set `PLEX_NO_AUTH_NETWORKS`; do not manage its claim, `Preferences.xml`, database, libraries, or users.
- Pi-hole requires Caddy and `caddy_lan_ip`; Docker publishes DNS only on `pihole_dns_address`, while its HTTP UI stays on the shared bridge behind Caddy. Enforce settings through `FTLCONF_*`, pass the UI password as a Compose secret, and do not add `no-new-privileges` because FTL gains file capabilities on exec.
- Tailscale enrollment is containerized and stateful. A fresh host gets a short-lived, one-use, non-ephemeral key generated on the controller for exactly `tag:nas` or `tag:irc`; only that key reaches the host and it is cleared after enrollment. Keep Tailscale SSH off and never run native `tailscaled` beside the container.
- Preserve each Tailscale service tag's self-ownership in `tagOwners`; a multi-tag OAuth client otherwise cannot mint a single-tag key. Never expose API response bodies, tokens, keys, or policy contents in diagnostics.
- ZNC keeps a read-only managed config plus a writable runtime copy because it locks and rewrites configuration. Preserve bounded buffers, savebuff state/passwords, TLS-only Tailscale binding, and secret redaction; never expose a web or public listener.

## Documentation

- Keep `README.md` as a short index and services table. Cross-service behavior belongs in `docs/*.md`; service variables, setup, exposure, data, and troubleshooting belong in `docs/services/<service>.md`.
- When adding a service, add its service guide and README table row in the same change, and update the relevant deployment, data-path, and validation guides. Update the matching guide whenever variables, targets, paths, exposure, or removal behavior change.
- Document a fact once and link to it with relative links; preserve heading anchors or update every incoming link.
