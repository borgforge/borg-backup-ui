from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROL_PAGE = ROOT / "plugin" / "borg-backup-ui.page"


def test_control_page_is_consistently_english():
    source = CONTROL_PAGE.read_text(encoding="utf-8")

    expected = [
        "Service Control",
        "Open Borg Backup UI",
        "Please wait...",
        "Configuration",
        "Bind address",
        "all interfaces",
        "local only",
        "Python 3.10 or newer",
    ]
    forbidden = [
        "Web-Oberfläche",
        "nicht gefunden",
        "nicht ausführbar",
        "konnte nicht ermittelt werden",
        "ist zu alt",
        "Bitte warten",
        "öffnen",
        "alle Interfaces",
        "nur lokal",
        "benötigt",
    ]

    assert all(text in source for text in expected)
    assert all(text not in source for text in forbidden)


def test_control_page_service_actions_remain_available():
    source = CONTROL_PAGE.read_text(encoding="utf-8")

    for action in ("start", "stop", "restart", "apply", "default"):
        assert f"'{action}'" in source or f'\"{action}\"' in source


def test_control_page_config_apply_uses_async_restart_redirect():
    source = CONTROL_PAGE.read_text(encoding="utf-8")

    assert "bbui_async" in source
    assert "Content-Type: application/json" in source
    assert "bbui_apply_config('apply')" in source
    assert "bbui_apply_config('default')" in source
    assert "new URLSearchParams()" in source
    assert "fetch('?' + params.toString()" in source
    assert "window.location.href = target" in source
    assert "bbui_ui_url($port)" in source
    assert "($_GET['PORT'] ?? 8765)" in source


def test_control_page_reads_test_and_stable_manifest_versions():
    source = CONTROL_PAGE.read_text(encoding="utf-8")

    test_manifest = '"/boot/config/plugins/borg-backup-ui-test.plg"'
    stable_manifest = '"/boot/config/plugins/borg-backup-ui.plg"'
    assert test_manifest in source
    assert stable_manifest in source
    assert source.index(test_manifest) < source.index(stable_manifest)
    assert "foreach ($plugin_manifests as $plg)" in source
