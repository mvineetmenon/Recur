# Recur Verification Checklist

Use this checklist to verify your Recur installation and setup.

## ✅ Installation Verification

### Server Setup

- [ ] Python 3.12+ installed: `python3 --version`
- [ ] Virtual environment created: `ls -d venv`
- [ ] Dependencies installed: `pip list | grep fastapi`
- [ ] Database initialized: `ls -f recur.db` or check PostgreSQL
- [ ] Server starts: `python3 -m server.app.main`
- [ ] Health check responds: `curl http://localhost:8000/api/v1/health`
- [ ] Dashboard accessible: `curl http://localhost:8000/dashboard`

### Agent Setup (if deployed)

- [ ] Agent installed: `which recur-agent`
- [ ] Configuration exists: `ls -f /etc/recur/config.yaml`
- [ ] Agent service running: `sudo systemctl status recur-agent`
- [ ] Agent registered with server
- [ ] Agent sends heartbeat
- [ ] Logs readable: `tail /var/log/recur/agent.log`

## ✅ Feature Verification

### API Endpoints

- [ ] **Health Check**
  ```bash
  curl http://localhost:8000/api/v1/health
  # Should return: {"status": "healthy", ...}
  ```

- [ ] **Agent Registration**
  ```bash
  curl -X POST http://localhost:8000/api/v1/agents/register \
    -H "Content-Type: application/json" \
    -d '{"agent_id":"test","hostname":"test","ip_address":"127.0.0.1"}'
  # Should return agent data
  ```

- [ ] **List Agents**
  ```bash
  curl http://localhost:8000/api/v1/agents
  # Should return: {"total": N, "agents": [...]}
  ```

- [ ] **Create System**
  ```bash
  curl -X POST http://localhost:8000/api/v1/systems \
    -H "Content-Type: application/json" \
    -d '{
      "system_id":"test",
      "name":"Test",
      "config":{"name":"Test","tasks":[]}
    }'
  # Should return created system
  ```

- [ ] **List Systems**
  ```bash
  curl http://localhost:8000/api/v1/systems
  # Should return: {"total": N, "systems": [...]}
  ```

- [ ] **Submit Status Report**
  ```bash
  curl -X POST http://localhost:8000/api/v1/status \
    -H "Content-Type: application/json" \
    -d '{
      "agent_id":"test",
      "timestamp":"2026-09-06T10:00:00Z",
      "system_status":{"system_id":"test","name":"Test","status":"UP","tasks":[]}
    }'
  # Should return: {"status": "accepted", ...}
  ```

### Health Check Types

- [ ] **HTTP Check**
  - Configuration accepted
  - Timeout respected
  - Status code validated

- [ ] **TCP Check**
  - Port connectivity verified
  - Timeout respected
  - Connection refused handled

- [ ] **Ping Check**
  - ICMP echo works
  - Timeout respected
  - Network unreachable handled

- [ ] **Command Check**
  - Shell commands execute
  - Exit code checked
  - Timeout enforced

### Recursive Evaluation

- [ ] Create system with dependencies
- [ ] All child tasks UP → system UP
- [ ] One child task DOWN → system DOWN
- [ ] One dependency DOWN → parent DOWN
- [ ] Deeply nested systems evaluated correctly

## ✅ Configuration Verification

### YAML Validation

- [ ] Simple YAML loads: `python3 -c "import yaml; yaml.safe_load(open('configs/simple-system.yaml'))"`
- [ ] Complex YAML loads: `python3 -c "import yaml; yaml.safe_load(open('configs/complex-cluster.yaml'))"`
- [ ] Multi-region YAML loads: `python3 -c "import yaml; yaml.safe_load(open('configs/multi-region.yaml'))"`
- [ ] Invalid YAML rejected (test with malformed file)
- [ ] Task type validation works
- [ ] Dependency nesting works

## ✅ Database Verification

### SQLite (Development)

- [ ] Database file exists: `ls -l recur.db`
- [ ] Tables created: `sqlite3 recur.db ".tables"`
- [ ] Agents table: `sqlite3 recur.db "SELECT COUNT(*) FROM agents;"`
- [ ] Systems table: `sqlite3 recur.db "SELECT COUNT(*) FROM systems;"`
- [ ] Tasks table: `sqlite3 recur.db "SELECT COUNT(*) FROM tasks;"`

### PostgreSQL (Production)

- [ ] Database connection works
- [ ] All tables created
- [ ] Foreign key constraints working
- [ ] Indexes created properly

