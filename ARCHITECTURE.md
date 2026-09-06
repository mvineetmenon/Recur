# Recur Architecture

## System Overview

Recur is a distributed health monitoring system with three main components:

```
┌─────────────────────────────────────────────────────────────────┐
│                         Web Dashboard                           │
│              (http://server:8000/dashboard)                     │
└─────────────────────┬───────────────────────────────────────────┘
                      │ HTTP/JSON
                      │
┌─────────────────────▼───────────────────────────────────────────┐
│                   Central Server (FastAPI)                      │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ REST API (OpenAPI/Swagger documentation)                │  │
│  │  /api/v1/agents/*                                       │  │
│  │  /api/v1/systems/*                                      │  │
│  │  /api/v1/status                                         │  │
│  └──────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ Services Layer (Business Logic)                         │  │
│  │  - StatusEvaluator (recursive evaluation)               │  │
│  │  - SystemManager (system lifecycle)                     │  │
│  │  - HealthCheckProcessor (report processing)             │  │
│  └──────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ Database (SQLAlchemy ORM)                               │  │
│  │  - SQLite (development)                                 │  │
│  │  - PostgreSQL (production)                              │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────▲───────────────────────────────────────────┘
                      │ HTTP/JSON
                      │
    ┌─────────────────┼─────────────────┬──────────────────┐
    │                 │                 │                  │
┌───▼───────┐  ┌────▼─────┐  ┌────────▼──┐  ┌─────────────▼──┐
│  Agent 1  │  │  Agent 2  │  │  Agent 3  │  │   Agent N     │
│ (Bash +   │  │ (Bash +   │  │ (Bash +   │  │ (Bash +       │
│  Python)  │  │  Python)  │  │  Python)  │  │  Python)      │
│           │  │           │  │           │  │               │
│ Config:   │  │ Config:   │  │ Config:   │  │ Config:       │
│ .yaml     │  │ .yaml     │  │ .yaml     │  │ .yaml         │
└───────────┘  └───────────┘  └───────────┘  └───────────────┘
    ▲              ▲              ▲              ▲
    │              │              │              │
    └──────────────┴──────────────┴──────────────┘
         Local Network / Internet
           (Periodic Connections)
```

## Core Components

### 1. Central Server (Python/FastAPI)

**Location**: `/workspaces/Recur/server/app/`

#### Application Structure

```
main.py                  # FastAPI app initialization, lifespan management
├── config.py           # Configuration management
├── models.py           # SQLAlchemy ORM models
├── schemas.py          # Pydantic request/response schemas
├── database.py         # Database session management
│
├── routers/            # API endpoint handlers
│   ├── agents.py       # Agent registration, listing, management
│   ├── systems.py      # System CRUD and querying
│   └── status.py       # Status report submission and history
│
├── services/           # Business logic layer
│   ├── status_evaluator.py    # Recursive status evaluation
│   ├── system_manager.py      # System lifecycle management
│   └── health_check.py        # Status report processing
│
├── utils/              # Utility functions
│   ├── yaml_loader.py  # YAML parsing and validation
│   └── logger.py       # Logging setup
│
└── templates/          # Web UI (HTML/CSS/JS)
    └── dashboard.html  # Real-time dashboard
```

#### Database Schema

**Core Tables**:

