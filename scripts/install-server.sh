#!/bin/bash

################################################################################
# Recur Server Installation Script
# Sets up the central monitoring server
################################################################################

set -euo pipefail

echo "=========================================="
echo "Recur Server Installation"
echo "=========================================="

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "Project root: $PROJECT_ROOT"
echo ""

# Check Python version
echo "[1/5] Checking Python installation..."
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 is not installed"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
echo "Found Python $PYTHON_VERSION"

if (( $(echo "$PYTHON_VERSION < 3.11" | bc -l) )); then
    echo "ERROR: Python 3.11+ is required"
    exit 1
fi

# Create virtual environment
echo "[2/5] Creating virtual environment..."
if [[ -d "$PROJECT_ROOT/venv" ]]; then
    echo "Virtual environment already exists"
else
    python3 -m venv "$PROJECT_ROOT/venv"
fi

source "$PROJECT_ROOT/venv/bin/activate"

# Install dependencies
echo "[3/5] Installing dependencies..."
pip install -q --upgrade pip setuptools wheel
pip install -q -r "$PROJECT_ROOT/requirements.txt"

# Create directories
echo "[4/5] Creating directories..."
mkdir -p "$PROJECT_ROOT/server/logs"
mkdir -p "$PROJECT_ROOT/server/data"

# Initialize database
echo "[5/5] Initializing database..."
cd "$PROJECT_ROOT"
python3 -c "
from server.app.database import init_db
init_db()
print('Database initialized successfully')
"

echo ""
echo "=========================================="
echo "Installation Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Activate virtual environment:"
echo "   source venv/bin/activate"
echo ""
echo "2. Start the server:"
echo "   python server/app/main.py"
echo ""
echo "3. Access the dashboard:"
echo "   http://localhost:8000/dashboard"
echo ""
echo "4. View API documentation:"
echo "   http://localhost:8000/docs"
echo ""
