#!/bin/bash

################################################################################
# Recur Agent Uninstallation Script
# Reverses agent/install.sh: stops the service, removes the systemd unit,
# the installed agent files (including vendored PyYAML), and configuration.
#
# Usage:
#   sudo ./agent/uninstall.sh [-y] [-k]
#     -y, --yes            Do not prompt for confirmation
#     -k, --keep-config    Keep /etc/recur (config.yaml and agent.env)
################################################################################

set -euo pipefail

echo "=========================================="
echo "Recur Agent Uninstallation"
echo "=========================================="

FORCE=0
KEEP_CONFIG=0

usage() {
    echo "Usage: $0 [-y|--yes] [-k|--keep-config]"
}

for arg in "$@"; do
    case "$arg" in
        -y|--yes)
            FORCE=1
            ;;
        -k|--keep-config)
            KEEP_CONFIG=1
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "ERROR: Unknown option: $arg"
            usage
            exit 1
            ;;
    esac
done

# Check if running as root
if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root"
    exit 1
fi

if (( FORCE )); then
    echo "Uninstalling without confirmation (-y)"
else
    if (( KEEP_CONFIG )); then
        read -r -p "This will remove the Recur agent service, files and logs (keeping /etc/recur config). Continue? [y/N] " ans
    else
        read -r -p "This will remove the Recur agent including its configuration in /etc/recur. Continue? [y/N] " ans
    fi
    if [[ "$ans" != "y" && "$ans" != "Y" ]]; then
        echo "Aborted."
        exit 1
    fi
fi

# Stop and remove the systemd service (if present)
echo ""
echo "[1/4] Stopping and removing service..."
if command -v systemctl &> /dev/null && [[ -f /etc/systemd/system/recur-agent.service ]]; then
    systemctl stop recur-agent 2>/dev/null || true
    systemctl disable recur-agent 2>/dev/null || true
    rm -f /etc/systemd/system/recur-agent.service
    systemctl daemon-reload
    echo "Service stopped and removed"
else
    echo "No systemd service found (nothing to stop)"
fi

# Remove agent binaries and libraries
echo "[2/4] Removing agent files..."
rm -f /usr/local/bin/recur-agent /usr/local/bin/recur-health-check
rm -rf /usr/local/lib/recur
echo "Removed /usr/local/lib/recur and /usr/local/bin symlinks"

# Remove configuration
echo "[3/4] Removing configuration..."
if (( KEEP_CONFIG )); then
    echo "Keeping /etc/recur (config.yaml and agent.env preserved)"
else
    rm -rf /etc/recur
    echo "Removed /etc/recur"
fi

# Remove runtime data and logs
echo "[4/4] Removing runtime data and logs..."
rm -rf /var/lib/recur
rm -f /var/log/recur/agent.log /var/log/recur-agent.log
rmdir /var/log/recur 2>/dev/null || true
echo "Removed runtime data and logs"

echo ""
echo "=========================================="
echo "Uninstallation Complete!"
echo "=========================================="
echo ""
if (( KEEP_CONFIG )); then
    echo "Note: configuration was kept in /etc/recur"
else
    echo "The agent, its configuration, data and logs have been removed."
fi
echo ""
