# Recur - Recursive System Health Monitoring Platform

A production-ready, YAML-driven system health monitoring platform that supports recursive dependency checking across complex hierarchical systems. Monitor availability of your entire infrastructure stack with a centralized server, lightweight distributed agents, and an intuitive web dashboard.

## Features

- **Recursive Dependency Checking** - System health evaluated hierarchically; overall status depends on all nested dependencies
- **YAML-Driven Configuration** - Define entire system topology in simple, readable YAML files
- **Lightweight Agent** - Pure Bash + minimal Python; minimal system overhead
- **Web Dashboard** - Auto-refreshing UI showing system status; full dependency trees via the `/tree` API
- **Multiple Health Check Types** - HTTP/HTTPS, TCP ports, ping, shell commands, custom scripts
- **REST API** - Full API for integrations and automation
- **Easy Installation** - Single-command agent and server setup, standalone or Dockerized
- **Resilient & Observable** - Comprehensive logging, graceful failure handling, retry logic

## Architecture

```
Agents (Remote Machines)              Central Server (FastAPI)         Dashboard (Web UI)
┌──────────────────────────┐           ┌──────────────────┐            ┌──────────────┐
│  recur-agent.sh          │           │  REST API        │            │  Web Browser │
│  - Read YAML config      ├─────────> │  - Ingest status │<───────────┤  - View      │
│  - Execute health checks │  POST     │  - Eval tree     │  auto-     │    systems   │
│  - Push JSON results     │           │  - Store history │            │  - Expand    │
└──────────────────────────┘           │                  │            │    tree      │
         ▲                             │  SQLite/PgSQL DB │            └──────────────┘
         │                             └──────────────────┘
    Configurable
     Interval
```

## Installation

The central server can run two ways:

- **Standalone** - from source in a Python virtualenv (recommended for development)
- **Dockerized** - via Docker Compose (recommended for deployment)

Agents are installed identically either way: on each machine you monitor, as a native systemd service.

### Prerequisites

- **Standalone:** Python 3.12+, Bash 4.0+, curl, git
- **Dockerized:** Docker Engine with the Compose plugin (`docker compose version`)

### Option 1: Standalone (source + venv)

```bash
git clone https://github.com/mvineetmenon/Recur.git
cd Recur
./scripts/install-server.sh
source venv/bin/activate
python -m server.app.main
```

- Server: `http://localhost:8000`
- Dashboard: `http://localhost:8000/dashboard`
- Health: `http://localhost:8000/api/v1/health`

### Option 2: Dockerized

```bash
git clone https://github.com/mvineetmenon/Recur.git
cd Recur
docker compose up -d --build
```

- Server: `http://localhost:8000`
- Dashboard: `http://localhost:8000/dashboard`
- Health: `http://localhost:8000/api/v1/health`

Notes:

- The default profile runs the server only (SQLite, data in a named volume).
- `docker compose --profile production up -d` additionally starts PostgreSQL and Redis.
- Host port is configurable: `RECUR_HTTP_PORT=9000 docker compose up -d`
- CORS is configurable (comma-separated origins, defaults to `*`): `CORS_ORIGINS="https://dash.example.com" docker compose up -d`

### Agent (both options)

```bash
# On each remote machine you want to monitor from
curl -s https://raw.githubusercontent.com/mvineetmenon/Recur/main/agent/install.sh | sudo bash

# Edit the configuration (installed example: /etc/recur/config.yaml)
sudo vim /etc/recur/config.yaml

# If the server is not on this host, point the agent at it
# (/etc/recur/agent.env, then: sudo systemctl daemon-reload)
#   RECUR_AGENT_SERVER_URL=http://your-server:8000

# Start the agent
sudo systemctl start recur-agent
sudo systemctl enable recur-agent
```

## YAML Configuration

### Simple Example

```yaml
system:
  name: "API Server"
  description: "Main API endpoint"
  interval: 60
  tasks:
    - name: "api_health"
      type: http
      url: "https://api.example.com/health"
      expected_status: 200
      timeout: 5
```

### Task Types

| Type | Purpose | Key Fields |
|------|---------|------------|
| `http` / `https` | Check HTTP endpoint | `url`, `expected_status`, `timeout` |
| `tcp` | Check TCP port | `host`, `port`, `timeout` |
| `ping` | ICMP ping | `host`, `timeout` |
| `command` | Execute shell command (exit 0 = success) | `command`, `timeout` |
| `script` | Execute local script | `path`, `timeout` |

### Complex Example

`configs/complex-cluster.yaml` contains a production-like configuration with nested
dependencies (web tier, database layer, cache, backup, message queue). Excerpt:

```yaml
system:
  name: "Production Cluster"
  interval: 60
  tasks:
    - name: "cluster_ping"
      type: ping
      host: "cluster.example.com"
      timeout: 2
  dependencies:
    - name: "Web Tier"
      interval: 30
      tasks:
        - name: "nginx_health"
          type: http
          url: "http://web1:8080/health"
          expected_status: 200
      dependencies:
        - name: "SSL Certificates"
          tasks:
            - name: "cert_check"
              type: command
              command: "openssl s_client -connect api.example.com:443 </dev/null 2>/dev/null | openssl x509 -noout -dates"
```

More examples: `configs/simple-system.yaml`, `configs/multi-region.yaml`.

## REST API

