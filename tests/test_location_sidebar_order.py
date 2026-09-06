from pathlib import Path
import ast
import re


ROOT = Path(__file__).resolve().parents[1]
EXPECTED = ['local', 'usb', 'smb', 'storagebox']


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_all_location_sidebars_use_the_shared_fixed_order() -> None:
    sources = {
        "ui/js/pages/dashboard.js": "DASHBOARD_LOCATION_ORDER",
        "ui/js/pages/history.js": "HISTORY_LOCATIONS",
        "ui/js/pages/reports.js": "const order",
        "ui/js/pages/restore-tests.js": "const order",
        "ui/js/pages/restore.js": "const order",
        "ui/js/pages/storage.js": "STORAGE_LOCATION_ORDER",
    }
    for path, marker in sources.items():
        source = _read(path)
        match = re.search(rf"\b{re.escape(marker)}\s*=\s*(\[[^\]]*\])", source)
        assert match is not None, path
        locations = ast.literal_eval(match.group(1))
        # Historical records without a known location remain visible after
        # migration, following the four established storage locations.
        suffix = ['unknown'] if path.endswith('/history.js') else []
        assert locations == EXPECTED + suffix, path

    jobs = _read("ui/js/pages/jobs.js")
    assert "['local', 'usb', 'smb', 'storagebox', 'utility']" in jobs