```
┌─────────────┐
│   Agents    │  (Remote monitoring agents)
├─────────────┤
│ id          │ (Primary Key)
│ agent_id    │ (Unique identifier)
│ hostname    │
│ ip_address  │
│ status      │ (UP, DOWN, UNKNOWN, DEGRADED)
│ last_heart  │
│ created_at  │
└─────────────┘

┌──────────────┐
│   Systems    │  (Monitored systems)
├──────────────┤
│ id           │
│ system_id    │ (Unique identifier)
│ agent_id     │ (FK to Agents)
│ name         │
│ config       │ (JSON: full YAML config)
│ status       │ (Overall system health)
│ last_check   │
└──────────────┘

┌────────────────┐
│     Tasks      │  (Individual health checks)
├────────────────┤
│ id             │
│ task_id        │
│ system_id      │ (FK to Systems)
│ task_type      │ (http, tcp, command, ping, script)
│ config         │ (JSON: type-specific config)
│ status         │
│ last_duration  │
│ last_error     │
└────────────────┘

┌──────────────────────┐
│  StatusReports       │  (Archived status reports)
├──────────────────────┤
│ id                   │
│ agent_id             │ (FK)
│ system_id            │ (FK)
│ report_timestamp     │ (When report was generated)
│ received_at          │ (When server received it)
│ report_data          │ (JSON: full report tree)
│ processing_duration  │
└──────────────────────┘

┌──────────────────────┐
│   TaskResults        │  (Individual task results)
├──────────────────────┤
│ id                   │
│ task_id              │ (FK)
│ status_report_id     │ (FK)
│ status               │
│ duration_ms          │
│ error_message        │
│ output_data          │ (JSON: type-specific output)
│ created_at           │
└──────────────────────┘

┌────────────────────────┐
│ SystemDependencies     │  (Dependency relationships)
├────────────────────────┤
│ id                     │
│ parent_system_id       │ (FK to Systems)
│ child_system_id        │ (FK to Systems)
│ criticality            │ (HIGH, MEDIUM, LOW)
└────────────────────────┘
```

### 2. Agent (Bash + Python)

**Location**: `/workspaces/Recur/agent/`

#### Execution Flow

```
┌──────────────────────────────────────┐
│  recur-agent.sh (Main Loop)          │
│  - Loads configuration               │
│  - Registers with server             │
│  - Runs periodic health checks       │
└──────────┬───────────────────────────┘
           │
           ├─ Load YAML config
           │
           ├─ Call: health_check_utils.py
           │         (execute checks)
           │
           ├─ Build JSON report tree
           │
           ├─ POST /api/v1/status
           │
           └─ Send heartbeat
```

#### Agent Components

**recur-agent.sh**:
- Main entry point (Bash)
- Configuration loading
- Agent registration
- Periodic health check loop
- Report submission
- Heartbeat management

**health_check_utils.py**:
- YAML parsing using PyYAML
- Recursive check execution
- Task type handling:
  - HTTP/HTTPS (curl-based)
  - TCP (bash socket check)
  - Ping (ICMP)
  - Command (arbitrary shell)
- JSON report generation

#### Configuration Format

```yaml
system:                    # Root system
  name: "String"          # Required: Display name
  description: "String"   # Optional: Description
  interval: 60            # Optional: Check interval (seconds)
  
  tasks:                  # Optional: Health check tasks
    - name: "String"      # Task identifier
      type: "http|tcp|ping|command|script"
      # Type-specific config...
  
  dependencies:           # Optional: Nested systems
    - name: "String"      # Recursive system definition
      # Same structure as parent
```

### 3. Data Flow

#### Health Check Submission

```
Agent                         Server
  │                              │
  ├─ Load config.yaml           │
  ├─ Execute all tasks          │
  ├─ Build JSON tree            │
  │                              │
  └─ POST /api/v1/status ──────►│
                                 │
                                 ├─ Validate agent exists
                                 ├─ Create StatusReport
                                 ├─ Process task results
                                 ├─ Evaluate system status
                                 ├─ Update database
                                 │
                                 └─ Return 200 OK
                                 │
  ◄──────────── Response ────────┘
```

#### Status Evaluation (Recursive)

```
evaluate_system_status(system):
  │
  ├─ Get all task statuses
  │   └─ If any task DOWN → return DOWN
  │
  ├─ For each dependency:
  │   └─ evaluate_system_status(dependency)  # Recursive!
  │       └─ If any dependency DOWN → return DOWN
  │
  └─ All tasks and dependencies UP → return UP
```

## Key Design Patterns

