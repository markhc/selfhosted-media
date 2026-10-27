# cAdvisor

[cAdvisor](https://github.com/google/cadvisor) exports per-container CPU,
memory, network, and filesystem metrics. It is optional; host monitoring does
not require it.

## Enable

Set `cadvisor_enabled: true` together with Prometheus and Grafana. Defaults are
`127.20.0.4:8080` and a 30-second housekeeping interval. Override them with
`cadvisor_address`, `cadvisor_port`, and `cadvisor_housekeeping_interval`.
Image variables use the `cadvisor` prefix.

## Deploy

Run `make deploy` so Prometheus and Grafana learn the selected component.

## Network exposure

The endpoint is loopback-only and is not published through Caddy.

## Data and host access

cAdvisor is stateless, but it requires privileged access plus read-only mounts
of the host root, Docker state, sysfs, runtime state, and disk devices. This is
why it is disabled by default. Do not enable it on a host where this trust is
unacceptable.

## Troubleshooting

Check the Prometheus `cadvisor` target. Some storage drivers or restricted
kernels expose fewer metrics; cAdvisor should still provide CPU and memory
series for running containers. The role overrides the image's localhost health
check because cAdvisor listens only on its dedicated loopback address.
