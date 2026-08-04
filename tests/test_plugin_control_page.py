from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROL_PAGE = ROOT / "plugin" / "borg-backup-ui.page"
ADMIN_RECOVERY_ENDPOINT = ROOT / "plugin" / "admin-recovery.php"


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
        "Admin Access Recovery",
        "Reset Admin Access",
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
    assert "Unsupported control page action." in source
    assert "window.open('about:blank', '_blank')" in source
    assert "targetWindow.location.href = target" in source
    assert "var defaultButtons = buttons.innerHTML" in source
    assert "buttons.innerHTML = defaultButtons" in source
    assert "Open the UI in a new browser window" not in source
    assert "Open Borg Backup UI" in source
    assert "window.location.href = target" not in source
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


def test_control_page_admin_recovery_uses_post_body_and_python_helper():
    source = CONTROL_PAGE.read_text(encoding="utf-8")
    endpoint = ADMIN_RECOVERY_ENDPOINT.read_text(encoding="utf-8")

    assert "api/admin_recovery.py" in source
    assert "--list-admins" in source
    assert "method: 'POST'" in source
    assert "new FormData(form)" in source
    assert "fetch('/plugins/borg-backup-ui/admin-recovery.php'" in source
    assert "bbui_request_value('password'" in endpoint
    assert "file_get_contents('php://input')" in endpoint
    assert "--control-page" in endpoint
    assert "Content-Type: application/json" in endpoint
    assert "Admin recovery requires POST." in endpoint
    assert "Admin recovery returned an empty response." in source
    assert "bbui_load_admin_accounts" in source
    assert "<select class=\"bbui-select\" name=\"username\"" in source
    assert "password_confirm" in source
    assert "Password must contain at least 12 characters." in source
    assert "All Borg Backup UI sessions were signed out" in source
    assert "Reset the password of an existing Borg Backup UI administrator account" in source
    assert "Reset or create an enabled" not in source
