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


def test_build_installs_apprise_and_packages_vendor_bundle() -> None:
    script = (ROOT / "plugin" / "build.sh").read_text(encoding="utf-8")

    assert "apprise-requirements.lock" in script
    assert "runtime/vendor" in script
    assert "runtime/vendor-bundles" in script
    assert "apprise-vendor.json" in script
    assert "apprise-${APPRISE_VENDOR_VERSION}-${bundle_sha}.tar.xz" in script
    assert "--exclude='./vendor'" in script
    assert "--sort=name" in script
    assert "sha256sum" in script
    assert "--require-hashes" in script
    assert "python3 -m pip install" in script


def test_release_preflight_requires_apprise_vendor_bundle() -> None:
    workflow = (ROOT / "plugin" / "release_workflow.py").read_text(encoding="utf-8")

    assert "runtime/vendor-bundles/apprise-vendor.json" in workflow
    assert "Package must contain exactly one Apprise vendor bundle" in workflow
    assert "Package must not contain expanded Apprise vendor files" in workflow
    assert "Apprise vendor bundle SHA256 does not match metadata" in workflow


def test_manifest_installer_extracts_apprise_vendor_only_when_changed() -> None:
    workflow = (ROOT / "plugin" / "release_workflow.py").read_text(encoding="utf-8")

    assert "ensure_apprise_vendor" in workflow
    assert ".apprise-vendor.json" in workflow
    assert "Apprise Runtime unveraendert, Extraktion wird uebersprungen." in workflow
    assert "extrahiere Apprise Runtime" in workflow
    assert "Apprise Vendor-Bundle SHA256 stimmt nicht." in workflow
