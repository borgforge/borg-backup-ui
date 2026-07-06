import json
from pathlib import Path
from types import SimpleNamespace
import sys

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from status_api import _auto_write_weekly_snapshot, _import_legacy_snapshot_if_needed  # noqa: E402


def test_weekly_snapshots_import_legacy_once_and_write_only_canonical(tmp_path: Path):
    status_dir = tmp_path / "status"
    snapshot_file = tmp_path / "weekly-snapshots.json"
    legacy_snapshot_file = status_dir / "weekly-snapshots.json"
    legacy_snapshot_file.parent.mkdir(parents=True)
    legacy_snapshot_file.write_text(
        json.dumps({"appdata_local": [{"week": "2026-06-22", "size": 100}]}),
        encoding="utf-8",
    )

    _import_legacy_snapshot_if_needed(snapshot_file, legacy_snapshot_file)
    _auto_write_weekly_snapshot(
        snapshot_file,
        {"appdata_local": SimpleNamespace(repository_size=200)},
        force_write=True,
    )

    canonical = json.loads(snapshot_file.read_text(encoding="utf-8"))
    legacy = json.loads(legacy_snapshot_file.read_text(encoding="utf-8"))

    assert canonical["appdata_local"][-1]["size"] == 200
    assert legacy == {"appdata_local": [{"week": "2026-06-22", "size": 100}]}