All endpoints are under `/api/v1`:

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Server health |
| `POST` | `/agents/register` | Register an agent |
| `GET` | `/agents` | List agents |
| `GET` | `/agents/{agent_id}` | Agent details |
| `GET` | `/agents/{agent_id}/systems` | Systems reported by agent |
| `POST` | `/agents/{agent_id}/check` | Request an immediate check |
| `PUT` | `/agents/{agent_id}/heartbeat` | Agent heartbeat |
| `DELETE` | `/agents/{agent_id}` | Remove agent |
| `POST` | `/status` | Submit a status report |
| `POST` | `/systems` | Create a system |
| `GET` | `/systems` | List systems |
| `GET` | `/systems/{system_id}` | System details |
| `PUT` | `/systems/{system_id}` | Update a system |
| `GET` | `/systems/{system_id}/tree` | Full dependency tree |
| `GET` | `/systems/{system_id}/health` | Latest health summary |
| `GET` | `/systems/{system_id}/history` | Status report history |
| `DELETE` | `/systems/{system_id}` | Remove system |

Examples:

```bash
# Register an agent
curl -X POST http://localhost:8000/api/v1/agents/register \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"prod-web-01","hostname":"prod-web-01","ip_address":"10.0.1.42"}'

# Submit a status report
curl -X POST http://localhost:8000/api/v1/status \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"prod-web-01","timestamp":"2026-09-06T10:30:00Z","system_status":{...}}'
```

## Dashboard & Usage

Navigate to `http://localhost:8000/dashboard` to view:

- All monitored systems with current status (UP / DOWN / UNKNOWN), auto-refreshed every 10 seconds
- System description and last check time

For the full hierarchical view (nested dependencies, per-task status, durations and
errors), query the tree API:

```bash
curl http://localhost:8000/api/v1/systems/{system_id}/tree

# Response
{
  "name": "Production Cluster",
  "status": "UP",
  "tasks": [...],
  "dependencies": [
    {
      "name": "Web Tier",
      "status": "UP",
      "dependencies": [...]
    }
  ]
}
```

Trigger a manual check on an agent:

```bash
curl -X POST http://localhost:8000/api/v1/agents/prod-web-01/check

# Response (request is accepted; the agent acts on its next interval)
{
  "agent_id": "prod-web-01",
  "status": "check_requested",
  "message": "Check requested - agent will run on next interval"
}
```

## Project Layout

```
Recur/
├── README.md                  # This file
├── pyproject.toml
├── requirements.txt
├── docker-compose.yml
├── Dockerfile.server
│
├── server/                    # Central server
│   ├── app/
│   │   ├── main.py            # FastAPI application entry
│   │   ├── config.py          # Configuration management
│   │   ├── models.py          # Database models
│   │   ├── database.py        # SQLAlchemy setup
│   │   ├── schemas.py         # Pydantic schemas
│   │   ├── routers/           # API endpoints
│   │   ├── services/          # Business logic
│   │   ├── utils/             # Utilities (YAML loading, logging)
│   │   └── templates/         # Web UI templates
│   └── tests/                 # Test suite
│
├── agent/                     # Lightweight agent
│   ├── recur-agent.sh         # Main agent script (Bash)
│   ├── health_check_utils.py  # Python check executor
│   ├── install.sh             # Installation script
│   └── config.example.yaml    # Example configuration
│
├── configs/                   # Example configurations
│   ├── simple-system.yaml
│   ├── complex-cluster.yaml
│   └── multi-region.yaml
│
└── scripts/                   # Setup scripts
    ├── install-server.sh
    ├── dev-setup.sh
    └── api-examples.sh
```

## Development

```bash
./scripts/dev-setup.sh
source venv/bin/activate
```

Run the test suite:

```bash
make test          # or: pytest -v --cov=server/app
```

Code style (also enforced via pre-commit):

```bash
make lint          # or: black --check server/ && flake8 server/ && mypy server/
make format        # black + isort
```

## Deployment

### Production Checklist

- [ ] Configure `DATABASE_URL` with production database (PostgreSQL recommended)
- [ ] Set `DEBUG=false`
- [ ] Restrict CORS via `CORS_ORIGINS`
- [ ] Configure TLS/HTTPS certificates (reverse proxy)
- [ ] Set up log aggregation
- [ ] Configure monitoring and alerting
- [ ] Set appropriate check intervals based on SLA
- [ ] Test failover scenarios
- [ ] Document runbooks for common issues

### Behind a Reverse Proxy (Nginx)

```nginx
server {
    listen 80;
    server_name monitoring.example.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## Troubleshooting

### Agent not reporting status

1. Check agent logs: `sudo tail -f /var/log/recur/agent.log`
   (systemd installs; the script default is `/var/log/recur-agent.log`)
2. Verify configuration: `sudo cat /etc/recur/config.yaml`
3. Test connectivity from the agent host to the server:
   `curl http://your-server:8000/api/v1/health`

### All checks showing as DOWN

1. Verify network connectivity between agent and targets
2. Check firewall rules on target systems
3. Verify timeout values (increase if needed)
4. Review agent logs for specific error messages

### Dashboard not loading

1. Check server logs: `tail -f server/logs/server_app_main.log`
2. Verify FastAPI is running: `curl http://localhost:8000/api/v1/health`
3. Check browser console for JS errors

## Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Add tests for new features
4. Submit a pull request

## License

MIT License - see LICENSE file for details

## Support

- **Issues**: Open a GitHub issue
- **Questions**: Check existing issues/discussions
- **Security**: security@example.com

---

**Built with ❤️ for infrastructure reliability**
