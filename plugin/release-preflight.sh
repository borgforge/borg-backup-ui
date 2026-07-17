#!/bin/bash
# Artifact-only preflight for a dedicated stable release pull request.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
branch="$(git -C "$REPO_DIR" branch --show-current)"

case "$branch" in
  codex/release-*|release-*) ;;
  *)
    echo "Fehler: release-preflight.sh darf nur auf einem Release-Branch laufen." >&2
    exit 1
    ;;
esac

echo "==> Hole origin/main und origin/test-channel"
git -C "$REPO_DIR" fetch origin main test-channel >/dev/null 2>&1

echo "==> Pruefe sauberen Arbeitsbaum"
if [[ -n "$(git -C "$REPO_DIR" status --porcelain=v1 --untracked-files=all)" ]]; then
  echo "Fehler: Der Release-Arbeitsbaum ist nicht sauber." >&2
  git -C "$REPO_DIR" status --short
  exit 1
fi

echo "==> Pruefe Release-Delta"
changed_files="$(git -C "$REPO_DIR" diff --name-only origin/main...HEAD)"
changed_status="$(git -C "$REPO_DIR" diff --name-status origin/main...HEAD)"
if [[ -z "$changed_files" ]]; then
  echo "Fehler: Der Release-PR enthaelt keine Aenderungen." >&2
  exit 1
fi
if ! grep -Fxq "borg-backup-ui.plg" <<<"$changed_files"; then
  echo "Fehler: Stable-Manifest fehlt im Release-PR." >&2
  exit 1
fi
if ! grep -Eq '^releases/borg-backup-ui-[^/]+\.txz$' <<<"$changed_files"; then
  echo "Fehler: Stable-Paket fehlt im Release-PR." >&2
  exit 1
fi

while IFS= read -r file; do
  case "$file" in
    borg-backup-ui.plg|borg_backup_ui.py|releases/borg-backup-ui-*.txz|release-notes/pending/*) ;;
    *)
      echo "Fehler: Unzulaessige Datei im reinen Release-PR: $file" >&2
      exit 1
      ;;
  esac
done <<<"$changed_files"

while IFS=$'\t' read -r status file _; do
  case "$file" in
    release-notes/pending/*)
      if [[ "$status" != "D" ]]; then
        echo "Fehler: Release-Note-Fragmente duerfen im Release-PR nur geloescht werden: $file ($status)" >&2
        exit 1
      fi
      ;;
  esac
done <<<"$changed_status"

echo "==> Pruefe synchronen Remote-Stand"
remote_sha="$(git -C "$REPO_DIR" ls-remote --heads origin "$branch" | awk '{print $1}')"
local_sha="$(git -C "$REPO_DIR" rev-parse HEAD)"
if [[ -z "$remote_sha" || "$remote_sha" != "$local_sha" ]]; then
  echo "Fehler: Release-Branch ist nicht exakt auf origin gepusht." >&2
  exit 1
fi

version="$(sed -n 's/.*<!ENTITY version   "\([^"]*\)">.*/\1/p' "$REPO_DIR/borg-backup-ui.plg" | head -n1)"
package="$REPO_DIR/releases/borg-backup-ui-${version}.txz"
test_manifest="$(git -C "$REPO_DIR" show origin/test-channel:borg-backup-ui-test.plg)"
test_version="$(sed -n 's/.*<!ENTITY version   "\([^"]*\)">.*/\1/p' <<<"$test_manifest" | head -n1)"
if [[ -z "$version" || "$version" != "$test_version" ]]; then
  echo "Fehler: Stable-Version ${version:-<leer>} entspricht nicht dem aktuellen Test-Channel ${test_version:-<leer>}." >&2
  exit 1
fi

mkdir -p "$REPO_DIR/.release-tmp"
test_package="$(mktemp "$REPO_DIR/.release-tmp/release-preflight-${version}.XXXXXX.txz")"
trap 'rm -f "$test_package"' EXIT
git -C "$REPO_DIR" show "origin/test-channel:releases/borg-backup-ui-${version}.txz" >"$test_package"
stable_sha="$(sha256sum "$package" | awk '{print $1}')"
test_sha="$(sha256sum "$test_package" | awk '{print $1}')"
if [[ "$stable_sha" != "$test_sha" ]]; then
  echo "Fehler: Stable-Paket ist nicht byte-identisch zum getesteten Test-Channel-Paket." >&2
  exit 1
fi

echo "==> Pruefe Manifest, URLs, MD5, Paketinhalt, Provenienz und Retention"
python3 "$SCRIPT_DIR/release_workflow.py" verify-release \
  --repo "$REPO_DIR" \
  --main-ref origin/main >/dev/null

echo "OK: Release-Artefakt-Preflight bestanden (keine erneute Volltestsuite)."
