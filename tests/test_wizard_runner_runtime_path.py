from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import wizard_runner  # noqa: E402


def test_wizard_runner_prefers_plugin_runtime_before_data_root(tmp_path: Path):
    plugin_runtime = wizard_runner.ROOT_DIR / "runtime"
    data_root = tmp_path / "borg-backup"
    data_root.mkdir()

    original = list(sys.path)
    try:
        for path in (str(plugin_runtime), str(data_root)):
            while path in sys.path:
                sys.path.remove(path)

        wizard_runner._ensure_runtime_import_paths(data_root)

        assert sys.path.index(str(plugin_runtime)) < sys.path.index(str(data_root))
    finally:
        sys.path[:] = original
