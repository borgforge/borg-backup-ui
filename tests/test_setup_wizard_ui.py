from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


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
