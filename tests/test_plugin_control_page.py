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
