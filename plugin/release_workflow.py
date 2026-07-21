#!/usr/bin/env python3
"""Shared verification helpers for test-channel and stable releases."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path


NAME = "borg-backup-ui"
PROVENANCE_NAME = "build-provenance.json"
PROVENANCE_MEMBER = f"boot/config/plugins/{NAME}/{PROVENANCE_NAME}"
EXPECTED_PACKAGE_MEMBERS = (
    f"boot/config/plugins/{NAME}/borg_backup_ui.py",
    f"boot/config/plugins/{NAME}/api/apprise_profiles_api.py",
    f"boot/config/plugins/{NAME}/api/config_api.py",
    f"boot/config/plugins/{NAME}/api/factory_reset_worker.py",
    f"boot/config/plugins/{NAME}/ui/index.html",
    f"boot/config/plugins/{NAME}/runtime/config/backup.conf.example",
    f"boot/config/plugins/{NAME}/runtime/vendor-bundles/apprise-vendor.json",
    "etc/rc.d/rc.borg_backup_ui",
    PROVENANCE_MEMBER,
)

PACKAGE_INSTALL_BEGIN = "<!-- BEGIN borg-backup-ui package installer -->"
PACKAGE_INSTALL_END = "<!-- END borg-backup-ui package installer -->"
PACKAGE_INSTALL_BLOCK_RE = re.compile(
    rf"{re.escape(PACKAGE_INSTALL_BEGIN)}.*?{re.escape(PACKAGE_INSTALL_END)}",
    re.DOTALL,
)
LEGACY_PACKAGE_FILE_RE = re.compile(
    r'<FILE Name="&bootdir;/&name;-&version;\.txz" Run="upgradepkg --install-new">\s*'
    r"<URL>&pkgurl;</URL>\s*"
    r"<MD5>[^<]*</MD5>\s*"
    r"</FILE>",
    re.DOTALL,
)


def run_git(repo: Path, *args: str, text: bool = True) -> str | bytes:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=text,
    )
    return result.stdout


def git_path(repo: Path, relative: str) -> Path:
    value = str(run_git(repo, "rev-parse", "--git-path", relative)).strip()
    path = Path(value)
    return path if path.is_absolute() else repo / path


def is_deployable_path(path: str) -> bool:
    if path in {"borg_backup_ui.py", "borg_backup_ui.conf.example"}:
        return True
    if path.startswith(("api/", "ui/", "runtime/", "docs/user-manual/")):
        return True
    if path in {
        "plugin/apprise-requirements.lock",
        "plugin/build.sh",
        "plugin/borg-backup-ui.page",
        "plugin/rc.borg_backup_ui",
        "plugin/plugin-icon.png",
        "plugin/plugin-icon-dark.png",
        "plugin/plugin-icon-light.png",
    }:
        return True
    return False


def normalized_source(path: str, data: bytes) -> bytes:
    if path == "borg_backup_ui.py":
        text = data.decode("utf-8")
        text = re.sub(
            r'^APP_VERSION\s*=\s*"[^"]*"',
            'APP_VERSION = "<release-version>"',
            text,
            count=1,
            flags=re.MULTILINE,
        )
        return text.encode("utf-8")
    return data


def source_digest(repo: Path, revision: str) -> str:
    paths = str(run_git(repo, "ls-tree", "-r", "--name-only", revision)).splitlines()
    digest = hashlib.sha256()
    selected = [path for path in paths if is_deployable_path(path)]
    if not selected:
        raise RuntimeError(f"No deployable source files found at {revision}")
    for path in sorted(selected):
        data = run_git(repo, "show", f"{revision}:{path}", text=False)
        assert isinstance(data, bytes)
        data = normalized_source(path, data)
        encoded_path = path.encode("utf-8")
        digest.update(len(encoded_path).to_bytes(4, "big"))
        digest.update(encoded_path)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def require_clean(repo: Path) -> None:
    status = str(run_git(repo, "status", "--porcelain=v1", "--untracked-files=all"))
    if status.strip():
        raise RuntimeError("Working tree is not clean; commit or remove all changes first")


def implementation_delta_violations(repo: Path, base_ref: str) -> list[str]:
    paths = str(run_git(repo, "diff", "--name-only", f"{base_ref}...HEAD")).splitlines()
    violations: list[str] = []
    if "borg-backup-ui.plg" in paths:
        violations.append("borg-backup-ui.plg belongs only in a dedicated stable release PR")
    if any(path.startswith("releases/borg-backup-ui-") and path.endswith(".txz") for path in paths):
        violations.append("stable release packages belong only in a dedicated stable release PR")
    if "borg_backup_ui.py" in paths:
        base = run_git(repo, "show", f"{base_ref}:borg_backup_ui.py")
        head = run_git(repo, "show", "HEAD:borg_backup_ui.py")
        version_pattern = re.compile(r'^APP_VERSION\s*=\s*"([^"]*)"', re.MULTILINE)
        base_match = version_pattern.search(str(base))
        head_match = version_pattern.search(str(head))
        if not base_match or not head_match:
            violations.append("APP_VERSION declaration could not be verified")
        elif base_match.group(1) != head_match.group(1):
            violations.append("APP_VERSION changes belong only in a dedicated stable release PR")
    return violations


def verify_implementation_delta(repo: Path, base_ref: str) -> None:
    violations = implementation_delta_violations(repo, base_ref)
    if violations:
        raise RuntimeError("; ".join(violations))


def attestation_path(repo: Path) -> Path:
    return git_path(repo, "borg-backup-ui/preflight.json")


def write_attestation(repo: Path, base_ref: str) -> dict[str, object]:
    require_clean(repo)
    head = str(run_git(repo, "rev-parse", "HEAD")).strip()
    base_sha = str(run_git(repo, "rev-parse", base_ref)).strip()
    branch = str(run_git(repo, "branch", "--show-current")).strip()
    payload: dict[str, object] = {
        "schema_version": 1,
        "result": "passed",
        "head_sha": head,
        "base_ref": base_ref,
        "base_sha": base_sha,
        "branch": branch,
        "source_digest": source_digest(repo, head),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    path = attestation_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    return payload


def verify_attestation(repo: Path) -> dict[str, object]:
    require_clean(repo)
    path = attestation_path(repo)
    if not path.is_file():
        raise RuntimeError("No preflight attestation found; run ./plugin/mr-preflight.sh")
    payload = json.loads(path.read_text(encoding="utf-8"))
    head = str(run_git(repo, "rev-parse", "HEAD")).strip()
    branch = str(run_git(repo, "branch", "--show-current")).strip()
    base_ref = str(payload.get("base_ref", ""))
    if not base_ref:
        raise RuntimeError("Preflight attestation has no base reference; rerun mr-preflight")
    expected = {
        "result": "passed",
        "head_sha": head,
        "branch": branch,
        "base_sha": str(run_git(repo, "rev-parse", base_ref)).strip(),
        "source_digest": source_digest(repo, head),
    }
    mismatches = [
        key for key, value in expected.items() if str(payload.get(key, "")) != str(value)
    ]
    if mismatches:
        raise RuntimeError(
            "Preflight attestation is stale (" + ", ".join(mismatches) + "); rerun mr-preflight"
        )
    return payload


def pending_fragments(root: Path) -> list[Path]:
    directory = root / "release-notes" / "pending"
    if not directory.is_dir():
        return []
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and not path.name.startswith(".") and path.name.lower() != "readme.md"
    )


def rendered_release_notes(root: Path) -> tuple[str, list[dict[str, str]], str]:
    rendered: list[str] = []
    metadata: list[dict[str, str]] = []
    for path in pending_fragments(root):
        data = path.read_bytes()
        text = data.decode("utf-8").strip()
        if not text:
            continue
        for line in text.splitlines():
            clean = line.strip()
            if clean:
                rendered.append(clean if clean.startswith("-") else f"- {clean}")
        metadata.append(
            {
                "path": str(path.relative_to(root)),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    if not rendered:
        rendered = ["- Internal maintenance changes only; no user-facing release note."]
    notes = "\n".join(rendered)
    return notes, metadata, hashlib.sha256(notes.encode("utf-8")).hexdigest()


def replace_changelog_block(manifest: str, version: str, notes: str) -> str:
    manifest = re.sub(
        rf"###{re.escape(version)}###\n(?:.*?)(?=\n###|\n\]\]>|\Z)",
        "",
        manifest,
        flags=re.DOTALL,
    )
    block = f"###{version}###\n{notes}\n\n"
    if "<![CDATA[\n" not in manifest:
        raise RuntimeError("Plugin manifest has no changelog CDATA section")
    return manifest.replace("<![CDATA[\n", "<![CDATA[\n" + block, 1)


def package_install_block(md5: str) -> str:
    md5 = str(md5 or "").strip()
    if not re.fullmatch(r"[0-9a-fA-F]{32}", md5):
        raise RuntimeError("Package MD5 must be a 32 character hexadecimal digest")
    return f"""{PACKAGE_INSTALL_BEGIN}
