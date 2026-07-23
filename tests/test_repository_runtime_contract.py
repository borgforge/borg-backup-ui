from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_productive_job_runtime_does_not_read_legacy_repository_fields() -> None:
    productive_sources = (
        ROOT / "api" / "wizard_runner.py",
        ROOT / "api" / "wizard_api.py",
        ROOT / "api" / "jobs_api.py",
        ROOT / "api" / "restore_api.py",
        ROOT / "runtime" / "scripts" / "borg_restore_test.py",
    )
    legacy_fields = (
        "repo",
        "passphrase",
        "encryption",
        "storage_key",
        "usb_profile_key",
        "smb_profile_key",
        "storage_profile_key",
        "create_repo_if_missing",
        "remote_init_confirmed",
    )
    for source_path in productive_sources:
        source = source_path.read_text(encoding="utf-8")
        for variable in ("meta", "raw", "job", "job_meta"):
            for field in legacy_fields:
                assert f'{variable}.get("{field}")' not in source, (
                    f"{source_path.relative_to(ROOT)} reads legacy job field {field}"
                )
