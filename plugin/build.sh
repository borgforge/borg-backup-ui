#!/bin/bash
# build.sh – Erstellt das Unraid Plugin Package (.txz) für borg-backup-ui
#
# Internal package builder. Release metadata and provenance must already have
# been prepared in an exported staging tree by deploy-test.sh.
#
# Das erzeugte .txz enthält:
#   boot/config/plugins/borg-backup-ui/   → persistente App-Dateien (Flash)
#   etc/rc.d/rc.borg_backup_ui            → Start/Stop-Skript
#   usr/local/emhttp/plugins/borg-backup-ui/ → Unraid Plugin-Metadaten
#   install/slack-desc                    → Paketbeschreibung

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
NAME="borg-backup-ui"
VERSION="${1:-$(date +%Y.%m.%d.%H%M)}"
BUILD_OUTPUT_DIR="${BUILD_OUTPUT_DIR:-${SCRIPT_DIR}/build}"
BUILD_RELEASES_DIR="${BUILD_RELEASES_DIR:-${REPO_DIR}/releases}"
BUILD_PREPARED="${BUILD_PREPARED:-0}"
BUILD_DIR="${BUILD_OUTPUT_DIR}/pkg"
PKG_FILE="${BUILD_OUTPUT_DIR}/${NAME}-${VERSION}.txz"
PLG_FILE="${REPO_DIR}/${NAME}.plg"
APPRISE_LOCK_FILE="${SCRIPT_DIR}/apprise-requirements.lock"
APPRISE_VENDOR_DIR="${REPO_DIR}/runtime/vendor"
APPRISE_VENDOR_VERSION=""

echo "==> Baue ${NAME} v${VERSION}"

case "${BUILD_OUTPUT_DIR}" in
  ""|"/"|"${REPO_DIR}")
    echo "ERROR: Unsicheres BUILD_OUTPUT_DIR: ${BUILD_OUTPUT_DIR}" >&2
    exit 1
    ;;
esac

if [ "${BUILD_PREPARED}" != "1" ]; then
  echo "ERROR: Direkte Paket-Builds sind deaktiviert." >&2
  echo "       Zuerst den finalen Commit pushen und ./plugin/mr-preflight.sh ausfuehren." >&2
  echo "       Testpakete anschliessend mit ./plugin/deploy-test.sh <version> bauen." >&2
  exit 1
fi

PROVENANCE_FILE="${REPO_DIR}/build-provenance.json"
if [ ! -f "${PROVENANCE_FILE}" ]; then
  echo "ERROR: Vorbereiteter Build ohne build-provenance.json." >&2
  exit 1
fi
python3 - "${PROVENANCE_FILE}" "${VERSION}" <<'PY'
import json
import pathlib
import sys

payload = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
if payload.get("version") != sys.argv[2]:
    raise SystemExit("ERROR: Version in build-provenance.json stimmt nicht mit dem Build ueberein.")
if not payload.get("source_digest") or not payload.get("source_commit"):
    raise SystemExit("ERROR: Unvollstaendige Build-Provenance.")
PY
grep -F -q "<!ENTITY version   \"${VERSION}\">" "${PLG_FILE}" || {
  echo "ERROR: Vorbereitetes Manifest enthaelt nicht Version ${VERSION}." >&2
  exit 1
}
grep -F -q "APP_VERSION = \"${VERSION}\"" "${REPO_DIR}/borg_backup_ui.py" || {
  echo "ERROR: Vorbereiteter Quellbaum enthaelt nicht APP_VERSION ${VERSION}." >&2
  exit 1
}

install_apprise_vendor() {
  if [ ! -f "${APPRISE_LOCK_FILE}" ]; then
    echo "ERROR: Apprise dependency lock is missing: ${APPRISE_LOCK_FILE}" >&2
    exit 1
  fi
  if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 is required to vendor Apprise." >&2
    exit 1
  fi

  echo "==> Installiere hash-gepruefte Apprise Runtime nach runtime/vendor"
  rm -rf "${APPRISE_VENDOR_DIR}"
  mkdir -p "${APPRISE_VENDOR_DIR}"
  python3 -m pip install \
    --disable-pip-version-check \
    --no-cache-dir \
    --only-binary=:all: \
    --require-hashes \
    --target "${APPRISE_VENDOR_DIR}" \
    -r "${APPRISE_LOCK_FILE}"
  find "${APPRISE_VENDOR_DIR}" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
  APPRISE_VENDOR_VERSION="$(PYTHONDONTWRITEBYTECODE=1 python3 - "${APPRISE_VENDOR_DIR}" <<'PY'
import sys
from pathlib import Path

vendor = Path(sys.argv[1])
sys.path.insert(0, str(vendor))
import apprise  # noqa: E402

version = str(getattr(apprise, "__version__", "") or "")
if not version:
    raise SystemExit("ERROR: Bundled Apprise import did not expose a version.")
print(version)
PY
)"
  find "${APPRISE_VENDOR_DIR}" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
  echo "==> Apprise Runtime: ${APPRISE_VENDOR_VERSION}"
}

