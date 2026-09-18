# Recur - Recursive System Health Monitoring Platform

A self-hosted, YAML-driven health monitoring platform. Define the topology of
a system (tasks plus nested dependencies) in YAML, run a lightweight agent on
each machine, and watch the recursive health of your entire stack roll up in
one central server with a live dashboard.

A 5-minute path to a running agent is in [QUICK_START.md](QUICK_START.md).

## Features

- **Recursive Dependency Checking** — a system is UP only if all its tasks
  *and* all its nested dependencies (recursively) are UP
- **YAML-Driven Configuration** — the entire topology lives in one readable
  file per agent; edits are picked up live, no restart
- **Lightweight Agent** — pure Python (stdlib + vendored PyYAML); installs as
  a systemd service; runs on air-gapped hosts with no pip or OS package access
- **Self-Registering Topology** — agents register themselves, and the server
  registers the systems they report automatically (see [How It Works](#how-it-works))
- **Authenticated Agents** — every agent holds a per-agent bearer token issued
  at registration (only a hash is stored server-side); report and heartbeat
  calls are verified, cross-agent impersonation is rejected, and new
  registrations can be gated behind an enrollment token (see
  [Agent Authentication](#agent-authentication))
- **Web Dashboard** — auto-refreshing status board with a semantic dependency
  tree per system
- **Multiple Health Check Types** — HTTP/HTTPS, TCP ports, ICMP ping, shell
  commands, custom scripts
- **REST API** — full API for integrations and automation
- **Easy Installation** — one-command server and agent setup, standalone or
  Dockerized

## How It Works

### Architecture

```
Agents (Remote Machines)              Central Server (FastAPI)         Dashboard (Web UI)
┌──────────────────────────┐           ┌──────────────────┐            ┌──────────────┐
│  recur_agent.py          │           │  REST API        │            │  Web Browser │
│  - Read YAML config      ├─────────> │  - Ingest status │<───────────┤  - View      │
│  - Execute health checks │  POST     │  - Eval tree     │  auto-     │    systems   │
│  - Push JSON results     │           │  - Store history │            │  - Expand    │
└──────────────────────────┘           │                  │            │    tree      │
          ▲                            │  SQLite/Postgres │            └──────────────┘
          │                            └──────────────────┘
     Configurable
      Interval
```

Each agent loops: read `config.yaml`, run every check, evaluate the tree,
`POST` the JSON report, heartbeat, sleep for the configured interval. Every
agent call is sent with its per-agent bearer token, which it receives on first
registration (see [Agent Authentication](#agent-authentication)).

### Agents, Systems, and Reports

Three distinct entities — the source of most confusion, so here it is
explicitly:

| Entity | What it is | Defined by | How it reaches the server |
|---|---|---|---|
| **Agent** | the monitoring client on a host (*who is reporting*) | the host itself (`/etc/recur/`) | registers itself on startup: `POST /api/v1/agents/register`, which issues the bearer token it stores in `/etc/recur/agent.token` |
| **System** | a monitored topology: tasks + nested dependencies (*what is monitored*) | the agent's `config.yaml` | auto-registered by the server on the agent's **first report** |
| **Report** | the results of one check cycle — a recursive JSON tree | produced by the agent each cycle | `POST /api/v1/status` |

The server's report semantics make config changes fully automatic — there is
no manual server-side step when an agent's `config.yaml` changes:

- **First report for an unknown system** (root or nested) auto-registers it,
  materializing its tasks from the report.
- **Each report is treated as the agent's current configuration**: tasks and
  dependency links it no longer contains are pruned, and the system's display
  name follows the report. A removed task can therefore never keep a system
  pinned DOWN.
- **A system's `id` is its stable identity** — taken from `system.id`, or
  derived from `system.name` when absent ("Local Services" →
  `local-services`). Renaming the id registers a *new* system; delete the old
  one with `DELETE /api/v1/systems/{id}`.
- `POST /api/v1/systems` remains available to **pre-create** a system with a
  curated description/config before the first report arrives.

### Recursive Status Evaluation

Evaluation happens server-side on every report and rolls up bottom-up:

- A system is **UP** only if all of its tasks are UP *and* all of its
  dependencies are UP (recursively).
- Any DOWN task or dependency makes the system **DOWN**.
- Missing/stale data yields **UNKNOWN** rather than a false UP.

The same rules run inside the agent before each report, so the submitted tree
is already consistent.

### Agent Authentication

Agent↔server traffic is authenticated with per-agent bearer tokens:

1. **Issuance.** The first `POST /agents/register` for an agent returns a
   random 256-bit token exactly once (`agent_token` in the response). The
   agent stores it in `/etc/recur/agent.token` (mode `0600`); the server
   stores only its SHA-256 hash — the plaintext is never persisted.
2. **Use.** Every subsequent agent call sends `Authorization: Bearer
   <token>`. `POST /status` and `PUT /agents/{id}/heartbeat` require it, and
   the token's owner must match the `agent_id` claimed — nobody on the
   network can report for or heartbeat as another agent.
3. **Enrollment.** When `RECUR_ENROLLMENT_TOKEN` is set on the server, new
   registrations are additionally gated: the agent must present it (from
   `RECUR_AGENT_ENROLLMENT_TOKEN`) as an `X-Recur-Enrollment-Token` header.
   Agents that already hold a valid token re-register without it. When unset,
   registration is open (dev mode) and the server logs a warning for every
   open registration.
4. **Rotation & self-healing.** Re-registration rotates the token and
   returns the new plaintext. The agent does this automatically on any
   `401`/`403` (deleting the old token file first), so a lost, stale, or
   rotated token recovers on the next cycle — no restart required.

Known limits and the remaining hardening roadmap (TLS, admin-endpoint
auth, request signing, rate limiting) are tracked in
[SECURITY_TODO.md](SECURITY_TODO.md).

## Installation

The central server runs two ways; agents are installed identically either way.

### Prerequisites

- **Standalone server:** Python 3.12+, Bash 4.0+, curl, git
- **Dockerized server:** Docker Engine with the Compose plugin
  (`docker compose version`)
- **Agent:** Python 3 only — PyYAML is vendored with the agent, so air-gapped
  hosts need no pip or OS package access

### Server Option A: Standalone (source + venv)

```bash
git clone https://github.com/mvineetmenon/Recur.git
cd Recur
./scripts/install-server.sh        # or: make install
cp .env.example .env               # optional: adjust settings (see below)
source venv/bin/activate
python -m server.app.main           # or: make run
```

Uses SQLite by default (`./recur.db`). To use PostgreSQL instead, set
`DATABASE_URL` in `.env` (e.g.
`postgresql+psycopg2://recur:secret@db.example.com:5432/recur`). The server
loads `.env` automatically; real environment variables take precedence.

### Server Option B: Dockerized

```bash
git clone https://github.com/mvineetmenon/Recur.git
cd Recur
cp .env.example .env               # optional: adjust settings (see below)
docker compose up -d --build        # or: make run-docker
```

- The default setup runs the server plus PostgreSQL (JSON columns stored as
  JSONB).
- `docker compose --profile production up -d` additionally starts Redis.
- All host ports, the database password, and the container's runtime settings
  (`DEBUG`, `LOG_LEVEL`, `CORS_ORIGINS`, `RECUR_ENROLLMENT_TOKEN`) are
  configured in `.env` — see
  [Environment Variables](#environment-variables). One-off overrides still
  work inline, e.g. `RECUR_HTTP_PORT=9000 DB_PASSWORD=secret docker compose up -d`.

Both options serve:

- Server: `http://localhost:8000`
- Dashboard: `http://localhost:8000/dashboard` (the `/` route redirects there)
- Health: `http://localhost:8000/api/v1/health`

### Agent (both options)

On each machine you want to monitor, install the agent either way:

**Option A: one-liner** — the installer downloads `recur_agent.py`,
`health_check_utils.py`, `_bootstrap.py`, the vendored `vendor/yaml/` package,
and `config.example.yaml` from the repository:

```bash
curl -s https://raw.githubusercontent.com/mvineetmenon/Recur/main/agent/install.sh | sudo bash
```

**Option B: from a local checkout** — clone the repo on the target machine;
the installer finds the agent files next to the script and uses them as-is, so
nothing is downloaded:

```bash
git clone https://github.com/mvineetmenon/Recur.git
cd Recur
sudo ./agent/install.sh             # or: make install-agent-local
```

(`make install-agent` prints the Option A command for you.)

The installer lays down:

- `/usr/local/lib/recur/` — `recur_agent.py`, `health_check_utils.py`,
  `_bootstrap.py`, `vendor/yaml/`
- `/usr/local/bin/recur-agent` and `/usr/local/bin/recur-health-check`
  (symlinks)
- `/etc/recur/config.yaml` (from `config.example.yaml`; an existing file is
  backed up to `config.yaml.bak`)
- `/etc/recur/agent.env` — environment overrides for the systemd service
  (created once; edits stick)
- `/etc/systemd/system/recur-agent.service`

(`/etc/recur/agent.token` is *not* created by the installer — the agent writes
it itself, mode `0600`, on its first successful registration.)

Then finish the setup on that machine:

```bash
# Edit the configuration
sudo vim /etc/recur/config.yaml

# If the server is not on this host: point the agent at it
#   /etc/recur/agent.env -> RECUR_AGENT_SERVER_URL=http://your-server:8000

# If the server gates new registrations (RECUR_ENROLLMENT_TOKEN is set on
# the server), hand the agent the enrollment token:
#   /etc/recur/agent.env -> RECUR_AGENT_ENROLLMENT_TOKEN=<enrollment token>

sudo systemctl daemon-reload

# Start the agent
sudo systemctl start recur-agent
sudo systemctl enable recur-agent
```

**Running the agent directly** (no systemd): the CLI is
`recur-agent {run|check|register|report}` — `run` is the service loop,
`check` one cycle, `register` registration only, `report` print the current
report tree to stdout. Outside systemd it loads `RECUR_AGENT_ENV_FILE` (if
set) or `./.env` from the working directory; the default log is
`/var/log/recur-agent.log`.

**Uninstalling:** `sudo ./agent/uninstall.sh` (add `-y` to skip the prompt,
`-k` to keep `/etc/recur`).

## Environment Variables

All configuration lives in a single `.env` file that works in **both** run
modes:

```bash
cp .env.example .env
```

- **Standalone:** the server loads `.env` automatically on startup (repo root,
  or the current working directory) via `python-dotenv`.
- **Dockerized:** `docker compose` loads `.env` automatically for variable
  interpolation, and `docker-compose.yml` forwards the server variables into
  the container.
- **Agent:** the systemd unit reads `/etc/recur/agent.env` (created by
  `agent/install.sh`); running `recur-agent` directly loads
  `RECUR_AGENT_ENV_FILE` (if set) or `./.env` from the current directory.
- Real environment variables always take precedence over `.env` values.
  `.env` is git-ignored; never commit it (it may contain credentials).

### Server (standalone and dockerized)

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./recur.db` (standalone); derived from `DB_PASSWORD` (docker) | SQLAlchemy database URL, e.g. `postgresql+psycopg2://recur:secret@db.example.com:5432/recur` |
| `DEBUG` | `false` | `true` enables debug logging and uvicorn auto-reload; keep `false` in production (also exposes `/docs` and `/openapi.json`) |
| `LOG_LEVEL` | `INFO` | Logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `CORS_ORIGINS` | *(empty)* | Comma-separated allowed origins; empty disables CORS entirely (the dashboard is same-origin and needs none); `*` allows all origins |
| `RECUR_ENROLLMENT_TOKEN` | *(empty)* | Pre-shared token required for **new** agent registrations when set; empty = open registration (dev mode, logs a warning per registration). See [Agent Authentication](#agent-authentication) |

### Server (standalone only)

| Variable | Default | Meaning |
|---|---|---|
| `HOST` | `127.0.0.1` | Interface the server binds to (not used in docker mode); the standalone default is loopback — put a reverse proxy in front for network access |
| `PORT` | `8000` | Port the server listens on (in docker mode the container always listens on `8000`; map the host port with `RECUR_HTTP_PORT`) |

### Docker Compose (host side only)

| Variable | Default | Meaning |
|---|---|---|
| `RECUR_HTTP_PORT` | `8000` | Host port the server is published on |
| `PG_HOST_PORT` | `5432` | Host port the PostgreSQL container is published on |
| `DB_PASSWORD` | `recur-dev-password` | Password of the PostgreSQL `recur` user, used by the default `DATABASE_URL`; set a strong value outside local dev |

### Agent

| Variable | Default | Meaning |
|---|---|---|
| `RECUR_AGENT_SERVER_URL` | `http://localhost:8000` | Base URL of the central server (no trailing path) |
| `RECUR_AGENT_ID` | machine hostname | Unique agent identifier |
| `RECUR_AGENT_CONFIG_FILE` | `/etc/recur/config.yaml` | YAML file with the system, tasks, and dependencies to check |
| `RECUR_AGENT_LOG_FILE` | `/var/log/recur-agent.log` | Agent log file (systemd installs use `/var/log/recur/agent.log`) |
| `RECUR_AGENT_ENV_FILE` | `./.env` | `.env` file loaded when running the agent directly (systemd uses `/etc/recur/agent.env` instead) |
| `RECUR_AGENT_TOKEN_FILE` | `/etc/recur/agent.token` | Where the agent stores its server-issued bearer token (written mode `0600`; never commit it) |
| `RECUR_AGENT_ENROLLMENT_TOKEN` | *(empty)* | Bootstrap token for first registration when the server requires `RECUR_ENROLLMENT_TOKEN` |

## YAML Configuration

Each agent reads one YAML file (default `/etc/recur/config.yaml`). The top
level is a single `system:` block:

```yaml
system:
  name: "API Server"
  description: "Main API endpoint"
  interval: 60        # seconds between check cycles
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
| `http` / `https` | Check an HTTP endpoint | `url`, `expected_status`, `timeout` |
| `tcp` | Check a TCP port | `host`, `port`, `timeout` |
| `ping` | ICMP ping (needs the `ping` binary) | `host`, `timeout` |
| `command` | Execute a shell command (exit 0 = UP) | `command`, `timeout` |
| `script` | Execute a local script (exit 0 = UP) | `path`, `timeout` |

Tasks optionally accept `max_retries` (default 0).

### Nested Dependencies

`dependencies:` holds child systems, which may themselves have tasks and
further `dependencies:` — the tree is recursive to any depth:

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

`configs/complex-cluster.yaml` is a production-like example (web tier,
database layer, cache, backup, message queue); also see
`configs/simple-system.yaml` and `configs/multi-region.yaml`. The agent ships
with `agent/config.example.yaml`.

### Live Reloading

The agent re-reads the file **every cycle** — no restart needed. The server
syncs its side automatically with each report (see
[Agents, Systems, and Reports](#agents-systems-and-reports)): new tasks and
dependencies appear, removed ones are pruned, and the system name follows the
report.

## REST API

All endpoints are under `/api/v1`. `scripts/api-examples.sh` runs a full tour.

Agent-facing endpoints are authenticated — see
[Agent Authentication](#agent-authentication). `POST /status` and
`PUT /agents/{agent_id}/heartbeat` require the agent's bearer token
(`Authorization: Bearer <token>`); `POST /agents/register` issues it and,
when `RECUR_ENROLLMENT_TOKEN` is set, requires the enrollment token for new
agents.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Server health |
| `POST` | `/agents/register` | Register an agent (agents do this themselves on startup); issues/rotates its bearer token; new agents gated by the enrollment token when set |
| `GET` | `/agents` | List agents (`skip`, `limit`) |
| `GET` | `/agents/{agent_id}` | Agent details |
| `GET` | `/agents/{agent_id}/systems` | Systems reported by the agent |
| `POST` | `/agents/{agent_id}/check` | Request an immediate check (agent acts on its next interval) |
| `PUT` | `/agents/{agent_id}/heartbeat` | Agent heartbeat (requires the agent's token) |
| `DELETE` | `/agents/{agent_id}` | Remove agent |
| `POST` | `/status` | Submit a status report (what agents do automatically; requires the agent's token and an `agent_id` matching its owner; auto-registers unknown systems) |
| `POST` | `/systems` | Create a system (optional — the agent's first report registers it) |
| `GET` | `/systems` | List systems (`skip`, `limit`) |
| `GET` | `/systems/forest` | All systems as a forest of dependency trees |
| `GET` | `/systems/{system_id}` | System details |
| `PUT` | `/systems/{system_id}` | Update a system |
| `GET` | `/systems/{system_id}/tree` | Full dependency tree with per-task status |
| `GET` | `/systems/{system_id}/health` | Latest health summary |
| `GET` | `/systems/{system_id}/history` | Status report history (`limit`) |
| `DELETE` | `/systems/{system_id}` | Remove system |

### Examples

```bash
# Register an agent (agents do this themselves on startup).
# The first registration returns the agent's bearer token exactly once:
#   {"agent_id": "prod-web-01", ..., "agent_token": "<256-bit token>"}
# The agent stores it in /etc/recur/agent.token (0600) and sends it as
# "Authorization: Bearer <token>" on every later call.
curl -X POST http://localhost:8000/api/v1/agents/register \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"prod-web-01","hostname":"prod-web-01","ip_address":"10.0.1.42"}'

# Create a system (optional: the agent's first report registers it)
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

# Submit a status report (what agents do automatically; requires the
# agent's bearer token)
curl -X POST http://localhost:8000/api/v1/status \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <agent token>" \
  -d '{
    "agent_id": "prod-web-01",
    "timestamp": "2026-09-06T10:30:00Z",
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

# Trigger a manual check on an agent
curl -X POST http://localhost:8000/api/v1/agents/prod-web-01/check
```

## Dashboard

`http://localhost:8000/dashboard` (the `/` route redirects there):

- All monitored systems with live status (**UP** / **DOWN** / **UNKNOWN**),
  auto-refreshed
- A semantic **dependency tree** per system: nested dependencies, per-task
  status, durations, and error messages
- System description and last check time

## Project Layout

```
Recur/
├── README.md                  # This file
├── QUICK_START.md             # 5-minute getting started
├── SECURITY_TODO.md           # Security hardening roadmap & status
├── .env.example               # Documented environment template (all run modes)
├── Makefile
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
│   │   ├── security.py        # Bearer token + enrollment authentication
│   │   ├── routers/           # API endpoints (agents, systems, status)
│   │   ├── services/          # Business logic (report processing, evaluation)
│   │   ├── utils/             # Utilities (YAML loading, logging)
│   │   └── templates/         # Web UI templates (dashboard)
│   └── tests/                 # Test suite
│
├── agent/                     # Lightweight agent (pure Python)
│   ├── recur_agent.py         # Main agent entry point (CLI: run|check|register|report)
│   ├── health_check_utils.py  # Check executor (http/tcp/ping/command/script)
│   ├── _bootstrap.py          # PyYAML resolver (system → vendored fallback)
│   ├── vendor/yaml/           # Vendored pure-Python PyYAML (air-gapped hosts)
│   ├── config.example.yaml    # Example configuration
│   ├── install.sh             # Installation script
│   └── uninstall.sh           # Uninstallation script
│
├── configs/                   # Example configurations
│   ├── simple-system.yaml
│   ├── complex-cluster.yaml
│   └── multi-region.yaml
│
└── scripts/                   # Setup scripts
    ├── install-server.sh
    ├── dev-setup.sh
    └── api-examples.sh        # Full tour of the REST API
```

## Development

```bash
./scripts/dev-setup.sh         # or: make dev-setup  (venv + dependencies)
source venv/bin/activate
```

Run the test suite:

```bash
make test                      # or: pytest -v --cov=server/app
```

Code style (also enforced via pre-commit):

```bash
make lint                      # black --check + flake8 + mypy (server/)
make format                    # black + isort
```

Useful targets: `make run` (standalone server), `make run-docker`,
`make install-agent` / `make install-agent-local`.

Logs: the server writes one file per module under `server/logs/` (e.g.
`tail -f server/logs/server_app_main.log`); the agent logs to
`/var/log/recur/agent.log` under systemd.

## Deployment

### Production Checklist

- [ ] Create `.env` from `.env.example` and review all values (see
      [Environment Variables](#environment-variables))
- [ ] Set a strong `DB_PASSWORD` (or point `DATABASE_URL` at your own PostgreSQL)
- [ ] Set `DEBUG=false` (hides `/docs` and `/openapi.json`)
- [ ] Set `RECUR_ENROLLMENT_TOKEN` so new agent registrations are gated
      ([Agent Authentication](#agent-authentication))
- [ ] Leave `CORS_ORIGINS` empty or restrict it (CORS is off by default)
- [ ] Configure TLS/HTTPS certificates (reverse proxy)
- [ ] Set up log aggregation
- [ ] Configure monitoring and alerting (Recur itself can monitor the monitors)
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

### Server won't start

```bash
# Port 8000 already in use?
lsof -i :8000

# Start on a different port
PORT=8001 python -m server.app.main
```

### Agent not reporting status

1. Check agent logs: `sudo tail -f /var/log/recur/agent.log`
   (systemd installs; the script default is `/var/log/recur-agent.log`)
2. Verify configuration: `sudo cat /etc/recur/config.yaml`
3. Test connectivity from the agent host to the server:
   `curl http://your-server:8000/api/v1/health`
4. Look for `401`/`403` in the agent log (auth failures): the agent deletes
   its token file and re-registers automatically on the next cycle. If the
   server gates new registrations and the agent no longer holds a valid
   token, set `RECUR_AGENT_ENROLLMENT_TOKEN` in `/etc/recur/agent.env`, then
   `sudo systemctl daemon-reload`.
5. Reports are only accepted from **registered agents** — the agent
   self-heals after being deleted from the server (it re-registers on the
   next cycle and the server rotates its token); a restart also works. The
   system it reports does **not** need to be pre-created; the first report
   registers it ([How It Works](#agents-systems-and-reports)).

### All checks showing as DOWN

1. Verify network connectivity between the agent host and the targets
   (checks run **from the agent**)
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
3. Add tests for new features (`make test`)
4. Submit a pull request

## License

MIT License - see LICENSE file for details.

## Support

- **Issues**: Open a GitHub issue
- **Questions**: Check existing issues/discussions
- **Security**: security@example.com

---

**Built for infrastructure reliability**
