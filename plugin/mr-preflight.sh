#!/bin/bash
set -euo pipefail

# Preflight check before creating/pushing a PR.
# Usage:
#   ./plugin/mr-preflight.sh

branch="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$branch" == "main" || "$branch" == "master" ]]; then
  echo "Fehler: Du bist auf '$branch'. Bitte auf einem Feature/Hotfix-Branch arbeiten."
  exit 1
fi

echo "==> Hole origin/main"
git fetch origin main >/dev/null 2>&1 || git fetch origin master >/dev/null 2>&1

echo "==> Python-Syntax prüfen"
python3 -m py_compile borg_backup_ui.py api/*.py runtime/lib/*.py runtime/scripts/*.py

echo "==> Tests ausführen"
pytest -q

base_ref="origin/main"
if ! git show-ref --verify --quiet refs/remotes/origin/main; then
  base_ref="origin/master"
fi

echo "==> Prüfe Diff gegen ${base_ref}"
if git diff --quiet "${base_ref}...HEAD"; then
  echo "Fehler: Kein Delta gegen ${base_ref}. Ein PR haette keine Aenderungen."
  exit 1
fi

echo "==> Prüfe Release-Regel für Plugin-Code"
changed_files="$(git diff --name-only "${base_ref}...HEAD")"
plugin_code_changed=0
release_manifest_changed=0
release_artifact_changed=0
release_pr=0
case "${branch}" in
  codex/release-*|release-*)
    release_pr=1
    ;;
esac

while IFS= read -r file; do
  case "${file}" in
    borg_backup_ui.py|borg_backup_ui.conf.example|api/*.py|runtime/*|runtime/**|ui/*|ui/**|plugin/*.page|plugin/rc.borg_backup_ui|borg-backup-ui.plg)
      plugin_code_changed=1
      ;;
  esac
  case "${file}" in
    borg-backup-ui.plg)
      release_manifest_changed=1
      ;;
    releases/borg-backup-ui-*.txz)
      release_artifact_changed=1
      ;;
  esac
done <<< "${changed_files}"

release_build_changed=0
if [[ "${release_manifest_changed}" -eq 1 && "${release_artifact_changed}" -eq 1 ]]; then
  release_build_changed=1
fi

if [[ "${release_pr}" -eq 0 && "${release_manifest_changed}" -eq 1 ]]; then
  echo "Fehler: borg-backup-ui.plg darf nur in einem separaten Release-PR geaendert werden."
  echo "Bitte Feature-/Fix-PR ohne Stable-Manifest erstellen und spaeter ./plugin/promote-release.sh <version> nutzen."
  exit 1
fi

if [[ "${release_pr}" -eq 0 && "${release_artifact_changed}" -eq 1 ]]; then
  echo "Fehler: releases/borg-backup-ui-*.txz darf nur in einem separaten Release-PR geaendert werden."
  echo "Bitte Test-Channel-Artefakte nicht in Feature-/Fix-PRs committen."
  exit 1
fi

if [[ "${release_pr}" -eq 1 && "${release_build_changed}" -eq 0 ]]; then
  echo "Fehler: Release-PR ohne vollstaendige Stable-Artefakte."
  echo "Erwartet werden borg-backup-ui.plg und releases/borg-backup-ui-<version>.txz."
  exit 1
fi

if [[ "${plugin_code_changed}" -eq 1 && "${release_pr}" -eq 0 ]]; then
  echo "Hinweis: Plugin-Code wurde geaendert. Stable-Artefakte gehoeren nicht in diesen PR."
  echo "        Test-Channel-Deploy separat verifizieren; Stable spaeter per eigenem Release-PR."
fi

echo "==> Prüfe, ob Branch auf origin existiert"
if ! git ls-remote --heads origin "${branch}" | grep -q .; then
  echo "Hinweis: Branch ist noch nicht auf origin. Bitte zuerst pushen:"
  echo "  git push -u origin ${branch}"
  exit 1
fi

local_sha="$(git rev-parse HEAD)"
remote_sha="$(git ls-remote --heads origin "${branch}" | awk '{print $1}')"
if [[ -z "${remote_sha}" || "${local_sha}" != "${remote_sha}" ]]; then
  echo "Fehler: Lokaler Stand ist nicht auf origin (${branch})."
  echo "  local : ${local_sha}"
  echo "  remote: ${remote_sha:-<none>}"
  echo "Bitte pushen:"
  echo "  git push origin ${branch}"
  exit 1
fi

echo "OK: Preflight bestanden."
echo "- Branch: ${branch}"
echo "- Base  : ${base_ref}"
echo "- Delta : vorhanden"
echo "- Push  : synchron"
