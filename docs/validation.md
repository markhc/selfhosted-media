# Validation

Validation uses the non-routable example inventory and does not contact a NAS:

```bash
make check
```

The offline tests check host selection, secret redaction (including `--diff`),
input validation, and generated configuration.

## Container smoke tests

An additional local Docker smoke test starts ZNC and a fake TLS IRC server in an
isolated network namespace, checks certificate generation/renewal, verified
TLS, SASL, and missed-message playback across disconnects and restarts. ACME
tests use a local fake CA to check atomic installation, key rotation,
hostname/expiry/trust failures, renewal restart retries, and secret redaction.
Opt-in container checks also verify the public-certificate configuration and
non-root Certbot plugin runtime without contacting a CA or DNS provider. No host
ports are exposed:

```bash
ZNC_CONTAINER_TESTS=1 make test
```
