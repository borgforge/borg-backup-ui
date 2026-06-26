from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]


def test_plugin_manifest_extracts_payload_when_upgradepkg_left_it_missing() -> None:
    manifest = (ROOT / "borg-backup-ui.plg").read_text(encoding="utf-8")

    assert 'PACKAGE_FILE="${PLUGIN_DIR}/borg-backup-ui-&version;.txz"' in manifest
    assert 'tar -xf "${PACKAGE_FILE}" -C /' in manifest
    assert 'ERROR: borg-backup-ui payload was not installed' in manifest


def test_plugin_manifest_is_valid_xml() -> None:
    ET.parse(ROOT / "borg-backup-ui.plg")


def test_test_channel_deploy_validates_manifest_and_package_payload() -> None:
    script = (ROOT / "plugin" / "deploy-test.sh").read_text(encoding="utf-8")

    assert "require_pkg_entry" in script
    assert 'require_pkg_entry "boot/config/plugins/${NAME}/borg_backup_ui.py"' in script
    assert 'require_pkg_entry "boot/config/plugins/${NAME}/api/config_api.py"' in script
    assert 'require_pkg_entry "boot/config/plugins/${NAME}/ui/index.html"' in script
    assert 'require_pkg_entry "boot/config/plugins/${NAME}/runtime/config/backup.conf.example"' in script
    assert 'require_pkg_entry "etc/rc.d/rc.borg_backup_ui"' in script
    assert "ET.parse(sys.argv[1])" in script
