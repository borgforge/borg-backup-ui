#!/bin/bash
# Create or update a dedicated stable release PR from a tested test-channel build.
#
# The feature/fix PR must be merged first. This script starts from origin/main,
# copies the tested package from test-channel, updates the stable manifest, and
# opens/reuses a separate release PR.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
NAME="borg-backup-ui"
VERSION="${1:-}"
MAIN_BRANCH="${MAIN_BRANCH:-main}"
TEST_BRANCH="${TEST_BRANCH:-test-channel}"
RELEASE_BRANCH="${RELEASE_BRANCH:-codex/release-${VERSION}}"

if [ -z "$VERSION" ]; then
  echo "Usage: ./plugin/promote-release.sh <version>" >&2
  exit 2
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "ERROR: gh is required to create/update the release PR." >&2
  exit 1
fi

echo "==> Promote tested ${NAME} ${VERSION} to stable"
echo "==> Main branch   : ${MAIN_BRANCH}"
echo "==> Test branch   : ${TEST_BRANCH}"
echo "==> Release branch: ${RELEASE_BRANCH}"

git -C "$REPO_DIR" fetch origin "$MAIN_BRANCH" "$TEST_BRANCH"

TEST_PLG="${REPO_DIR}/.release-tmp/${NAME}-test-${VERSION}.plg"
TEST_PKG="${REPO_DIR}/.release-tmp/${NAME}-${VERSION}.txz"
mkdir -p "${REPO_DIR}/.release-tmp"
git -C "$REPO_DIR" show "origin/${TEST_BRANCH}:${NAME}-test.plg" > "$TEST_PLG"
git -C "$REPO_DIR" show "origin/${TEST_BRANCH}:releases/${NAME}-${VERSION}.txz" > "$TEST_PKG"

