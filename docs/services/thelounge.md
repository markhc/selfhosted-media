# The Lounge

The Lounge is a private, authenticated web IRC client on the NAS, served
through [Caddy](caddy.md). It is not a public IRC relay.

## Enable

```yaml
caddy_enabled: true
thelounge_enabled: true
thelounge_hostname: lounge.example.com
```

The Lounge requires Caddy. Replace the placeholder hostname in your local
inventory and complete the [Caddy HTTPS setup](caddy.md#set-up-private-https)
before deploying with `make deploy-thelounge` or `make deploy`.

## Create an account

Create a Lounge account interactively **on the NAS**; the placeholder below is
a local app username, not an IRC nick or an infrastructure credential:

```bash
sudo docker compose --project-directory /opt/selfhosted/thelounge \
  --project-name selfhosted-thelounge exec --user 1000:1000 thelounge \
  thelounge add example-user
```

From a Tailscale-connected administrator device, visit your HTTPS hostname. For
LAN clients without Tailscale, see [Caddy LAN access](caddy.md#optional-lan-access).

## Connect through ZNC

To keep upstream IRC connections alive while the NAS is offline, connect The
Lounge to an optional [ZNC bouncer](znc.md) instead of directly to IRC networks.
See [Connect The Lounge](znc.md#connect-the-lounge) for server settings and
[listener certificates](znc.md#listener-certificates) for trusting a
self-signed bouncer certificate.

## Network exposure

The Lounge runs in private mode with `reverseProxy: true` on the shared bridge
as `thelounge:9000`, without Docker port publishing. Caddy is the only listener
reachable from the tailnet or LAN.

## Data

Lounge accounts, history, uploads, and the managed `config.js` are stored under
`/opt/selfhosted/thelounge/data`. Back them up securely and do not delete them
on redeployment. Disabling The Lounge stops managing it but leaves its
container and Caddy site running; see
[Service selection and removal](../operations.md#service-selection-and-removal). See [Operations](../operations.md) for general guidance.
