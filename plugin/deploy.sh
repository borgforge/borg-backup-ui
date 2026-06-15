#!/bin/bash
# deploy.sh – Dev-Deploy: bauen + direkt auf Unraid installieren (ohne PLG-Versionscheck)
#
# Verwendung:
#   ./plugin/deploy.sh 192.168.178.23
#
# Voraussetzungen:
#   - SSH-Zugang zu Unraid (root@<IP>)
#   - tar, xz, md5sum lokal installiert

set -euo pipefail

UNRAID_IP="${1:-}"
if [ -z "$UNRAID_IP" ]; then
  echo "FEHLER: Unraid-IP fehlt. Verwendung: $0 <IP>"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
NAME="borg-backup-ui"
PLUGIN_DIR="/boot/config/plugins/${NAME}"

# ── Bauen ─────────────────────────────────────────────────────────────────────
VERSION="$(date +%Y.%m.%d.%H%M)"
echo "==> Baue ${NAME} v${VERSION}"
bash "${SCRIPT_DIR}/build.sh" "${VERSION}"
PKG_FILE="${SCRIPT_DIR}/build/${NAME}-${VERSION}.txz"

# ── Auf Unraid deployen ────────────────────────────────────────────────────────
echo "==> Übertrage nach root@${UNRAID_IP}:${PLUGIN_DIR}/"
ssh "root@${UNRAID_IP}" "mkdir -p '${PLUGIN_DIR}'"
scp "${PKG_FILE}" "root@${UNRAID_IP}:${PLUGIN_DIR}/"

echo "==> Installiere auf Unraid..."
ssh "root@${UNRAID_IP}" "
  # Laufenden Server stoppen
  /etc/rc.d/rc.borg_backup_ui stop 2>/dev/null || true
  sleep 1

  # Paket installieren (überschreibt App-Dateien, behält conf)
  upgradepkg --install-new '${PLUGIN_DIR}/${NAME}-${VERSION}.txz'

  # Conf aus Example ableiten falls nicht vorhanden
  if [ ! -f '${PLUGIN_DIR}/borg_backup_ui.conf' ]; then
    cp '${PLUGIN_DIR}/borg_backup_ui.conf.example' '${PLUGIN_DIR}/borg_backup_ui.conf'
    echo 'Neue borg_backup_ui.conf aus Vorlage erstellt.'
  fi

  # Autostart eintragen (einmalig)
  if ! grep -q 'rc.borg_backup_ui' /boot/config/go 2>/dev/null; then
    echo '' >> /boot/config/go
    echo '# Borg Backup UI' >> /boot/config/go
    echo '/etc/rc.d/rc.borg_backup_ui start' >> /boot/config/go
  fi

  # Neu starten
  /etc/rc.d/rc.borg_backup_ui start
"

echo ""
echo "==> Deploy abgeschlossen: http://${UNRAID_IP}:8765"
