#!/bin/bash
# Prepare the current branch for go-live by pushing it and opening/reusing a MR.
#
# This script does not rebuild. It expects the branch to already contain the
# tested version and release artifact produced by plugin/deploy-test.sh.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
NAME="borg-backup-ui"
VERSION="${1:-}"
BRANCH="$(git -C "$REPO_DIR" branch --show-current)"

if [ -z "$VERSION" ]; then
  echo "Usage: ./plugin/promote-release.sh <version>" >&2
  exit 2
fi

if [ -z "$BRANCH" ]; then
  echo "ERROR: Kein aktueller Git-Branch gefunden." >&2
  exit 1
fi

if [ "$BRANCH" = "main" ] || [ "$BRANCH" = "master" ]; then
  echo "ERROR: Go-live-MR bitte von einem Feature-/Fix-Branch erstellen, nicht von ${BRANCH}." >&2
  exit 1
fi

PLG_FILE="${REPO_DIR}/${NAME}.plg"
PKG_FILE="${REPO_DIR}/releases/${NAME}-${VERSION}.txz"

if [ ! -f "$PKG_FILE" ]; then
  echo "ERROR: Release-Paket fehlt: ${PKG_FILE}" >&2
  exit 1
fi

MANIFEST_VERSION="$(sed -n 's/.*<!ENTITY version   "\([^"]*\)">.*/\1/p' "$PLG_FILE" | head -n1)"
if [ "$MANIFEST_VERSION" != "$VERSION" ]; then
  echo "ERROR: ${NAME}.plg zeigt auf ${MANIFEST_VERSION}, erwartet ${VERSION}." >&2
  exit 1
fi

if ! git -C "$REPO_DIR" diff --quiet || ! git -C "$REPO_DIR" diff --cached --quiet; then
  echo "ERROR: Arbeitsbaum enthaelt uncommitted Aenderungen. Bitte zuerst committen." >&2
  git -C "$REPO_DIR" status --short
  exit 1
fi

git -C "$REPO_DIR" push -u origin "$BRANCH"

if command -v glab >/dev/null 2>&1; then
  EXISTING="$(glab mr list --source-branch "$BRANCH" 2>/dev/null || true)"
  if printf '%s\n' "$EXISTING" | grep -q '![0-9]'; then
    echo "==> Vorhandener Merge Request:"
    printf '%s\n' "$EXISTING"
  else
    glab mr create \
      --source-branch "$BRANCH" \
      --target-branch main \
      --title "Promote ${VERSION} to stable" \
      --description $'Promotes a tested Borg Backup UI build to the stable channel.\n\nChanges:\n- Release artifact '"${VERSION}"$' is included.\n- borg-backup-ui.plg points to the tested version.\n- Source and shipped package are promoted together.\n\nTests:\n- Tested via test-channel before go-live.\n- Run ./plugin/mr-preflight.sh before merge.'
  fi
else
  cat <<EOF
glab nicht gefunden. Erstelle den Merge Request manuell:
  Source: ${BRANCH}
  Target: main
  Title : Promote ${VERSION} to stable
EOF
fi

echo "==> Vor dem Merge ausfuehren:"
echo "    ./plugin/mr-preflight.sh"
