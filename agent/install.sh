#!/bin/bash

################################################################################
# Recur Agent Installation Script
# Installs the Recur health check agent on a system
#
# Runtime requirement: python3 only. PyYAML is vendored (agent/vendor/), so
# no pip or OS package access is needed on air-gapped hosts.
#
# Works in both modes:
#   - Local: run from a repository checkout (agent files sit next to this
#     script and are installed as-is)
#   - Remote: curl -s <raw URL>/agent/install.sh | sudo bash
#     (the script is read from stdin, so the companion files are downloaded
#     from the repository; curl or wget is used for that download)
################################################################################

set -euo pipefail

echo "=========================================="
echo "Recur Agent Installation"
echo "=========================================="

# Determine the directory where this script is located (the CWD when the
# script is piped via curl, since BASH_SOURCE is unset/empty in that case;
# the :- guard keeps this safe under `set -u` on bash < 4.4)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-}")" && pwd)"

# Base URL used to fetch the companion agent files when they are not present
# locally (piped install). Override with RECUR_REPO_BASE_URL to install from
# a mirror or fork.
RECUR_REPO_BASE="${RECUR_REPO_BASE_URL:-https://raw.githubusercontent.com/mvineetmenon/Recur/main}"

# Companion files required from the agent/ directory
AGENT_FILES=("recur_agent.py" "health_check_utils.py" "_bootstrap.py" "config.example.yaml")

# Vendored PyYAML (pure Python, MIT licensed) — the agent's only
# non-stdlib dependency, bundled so pip/OS repos are not required.
VENDOR_FILES=(
    "yaml/__init__.py" "yaml/composer.py" "yaml/constructor.py" "yaml/cyaml.py"
    "yaml/dumper.py" "yaml/emitter.py" "yaml/error.py" "yaml/events.py"
    "yaml/loader.py" "yaml/nodes.py" "yaml/parser.py" "yaml/reader.py"
    "yaml/representer.py" "yaml/resolver.py" "yaml/scanner.py"
    "yaml/serializer.py" "yaml/tokens.py" "LICENSE"
)

# Check if running as root
if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root"
    exit 1
fi

# Check dependencies: python3 is the only runtime requirement.
echo ""
echo "[1/5] Checking dependencies..."
if ! command -v python3 &> /dev/null; then
    echo "python3 not found; attempting installation..."
    if command -v apt-get &> /dev/null; then
        apt-get update -qq
        apt-get install -y -qq python3
    elif command -v yum &> /dev/null; then
        yum install -y -q python3
    elif command -v dnf &> /dev/null; then
        dnf install -y -q python3
    fi
fi
if ! command -v python3 &> /dev/null; then
    echo "ERROR: python3 is required but could not be installed"
    exit 1
fi
echo "python3: $(python3 --version 2>&1)"

# Create directories
echo "[2/5] Creating directories..."
mkdir -p /etc/recur
mkdir -p /var/lib/recur
mkdir -p /var/log/recur
chmod 755 /etc/recur /var/lib/recur /var/log/recur