TEST_VERSION="$(sed -n 's/.*<!ENTITY version   "\([^"]*\)">.*/\1/p' "$TEST_PLG" | head -n1)"
if [ "$TEST_VERSION" != "$VERSION" ]; then
  echo "ERROR: test-channel manifest points to ${TEST_VERSION}, expected ${VERSION}." >&2
  exit 1
fi

if command -v md5sum >/dev/null 2>&1; then
  PKG_MD5="$(md5sum "$TEST_PKG" | cut -d' ' -f1)"
else
  PKG_MD5="$(md5 -q "$TEST_PKG")"
fi
MANIFEST_MD5="$(sed -n 's|.*<MD5>\([^<]*\)</MD5>.*|\1|p' "$TEST_PLG" | head -n1)"
if [ "$PKG_MD5" != "$MANIFEST_MD5" ]; then
  echo "ERROR: test-channel MD5 mismatch." >&2
  echo "  manifest: ${MANIFEST_MD5}" >&2
  echo "  package : ${PKG_MD5}" >&2
  exit 1
fi

WORKTREE="$(mktemp -d "${REPO_DIR}/.release-tmp/release-${VERSION}.XXXXXX")"
cleanup() {
  rm -rf "$WORKTREE"
  rm -f "$TEST_PLG" "$TEST_PKG"
}
trap cleanup EXIT

ORIGIN_URL="$(git -C "$REPO_DIR" remote get-url origin)"
git -C "$WORKTREE" init
git -C "$WORKTREE" remote add origin "$ORIGIN_URL"

if git -C "$REPO_DIR" ls-remote --exit-code --heads origin "$RELEASE_BRANCH" >/dev/null 2>&1; then
  git -C "$WORKTREE" fetch --depth 1 origin "$RELEASE_BRANCH"
  git -C "$WORKTREE" switch -c "$RELEASE_BRANCH" FETCH_HEAD
else
  git -C "$WORKTREE" fetch --depth 1 origin "$MAIN_BRANCH"
  git -C "$WORKTREE" switch -c "$RELEASE_BRANCH" FETCH_HEAD
fi

mkdir -p "${WORKTREE}/releases"
cp "$TEST_PKG" "${WORKTREE}/releases/${NAME}-${VERSION}.txz"

python3 - "$WORKTREE" "$TEST_PLG" "$VERSION" "$PKG_MD5" <<'PY'
import re
import sys
from pathlib import Path

worktree = Path(sys.argv[1])
test_manifest = Path(sys.argv[2])
version = sys.argv[3]
md5 = sys.argv[4]

stable_path = worktree / "borg-backup-ui.plg"
app_path = worktree / "borg_backup_ui.py"

stable = stable_path.read_text(encoding="utf-8")
test = test_manifest.read_text(encoding="utf-8")

stable = re.sub(r'<!ENTITY version   "[^"]*">', f'<!ENTITY version   "{version}">', stable, count=1)
stable = re.sub(r"<MD5>[^<]*</MD5>", f"<MD5>{md5}</MD5>", stable, count=1)

launch_match = re.search(r'<PLUGIN\b[^>]*\blaunch="([^"]+)"', test, re.S)
if not launch_match:
    raise SystemExit("Test manifest does not define the tested Unraid launch target")
launch_target = launch_match.group(1)
if re.search(r'<PLUGIN\b[^>]*\blaunch="[^"]*"', stable, re.S):
    stable = re.sub(
        r'(<PLUGIN\b[^>]*?)\blaunch="[^"]*"',
        lambda match: match.group(1) + f'launch="{launch_target}"',
        stable,
        count=1,
        flags=re.S,
    )
else:
    stable = re.sub(
        r'(<PLUGIN\b[^>]*?\bversion="[^"]*")',
        lambda match: match.group(1) + f'\n        launch="{launch_target}"',
        stable,
        count=1,
        flags=re.S,
    )

block_match = re.search(rf"###(?:{re.escape(version)})###\n(?:.*?)(?=\n###|\n\]\]>|\Z)", test, re.S)
if not block_match:
    raise SystemExit(f"Could not find changelog block for {version} in test manifest")
block = block_match.group(0).strip() + "\n\n"

stable = re.sub(rf"###{re.escape(version)}###\n(?:.*?)(?=\n###|\n\]\]>|\Z)", "", stable, flags=re.S)
stable = stable.replace("<![CDATA[\n", "<![CDATA[\n" + block, 1)
stable_path.write_text(stable, encoding="utf-8")

app = app_path.read_text(encoding="utf-8")
app = re.sub(r'APP_VERSION = "[^"]*"', f'APP_VERSION = "{version}"', app, count=1)
app_path.write_text(app, encoding="utf-8")
PY

# Keep only the newest five stable packages in the release PR.
mapfile -t release_files < <(find "${WORKTREE}/releases" -maxdepth 1 -type f -name "${NAME}-*.txz" | sort)
if [ "${#release_files[@]}" -gt 5 ]; then
  remove_count=$(( ${#release_files[@]} - 5 ))
  for ((i=0; i<remove_count; i++)); do
    rm -f "${release_files[$i]}"
  done
fi

python3 -c 'import sys, xml.etree.ElementTree as ET; ET.parse(sys.argv[1])' "${WORKTREE}/${NAME}.plg"

git -C "$WORKTREE" add "${NAME}.plg" borg_backup_ui.py releases
if git -C "$WORKTREE" diff --cached --quiet; then
  echo "==> Release branch already contains ${VERSION}."
else
  git -C "$WORKTREE" commit -m "Promote ${VERSION} to stable"
fi
git -C "$WORKTREE" push -u origin "$RELEASE_BRANCH"

EXISTING="$(gh pr list --repo borgforge/borg-backup-ui --head "$RELEASE_BRANCH" --base "$MAIN_BRANCH" 2>/dev/null || true)"
if printf '%s\n' "$EXISTING" | grep -q '^[0-9]'; then
  echo "==> Existing release pull request:"
  printf '%s\n' "$EXISTING"
else
  gh pr create \
    --repo borgforge/borg-backup-ui \
    --head "$RELEASE_BRANCH" \
    --base "$MAIN_BRANCH" \
    --title "Promote ${VERSION} to stable" \
    --body $'Promotes a tested Borg Backup UI build to the stable channel.\n\nChanges:\n- Separate release PR for version '"${VERSION}"$'.\n- borg-backup-ui.plg points to the tested version.\n- The tested package from test-channel is included.\n- Older release artifacts are pruned to keep the newest five packages.\n\nTests:\n- Tested via test-channel before go-live.\n- Run ./plugin/mr-preflight.sh on the release branch before merge.'
fi

cat <<EOF

Fertig.
Release-Branch:
  ${RELEASE_BRANCH}

Vor dem Merge auf dem Release-Branch ausfuehren:
  ./plugin/mr-preflight.sh
EOF
