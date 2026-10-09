#!/bin/bash
# Promote the exact tested test-channel package in a dedicated stable PR.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
NAME="borg-backup-ui"
VERSION="${1:-}"
MAIN_BRANCH="${MAIN_BRANCH:-main}"
TEST_BRANCH="${TEST_BRANCH:-test-channel}"
RELEASE_BRANCH="${RELEASE_BRANCH:-codex/release-${VERSION}}"
TMP_ROOT="${REPO_DIR}/.release-tmp"
SECURITY_CANDIDATE=""
PUBLISH_SECURITY=""
shift || true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --security-candidate) SECURITY_CANDIDATE="${2:?Missing candidate}"; shift 2;;
    --publish-security) PUBLISH_SECURITY="${2:?Missing advisory}"; shift 2;;
    *) echo "Unknown argument: $1" >&2; exit 2;;
  esac
done
if [[ -n "$SECURITY_CANDIDATE" ]]; then
  SECURITY_CANDIDATE="$(realpath "$SECURITY_CANDIDATE")"
  python3 "$SCRIPT_DIR/security_workflow.py" verify --candidate "$SECURITY_CANDIDATE" --version "$VERSION" >/dev/null
  if [[ -z "$PUBLISH_SECURITY" ]]; then
    exec python3 "$SCRIPT_DIR/security_workflow.py" prepare-release --candidate "$SECURITY_CANDIDATE" --version "$VERSION"
  fi
  python3 "$SCRIPT_DIR/security_workflow.py" authorize-publication \
    --candidate "$SECURITY_CANDIDATE" --advisory "$PUBLISH_SECURITY"
else
  [[ -z "$PUBLISH_SECURITY" ]] || { echo 'Private candidate required' >&2; exit 2; }
  python3 "$SCRIPT_DIR/security_workflow.py" guard-public
fi


if [[ ! "$VERSION" =~ ^[0-9]{4}\.[0-9]{2}\.[0-9]{2}\.[0-9]{4}$ ]]; then
  echo "Usage: ./plugin/promote-release.sh <YYYY.MM.DD.HHMM>" >&2
  exit 2
fi
if ! command -v gh >/dev/null 2>&1; then
  echo "ERROR: gh is required to create or update the release PR." >&2
  exit 1
fi

echo "==> Promote tested ${NAME} ${VERSION} to stable"
if [[ -n "$SECURITY_CANDIDATE" ]]; then
  git -C "$REPO_DIR" fetch --prune origin "$MAIN_BRANCH"
else
  git -C "$REPO_DIR" fetch --prune origin "$MAIN_BRANCH" "$TEST_BRANCH"
fi

CURRENT_BRANCH="$(git -C "$REPO_DIR" branch --show-current)"
LOCAL_SHA="$(git -C "$REPO_DIR" rev-parse HEAD)"
MAIN_SHA="$(git -C "$REPO_DIR" rev-parse "origin/${MAIN_BRANCH}")"
if [[ "$CURRENT_BRANCH" != "$MAIN_BRANCH" ]]; then
  echo "ERROR: Stable promotion must be started from ${MAIN_BRANCH}, not ${CURRENT_BRANCH:-<detached>}." >&2
  exit 1
fi
if [[ -n "$(git -C "$REPO_DIR" status --porcelain=v1 --untracked-files=all)" ]]; then
  echo "ERROR: Stable promotion requires a clean working tree." >&2
  exit 1
fi
if [[ "$LOCAL_SHA" != "$MAIN_SHA" ]]; then
  echo "ERROR: Local ${MAIN_BRANCH} must exactly match origin/${MAIN_BRANCH} before promotion." >&2
  exit 1
fi

mkdir -p "$TMP_ROOT"
RUN_DIR="$(mktemp -d "${TMP_ROOT}/promote-${VERSION}.XXXXXX")"
TEST_PLG="${RUN_DIR}/${NAME}-test.plg"
TEST_PKG="${RUN_DIR}/${NAME}-${VERSION}.txz"
WORKTREE="${RUN_DIR}/release"
cleanup() {
  rm -rf "$RUN_DIR"
}
trap cleanup EXIT

