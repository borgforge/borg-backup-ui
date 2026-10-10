#!/bin/bash
# Practical hook example (#557). Read README.md / README.de.md before enabling.
# Configure the constants below; arguments and inherited credentials are unused.
set -euo pipefail
CONFIGURED="no"
# Send one WOL packet if the target TCP port is closed, then wait at most WAIT_SECONDS.
# Requires Python 3, IPv4 addresses and a configured WOL target; TCP is not an
# authenticated service check. Exit nonzero blocks backup. Suggested timeout: 150 s.
MAC_ADDRESS="CHANGE_ME"
BROADCAST_IP="192.0.2.255"
SERVER_IP="192.0.2.10"
SERVER_PORT=22
WAIT_SECONDS=120

# Refuse unconfigured scripts and assignment to the wrong hook phase.
[[ "$CONFIGURED" == "yes" ]] || { echo 'Configure this example before use.' >&2; exit 2; }
[[ "${BBUI_HOOK_PHASE:-}" == "pre" ]] || { echo 'Assign this script as Pre.' >&2; exit 2; }

command -v python3 >/dev/null
python3 - "$MAC_ADDRESS" "$BROADCAST_IP" "$SERVER_IP" "$SERVER_PORT" "$WAIT_SECONDS" <<'PYTHON'
import ipaddress
import re
import socket
import sys
import time


def ready(host, port, timeout):
    """Return whether an IPv4 TCP connection succeeds within timeout seconds."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def main():
    """Validate constants, optionally send WOL, and bound the TCP readiness wait."""
    mac, broadcast, host, port_text, wait_text = sys.argv[1:]
    if not re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", mac):
        raise ValueError("Invalid MAC address")
    broadcast = str(ipaddress.IPv4Address(broadcast))
    host = str(ipaddress.IPv4Address(host))
    port, seconds = int(port_text), int(wait_text)
    if not 1 <= port <= 65535 or not 1 <= seconds <= 3600:
        raise ValueError("Invalid port or wait duration")
    deadline = time.monotonic() + seconds
    if ready(host, port, min(2, seconds)):
        print("Server TCP port is already reachable.")
        return 0
    packet = b"\xff" * 6 + bytes.fromhex(mac.replace(":", "")) * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(2)
        sock.sendto(packet, (broadcast, 9))
    while (remaining := deadline - time.monotonic()) > 0:
        if ready(host, port, min(2, remaining)):
            print("Server TCP port is reachable.")
            return 0
        time.sleep(min(1, max(0, deadline - time.monotonic())))
    print("Server readiness timed out.", file=sys.stderr)
    return 1


try:
    sys.exit(main())
except (ValueError, OSError):
    print("Wake configuration or network operation failed.", file=sys.stderr)
    sys.exit(1)
PYTHON
