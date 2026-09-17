.PHONY: help install dev-setup test lint format run run-docker install-agent install-agent-local clean

help:
	@echo "Recur - System Health Monitoring Platform"
	@echo ""
	@echo "Available commands:"
	@echo "  make install      - Install server and dependencies"
	@echo "  make dev-setup    - Setup development environment"
	@echo "  make test         - Run tests"
	@echo "  make lint         - Run linting"
	@echo "  make format       - Format code"
	@echo "  make run          - Run development server"
	@echo "  make run-docker   - Run with Docker Compose"
	@echo "  make install-agent       - Show the remote (curl) agent install command"
	@echo "  make install-agent-local - Install agent from this checkout (sudo)"
	@echo "  make clean        - Clean up build artifacts"

install:
	@chmod +x scripts/install-server.sh
	@./scripts/install-server.sh

dev-setup:
	@chmod +x scripts/dev-setup.sh
	@./scripts/dev-setup.sh

test:
	@. venv/bin/activate && pytest -v --cov=server/app server/tests/

lint:
	@. venv/bin/activate && black --check server/ && flake8 server/ && mypy server/

format:
	@. venv/bin/activate && black server/ && isort server/

run:
	@. venv/bin/activate && python -m server.app.main

run-docker:
	@docker compose up -d
	@echo "Server running at http://localhost:8000"
	@echo "Dashboard at http://localhost:8000/dashboard"

install-agent:
	@echo "To install the agent on a remote machine, run there:"
	@echo "  curl -s https://raw.githubusercontent.com/mvineetmenon/Recur/main/agent/install.sh | sudo bash"
	@echo "(the installer downloads the companion agent files from the repository)"

install-agent-local:
	@chmod +x agent/install.sh
	@echo "Installing agent from this checkout (companion files are taken from"
	@echo "the local agent/ directory, so no download of agent files is needed)..."
	@sudo ./agent/install.sh

clean:
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete
	@find . -type f -name ".coverage" -delete
	@find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	@rm -f server/db.sqlite3 recur.db
	@echo "Cleaned up build artifacts"
