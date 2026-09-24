#!/bin/bash
# Build an exact exported commit. Callers verify its preflight and remote first.
# Arguments: version, source commit, base commit, source digest, new output root.
# Writes source/output/releases below the output root; never publishes anything.
set -euo pipefail
[[ $# -eq 5 ]] || { echo 'Expected version, commit, base, digest, output root' >&2; exit 2; }
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
VERSION="$1"
SOURCE_COMMIT="$2"
SOURCE_BASE_SHA="$3"
SOURCE_DIGEST="$4"
RUN_DIR="$5"
STAGE_DIR="$RUN_DIR/source"
mkdir "$STAGE_DIR" "$RUN_DIR/output" "$RUN_DIR/releases"
git -C "$REPO_DIR" archive "$SOURCE_COMMIT" | tar -x -C "$STAGE_DIR"
BUILT_AT="$(git -C "$REPO_DIR" show -s --format=%cI "$SOURCE_COMMIT")"
python3 "$SCRIPT_DIR/release_workflow.py" prepare-build-tree \
  --root "$STAGE_DIR" --version "$VERSION" --source-commit "$SOURCE_COMMIT" \
  --base-sha "$SOURCE_BASE_SHA" --source-digest "$SOURCE_DIGEST" --built-at "$BUILT_AT" >/dev/null
BUILD_PREPARED=1 BUILD_OUTPUT_DIR="$RUN_DIR/output" BUILD_RELEASES_DIR="$RUN_DIR/releases" \
  bash "$STAGE_DIR/plugin/build.sh" "$VERSION"
python3 "$SCRIPT_DIR/release_workflow.py" package-provenance \
  --package "$RUN_DIR/releases/borg-backup-ui-$VERSION.txz" \
  --expect-version "$VERSION" --expect-source-digest "$SOURCE_DIGEST" >/dev/null
