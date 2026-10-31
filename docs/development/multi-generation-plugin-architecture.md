# One application, two Unraid plugin generations (#671)

Status: architecture and build-target preparation, 2026-10-31. The only
implemented package is the existing legacy Unraid plugin. This document neither
claims Unraid 8 compatibility nor authorizes a data migration or publication.
Related investigations: #549 (Unraid 8) and #548 (private Python runtime).

## Decision and evidence

Keep `borg_backup_ui.py`, `api/`, `runtime/`, `ui/` and `plugin/`. Do not introduce
a second application, fork the UI, move everything into `src/`, or replace the
HTTP server/framework. The existing architecture is a useful basis, but it is
not already a platform-independent core: host paths, command execution, lifecycle
and privilege assumptions cross several modules.

Official Unraid announcements describe a Fedora/uCore base and a new SDK. The
October Q&A describes documentation/tooling still being prepared and an alpha
programme. Neither source supplies a complete implementable packaging,
permission, lifecycle or host API contract. Consequently this change does not
invent SDK APIs, service manifests, permission names, package extensions or
Unraid 8 feed addresses. See [the announcement](https://unraid.net/blog/unraid-8-announced)
and [the Q&A](https://unraid.net/blog/unraid-8-qa). Recheck these primary sources
and issue #549 when official SDK documentation becomes available.

## Current coupling and reusable components

| Area | Actual source and dependency | Reuse / required boundary |
| --- | --- | --- |
| Retention, archive selection, progress and reports | `runtime/lib/retention_policy.py`, `api/restore_selection.py`, `api/reports_api.py`, shared parsing/validation | Keep domain decisions, formats and tests; pass storage/execution context explicitly. |
| Borg execution and repository operations | `runtime/lib/borg_runner.py`, `api/borg_environment.py`, `api/borg_ssh.py`, bundled Linux x86_64 Borg | Reuse orchestration and argument handling; validate executable ABI, paths, SSH/key access and process isolation per target. This is not an OS-independent engine binary. |
| Backup orchestration | `runtime/lib/backup_job.py` | Keep one job state machine and recovery logic. Extract only host probes/actions when needed. The current parity check calls `mdcmd`; absence currently skips that guard, which must not become the future adapter's implicit safety policy. |
| API and browser UI | `borg_backup_ui.py`, `api/`, `ui/` | Reuse routes, data models, translation and frontend. Host-facing handlers need capability-aware responses; authentication/proxy embedding must be checked against the SDK. Not every API module is portable today. |
| Docker and VMs | `runtime/lib/docker_manager.py`, `runtime/lib/vm_manager.py` | Existing manager classes already concentrate CLI, `virsh` and guest-agent behavior. Keep caller semantics; inject a documented host implementation only when necessary. Do not assume socket/root/libvirt access on Unraid 8. |
| Paths, mounts, array readiness | `api/config_api.py`, `api/job_source_paths.py` | Configuration provides useful seams, but `/mnt/user`, `/boot`, `/proc/mounts`, `mdcmd` and mount-prefix policies remain embedded. Resolve semantic paths and storage readiness through the platform boundary. Never create missing mount roots as ordinary directories. |
| Secrets and configuration transfer | `api/config_api.py`, `api/smb_profiles_api.py`, `api/settings_transfer_api.py`, `api/borg_key_store.py` | Reuse validation/export formats. Some secret roots still use `/boot/config/borg-backup/secrets`; credential permissions and export/re-key policy need explicit target handling. |
| Scheduling | `api/schedule_api.py`, `api/report_mail_api.py` | Reuse schedule definitions and validation; host crontab application is platform integration. A new backend must have exactly one active scheduler, not a second set of jobs. |
| Notifications | `runtime/lib/notifications.py`, Apprise/mail code | Reuse notification events, levels and provider settings. `/usr/local/emhttp/webGui/scripts/notify` is a legacy transport. SDK host notifications require a separate implementation. |
| Resource enforcement | `api/resource_metrics.py`, `api/restore_test_resources.py` | `/proc`, process ownership and writable cgroup v2 controllers are Linux capabilities, not guaranteed plugin permissions. Preserve fail-closed restore-test limits; do not silently run an unbounded worker. |
| Installation and lifecycle | `.plg`, `plugin/rc.borg_backup_ui`, `.page`, `widget-status.php` | Legacy-only packaging and webGui/rc hooks. Unraid 8 needs official lifecycle, permission and embedding definitions; shared code must not write legacy host paths there. |
| Data migrations | `api/migrations/registry.py`, `api/migrations/audit.py`, `api/migration_api.py` | Reuse the existing audited, fail-closed runner and UI status. A cross-generation transfer is a future explicitly authorized migration, not implemented here. |

Coupling is low in pure validation/parsing, medium in the Borg/job orchestration,
and high in lifecycle, paths, scheduling and host control. No numeric portability
percentage is inferred from file counts. Unchanged domain/UI modules can remain
shared; their unchanged compatibility still needs execution tests on the SDK.

## Boundary contracts

The following are application-side responsibilities, not claimed SDK methods.
Start from the existing configuration objects and manager interfaces; avoid an
all-purpose adapter that duplicates every application method.

| Contract | Inputs / result | Error and side-effect contract |
| --- | --- | --- |
| Host identity and capabilities | Parsed OS version, plugin generation; explicit capability availability | Unknown version/permission is an explicit unsupported result, never guessed success. Detection is read-only. |
| Paths and storage readiness | Semantic roles: config, secrets, jobs, history, logs, cache, runtime; resolved paths and mount readiness | No implicit config overwrite or mount creation. Unavailable storage prevents dependent writes. |
| Managed containers and VMs | Existing managers' list/stop/start and recovery information | Preserve timeouts, start ordering and saved runtime recovery state; permission denial is an error, not an empty successful list. |
| Scheduler application | Validated schedules; saved/applied result and diagnostics | Changes only plugin-owned entries; failed application remains visible. Ownership must prevent duplicate execution across generations. |
| Resource/process supervision | Requested limits and executable context; supervised process/result | Enforce requested isolation or fail closed. Cancellation must stop owned children and retain recovery information. |
| Notifications | Common event/level/message; transport outcome | Host transport failure does not expose credentials; optional transport absence is reported explicitly. |
| Lifecycle and web integration | Shared application launch configuration; host registration/health outcome | Implemented by the package integration; install/uninstall never treats external user data as disposable payload. |

Do not add empty runtime implementations or fallback paths today. The low-risk
executable abstraction added now is `plugin/build_targets.py`: platform/channel
identity, unchanged legacy feed definitions, version validation, and an explicit
generation-selection validator. `require_host_generation()` rejects unknown or
cross-generation input; it is a tested planning helper, **not wired into the
current legacy installer** and not a minimum-version/SDK compatibility claim.
CA currently declares minimum Unraid 6.12.5. Runtime adapter extraction should be
small, separately reviewed changes once the required official contracts exist.

## Targets and channels

| Platform | Channel | Current behavior | Future ownership |
| --- | --- | --- | --- |
| `unraid-legacy` | `testing` | Local/Actions candidate preview; existing `test-channel` feed identity | Existing legacy `.plg` and `.txz` publisher, only after authorization. |
| `unraid-legacy` | `stable` | Preview promotes exact tested bytes; existing `main` identity | Existing separate release PR and explicit test approval. |
| `unraid-8` | `testing` | Explicit error before packaging or output; no fallback | Separate SDK package identity and feed, after SDK/system validation. |
| `unraid-8` | `stable` | Explicit error before packaging or output; no fallback | Separate protected approval and SDK release metadata. |

Platform and channel are separate parameters, not encoded by swapping the
application branch. Dispatch selects a target; there is no automatic four-way
release matrix per push. Common quality/tests execute once per workflow. Later,
use a selected-platform packaging matrix only when more than one implemented
target was requested. A stable promotion consumes a platform-specific tested
package and does not run the core build again.

Legacy plugin name, `.plg` name, timestamp version schema and both feed paths
remain unchanged. New provenance records `platform=unraid-legacy` and
`architecture=x86_64`; validation accepts old legacy provenance without the
additive fields. Future Unraid 8 provenance must explicitly identify its target;
it must never use legacy defaults. Generation-specific plugin IDs/feeds and
install-time capability checks will prevent cross-generation updates. Today,
no Unraid 8 package/feed exists to be accidentally offered to legacy users.

## Shared source, independent releases

Use the existing deployable source digest and source commit as the common core
identity. Keep legacy `YYYY.MM.DD.HHMM` package versions. An eventual Unraid 8
package can carry the same core commit/digest plus its own supported package
version and packaging revision. Do not invent its native version format before
the SDK defines it. Platform releases need not occur simultaneously.

Candidate metadata separates `platform`, `channel`, `version`, source commit,
source digest, release-note digest and package SHA256. Channel is outside the
package: this permits testing-to-stable promotion without modifying package
bytes. Separate proposed tag namespaces such as `unraid-legacy/<version>` and
`unraid-8/<version>` avoid collisions if GitHub Releases are later activated.
No tags/releases are created now; their names are proposals, not update feeds.
Asset names must carry platform identity in any future GitHub Release workflow.

Python source and the static UI do not require a compiled application build.
Export a normalized shared source bundle once, run common tests once, then add
target metadata and integration files. Wheel caches are keyed by OS, CPU,
Python ABI and lock hash: never reuse a legacy installed vendor directory or
native wheel blindly on a different runtime. Common pure source/manual assets
may be reused by content digest. Borg/Python binaries, permissions and packaging
remain target-specific verification inputs. Full payload caching is deferred:
an incorrect source/provenance key is more harmful than the current small
documentation-copy cost.

## Future migration and recovery concept

No migration or production-data transfer is implemented by #671. Before a
future implementation, inventory configured data roots and all of:

- Job IDs/configurations, repository profiles and locations, schedules/groups,
  retention and restore-test settings.
- Secrets/passphrase files, SSH/Borg key/security state, notification credentials
  and access permissions; do not assume encrypted keys are portable unchanged.
- General settings, reports/history, runtime recovery state and active jobs.
- Cache/log locations and path references in jobs/hooks, including paths no
  longer accessible under the new permission model.

The migration plan must be an explicit user-reviewed transfer with a unique
ID. Detect legacy state read-only, reject concurrent active jobs/schedulers,
validate SDK permissions and path mappings, and create a verified snapshot of
affected data before writing. Reuse export/validation code where its existing
coverage matches this inventory; current settings export is not asserted to
cover all history or runtime state.

Use the existing runner contract: `detect(config)` returns a mapping containing
boolean `required`; `apply(config)` returns a supported status. Record
`pending`, `applied`, `skipped`, `failed`, `blocked` or `not_applicable`, timestamp,
affected objects/files, actions and masked errors in the audit log. The first
failure blocks subsequent migrations, normal scheduling and write APIs. Re-run
must be idempotent; partial writes require a documented repair strategy.
Expose audit/status through the existing migration UI.

Preserve originals until verified import and explicit cutover. Activate only
one scheduler and one service owner; validate a synthetic backup/restore before
enabling scheduled jobs. Snapshot recovery is controlled data restoration, not
an automatic OS or plugin downgrade. Any return to legacy must verify data
schema compatibility and disable the new scheduler first. Never delete Borg
repositories, discard unknown configuration, or overwrite credentials silently.

Required migration tests: source inventory, successful transfer, second-run
idempotency, inaccessible secrets/storage, malformed results, interrupted writes,
failure blocking later migrations, no duplicate schedules, and audited recovery.
Real OS upgrade/downgrade behavior requires disposable Unraid systems.

## Delivery sequence and validation

**Now (#671):** preserve the single codebase and runtime behavior; document the
coupling; optimize the legacy builder; add channel/target/provenance validation,
read-only CI and non-publishing previews. Tests cover existing legacy metadata,
checksums, permissions, deterministic packaging, and blocked Unraid 8 selection.

**After official SDK:** verify documented package format, service lifecycle,
permissions, filesystem, host APIs, auth/web embedding and binary/runtime ABI.
Implement only required adapters and SDK packaging. Run the common suite plus
SDK/package/permissions/installation/update/removal tests on a supported image.
Add migration tests only with explicit migration authorization. Activate the
Unraid 8 testing feed before considering stable; require separate user testing
and approval for that generation.

Shared regression tests cover API/UI behavior and synthetic Borg operations.
Legacy checks cover PLG/payload/channel metadata and installer functions locally;
real install/update/reboot/removal on 6.12.5 and supported 7.x remains a manual
gate. No Unraid 8 test is represented as passing or silently skipped: requesting
the target is a visible failure.

The main risks are accidental shared host state, permission differences,
runtime/native ABI mismatch, duplicate schedulers, incompatible data changes
and feed crossover. Separate packaging/identities, a shared domain model,
explicit capability failures and audited migration are the controls. This
approach avoids duplicate feature development without assuming identical host
integration or promising byte-identical packages across OS generations.
