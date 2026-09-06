# Quick Start Guide - Recur Health Monitoring Platform

## Overview

Recur is a complete system for monitoring the health of complex hierarchical systems. This guide will get you up and running in 5 minutes.

## Prerequisites

- Python 3.11+
- Bash 4.0+
- curl
- git (optional, for cloning)

## 1. Quick Installation (5 minutes)

### Server Setup

```bash
# Clone or navigate to the Recur directory
cd Recur

# Install server
./scripts/install-server.sh

# Activate virtual environment
source venv/bin/activate

# Start the server
python server/app/main.py
```

The server will start on `http://localhost:8000`.

**Access the dashboard:** http://localhost:8000/dashboard

### Agent Setup (Optional - On Another Machine)

```bash
# Download and run installation
curl -s https://raw.githubusercontent.com/mvineetmenon/Recur/main/agent/install.sh | sudo bash

# Configure the agent
sudo vim /etc/recur/config.yaml

# Edit to point to your server:
# SERVER_URL=http://your-server:8000

# Start the agent
sudo systemctl start recur-agent
sudo systemctl enable recur-agent
```

## 2. Quick API Testing

### Register an Agent

```bash
curl -X POST http://localhost:8000/api/v1/agents/register \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "my-agent",
    "hostname": "my-host",
    "ip_address": "192.168.1.100"
  }'
```

### Create a System

```bash
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
```

### Submit a Status Report

```bash
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
        {
          "task_id": "web_health",
          "name": "web_health",
          "type": "http",
          "status": "UP",
          "duration_ms": 150
        }
      ],
      "dependencies": []
    }
  }'
```

### List Systems

```bash
curl http://localhost:8000/api/v1/systems
```

### Get System Tree

```bash
curl http://localhost:8000/api/v1/systems/my-system/tree
```

### Get System Health

```bash
curl http://localhost:8000/api/v1/systems/my-system/health
```

## 3. YAML Configuration Basics

Create a file `my-config.yaml`:

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

The agent will automatically parse this and execute all checks recursively.

## 4. Supported Health Check Types

### HTTP / HTTPS
```yaml
- name: "api_check"
  type: http
  url: "http://api.example.com/health"
  expected_status: 200
  timeout: 5
```

### TCP Port Check
```yaml
- name: "db_check"
  type: tcp
  host: "db.internal"
  port: 5432
  timeout: 3
```

### Ping
```yaml
- name: "ping_check"
  type: ping
  host: "example.com"
  timeout: 5
```

### Shell Command
```yaml
- name: "cmd_check"
  type: command
  command: "pg_isready -h db.internal"
  timeout: 10
```

## 5. Key Concepts

### Recursive Status Evaluation

A system is **UP** only if:
1. All its tasks are **UP**, AND
2. All its dependencies (recursively) are **UP**

If any task or dependency is **DOWN**, the entire system is **DOWN**.

### Agent Workflow

1. Agent reads YAML configuration
2. Executes all health checks (tasks)
3. Recursively processes dependencies
4. Builds JSON report of entire tree
5. Pushes report to central server
6. Server evaluates overall status
7. Dashboard shows real-time status

## 6. Docker Compose (Optional)

Quick setup with Docker:

```bash
docker-compose up -d
# Server: http://localhost:8000
# Dashboard: http://localhost:8000/dashboard
```

## 7. Development

### Run Tests

```bash
make test
```

### Format Code

```bash
make format
```

### View Logs

```bash
# Server logs
tail -f server/logs/app.log

# Agent logs
sudo tail -f /var/log/recur/agent.log
```

## 8. Common Tasks

### Trigger Manual Check

```bash
curl -X POST http://localhost:8000/api/v1/agents/my-agent/check
```

### Get Agent Status

```bash
curl http://localhost:8000/api/v1/agents/my-agent
```

### Delete a System

```bash
curl -X DELETE http://localhost:8000/api/v1/systems/my-system
```

### Register Multiple Agents

```bash
for i in {1..5}; do
  curl -X POST http://localhost:8000/api/v1/agents/register \
    -H "Content-Type: application/json" \
    -d "{
      \"agent_id\": \"agent-$i\",
      \"hostname\": \"host-$i\",
      \"ip_address\": \"192.168.1.$i\"
    }"
done
```

## 9. Troubleshooting

### Server won't start

```bash
# Check if port 8000 is in use
lsof -i :8000

# Start on different port
PORT=8001 python server/app/main.py
```

### Agent can't connect to server

```bash
# Test connectivity
curl http://your-server:8000/api/v1/health

# Check firewall
sudo ufw allow 8000

# Check agent config
sudo cat /etc/recur/config.yaml
```

### Tasks always report DOWN

- Check that the targets are accessible
- Verify timeouts are appropriate
- Check firewall rules
- Review agent logs

## 10. Next Steps

- Read the [README.md](README.md) for complete documentation
- Explore [configs/](configs/) for production examples
- Check [server/app/](server/app/) for API details
- See [agent/](agent/) for agent customization

---

**Need help?** Check the troubleshooting section or open an issue on GitHub.
