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
release_build_changed=0
deferred_release_allowed="${BORG_UI_ALLOW_DEFERRED_RELEASE:-0}"

while IFS= read -r file; do
  case "${file}" in
    borg_backup_ui.py|borg_backup_ui.conf.example|api/*.py|runtime/*|runtime/**|ui/*|ui/**|plugin/*.page|plugin/rc.borg_backup_ui|borg-backup-ui.plg)
      plugin_code_changed=1
      ;;
  esac
  case "${file}" in
    borg_backup_ui.py|borg-backup-ui.plg|releases/borg-backup-ui-*.txz)
      release_build_changed=1
      ;;
  esac
done <<< "${changed_files}"

if [[ "${plugin_code_changed}" -eq 1 && "${release_build_changed}" -eq 0 && "${deferred_release_allowed}" == "1" ]]; then
  echo "Hinweis: Plugin-Code wurde geändert, aber kein Release-Build ist im Branch enthalten."
  echo "        Release-Build ist fuer ein freigegebenes Umbrella-Feature bewusst aufgeschoben."
elif [[ "${plugin_code_changed}" -eq 1 && "${release_build_changed}" -eq 0 ]]; then
  echo "Fehler: Plugin-Code wurde geändert, aber kein Release-Build ist im Branch enthalten."
  echo "Bitte ./plugin/build.sh ausführen und die entstehenden Änderungen committen."
  echo "Erwartet werden typischerweise:"
  echo "  - borg_backup_ui.py"
  echo "  - borg-backup-ui.plg"
  echo "  - releases/borg-backup-ui-<version>.txz"
  exit 1
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