echo "==> Lade getestetes Manifest und exaktes Paket"
if [[ -n "$SECURITY_CANDIDATE" ]]; then
  cp "$SECURITY_CANDIDATE/release-template.plg" "$TEST_PLG"
  cp "$SECURITY_CANDIDATE/${NAME}-${VERSION}.txz" "$TEST_PKG"
else
  git -C "$REPO_DIR" show "origin/${TEST_BRANCH}:${NAME}-test.plg" > "$TEST_PLG"
  git -C "$REPO_DIR" show "origin/${TEST_BRANCH}:releases/${NAME}-${VERSION}.txz" > "$TEST_PKG"
fi

TEST_VERSION="$(sed -n 's/.*<!ENTITY version   "\([^"]*\)">.*/\1/p' "$TEST_PLG" | head -n1)"
if [[ "$TEST_VERSION" != "$VERSION" ]]; then
  echo "ERROR: test-channel manifest points to ${TEST_VERSION:-<none>}, expected ${VERSION}." >&2
  exit 1
fi

if command -v md5sum >/dev/null 2>&1; then
  PKG_MD5="$(md5sum "$TEST_PKG" | cut -d' ' -f1)"
  TEST_PACKAGE_SHA256="$(sha256sum "$TEST_PKG" | cut -d' ' -f1)"
else
  PKG_MD5="$(md5 -q "$TEST_PKG")"
  TEST_PACKAGE_SHA256="$(shasum -a 256 "$TEST_PKG" | cut -d' ' -f1)"
fi
MANIFEST_MD5="$(python3 "$SCRIPT_DIR/release_workflow.py" manifest-md5 --manifest "$TEST_PLG")"
if [[ "$PKG_MD5" != "$MANIFEST_MD5" ]]; then
  echo "ERROR: test-channel MD5 does not match the tested package." >&2
  exit 1
fi

PROVENANCE_JSON="$(python3 "$SCRIPT_DIR/release_workflow.py" package-provenance \
  --package "$TEST_PKG" \
  --expect-version "$VERSION")"
SOURCE_DIGEST="$(printf '%s' "$PROVENANCE_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["source_digest"])')"
SOURCE_COMMIT="$(printf '%s' "$PROVENANCE_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["source_commit"])')"
MAIN_DIGEST="$(python3 "$SCRIPT_DIR/release_workflow.py" source-digest \
  --repo "$REPO_DIR" \
  --revision "origin/${MAIN_BRANCH}")"
if [[ "$SOURCE_DIGEST" != "$MAIN_DIGEST" ]]; then
  echo "ERROR: origin/${MAIN_BRANCH} does not contain the exact tested deployable source." >&2
  echo "  tested: ${SOURCE_DIGEST}" >&2
  echo "  main  : ${MAIN_DIGEST}" >&2
  echo "Merge the tested feature/fix PR before promoting this version." >&2
  exit 1
fi

echo "==> Erstelle Repository-lokalen Release-Arbeitsbaum"
ORIGIN_URL="$(git -C "$REPO_DIR" remote get-url origin)"
git clone --quiet "$ORIGIN_URL" "$WORKTREE"
git -C "$WORKTREE" fetch --quiet origin "$MAIN_BRANCH"
if [[ -z "$SECURITY_CANDIDATE" ]]; then
  git -C "$WORKTREE" fetch --quiet origin "$TEST_BRANCH"
fi

if git -C "$WORKTREE" ls-remote --exit-code --heads origin "$RELEASE_BRANCH" >/dev/null 2>&1; then
  git -C "$WORKTREE" switch --quiet --track "origin/${RELEASE_BRANCH}"
  git -C "$WORKTREE" merge --no-edit "origin/${MAIN_BRANCH}"
else
  git -C "$WORKTREE" switch --quiet -c "$RELEASE_BRANCH" "origin/${MAIN_BRANCH}"
fi

