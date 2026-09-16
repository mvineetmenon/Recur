#!/bin/bash

################################################################################
# Development Setup Script
# Installs development dependencies and sets up pre-commit hooks
################################################################################

set -euo pipefail

echo "=========================================="
echo "Recur Development Setup"
echo "=========================================="

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

# Create virtual environment if needed
if [[ ! -d "venv" ]]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install -q --upgrade pip setuptools wheel
pip install -q -r requirements-dev.txt

# Initialize database
echo "Initializing database..."
python3 -c "
from server.app.database import init_db
init_db()
print('Database initialized')
"

# Install pre-commit hooks
echo "Setting up pre-commit hooks..."
pre-commit install || echo "Pre-commit not configured"

echo ""
echo "=========================================="
echo "Development Setup Complete!"
echo "=========================================="
echo ""
echo "Available commands:"
echo "  make test          - Run tests"
echo "  make lint          - Run linting"
echo "  make format        - Format code"
echo "  make run           - Start development server"
echo ""
echo "Or directly:"
echo "  pytest -v          - Run tests with verbose output"
echo "  black server/      - Format code"
echo "  flake8 server/     - Lint code"
echo ""
