from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from migrations import borg_keyfiles_v1  # noqa: E402
from repositories_api import read_repository_store, write_repository_store  # noqa: E402


def test_borg_keyfile_migration_is_exact_and_idempotent(tmp_path: Path, monkeypatch):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path / "borg-backup")}
    repository_id = "a" * 64
    home = tmp_path / "home"
    legacy = home / ".config" / "borg" / "keys"
    legacy.mkdir(parents=True)
    (legacy / "wanted").write_text(f"BORG_KEY {repository_id}\nencoded\n", encoding="utf-8")
    (legacy / "unrelated").write_text(f"BORG_KEY {'b' * 64}\nother\n", encoding="utf-8")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    write_repository_store(config, {"repositories": [{
        "repository_key": "repo_flash",
        "display_name": "Flash",
        "storage_key": "storage_local",
        "relative_path": "borg-backup-flash",
        "path_raw": "/mnt/backup/borg-backup-flash",
        "encryption": "keyfile-blake2",
        "borg_repository_id": repository_id,
    }]})

    detected = borg_keyfiles_v1.detect(config)
    first = borg_keyfiles_v1.apply(config)
    second = borg_keyfiles_v1.apply(config)

    assert detected["required"] is True
    assert first["status"] == "applied"
    assert first["details"]["updated_repositories"] == ["repo_flash"]
    assert second["status"] == "not_required"
    repository = read_repository_store(config)["repositories"][0]
    key_path = Path(repository["keyfile_ref"])
    assert key_path.is_file()
    assert key_path.read_text(encoding="utf-8").startswith(f"BORG_KEY {repository_id}")
    assert not (key_path.parent / "unrelated").exists()
