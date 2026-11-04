#!/bin/bash
# Select/stage Python for independent entrypoints; never modify system Python.
# --select refreshes the stopped service selection; --status prints JSON.
# --exec SCRIPT [ARGS...] preserves a running service's selected interpreter.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
STATE="${BBUI_RUNTIME_STATE:-/run/borg-backup-ui}"
PIDFILE="${BBUI_SERVICE_PIDFILE:-/var/run/borg_backup_ui.pid}"
MODE="${1:---status}"
shift || true
umask 077
install -d -m 0700 "$STATE"
exec 9>"$STATE/python.lock"
flock -w 60 9

fail() {
  echo 'ERROR: No usable Python runtime. Reinstall the Borg Backup UI package and check the service log and available RAM. / Keine nutzbare Python-Laufzeit. Borg Backup UI neu installieren; Dienstprotokoll und freien RAM pruefen.' >&2
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
  [ -r "$STATE/selected-python" ] || fail
  PYTHON="$(sed -n '1p' "$STATE/selected-python")"
  export BBUI_PYTHON_SOURCE="$(sed -n '2p' "$STATE/selected-python")"
  RESULT="$(probe)" || fail
else
  PYTHON="$(command -v python3 || true)"
  export BBUI_PYTHON_SOURCE=external
  RESULT=""
  if [ -n "$PYTHON" ] && [[ "$PYTHON" = /* ]]; then RESULT="$(probe)" || RESULT=""; fi
  if [ -z "$RESULT" ]; then
    echo "External Python absent or incompatible; selecting the bundled runtime. / Mitgelieferte Python-Laufzeit wird verwendet." >&2
    export BBUI_PYTHON_SOURCE=bundled
    META="$ROOT/runtime/python/python-runtime.json"
    [ -f "$META" ] || fail
    HASH="$(sed -n 's/^  "bundle_sha256": "\([0-9a-f]*\)",*$/\1/p' "$META")"
    EXECUTABLE="$(sed -n 's/^  "executable": "\(bin\/python[0-9.]*\)",*$/\1/p' "$META")"
    [[ "$HASH" =~ ^[0-9a-f]{64}$ ]] && [[ "$EXECUTABLE" =~ ^bin/python3\.[0-9]+$ ]] || fail
    BUNDLE="$ROOT/runtime/python/python-runtime.tar.xz"
    echo "$HASH  $BUNDLE" | sha256sum -c --status || fail
    TARGET="$STATE/python/$HASH"
    PYTHON="$TARGET/$EXECUTABLE"
    if [ ! -f "$TARGET/.complete" ]; then
      install -d -m 0700 "$STATE/python"
      TEMP="$(mktemp -d "$STATE/python/staging.XXXXXX")"
      trap 'rm -rf "$TEMP"' EXIT
      tar -xJf "$BUNDLE" -C "$TEMP" --no-same-owner || fail
      # Validate before making the complete tree visible to another entrypoint.
      PYTHON="$TEMP/$EXECUTABLE"
      probe >/dev/null || fail
      touch "$TEMP/.complete"
      if [ -e "$TARGET" ]; then rm -rf "$TARGET"; fi
      mv "$TEMP" "$TARGET"
      trap - EXIT
      PYTHON="$TARGET/$EXECUTABLE"
    fi
    RESULT="$(probe)" || fail
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