<FILE Name="/tmp/borg-backup-ui-package-install.sh" Run="/bin/bash">
<INLINE>
#!/bin/bash
set -e

NAME="borg-backup-ui"
VERSION="&version;"
PLUGIN_DIR="/boot/config/plugins/${{NAME}}"
PACKAGE_FILE="${{PLUGIN_DIR}}/${{NAME}}-${{VERSION}}.txz"
PACKAGE_TMP="${{PACKAGE_FILE}}.tmp"
PACKAGE_URL="&pkgurl;"
EXPECTED_MD5="{md5.lower()}"
INSTALLED_MD5_FILE="${{PLUGIN_DIR}}/.installed-package-md5"
VENDOR_DIR="${{PLUGIN_DIR}}/runtime/vendor"
VENDOR_BUNDLE_DIR="${{PLUGIN_DIR}}/runtime/vendor-bundles"
VENDOR_META="${{VENDOR_BUNDLE_DIR}}/apprise-vendor.json"
VENDOR_MARKER="${{VENDOR_DIR}}/.apprise-vendor.json"
VENDOR_TMP="${{PLUGIN_DIR}}/runtime/vendor.tmp.$$"

file_md5() {{
  if command -v md5sum >/dev/null 2>/dev/null; then
    md5sum "$1" | awk '{{print $1}}'
  else
    md5 -q "$1"
  fi
}}

