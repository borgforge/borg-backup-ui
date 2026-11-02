#!/bin/bash
# Public preflight reads GitHub evidence; confidential advisories stay local.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ "${1:-}" == "--security" && $# -eq 1 ]]; then
  exec python3 "$SCRIPT_DIR/security_workflow.py" preflight
fi
[[ $# -eq 0 ]] || { echo 'Usage: mr-preflight.sh [--security]' >&2; exit 2; }
python3 "$SCRIPT_DIR/security_workflow.py" guard-public
exec python3 "$SCRIPT_DIR/ci_release.py" preflight
