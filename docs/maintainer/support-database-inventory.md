# Database profile inventory in support bundles (#703)

Support ZIPs include `config/database-profiles.sanitized.json`. This additive
member describes **current configuration at export time**, not the profile
configuration used for a historical run. Existing jobs, statuses and logs keep
their existing paths and formats. It is diagnostic data, not a restorable
configuration export or database dump.

## Export schema v1

```json
{
  "schema_version": 1,
  "scope": "current_configuration_at_export",
  "captured_at": "2026-11-05T10:00:00+00:00",
  "status": "available",
  "profiles": [
    {
      "id": "db-0123456789ab",
      "name": "App database",
      "engine": "postgresql",
      "engine_status": "supported",
      "enabled": true,
      "container": "postgres",
      "databases": ["app"],
      "include_globals": true,
      "staging_mount": "/mnt/cache",
      "staging_dir": "/mnt/cache/db-dumps",
      "port": 5432,
      "timeout_seconds": 600,
      "min_free_mib": 2048,
      "retention": "after_archive"
    }
  ]
}
```

The export schema version is independent of the internal inventory schema.
`captured_at` is an offset-aware UTC capture timestamp, not a profile update or
backup-run time. The source is the canonical `config/database-profiles.json`
under the configured data root. Reading does not create/repair files or acquire
write locks; the application's inventory writer uses atomic replacement.

| Status | Meaning |
| --- | --- |
| `available` | Entire inventory validated; `profiles: []` means a known empty inventory. |
| `missing` | Source inventory was absent. Its contents are unknown. |
| `unreadable` | Read/access failed, or the source is a symlink/non-regular file. |
| `invalid` | Invalid UTF-8/JSON, malformed envelope/profile or duplicate profile IDs. No partial rows are exported. |
| `unsupported_schema` | Source has an integer schema version other than the supported v1. |
| `too_large` | Source exceeds 2 MiB. No truncated or partial inventory is exported. |

All non-available statuses have `profiles: []`; they never mean zero configured
profiles. The ZIP remains available, and `support/sanitizing-report.json`
records the same fixed reason against `config/database-profiles.json`. Error
messages and raw invalid source content are not copied into this member.
Job health reports inaccessible/corrupt database inventories as configuration
errors instead of aborting the support export.

Profiles are sorted by stable `id`, including disabled profiles. The allowlist
is exactly the example's profile fields. `engine_status` is `supported` for
`mariadb`, `mysql`, `postgresql`, and `retired` for preserved `mongodb`, `redis`,
`sqlite` metadata. It indicates product support, not a connectivity or dump
check. Retired metadata can omit optional fields; consumers must show unknown
rather than inventing values. Active profiles use the existing profile
validator's normalized values/defaults. Retention is `keep` or `after_archive`.

Passwords, authentication mode, credential references/file paths, database and
execution users, arbitrary extensions and engine-specific retired connection
fields are excluded. No credential file or dump is opened. General support
string masking is then applied to the selected fields (for example email,
HTTP/SSH URLs and recognized password/token assignments in free text).
Names, container names, database names and staging paths remain diagnostically
useful and can identify an environment: sanitized does not mean anonymous.

## Consumer/Toolbox handoff

1. Detect the member by path, then validate export `schema_version`, `scope`
   and `status`. Do not gate solely on plugin version. A missing member in older
   ZIPs or an unknown future schema is unavailable inventory, not a backup error.
2. For `available`, index profiles by `id`. Join job `database_profile_ids` and
   database run/manifest profile references by exact ID, never display name,
   list order or engine. An unresolved ID may refer to a deleted profile.
3. Label the resulting panel **Current profile configuration at export time**
   with `captured_at`. Keep historical run/manifest facts and current settings
   separate; do not fill historical gaps from current settings as proven facts.
4. Preserve masked values as masked and missing fields as unknown. Render all
   strings as text, never HTML. Unknown/missing/retired inventory must not change
   a run result, mark a dump failed or override explicit historical evidence.
5. Dump completion, archive readability and database import/restore validation
   are separate findings. This inventory supplies no evidence for any of them.
   Keep `database restore not tested` unless an explicit restore result exists.
6. Keep manual supplemental files separate from the original ZIP and retain
   their provenance. A conflicting supplemental profile must not silently
   overwrite original or historical evidence.

Consumer tests should cover available/empty inventory, two profiles joined to
one job, disabled/retired entries, masked/absent fields, unresolved/deleted IDs,
every unavailable status, older ZIPs without the member, unknown future schemas,
and conflicting current versus historical or supplemental data. Toolbox code
is maintained separately and is not changed by #703.