file_sha256() {{
  if command -v sha256sum >/dev/null 2>/dev/null; then
    sha256sum "$1" | awk '{{print $1}}'
  else
    shasum -a 256 "$1" | awk '{{print $1}}'
  fi
}}

json_value() {{
  _json_file="$1"
  _json_key="$2"
  sed -n 's/^[[:space:]]*"'"${{_json_key}}"'"[[:space:]]*:[[:space:]]*"\\([^"]*\\)".*/\\1/p' "${{_json_file}}" | head -n 1
}}

package_registered() {{
  for _package_log in "/var/log/packages/${{NAME}}-${{VERSION}}"*; do
    if [ -e "${{_package_log}}" ]; then
      return 0
    fi
  done
  return 1
}}

core_payload_present() {{
  [ -f "${{PLUGIN_DIR}}/borg_backup_ui.py" ] || return 1
  [ -f "/etc/rc.d/rc.borg_backup_ui" ] || return 1
  return 0
}}

vendor_ready() {{
  [ -f "${{VENDOR_META}}" ] || return 1
  [ -f "${{VENDOR_MARKER}}" ] || return 1
  [ -f "${{VENDOR_DIR}}/apprise/__init__.py" ] || return 1
  expected_version="$(json_value "${{VENDOR_META}}" version)"
  expected_sha="$(json_value "${{VENDOR_META}}" sha256)"
  marker_version="$(json_value "${{VENDOR_MARKER}}" version)"
  marker_sha="$(json_value "${{VENDOR_MARKER}}" sha256)"
  [ -n "${{expected_version}}" ] || return 1
  [ -n "${{expected_sha}}" ] || return 1
  [ "${{expected_version}}" = "${{marker_version}}" ] || return 1
  [ "${{expected_sha}}" = "${{marker_sha}}" ] || return 1
  return 0
}}

