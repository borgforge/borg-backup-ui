from pathlib import Path
import json
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from wizard_api import generate_flow_preview, save_job


def _storagebox_params(repo: str = "ssh://u123@u123.your-storagebox.de:23/./backup/borg-backup-flash") -> dict:
    return {
        "type_id": "flash",
        "job_name": "Flash",
        "location": "storagebox",
        "storage_profile_key": "storage-1",
        "repo_path": repo,
        "source_paths": "/boot",
        "encryption": "none",
    }


class _RunResult:
    def __init__(self, returncode: int):
        self.returncode = returncode
        self.stdout = ""
        self.stderr = "not found" if returncode else ""


def test_wizard_preview_marks_existing_storagebox_repo_without_confirm(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: _RunResult(0))

    flow = generate_flow_preview(_storagebox_params(), {}, Path("/tmp/scripts"))

    assert flow["remote_repo"]["checked"] is True
    assert flow["remote_repo"]["exists"] is True
    assert flow["remote_repo"]["needs_init_confirm"] is False


def test_wizard_preview_rebuilds_storagebox_repo_from_profile(monkeypatch):
    import storage_profiles_api

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: _RunResult(0))
    monkeypatch.setattr(storage_profiles_api, "resolve_storage_profile", lambda _cfg, _key: {
        "key": "storage-1",
        "host": "u123.your-storagebox.de",
        "port": "23",
        "user": "u123",
        "base_path": "./backup",
    })
    params = _storagebox_params("ssh://u123@u123.your-storagebox.de:23./backup/borg-backup-flash")

    flow = generate_flow_preview(params, {}, Path("/tmp/scripts"))

    assert flow["summary"]["repo"] == "ssh://u123@u123.your-storagebox.de:23/./backup/borg-backup-flash"


def test_wizard_preview_exposes_stable_step_codes_and_english_fallbacks(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: _RunResult(0))
    params = _storagebox_params()
    params["source_paths"] = "/boot /mnt/user/appdata"

    flow = generate_flow_preview(params, {}, Path("/tmp/scripts"))

    assert [step["code"] for step in flow["step_codes"]] == [
        "prechecks",
        "resourceLocksAcquire",
        "borgCreate",
        "borgMaintenance",
        "statusNotification",
        "resourceLocksRelease",
    ]
    assert flow["step_codes"][2]["params"] == {"count": 2}
    fallback = "\n".join(flow["steps"])
    assert "Pfade" not in fallback
    assert "Quelle(n)" not in fallback
    assert "Wartung" not in fallback
    assert "Benachrichtigung" not in fallback


def test_save_storagebox_job_existing_repo_disables_create_if_missing(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: _RunResult(0))

    result = save_job(_storagebox_params(), tmp_path / "scripts", tmp_path / "data", {})
    metadata = json.loads(Path(result["metadata_path"]).read_text(encoding="utf-8"))

    assert metadata["remote_init_confirmed"] is False
    assert metadata["create_repo_if_missing"] is False


def test_save_storagebox_job_missing_repo_requires_confirm(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: _RunResult(2))

    with pytest.raises(ValueError, match="Remote repository creation is not confirmed"):
        save_job(_storagebox_params(), tmp_path / "scripts", tmp_path / "data", {})
