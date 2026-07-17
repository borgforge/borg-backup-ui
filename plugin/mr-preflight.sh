#!/bin/bash
set -euo pipefail

# Full source preflight for feature/fix branches.
# Usage:
#   ./plugin/mr-preflight.sh

branch="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$branch" == "main" || "$branch" == "master" ]]; then
  echo "Fehler: Du bist auf '$branch'. Bitte auf einem Feature/Hotfix-Branch arbeiten."
  exit 1
fi

case "${branch}" in
  codex/release-*|release-*)
    echo "==> Release-Branch erkannt; pruefe nur Release-Artefakte"
    exec "$(dirname "$0")/release-preflight.sh"
    ;;
esac

echo "==> Hole origin/main"
git fetch origin main >/dev/null 2>&1 || git fetch origin master >/dev/null 2>&1

base_ref="origin/main"
if ! git show-ref --verify --quiet refs/remotes/origin/main; then
  base_ref="origin/master"
fi

echo "==> Pruefe sauberen Arbeitsbaum"
if [[ -n "$(git status --porcelain=v1 --untracked-files=all)" ]]; then
  echo "Fehler: Der Arbeitsbaum ist nicht sauber. Preflight gilt nur fuer einen exakten Commit."
  git status --short
  exit 1
fi

echo "==> Prüfe Diff gegen ${base_ref}"
if git diff --quiet "${base_ref}...HEAD"; then
  echo "Fehler: Kein Delta gegen ${base_ref}. Ein PR haette keine Aenderungen."
  exit 1
fi

echo "==> Pruefe Trennung von Implementierung und Stable-Artefakten"
changed_files="$(git diff --name-only "${base_ref}...HEAD")"
plugin_code_changed=0

while IFS= read -r file; do
  case "${file}" in
    borg_backup_ui.py|borg_backup_ui.conf.example|api/*.py|runtime/*|runtime/**|ui/*|ui/**|plugin/*.page|plugin/rc.borg_backup_ui)
      plugin_code_changed=1
      ;;
  esac
done <<< "${changed_files}"

python3 "$(dirname "$0")/release_workflow.py" verify-implementation-delta \
  --repo "$(git rev-parse --show-toplevel)" \
  --base-ref "${base_ref}"

if [[ "${plugin_code_changed}" -eq 1 ]]; then
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

echo "==> Guenstige Vorpruefungen bestanden"

echo "==> Python-Syntax pruefen"
python3 -m py_compile borg_backup_ui.py api/*.py runtime/lib/*.py runtime/scripts/*.py plugin/release_workflow.py

echo "==> Tests ausfuehren"
pytest -q

echo "==> Commitgebundene Preflight-Attestierung schreiben"
python3 "$(dirname "$0")/release_workflow.py" write-attestation \
  --repo "$(git rev-parse --show-toplevel)" \
  --base-ref "${base_ref}" >/dev/null
attestation="$(git rev-parse --git-path borg-backup-ui/preflight.json)"

echo "OK: Preflight bestanden."
echo "- Branch: ${branch}"
echo "- Base  : ${base_ref}"
echo "- Delta : vorhanden"
echo "- Push  : synchron"
echo "- Test  : bestanden"
echo "- Attest: ${attestation}"