ensure_apprise_vendor() {{
  if vendor_ready; then
    echo "Borg Backup UI: Apprise Runtime unveraendert, Extraktion wird uebersprungen."
    return 0
  fi

  if [ ! -f "${{VENDOR_META}}" ]; then
    echo "ERROR: Apprise Vendor-Metadaten fehlen: ${{VENDOR_META}}"
    return 1
  fi

  bundle_name="$(json_value "${{VENDOR_META}}" bundle)"
  expected_sha="$(json_value "${{VENDOR_META}}" sha256)"
  expected_version="$(json_value "${{VENDOR_META}}" version)"
  if [ -z "${{bundle_name}}" ] || [ -z "${{expected_sha}}" ] || [ -z "${{expected_version}}" ]; then
    echo "ERROR: Apprise Vendor-Metadaten sind unvollstaendig."
    return 1
  fi

  bundle_path="${{VENDOR_BUNDLE_DIR}}/${{bundle_name}}"
  if [ ! -f "${{bundle_path}}" ]; then
    echo "ERROR: Apprise Vendor-Bundle fehlt: ${{bundle_path}}"
    return 1
  fi

  actual_sha="$(file_sha256 "${{bundle_path}}")"
  if [ "${{actual_sha}}" != "${{expected_sha}}" ]; then
    echo "ERROR: Apprise Vendor-Bundle SHA256 stimmt nicht."
    echo "  erwartet: ${{expected_sha}}"
    echo "  erhalten : ${{actual_sha}}"
    return 1
  fi

  echo "Borg Backup UI: extrahiere Apprise Runtime ${{expected_version}} einmalig..."
  rm -rf "${{VENDOR_TMP}}" 2>/dev/null || true
  mkdir -p "${{VENDOR_TMP}}"
  tar -xf "${{bundle_path}}" -C "${{VENDOR_TMP}}"
  if [ ! -f "${{VENDOR_TMP}}/apprise/__init__.py" ]; then
    echo "ERROR: Apprise Vendor-Bundle enthaelt keine lauffaehige Runtime."
    rm -rf "${{VENDOR_TMP}}" 2>/dev/null || true
    return 1
  fi
  rm -rf "${{VENDOR_DIR}}" 2>/dev/null || true
  mv "${{VENDOR_TMP}}" "${{VENDOR_DIR}}"
  cp "${{VENDOR_META}}" "${{VENDOR_MARKER}}"
}}

download_package() {{
  echo "Borg Backup UI: lade Paket ${{VERSION}} herunter..."
  rm -f "${{PACKAGE_TMP}}"
  if command -v curl >/dev/null 2>/dev/null; then
    curl -fL --retry 3 --connect-timeout 20 -o "${{PACKAGE_TMP}}" "${{PACKAGE_URL}}"
  elif command -v wget >/dev/null 2>/dev/null; then
    wget -O "${{PACKAGE_TMP}}" "${{PACKAGE_URL}}"
  else
    echo "ERROR: Weder curl noch wget ist verfuegbar, Paket kann nicht geladen werden."
    return 1
  fi

  actual_md5="$(file_md5 "${{PACKAGE_TMP}}")"
  if [ "${{actual_md5}}" != "${{EXPECTED_MD5}}" ]; then
    echo "ERROR: Paket-MD5 stimmt nicht."
    echo "  erwartet: ${{EXPECTED_MD5}}"
    echo "  erhalten : ${{actual_md5}}"
    rm -f "${{PACKAGE_TMP}}"
    return 1
  fi
  mv -f "${{PACKAGE_TMP}}" "${{PACKAGE_FILE}}"
}}

ensure_package_file() {{
  if [ -f "${{PACKAGE_FILE}}" ]; then
    actual_md5="$(file_md5 "${{PACKAGE_FILE}}")"
    if [ "${{actual_md5}}" = "${{EXPECTED_MD5}}" ]; then
      echo "Borg Backup UI: vorhandenes Paket passt zur MD5, Download wird uebersprungen."
      return 0
    fi
    echo "Borg Backup UI: lokales Paket hat andere MD5, lade neu."
  fi
  download_package
}}

mkdir -p "${{PLUGIN_DIR}}"

