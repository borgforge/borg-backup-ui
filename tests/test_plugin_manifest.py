from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_plugin_manifest_extracts_payload_when_upgradepkg_left_it_missing() -> None:
    manifest = (ROOT / "borg-backup-ui.plg").read_text(encoding="utf-8")

    assert 'PACKAGE_FILE="${PLUGIN_DIR}/borg-backup-ui-&version;.txz"' in manifest
    assert 'tar -xf "${PACKAGE_FILE}" -C /' in manifest
    assert 'ERROR: borg-backup-ui payload was not installed' in manifest
