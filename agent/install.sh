#!/bin/bash

################################################################################
# Recur Agent Installation Script
# Installs the Recur health check agent on a system
################################################################################

set -euo pipefail

echo "=========================================="
echo "Recur Agent Installation"
echo "=========================================="

# Determine the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Check if running as root
if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root"
    exit 1
fi

# Install dependencies
echo ""
echo "[1/5] Installing dependencies..."
if command -v apt-get &> /dev/null; then
    apt-get update -qq
    apt-get install -y -qq curl python3 python3-pip
    pip3 install -q pyyaml
elif command -v yum &> /dev/null; then
    yum install -y -q curl python3 python3-pip
    pip3 install -q pyyaml
else
    echo "ERROR: Unsupported package manager"
    exit 1
fi

# Create directories
echo "[2/5] Creating directories..."
mkdir -p /etc/recur
mkdir -p /var/lib/recur
mkdir -p /var/log/recur
chmod 755 /etc/recur /var/lib/recur /var/log/recur

# Install agent scripts
echo "[3/5] Installing agent scripts..."
install -m 755 "$SCRIPT_DIR/recur-agent.sh" /usr/local/bin/recur-agent
install -m 755 "$SCRIPT_DIR/health_check_utils.py" /usr/local/bin/recur-health-check
chmod +x /usr/local/bin/recur-agent /usr/local/bin/recur-health-check

# Install example configuration
echo "[4/5] Installing configuration..."
if [[ -f /etc/recur/config.yaml ]]; then
    cp /etc/recur/config.yaml /etc/recur/config.yaml.bak
    echo "Backed up existing configuration to /etc/recur/config.yaml.bak"
fi
install -m 644 "$SCRIPT_DIR/config.example.yaml" /etc/recur/config.yaml

# Install systemd service
echo "[5/5] Installing systemd service..."
cat > /etc/systemd/system/recur-agent.service <<'EOF'
[Unit]
Description=Recur Health Check Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
ExecStart=/usr/local/bin/recur-agent run
Restart=always
RestartSec=30
StandardOutput=journal
StandardError=journal

Environment="RECUR_CONFIG_FILE=/etc/recur/config.yaml"
Environment="RECUR_SERVER_URL=http://localhost:8000"
Environment="RECUR_LOG_FILE=/var/log/recur/agent.log"

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload

echo ""
echo "=========================================="
echo "Installation Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Edit configuration: sudo vim /etc/recur/config.yaml"
echo "2. Set server URL: export RECUR_SERVER_URL=http://your-server:8000"
echo "3. Start the agent: sudo systemctl start recur-agent"
echo "4. Enable on boot: sudo systemctl enable recur-agent"
echo "5. Check status: sudo systemctl status recur-agent"
echo "6. View logs: sudo tail -f /var/log/recur/agent.log"
echo ""
