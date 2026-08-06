from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import settings_transfer_api as transfer  # noqa: E402


pytestmark = pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl is not installed")

PASSWORD = "authenticated-export-password"


def _legacy_encrypt(plaintext: bytes, password: str) -> bytes:
    env = dict(os.environ)
    env["BBUI_SECRET_PASS"] = password
    proc = subprocess.run(
        [
            "openssl",
            "enc",
            "-aes-256-cbc",
            "-pbkdf2",
            "-salt",
            "-iter",
            "200000",
            "-pass",
            "env:BBUI_SECRET_PASS",
        ],
        input=plaintext,
        capture_output=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0
    return proc.stdout


def _tamper_ciphertext(encrypted: bytes) -> bytes:
    magic = transfer._AUTHENTICATED_EXPORT_MAGIC
    envelope = json.loads(encrypted[len(magic):].decode("utf-8"))
    ciphertext = bytearray(base64.b64decode(envelope["ciphertext_b64"], validate=True))
    ciphertext[-1] ^= 0x01
    envelope["ciphertext_b64"] = base64.b64encode(ciphertext).decode("ascii")
    return magic + transfer._canonical_json_bytes(envelope)


def _extract_inner_ciphertext(encrypted: bytes) -> bytes:
    magic = transfer._AUTHENTICATED_EXPORT_MAGIC
    envelope = json.loads(encrypted[len(magic):].decode("utf-8"))
    return base64.b64decode(envelope["ciphertext_b64"], validate=True)


def _secrets_payload() -> bytes:
    return json.dumps({
        "format": "bbui-secrets-backup-v1",
        "created_at": "2026-07-15T12:00:00Z",
        "files": [{
            "name": ".borg-passphrase-test",
            "content_b64": base64.b64encode(b"repository-secret\n").decode("ascii"),
            "mode": 0o600,
            "mtime": 0,
            "sha256": "",
        }],
    }).encode("utf-8")


def test_authenticated_export_round_trip_and_versioned_header():
    plaintext = b'{"secret":"not logged"}'

    encrypted = transfer._encrypt_authenticated_export(plaintext, PASSWORD)
    decrypted, encryption_format = transfer._decrypt_encrypted_export(encrypted, PASSWORD)
    envelope = json.loads(encrypted[len(transfer._AUTHENTICATED_EXPORT_MAGIC):].decode("utf-8"))

    assert encrypted.startswith(transfer._AUTHENTICATED_EXPORT_MAGIC)
    assert envelope["protected"]["format"] == "bbui-authenticated-export"
    assert envelope["protected"]["version"] == 2
    assert envelope["protected"]["cipher"]["name"] == "aes-256-cbc"
    assert envelope["protected"]["authentication"]["name"] == "hmac-sha256"
    assert decrypted == plaintext
    assert encryption_format == "authenticated-v2"


def test_wrong_password_is_rejected_without_exposing_password():
    encrypted = transfer._encrypt_authenticated_export(b"sensitive payload", PASSWORD)
    wrong_password = "wrong-password-value"

    with pytest.raises(ValueError) as exc_info:
        transfer._decrypt_encrypted_export(encrypted, wrong_password)

    assert "authentication failed" in str(exc_info.value).lower()
    assert exc_info.value.api_code == "encrypted_export_authentication_failed"
    assert wrong_password not in str(exc_info.value)
    assert PASSWORD not in str(exc_info.value)


def test_tampered_ciphertext_is_rejected_before_decryption():
    encrypted = transfer._encrypt_authenticated_export(b"sensitive payload", PASSWORD)

    with pytest.raises(ValueError, match="authentication failed") as exc_info:
        transfer._decrypt_encrypted_export(_tamper_ciphertext(encrypted), PASSWORD)

    assert exc_info.value.api_code == "encrypted_export_authentication_failed"


def test_truncated_export_is_rejected_with_clear_error():
    encrypted = transfer._encrypt_authenticated_export(b"sensitive payload", PASSWORD)

    with pytest.raises(ValueError, match="invalid or truncated") as exc_info:
        transfer._decrypt_encrypted_export(encrypted[:-11], PASSWORD)

    assert exc_info.value.api_code == "encrypted_export_invalid"


def test_unsupported_export_format_has_actionable_error_code():
    with pytest.raises(ValueError, match="Unsupported encrypted export format") as exc_info:
        transfer._decrypt_encrypted_export(b"unknown encrypted format", PASSWORD)

    assert exc_info.value.api_code == "encrypted_export_unsupported"


def test_legacy_openssl_export_remains_explicitly_importable():
    plaintext = _secrets_payload()
    legacy = _legacy_encrypt(plaintext, PASSWORD)

    decrypted, encryption_format = transfer._decrypt_encrypted_export(legacy, PASSWORD)

    assert legacy.startswith(b"Salted__")
    assert decrypted == plaintext
    assert encryption_format == "legacy-openssl-aes-256-cbc"


def test_authenticated_ciphertext_cannot_be_downgraded_to_legacy_import(tmp_path: Path, monkeypatch):
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    monkeypatch.setattr(transfer, "_secrets_dir", lambda: secrets_dir)
    encrypted = transfer._encrypt_authenticated_export(_secrets_payload(), PASSWORD)
    stripped_envelope_b64 = base64.b64encode(_extract_inner_ciphertext(encrypted)).decode("ascii")

    with pytest.raises(ValueError, match="payload is invalid"):
        transfer.import_secrets_backup(PASSWORD, stripped_envelope_b64, mode="overwrite")

    assert list(secrets_dir.rglob("*")) == []


def test_legacy_preview_is_marked_and_new_export_uses_authenticated_format(tmp_path: Path, monkeypatch):
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    monkeypatch.setattr(transfer, "_secrets_dir", lambda: secrets_dir)
    legacy_b64 = base64.b64encode(_legacy_encrypt(_secrets_payload(), PASSWORD)).decode("ascii")

    preview = transfer.preview_secrets_backup(PASSWORD, legacy_b64)
    exported = transfer.export_secrets_backup(PASSWORD)
    exported_raw = base64.b64decode(exported["payload_b64"], validate=True)

    assert preview["legacy_encryption"] is True
    assert preview["encryption_format"] == "legacy-openssl-aes-256-cbc"
    assert exported_raw.startswith(transfer._AUTHENTICATED_EXPORT_MAGIC)
    assert not exported_raw.startswith(b"Salted__")


def test_every_secret_bearing_export_entry_point_uses_authenticated_format(tmp_path: Path, monkeypatch):
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    monkeypatch.setattr(transfer, "_secrets_dir", lambda: secrets_dir)
    monkeypatch.setattr(transfer, "export_jobs_bundle", lambda config, selected_keys=None: {
        "bundle": {"format": "bbui-job-bundle-v2", "jobs": []},
        "job_count": 0,
    })
    monkeypatch.setattr(transfer, "_collect_job_passphrase_files", lambda bundle: {})
    monkeypatch.setattr(transfer, "_collect_job_key_files", lambda config, bundle, include_content: {})
    monkeypatch.setattr(transfer, "_collect_repository_key_exports", lambda config, bundle: {})
    monkeypatch.setattr(transfer, "_canonical_profile_payload", lambda config: {
        "smb_profiles": [],
        "storage_profiles": [],
    })
    monkeypatch.setattr(transfer, "_collect_profile_secrets", lambda settings_payload: [])

    exports = [
        transfer.export_secrets_backup(PASSWORD),
        transfer.export_jobs_bundle_encrypted({}, PASSWORD),
        transfer.export_profile_secrets_backup({}, PASSWORD),
    ]

    for exported in exports:
        raw = base64.b64decode(exported["payload_b64"], validate=True)
        assert raw.startswith(transfer._AUTHENTICATED_EXPORT_MAGIC)


def test_tampered_import_does_not_write_any_secret_file(tmp_path: Path, monkeypatch):
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    monkeypatch.setattr(transfer, "_secrets_dir", lambda: secrets_dir)
    encrypted = transfer._encrypt_authenticated_export(_secrets_payload(), PASSWORD)
    tampered_b64 = base64.b64encode(_tamper_ciphertext(encrypted)).decode("ascii")

    with pytest.raises(ValueError, match="authentication failed"):
        transfer.import_secrets_backup(PASSWORD, tampered_b64, mode="overwrite")

    assert list(secrets_dir.rglob("*")) == []


def test_invalid_transport_base64_is_rejected_without_writes(tmp_path: Path, monkeypatch):
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    monkeypatch.setattr(transfer, "_secrets_dir", lambda: secrets_dir)

    with pytest.raises(ValueError, match="invalid or truncated"):
        transfer.import_secrets_backup(PASSWORD, "not valid base64!", mode="overwrite")

    assert list(secrets_dir.rglob("*")) == []


def test_server_preserves_safe_encrypted_export_error_codes():
    source = (ROOT / "borg_backup_ui.py").read_text(encoding="utf-8")

    assert 'getattr(exc, "api_code", "") or "bad_request"' in source


def test_failed_preview_invalidates_previously_loaded_sensitive_state():
    source = (ROOT / "ui" / "js" / "pages" / "settings.js").read_text(encoding="utf-8")
    cases = [
        (
            "async function importJobsSecurePreviewSelectFile()",
            "async function importJobsApplySelected",
            "clearJobsImportPreview();",
            "fetch('/api/settings/jobs-import-secure-preview'",
        ),
        (
            "async function importSecretsPreviewSelectFile()",
            "async function importSecretsApplySelected()",
            "clearSecretsImportPreview();",
            "fetch('/api/settings/secrets-backup-preview'",
        ),
        (
            "async function importProfileSecretsPreviewSelectFile()",
            "async function importProfileSecretsApplySelected",
            "clearProfileSecretsImportPreview();",
            "fetch('/api/settings/profile-secrets-preview'",
        ),
    ]

    for start_marker, end_marker, clear_call, fetch_call in cases:
        block = source[source.index(start_marker):source.index(end_marker)]
        assert block.index(clear_call) < block.index(fetch_call)

    assert "settingsState.transferProfileSecretsPreview = null;" in source
    assert "settingsState.transferProfileSecretsPayloadB64 = '';" in source
    assert "settingsState.transferProfileSecretsPassword = '';" in source
    assert "previewEl.replaceChildren();" in source


def test_secure_jobs_import_uses_guided_per_job_selection():
    source = (ROOT / "ui" / "js" / "pages" / "settings.js").read_text(encoding="utf-8")
    de = json.loads((ROOT / "ui" / "i18n" / "de.json").read_text(encoding="utf-8"))
    en = json.loads((ROOT / "ui" / "i18n" / "en.json").read_text(encoding="utf-8"))

    assert "async function settingsTransferRunSecureJobsWizard" in source
    assert "renderSettingsTransferJobSelectionStep" in source
    assert "renderSettingsTransferActionStep" in source
    assert "renderSettingsTransferConfirmStep" in source
    assert "data-jobs-secure-row-select" in source
    assert "data-jobs-secure-row-mode" in source
    assert "jobImportCreateNew" in source

    for catalog in (de, en):
        transfer_labels = catalog["settings"]["transfer"]
        assert transfer_labels["importStepSelectTitle"]
        assert transfer_labels["importStepActionTitle"]
        assert transfer_labels["importStepConfirmTitle"]
        assert transfer_labels["selectedJobsCount"]
        assert transfer_labels["importScopeAllHelp"]
        assert transfer_labels["passphraseIncluded"]
