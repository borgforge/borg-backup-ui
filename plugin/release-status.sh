#!/bin/bash
# Show local, test-channel and stable release status.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
NAME="borg-backup-ui"
TEST_BRANCH="${TEST_BRANCH:-test-channel}"

manifest_version() {
  sed -n 's/.*<!ENTITY version   "\([^"]*\)">.*/\1/p' | head -n1
}

echo "Branch:"
git -C "$REPO_DIR" status --short --branch
echo

echo "Lokales Stable-Manifest:"
printf '  %s\n' "$(manifest_version < "${REPO_DIR}/${NAME}.plg")"
echo

echo "Lokale Release-Artefakte:"
ls -1 "${REPO_DIR}/releases/${NAME}-"*.txz 2>/dev/null | sed 's|.*/|  |' || echo "  keine"
echo

echo "Remote main:"
if git -C "$REPO_DIR" show "origin/main:${NAME}.plg" >/dev/null 2>&1; then
  git -C "$REPO_DIR" show "origin/main:${NAME}.plg" | manifest_version | sed 's/^/  /'
else
  echo "  nicht verfuegbar"
fi
echo

echo "Remote ${TEST_BRANCH}:"
if git -C "$REPO_DIR" show "origin/${TEST_BRANCH}:${NAME}-test.plg" >/dev/null 2>&1; then
  git -C "$REPO_DIR" show "origin/${TEST_BRANCH}:${NAME}-test.plg" | manifest_version | sed 's/^/  /'
else
  echo "  noch nicht angelegt"
fi

if command -v glab >/dev/null 2>&1; then
  echo
  echo "Offene Merge Requests:"
  glab mr list || true
fi
