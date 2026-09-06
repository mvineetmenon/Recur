# Recur - Recursive System Health Monitoring Platform

A production-ready, YAML-driven system health monitoring platform that supports recursive dependency checking across complex hierarchical systems. Monitor availability of your entire infrastructure stack with a centralized server, lightweight distributed agents, and an intuitive web dashboard.

## Features

✅ **Recursive Dependency Checking** - System health evaluated hierarchically; overall status depends on all nested dependencies  
✅ **YAML-Driven Configuration** - Define entire system topology in simple, readable YAML files  
✅ **Lightweight Agent** - Pure Bash + minimal Python; minimal system overhead  
✅ **Real-Time Dashboard** - Modern web UI showing system status and dependency trees  
✅ **Multiple Health Check Types** - HTTP/HTTPS, TCP ports, shell commands, ping, custom scripts  
✅ **REST API** - Full API for integrations and automation  
✅ **Easy Installation** - Single-command agent and server setup  
✅ **Resilient & Observable** - Comprehensive logging, graceful failure handling, retry logic  

## Architecture

```
Agents (Remote Machines)              Central Server (FastAPI)         Dashboard (Web UI)
┌──────────────────────────┐          ┌──────────────────┐            ┌──────────────┐
│  recur-agent.sh          │          │  REST API        │            │  Web Browser │
│  - Read YAML config      ├─────────>│  - Ingest status │<───────────┤  - View      │
│  - Execute health checks │  POST    │  - Eval tree     │   WebSocket│    systems   │
│  - Push JSON results     │          │  - Store history │            │  - Expand    │
└──────────────────────────┘          │                  │            │    tree      │
         ▲                             │  SQLite/PgSQL DB │            │              │
         │                             └──────────────────┘            └──────────────┘
    Configurable
     Interval
```

## Quick Start

### Server Setup

```bash
cd /workspaces/Recur
./scripts/install-server.sh
python server/app/main.py
# Server runs on http://localhost:8000
# Dashboard: http://localhost:8000/dashboard
```

### Agent Setup

```bash
# On remote machine
curl -s https://raw.githubusercontent.com/mvineetmenon/Recur/main/agent/install.sh | bash

# Copy your config
scp configs/example-system.yaml agent@remote:/etc/recur/config.yaml

# Restart agent
sudo systemctl restart recur-agent
```

## YAML Configuration Schema

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

### Complex Nested Example

```yaml
system:
  name: "Production Cluster"
  description: "Full production environment"
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
    
    - name: "Database Layer"
      tasks:
        - name: "postgres_primary"
          type: tcp
          host: "db-primary.internal"
          port: 5432
        
        - name: "postgres_replication"
          type: command
          command: "pg_isready -h db-primary.internal"
      
      dependencies:
        - name: "Redis Cache"
          tasks:
            - name: "redis_port"
              type: tcp
              host: "redis.internal"
              port: 6379
        
        - name: "Backup Storage"
          tasks:
            - type: http
              url: "http://s3-backup:9000/minio/health/live"
    
    - name: "Message Queue"
      tasks:
        - type: http
          url: "http://rabbitmq:15672/api/healthchecks/node"
          timeout: 5
```

## Supported Task Types

| Type | Purpose | Example |
|------|---------|---------|
| `http` / `https` | Check HTTP endpoint | `url: https://api.example.com/health`, `expected_status: 200` |
| `tcp` | Check TCP port | `host: db.internal`, `port: 5432` |
| `command` | Execute shell command | `command: "pg_isready -h localhost"` (exit 0 = success) |
| `ping` | ICMP ping | `host: example.com`, `timeout: 2` |
| `script` | Execute local script | `path: /etc/recur/custom-checks.sh` |

## REST API Endpoints

```bash
# Register agent
POST /api/v1/agents/register
{
  "agent_id": "prod-web-01",
  "hostname": "prod-web-01.internal",
  "ip_address": "10.0.1.42"
}

# Push status report
POST /api/v1/status
{
  "agent_id": "prod-web-01",
  "timestamp": "2026-09-06T10:30:00Z",
  "system_status": { ... }
}

# Query system status
GET /api/v1/systems/{system_id}
GET /api/v1/systems/{system_id}/tree    # Full dependency tree

# List all systems
GET /api/v1/systems

# Get agent status
GET /api/v1/agents/{agent_id}
```

## Directory Structure

