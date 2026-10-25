# Tailscale

Tailscale runs as a container with host networking, kernel TUN, and persistent
state on every host that selects it. No Tailscale SSH server is enabled. Tailnet
creation, the controller OAuth credential, and the access policy are covered in
[Tailnet setup and policy](../tailnet.md).

## Enable

Select the service in the host's group variables and give each host a MagicDNS
machine name:

```yaml
tailscale_enabled: true
tailscale_machine_name: media-nas
```

Hosts other than the NAS also set their enrollment tag, for example
`nas_tailscale_auth_key_tags: ["tag:irc"]` for a [ZNC bouncer](znc.md). The
`nas_tailscale` role enrolls every selected host despite its historical name.

## Deploy

```bash
make deploy-tailscale
```

Initial enrollment should use LAN SSH, not a Tailscale connection that may be
interrupted.

## Enrollment

For a fresh host, Ansible uses the controller OAuth credential to generate a
10-minute, one-off, non-ephemeral, pre-approved auth key restricted to the
host's tag (`tag:nas` by default). Only this generated key reaches the host.
After enrollment, Ansible clears it from the host environment and recreates the
container without it, verifying that saved state works. Ordinary reruns and
restarts make no API request for an auth key while valid state remains in
`/opt/selfhosted/tailscale/state`. Do not delete state just to rotate the OAuth
credential.

If you deployed an earlier auth-key or device-side OAuth configuration, preserve
the existing state and run the normal deployment. Ansible will not mint a new
key for an already-enrolled host. After verifying connectivity, revoke obsolete
credentials.

See Tailscale's [auth-key documentation](https://tailscale.com/docs/features/access-control/auth-keys).
If enrollment fails while the OAuth client has multiple tags, see
[Troubleshooting single-tag enrollment](../tailnet.md#troubleshooting-single-tag-enrollment).

## Check status

To confirm which tailnet accepted the host, run
`make tailscale-status ASK_BECOME_PASS=1`. It reports the machine name, active
tailnet, tags, and Tailscale addresses from the container. If the node is online
there but absent from the admin console, switch the console to the reported
tailnet; OAuth credentials always enroll into the tailnet that owns them.

To print the host's Tailscale IPv4 address directly on the host:

```bash
sudo docker compose --project-directory /opt/selfhosted/tailscale \
  --project-name selfhosted-tailscale exec -T tailscale tailscale ip -4
```

## Native tailscaled and migration

Do not run native `tailscaled` alongside its container. The playbook refuses an
active or boot-enabled native daemon and does not silently migrate existing
state. A fresh state directory registers a new device; plan migration separately
if already deployed.

## Data

Persistent state is under `/opt/selfhosted/tailscale/state`. Back it up
securely and do not delete it on redeployment. The auth key is cleared from the
host after enrollment. See [Operations](../operations.md) for general backup
and credential guidance.
