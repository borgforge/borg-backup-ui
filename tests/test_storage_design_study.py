from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_storage_study_offers_three_distinct_variants() -> None:
    html = _read("docs/ui-design/storage-study/index.html")
    script = _read("docs/ui-design/storage-study/storage.js")
    for variant in ("a", "b", "c"):
        assert f'data-variant="{variant}"' in html
        assert f"variant{variant.upper()}" in script


def test_storage_study_preserves_operational_controls() -> None:
    script = _read("docs/ui-design/storage-study/storage.js")
    for contract in (
        "Repository testen", "Manueller Borg Check", "Schnell", "Verbose",
        "Verify Data", "Mount", "Unmount", "Leeren", "data-check-log",
    ):
        assert contract in script


def test_storage_study_reuses_location_icons_and_responsive_states() -> None:
    script = _read("docs/ui-design/storage-study/storage.js")
    css = _read("docs/ui-design/storage-study/storage.css")
    for location in ("local", "usb", "smb", "storagebox"):
        assert f"{location}:'<svg" in script
    assert "html[data-theme=light]" in css
    assert "@media(max-width:1100px)" in css
    assert "@media(max-width:720px)" in css
