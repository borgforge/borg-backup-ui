import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]


def test_plugin_manifest_extracts_payload_when_upgradepkg_left_it_missing() -> None:
    manifest = (ROOT / "borg-backup-ui.plg").read_text(encoding="utf-8")

    assert 'PACKAGE_FILE="${PLUGIN_DIR}/borg-backup-ui-&version;.txz"' in manifest
    assert 'tar -xf "${PACKAGE_FILE}" -C /' in manifest
    assert 'ERROR: borg-backup-ui payload was not installed' in manifest


def test_plugin_manifest_is_valid_xml() -> None:
    ET.parse(ROOT / "borg-backup-ui.plg")


def test_plugin_manifest_uses_github_stable_channel_urls() -> None:
    manifest = (ROOT / "borg-backup-ui.plg").read_text(encoding="utf-8")

    assert 'https://raw.githubusercontent.com/borgforge/borg-backup-ui' in manifest
    assert '&github;/main/&name;.plg' in manifest
    assert '&github;/main/releases/&name;-&version;.txz' in manifest
    assert 'gitlab.thetwist.de' not in manifest


def test_test_channel_deploy_validates_manifest_and_package_payload() -> None:
    script = (ROOT / "plugin" / "deploy-test.sh").read_text(encoding="utf-8")

    assert "require_pkg_entry" in script
    assert 'require_pkg_entry "boot/config/plugins/${NAME}/borg_backup_ui.py"' in script
    assert 'require_pkg_entry "boot/config/plugins/${NAME}/api/config_api.py"' in script
    assert 'require_pkg_entry "boot/config/plugins/${NAME}/api/factory_reset_worker.py"' in script
    assert 'require_pkg_entry "boot/config/plugins/${NAME}/ui/index.html"' in script
    assert 'require_pkg_entry "boot/config/plugins/${NAME}/runtime/config/backup.conf.example"' in script
    assert 'require_pkg_entry "etc/rc.d/rc.borg_backup_ui"' in script
    assert "ET.parse(sys.argv[1])" in script
    assert 'launch="Settings/borg-backup-ui"' in script


def test_build_removes_stale_generated_packages() -> None:
    script = (ROOT / "plugin" / "build.sh").read_text(encoding="utf-8")

    assert 'find "${SCRIPT_DIR}/build"' in script
    assert '-name "${NAME}-*.txz" -delete' in script


def test_test_channel_publisher_replaces_snapshot_with_exact_lease(tmp_path: Path) -> None:
    publisher = ROOT / "plugin" / "publish-test-snapshot.sh"
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    work.mkdir()
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)

    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
        }
    )

    manifest = work / "borg-backup-ui-test.plg"
    first_package = work / "borg-backup-ui-1.txz"
    manifest.write_text("version=1\n", encoding="utf-8")
    first_package.write_bytes(b"first package")
    subprocess.run(
        [
            str(publisher),
            str(remote),
            "test-channel",
            str(manifest),
            str(first_package),
            "first snapshot",
            str(work),
        ],
        check=True,
        capture_output=True,
        env=env,
    )

    manifest.write_text("version=2\n", encoding="utf-8")
    second_package = work / "borg-backup-ui-2.txz"
    second_package.write_bytes(b"second package")
    subprocess.run(
        [
            str(publisher),
            str(remote),
            "test-channel",
            str(manifest),
            str(second_package),
            "second snapshot",
            str(work),
        ],
        check=True,
        capture_output=True,
        env=env,
    )

    files = subprocess.run(
        ["git", f"--git-dir={remote}", "ls-tree", "-r", "--name-only", "test-channel"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    history_count = subprocess.run(
        ["git", f"--git-dir={remote}", "rev-list", "--count", "test-channel"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    assert files == ["borg-backup-ui-test.plg", "releases/borg-backup-ui-2.txz"]
    assert history_count == "1"


def test_test_channel_publisher_uses_exact_force_with_lease() -> None:
    script = (ROOT / "plugin" / "publish-test-snapshot.sh").read_text(encoding="utf-8")

    assert '--force-with-lease="refs/heads/${TEST_BRANCH}:${REMOTE_HEAD}"' in script
    assert 'if [ "$TEST_BRANCH" != "test-channel" ]; then' in script


def test_release_promotion_copies_tested_settings_launch_target() -> None:
    script = (ROOT / "plugin" / "promote-release.sh").read_text(encoding="utf-8")

    assert "Test manifest does not define the tested Unraid launch target" in script
    assert "launch_target" in script