mkdir -p "${WORKTREE}/releases"
cp "$TEST_PKG" "${WORKTREE}/releases/${NAME}-${VERSION}.txz"

python3 "$SCRIPT_DIR/release_workflow.py" promote-artifacts \
  --root "$WORKTREE" --manifest "$TEST_PLG" --version "$VERSION" \
  --md5 "$PKG_MD5" --provenance "$PROVENANCE_JSON"

# Keep only the newest five stable packages in main.
mapfile -t release_files < <(find "${WORKTREE}/releases" -maxdepth 1 -type f -name "${NAME}-*.txz" | sort)
if (( ${#release_files[@]} > 5 )); then
  remove_count=$(( ${#release_files[@]} - 5 ))
  for ((i=0; i<remove_count; i++)); do
    rm -f "${release_files[$i]}"
  done
fi

if command -v sha256sum >/dev/null 2>&1; then
  RELEASE_PACKAGE_SHA256="$(sha256sum "${WORKTREE}/releases/${NAME}-${VERSION}.txz" | cut -d' ' -f1)"
else
  RELEASE_PACKAGE_SHA256="$(shasum -a 256 "${WORKTREE}/releases/${NAME}-${VERSION}.txz" | cut -d' ' -f1)"
fi
if [[ "$RELEASE_PACKAGE_SHA256" != "$TEST_PACKAGE_SHA256" ]]; then
  echo "ERROR: Stable package is not byte-identical to the tested package." >&2
  exit 1
fi

git -C "$WORKTREE" add borg-backup-ui.plg borg_backup_ui.py releases release-notes/pending 2>/dev/null || \
  git -C "$WORKTREE" add borg-backup-ui.plg borg_backup_ui.py releases
if git -C "$WORKTREE" diff --cached --quiet; then
  echo "==> Release branch already contains ${VERSION}."
else
  git -C "$WORKTREE" commit -m "Promote ${VERSION} to stable"
fi
git -C "$WORKTREE" push -u origin "$RELEASE_BRANCH"

echo "==> Fuehre ausschliesslich Release-Artefakt-Preflight aus"
if [[ -n "$SECURITY_CANDIDATE" ]]; then
  "${WORKTREE}/plugin/release-preflight.sh" --security-candidate "$SECURITY_CANDIDATE"
else
  "${WORKTREE}/plugin/release-preflight.sh"
fi

PR_BODY="${RUN_DIR}/pr-body.md"
printf '%s\n' \
  'Promotes the exact tested Borg Backup UI package to the stable channel.' \
  '' \
  'Changes:' \
  "- Promotes verified candidate version ${VERSION}." \
  "- Reuses the byte-identical tested package (SHA-256: ${TEST_PACKAGE_SHA256})." \
  "- Verifies tested deployable source digest against origin/${MAIN_BRANCH}." \
  '- Keeps only the newest five stable packages.' \
  '' \
  'Verification:' \
  "- Source commit recorded in package provenance: ${SOURCE_COMMIT}." \
  '- Release artifact preflight passed without rerunning the full source test suite.' \
  > "$PR_BODY"

EXISTING_NUMBER="$(gh pr list --repo borgforge/borg-backup-ui --head "$RELEASE_BRANCH" --base "$MAIN_BRANCH" --json number --jq '.[0].number // empty' 2>/dev/null || true)"
if [[ -n "$EXISTING_NUMBER" ]]; then
  gh pr edit --repo borgforge/borg-backup-ui "$EXISTING_NUMBER" --body-file "$PR_BODY"
  echo "==> Existing release pull request updated."
else
  gh pr create \
    --repo borgforge/borg-backup-ui \
    --head "$RELEASE_BRANCH" \
    --base "$MAIN_BRANCH" \
    --title "Promote ${VERSION} to stable" \
    --body-file "$PR_BODY"
fi

cat <<EOF

Fertig.
Release-Branch: ${RELEASE_BRANCH}
Getestetes Paket: ${TEST_PACKAGE_SHA256}
Der Release-PR enthaelt keinen neuen Build und keine erneute Volltestsuite.
EOF
