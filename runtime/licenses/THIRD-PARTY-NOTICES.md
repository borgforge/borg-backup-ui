# Third-party license notices

Borg Backup UI bundles selected third-party components so the Unraid plugin can
run without installing Python packages at runtime.

## BorgBackup runtime

| Component | Version | License | Notice |
| --- | --- | --- | --- |
| BorgBackup | bundled runtime | BSD-3-Clause | See `runtime/licenses/borg/LICENSE`. |

## Apprise notification runtime

The Apprise runtime is bundled as a verified vendor archive generated from
`plugin/apprise-requirements.lock`. The archive is extracted on the Unraid
system only when the bundled version or SHA256 changes.

| Component | Version | License | Notice |
| --- | --- | --- | --- |
| apprise | 1.12.0 | BSD-2-Clause | See `runtime/licenses/apprise/LICENSE`. |
| certifi | 2026.6.17 | MPL-2.0 | Python package dependency of Apprise. |
| charset-normalizer | 3.4.9 | MIT | Python package dependency of Apprise. |
| click | 8.4.2 | BSD-3-Clause | Python package dependency of Apprise. |
| idna | 3.18 | BSD-3-Clause | Python package dependency of Apprise. |
| Markdown | 3.10.2 | BSD-3-Clause | Python package dependency of Apprise. |
| oauthlib | 3.3.1 | BSD-3-Clause | Python package dependency of Apprise. |
| PyYAML | 6.0.3 | MIT | Python package dependency of Apprise. |
| requests | 2.34.2 | Apache-2.0 | Python package dependency of Apprise. |
| requests-oauthlib | 2.0.0 | ISC | Python package dependency of Apprise. |
| urllib3 | 2.7.0 | MIT | Python package dependency of Apprise. |

The package versions above must stay aligned with
`plugin/apprise-requirements.lock`.
