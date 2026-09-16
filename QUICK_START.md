# Quick Start - Recur

Get up and running in 5 minutes. For full documentation, see [README.md](README.md).

## Prerequisites

- **Standalone:** Python 3.12+, curl, git
- **Dockerized:** Docker Engine with the Compose plugin

## 1. Install the Server (pick one)

### Option A: Standalone (source + venv)

```bash
git clone https://github.com/mvineetmenon/Recur.git
cd Recur
./scripts/install-server.sh
source venv/bin/activate
python -m server.app.main
```

### Option B: Dockerized

```bash
git clone https://github.com/mvineetmenon/Recur.git
cd Recur
docker compose up -d --build
```

Either way:

- Server: `http://localhost:8000`
- Dashboard: `http://localhost:8000/dashboard`
- Health: `http://localhost:8000/api/v1/health`

## 2. Install an Agent

On each machine you want to monitor:

```bash
curl -s https://raw.githubusercontent.com/mvineetmenon/Recur/main/agent/install.sh | sudo bash

# Edit the configuration
sudo vim /etc/recur/config.yaml

# If the server is not on this host, point the agent at it
# (uncomment in /etc/recur/agent.env, then: sudo systemctl daemon-reload)
#   RECUR_AGENT_SERVER_URL=http://your-server:8000

# Start the agent
sudo systemctl start recur-agent
sudo systemctl enable recur-agent
```

## 3. Try the API

```bash
# Register an agent
curl -X POST http://localhost:8000/api/v1/agents/register \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"my-agent","hostname":"my-host","ip_address":"192.168.1.100"}'

# Create a system
curl -X POST http://localhost:8000/api/v1/systems \
  -H "Content-Type: application/json" \
  -d '{
    "system_id": "my-system",
    "name": "My System",
    "description": "My test system",
    "config": {
      "name": "My System",
      "tasks": [
        {
          "name": "web_health",
          "type": "http",
          "url": "http://example.com",
          "expected_status": 200,
          "timeout": 5
        }
      ]
    }
  }'

# Submit a status report (what agents do automatically)
curl -X POST http://localhost:8000/api/v1/status \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "my-agent",
    "timestamp": "2026-09-06T10:00:00Z",
    "system_status": {
      "system_id": "my-system",
      "name": "My System",
      "status": "UP",
      "tasks": [
        {"task_id": "web_health", "name": "web_health", "type": "http", "status": "UP", "duration_ms": 150}
      ],
      "dependencies": []
    }
  }'

# Get the dependency tree
curl http://localhost:8000/api/v1/systems/my-system/tree
```

## 4. Write a Config

Example `my-config.yaml` — tasks plus nested dependencies:

```yaml
system:
  name: "My App"
  description: "My application stack"
  interval: 60
  tasks:
    - name: "api_health"
      type: http
      url: "http://api.example.com/health"
      expected_status: 200
      timeout: 5
  dependencies:
    - name: "Database"
      tasks:
        - name: "db_port"
          type: tcp
          host: "db.internal"
          port: 5432
          timeout: 3
    - name: "Cache"
      tasks:
        - name: "redis_port"
          type: tcp
          host: "cache.internal"
          port: 6379
          timeout: 3
```

Task types (see [README.md](README.md#yaml-configuration) for full details):

| Type | Key Fields |
|------|------------|
| `http` / `https` | `url`, `expected_status`, `timeout` |
| `tcp` | `host`, `port`, `timeout` |
| `ping` | `host`, `timeout` |
| `command` | `command` (exit 0 = success), `timeout` |
| `script` | `path`, `timeout` |

## 5. Key Concepts

**Recursive status evaluation** - a system is **UP** only if all of its tasks are UP *and* all of its dependencies (recursively) are UP. Any DOWN task or dependency makes the whole system **DOWN**.

**Agent workflow** - read YAML config, run all checks, evaluate dependencies recursively, push the JSON report to the server, repeat on the configured interval. The server stores history and the dashboard auto-refreshes.

## 6. Common Tasks

```bash
# Trigger a manual check on an agent
curl -X POST http://localhost:8000/api/v1/agents/my-agent/check

# Get agent status
curl http://localhost:8000/api/v1/agents/my-agent

# Delete a system
curl -X DELETE http://localhost:8000/api/v1/systems/my-system

# Register multiple agents at once
for i in {1..5}; do
  curl -X POST http://localhost:8000/api/v1/agents/register \
    -H "Content-Type: application/json" \
    -d "{\"agent_id\":\"agent-$i\",\"hostname\":\"host-$i\",\"ip_address\":\"192.168.1.$i\"}"
done
```

## 7. Troubleshooting

### Server won't start

```bash
# Port 8000 already in use?
lsof -i :8000

# Start on a different port
PORT=8001 python -m server.app.main
```

### Agent can't connect to server

```bash
# Test connectivity from the agent host
curl http://your-server:8000/api/v1/health

# Firewall / agent config
sudo ufw allow 8000
sudo cat /etc/recur/config.yaml
```

### Tasks always report DOWN

- Check that the targets are reachable from the agent host
- Verify timeouts are appropriate
- Check firewall rules on the targets
- Review agent logs: `sudo tail -f /var/log/recur/agent.log`

More in [README.md - Troubleshooting](README.md#troubleshooting).

## Development

```bash
make test      # run the test suite
make format    # black + isort
make lint      # black --check + flake8 + mypy

# Server logs (one file per module)
tail -f server/logs/server_app_main.log

# Agent logs (systemd install; script default is /var/log/recur-agent.log)
sudo tail -f /var/log/recur/agent.log
```

## Next Steps

- [README.md](README.md) - complete documentation
- [configs/](configs/) - production-ready examples
- [agent/](agent/) - agent internals and customization
- [server/app/](server/app/) - API and business logic

---

**Need help?** Check the troubleshooting section above or open an issue on GitHub.
