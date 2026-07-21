#!/bin/bash
# Publish the exact, preflight-attested source commit to test-channel.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
NAME="borg-backup-ui"
TEST_BRANCH="${TEST_BRANCH:-test-channel}"
VERSION="${1:-$(date +%Y.%m.%d.%H%M)}"
CURRENT_BRANCH="$(git -C "$REPO_DIR" branch --show-current)"

if [[ ! "$VERSION" =~ ^[0-9]{4}\.[0-9]{2}\.[0-9]{2}\.[0-9]{4}$ ]]; then
  echo "ERROR: Version muss dem Format YYYY.MM.DD.HHMM entsprechen: ${VERSION}" >&2
  exit 2
fi
if [ -z "$CURRENT_BRANCH" ] || [ "$CURRENT_BRANCH" = "main" ] || [ "$CURRENT_BRANCH" = "$TEST_BRANCH" ]; then
  echo "ERROR: Test-Deploy erfordert einen Feature-/Fix-Branch." >&2
  exit 1
fi

echo "==> Test-Deploy ${NAME} ${VERSION}"
echo "==> Source-Branch: ${CURRENT_BRANCH}"

echo "==> Pruefe commitgebundene Preflight-Attestierung"
ATTEST_JSON="$(python3 "$SCRIPT_DIR/release_workflow.py" verify-attestation --repo "$REPO_DIR")"
SOURCE_COMMIT="$(printf '%s' "$ATTEST_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["head_sha"])')"
SOURCE_BASE_SHA="$(printf '%s' "$ATTEST_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["base_sha"])')"
SOURCE_DIGEST="$(printf '%s' "$ATTEST_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["source_digest"])')"

echo "==> Pruefe exakt gepushten Quellstand"
REMOTE_SHA="$(git -C "$REPO_DIR" ls-remote --heads origin "$CURRENT_BRANCH" | awk '{print $1}')"
if [ -z "$REMOTE_SHA" ] || [ "$REMOTE_SHA" != "$SOURCE_COMMIT" ]; then
  echo "ERROR: Attestierter Commit ist nicht exakt auf origin/${CURRENT_BRANCH}." >&2
  echo "  attestiert: ${SOURCE_COMMIT}" >&2
  echo "  remote    : ${REMOTE_SHA:-<none>}" >&2
  exit 1
fi

TMP_ROOT="${REPO_DIR}/.release-tmp"
mkdir -p "$TMP_ROOT"
RUN_DIR="$(mktemp -d "${TMP_ROOT}/test-${VERSION}.XXXXXX")"
STAGE_DIR="${RUN_DIR}/source"
OUTPUT_DIR="${RUN_DIR}/output"
RELEASES_DIR="${RUN_DIR}/releases"
mkdir -p "$STAGE_DIR" "$OUTPUT_DIR" "$RELEASES_DIR"

cleanup() {
  rm -rf "$RUN_DIR"
}
trap cleanup EXIT

echo "==> Exportiere attestierten Commit in Repository-lokales Staging"
git -C "$REPO_DIR" archive "$SOURCE_COMMIT" | tar -x -C "$STAGE_DIR"
BUILT_AT="$(git -C "$REPO_DIR" show -s --format=%cI "$SOURCE_COMMIT")"
python3 "$SCRIPT_DIR/release_workflow.py" prepare-build-tree \
  --root "$STAGE_DIR" \
  --version "$VERSION" \
  --source-commit "$SOURCE_COMMIT" \
  --base-sha "$SOURCE_BASE_SHA" \
  --source-digest "$SOURCE_DIGEST" \
  --built-at "$BUILT_AT" >/dev/null

echo "==> Baue isoliertes Testpaket"
BUILD_PREPARED=1 \
BUILD_OUTPUT_DIR="$OUTPUT_DIR" \
BUILD_RELEASES_DIR="$RELEASES_DIR" \
  "$STAGE_DIR/plugin/build.sh" "$VERSION"

