from pathlib import Path
import json
import sys


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import jobs_api  # noqa: E402
import repository_context  # noqa: E402
import restore_tests_api  # noqa: E402


def test_restore_step_labels_archive_path_and_shows_origin_context() -> None:
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "ui" / "js" / "pages" / "restore.js").read_text(encoding="utf-8")
    german = json.loads((ROOT / "ui" / "i18n" / "de.json").read_text(encoding="utf-8"))
    english = json.loads((ROOT / "ui" / "i18n" / "en.json").read_text(encoding="utf-8"))

    assert german["restore"]["sourcePath"] == "Archiv-Pfad"
    assert english["restore"]["sourcePath"] == "Archive path"
    assert 'id="restore-source-repository"' in html
    assert 'id="restore-source-archive"' in html
    assert "job?.repository_name || job?.repository_key" in script
    assert "archive.textContent = restoreState.archive" in script


def test_job_api_exposes_repository_display_name_for_restore_context(monkeypatch) -> None:
    job = jobs_api.JobInfo(
        key="photos_local",
        backup_type="photos",
        location="local",
        script_path=None,
        name="Photos",
    )
    monkeypatch.setattr(jobs_api, "resolve_scripts_dir", lambda _config: Path("/unused/scripts"))
    monkeypatch.setattr(jobs_api, "resolve_data_root", lambda _config: Path("/unused"))
    monkeypatch.setattr(jobs_api, "get_all_runtime_states", lambda _config: {})
    monkeypatch.setattr(jobs_api, "discover_jobs", lambda _scripts, _root: [job])
    monkeypatch.setattr(repository_context, "load_repository_inventory", lambda _config: {
        "repositories": {},
        "storages": {},
    })
    monkeypatch.setattr(repository_context, "resolve_job_repository_context", lambda *_args, **_kwargs: {
        "repository_path": "/mnt/backup/borg-photos",
        "repository_key": "repo_photos",
        "repository": {
            "repository_key": "repo_photos",
            "display_name": "Photos Repository",
        },
    })
    monkeypatch.setattr(restore_tests_api, "build_restore_verification_map", lambda *_args: {})

    result = jobs_api.list_jobs({}, {})

    assert result[0]["repository_key"] == "repo_photos"
    assert result[0]["repository_name"] == "Photos Repository"
