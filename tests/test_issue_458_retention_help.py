import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
for path in (ROOT, API_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from check_api import CheckManager  # noqa: E402
from runtime.lib.borg_runner import BORG_EXIT_ERROR, BorgConfig, BorgRunner  # noqa: E402
from wizard_api import (  # noqa: E402
    RetentionValidationError,
    _retention_from_params,
    generate_flow_preview,
)


def test_retention_counts_are_normalized_and_allow_individual_zero_values() -> None:
    assert _retention_from_params({}) == {
        "daily": "7",
        "weekly": "4",
        "monthly": "6",
        "yearly": "3",
    }
    assert _retention_from_params({
        "keep_daily": "020",
        "keep_weekly": "0",
        "keep_monthly": "6",
        "keep_yearly": "3",
    }) == {
        "daily": "20",
        "weekly": "0",
        "monthly": "6",
        "yearly": "3",
    }


def test_retention_rejects_all_zero_and_invalid_counts() -> None:
    with pytest.raises(RetentionValidationError) as all_zero:
        _retention_from_params({
            "keep_daily": "0",
            "keep_weekly": "0",
            "keep_monthly": "0",
            "keep_yearly": "0",
        })
    assert all_zero.value.api_code == "retention_all_zero"

    for value in ("-1", "1.5", "not-a-number"):
        with pytest.raises(RetentionValidationError) as invalid:
            _retention_from_params({"keep_daily": value})
        assert invalid.value.api_code == "retention_invalid"


def test_automatic_prune_blocks_legacy_all_zero_policy(monkeypatch, caplog) -> None:
    called = False

    def fake_run(*_args, **_kwargs):
        nonlocal called
        called = True
        return 0

    monkeypatch.setattr("runtime.lib.borg_runner._run_borg", fake_run)
    runner = BorgRunner(BorgConfig(
        keep_daily=0,
        keep_weekly=0,
        keep_monthly=0,
        keep_yearly=0,
        repo="/mnt/backup/repository",
    ))

    assert runner.prune("appdata-backup") == BORG_EXIT_ERROR
    assert called is False
    assert "at least one retention value must be greater than zero" in caplog.text


def test_manual_repository_prune_blocks_all_zero_policy(tmp_path: Path) -> None:
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    jobs = tmp_path / "config" / "jobs"
    jobs.mkdir(parents=True)
    (jobs / "appdata_local.json").write_text(json.dumps({
        "job_key": "appdata_local",
        "repository_key": "repo_appdata",
        "retention": {"daily": "0", "weekly": "0", "monthly": "0", "yearly": "0"},
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="At least one retention value"):
        CheckManager()._repository_command(
            config,
            {"repository_key": "repo_appdata", "used_by": ["appdata_local"]},
            "/mnt/backup/appdata",
            "prune",
            "quick",
        )


def test_flow_preview_exposes_the_effective_retention_policy() -> None:
    flow = generate_flow_preview({
        "type_id": "appdata",
        "location": "local",
        "source_paths": ["/mnt/user/appdata"],
        "keep_daily": "20",
        "keep_weekly": "40",
        "keep_monthly": "20",
        "keep_yearly": "23",
    })

    assert flow["summary"]["retention"] == {
        "daily": "20",
        "weekly": "40",
        "monthly": "20",
        "yearly": "23",
    }


def test_retention_step_explains_periods_and_blocks_all_zero_in_both_languages() -> None:
    index = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "ui" / "js" / "pages" / "wizard.js").read_text(encoding="utf-8")
    bindings = (ROOT / "ui" / "js" / "components" / "app-bindings.js").read_text(encoding="utf-8")
    de = json.loads((ROOT / "ui" / "i18n" / "de.json").read_text(encoding="utf-8"))
    en = json.loads((ROOT / "ui" / "i18n" / "en.json").read_text(encoding="utf-8"))

    assert 'data-i18n="wizard.retentionExplanation"' in index
    assert 'data-i18n="wizard.retentionExample"' in index
    assert 'data-i18n="wizard.retentionAutomaticPrune"' in index
    assert 'id="wiz-retention-manual-link"' in index
    assert "github.com/borgforge/borg-backup-ui/blob/main/docs/user-manual/${language}" in script
    assert index.count('min="0" step="1" id="wiz-keep-') == 4

    assert "function _wizardRetentionValidationKey(params)" in script
    assert "if (step === 5)" in script
    assert "wizard.validationRetentionRequired" in script
    assert "wizard.previewRetention" in script
    assert "retention_all_zero" in script
    assert "wizardClearError(5)" in bindings

    assert "Zeiträume" in de["wizard"]["retentionExplanation"]
    assert "time periods" in en["wizard"]["retentionExplanation"]
    assert "größer als 0" in de["wizard"]["validationRetentionRequired"]
    assert "greater than 0" in en["wizard"]["validationRetentionRequired"]
    assert "max. 1/Tag" in de["storage"]["repositoryRetentionDaily"]
    assert "max. 1/day" in en["storage"]["repositoryRetentionDaily"]


def test_quick_help_and_manuals_use_the_same_retention_semantics() -> None:
    quick_de = (ROOT / "ui" / "docs" / "help.md").read_text(encoding="utf-8")
    quick_en = (ROOT / "ui" / "docs" / "help.en.md").read_text(encoding="utf-8")
    manual_de = (ROOT / "docs" / "user-manual" / "de" / "user-manual.md").read_text(encoding="utf-8")
    manual_en = (ROOT / "docs" / "user-manual" / "en" / "user-manual.md").read_text(encoding="utf-8")

    assert "Retention-Werte zählen Zeiträume" in quick_de
    assert "Retention values count periods" in quick_en
    assert "Backups um 08:00 und 08:30 Uhr" in manual_de
    assert "08:00 and 08:30" in manual_en
    assert "viermal `0` wird abgelehnt" in manual_de
    assert "four zero values is rejected" in manual_en
