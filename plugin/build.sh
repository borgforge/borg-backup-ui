#!/bin/bash
# build.sh – Erstellt das Unraid Plugin Package (.txz) für borg-backup-ui
#
# Verwendung:
#   ./plugin/build.sh             # Version = jetzt (YYYY.MM.DD.HHMM)
#   ./plugin/build.sh 2026.05.10  # explizite Version (nur bei Ausnahmen)
#
# Workflow vor dem Build:
#   1. Änderungen unter ###NEXT### in borg-backup-ui.plg eintragen
#   2. ./plugin/build.sh  (keine Version nötig)
#   3. git add releases/<name>-<version>.txz borg-backup-ui.plg borg_backup_ui.py
#   4. git commit -m "Release <version>"
#   5. git push
#   6. ./plugin/mr-preflight.sh   # verhindert "PR enthält keine Änderungen"
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
BUILD_DIR="${SCRIPT_DIR}/build/pkg"
PKG_FILE="${SCRIPT_DIR}/build/${NAME}-${VERSION}.txz"
PLG_FILE="${REPO_DIR}/${NAME}.plg"
MAX_NEXT_CHANGE_LINES="${MAX_NEXT_CHANGE_LINES:-30}"

echo "==> Baue ${NAME} v${VERSION}"

# ── Changelog pruefen, bevor Dateien veraendert werden ───────────────────
if [ -f "${PLG_FILE}" ]; then
  NEXT_COUNT=$(grep -F -x -c '###NEXT###' "${PLG_FILE}" || true)
  VERSION_COUNT=$(grep -F -x -c "###${VERSION}###" "${PLG_FILE}" || true)

  if [ "${NEXT_COUNT}" -gt 1 ]; then
    echo "ERROR: Mehr als ein ###NEXT###-Block in ${NAME}.plg gefunden." >&2
    exit 1
  fi

  if [ "${VERSION_COUNT}" -gt 1 ]; then
    echo "ERROR: Mehr als ein ###${VERSION}###-Block in ${NAME}.plg gefunden." >&2
    exit 1
  fi

  if [ "${NEXT_COUNT}" -eq 1 ] && [ "${VERSION_COUNT}" -gt 0 ]; then
    echo "ERROR: ${NAME}.plg enthaelt bereits ###${VERSION}### und zusaetzlich ###NEXT###." >&2
    echo "       Bitte Version pruefen, damit keine doppelten Changelog-Eintraege entstehen." >&2
    exit 1
  fi

  if [ "${NEXT_COUNT}" -eq 0 ] && [ "${VERSION_COUNT}" -eq 0 ]; then
    echo "ERROR: Kein ###NEXT###-Block und kein bestehender ###${VERSION}###-Block gefunden." >&2
    echo "       Fuer neue Releases zuerst nutzerrelevante Release Notes unter ###NEXT### pflegen." >&2
    echo "       Fuer Rebuilds dieselbe Version angeben, die bereits im Changelog steht." >&2
    exit 1
  fi

  if [ "${NEXT_COUNT}" -eq 1 ]; then
    NEXT_LINES=$(awk '
      /^###NEXT###$/ { in_next=1; next }
      in_next && /^###[^#]+###$/ { in_next=0 }
      in_next && NF { count++ }
      END { print count + 0 }
    ' "${PLG_FILE}")
    if [ "${NEXT_LINES}" -gt "${MAX_NEXT_CHANGE_LINES}" ]; then
      echo "ERROR: ###NEXT### enthaelt ${NEXT_LINES} nicht-leere Zeilen, erlaubt sind ${MAX_NEXT_CHANGE_LINES}." >&2
      echo "       Das Manifest-Changelog soll kurz bleiben; technische Details nach docs/changelog.md auslagern." >&2
      exit 1
    fi
  else
    echo "==> Rebuild einer bestehenden Version: ###${VERSION}### vorhanden, kein ###NEXT### noetig"
  fi
fi

# ── APP_VERSION in borg_backup_ui.py aktualisieren (VOR dem Kopieren!) ────────
MAIN_PY="${REPO_DIR}/borg_backup_ui.py"
if [ -f "${MAIN_PY}" ]; then
  sed -i.bak "s|^APP_VERSION = \"[^\"]*\"|APP_VERSION = \"${VERSION}\"|" "${MAIN_PY}"
  rm -f "${MAIN_PY}.bak"
  echo "==> APP_VERSION in borg_backup_ui.py → ${VERSION}"
fi

# ── ###NEXT### in CHANGES durch ###VERSION### ersetzen ───────────────────────
if [ -f "${PLG_FILE}" ]; then
  if grep -q "###NEXT###" "${PLG_FILE}"; then
    sed -i.bak "s|###NEXT###|###${VERSION}###|" "${PLG_FILE}"
    rm -f "${PLG_FILE}.bak"
    echo "==> ###NEXT### → ###${VERSION}### in CHANGES ersetzt"
  fi
fi

# ── Aufräumen ──────────────────────────────────────────────────────────────
rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}"
mkdir -p "${SCRIPT_DIR}/build"

# ── App-Dateien → /boot/config/plugins/borg-backup-ui/ ────────────────────
APP_DST="${BUILD_DIR}/boot/config/plugins/${NAME}"
mkdir -p "${APP_DST}"
cp "${REPO_DIR}/borg_backup_ui.py"           "${APP_DST}/"
cp "${REPO_DIR}/borg_backup_ui.conf.example" "${APP_DST}/"
cp -r "${REPO_DIR}/api"                      "${APP_DST}/"
cp -r "${REPO_DIR}/ui"                       "${APP_DST}/"
[ -d "${REPO_DIR}/runtime" ] && cp -r "${REPO_DIR}/runtime" "${APP_DST}/"
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
RELEASES_DIR="${REPO_DIR}/releases"
mkdir -p "${RELEASES_DIR}"
cp "${PKG_FILE}" "${RELEASES_DIR}/"
echo "==> Kopiert nach: ${RELEASES_DIR}/$(basename "${PKG_FILE}")"

echo ""
echo "Fertig! Nächste Schritte:"
echo "  1. Alles committen und pushen:"
echo "     git add releases/${NAME}-${VERSION}.txz ${NAME}.plg borg_backup_ui.py"
echo "     git commit -m 'Release ${VERSION} – <Kurzbeschreibung>'"
echo "     git push"
echo "  2. Plugin-URL in Unraid:"
echo "     https://raw.githubusercontent.com/borgforge/borg-backup-ui/main/${NAME}.plg"