PKG_FILE="${RELEASES_DIR}/${NAME}-${VERSION}.txz"
PLG_FILE="${STAGE_DIR}/${NAME}.plg"
python3 "$SCRIPT_DIR/release_workflow.py" package-provenance \
  --package "$PKG_FILE" \
  --expect-version "$VERSION" \
  --expect-source-digest "$SOURCE_DIGEST" >/dev/null

if command -v md5sum >/dev/null 2>&1; then
  MD5="$(md5sum "$PKG_FILE" | cut -d' ' -f1)"
else
  MD5="$(md5 -q "$PKG_FILE")"
fi

TEST_PLG="${RUN_DIR}/${NAME}-test.plg"
cp "$PLG_FILE" "$TEST_PLG"
sed -i \
  -e "s|<!ENTITY pluginURL \"[^\"]*\">|<!ENTITY pluginURL \"https://raw.githubusercontent.com/borgforge/borg-backup-ui/${TEST_BRANCH}/\&name;-test.plg\">|" \
  -e "s|<!ENTITY pkgurl    \"[^\"]*\">|<!ENTITY pkgurl    \"https://raw.githubusercontent.com/borgforge/borg-backup-ui/${TEST_BRANCH}/releases/\&name;-\&version;.txz\">|" \
  -e "s|description=\"[^\"]*\"|description=\"TEST CHANNEL - Web UI for Borg Backup. Install this only on test systems.\"|" \
  -e "s|<MD5>[^<]*</MD5>|<MD5>${MD5}</MD5>|" \
  "$TEST_PLG"

python3 "$SCRIPT_DIR/release_workflow.py" rewrite-package-installer \
  --manifest "$TEST_PLG" \
  --md5 "$MD5"

python3 - "$TEST_PLG" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
if re.search(r'<PLUGIN\b[^>]*\blaunch="[^"]*"', text, re.S):
    text = re.sub(
        r'(<PLUGIN\b[^>]*?)\blaunch="[^"]*"',
        r'\1launch="Settings/borg-backup-ui"',
        text,
        count=1,
        flags=re.S,
    )
else:
    text = re.sub(
        r'(<PLUGIN\b[^>]*?\bversion="[^"]*")',
        r'\1\n        launch="Settings/borg-backup-ui"',
        text,
        count=1,
        flags=re.S,
    )
path.write_text(text, encoding="utf-8")
PY

python3 -c 'import sys, xml.etree.ElementTree as ET; ET.parse(sys.argv[1])' "$TEST_PLG"

# Recheck immediately before publishing so an outdated local attestation cannot
# race with a subsequently pushed commit.
REMOTE_SHA="$(git -C "$REPO_DIR" ls-remote --heads origin "$CURRENT_BRANCH" | awk '{print $1}')"
if [ "$REMOTE_SHA" != "$SOURCE_COMMIT" ]; then
  echo "ERROR: Source branch changed while building; test snapshot is not published." >&2
  exit 1
fi

ORIGIN_URL="$(git -C "$REPO_DIR" remote get-url origin)"
"${SCRIPT_DIR}/publish-test-snapshot.sh" \
  "$ORIGIN_URL" \
  "$TEST_BRANCH" \
  "$TEST_PLG" \
  "$PKG_FILE" \
  "Deploy test ${VERSION} from ${CURRENT_BRANCH}@${SOURCE_COMMIT}" \
  "$TMP_ROOT"

cat <<EOF

Fertig.
Test-Plugin-URL:
  https://raw.githubusercontent.com/borgforge/borg-backup-ui/${TEST_BRANCH}/${NAME}-test.plg

Getestete Version:
  ${VERSION}

Quellcommit:
  ${SOURCE_COMMIT}

Nach erfolgreichem Test:
  Feature-PR mergen und erst nach ausdruecklicher Stable-Freigabe:
  ./plugin/promote-release.sh ${VERSION}
EOF
