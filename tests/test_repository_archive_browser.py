import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import archive_browser  # noqa: E402
import jobs_api  # noqa: E402
import repositories_api  # noqa: E402
from repositories_api import RepositoryBusyError, get_repository_archive_files, write_repository_store  # noqa: E402
from storage_objects_api import write_storage_store  # noqa: E402


@pytest.fixture(autouse=True)
def clear_archive_browser_cache():
    archive_browser._CACHE.clear()
    yield
    archive_browser._CACHE.clear()


def _repository_config(tmp_path: Path) -> tuple[dict, Path]:
    base = tmp_path / "backup"
    repository_path = base / "repository"
    repository_path.mkdir(parents=True)
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_local",
        "display_name": "Local",
        "storage_type": "local",
        "location": "local",
        "identity": f"local:{base}",
        "base_path": str(base),
    }]})
    write_repository_store(config, {"repositories": [{
        "repository_key": "repo_test",
        "display_name": "Test repository",
        "repository_name": "repository",
        "storage_key": "storage_local",
        "location": "local",
        "relative_path": "repository",
        "path_raw": str(repository_path),
        "encryption": "none",
    }]})
    return config, repository_path


def test_shared_archive_index_lists_root_and_nested_entries_and_is_cached(monkeypatch):
    calls = []
    output = "\n".join([
        json.dumps({"path": "share", "type": "d", "size": 0, "mtime": "2026-09-05T08:00:00"}),
        json.dumps({"path": "share/file.txt", "type": "-", "size": 42, "mtime": "2026-09-05T08:01:00"}),
        json.dumps({"path": "root.txt", "type": "-", "size": 7, "mtime": "2026-09-05T08:02:00"}),
    ])

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=output, stderr="")

    monkeypatch.setattr(archive_browser.subprocess, "run", fake_run)

    root = archive_browser.list_archive_directory("/repo", "archive-1", "", {"LANG": "C"})
    nested = archive_browser.list_archive_directory("/repo", "archive-1", "share", {"LANG": "C"})

    assert [entry["name"] for entry in root] == ["share", "root.txt"]
    assert nested == [{
        "name": "file.txt",
        "path": "share/file.txt",
        "type": "-",
        "size": 42,
        "mtime": "2026-09-05T08:01:00",
        "mode": "",
    }]
    assert len(calls) == 1
    assert calls[0][0] == ["borg", "list", "--json-lines", "/repo::archive-1"]
    assert calls[0][1]["timeout"] == 300


def test_shared_archive_index_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(
        archive_browser.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    for index in range(archive_browser.ARCHIVE_INDEX_CACHE_MAX_ENTRIES + 3):
        archive_browser.build_archive_index(f"/repo-{index}", f"archive-{index}", {})

    assert len(archive_browser._CACHE) <= archive_browser.ARCHIVE_INDEX_CACHE_MAX_ENTRIES


def test_repository_archive_browser_resolves_repository_without_job(tmp_path: Path, monkeypatch):
    config, repository_path = _repository_config(tmp_path)
    monkeypatch.setattr(jobs_api, "is_resource_active", lambda *_args, **_kwargs: False)
    captured = {}

    def fake_list(repo, archive, path, env):
        captured.update({"repo": repo, "archive": archive, "path": path, "env": env})
        return [{"name": "folder", "path": "folder", "type": "d", "size": 0, "mtime": "", "mode": ""}]

    monkeypatch.setattr(archive_browser, "list_archive_directory", fake_list)

    result = get_repository_archive_files(config, "repo_test", "imported archive", "")

    assert result["repository_key"] == "repo_test"
    assert result["archive"] == "imported archive"
    assert result["files"][0]["name"] == "folder"
    assert captured["repo"] == str(repository_path)
    assert captured["archive"] == "imported archive"
    assert captured["path"] == ""
    assert captured["env"]["BORG_UNKNOWN_UNENCRYPTED_REPO_ACCESS_IS_OK"] == "yes"


def test_repository_archive_browser_rejects_busy_repository(tmp_path: Path, monkeypatch):
    config, _repository_path = _repository_config(tmp_path)
    monkeypatch.setattr(jobs_api, "is_resource_active", lambda *_args, **_kwargs: True)

    with pytest.raises(RepositoryBusyError, match="currently in use"):
        get_repository_archive_files(config, "repo_test", "archive-1", "")


@pytest.mark.parametrize("archive", ["", "bad::name", "bad\nname"])
def test_repository_archive_browser_rejects_invalid_archive_names(tmp_path: Path, archive: str):
    config, _repository_path = _repository_config(tmp_path)

    with pytest.raises(ValueError, match="Archive name is invalid"):
        get_repository_archive_files(config, "repo_test", archive, "")


@pytest.mark.parametrize("path", ["/absolute", "../parent", "folder/../file", "folder//file", "bad\npath"])
def test_repository_archive_browser_rejects_invalid_paths(tmp_path: Path, path: str):
    config, _repository_path = _repository_config(tmp_path)

    with pytest.raises(ValueError, match="Archive path is invalid"):
        get_repository_archive_files(config, "repo_test", "archive-1", path)


def test_repository_archive_browser_frontend_is_read_only_and_localized():
    script = (ROOT / "ui" / "js" / "pages" / "storage.js").read_text(encoding="utf-8")
    server = (ROOT / "borg_backup_ui.py").read_text(encoding="utf-8")
    de = json.loads((ROOT / "ui" / "i18n" / "de.json").read_text(encoding="utf-8"))
    en = json.loads((ROOT / "ui" / "i18n" / "en.json").read_text(encoding="utf-8"))

    assert "/api/repositories/archive-files?" in script
    assert 'data-storage-action="open-repository-archive"' in script
    assert 'data-storage-action="browse-repository-archive-path"' in script
    assert "renderStorageArchiveBrowser" in script
    assert "/api/repositories/archive-files" in server
    assert de["storage"]["repositoryArchiveBrowserReadOnly"] == "Schreibgeschützte Ansicht"
    assert en["storage"]["repositoryArchiveBrowserReadOnly"] == "Read-only view"
    browser_renderer = script.split("function renderStorageArchiveBrowser", 1)[1].split("async function loadRepositoryArchiveFiles", 1)[0]
    assert "download" not in browser_renderer.lower()
    assert "restore" not in browser_renderer.lower()
