#!/bin/bash

################################################################################
# Recur API Examples
# Common curl commands for interacting with the Recur server
################################################################################

# Set the server URL
SERVER="http://localhost:8000"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_section() {
    echo -e "\n${BLUE}=== $1 ===${NC}\n"
}

# ============================================================================
# HEALTH CHECK
# ============================================================================

print_section "1. Health Check - Server Status"
echo "GET $SERVER/api/v1/health"
curl -s "$SERVER/api/v1/health" | jq .

# ============================================================================
# AGENT MANAGEMENT
# ============================================================================

print_section "2. Register an Agent"
echo "POST $SERVER/api/v1/agents/register"
AGENT_RESPONSE=$(curl -s -X POST "$SERVER/api/v1/agents/register" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "prod-web-01",
    "hostname": "prod-web-01.internal",
    "ip_address": "10.0.1.100",
    "version": "0.1.0",
    "os_type": "Linux",
    "cpu_count": 4,
    "python_version": "3.11.0"
  }')
echo "$AGENT_RESPONSE" | jq .
AGENT_ID=$(echo "$AGENT_RESPONSE" | jq -r '.agent_id')

print_section "3. List All Agents"
echo "GET $SERVER/api/v1/agents"
curl -s "$SERVER/api/v1/agents?limit=10" | jq .

print_section "4. Get Specific Agent"
echo "GET $SERVER/api/v1/agents/$AGENT_ID"
curl -s "$SERVER/api/v1/agents/$AGENT_ID" | jq .

print_section "5. Get Agent Systems"
echo "GET $SERVER/api/v1/agents/$AGENT_ID/systems"
curl -s "$SERVER/api/v1/agents/$AGENT_ID/systems" | jq .

print_section "6. Send Agent Heartbeat"
echo "PUT $SERVER/api/v1/agents/$AGENT_ID/heartbeat"
curl -s -X PUT "$SERVER/api/v1/agents/$AGENT_ID/heartbeat" | jq .

# ============================================================================
# SYSTEM MANAGEMENT
# ============================================================================

print_section "7. Create a Simple System"
echo "POST $SERVER/api/v1/systems"
SYSTEM_RESPONSE=$(curl -s -X POST "$SERVER/api/v1/systems" \
  -H "Content-Type: application/json" \
  -d '{
    "system_id": "web-app",
    "name": "Web Application",
    "description": "Main web application service",
    "config": {
      "name": "Web Application",
      "tasks": [
        {
          "name": "api_health",
          "type": "http",
          "url": "http://localhost:8000/health",
          "expected_status": 200,
          "timeout": 5
        }
      ]
    }
  }')
echo "$SYSTEM_RESPONSE" | jq .
SYSTEM_ID=$(echo "$SYSTEM_RESPONSE" | jq -r '.system_id')

print_section "8. Create a Complex System with Dependencies"
echo "POST $SERVER/api/v1/systems"
curl -s -X POST "$SERVER/api/v1/systems" \
  -H "Content-Type: application/json" \
  -d '{
    "system_id": "production-cluster",
    "name": "Production Cluster",
    "description": "Full production environment",
    "config": {
      "name": "Production Cluster",
      "interval": 60,
      "tasks": [
        {
          "name": "cluster_ping",
          "type": "ping",
          "host": "cluster.example.com",
          "timeout": 5
        }
      ],
      "dependencies": [
        {
          "name": "Web Tier",
          "tasks": [
            {
              "name": "nginx",
              "type": "tcp",
              "host": "web1.internal",
              "port": 80,
              "timeout": 3
            }
          ]
        },
        {
          "name": "Database Layer",
          "tasks": [
            {
              "name": "postgres",
              "type": "tcp",
              "host": "db.internal",
              "port": 5432,
              "timeout": 3
            }
          ],
          "dependencies": [
            {
              "name": "Redis Cache",
              "tasks": [
                {
                  "name": "redis",
                  "type": "tcp",
                  "host": "cache.internal",
                  "port": 6379,
                  "timeout": 3
                }
              ]
            }
          ]
        }
      ]
    }
  }' | jq .)

print_section "9. List All Systems"
echo "GET $SERVER/api/v1/systems"
curl -s "$SERVER/api/v1/systems?limit=20" | jq .

print_section "10. Get Specific System"
echo "GET $SERVER/api/v1/systems/$SYSTEM_ID"
curl -s "$SERVER/api/v1/systems/$SYSTEM_ID" | jq .

