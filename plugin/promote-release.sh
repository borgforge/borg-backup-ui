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

if [[ ! "$VERSION" =~ ^[0-9]{4}\.[0-9]{2}\.[0-9]{2}\.[0-9]{4}$ ]]; then
  echo "Usage: ./plugin/promote-release.sh <YYYY.MM.DD.HHMM>" >&2
  exit 2
fi
if ! command -v gh >/dev/null 2>&1; then
  echo "ERROR: gh is required to create or update the release PR." >&2
  exit 1
fi

echo "==> Promote tested ${NAME} ${VERSION} to stable"
git -C "$REPO_DIR" fetch --prune origin "$MAIN_BRANCH" "$TEST_BRANCH"

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
git -C "$REPO_DIR" show "origin/${TEST_BRANCH}:${NAME}-test.plg" > "$TEST_PLG"
git -C "$REPO_DIR" show "origin/${TEST_BRANCH}:releases/${NAME}-${VERSION}.txz" > "$TEST_PKG"

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
git -C "$WORKTREE" fetch --quiet origin "$MAIN_BRANCH" "$TEST_BRANCH"

if git -C "$WORKTREE" ls-remote --exit-code --heads origin "$RELEASE_BRANCH" >/dev/null 2>&1; then
  git -C "$WORKTREE" switch --quiet --track "origin/${RELEASE_BRANCH}"
  git -C "$WORKTREE" merge --no-edit "origin/${MAIN_BRANCH}"
else
  git -C "$WORKTREE" switch --quiet -c "$RELEASE_BRANCH" "origin/${MAIN_BRANCH}"
fi

mkdir -p "${WORKTREE}/releases"
cp "$TEST_PKG" "${WORKTREE}/releases/${NAME}-${VERSION}.txz"

python3 - "$WORKTREE" "$TEST_PLG" "$VERSION" "$PKG_MD5" "$PROVENANCE_JSON" <<'PY'
import hashlib
import json
import re
import sys
from pathlib import Path

worktree = Path(sys.argv[1])
test_manifest = Path(sys.argv[2])
version = sys.argv[3]
md5 = sys.argv[4]
provenance = json.loads(sys.argv[5])
stable_path = worktree / "borg-backup-ui.plg"
app_path = worktree / "borg_backup_ui.py"
package_install_begin = "<!-- BEGIN borg-backup-ui package installer -->"
package_install_end = "<!-- END borg-backup-ui package installer -->"
max_changelog_releases = 3
package_install_re = re.compile(
    re.escape(package_install_begin) + r".*?" + re.escape(package_install_end),
    re.DOTALL,
)
legacy_package_file_re = re.compile(
    r'<FILE Name="&bootdir;/&name;-&version;\.txz" Run="upgradepkg --install-new">\s*'
    r"<URL>&pkgurl;</URL>\s*"
    r"<MD5>[^<]*</MD5>\s*"
    r"</FILE>",
    re.DOTALL,
)

stable = stable_path.read_text(encoding="utf-8")
already_promoted = f"###{version}###" in stable
test = test_manifest.read_text(encoding="utf-8")
block_match = re.search(
    rf"###{re.escape(version)}###\n(?:.*?)(?=\n###|\n\]\]>|\Z)",
    test,
    re.DOTALL,
)
if not block_match:
    raise SystemExit(f"Test manifest has no exact changelog block for {version}")
tested_block = block_match.group(0).strip() + "\n\n"

stable = re.sub(r'<!ENTITY version\s+"[^"]*">', f'<!ENTITY version   "{version}">', stable, count=1)
tested_package_install = package_install_re.search(test)
if tested_package_install:
    package_install_replacement = tested_package_install.group(0)
    if package_install_re.search(stable):
        stable = package_install_re.sub(lambda _match: package_install_replacement, stable, count=1)
    elif legacy_package_file_re.search(stable):
        stable = legacy_package_file_re.sub(lambda _match: package_install_replacement, stable, count=1)
    else:
        raise SystemExit("Stable manifest has no package install block to replace")
else:
    stable = re.sub(r"<MD5>[^<]*</MD5>", f"<MD5>{md5}</MD5>", stable, count=1)
stable = re.sub(
    rf"###{re.escape(version)}###\n(?:.*?)(?=\n###|\n\]\]>|\Z)",
    "",
    stable,
    flags=re.DOTALL,
)
if "<![CDATA[\n" not in stable:
    raise SystemExit("Stable manifest has no changelog CDATA section")
stable = stable.replace("<![CDATA[\n", "<![CDATA[\n" + tested_block, 1)

def limit_changelog(manifest: str) -> str:
    start_marker = "<![CDATA[\n"
    end_marker = "\n]]>"
    start = manifest.find(start_marker)
    end = manifest.find(end_marker, start + len(start_marker))
    if start < 0 or end < 0:
        raise SystemExit("Stable manifest has no changelog CDATA section")
    body_start = start + len(start_marker)
    body = manifest[body_start:end]
    blocks = list(
        re.finditer(
            r"###[^#\n]+###\n.*?(?=\n###[^#\n]+###|\Z)",
            body.strip(),
            re.DOTALL,
        )
    )
    if len(blocks) <= max_changelog_releases:
        return manifest
    kept = "\n\n".join(match.group(0).strip() for match in blocks[:max_changelog_releases])
    return manifest[:body_start] + kept + "\n" + manifest[end:]

stable = limit_changelog(stable)

launch = re.search(r'<PLUGIN\b[^>]*\blaunch="([^"]+)"', test, re.DOTALL)
if not launch:
    raise SystemExit("Test manifest has no tested launch target")
launch_target = launch.group(1)
if re.search(r'<PLUGIN\b[^>]*\blaunch="[^"]*"', stable, re.DOTALL):
    stable = re.sub(
        r'(<PLUGIN\b[^>]*?)\blaunch="[^"]*"',
        lambda match: match.group(1) + f'launch="{launch_target}"',
        stable,
        count=1,
        flags=re.DOTALL,
    )
else:
    stable = re.sub(
        r'(<PLUGIN\b[^>]*?\bversion="[^"]*")',
        lambda match: match.group(1) + f'\n        launch="{launch_target}"',
        stable,
        count=1,
        flags=re.DOTALL,
    )
stable_path.write_text(stable, encoding="utf-8")

app = app_path.read_text(encoding="utf-8")
app = re.sub(r'APP_VERSION = "[^"]*"', f'APP_VERSION = "{version}"', app, count=1)
app_path.write_text(app, encoding="utf-8")

# Consume only the release-note fragments that were hashed into this exact
# tested package. Newer fragments remain pending for the next release.
for item in provenance.get("release_note_fragments", []):
    relative = Path(str(item.get("path", "")))
    if relative.is_absolute() or relative.parts[:2] != ("release-notes", "pending") or ".." in relative.parts:
        raise SystemExit(f"Unsafe release-note fragment path in provenance: {relative}")
    path = worktree / relative
    if not path.exists():
        if already_promoted:
            continue
        raise SystemExit(f"Tested release-note fragment is missing: {relative}")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != item.get("sha256"):
        raise SystemExit(f"Tested release-note fragment changed after the test build: {relative}")
    path.unlink()
PY

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
"${WORKTREE}/plugin/release-preflight.sh"

PR_BODY="${RUN_DIR}/pr-body.md"
printf '%s\n' \
  'Promotes the exact tested Borg Backup UI package to the stable channel.' \
  '' \
  'Changes:' \
  "- Promotes test-channel version ${VERSION}." \
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
