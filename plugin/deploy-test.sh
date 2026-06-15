#!/bin/bash
# Deploy the current working tree as an installable Unraid test-channel build.
#
# This script builds the current tree, generates borg-backup-ui-test.plg, and
# pushes only the test manifest plus release package to the test-channel branch.
# The test-channel branch intentionally does not contain the full source tree or
# history. The current branch remains the source of truth for the later go-live
# MR.

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

"${SCRIPT_DIR}/build.sh" "$VERSION"

PKG_FILE="${REPO_DIR}/releases/${NAME}-${VERSION}.txz"
if [ ! -f "$PKG_FILE" ]; then
  echo "ERROR: Release-Paket fehlt: ${PKG_FILE}" >&2
  exit 1
fi

if command -v md5sum >/dev/null 2>&1; then
  MD5="$(md5sum "$PKG_FILE" | cut -d' ' -f1)"
else
  MD5="$(md5 -q "$PKG_FILE")"
fi

TMP_ROOT="${REPO_DIR}/.release-tmp"
mkdir -p "$TMP_ROOT"

TMP_PLG="$(mktemp "${TMP_ROOT}/${NAME}-test.XXXXXX.plg")"
cp "${REPO_DIR}/${NAME}.plg" "$TMP_PLG"
sed -i.bak \
  -e "s|<!ENTITY pluginURL \"[^\"]*\">|<!ENTITY pluginURL \"\\&gitlab;/-/raw/${TEST_BRANCH}/\\&name;-test.plg\">|" \
  -e "s|<!ENTITY pkgurl    \"[^\"]*\">|<!ENTITY pkgurl    \"\\&gitlab;/-/raw/${TEST_BRANCH}/releases/\\&name;-\\&version;.txz\">|" \
  -e "s|description=\"[^\"]*\"|description=\"TEST CHANNEL - Web UI for Borg Backup. Install this only on test systems.\"|" \
  -e "s|<MD5>[^<]*</MD5>|<MD5>${MD5}</MD5>|" \
  "$TMP_PLG"
rm -f "${TMP_PLG}.bak"

WORKTREE="$(mktemp -d "${TMP_ROOT}/${TEST_BRANCH}.XXXXXX")"
cleanup() {
  rm -rf "$WORKTREE"
  rm -f "$TMP_PLG"
}
trap cleanup EXIT

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
  https://gitlab.thetwist.de/tsteinbe/borg-backup-ui/-/raw/${TEST_BRANCH}/${NAME}-test.plg

Getestete Version:
  ${VERSION}

Nach erfolgreichem Test:
  ./plugin/promote-release.sh ${VERSION}
EOF
