from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _selector_block(css: str, selector: str) -> str:
    return css.split(f"{selector} {{", 1)[1].split("}", 1)[0]


def test_job_wizard_nested_scroll_areas_do_not_scroll_the_background() -> None:
    css = (ROOT / "ui" / "style.css").read_text(encoding="utf-8")

    assert "overscroll-behavior-y: contain" in _selector_block(css, ".wizard-body")
    assert "overscroll-behavior-y: contain" in _selector_block(
        css, ".wizard-runtime-selection"
    )
