#!/bin/bash
# Publish one immutable test-channel snapshot without retaining package history.

set -euo pipefail

if [ "$#" -ne 6 ]; then
  echo "Usage: $0 <remote> <branch> <manifest> <package> <message> <tmp-root>" >&2
  exit 2
fi

REMOTE_URL="$1"
TEST_BRANCH="$2"
MANIFEST_FILE="$3"
PACKAGE_FILE="$4"
COMMIT_MESSAGE="$5"
TMP_ROOT="$6"

if [ "$TEST_BRANCH" != "test-channel" ]; then
  echo "ERROR: Snapshot-Publishing ist nur fuer test-channel erlaubt." >&2
  exit 1
fi

if ! git check-ref-format "refs/heads/${TEST_BRANCH}" >/dev/null 2>&1; then
  echo "ERROR: Ungueltiger Test-Channel-Branch: ${TEST_BRANCH}" >&2
  exit 1
fi

if [ ! -f "$MANIFEST_FILE" ]; then
  echo "ERROR: Test-Manifest fehlt: ${MANIFEST_FILE}" >&2
  exit 1
fi

if [ ! -f "$PACKAGE_FILE" ]; then
  echo "ERROR: Test-Paket fehlt: ${PACKAGE_FILE}" >&2
  exit 1
fi

mkdir -p "$TMP_ROOT"
SNAPSHOT_DIR="$(mktemp -d "${TMP_ROOT}/test-channel-snapshot.XXXXXX")"

cleanup() {
  rm -rf "$SNAPSHOT_DIR"
}
trap cleanup EXIT

git -C "$SNAPSHOT_DIR" init --initial-branch="$TEST_BRANCH" >/dev/null
git -C "$SNAPSHOT_DIR" remote add origin "$REMOTE_URL"

if ! git -C "$SNAPSHOT_DIR" config user.name >/dev/null; then
  git -C "$SNAPSHOT_DIR" config user.name "borg-codex-bot"
fi
if ! git -C "$SNAPSHOT_DIR" config user.email >/dev/null; then
  git -C "$SNAPSHOT_DIR" config user.email "borg-codex-bot@users.noreply.github.com"
fi

mkdir -p "${SNAPSHOT_DIR}/releases"
cp "$MANIFEST_FILE" "${SNAPSHOT_DIR}/borg-backup-ui-test.plg"
cp "$PACKAGE_FILE" "${SNAPSHOT_DIR}/releases/$(basename "$PACKAGE_FILE")"

git -C "$SNAPSHOT_DIR" add --all -- \
  "borg-backup-ui-test.plg" \
  "releases/$(basename "$PACKAGE_FILE")"

mapfile -t SNAPSHOT_FILES < <(git -C "$SNAPSHOT_DIR" ls-files)
if [ "${#SNAPSHOT_FILES[@]}" -ne 2 ] || \
   [ "${SNAPSHOT_FILES[0]}" != "borg-backup-ui-test.plg" ] || \
   [ "${SNAPSHOT_FILES[1]}" != "releases/$(basename "$PACKAGE_FILE")" ]; then
  echo "ERROR: Test-Channel-Snapshot enthaelt unerwartete Dateien." >&2
  printf '  %s\n' "${SNAPSHOT_FILES[@]}" >&2
  exit 1
fi

git -C "$SNAPSHOT_DIR" commit -m "$COMMIT_MESSAGE" >/dev/null
LOCAL_HEAD="$(git -C "$SNAPSHOT_DIR" rev-parse HEAD)"
REMOTE_HEAD="$(
  git ls-remote --heads "$REMOTE_URL" "refs/heads/${TEST_BRANCH}" |
    awk 'NR == 1 { print $1 }'
)"

if [ -n "$REMOTE_HEAD" ]; then
  # The exact expected old SHA makes this safe against concurrent publishes.
  git -C "$SNAPSHOT_DIR" push \
    --force-with-lease="refs/heads/${TEST_BRANCH}:${REMOTE_HEAD}" \
    origin "HEAD:refs/heads/${TEST_BRANCH}"
else
  git -C "$SNAPSHOT_DIR" push origin "HEAD:refs/heads/${TEST_BRANCH}"
fi

PUBLISHED_HEAD="$(
  git ls-remote --heads "$REMOTE_URL" "refs/heads/${TEST_BRANCH}" |
    awk 'NR == 1 { print $1 }'
)"
if [ "$PUBLISHED_HEAD" != "$LOCAL_HEAD" ]; then
  echo "ERROR: Remote-Test-Channel zeigt nicht auf den erzeugten Snapshot." >&2
  exit 1
fi

echo "==> Test-Channel-Snapshot: ${PUBLISHED_HEAD}"
echo "==> Snapshot-Dateien: 2 (Manifest + aktuelles Paket)"
