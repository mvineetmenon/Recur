# Quick Start - Recur

Get a server and an agent talking in 5 minutes. Everything in detail is in
[README.md](README.md).

## Prerequisites

- **Server (standalone):** Python 3.12+, curl, git
- **Server (dockerized):** Docker Engine with the Compose plugin
- **Agent:** Python 3 only — PyYAML is vendored with the agent, so no pip or
  OS package access is needed (works on air-gapped hosts)

## 1. Start the Server

Pick one:

```bash
# Option A: standalone (source + venv, SQLite)
git clone https://github.com/mvineetmenon/Recur.git
cd Recur
./scripts/install-server.sh
source venv/bin/activate
python -m server.app.main

# Option B: dockerized (server + PostgreSQL)
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
# Option A: one-liner (downloads the agent files from the repository)
curl -s https://raw.githubusercontent.com/mvineetmenon/Recur/main/agent/install.sh | sudo bash

# Option B: from a local checkout (no download)
git clone https://github.com/mvineetmenon/Recur.git && cd Recur && sudo ./agent/install.sh
```

Then point it at your server and start it:

```bash
# Edit the configuration
sudo vim /etc/recur/config.yaml

# If the server is not on this host: set it in /etc/recur/agent.env
#   RECUR_AGENT_SERVER_URL=http://your-server:8000
# then:
sudo systemctl daemon-reload

# Start the agent
sudo systemctl start recur-agent
sudo systemctl enable recur-agent
```

## 3. What Happens Next

Everything else is automatic:

1. **The agent registers itself** with the server on startup
   (`POST /api/v1/agents/register`) and heartbeats every cycle.
2. **Its system is auto-registered** by the server on the first status report
   — no API call needed. Nested dependencies in the config are registered the
   same way. (You can still pre-create a system with
   `POST /api/v1/systems` to pin its description/config first.)
3. **Config edits are picked up on the next check cycle** — the agent reloads
   `config.yaml` live, and the server treats each report as the current
   configuration: added tasks appear, removed tasks/dependencies are pruned
   (so a removed task can no longer keep the system DOWN).

Full explanation: [README — How It Works](README.md#how-it-works).

## 4. Verify It Works

```bash
# Server is up
curl http://localhost:8000/api/v1/health

# The system tree (replace the id; the agent's config "name" is slugged,
# e.g. "Local Services" -> local-services)
curl http://localhost:8000/api/v1/systems/local-services/tree

# Request an immediate check (agent id = RECUR_AGENT_ID, or the hostname
# when unset; find it in the dashboard or `GET /api/v1/agents`)
curl -X POST http://localhost:8000/api/v1/agents/agent-01/check

# Agent side (on the agent host)
sudo tail -f /var/log/recur/agent.log
```

Then open the dashboard: `http://localhost:8000/dashboard`.

## 5. Write a Config

`/etc/recur/config.yaml` on each agent:

```yaml
system:
  name: "My App"
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
```

Task types: `http`/`https`, `tcp`, `ping`, `command`, `script` — field
reference, nested examples, and production configs in
[README — YAML Configuration](README.md#yaml-configuration) and in
[configs/](configs/).

## 6. Common Tasks

```bash
# Trigger a manual check on an agent
curl -X POST http://localhost:8000/api/v1/agents/agent-01/check

# Get agent status
curl http://localhost:8000/api/v1/agents/agent-01

# Delete a system (also when you rename a system's id)
curl -X DELETE http://localhost:8000/api/v1/systems/local-services

# Uninstall the agent (on the agent host)
sudo ./agent/uninstall.sh        # add -y to skip the prompt, -k to keep /etc/recur
```

Full API reference: [README — REST API](README.md#rest-api) (or run
`scripts/api-examples.sh`).

## 7. Troubleshooting (short version)

- **No reports from the agent** — `sudo tail -f /var/log/recur/agent.log`;
  check `RECUR_AGENT_SERVER_URL` in `/etc/recur/agent.env`; test
  `curl http://your-server:8000/api/v1/health` from the agent host.
- **All tasks DOWN** — the targets must be reachable *from the agent host*;
  check firewalls and timeouts.
- **Server won't start** — port 8000 in use? `lsof -i :8000`; start with
  `PORT=8001 python -m server.app.main`.
- **Dashboard not loading** — `curl http://localhost:8000/api/v1/health`;
  check `server/logs/server_app_main.log`.

More in [README — Troubleshooting](README.md#troubleshooting).

## Next Steps

- [README.md](README.md) — complete documentation
- [configs/](configs/) — production-ready example configurations
- [agent/](agent/) — agent internals and customization
- [server/app/](server/app/) — API and business logic

---

**Need help?** Open an issue on GitHub.
