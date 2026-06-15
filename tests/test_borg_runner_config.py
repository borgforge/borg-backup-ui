from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
RUNTIME_ROOT = ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from runtime.lib.borg_runner import BorgConfig


def test_retention_values_are_clamped_to_non_negative():
    cfg = BorgConfig.from_config(
        {
            "BORG_KEEP_DAILY": "-1",
            "BORG_KEEP_WEEKLY": "-2",
            "BORG_KEEP_MONTHLY": "-3",
            "BORG_KEEP_YEARLY": "-4",
            "BORG_MAX_RUNTIME_HOURS": "-99",
        }
    )
    assert cfg.keep_daily == 0
    assert cfg.keep_weekly == 0
    assert cfg.keep_monthly == 0
    assert cfg.keep_yearly == 0
    assert cfg.max_runtime_hours == 0