# Resolve where the companion agent files come from: this script's directory
# when running from a checkout, otherwise a temp dir populated from the repo.
resolve_agent_sources() {
    local f missing=()
    for f in "${AGENT_FILES[@]}"; do
        [[ -f "$SCRIPT_DIR/$f" ]] || missing+=("$f")
    done
    for f in "${VENDOR_FILES[@]}"; do
        [[ -f "$SCRIPT_DIR/vendor/$f" ]] || missing+=("vendor/$f")
    done

    if (( ${#missing[@]} == 0 )); then
        AGENT_SRC_DIR="$SCRIPT_DIR"
        return 0
    fi

    # A downloader is needed for the piped-install path.
    if ! command -v curl &> /dev/null && ! command -v wget &> /dev/null; then
        if command -v apt-get &> /dev/null; then
            apt-get install -y -qq curl
        elif command -v yum &> /dev/null; then
            yum install -y -q curl
        elif command -v dnf &> /dev/null; then
            dnf install -y -q curl
        fi
    fi
    if ! command -v curl &> /dev/null && ! command -v wget &> /dev/null; then
        echo "ERROR: curl or wget is required to download the agent files"
        exit 1
    fi

    AGENT_SRC_DIR="$(mktemp -d)"
    trap 'rm -rf "$AGENT_SRC_DIR"' EXIT
    for f in "${missing[@]}"; do
        echo "Downloading agent/$f from the repository..."
        if command -v curl &> /dev/null; then
            curl -fsSL --retry 3 "$RECUR_REPO_BASE/agent/$f" -o "$AGENT_SRC_DIR/$f"
        else
            wget -q -O "$AGENT_SRC_DIR/$f" "$RECUR_REPO_BASE/agent/$f"
        fi
    done
}

# Install agent scripts (lib dir keeps the python files + vendored yaml next
# to the agent; /usr/local/bin holds symlinks so the agent works from any
# PATH location)
echo "[3/5] Installing agent scripts..."
resolve_agent_sources
mkdir -p /usr/local/lib/recur
install -m 755 "$AGENT_SRC_DIR/recur_agent.py" /usr/local/lib/recur/recur_agent.py
install -m 755 "$AGENT_SRC_DIR/health_check_utils.py" /usr/local/lib/recur/health_check_utils.py
install -m 644 "$AGENT_SRC_DIR/_bootstrap.py" /usr/local/lib/recur/_bootstrap.py
mkdir -p /usr/local/lib/recur/vendor
cp -r "$AGENT_SRC_DIR/vendor/." /usr/local/lib/recur/vendor/
chmod -R a+rX /usr/local/lib/recur/vendor
ln -sf /usr/local/lib/recur/recur_agent.py /usr/local/bin/recur-agent
ln -sf /usr/local/lib/recur/health_check_utils.py /usr/local/bin/recur-health-check

# Install example configuration
echo "[4/5] Installing configuration..."
if [[ -f /etc/recur/config.yaml ]]; then
    cp /etc/recur/config.yaml /etc/recur/config.yaml.bak
    echo "Backed up existing configuration to /etc/recur/config.yaml.bak"
fi
install -m 644 "$AGENT_SRC_DIR/config.example.yaml" /etc/recur/config.yaml

# Install environment overrides file (systemd EnvironmentFile; existing file is kept)
if [[ -f /etc/recur/agent.env ]]; then
    echo "Keeping existing /etc/recur/agent.env"
else
    cat > /etc/recur/agent.env <<'ENVEOF'
# Recur agent environment overrides.
# Uncomment and adjust as needed, then apply with:
#   sudo systemctl daemon-reload
#
# RECUR_AGENT_SERVER_URL=http://your-server:8000
# RECUR_AGENT_ID=agent-01
# RECUR_AGENT_LOG_FILE=/var/log/recur/agent.log
#
# Auth: the agent stores its server-issued token in this file (0600).
# RECUR_AGENT_TOKEN_FILE=/etc/recur/agent.token
# Required on first registration only, when the server is configured with
# RECUR_ENROLLMENT_TOKEN (ask the server operator for the value):
# RECUR_AGENT_ENROLLMENT_TOKEN=<enrollment token>
ENVEOF
    chmod 644 /etc/recur/agent.env
fi

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

Environment="RECUR_AGENT_CONFIG_FILE=/etc/recur/config.yaml"
Environment="RECUR_AGENT_SERVER_URL=http://localhost:8000"
Environment="RECUR_AGENT_LOG_FILE=/var/log/recur/agent.log"
# User overrides (wins over the Environment= defaults above; optional file)
EnvironmentFile=-/etc/recur/agent.env

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
echo "2. If the server is not on this host, set RECUR_AGENT_SERVER_URL in"
echo "   /etc/recur/agent.env (e.g. RECUR_AGENT_SERVER_URL=http://your-server:8000)"
echo "   and run: sudo systemctl daemon-reload"
echo "3. Start the agent: sudo systemctl start recur-agent"
echo "4. Enable on boot: sudo systemctl enable recur-agent"
echo "5. Check status: sudo systemctl status recur-agent"
echo "6. View logs: sudo tail -f /var/log/recur/agent.log"
echo ""