print_section "11. Get System Health Summary"
echo "GET $SERVER/api/v1/systems/$SYSTEM_ID/health"
curl -s "$SERVER/api/v1/systems/$SYSTEM_ID/health" | jq .

# ============================================================================
# DEPENDENCY TREE
# ============================================================================

print_section "12. Get Full System Tree (with Dependencies)"
echo "GET $SERVER/api/v1/systems/$SYSTEM_ID/tree"
curl -s "$SERVER/api/v1/systems/$SYSTEM_ID/tree" | jq .

print_section "13. Get System Status History"
echo "GET $SERVER/api/v1/systems/$SYSTEM_ID/history"
curl -s "$SERVER/api/v1/systems/$SYSTEM_ID/history?limit=5" | jq .

# ============================================================================
# STATUS REPORTS
# ============================================================================

print_section "14. Submit Status Report from Agent"
echo "POST $SERVER/api/v1/status"
curl -s -X POST "$SERVER/api/v1/status" \
  -H "Content-Type: application/json" \
  -d "{
    \"agent_id\": \"$AGENT_ID\",
    \"timestamp\": \"$(date -u +'%Y-%m-%dT%H:%M:%SZ')\",
    \"system_status\": {
      \"system_id\": \"$SYSTEM_ID\",
      \"name\": \"Web Application\",
      \"status\": \"UP\",
      \"tasks\": [
        {
          \"task_id\": \"api_health\",
          \"name\": \"api_health\",
          \"type\": \"http\",
          \"status\": \"UP\",
          \"duration_ms\": 45.5,
          \"error\": null
        }
      ],
      \"dependencies\": []
    }
  }" | jq .

print_section "15. Submit Status Report with Failed Tasks"
echo "POST $SERVER/api/v1/status"
curl -s -X POST "$SERVER/api/v1/status" \
  -H "Content-Type: application/json" \
  -d "{
    \"agent_id\": \"$AGENT_ID\",
    \"timestamp\": \"$(date -u +'%Y-%m-%dT%H:%M:%SZ')\",
    \"system_status\": {
      \"system_id\": \"production-cluster\",
      \"name\": \"Production Cluster\",
      \"status\": \"DOWN\",
      \"tasks\": [
        {
          \"task_id\": \"cluster_ping\",
          \"name\": \"cluster_ping\",
          \"type\": \"ping\",
          \"status\": \"DOWN\",
          \"duration_ms\": 5000,
          \"error\": \"Ping timeout\"
        }
      ],
      \"dependencies\": [
        {
          \"system_id\": \"web-tier\",
          \"name\": \"Web Tier\",
          \"status\": \"UP\",
          \"tasks\": []
        },
        {
          \"system_id\": \"db-layer\",
          \"name\": \"Database Layer\",
          \"status\": \"DOWN\",
          \"tasks\": [
            {
              \"task_id\": \"postgres\",
              \"name\": \"postgres\",
              \"type\": \"tcp\",
              \"status\": \"DOWN\",
              \"duration_ms\": 3000,
              \"error\": \"Connection refused\"
            }
          ]
        }
      ]
    }
  }" | jq .)

# ============================================================================
# UPDATES & DELETIONS
# ============================================================================

print_section "16. Trigger Manual Check on Agent"
echo "POST $SERVER/api/v1/agents/$AGENT_ID/check"
curl -s -X POST "$SERVER/api/v1/agents/$AGENT_ID/check" | jq .

print_section "17. Delete a System"
echo "DELETE $SERVER/api/v1/systems/$SYSTEM_ID"
curl -s -X DELETE "$SERVER/api/v1/systems/$SYSTEM_ID"
echo "System deleted"

print_section "18. Delete an Agent"
echo "DELETE $SERVER/api/v1/agents/$AGENT_ID"
curl -s -X DELETE "$SERVER/api/v1/agents/$AGENT_ID"
echo "Agent deleted"

# ============================================================================
# PAGINATION EXAMPLES
# ============================================================================

print_section "19. List Systems with Pagination"
echo "GET $SERVER/api/v1/systems?skip=0&limit=10"
curl -s "$SERVER/api/v1/systems?skip=0&limit=10" | jq '.systems[0:2]'

echo -e "\n${GREEN}✓ Examples complete!${NC}\n"
