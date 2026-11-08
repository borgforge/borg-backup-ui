# Apprise 2.2.0 review (#721)

Reviewed on 2026-11-08. Update the bundled library from 2.1.0 to 2.2.0 within
its existing base-package scope. No profile/secret migration or notification
adapter change is required. Optional `all-plugins` dependencies are not added.

## Upstream and compatibility

- [Release notes](https://github.com/caronc/apprise/releases/tag/v2.2.0)
  describe twelve new services and provider fixes, including Telegram, XML,
  Zulip and Bark. This is a library update, not an application architecture change.
- [PyPI metadata](https://pypi.org/pypi/apprise/2.2.0/json) retains Python
  `>=3.9` and the same base dependency requirements as 2.1.0. The plugin's
  supported external Python range remains 3.10-3.13; its private runtime remains
  3.13.18. This does not extend supported Unraid versions.
- The reviewed `apprise-2.2.0-py3-none-any.whl` SHA256 is
  `deac7647c02463f5398f3f5dbba965031a1507adf1b4348ccf5e53e8f0528f51`.
  Hash-checked installation resolves with the existing transitive pins, which
  are retained. The BSD-2-Clause license text is unchanged.
- Isolated provider discovery exposes 170 providers, up from 158. All previous
  URL schemes remain available. Burst SMS is renamed to Kudosity in metadata;
  `burstsms://` remains supported and `kudosity://` is an additional alias.
  The committed inventory and bilingual user documentation reflect the bundle,
  rather than upstream's broader count including optional/platform providers.

## Security assessment

[GHSA-cfp4-m43r-v9q4](https://github.com/caronc/apprise/security/advisories/GHSA-cfp4-m43r-v9q4)
identifies a denial of service in 2.1.0 when Apprise loads YAML configuration
with cyclic or exponentially expanding aliases; 2.2.0 is the patched version.

The plugin adapter passes strings to `Apprise.add()` to construct notification
services. It does not construct `AppriseConfig` objects or load Apprise YAML
configuration sources. Code inspection and an offline parser spy support the
assessment that the documented YAML-import path is not exposed by the current
profile API. Embedded notification URLs may still be recognized in input text;
that does not cause YAML parsing. This assessment is specific to the current
adapter, not a claim that the old library is patched or universally safe.

The update includes the upstream fix. Build-time contract checks now verify
rejection of a cyclic alias and a bounded synthetic expansion over the upstream
limit, while retaining normal YAML parsing. They also verify that adapter URL
validation never invokes the YAML parser. PyPI's version metadata contained no
advisory entries at review time; that absence does not override the published
GitHub advisory. GitHub dependency audits remain mandatory and unsuppressed.

## Validation and release boundary

The exact hash-installed vendor tree passed the offline runtime contract on
Python 3.12 and the private Python 3.13.18: all 170 provider metadata entries and
module imports, ntfy token/basic authentication, HTTP/SMTP success and rejection,
OAuth/TLS, sanitized failures, deadlines, result cleanup, YAML hardening and
legacy Burst SMS URL validation. All provider configuration forms were exercised
in German and English using the live metadata. No real notifications were sent.

Focused profile, adapter, packaging, notification and documentation tests plus
PR CI cover the integration. The hosted build rechecks the vendor tree under
its build interpreter and the packaged private interpreter. The test-channel
candidate and its verified provenance are recorded in the PR. Maintainer tests
on Unraid with configured providers and explicit stable approval are still
required; this review does not authorize stable promotion.
