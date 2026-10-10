#!/bin/bash
# Practical hook example (#557). Read README.md / README.de.md before enabling.
# Configure the constants below; arguments and inherited credentials are unused.
set -euo pipefail
CONFIGURED="no"
# Read-only: check free space on an already mounted local dump/staging filesystem.
# This is a threshold, not an estimate of backup size. Suggested timeout: 30 s.
# Exit 0 permits backup; a missing mount or low free space blocks it.
MOUNT_PATH="/CHANGE_ME"
MIN_FREE_GIB=10

# Refuse unconfigured scripts and assignment to the wrong hook phase.
[[ "$CONFIGURED" == "yes" ]] || { echo 'Configure this example before use.' >&2; exit 2; }
[[ "${BBUI_HOOK_PHASE:-}" == "pre" ]] || { echo 'Assign this script as Pre.' >&2; exit 2; }

command -v mountpoint >/dev/null
[[ "$MOUNT_PATH" != / && "$MIN_FREE_GIB" =~ ^[1-9][0-9]{0,5}$ ]]
mountpoint -q -- "$MOUNT_PATH" || { echo 'Expected staging mount is missing.' >&2; exit 1; }
available_kib=$(LC_ALL=C df -Pk -- "$MOUNT_PATH" | awk 'NR == 2 {print $4}')
[[ "$available_kib" =~ ^[0-9]+$ ]] || { echo 'Cannot read available space.' >&2; exit 1; }
(( available_kib >= MIN_FREE_GIB * 1024 * 1024 )) || { echo 'Insufficient staging space.' >&2; exit 1; }
echo 'Free-space threshold satisfied.'
