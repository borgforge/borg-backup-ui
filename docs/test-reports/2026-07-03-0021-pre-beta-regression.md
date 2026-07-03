# Pre-Beta Regression Test Report

## Build

- Version: `2026.07.03.0021`
- Commit: `6133b0d`
- Date: `2026-07-03`
- Scope: Issue `#124`

## Commands

```bash
pytest -q tests/test_resource_locks.py tests/test_docker_manager_runtime.py tests/test_corrupt_config_recovery.py tests/test_security_utils.py tests/test_support_bundle_api.py
pytest -q
```

## Results

- Focused pre-beta safety tests: `12 passed`
- Full local test suite: `256 passed`

## Covered Areas

- Schedule and cron safety
- Restore target path safety
- Resource locks and stale lock recovery
- Borg restore-download timeout and stderr collection
- Docker selected stop/start behavior and runtime recovery state
- Secret masking and support bundle sanitizing
- Corrupt config/status recovery
- Notification reminder logic

## Manual Follow-Up

The local suite does not require Unraid, Docker, VMs, or real Borg repositories.
The following checks remain manual integration tests on Unraid:

- Save one real schedule and inspect the generated crontab entry.
- Run one Browse & Restore dry-run and one small real restore.
- Run one Docker-selected backup and one VM-selected backup.
- Trigger one real ntfy test notification and one overdue-reminder check.
- Inspect one real support bundle before sharing it externally.
