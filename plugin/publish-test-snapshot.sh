#!/bin/bash
# Publish a pinned candidate plus the rotating two-file test-channel snapshot.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
python3 "$SCRIPT_DIR/security_workflow.py" guard-public

if [ "$#" -ne 7 ]; then
  echo "Usage: $0 <remote> <branch> <manifest> <package> <message> <tmp-root> <candidate-tag>" >&2
  exit 2
fi

REMOTE_URL="$1"
TEST_BRANCH="$2"
MANIFEST_FILE="$3"
PACKAGE_FILE="$4"
COMMIT_MESSAGE="$5"
TMP_ROOT="$6"
CANDIDATE_TAG="$7"

# Only the reviewed main workflow may call this internal publication helper.
[[ "${GITHUB_ACTIONS:-}" == true && "${GITHUB_EVENT_NAME:-}" == workflow_dispatch &&
   "${GITHUB_REF:-}" == refs/heads/main && "${BBUI_ENVIRONMENT:-}" == testing &&
   "${GITHUB_WORKFLOW_REF:-}" == borgforge/borg-backup-ui/.github/workflows/testing-release.yml@refs/heads/main ]] || {
  echo 'ERROR: Protected testing workflow required.' >&2; exit 1;
}
[[ "$REMOTE_URL" == https://github.com/borgforge/borg-backup-ui.git ]] || {
  echo 'ERROR: Unexpected publication repository.' >&2; exit 1;
}
[[ "$CANDIDATE_TAG" =~ ^test-candidates/[0-9]{4}\.[0-9]{2}\.[0-9]{2}\.[0-9]{4}$ ]] || {
  echo 'ERROR: Invalid candidate tag.' >&2; exit 1;
}
VERSION="${CANDIDATE_TAG#test-candidates/}"
[[ "$(basename "$PACKAGE_FILE")" == "borg-backup-ui-${VERSION}.txz" ]] || exit 1

# Check the real identity before each push. Credentials remain process-scoped.
bot_push() {
  [[ "$(gh api user --jq .login)" == borg-codex-bot ]] || {
    echo 'ERROR: borg-codex-bot credentials required.' >&2; return 1;
  }
  git -C "$SNAPSHOT_DIR" -c credential.helper= \
    -c 'credential.helper=!gh auth git-credential' push "$@"
}

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

export GIT_AUTHOR_NAME=borg-codex-bot GIT_COMMITTER_NAME=borg-codex-bot
export GIT_AUTHOR_EMAIL=borg-codex-bot@users.noreply.github.com
export GIT_COMMITTER_EMAIL=borg-codex-bot@users.noreply.github.com

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
  git -C "$SNAPSHOT_DIR" fetch --no-tags origin "$REMOTE_HEAD" >/dev/null
  CURRENT_VERSION="$(git -C "$SNAPSHOT_DIR" show "${REMOTE_HEAD}:borg-backup-ui-test.plg" |
    python3 -c 'import sys,xml.etree.ElementTree as E; print(E.fromstring(sys.stdin.read()).attrib["version"])')"
  if [[ "$VERSION" < "$CURRENT_VERSION" ]]; then
    echo 'ERROR: Refusing to replace a newer test feed with an older candidate.' >&2; exit 1
  fi
  if [[ "$VERSION" == "$CURRENT_VERSION" &&
        "$(git -C "$SNAPSHOT_DIR" rev-parse "${REMOTE_HEAD}^{tree}")" != "$(git -C "$SNAPSHOT_DIR" rev-parse 'HEAD^{tree}')" ]]; then
    echo 'ERROR: This version already has different published bytes.' >&2; exit 1
  fi
fi

PINNED="$(git ls-remote --refs "$REMOTE_URL" "refs/tags/${CANDIDATE_TAG}" | awk 'NR == 1 { print $1 }')"
if [[ -n "$PINNED" ]]; then
  git -C "$SNAPSHOT_DIR" fetch --no-tags origin "$PINNED" >/dev/null
  if [[ -n "$(git -C "$SNAPSHOT_DIR" show -s --format=%P "$PINNED")" ||
        "$(git -C "$SNAPSHOT_DIR" rev-parse "${PINNED}^{tree}")" != "$(git -C "$SNAPSHOT_DIR" rev-parse 'HEAD^{tree}')" ]]; then
    echo 'ERROR: Candidate version already identifies different bytes.' >&2; exit 1
  fi
  LOCAL_HEAD="$PINNED"
else
  # No force: a concurrent creation fails instead of changing candidate identity.
  bot_push origin "HEAD:refs/tags/${CANDIDATE_TAG}"
fi

if [ -n "$REMOTE_HEAD" ]; then
  # The exact expected old SHA makes this safe against concurrent publishes.
  bot_push \
    --force-with-lease="refs/heads/${TEST_BRANCH}:${REMOTE_HEAD}" \
    origin "${LOCAL_HEAD}:refs/heads/${TEST_BRANCH}"
else
  bot_push origin "${LOCAL_HEAD}:refs/heads/${TEST_BRANCH}"
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
