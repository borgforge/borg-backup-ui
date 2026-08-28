from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _selector_block(css: str, selector: str) -> str:
    return css.split(f"{selector} {{", 1)[1].split("}", 1)[0]


def test_job_wizard_nested_scroll_areas_do_not_scroll_the_background() -> None:
    css = (ROOT / "ui" / "style.css").read_text(encoding="utf-8")
    wizard_js = (ROOT / "ui" / "js" / "pages" / "wizard.js").read_text(
        encoding="utf-8"
    )

    assert "overscroll-behavior-y: contain" in _selector_block(css, ".wizard-body")
    assert "overscroll-behavior-y: contain" in _selector_block(
        css, ".wizard-runtime-selection"
    )
    assert "overflow: hidden" in _selector_block(css, "body.wizard-modal-open")
    assert "document.body.classList.add('wizard-modal-open')" in wizard_js
    assert "document.body.classList.remove('wizard-modal-open')" in wizard_js


def test_runtime_risk_notices_leave_room_for_selection_lists() -> None:
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "ui" / "style.css").read_text(encoding="utf-8")

    assert 'id="wiz-appdata-risk" class="status-message warning wizard-runtime-risk hidden"' in html
    assert 'id="wiz-domains-risk" class="status-message warning wizard-runtime-risk hidden"' in html
    assert "wizard-runtime-head" not in html

    risk_block = _selector_block(css, ".wizard-runtime-risk")
    assert "grid-template-columns: minmax(0, 1fr) auto" in risk_block
    assert "margin: 0" in risk_block
    assert "padding: 8px 12px" in risk_block


def test_final_preview_contains_runtime_risk_acknowledgements() -> None:
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "ui" / "js" / "pages" / "wizard.js").read_text(
        encoding="utf-8"
    )

    assert 'id="wiz-final-risk-list" class="wizard-final-risk-list hidden"' in html
    assert 'id="wiz-final-ack-appdata-risk"' in html
    assert 'id="wiz-final-ack-domains-risk"' in html
    assert "function wizardUpdateFinalRiskAcknowledgements()" in script
    assert "if (step === 3) return _wizardRuntimeMode('docker') !== 'none';" in script
    assert "if (step === 4) return _wizardRuntimeMode('vm') !== 'none';" in script
    assert "if (step === 9)" in script
    assert "_wizardFocusRuntimeRisk('wiz-final-appdata-risk')" in script
    assert "_wizardSyncRiskAcknowledgement('docker', el.checked)" in script
    assert "saveBtn.disabled = pending" in script
