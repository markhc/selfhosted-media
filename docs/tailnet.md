# Tailnet Setup and Policy

Tailscale creates a tailnet when you sign up. This repository configures
machines inside that existing tailnet; it cannot create the identity-provider
account itself. Host-side enrollment is covered in the
[Tailscale service guide](services/tailscale.md).

## Prerequisites

1. Create or select a tailnet in the Tailscale admin console.
2. Review and apply [`tailscale/policy.hujson`](../tailscale/policy.hujson) once
   in the admin console to define `tag:nas` (and `tag:irc` for optional ZNC
   hosts). Tailscale requires the tag to exist before it can restrict an OAuth
   client's auth-key permission to that tag.
3. Create the single [controller OAuth credential](#create-the-controller-oauth-credential)
   and store it in the encrypted local Ansible Vault created by
   `make configure`.

The supplied policy permits tailnet administrators to access the NAS on HTTPS
port 443 only (every Caddy-served web service), and permits the NAS and administrators to reach `tag:irc` on
TCP 6697 for ZNC. It grants no access from the bouncer back into the NAS and
does not grant SSH. To let other tailnet members, such as Audiobookshelf
listeners, reach the web services, add their users or groups as `src` in a
private copy of the `tag:nas` `tcp:443` grant (see
[Use a private policy file](#use-a-private-policy-file)); each service still
requires its own login. Review before replacing an existing policy: unrelated
grants will be removed.

## Create the controller OAuth credential

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

## Automate the tailnet policy

This is a separate, explicit controller-only workflow. It never connects to the
NAS, uses sudo, installs Docker, or runs as part of `site.yml`. Complete the
Python dependency setup in [Getting started](getting-started.md#configure-the-controller)
first; no NAS inventory or Galaxy collection is required for the policy
playbook.

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

### Use a private policy file

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
workflow. Host enrollment keys are generated automatically only when persistent
Tailscale state is absent.

## Troubleshooting single-tag enrollment

If enrollment fails at **Stop if a valid enrollment key was not created** while
the OAuth client already has both tags, check the live policy contains:

```json
"tagOwners": {
  "tag:nas": ["autogroup:admin", "tag:nas"],
  "tag:irc": ["autogroup:admin", "tag:irc"]
}
```

Review with `make policy-preview`, then explicitly apply the complete reviewed
policy using the [policy workflow](#preview-then-explicitly-apply) (an already
customized policy requires `make policy-replace`). Do not work around this by
tagging both hosts with both service identities: that would mix their access
privileges. The enrollment error reports only the HTTP status and safe
guidance, never tokens or response bodies.
