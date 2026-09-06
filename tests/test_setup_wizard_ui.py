from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


@pytest.mark.parametrize("scenario", [
    "maintenance_response",
    "status_markers",
    "stale_setup_response",
    "existing_mandatory_modal",
    "startup_response_order",
    "pending_return_and_actions",
    "normal_initial_setup",
    "normal_optional_setup",
    "normal_save_data_dir",
])
def test_setup_wizard_yields_to_migration_maintenance(scenario: str) -> None:
    node = os.environ.get("BBUI_TEST_NODE") or shutil.which("node")
    if not node:
        pytest.skip("Node.js unavailable")
    result = subprocess.run(
        [node, str(ROOT / "tests/setup_wizard_maintenance_ui.cjs"), scenario],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_first_run_setup_wizard_is_loaded_and_has_modal_contract() -> None:
    bootstrap = _read("ui/js/app-main.js")
    html = _read("ui/index.html")
    script = _read("ui/js/pages/setup-wizard.js")

    assert "/ui/js/pages/setup-wizard.js" in bootstrap
    assert bootstrap.index("/ui/js/pages/settings.js") < bootstrap.index("/ui/js/pages/setup-wizard.js")
    assert 'id="dashboard-setup-actions"' in html
    assert 'id="setup-wizard-modal"' in html
    assert 'data-setup-wizard-action="save-data-dir"' in html
    assert "fetch('/api/setup-status'" in script
    assert "fetch('/api/setup-wizard'" in script
    assert "GLOBAL_DATA_DIR" in script
    assert "openRepositoryManager" in script
    assert "openWizard" in script


def test_dashboard_and_startup_wire_setup_wizard_actions() -> None:
    bindings = _read("ui/js/components/app-bindings.js")
    dashboard = _read("ui/js/pages/dashboard.js")
    core = _read("ui/js/core/app-core.js")

    assert "dashboard-setup-actions" in bindings
    assert "updateDataDirWarning?.({ deferMissingWarning: true })" in bindings
    assert "setupWizard?.open?.(setupStatus)" in bindings
    assert "setupWizard?.maybeOpen?.(false)" in bindings
    assert "hideMissingDataDirWarnings" in core
    assert "!ready && !hideMissingDataDirWarnings" in core
    assert "setupWizard?.renderDashboardPanel" in dashboard
    assert "fetchSetupStatus(false)" in dashboard


def test_setup_wizard_returns_after_external_save_flows() -> None:
    setup_wizard = _read("ui/js/pages/setup-wizard.js")
    settings = _read("ui/js/pages/settings.js")
    storage = _read("ui/js/pages/storage.js")
    wizard = _read("ui/js/pages/wizard.js")

    assert "function armReturn(step)" in setup_wizard
    assert "function resumeAfterExternalSave(step = '')" in setup_wizard
    assert "armReturn('storage')" in setup_wizard
    assert "armReturn('repository')" in setup_wizard
    assert "armReturn('job')" in setup_wizard
    assert "openRepositoryManager({ forceRefresh: true })" in setup_wizard
    assert "setupWizard?.resumeAfterExternalSave?.('storage')" in settings
    assert "setupWizard?.resumeAfterExternalSave?.('repository')" in storage
    assert "setupWizard?.resumeAfterExternalSave?.('job')" in wizard
    assert "async function repositoryManagerEnsureStorages(force = false)" in storage


def test_setup_wizard_uses_minimal_status_icons() -> None:
    script = _read("ui/js/pages/setup-wizard.js")
    css = _read("ui/style.css")

    assert "function setupStatusIcon(status)" in script
    assert 'neutral: \'<circle cx="12" cy="12" r="8.5"/><path d="M8 12h8"/>\'' in script
    assert 'success: \'<circle cx="12" cy="12" r="8.5"/><path d="m8.5 12.5 2.2 2.2 4.8-5.4"/>\'' in script
    assert 'warning: \'<path d="M10.3 4.4a2 2 0 0 1 3.4 0l7.4 12.8a2 2 0 0 1-1.7 3H4.6a2 2 0 0 1-1.7-3z"/>' in script
    assert "setupStatusIcon(complete ? 'success' : 'warning')" in script
    assert "setupStatusIcon('neutral')" in script
    assert "&#10003;" not in script
    assert "&middot;" not in script
    assert ".setup-wizard-step-state svg" in css
    assert ".setup-wizard-step-state {\n  display: inline-grid;\n  place-items: center;\n  width: 24px;\n  height: 24px;\n}" in css
