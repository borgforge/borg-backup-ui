import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FOUNDATION = ROOT / "ui" / "design-system.css"


def _foundation() -> str:
    return FOUNDATION.read_text(encoding="utf-8")


def test_foundation_is_loaded_after_legacy_styles() -> None:
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    assert html.index('/ui/style.css') < html.index('/ui/design-system.css')

    server = (ROOT / "borg_backup_ui.py").read_text(encoding="utf-8")
    assert server.count('<link rel="stylesheet" href="/ui/design-system.css">') == 2


def test_main_app_applies_stored_theme_before_stylesheets() -> None:
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    assert "bbui_theme_preference" in html
    assert "document.documentElement.setAttribute('data-theme', resolved)" in html
    assert html.index("bbui_theme_preference") < html.index('<link rel="stylesheet" href="/ui/style.css">')


def test_foundation_defines_shared_tokens_for_both_themes() -> None:
    css = _foundation()
    assert ':root[data-theme="light"]' in css

    required_tokens = {
        "--ui-color-bg",
        "--ui-color-surface",
        "--ui-color-border",
        "--ui-color-text",
        "--ui-font-sans",
        "--ui-space-4",
        "--ui-radius-md",
        "--ui-shadow-raised",
        "--ui-state-neutral-bg",
        "--ui-state-info-bg",
        "--ui-state-running-bg",
        "--ui-state-success-bg",
        "--ui-state-warning-bg",
        "--ui-state-error-bg",
        "--ui-state-disabled-bg",
    }
    for token in required_tokens:
        assert token in css


def test_foundation_exposes_incremental_component_contract() -> None:
    css = _foundation()
    required_components = {
        ".ui-page-header",
        ".ui-context-sidebar",
        ".ui-workspace-header",
        ".ui-context-nav__item",
        ".ui-table-wrap",
        ".ui-field",
        ".ui-badge",
        ".ui-summary-grid",
        ".ui-log",
        ".ui-actions",
        ".ui-loading",
        ".ui-empty",
        ".ui-state--warning",
        ".ui-state--error",
        ".ui-state--running",
        ".ui-state--success",
    }
    for component in required_components:
        assert component in css


def test_foundation_bridges_existing_status_components() -> None:
    css = _foundation()
    for component in (
        ".badge",
        ".loc-badge",
        ".history-status-badge",
        ".restore-v-badge",
        ".system-health-badge",
        ".setup-badge",
        ".smb-mount-badge",
        ".test-result",
        ".rt-step-status",
        ".check-mode-badge",
        ".status-message",
    ):
        assert component in css


def test_foundation_covers_tablet_mobile_and_accessibility_states() -> None:
    css = _foundation()
    assert "@media (max-width: 1023px)" in css
    assert "@media (max-width: 767px)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert ":focus-visible" in css
    assert '[aria-disabled="true"]' in css
    assert "overflow-x: auto" in css


def test_light_theme_uses_explicit_readable_status_surfaces() -> None:
    css = _foundation()
    light_theme = css.split(':root[data-theme="light"]', 1)[1]
    for value in (
        "--ui-state-neutral-bg: #eef2f6",
        "--ui-state-neutral-fg: #334155",
        "--ui-state-info-bg: #e8f1ff",
        "--ui-state-info-fg: #174ea6",
        "--ui-state-success-bg: #e7f6eb",
        "--ui-state-success-fg: #166534",
        "--ui-state-warning-bg: #fff4d6",
        "--ui-state-warning-fg: #854d0e",
        "--ui-state-error-bg: #fdebec",
        "--ui-state-error-fg: #991b1b",
    ):
        assert value in light_theme


def test_light_theme_status_text_meets_normal_text_contrast() -> None:
    css = _foundation()
    light_theme = css.split(':root[data-theme="light"]', 1)[1]

    def token(name: str) -> str:
        match = re.search(rf"{re.escape(name)}:\s*(#[0-9a-fA-F]{{6}})", light_theme)
        assert match, name
        return match.group(1)

    def luminance(color: str) -> float:
        channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    for state in ("neutral", "info", "running", "success", "warning", "error", "disabled"):
        foreground = luminance(token(f"--ui-state-{state}-fg"))
        background = luminance(token(f"--ui-state-{state}-bg"))
        contrast = (max(foreground, background) + 0.05) / (min(foreground, background) + 0.05)
        assert contrast >= 4.5, f"{state} contrast is only {contrast:.2f}:1"


def test_foundation_has_no_external_css_dependencies() -> None:
    css = _foundation()
    assert "@import" not in css
    assert "http://" not in css
    assert "https://" not in css