## ✅ Testing Verification

- [ ] Unit tests pass: `make test`
- [ ] Coverage acceptable: `pytest --cov=server/app`
- [ ] Router tests pass: `pytest server/tests/test_routers.py -v`
- [ ] Service tests pass: `pytest server/tests/test_services.py -v`
- [ ] YAML tests pass: `pytest server/tests/test_yaml_loader.py -v`
- [ ] No import errors in modules
- [ ] No linting errors: `make lint`

## ✅ Code Quality Verification

- [ ] Type hints present: `grep -r "def.*->" server/app/`
- [ ] Docstrings written: `grep -r "\"\"\"" server/app/`
- [ ] Code formatted: `black --check server/`
- [ ] Imports sorted: `isort --check server/`
- [ ] No linting issues: `flake8 server/`
- [ ] Type checking passes: `mypy server/ --ignore-missing-imports`

## ✅ Documentation Verification

- [ ] README.md exists and is readable
- [ ] QUICK_START.md has clear instructions
- [ ] ARCHITECTURE.md explains design
- [ ] CONTRIBUTING.md guides development
- [ ] Inline code comments present
- [ ] API examples work: `bash scripts/api-examples.sh`

## ✅ Deployment Verification

### Docker Compose

- [ ] Docker installed: `docker --version`
- [ ] Docker Compose installed: `docker compose version`
- [ ] Services start: `docker compose up -d`
- [ ] Server responsive: `curl http://localhost:8000/api/v1/health`
- [ ] Services stop gracefully: `docker compose down`

### Installation Scripts

- [ ] `scripts/install-server.sh` runs without errors
- [ ] `scripts/dev-setup.sh` runs without errors
- [ ] `agent/install.sh` runs without errors (needs sudo)

## ✅ Performance Verification

### Response Times

- [ ] Health check: < 100ms
- [ ] List agents: < 200ms (with 10 agents)
- [ ] Get system: < 100ms
- [ ] Submit report: < 200ms
- [ ] Dashboard loads: < 1s

### Scalability

- [ ] Create 100 systems: should complete in <10s
- [ ] Submit 100 status reports: should complete in <20s
- [ ] Query system tree with 10 dependencies: < 500ms

## ✅ Security Verification

- [ ] No SQL injection possible (ORM used)
- [ ] No command injection possible (validated inputs)
- [ ] YAML safe parsing (yaml.safe_load)
- [ ] Input validation on all endpoints
- [ ] CORS configured
- [ ] No credentials in code
- [ ] Error messages don't leak internals

## ✅ Error Handling Verification

- [ ] Missing config file handled
- [ ] Invalid YAML handled
- [ ] Network timeout handled
- [ ] Database connection failure handled
- [ ] Invalid agent ID handled
- [ ] Invalid system ID handled
- [ ] Malformed JSON handled
- [ ] Missing required fields handled

## ✅ Logging Verification

- [ ] Server logs to file: `tail -f server/logs/server_app_main.log`
- [ ] Agent logs to file: `tail -f /var/log/recur/agent.log`
- [ ] Log format is consistent
- [ ] Error messages are helpful
- [ ] Debug level works: `LOG_LEVEL=DEBUG`

## ✅ Integration Verification

- [ ] Agent can register with server
- [ ] Agent can submit status reports
- [ ] Server processes reports correctly
- [ ] Dashboard shows updated status
- [ ] System status reflects task status
- [ ] Dependency status propagates correctly
- [ ] Historical reports stored

## 🔧 Troubleshooting

If any check fails, refer to the troubleshooting section in:
- [README.md](README.md#troubleshooting)
- [QUICK_START.md](QUICK_START.md#7-troubleshooting)
- [ARCHITECTURE.md](ARCHITECTURE.md)

## ✨ Optional Enhancements to Try

- [ ] Setup HTTPS/TLS
- [ ] Configure PostgreSQL backend
- [ ] Setup Docker Compose production profile
- [ ] Add authentication (JWT)
- [ ] Setup log aggregation
- [ ] Configure monitoring alerts
- [ ] Add custom health check type
- [ ] Extend API with new endpoint

## 📋 Final Verification Summary

**Date Verified**: _______________

**Verified By**: _______________

**All Checks Passed**: ☐ YES ☐ NO

**Issues Found**: (if any)

```
_____________________________
_____________________________
_____________________________
```

**Notes**:

```
_____________________________
_____________________________
_____________________________
```

---

Once all checks pass, your Recur installation is ready for production use! 🎉
