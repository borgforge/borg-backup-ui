from __future__ import annotations

import re
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
    assert "PYTHONDONTWRITEBYTECODE=1" in script
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
    assert "Apprise runtime is unchanged, skipping extraction." in workflow
    assert "extracting Apprise runtime" in workflow
    assert "Apprise vendor bundle SHA256 does not match." in workflow


def test_apprise_vendor_dependencies_are_listed_in_license_notice() -> None:
    lock = (ROOT / "plugin" / "apprise-requirements.lock").read_text(encoding="utf-8")
    notice = (ROOT / "runtime" / "licenses" / "THIRD-PARTY-NOTICES.md").read_text(encoding="utf-8")

    pinned = re.findall(r"^([A-Za-z0-9_.-]+)==([0-9][^\s]+)", lock, re.MULTILINE)
    assert pinned
    for name, version in pinned:
        assert f"| {name} | {version} |" in notice

    apprise_license = ROOT / "runtime" / "licenses" / "apprise" / "LICENSE"
    assert apprise_license.is_file()
    assert "BSD 2-Clause License" in apprise_license.read_text(encoding="utf-8")


def test_project_mit_license_file_is_present() -> None:
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")

    assert license_text.startswith("MIT License\n")
    assert "Copyright (c) 2026 Thorsten Steinberg" in license_text
    assert 'THE SOFTWARE IS PROVIDED "AS IS"' in license_text
