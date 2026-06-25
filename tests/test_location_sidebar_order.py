from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED = "['local', 'usb', 'smb', 'storagebox']"


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_all_location_sidebars_use_the_shared_fixed_order() -> None:
    sources = {
        "ui/js/pages/dashboard.js": "DASHBOARD_LOCATION_ORDER",
        "ui/js/pages/history.js": "HISTORY_LOCATIONS",
        "ui/js/pages/reports.js": "const order",
        "ui/js/pages/restore-tests.js": "const order",
        "ui/js/pages/restore.js": "const order",
    }
    for path, marker in sources.items():
        source = _read(path)
        assert marker in source
        assert EXPECTED in source

    jobs = _read("ui/js/pages/jobs.js")
    assert "['local', 'usb', 'smb', 'storagebox', 'utility']" in jobs


def test_location_order_is_documented_as_fixed() -> None:
    design = _read("docs/ui-design/README.md")
    assert "Local, USB, SMB, Storagebox" in design
    assert "not user-configurable" in design