create_apprise_vendor_bundle() {
  if [ -z "${APPRISE_VENDOR_VERSION}" ]; then
    echo "ERROR: Apprise vendor version is unknown." >&2
    exit 1
  fi
  if [ ! -d "${APPRISE_VENDOR_DIR}/apprise" ]; then
    echo "ERROR: Apprise vendor tree is missing." >&2
    exit 1
  fi

  local bundle_dir="${APP_DST}/runtime/vendor-bundles"
  local bundle_tmp="${BUILD_OUTPUT_DIR}/apprise-vendor.tar.xz"
  local bundle_sha
  local bundle_name
  mkdir -p "${bundle_dir}"

  # Keep the bundle hash stable across builds when the vendored dependency tree
  # did not change. This lets Unraid upgrades skip re-extracting Apprise.
  tar --create \
      --xz \
      --file="${bundle_tmp}" \
      --directory="${APPRISE_VENDOR_DIR}" \
      --sort=name \
      --mtime='UTC 2024-01-01' \
      --owner=0 --group=0 --numeric-owner \
      .
  bundle_sha="$(sha256sum "${bundle_tmp}" | awk '{print $1}')"
  bundle_name="apprise-${APPRISE_VENDOR_VERSION}-${bundle_sha}.tar.xz"
  mv -f "${bundle_tmp}" "${bundle_dir}/${bundle_name}"
  python3 - "${bundle_dir}/apprise-vendor.json" "${APPRISE_VENDOR_VERSION}" "${bundle_sha}" "${bundle_name}" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
payload = {
    "name": "apprise",
    "version": sys.argv[2],
    "sha256": sys.argv[3],
    "bundle": sys.argv[4],
}
path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
  echo "==> Apprise Vendor-Bundle: ${bundle_name}"
}

install_apprise_vendor

# ── Aufräumen ──────────────────────────────────────────────────────────────
rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_OUTPUT_DIR}"
# Build-Ausgaben sind kurzlebig. Alte Pakete duerfen sich hier nicht bei jedem
# Test-Deploy weiter ansammeln; stabile Release-Artefakte liegen separat unter
# releases/ und werden von dieser Bereinigung nicht beruehrt.
find "${BUILD_OUTPUT_DIR}" -maxdepth 1 -type f -name "${NAME}-*.txz" -delete
mkdir -p "${BUILD_DIR}"

# ── App-Dateien → /boot/config/plugins/borg-backup-ui/ ────────────────────
APP_DST="${BUILD_DIR}/boot/config/plugins/${NAME}"
mkdir -p "${APP_DST}"
cp "${REPO_DIR}/borg_backup_ui.py"           "${APP_DST}/"
cp "${REPO_DIR}/borg_backup_ui.conf.example" "${APP_DST}/"
cp "${REPO_DIR}/LICENSE"                     "${APP_DST}/"
cp -r "${REPO_DIR}/api"                      "${APP_DST}/"
cp -r "${REPO_DIR}/ui"                       "${APP_DST}/"
MANUAL_DST="${APP_DST}/ui/docs/manual"
mkdir -p "${MANUAL_DST}/de" "${MANUAL_DST}/en"
cp "${REPO_DIR}/docs/user-manual/de/user-manual.md" "${MANUAL_DST}/de/"
cp "${REPO_DIR}/docs/user-manual/en/user-manual.md" "${MANUAL_DST}/en/"
cp -r "${REPO_DIR}/docs/user-manual/assets" "${MANUAL_DST}/"
if [ -d "${REPO_DIR}/runtime" ]; then
  mkdir -p "${APP_DST}/runtime"
  (
    cd "${REPO_DIR}/runtime"
    tar --create --exclude='./vendor' .
  ) | (
    cd "${APP_DST}/runtime"
    tar --extract
  )