if package_registered; then
  if core_payload_present; then
    marker_md5="$(cat "${{INSTALLED_MD5_FILE}}" 2>/dev/null || true)"
    if [ "${{marker_md5}}" = "${{EXPECTED_MD5}}" ]; then
      ensure_apprise_vendor
      echo "Borg Backup UI: Version ${{VERSION}} ist bereits installiert, Paketinstallation wird uebersprungen."
      exit 0
    fi
    if [ -f "${{PACKAGE_FILE}}" ]; then
      actual_md5="$(file_md5 "${{PACKAGE_FILE}}")"
      if [ "${{actual_md5}}" = "${{EXPECTED_MD5}}" ]; then
        ensure_apprise_vendor
        echo "Borg Backup UI: Version ${{VERSION}} ist bereits installiert, MD5-Marker wird aktualisiert."
        echo "${{EXPECTED_MD5}}" > "${{INSTALLED_MD5_FILE}}" 2>/dev/null || true
        exit 0
      fi
    else
      echo "Borg Backup UI: Version ${{VERSION}} ist bereits installiert, kein Download/Entpacken noetig."
      ensure_apprise_vendor
      echo "${{EXPECTED_MD5}}" > "${{INSTALLED_MD5_FILE}}" 2>/dev/null || true
      exit 0
    fi
  fi
fi

