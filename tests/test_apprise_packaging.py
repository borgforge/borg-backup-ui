from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_apprise_lock_is_hash_pinned() -> None:
    lock = ROOT / "plugin" / "apprise-requirements.lock"
    text = lock.read_text(encoding="utf-8")

    assert "apprise==1.12.0" in text
    assert "--hash=sha256:" in text
    for package in ("requests==", "PyYAML==", "certifi=="):
        assert package in text


def test_build_installs_apprise_into_runtime_vendor() -> None:
    script = (ROOT / "plugin" / "build.sh").read_text(encoding="utf-8")

    assert "apprise-requirements.lock" in script
    assert "runtime/vendor" in script
    assert "--require-hashes" in script
    assert "python3 -m pip install" in script


def test_release_preflight_requires_apprise_vendor_members() -> None:
    workflow = (ROOT / "plugin" / "release_workflow.py").read_text(encoding="utf-8")

    assert "runtime/vendor/apprise/__init__.py" in workflow
    assert "runtime/vendor/certifi/__init__.py" in workflow
