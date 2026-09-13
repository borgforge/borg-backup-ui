import subprocess
from pathlib import Path


def test_apprise_profiles_browser_logic():
    subprocess.run(["node", "tests/apprise_profiles_ui.cjs"],
                   cwd=Path(__file__).resolve().parents[1], check=True)