ensure_package_file
echo "Borg Backup UI: installiere Paket ${{VERSION}}. Auf USB-Flash kann dieser Schritt etwas dauern..."
upgradepkg --install-new "${{PACKAGE_FILE}}"
ensure_apprise_vendor
echo "${{EXPECTED_MD5}}" > "${{INSTALLED_MD5_FILE}}" 2>/dev/null || true
rm -f /tmp/borg-backup-ui-package-install.sh
</INLINE>
</FILE>
{PACKAGE_INSTALL_END}"""


def rewrite_package_installer(manifest: str, md5: str) -> str:
    block = package_install_block(md5)
    if PACKAGE_INSTALL_BLOCK_RE.search(manifest):
        return PACKAGE_INSTALL_BLOCK_RE.sub(lambda _match: block, manifest, count=1)
    if LEGACY_PACKAGE_FILE_RE.search(manifest):
        return LEGACY_PACKAGE_FILE_RE.sub(lambda _match: block, manifest, count=1)
    raise RuntimeError("Plugin manifest package install block was not found")


def prepare_build_tree(
    root: Path,
    version: str,
    source_commit: str,
    base_sha: str,
    digest: str,
    built_at: str,
) -> dict[str, object]:
    manifest_path = root / f"{NAME}.plg"
    app_path = root / "borg_backup_ui.py"
    notes, fragments, notes_digest = rendered_release_notes(root)

    manifest = manifest_path.read_text(encoding="utf-8")
    manifest = re.sub(
        r'<!ENTITY version\s+"[^"]*">',
        f'<!ENTITY version   "{version}">',
        manifest,
        count=1,
    )
    manifest = replace_changelog_block(manifest, version, notes)
    manifest_path.write_text(manifest, encoding="utf-8")

    app = app_path.read_text(encoding="utf-8")
    app = re.sub(r'APP_VERSION = "[^"]*"', f'APP_VERSION = "{version}"', app, count=1)
    app_path.write_text(app, encoding="utf-8")

    provenance: dict[str, object] = {
        "schema_version": 1,
        "package_name": NAME,
        "version": version,
        "source_commit": source_commit,
        "source_base_sha": base_sha,
        "source_digest": digest,
        "release_notes_sha256": notes_digest,
        "release_note_fragments": fragments,
        "built_at": built_at,
    }
    (root / PROVENANCE_NAME).write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return provenance


def package_provenance(package: Path) -> dict[str, object]:
    with tarfile.open(package, "r:*") as archive:
        members = {member.name.lstrip("./"): member for member in archive.getmembers()}
        missing = [name for name in EXPECTED_PACKAGE_MEMBERS if name not in members]
        if missing:
            raise RuntimeError("Package is missing required members: " + ", ".join(missing))
        forbidden = [
            name
            for name in members
            if name.startswith(f"boot/config/plugins/{NAME}/runtime/vendor/")
        ]
        if forbidden:
            raise RuntimeError("Package must not contain expanded Apprise vendor files")
        bundle_prefix = f"boot/config/plugins/{NAME}/runtime/vendor-bundles/"
        bundle_members = [
            name
            for name, member in members.items()
            if name.startswith(bundle_prefix)
            and name.endswith(".tar.xz")
            and member.isfile()
        ]
        if len(bundle_members) != 1:
            raise RuntimeError("Package must contain exactly one Apprise vendor bundle")
        meta_handle = archive.extractfile(
            members[f"boot/config/plugins/{NAME}/runtime/vendor-bundles/apprise-vendor.json"]
        )
        if meta_handle is None:
            raise RuntimeError("Apprise vendor metadata cannot be read")
        meta = json.loads(meta_handle.read().decode("utf-8"))
        bundle_name = str(meta.get("bundle", ""))
        bundle_sha = str(meta.get("sha256", ""))
        bundle_version = str(meta.get("version", ""))
        expected_bundle = bundle_prefix + bundle_name
        if not bundle_name or expected_bundle not in members:
            raise RuntimeError("Apprise vendor metadata references a missing bundle")
        if not bundle_version or not re.fullmatch(r"[0-9a-f]{64}", bundle_sha):
            raise RuntimeError("Apprise vendor metadata is incomplete")
        bundle_handle = archive.extractfile(members[expected_bundle])
        if bundle_handle is None:
            raise RuntimeError("Apprise vendor bundle cannot be read")
        digest = hashlib.sha256()
        for chunk in iter(lambda: bundle_handle.read(1024 * 1024), b""):
            digest.update(chunk)
        if digest.hexdigest() != bundle_sha:
            raise RuntimeError("Apprise vendor bundle SHA256 does not match metadata")
        handle = archive.extractfile(members[PROVENANCE_MEMBER])
        if handle is None:
            raise RuntimeError("Package provenance cannot be read")
        return json.loads(handle.read().decode("utf-8"))


def manifest_version(manifest: Path) -> str:
    text = manifest.read_text(encoding="utf-8")
    match = re.search(r'<!ENTITY version\s+"([^"]+)">', text)
    if not match:
        raise RuntimeError("Manifest version is missing")
    return match.group(1)


def manifest_md5(manifest: Path) -> str:
    text = manifest.read_text(encoding="utf-8")
    match = re.search(r"<MD5>([^<]+)</MD5>", text)
    if not match:
        match = re.search(r'EXPECTED_MD5="([0-9a-fA-F]{32})"', text)
    if not match:
        raise RuntimeError("Manifest MD5 is missing")
    return match.group(1).lower()


def file_md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_release_artifacts(repo: Path, main_ref: str = "HEAD") -> dict[str, object]:
    manifest = repo / f"{NAME}.plg"
    ET.parse(manifest)
    version = manifest_version(manifest)
    package = repo / "releases" / f"{NAME}-{version}.txz"
    if not package.is_file():
        raise RuntimeError(f"Stable package is missing: {package}")
    if manifest_md5(manifest) != file_md5(package):
        raise RuntimeError("Stable manifest MD5 does not match the package")
    text = manifest.read_text(encoding="utf-8")
    required = (
        'launch="Settings/borg-backup-ui"',
        "/main/&name;.plg",
        "/main/releases/&name;-&version;.txz",
    )
    for value in required:
        if value not in text:
            raise RuntimeError(f"Stable manifest value is missing: {value}")
    app = (repo / "borg_backup_ui.py").read_text(encoding="utf-8")
    if f'APP_VERSION = "{version}"' not in app:
        raise RuntimeError("APP_VERSION does not match the stable manifest")
    packages = sorted((repo / "releases").glob(f"{NAME}-*.txz"))
    if len(packages) > 5:
        raise RuntimeError("Stable release retention exceeds five packages")
    provenance = package_provenance(package)
    if provenance.get("version") != version:
        raise RuntimeError("Package provenance version does not match the manifest")
    actual_digest = source_digest(repo, main_ref)
    if provenance.get("source_digest") != actual_digest:
        raise RuntimeError("Stable source differs from the exact tested package source")
    block_match = re.search(
        rf"###{re.escape(version)}###\n(.*?)(?=\n###|\n\]\]>|\Z)",
        text,
        re.DOTALL,
    )
    if not block_match:
        raise RuntimeError("Stable manifest has no changelog block for the current version")
    notes = block_match.group(1).strip()
    notes_digest = hashlib.sha256(notes.encode("utf-8")).hexdigest()
    if provenance.get("release_notes_sha256") != notes_digest:
        raise RuntimeError("Stable changelog differs from the exactly tested release notes")
    return provenance


def command_source_digest(args: argparse.Namespace) -> None:
    print(source_digest(Path(args.repo).resolve(), args.revision))


def command_write_attestation(args: argparse.Namespace) -> None:
    payload = write_attestation(Path(args.repo).resolve(), args.base_ref)
    print(json.dumps(payload, sort_keys=True))


def command_verify_attestation(args: argparse.Namespace) -> None:
    payload = verify_attestation(Path(args.repo).resolve())
    print(json.dumps(payload, sort_keys=True))


def command_prepare_build_tree(args: argparse.Namespace) -> None:
    payload = prepare_build_tree(
        Path(args.root).resolve(),
        args.version,
        args.source_commit,
        args.base_sha,
        args.source_digest,
        args.built_at,
    )
    print(json.dumps(payload, sort_keys=True))


def command_package_provenance(args: argparse.Namespace) -> None:
    payload = package_provenance(Path(args.package).resolve())
    if args.expect_version and payload.get("version") != args.expect_version:
        raise RuntimeError("Package provenance version mismatch")
    if args.expect_source_digest and payload.get("source_digest") != args.expect_source_digest:
        raise RuntimeError("Package provenance source digest mismatch")
    print(json.dumps(payload, sort_keys=True))


def command_verify_release(args: argparse.Namespace) -> None:
    payload = verify_release_artifacts(Path(args.repo).resolve(), args.main_ref)
    print(json.dumps(payload, sort_keys=True))


def command_verify_implementation_delta(args: argparse.Namespace) -> None:
    verify_implementation_delta(Path(args.repo).resolve(), args.base_ref)


def command_rewrite_package_installer(args: argparse.Namespace) -> None:
    path = Path(args.manifest).resolve()
    text = path.read_text(encoding="utf-8")
    path.write_text(rewrite_package_installer(text, args.md5), encoding="utf-8")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    subparsers = result.add_subparsers(dest="command", required=True)

    item = subparsers.add_parser("source-digest")
    item.add_argument("--repo", default=".")
    item.add_argument("--revision", default="HEAD")
    item.set_defaults(func=command_source_digest)

    item = subparsers.add_parser("write-attestation")
    item.add_argument("--repo", default=".")
    item.add_argument("--base-ref", required=True)
    item.set_defaults(func=command_write_attestation)

    item = subparsers.add_parser("verify-attestation")
    item.add_argument("--repo", default=".")
    item.set_defaults(func=command_verify_attestation)

    item = subparsers.add_parser("prepare-build-tree")
    item.add_argument("--root", required=True)
    item.add_argument("--version", required=True)
    item.add_argument("--source-commit", required=True)
    item.add_argument("--base-sha", required=True)
    item.add_argument("--source-digest", required=True)
    item.add_argument("--built-at", required=True)
    item.set_defaults(func=command_prepare_build_tree)

    item = subparsers.add_parser("package-provenance")
    item.add_argument("--package", required=True)
    item.add_argument("--expect-version")
    item.add_argument("--expect-source-digest")
    item.set_defaults(func=command_package_provenance)

    item = subparsers.add_parser("verify-release")
    item.add_argument("--repo", default=".")
    item.add_argument("--main-ref", default="HEAD")
    item.set_defaults(func=command_verify_release)

    item = subparsers.add_parser("verify-implementation-delta")
    item.add_argument("--repo", default=".")
    item.add_argument("--base-ref", required=True)
    item.set_defaults(func=command_verify_implementation_delta)

    item = subparsers.add_parser("rewrite-package-installer")
    item.add_argument("--manifest", required=True)
    item.add_argument("--md5", required=True)
    item.set_defaults(func=command_rewrite_package_installer)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        args.func(args)
    except (
        RuntimeError,
        ValueError,
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        subprocess.CalledProcessError,
        tarfile.TarError,
        ET.ParseError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