fi
create_apprise_vendor_bundle
[ -f "${REPO_DIR}/build-provenance.json" ] && cp "${REPO_DIR}/build-provenance.json" "${APP_DST}/"
# Legacy fallback packaging (older repo layout)
[ -f "${REPO_DIR}/borg_restore_test.py" ] && install -m 0755 "${REPO_DIR}/borg_restore_test.py" "${APP_DST}/"
[ -f "${REPO_DIR}/borg_restore_test.description" ] && cp "${REPO_DIR}/borg_restore_test.description" "${APP_DST}/"
# __pycache__ nicht mitnehmen
find "${APP_DST}" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# ── rc-Skript → /etc/rc.d/ ────────────────────────────────────────────────
RC_DST="${BUILD_DIR}/etc/rc.d"
mkdir -p "${RC_DST}"
install -m 0755 "${SCRIPT_DIR}/rc.borg_backup_ui" "${RC_DST}/"

# ── Unraid emhttp-Verzeichnis → /usr/local/emhttp/plugins/ ────────────────
EMHTTP_DST="${BUILD_DIR}/usr/local/emhttp/plugins/${NAME}"
mkdir -p "${EMHTTP_DST}"
find "${SCRIPT_DIR}" -maxdepth 1 -type f -name 'plugin-icon*.png' -exec cp {} "${EMHTTP_DST}/" \;
[ -f "${SCRIPT_DIR}/${NAME}.page" ]    && cp "${SCRIPT_DIR}/${NAME}.page"    "${EMHTTP_DST}/"
[ -f "${SCRIPT_DIR}/${NAME}-dashboard.page" ] && cp "${SCRIPT_DIR}/${NAME}-dashboard.page" "${EMHTTP_DST}/"
[ -f "${SCRIPT_DIR}/widget-status.php" ] && cp "${SCRIPT_DIR}/widget-status.php" "${EMHTTP_DST}/widget-status.php"
[ -f "${REPO_DIR}/ui/assets/app-icon.png" ] && cp "${REPO_DIR}/ui/assets/app-icon.png" "${EMHTTP_DST}/app-icon.png"
[ -f "${SCRIPT_DIR}/README.md" ]        && cp "${SCRIPT_DIR}/README.md"        "${EMHTTP_DST}/"

# ── Slackware-Paketmetadaten ──────────────────────────────────────────────
INSTALL_DIR="${BUILD_DIR}/install"
mkdir -p "${INSTALL_DIR}"

cat > "${INSTALL_DIR}/slack-desc" << EOF
${NAME}: ${NAME} (Borg Backup Web UI für Unraid)
${NAME}:
${NAME}: Leichtgewichtiger Web-Server zur Verwaltung von Borg Backup
${NAME}: Skripten auf Unraid. Zeigt Dashboard, Jobs, Storage, History
${NAME}: und Einstellungen. Kein pip, nur Python 3 Standard-Library.
${NAME}:
${NAME}: Autor: Thorsten Steinberg
${NAME}: Version: ${VERSION}
${NAME}: https://github.com/borgforge/borg-backup-ui
${NAME}:
${NAME}:
EOF

# ── .txz bauen ────────────────────────────────────────────────────────────
cd "${BUILD_DIR}"
if command -v makepkg &>/dev/null; then
  makepkg -l y -c y "${PKG_FILE}"
else
  tar --create \
      --xz \
      --file="${PKG_FILE}" \
      --owner=root --group=root \
      --exclude='./.git' \
      .
fi
cd - >/dev/null

echo "==> Paket: ${PKG_FILE}"

# ── MD5 berechnen ─────────────────────────────────────────────────────────
if command -v md5sum &>/dev/null; then
  MD5=$(md5sum "${PKG_FILE}" | cut -d' ' -f1)
else
  MD5=$(md5 -q "${PKG_FILE}")  # macOS
fi
echo "==> MD5: ${MD5}"

# ── .plg-Datei aktualisieren (version-Entity + MD5) ──────────────────────
if [ -f "${PLG_FILE}" ]; then
  sed -i.bak \
    -e "s|<!ENTITY version   \"[^\"]*\">|<!ENTITY version   \"${VERSION}\">|" \
    -e "s|<MD5>[^<]*</MD5>|<MD5>${MD5}</MD5>|" \
    "${PLG_FILE}"
  rm -f "${PLG_FILE}.bak"
  echo "==> ${PLG_FILE} aktualisiert (version + MD5)"
fi

# ── Release-Artefakt kopieren (ohne Löschung bestehender Releases) ────────
RELEASES_DIR="${BUILD_RELEASES_DIR}"
mkdir -p "${RELEASES_DIR}"
cp "${PKG_FILE}" "${RELEASES_DIR}/"
echo "==> Kopiert nach: ${RELEASES_DIR}/$(basename "${PKG_FILE}")"

echo "==> Build abgeschlossen. Der Quellbaum wurde nicht als Release-Workflow mutiert."
