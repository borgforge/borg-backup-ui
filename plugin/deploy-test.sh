#!/bin/bash
# Deploy the current working tree as an installable Unraid test-channel build.
#
# This script builds the current tree, generates borg-backup-ui-test.plg, and
# pushes only the test manifest plus release package to the test-channel branch.
# The test-channel branch intentionally does not contain the full source tree or
# history. Stable build files generated during the build are restored locally
# before the script exits; stable promotion is handled by a separate release PR.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
NAME="borg-backup-ui"
TEST_BRANCH="${TEST_BRANCH:-test-channel}"
VERSION="${1:-$(date +%Y.%m.%d.%H%M)}"
CURRENT_BRANCH="$(git -C "$REPO_DIR" branch --show-current)"

if [ -z "$CURRENT_BRANCH" ]; then
  echo "ERROR: Kein aktueller Git-Branch gefunden." >&2
  exit 1
fi

echo "==> Test-Deploy ${NAME} ${VERSION}"
echo "==> Source-Branch: ${CURRENT_BRANCH}"
echo "==> Test-Branch  : ${TEST_BRANCH}"

TMP_ROOT="${REPO_DIR}/.release-tmp"
mkdir -p "$TMP_ROOT"

PLG_FILE="${REPO_DIR}/${NAME}.plg"
APP_FILE="${REPO_DIR}/borg_backup_ui.py"
PKG_FILE="${REPO_DIR}/releases/${NAME}-${VERSION}.txz"

PLG_SNAPSHOT="$(mktemp "${TMP_ROOT}/${NAME}.plg.before.XXXXXX")"
APP_SNAPSHOT="$(mktemp "${TMP_ROOT}/borg_backup_ui.py.before.XXXXXX")"
PKG_SNAPSHOT="$(mktemp "${TMP_ROOT}/${NAME}-${VERSION}.txz.before.XXXXXX")"
PKG_EXISTED=0
cp "$PLG_FILE" "$PLG_SNAPSHOT"
cp "$APP_FILE" "$APP_SNAPSHOT"
if [ -f "$PKG_FILE" ]; then
  cp "$PKG_FILE" "$PKG_SNAPSHOT"
  PKG_EXISTED=1
fi

WORKTREE=""
TMP_PLG=""

restore_stable_files() {
  cp "$PLG_SNAPSHOT" "$PLG_FILE"
  cp "$APP_SNAPSHOT" "$APP_FILE"
  if [ "$PKG_EXISTED" -eq 1 ]; then
    cp "$PKG_SNAPSHOT" "$PKG_FILE"
  else
    rm -f "$PKG_FILE"
  fi
}

cleanup() {
  restore_stable_files || true
  if [ -n "$WORKTREE" ]; then
    rm -rf "$WORKTREE"
  fi
  if [ -n "$TMP_PLG" ]; then
    rm -f "$TMP_PLG"
  fi
  rm -f "$PLG_SNAPSHOT" "$APP_SNAPSHOT" "$PKG_SNAPSHOT"
}
trap cleanup EXIT

"${SCRIPT_DIR}/build.sh" "$VERSION"

if [ ! -f "$PKG_FILE" ]; then
  echo "ERROR: Release-Paket fehlt: ${PKG_FILE}" >&2
  exit 1
fi

require_pkg_entry() {
  local entry="$1"
  if ! tar -tf "$PKG_FILE" | sed 's|^\./||' | grep -Fx "$entry" >/dev/null; then
    echo "ERROR: Paket ${PKG_FILE} enthaelt erwarteten Eintrag nicht: ${entry}" >&2
    exit 1
  fi
}

echo "==> Pruefe Paketinhalt"
require_pkg_entry "boot/config/plugins/${NAME}/borg_backup_ui.py"
require_pkg_entry "boot/config/plugins/${NAME}/api/config_api.py"
require_pkg_entry "boot/config/plugins/${NAME}/ui/index.html"
require_pkg_entry "boot/config/plugins/${NAME}/runtime/config/backup.conf.example"
require_pkg_entry "etc/rc.d/rc.borg_backup_ui"

if command -v md5sum >/dev/null 2>&1; then
  MD5="$(md5sum "$PKG_FILE" | cut -d' ' -f1)"
else
  MD5="$(md5 -q "$PKG_FILE")"
fi

TMP_PLG="$(mktemp "${TMP_ROOT}/${NAME}-test.XXXXXX.plg")"
cp "$PLG_FILE" "$TMP_PLG"
sed -i.bak \
  -e "s|<!ENTITY pluginURL \"[^\"]*\">|<!ENTITY pluginURL \"https://raw.githubusercontent.com/borgforge/borg-backup-ui/${TEST_BRANCH}/\\&name;-test.plg\">|" \
  -e "s|<!ENTITY pkgurl    \"[^\"]*\">|<!ENTITY pkgurl    \"https://raw.githubusercontent.com/borgforge/borg-backup-ui/${TEST_BRANCH}/releases/\\&name;-\\&version;.txz\">|" \
  -e "s|description=\"[^\"]*\"|description=\"TEST CHANNEL - Web UI for Borg Backup. Install this only on test systems.\"|" \
  -e "s|<MD5>[^<]*</MD5>|<MD5>${MD5}</MD5>|" \
  "$TMP_PLG"
rm -f "${TMP_PLG}.bak"

echo "==> Pruefe Test-Manifest XML"
python3 -c 'import sys, xml.etree.ElementTree as ET; ET.parse(sys.argv[1])' "$TMP_PLG"

WORKTREE="$(mktemp -d "${TMP_ROOT}/${TEST_BRANCH}.XXXXXX")"
ORIGIN_URL="$(git -C "$REPO_DIR" remote get-url origin)"
git -C "$WORKTREE" init
git -C "$WORKTREE" remote add origin "$ORIGIN_URL"

if git -C "$REPO_DIR" ls-remote --exit-code --heads origin "$TEST_BRANCH" >/dev/null 2>&1; then
  git -C "$WORKTREE" fetch --depth 1 origin "$TEST_BRANCH"
  git -C "$WORKTREE" switch -c "$TEST_BRANCH" FETCH_HEAD
else
  git -C "$WORKTREE" switch -c "$TEST_BRANCH"
fi

mkdir -p "${WORKTREE}/releases"
rm -f "${WORKTREE}/releases/${NAME}-"*.txz
cp "$TMP_PLG" "${WORKTREE}/${NAME}-test.plg"
cp "$PKG_FILE" "${WORKTREE}/releases/"

git -C "$WORKTREE" add "${NAME}-test.plg" "releases/${NAME}-${VERSION}.txz"

if git -C "$WORKTREE" diff --cached --quiet; then
  echo "==> Test-Channel ist bereits aktuell."
else
  git -C "$WORKTREE" commit -m "Deploy test ${VERSION} from ${CURRENT_BRANCH}"
fi

git -C "$WORKTREE" push origin "HEAD:${TEST_BRANCH}"

cat <<EOF

Fertig.
Test-Plugin-URL:
  https://raw.githubusercontent.com/borgforge/borg-backup-ui/${TEST_BRANCH}/${NAME}-test.plg

Getestete Version:
  ${VERSION}

Nach erfolgreichem Test:
  Feature-PR mergen und danach nur mit ausdruecklicher Stable-Freigabe:
  ./plugin/promote-release.sh ${VERSION}

Hinweis:
  Lokale Stable-Build-Dateien wurden wiederhergestellt. Feature-PRs duerfen
  borg-backup-ui.plg und releases/*.txz nicht als Stable-Artefakte enthalten.
EOF
