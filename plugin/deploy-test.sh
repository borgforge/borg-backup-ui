#!/bin/bash
# Request the complete hosted test publication; never build/publish locally.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
python3 "$SCRIPT_DIR/security_workflow.py" guard-public
[[ $# -ge 1 ]] || { echo 'Usage: deploy-test.sh <version> [--pr number] [--platform target]' >&2; exit 2; }
VERSION="$1"
shift
exec python3 "$SCRIPT_DIR/ci_release.py" dispatch-test --version "$VERSION" "$@"
