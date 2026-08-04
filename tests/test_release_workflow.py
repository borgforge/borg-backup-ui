from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "release_workflow", ROOT / "plugin" / "release_workflow.py"
)
assert SPEC and SPEC.loader
release_workflow = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_workflow)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test User")
    (repo / "borg_backup_ui.py").write_text(
        'APP_VERSION = "1"\nVALUE = 1\n', encoding="utf-8"
    )
    (repo / "ui").mkdir()
    (repo / "ui" / "index.html").write_text("<html>one</html>\n", encoding="utf-8")
    (repo / "plugin").mkdir()
    (repo / "plugin" / "apprise-requirements.lock").write_text(
        "apprise==1.12.0 --hash=sha256:old\n", encoding="utf-8"
    )
    (repo / "README.md").write_text("not deployable\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "Initial source")
    return repo


def test_source_digest_ignores_version_but_tracks_deployable_source(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    initial = release_workflow.source_digest(repo, "HEAD")

    (repo / "borg_backup_ui.py").write_text(
        'APP_VERSION = "2"\nVALUE = 1\n', encoding="utf-8"
    )
    git(repo, "add", "borg_backup_ui.py")
    git(repo, "commit", "-m", "Version only")
    assert release_workflow.source_digest(repo, "HEAD") == initial

    (repo / "borg_backup_ui.py").write_text(
        'APP_VERSION = "2"\nVALUE = 2\n', encoding="utf-8"
    )
    git(repo, "add", "borg_backup_ui.py")
    git(repo, "commit", "-m", "Deployable change")
    assert release_workflow.source_digest(repo, "HEAD") != initial


def test_source_digest_tracks_apprise_lock_as_package_input(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    initial = release_workflow.source_digest(repo, "HEAD")

    (repo / "plugin" / "apprise-requirements.lock").write_text(
        "apprise==1.12.0 --hash=sha256:new\n", encoding="utf-8"
    )
    git(repo, "add", "plugin/apprise-requirements.lock")
    git(repo, "commit", "-m", "Update Apprise lock")

    assert release_workflow.source_digest(repo, "HEAD") != initial


def test_source_digest_tracks_project_license_as_package_input(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    initial = release_workflow.source_digest(repo, "HEAD")

    (repo / "LICENSE").write_text("MIT License\nchanged\n", encoding="utf-8")
    git(repo, "add", "LICENSE")
    git(repo, "commit", "-m", "Add license")

    assert release_workflow.source_digest(repo, "HEAD") != initial


def test_attestation_rejects_dirty_and_stale_source(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    release_workflow.write_attestation(repo, "HEAD")
    release_workflow.verify_attestation(repo)

    (repo / "ui" / "index.html").write_text("<html>dirty</html>\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Working tree is not clean"):
        release_workflow.verify_attestation(repo)

    git(repo, "restore", "ui/index.html")
    (repo / "ui" / "index.html").write_text("<html>new commit</html>\n", encoding="utf-8")
    git(repo, "add", "ui/index.html")
    git(repo, "commit", "-m", "New source")
    with pytest.raises(RuntimeError, match="stale"):
        release_workflow.verify_attestation(repo)


def test_implementation_delta_rejects_stable_artifacts_and_version_bump(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path)
    base = git(repo, "rev-parse", "HEAD")
    (repo / "borg_backup_ui.py").write_text(
        'APP_VERSION = "2"\nVALUE = 1\n', encoding="utf-8"
    )
    (repo / "borg-backup-ui.plg").write_text("stable\n", encoding="utf-8")
    (repo / "releases").mkdir()
    (repo / "releases" / "borg-backup-ui-2.txz").write_bytes(b"stable")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "Forbidden release artifacts")

    violations = release_workflow.implementation_delta_violations(repo, base)
    assert any("borg-backup-ui.plg" in item for item in violations)
    assert any("stable release packages" in item for item in violations)
    assert any("APP_VERSION changes" in item for item in violations)


def test_release_note_fragments_are_ordered_and_hashed(tmp_path: Path) -> None:
    root = tmp_path / "source"
    pending = root / "release-notes" / "pending"
    pending.mkdir(parents=True)
    (pending / "README.md").write_text("ignored\n", encoding="utf-8")
    (pending / "020-fix.md").write_text("Fix second\n", encoding="utf-8")
    (pending / "010-feature.md").write_text("- Add first\n", encoding="utf-8")

    notes, metadata, digest = release_workflow.rendered_release_notes(root)

    assert notes == "- Add first\n- Fix second"
    assert [item["path"] for item in metadata] == [
        "release-notes/pending/010-feature.md",
        "release-notes/pending/020-fix.md",
    ]
    assert len(digest) == 64


def test_package_installer_rewrite_adds_checksum_and_skip_logic() -> None:
    manifest = """<PLUGIN>
<FILE Name="&bootdir;/&name;-&version;.txz" Run="upgradepkg --install-new">
<URL>&pkgurl;</URL>
<MD5>00000000000000000000000000000000</MD5>
</FILE>
</PLUGIN>
"""

    rendered = release_workflow.rewrite_package_installer(
        manifest,
        "ABCDEF0123456789ABCDEF0123456789",
    )

    assert "borg-backup-ui package installer" in rendered
    assert 'EXPECTED_MD5="abcdef0123456789abcdef0123456789"' in rendered
    assert "vorhandenes Paket passt zur MD5" in rendered
    assert "Version ${VERSION} ist bereits installiert" in rendered
    assert "package_payload_present()" in rendered
    assert "extract_package_payload()" in rendered
    assert "Paket ist registriert, aber Plugin-Dateien fehlen; Payload wird erneut entpackt." in rendered
    assert "Paketmanager hat die Payload nicht vollstaendig entpackt; Payload wird direkt entpackt." in rendered
    assert "upgradepkg --install-new" in rendered
    assert "<MD5>" not in rendered


def test_manifest_md5_accepts_rendered_package_installer(tmp_path: Path) -> None:
    manifest = tmp_path / "borg-backup-ui-test.plg"
    manifest.write_text(
        release_workflow.rewrite_package_installer(
            """<PLUGIN>
<FILE Name="&bootdir;/&name;-&version;.txz" Run="upgradepkg --install-new">
<URL>&pkgurl;</URL>
<MD5>00000000000000000000000000000000</MD5>
</FILE>
</PLUGIN>
""",
            "abcdef0123456789abcdef0123456789",
        ),
        encoding="utf-8",
    )

    assert release_workflow.manifest_md5(manifest) == "abcdef0123456789abcdef0123456789"


def test_release_workflow_cli_reads_inline_installer_md5(tmp_path: Path) -> None:
    manifest = tmp_path / "borg-backup-ui-test.plg"
    manifest.write_text(
        release_workflow.rewrite_package_installer(
            """<PLUGIN>
<FILE Name="&bootdir;/&name;-&version;.txz" Run="upgradepkg --install-new">
<URL>&pkgurl;</URL>
<MD5>00000000000000000000000000000000</MD5>
</FILE>
</PLUGIN>
""",
            "abcdef0123456789abcdef0123456789",
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "plugin" / "release_workflow.py"),
            "manifest-md5",
            "--manifest",
            str(manifest),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == "abcdef0123456789abcdef0123456789"


def test_source_preflight_is_fail_fast_and_runs_pytest_once() -> None:
    script = (ROOT / "plugin" / "mr-preflight.sh").read_text(encoding="utf-8")

    assert script.count("pytest -q") == 1
    assert script.index("verify-implementation-delta") < script.index("pytest -q")
    assert script.index("status --porcelain") < script.index("pytest -q")
    assert script.index("ls-remote --heads") < script.index("pytest -q")
    assert script.index("write-attestation") > script.index("pytest -q")


def test_test_deploy_requires_attestation_and_exact_commit() -> None:
    script = (ROOT / "plugin" / "deploy-test.sh").read_text(encoding="utf-8")

    assert "verify-attestation" in script
    assert "rewrite-package-installer" in script
    assert 'git -C "$REPO_DIR" archive "$SOURCE_COMMIT"' in script
    assert 'REMOTE_SHA" != "$SOURCE_COMMIT' in script
    assert "pytest -q" not in script


def test_stable_promotion_reuses_exact_package_from_clean_current_main() -> None:
    script = (ROOT / "plugin" / "promote-release.sh").read_text(encoding="utf-8")

    assert 'CURRENT_BRANCH" != "$MAIN_BRANCH' in script
    assert "status --porcelain=v1 --untracked-files=all" in script
    assert 'LOCAL_SHA" != "$MAIN_SHA' in script
    assert 'cp "$TEST_PKG"' in script
    assert 'if [[ "$RELEASE_PACKAGE_SHA256" != "$TEST_PACKAGE_SHA256" ]]' in script
    assert "tested_package_install" in script
    assert "package_install_re.sub(lambda _match: package_install_replacement" in script
    assert "legacy_package_file_re.sub(lambda _match: package_install_replacement" in script
    assert "plugin/build.sh" not in script


def test_release_preflight_is_artifact_only() -> None:
    script = (ROOT / "plugin" / "release-preflight.sh").read_text(encoding="utf-8")

    assert "verify-release" in script
    assert "byte-identisch" in script
    assert "pytest -q" not in script
