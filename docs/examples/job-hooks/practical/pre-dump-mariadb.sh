#!/bin/bash
# Practical hook example (#557). Read README.md / README.de.md before enabling.
# Configure the constants below; arguments and inherited credentials are unused.
set -euo pipefail
CONFIGURED="no"
# Transactional tables only; prevent DDL during export. Suggested timeout: 1800 s.
# A root-protected option file INSIDE the container provides backup credentials.
# Exit nonzero blocks backup; only a complete nonempty SQL dump is published.
MOUNT_PATH="/CHANGE_ME"
OUTPUT_DIR="/CHANGE_ME/private-dumps"
CONTAINER="CHANGE_ME"
DATABASE="CHANGE_ME"
CLIENT_CONFIG="/run/secrets/backup-client.cnf"

# Refuse unconfigured scripts and assignment to the wrong hook phase.
[[ "$CONFIGURED" == "yes" ]] || { echo 'Configure this example before use.' >&2; exit 2; }
[[ "${BBUI_HOOK_PHASE:-}" == "pre" ]] || { echo 'Assign this script as Pre.' >&2; exit 2; }

command -v docker >/dev/null
command -v mountpoint >/dev/null
command -v realpath >/dev/null
[[ "$MOUNT_PATH" != / && "$CONTAINER" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]]
[[ -n "$DATABASE" && "$DATABASE" != -* && "$DATABASE" != CHANGE_ME ]]
mountpoint -q -- "$MOUNT_PATH" || { echo 'Expected dump mount is missing.' >&2; exit 1; }
mount_root=$(realpath -e -- "$MOUNT_PATH")
output_root=$(realpath -e -- "$OUTPUT_DIR")
[[ -d "$output_root" && "$output_root" == "$mount_root/"* ]] || { echo 'Dump directory is outside the expected mount.' >&2; exit 1; }
[[ $(stat -c %u -- "$output_root") == "$EUID" && $(stat -c %a -- "$output_root") == 700 ]] || {
    echo 'Dump directory must be owned by the executing user with mode 0700.' >&2; exit 1;
}
umask 077
# Each run owns a new directory. Existing exports are never overwritten/pruned.
work=$(mktemp -d -- "$output_root/mariadb-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXXXX")
# Remove only this invocation's partial file; completed exports remain untouched.
cleanup() {
    # No arguments. Best-effort cleanup on exit; an empty run directory is removed.
    rm -f -- "$work/dump.partial"
    rmdir -- "$work" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
[[ "$CLIENT_CONFIG" == /* ]]
if ! docker exec "$CONTAINER" mariadb-dump "--defaults-extra-file=$CLIENT_CONFIG" \
    --single-transaction --quick --skip-lock-tables --databases "$DATABASE" \
    > "$work/dump.partial" 2>/dev/null; then
    echo 'MariaDB export failed; check container, client configuration and permissions.' >&2
    exit 1
fi
[[ -s "$work/dump.partial" ]] || { echo 'Database export is empty.' >&2; exit 1; }
mv -- "$work/dump.partial" "$work/database.sql"
echo 'Database export completed; include the configured dump directory in backup sources.'
