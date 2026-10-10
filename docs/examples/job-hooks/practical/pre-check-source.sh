#!/bin/bash
# Practical hook example (#557). Read README.md / README.de.md before enabling.
# Configure the constants below; arguments and inherited credentials are unused.
set -euo pipefail
CONFIGURED="no"
# Read-only: require this exact mount and a pre-created identity marker.
# Exit 0 permits backup; any other exit blocks it. Suggested timeout: 30 s.
MOUNT_PATH="/CHANGE_ME"
SOURCE_PATH="/CHANGE_ME/source"
MARKER_NAME=".backup-source-id"
EXPECTED_ID="CHANGE_ME"

# Refuse unconfigured scripts and assignment to the wrong hook phase.
[[ "$CONFIGURED" == "yes" ]] || { echo 'Configure this example before use.' >&2; exit 2; }
[[ "${BBUI_HOOK_PHASE:-}" == "pre" ]] || { echo 'Assign this script as Pre.' >&2; exit 2; }

command -v mountpoint >/dev/null
command -v realpath >/dev/null
[[ "$MOUNT_PATH" != / && "$EXPECTED_ID" != CHANGE_ME && -n "$EXPECTED_ID" ]]
[[ "$MARKER_NAME" != */* && "$MARKER_NAME" != . && "$MARKER_NAME" != .. && -n "$MARKER_NAME" ]]
mountpoint -q -- "$MOUNT_PATH" || { echo 'Expected source mount is missing.' >&2; exit 1; }
mount_root=$(realpath -e -- "$MOUNT_PATH")
source_root=$(realpath -e -- "$SOURCE_PATH")
[[ -d "$source_root" && ( "$source_root" == "$mount_root" || "$source_root" == "$mount_root/"* ) ]] || {
    echo 'Source is outside the expected mount.' >&2; exit 1;
}
marker="$source_root/$MARKER_NAME"
[[ -f "$marker" && ! -L "$marker" && -r "$marker" ]] || { echo 'Source marker is missing or unsafe.' >&2; exit 1; }
[[ $(stat -c %s -- "$marker") -le 256 ]] || { echo 'Source marker is too large.' >&2; exit 1; }
[[ "$(cat -- "$marker")" == "$EXPECTED_ID" ]] || { echo 'Source identity does not match.' >&2; exit 1; }
echo 'Source mount and identity verified.'