### 1. Recursive Status Evaluation

Systems are hierarchical trees. A system's health depends on:
1. **All its tasks** being UP
2. **All its dependencies** (recursively) being UP

If any task OR dependency fails, the entire system fails.

### 2. Configuration-Driven Architecture

Almost everything is controlled by YAML:
- System topology
- Health check definitions
- Check intervals
- Timeouts and retry policies

No code changes needed to add new systems or checks.

### 3. Lightweight Agent

- Pure Bash when possible
- Python only for YAML parsing and complex logic
- Minimal dependencies
- Self-contained in `/usr/local/bin/`
- Systemd service for management

### 4. REST API First

- All communication via HTTP/JSON
- RESTful design
- Agent-agnostic (could be replaced)
- Easy integration with existing tools

### 5. Immutable Status Reports

- Full reports stored in database
- Historical tracking
- Complete audit trail
- Enables root cause analysis

## Health Check Types

### HTTP/HTTPS

```python
def check_http(task, timeout):
    # curl to target URL
    # Compare HTTP status code
    # Return: UP/DOWN, duration, error message
```

### TCP Port

```python
def check_tcp(task, timeout):
    # Open socket to host:port
    # Check connection success
    # Return: UP/DOWN, duration, error message
```

### Ping (ICMP)

```python
def check_ping(task, timeout):
    # Send ICMP ping
    # Check response
    # Return: UP/DOWN, duration, error message
```

### Command (Arbitrary Shell)

```python
def check_command(task, timeout):
    # Execute shell command
    # Check exit code (0 = success)
    # Return: UP/DOWN, duration, error message
```

## Deployment Scenarios

### Development

```
localhost:8000 (Server)
        ▲
        │
        └─ localhost (Agent - same machine)
```

### Single Server + Multiple Agents

```
monitoring.example.com:8000 (Server)
        ▲
        ├─────────────────────────────────────┐
        │                                     │
    10.0.1.1 (Agent)          10.0.1.2 (Agent)
```

### Multi-Region

```
central.example.com:8000 (Server)
        ▲
        ├─────────────────┬──────────────────┐
        │                 │                  │
    us-east (Agent)  eu-central (Agent)  apac (Agent)
```

### High Availability

```
┌─ lb.example.com ─┐
│                  │
├─ server1:8000   │
├─ server2:8000   │
└─ server3:8000   │
        ▲
        └─ Shared PostgreSQL DB
        └─ Agents connect to LB
```

## Scalability Considerations

- **Agents**: Horizontal scaling - add more agents
- **Server**: Use PostgreSQL + load balancer for HA
- **Database**: Index on system_id, agent_id, timestamps
- **Reports**: Archive old reports to cold storage

## Security Considerations

- Agent-server communication over HTTPS (in production)
- API authentication (JWT recommended)
- Database user permissions (separate read/write users)
- Agent registration validation
- Input validation and sanitization
- Rate limiting on API

## Monitoring the Monitor

Recur itself should be monitored:
- Server health endpoint: `/api/v1/health`
- Database connectivity checks
- Agent heartbeats (timeout after 5 minutes)
- Reporting lag (when reports become old)

## Extension Points

1. **New Task Types**: Add check method to agent
2. **New API Endpoints**: Add router in `routers/`
3. **Custom Status Evaluation**: Extend `StatusEvaluator`
4. **Webhooks**: Add in `status.py`
5. **Authentication**: Add middleware in `main.py`
6. **Notifications**: Add alerting service

## Performance Characteristics

- HTTP check: ~50-200ms (depends on network)
- TCP check: ~5-50ms
- Ping: ~10-100ms
- Command: ~100ms-10s (varies)
- Report submission: <100ms (local processing)
- Status evaluation: O(n) where n = total tasks across tree
- Dashboard refresh: ~10s (configurable)

---

**See also**: [README.md](README.md), [QUICK_START.md](QUICK_START.md)
