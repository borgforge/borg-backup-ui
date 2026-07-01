from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_wizard_prefers_backend_validation_details_for_errors() -> None:
    script = (ROOT / "ui" / "js" / "pages" / "wizard.js").read_text(encoding="utf-8")

    assert "function wizardApiErrorMessage(payload, status = 0)" in script
    assert "for (const key of ['details', 'message', 'error'])" in script
    assert "return apiErrorMessage(payload, status);" in script
    assert script.count("wizardApiErrorMessage(data, res.status)") >= 4
    assert "throw new Error(wizardApiErrorMessage(data, res.status));" in script