```
Recur/
├── README.md                  # This file
├── pyproject.toml
├── requirements.txt
├── docker-compose.yml
│
├── server/                    # Central server
│   ├── app/
│   │   ├── main.py           # FastAPI application entry
│   │   ├── config.py         # Configuration management
│   │   ├── models.py         # Database models
│   │   ├── database.py       # SQLAlchemy setup
│   │   ├── schemas.py        # Pydantic schemas
│   │   ├── routers/          # API endpoints
│   │   ├── services/         # Business logic
│   │   ├── utils/            # Utilities (YAML loading, logging)
│   │   └── templates/        # Web UI templates
│   └── tests/                # Test suite
│
├── agent/                     # Lightweight agent
│   ├── recur-agent.sh        # Main agent script (Bash)
│   ├── health_check_utils.py # Python utilities
│   ├── install.sh            # Installation script
│   └── config.example.yaml   # Example configuration
│
├── configs/                   # Example configurations
│   ├── simple-system.yaml
│   ├── complex-cluster.yaml
│   └── multi-region.yaml
│
└── scripts/                   # Setup scripts
    ├── install-server.sh
    ├── uninstall-server.sh
    ├── init-db.sh
    └── dev-setup.sh
```

## Installation

### Prerequisites

- Python 3.11+
- Bash 4.0+
- curl
- git

### Server Installation

```bash
git clone https://github.com/mvineetmenon/Recur.git
cd Recur
./scripts/install-server.sh
source venv/bin/activate
python server/app/main.py
```

### Agent Installation

```bash
# On each remote machine you want to monitor from
curl -s https://raw.githubusercontent.com/mvineetmenon/Recur/main/agent/install.sh | bash

# Edit the configuration
sudo vim /etc/recur/config.yaml

# Start the agent
sudo systemctl start recur-agent
sudo systemctl enable recur-agent
```

### Docker Compose (Development)

```bash
docker-compose up -d
# Server: http://localhost:8000
# Dashboard: http://localhost:8000/dashboard
```

## Configuration Examples

### Example 1: Simple Website Monitoring

```yaml
system:
  name: "Website"
  description: "Public website endpoint"
  interval: 60
  tasks:
    - name: "homepage"
      type: http
      url: "https://example.com/"
      expected_status: 200
      timeout: 5
    - name: "api_endpoint"
      type: http
      url: "https://api.example.com/v1/status"
      expected_status: 200
      timeout: 5
```

### Example 2: Multi-Tier Application Stack

See `configs/complex-cluster.yaml` for a production-like configuration.

## Usage

### Dashboard

Navigate to `http://localhost:8000/dashboard` to view:
- All monitored systems with current status (🟢 UP / 🔴 DOWN)
- Expandable dependency tree showing nested components
- Last check time and latency
- Error messages for failed checks
- Manual trigger option for immediate checks

### Command-Line: Trigger Manual Check

```bash
curl -X POST http://localhost:8000/api/v1/agents/prod-web-01/check

# Response
{
  "agent_id": "prod-web-01",
  "status": "checking",
  "task_count": 8
}
```

### Retrieve Full System Tree

```bash
curl http://localhost:8000/api/v1/systems/prod-cluster/tree

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
    },
    ...
  ]
}
```

## Development

### Setup Development Environment

```bash
./scripts/dev-setup.sh
source venv/bin/activate
pytest server/tests/
```

### Running Tests

```bash
pytest -v --cov=server/app
```

### Code Style

- Use `black` for formatting
- Use `flake8` for linting
- Use `mypy` for type checking

```bash
black server/
flake8 server/
mypy server/
```

## Deployment

### Production Checklist

- [ ] Configure `.env` with production database (PostgreSQL recommended)
- [ ] Set `DEBUG=false`
- [ ] Configure TLS/HTTPS certificates
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

1. Check agent logs: `tail -f /var/log/recur-agent.log`
2. Verify configuration: `sudo cat /etc/recur/config.yaml`
3. Test connectivity: `curl -X POST http://server:8000/api/v1/status -d '...'`

### All checks showing as DOWN

1. Verify network connectivity between agent and targets
2. Check firewall rules on target systems
3. Verify timeout values (increase if needed)
4. Review agent logs for specific error messages

### Dashboard not loading

1. Check server logs: `tail -f server/logs/app.log`
2. Verify FastAPI is running: `curl http://localhost:8000/health`
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
