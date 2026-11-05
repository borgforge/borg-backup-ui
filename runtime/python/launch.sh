#!/bin/bash
# Select/stage Python for independent entrypoints; never modify system Python.
# --select refreshes the stopped service selection; --status prints JSON.
# --exec SCRIPT [ARGS...] preserves a running service's selected interpreter.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
STATE="${BBUI_RUNTIME_STATE:-/run/borg-backup-ui}"
# Unraid mounts /run with noexec; executable payload belongs in its /usr overlay.
RUNTIME_ROOT="${BBUI_RUNTIME_ROOT:-/usr/local/lib/borg-backup-ui/python}"
PIDFILE="${BBUI_SERVICE_PIDFILE:-/var/run/borg_backup_ui.pid}"
MODE="${1:---status}"
shift || true
umask 077
install -d -m 0700 "$STATE"
exec 9>"$STATE/python.lock"
flock -w 60 9

# Reasons passed here are fixed diagnostic strings, never raw interpreter output.
fail() {
  local reason="${1:-No usable Python runtime. Check the service log and available RAM. Reinstall Borg Backup UI only if its payload is missing or corrupt.}"
  echo "ERROR: $reason" >&2
  if [ "$MODE" = --status ]; then
    printf '{"ok":false,"path":"","version":"","source":"","reason":"%s","min_version":"3.10"}\n' "$reason"
  fi
  exit 1
}

# Probe with a deadline and without host startup customizations/site-packages.
probe() {
  timeout 20 "$PYTHON" -E -s -S -B "$ROOT/runtime/python/probe.py" "$ROOT" 2>/dev/null
}

# An active service pins independent helpers too; do not silently switch after
# external Python is removed or a second provider appears during its lifetime.
RUNNING=0
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then RUNNING=1; fi
if [ "$RUNNING" = 1 ]; then
  [ -r "$STATE/selected-python" ] || fail "Running service has no Python selection. Restart Borg Backup UI."
  PYTHON="$(sed -n '1p' "$STATE/selected-python")"
  export BBUI_PYTHON_SOURCE="$(sed -n '2p' "$STATE/selected-python")"
  RESULT="$(probe)" || fail "Selected Python is unavailable while the service is running. Restart Borg Backup UI to select its private runtime."
else
  PYTHON="$(command -v python3 || true)"
  if [ -n "$PYTHON" ]; then PYTHON="$(readlink -f -- "$PYTHON")" || PYTHON=""; fi
  export BBUI_PYTHON_SOURCE=external
  RESULT=""
  if [ -n "$PYTHON" ] && [[ "$PYTHON" = /* ]]; then RESULT="$(probe)" || RESULT=""; fi
  if [ -z "$RESULT" ]; then
    echo "External Python absent or incompatible; selecting the bundled runtime. / Mitgelieferte Python-Laufzeit wird verwendet." >&2
    export BBUI_PYTHON_SOURCE=bundled
    META="$ROOT/runtime/python/python-runtime.json"
    [ -f "$META" ] || fail "Private Python metadata is missing. Reinstall Borg Backup UI."
    HASH="$(sed -n 's/^  "bundle_sha256": "\([0-9a-f]*\)",*$/\1/p' "$META")"
    EXECUTABLE="$(sed -n 's/^  "executable": "\(bin\/python[0-9.]*\)",*$/\1/p' "$META")"
    [[ "$HASH" =~ ^[0-9a-f]{64}$ ]] && [[ "$EXECUTABLE" =~ ^bin/python3\.[0-9]+$ ]] || fail
    BUNDLE="$ROOT/runtime/python/python-runtime.tar.xz"
    echo "$HASH  $BUNDLE" | sha256sum -c --status || fail "Private Python bundle is missing or corrupt. Reinstall Borg Backup UI."
    TARGET="$RUNTIME_ROOT/$HASH"
    PYTHON="$TARGET/$EXECUTABLE"
    if [ ! -f "$TARGET/.complete" ]; then
      install -d -m 0700 "$RUNTIME_ROOT" || fail "Cannot create the private Python directory. Check its filesystem and free space."
      TEMP="$(mktemp -d "$RUNTIME_ROOT/staging.XXXXXX")" || fail "Cannot stage private Python. Check available space."
      trap 'rm -rf "$TEMP"' EXIT
      # Test direct execution before unpacking, so noexec has a useful diagnosis.
      printf '#!/bin/sh\nexit 0\n' > "$TEMP/exec-check"
      chmod 700 "$TEMP/exec-check"
      "$TEMP/exec-check" 2>/dev/null || fail "Private Python filesystem does not permit execution. Check noexec mount options and permissions."
      rm "$TEMP/exec-check"
      echo "Borg Backup UI: extracting private Python into its executable runtime directory..." >&2
      tar -xJf "$BUNDLE" -C "$TEMP" --no-same-owner || fail "Cannot extract private Python. Check available space and the bundle."
      # Validate before making the complete tree visible to another entrypoint.
      PYTHON="$TEMP/$EXECUTABLE"
      probe >/dev/null || fail "Private Python compatibility check failed after extraction. Check native libraries and the service log."
      touch "$TEMP/.complete"
      if [ -e "$TARGET" ]; then rm -rf "$TARGET"; fi
      mv "$TEMP" "$TARGET"
      trap - EXIT
      PYTHON="$TARGET/$EXECUTABLE"
    else
      echo "Borg Backup UI: reusing the extracted private Python runtime." >&2
    fi
    RESULT="$(probe)" || fail "Extracted private Python is not executable or failed its compatibility check."
  fi
fi
case "$MODE" in
  --select)
    printf '%s\n%s\n' "$PYTHON" "$BBUI_PYTHON_SOURCE" > "$STATE/selected-python.new"
    mv "$STATE/selected-python.new" "$STATE/selected-python"
    printf '%s\n' "$PYTHON"
    ;;
  --status) printf '%s\n' "$RESULT" ;;
  --exec)
    # Unlock before running a long-lived application or worker.
    flock -u 9
    exec 9>&-
    exec "$PYTHON" -E -s -S -B "$@"
    ;;
  *) echo 'Usage: launch.sh --select|--status|--exec SCRIPT [ARGS...]' >&2; exit 2 ;;
esac
