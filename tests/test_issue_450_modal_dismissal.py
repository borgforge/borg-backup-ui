from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_form_modals_ignore_backdrop_clicks_and_share_escape_close_contract() -> None:
    modal = _read("ui/js/components/modal.js")
    bindings = _read("ui/js/components/app-bindings.js")

    for modal_id in (
        "repository-manager-modal",
        "schedule-modal",
        "settings-dialog-modal",
        "storage-deploy-modal",
    ):
        backdrop_block = f"document.getElementById('{modal_id}')?.addEventListener('click'"
        assert backdrop_block not in modal

    assert "wireEscapeClose()" in modal
    assert "discard-confirm-modal" in modal
    assert "window.confirm" not in modal
    assert "['wizard-modal', 'closeWizard']" in modal
    assert "['repository-manager-modal', 'closeRepositoryManager']" in modal
    assert "['settings-dialog-modal', 'closeSettingsDialog']" in modal
    assert "['setup-wizard-modal', 'closeSetupWizard']" in modal
    assert "m.setAction('closeWizard', typeof closeWizard === 'function' ? closeWizard : null)" in bindings
    assert "m.setAction('closeRepositoryLifecycle', typeof closeRepositoryLifecycle === 'function' ? closeRepositoryLifecycle : null)" in bindings
    assert "event.target === event.currentTarget) closeRepositoryLifecycle" not in bindings


def test_job_wizard_create_and_edit_have_dirty_close_protection() -> None:
    wizard = _read("ui/js/pages/wizard.js")

    assert "function _wizardHasUnsavedChanges()" in wizard
    assert "function wizardBindCloseDirtyTracking()" in wizard
    assert "modal.addEventListener('input', wizardMarkCloseSnapshotTouched)" in wizard
    assert "modal.addEventListener('change', wizardMarkCloseSnapshotTouched)" in wizard
    assert "if (!options?.force && !_wizardConfirmDiscard()) return false;" in wizard
    assert "if (!wizardState.closeSnapshotTouched) _wizardCaptureCloseSnapshot();" in wizard

    edit_flow = wizard.split("async function openWizardForJob", 1)[1].split(
        "function closeWizard", 1
    )[0]
    assert "_wizardFillFromJob(job);" in edit_flow
    assert "_wizardCaptureCloseSnapshot();" in edit_flow
    assert "closeWizard({ force: true });" in wizard


def test_repository_and_confirmation_inputs_are_dirty_checked_before_close() -> None:
    storage = _read("ui/js/pages/storage.js")
    jobs = _read("ui/js/pages/jobs.js")
    settings = _read("ui/js/pages/settings.js")

    assert "storageState.repositoryManagerCloseSnapshot = storageModalSnapshot('repository-manager-modal')" in storage
    assert "storageModalDirty('repository-manager-modal', storageState.repositoryManagerCloseSnapshot)" in storage
    assert "storageState.lifecycleCloseSnapshot = storageModalSnapshot('repository-lifecycle-modal')" in storage
    assert "storageModalDirty('repository-lifecycle-modal', storageState.lifecycleCloseSnapshot)" in storage
    assert "closeRepositoryManager({ force: true })" in storage
    assert "closeRepositoryLifecycle({ force: true })" in storage

    assert "function confirmModalHasUnsavedInput()" in jobs
    assert "captureConfirmModalCloseSnapshot()" in jobs
    assert "closeModal({ force: true })" in jobs

    assert "modalHelpers.setAction?.('closeSettingsDialog', onCancel)" in settings
    assert "modal.addEventListener('click', onBackdrop)" not in settings
    assert "settingsState.storageDeployCloseSnapshot" in settings


def test_unsaved_discard_confirmation_is_localized() -> None:
    de = _read("ui/i18n/de.json")
    en = _read("ui/i18n/en.json")
    modal = _read("ui/js/components/modal.js")

    assert '"unsavedChangesTitle": "Ungespeicherte Änderungen"' in de
    assert '"discardUnsavedChangesMessage": "Deine Eingaben in diesem Dialog wurden noch nicht gespeichert."' in de
    assert '"keepEditing": "Weiter bearbeiten"' in de
    assert '"discardChanges": "Änderungen verwerfen"' in de
    assert '"unsavedChangesTitle": "Unsaved changes"' in en
    assert '"discardUnsavedChangesMessage": "Your entries in this dialog have not been saved yet."' in en
    assert '"keepEditing": "Keep editing"' in en
    assert '"discardChanges": "Discard changes"' in en
    assert "common.unsavedChangesTitle" in modal
    assert "common.discardUnsavedChangesMessage" in modal
