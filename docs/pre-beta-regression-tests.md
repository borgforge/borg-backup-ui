# Pre-Beta Regression Tests

This document describes the local regression coverage used before a beta-ready
build. The focus is on security-critical and failure-prone behavior that can be
tested without a real Unraid installation, Docker daemon, VM service, or Borg
repository.

## Test Command

```bash
pytest -q
```

## Coverage Map

| Area | Automated coverage | Test files | Manual / integration follow-up |
| --- | --- | --- | --- |
| Schedule and cron safety | Job-key validation, unknown-job rejection, shell-safe cron wrapper generation, crontab read/install errors | `tests/test_schedule_security.py` | Verify one saved schedule on Unraid creates the expected crontab entry |
| Restore target safety | Allowed-root validation, symlink resolution, exclusive staging directory creation, overwrite protection for symlink destinations outside the target | `tests/test_restore_path_safety.py` | Run one real Browse & Restore dry-run and one small real restore on Unraid |
| Resource locks and concurrency | Shared resource locks block concurrent access, release correctly, and recover corrupt stale lock files | `tests/test_resource_locks.py` | Start two UI/API actions against the same repository on Unraid and confirm one is blocked |
| Borg subprocess handling | Restore download timeout defaults/minimum and bounded stderr collection | `tests/test_restore_download_safety.py` | Confirm a real large download still streams and can be cancelled |
| Docker/VM runtime recovery | Runtime recovery state creation, stale warning exposure, manual acknowledgement, selected Docker stop/start behavior | `tests/test_runtime_recovery.py`, `tests/test_docker_manager_runtime.py` | On Unraid, run one Docker-selected backup and one VM-selected backup |
| Secret masking and support bundle safety | Common secret formats, repository test output, support bundle config/jobs/status/log sanitizing | `tests/test_security_utils.py`, `tests/test_support_bundle_api.py` | Inspect a real support bundle before sharing it externally |
| Corrupt config/status recovery | Corrupt canonical inventories, `schedules.json`, `runtime-recovery.json`, and backup status files degrade safely | `tests/test_corrupt_config_recovery.py`, `tests/test_inventory_consistency.py` | None required unless a real user reports damaged config files |
| Canonical data-model migration | Stable legacy, partial test and canonical source states; ID preservation; idempotence; rollback; central audit | `tests/test_canonical_data_model_migration.py`, `tests/test_repository_objects.py` | Install the final candidate over one tester's stable installation and inspect System Health |
| Cross-process inventory safety | Two independent processes serialize repository updates without corrupting JSON or losing unrelated rows | `tests/test_inventory_consistency.py` | None beyond the final tester upgrade |
| Notifications and reminders | Event routing, ntfy payloads, reminder state cleanup, overdue calculation and sender/diagnostic alignment | `tests/test_notification_events.py`, `tests/test_ntfy_api.py` | Trigger one real ntfy test notification and one overdue-reminder check |

## Notes

- These tests intentionally mock external services and subprocesses where
  possible. They protect the decision logic and error handling, not the Unraid
  platform itself.
- Real Unraid behavior remains covered by manual maintenance tests in
  `docs/manual-maintenance-tests.md`.
- Test reports for specific builds are stored in `docs/test-reports/`.
