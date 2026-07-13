from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from wizard_api import list_source_directories  # noqa: E402


def test_source_autocomplete_lists_base_and_nested_directories(tmp_path: Path):
    base = tmp_path / "mnt"
    user = base / "user"
    (user / "appdata").mkdir(parents=True)
    (user / "domains").mkdir()
    (base / "disks").mkdir()

    root_rows = list_source_directories(str(base), base_path=base)
    partial_rows = list_source_directories(str(base / "u"), base_path=base)
    user_rows = list_source_directories(str(user), base_path=base)

    assert root_rows == [
        {"path": f"{base}/disks/"},
        {"path": f"{base}/user/"},
    ]
    assert partial_rows == [{"path": f"{base}/user/"}]
    assert user_rows == [
        {"path": f"{user}/appdata/"},
        {"path": f"{user}/domains/"},
    ]


def test_source_autocomplete_rejects_paths_outside_base_and_symlinks(tmp_path: Path):
    base = tmp_path / "mnt"
    outside = tmp_path / "outside"
    base.mkdir()
    outside.mkdir()
    (base / "escape").symlink_to(outside, target_is_directory=True)

    assert list_source_directories(str(outside), base_path=base) == []
    assert list_source_directories(str(base), base_path=base) == []
