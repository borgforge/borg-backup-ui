from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_remaining_ui_redesign_styles_are_loaded_last() -> None:
    html = _read("ui/index.html")
    assert html.index("/ui/browse-restore-redesign.css") < html.index(
        "/ui/remaining-ui-redesign.css"
    )


def test_storage_uses_approved_variant_a_and_preserves_controls() -> None:
    html = _read("ui/index.html")
    script = _read("ui/js/pages/storage.js")
    for element_id in (
        "storage-location-list",
        "storage-workspace-header",
        "storage-content",
        "storage-check-card",
        "check-job-select",
        "check-level-select",
        "check-run-btn",
        "check-log-panel",
        "check-log-output",
    ):
        assert f'id="{element_id}"' in html
    for contract in (
        "STORAGE_LOCATION_ORDER = ['local', 'usb', 'smb', 'storagebox']",
        "renderStorageRepositoryRow",
        "renderStorageSmbProfiles",
        'data-storage-action="test-repo"',
        'data-storage-action="smb-action"',
        "/api/storage/test",
        "/api/storage/smb-action",
        "/api/storage/check/run",
        "/api/storage/check/stream",
    ):
        assert contract in script


def test_storage_reuses_location_icons_without_summary_ledger() -> None:
    script = _read("ui/js/pages/storage.js")
    for distinctive_path in (
        '<rect x="2" y="2" width="20" height="8" rx="2"/>',
        '<path d="M17 8h1a4 4 0 0 1 0 8h-1"/>',
        '<path d="M3 7h18"/><path d="M3 12h18"/><path d="M3 17h18"/>',
        '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
    ):
        assert distinctive_path in script
    assert "storage-summary" not in script


def test_help_has_generated_table_of_contents() -> None:
    html = _read("ui/index.html")
    script = _read("ui/js/pages/help.js")
    assert 'id="help-toc"' in html
    assert "function _renderHelpToc(content)" in script
    assert "content.querySelectorAll('h2, h3')" in script
    assert "_renderHelpToc(box);" in script


def test_remaining_surfaces_are_responsive_and_modal_content_is_contained() -> None:
    css = _read("ui/remaining-ui-redesign.css")
    assert "@media (max-width: 1023px)" in css
    assert "@media (max-width: 767px)" in css
    assert ".storage-table-wrap" in css
    assert "overflow-x: auto" in css
    assert ".modal-body" in css
    assert "overflow-y: auto" in css
    assert ".modal-wizard" in css
