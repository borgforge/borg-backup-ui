import os
import importlib.util
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]


def load_release_workflow_module():
    module_path = ROOT / "plugin" / "release_workflow.py"
    spec = importlib.util.spec_from_file_location("release_workflow", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def test_community_apps_metadata_describes_private_python() -> None:
    plugin = ROOT / "plugins" / "borg-backup-ui.xml"
    profile = ROOT / "ca_profile.xml"

    ET.parse(plugin)
    ET.parse(profile)

    plugin_text = plugin.read_text(encoding="utf-8")
    profile_text = profile.read_text(encoding="utf-8")
    assert "Python 3 for UNRAID" in plugin_text
    assert "Includes a private Python runtime" in plugin_text
    assert "Python 3 for UNRAID" in profile_text
    assert "include private Python" in profile_text


def test_community_apps_metadata_supports_unraid_6_12_5() -> None:
    plugin = ROOT / "plugins" / "borg-backup-ui.xml"

    plugin_root = ET.parse(plugin).getroot()

    assert plugin_root.findtext("MinVer") == "6.12.5"


def test_community_apps_metadata_uses_unraid_forum_support_thread() -> None:
    plugin = ROOT / "plugins" / "borg-backup-ui.xml"
    profile = ROOT / "ca_profile.xml"
    forum_url = (
        "https://forums.unraid.net/topic/198728-plugin-borg-backup-ui-web-ui-for-borg-backup-on-unraid/"
    )

    plugin_root = ET.parse(plugin).getroot()
    profile_root = ET.parse(profile).getroot()

    assert plugin_root.findtext("Support") == forum_url
    assert profile_root.findtext("Forum") == forum_url
    assert forum_url in profile.read_text(encoding="utf-8")
    assert "https://github.com/borgforge/borg-backup-ui/issues" in profile.read_text(encoding="utf-8")


def test_test_channel_deploy_validates_manifest_and_package_payload() -> None:
    script = (ROOT / "plugin" / "deploy-test.sh").read_text(encoding="utf-8")
    workflow = (ROOT / "plugin" / "release_workflow.py").read_text(encoding="utf-8")
    build = (ROOT / "plugin" / "build.sh").read_text(encoding="utf-8")

    assert 'ci_release.py" dispatch-test' in script
    assert 'f"boot/config/plugins/{NAME}/borg_backup_ui.py"' in workflow
    assert 'f"boot/config/plugins/{NAME}/LICENSE"' in workflow
    assert 'f"boot/config/plugins/{NAME}/api/apprise_profiles_api.py"' in workflow
    assert 'f"boot/config/plugins/{NAME}/api/config_api.py"' in workflow
    assert 'f"boot/config/plugins/{NAME}/api/factory_reset_worker.py"' in workflow
    assert 'f"boot/config/plugins/{NAME}/ui/index.html"' in workflow
    assert 'f"boot/config/plugins/{NAME}/runtime/config/backup.conf.example"' in workflow
    assert 'f"boot/config/plugins/{NAME}/runtime/vendor-bundles/apprise-vendor.json"' in workflow
    assert 'f"usr/local/emhttp/plugins/{NAME}/README.md"' in workflow
    assert 'f"usr/local/emhttp/plugins/{NAME}/{NAME}-dashboard.page"' in workflow
    assert 'f"usr/local/emhttp/plugins/{NAME}/widget-status.php"' in workflow
    assert 'f"usr/local/emhttp/plugins/{NAME}/app-icon.png"' in workflow
    assert '"etc/rc.d/rc.borg_backup_ui"' in workflow
    assert '"plugin/borg-backup-ui-dashboard.page"' in workflow
    assert '"plugin/widget-status.php"' in workflow
    pipeline = (ROOT / "plugin/ci_pipeline.py").read_text()
    assert "verify_candidate" in pipeline
    assert "Borg Backup UI" in pipeline
    assert '"${SCRIPT_DIR}/README.md"' in build


def test_build_removes_stale_generated_packages() -> None:
    script = (ROOT / "plugin" / "build.sh").read_text(encoding="utf-8")

    assert 'find "${BUILD_OUTPUT_DIR}"' in script
    assert '-name "${NAME}-*.txz" -delete' in script


def test_test_channel_publisher_replaces_snapshot_with_exact_lease(tmp_path: Path) -> None:
    publisher = ROOT / "plugin" / "publish-test-snapshot.sh"
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    work.mkdir()
    # Exercise the real publisher in an isolated ordinary checkout. The source
    # checkout may legitimately have an active private advisory guard.
    subprocess.run(["git", "init", "-b", "main", str(work)], check=True, capture_output=True)
    (work / "plugin").mkdir()
    for name in ("publish-test-snapshot.sh", "security_workflow.py", "release_workflow.py"):
        target = work / "plugin" / name
        target.write_bytes((ROOT / "plugin" / name).read_bytes())
        target.chmod(0o755)
    publisher = work / "plugin" / "publish-test-snapshot.sh"
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

    tools = work / "tools"
    tools.mkdir()
    (tools / "gh").write_text("#!/bin/sh\necho borg-codex-bot\n")
    (tools / "gh").chmod(0o755)
    env.update({"PATH": str(tools) + os.pathsep + env["PATH"],
                "GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch",
                "GITHUB_REF": "refs/heads/main", "BBUI_ENVIRONMENT": "testing",
                "GITHUB_WORKFLOW_REF": "borgforge/borg-backup-ui/.github/workflows/testing-release.yml@refs/heads/main",
                "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": f"url.{remote}.insteadOf",
                "GIT_CONFIG_VALUE_0": "https://github.com/borgforge/borg-backup-ui.git"})

    manifest = work / "borg-backup-ui-test.plg"
    first_package = work / "borg-backup-ui-2026.11.02.1200.txz"
    manifest.write_text('<PLUGIN version="2026.11.02.1200"/>', encoding="utf-8")
    first_package.write_bytes(b"first package")
    subprocess.run(
        [
            str(publisher),
            "https://github.com/borgforge/borg-backup-ui.git",
            "test-channel",
            str(manifest),
            str(first_package),
            "first snapshot",
            str(work),
            "test-candidates/2026.11.02.1200",
        ],
        check=True,
        capture_output=True,
        env=env,
    )

    manifest.write_text('<PLUGIN version="2026.11.02.1300"/>', encoding="utf-8")
    second_package = work / "borg-backup-ui-2026.11.02.1300.txz"
    second_package.write_bytes(b"second package")
    subprocess.run(
        [
            str(publisher),
            "https://github.com/borgforge/borg-backup-ui.git",
            "test-channel",
            str(manifest),
            str(second_package),
            "second snapshot",
            str(work),
            "test-candidates/2026.11.02.1300",
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

    assert files == ["borg-backup-ui-test.plg", "releases/borg-backup-ui-2026.11.02.1300.txz"]
    assert history_count == "1"

    def remote_git(*args):
        return subprocess.check_output(["git", f"--git-dir={remote}", *args], text=True).strip()
    assert remote_git("rev-parse", "test-channel") == remote_git("rev-parse", "refs/tags/test-candidates/2026.11.02.1300")
    assert remote_git("show", "refs/tags/test-candidates/2026.11.02.1200:releases/borg-backup-ui-2026.11.02.1200.txz") == "first package"
    command = [str(publisher), "https://github.com/borgforge/borg-backup-ui.git", "test-channel",
               str(manifest), str(second_package), "retry snapshot", str(work), "test-candidates/2026.11.02.1300"]
    previous = remote_git("rev-parse", "test-channel")
    subprocess.run(command, env=env, check=True, capture_output=True)
    assert remote_git("rev-parse", "test-channel") == previous
    second_package.write_bytes(b"changed bytes")
    assert subprocess.run(command, env=env, capture_output=True).returncode != 0
    assert remote_git("rev-parse", "test-channel") == previous
    command[4] = str(first_package)
    command[-1] = "test-candidates/2026.11.02.1200"
    assert subprocess.run(command, env=env, capture_output=True).returncode != 0
    assert remote_git("rev-parse", "test-channel") == previous


def test_test_channel_publisher_uses_exact_force_with_lease() -> None:
    script = (ROOT / "plugin" / "publish-test-snapshot.sh").read_text(encoding="utf-8")

    assert '--force-with-lease="refs/heads/${TEST_BRANCH}:${REMOTE_HEAD}"' in script
    assert 'if [ "$TEST_BRANCH" != "test-channel" ]; then' in script


def test_release_promotion_copies_tested_display_title_and_settings_launch_target() -> None:
    script = (ROOT / "plugin" / "release_workflow.py").read_text(encoding="utf-8")

    assert "Test manifest has no tested display title" in script
    assert "display_title" in script
    assert "Test manifest has no tested launch target" in script
    assert "launch_target" in script


def test_release_workflow_generates_safe_uninstall_payload_cleanup() -> None:
    workflow = load_release_workflow_module()
    manifest = (ROOT / "borg-backup-ui.plg").read_text(encoding="utf-8")
    rewritten = workflow.rewrite_remove_handler(manifest)
    ET.fromstring(rewritten)

    assert 'Method="remove"' in rewritten
    assert 'PLUGIN_DIR="/boot/config/plugins/${NAME}"' in rewritten
    assert 'EMHTTP_DIR="/usr/local/emhttp/plugins/${NAME}"' in rewritten
    assert 'RC_SCRIPT="/etc/rc.d/rc.borg_backup_ui"' in rewritten
    assert 'rm -rf "${PLUGIN_DIR}"' in rewritten
    assert 'rm -rf "${EMHTTP_DIR}"' in rewritten
    assert 'rm -f "${RC_SCRIPT}"' in rewritten
    assert 'rm -f "${PIDFILE}" "${WAIT_PIDFILE}" "${LOGFILE}" "${CLIENT_LOGFILE}"' in rewritten
    assert 'if [ "${PLUGIN_DIR}" = "/boot/config/plugins/${NAME}" ]; then' in rewritten
    assert "User data outside this" in rewritten
    assert "Borg repositories, jobs, histories, and configured data paths are" in rewritten


def test_release_promotion_copies_tested_remove_handler() -> None:
    script = (ROOT / "plugin" / "release_workflow.py").read_text(encoding="utf-8")

    assert "remove_handler_re" in script
    assert "Test manifest has no remove handler block" in script
    assert "Stable manifest has no remove handler block to replace" in script
    assert "tested_remove_handler.group(0)" in script


def test_rc_script_selects_private_fallback_without_boot_order_wait() -> None:
    script = (ROOT / "plugin/rc.borg_backup_ui").read_text()
    assert 'bash "$PYTHON_LAUNCHER" --select' in script
    assert 'defer_start_until_python_ready' not in script
    assert 'PYTHON_WAIT_SECONDS' not in script
    # Older deferred processes are still stopped during an upgrade.
    assert 'Borg Backup UI wait process stopped' in script
