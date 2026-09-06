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


from test_canonical_job_wizard import setup, create


def test_job_api_exposes_repository_display_name_for_restore_context(setup, monkeypatch) -> None:
    from job_store import read_json
    from inventory_store import atomic_write_json
    result, _ = create(setup)
    store_path = setup[3] / 'config/repositories.json'
    store = read_json(store_path)
    store['repositories'][0]['display_name'] = 'Photos Repository'
    atomic_write_json(store_path, store)
    monkeypatch.setattr(jobs_api, 'get_all_runtime_states', lambda _config: {})
    data = jobs_api.list_jobs(setup[0], {})
    assert data[0]['job_id'] == result['job_id']
    assert data[0]['repository_key'] == 'repo_a'
    assert data[0]['repository_name'] == 'Photos Repository'
