#!/bin/bash

################################################################################
# Recur Health Check Agent
# Lightweight agent that executes health checks and reports to central server
################################################################################

set -euo pipefail

# Configuration
AGENT_VERSION="0.1.0"
CONFIG_FILE="${RECUR_CONFIG_FILE:-/etc/recur/config.yaml}"
SERVER_URL="${RECUR_SERVER_URL:-http://localhost:8000}"
AGENT_ID="${RECUR_AGENT_ID:-$(hostname)}"
LOG_FILE="${RECUR_LOG_FILE:-/var/log/recur-agent.log}"
CHECK_TIMEOUT="${RECUR_CHECK_TIMEOUT:-300}"

# State
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMP_DIR="${TEMP_DIR:-.}"
REPORT_FILE="${TEMP_DIR}/recur-report-$$.json"

################################################################################
# Logging
################################################################################

log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

log_error() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $*" | tee -a "$LOG_FILE" >&2
}

################################################################################
# Configuration Loading
################################################################################

load_config() {
    if [[ ! -f "$CONFIG_FILE" ]]; then
        log_error "Configuration file not found: $CONFIG_FILE"
        exit 1
    fi
    
    log "Loading configuration from: $CONFIG_FILE"
}

################################################################################
# Health Check Execution
################################################################################

execute_http_check() {
    local name="$1"
    local url="$2"
    local expected_status="${3:-200}"
    local timeout="${4:-5}"
    
    local start_time=$(date +%s%N)
    local response
    local http_code
    
    response=$(curl -s -w "\n%{http_code}" \
        --max-time "$timeout" \
        --connect-timeout 3 \
        "$url" 2>/dev/null || echo "error")
    
    local end_time=$(date +%s%N)
    local duration_ms=$(( (end_time - start_time) / 1000000 ))
    
    http_code=$(echo "$response" | tail -n1)
    
    if [[ "$http_code" == "$expected_status" ]]; then
        echo "$name:UP:$duration_ms"
    else
        echo "$name:DOWN:$duration_ms:HTTP $http_code (expected $expected_status)"
    fi
}

execute_tcp_check() {
    local name="$1"
    local host="$2"
    local port="$3"
    local timeout="${4:-5}"
    
    local start_time=$(date +%s%N)
    
    if timeout "$timeout" bash -c "echo >/dev/tcp/$host/$port" 2>/dev/null; then
        local end_time=$(date +%s%N)
        local duration_ms=$(( (end_time - start_time) / 1000000 ))
        echo "$name:UP:$duration_ms"
    else
        local end_time=$(date +%s%N)
        local duration_ms=$(( (end_time - start_time) / 1000000 ))
        echo "$name:DOWN:$duration_ms:Connection failed to $host:$port"
    fi
}

execute_ping_check() {
    local name="$1"
    local host="$2"
    local timeout="${3:-5}"
    
    local start_time=$(date +%s%N)
    
    if ping -c 1 -W "$timeout" "$host" >/dev/null 2>&1; then
        local end_time=$(date +%s%N)
        local duration_ms=$(( (end_time - start_time) / 1000000 ))
        echo "$name:UP:$duration_ms"
    else
        local end_time=$(date +%s%N)
        local duration_ms=$(( (end_time - start_time) / 1000000 ))
        echo "$name:DOWN:$duration_ms:Ping failed"
    fi
}

execute_command_check() {
    local name="$1"
    local command="$2"
    local timeout="${3:-5}"
    
    local start_time=$(date +%s%N)
    
    if timeout "$timeout" bash -c "$command" >/dev/null 2>&1; then
        local end_time=$(date +%s%N)
        local duration_ms=$(( (end_time - start_time) / 1000000 ))
        echo "$name:UP:$duration_ms"
    else
        local end_time=$(date +%s%N)
        local duration_ms=$(( (end_time - start_time) / 1000000 ))
        echo "$name:DOWN:$duration_ms:Command failed"
    fi
}

################################################################################
# YAML Parsing (Basic)
################################################################################

# Extract system name from YAML
get_system_name() {
    grep -A 1 "^system:" "$CONFIG_FILE" | grep "name:" | head -1 | sed 's/.*name:\s*"\?\([^"]*\)"\?/\1/'
}

# Extract system interval from YAML
get_system_interval() {
    grep "interval:" "$CONFIG_FILE" | head -1 | awk '{print $2}' || echo "60"
}

# Get tasks from YAML (simplified parsing)
get_tasks_json() {
    # This is a simplified implementation
    # For production, use a proper YAML parser (Python helper)
    
    # For now, return a dummy task for testing
    cat <<'EOF'
[
  {
    "name": "test_check",
    "type": "http",
    "url": "http://localhost:8000/health",
    "expected_status": 200,
    "timeout": 5
  }
]
EOF
}

################################################################################
# Report Generation
################################################################################

generate_report() {
    local system_id="$(hostname)"
    local system_name="$(get_system_name)"
    local timestamp="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
    
    # For now, generate a minimal report
    cat > "$REPORT_FILE" <<EOF
{
  "agent_id": "$AGENT_ID",
  "timestamp": "$timestamp",
  "system_status": {
    "system_id": "$system_id",
    "name": "${system_name:-Unknown}",
    "tasks": [],
    "status": "UP"
  }
}
EOF
    
    log "Report generated: $REPORT_FILE"
}

################################################################################
# Report Submission
################################################################################

submit_report() {
    if [[ ! -f "$REPORT_FILE" ]]; then
        log_error "Report file not found: $REPORT_FILE"
        return 1
    fi
    
    log "Submitting report to: $SERVER_URL/api/v1/status"
    
    local response
    response=$(curl -s -X POST \
        -H "Content-Type: application/json" \
        -d @"$REPORT_FILE" \
        "$SERVER_URL/api/v1/status" 2>&1)
    
    if echo "$response" | grep -q '"status"'; then
        log "Report submitted successfully"
        return 0
    else
        log_error "Failed to submit report: $response"
        return 1
    fi
}

################################################################################
# Agent Registration
################################################################################

register_agent() {
    log "Registering agent with server..."
    
    local response
    response=$(curl -s -X POST \
        -H "Content-Type: application/json" \
        -d "{
            \"agent_id\": \"$AGENT_ID\",
            \"hostname\": \"$(hostname)\",
            \"ip_address\": \"$(hostname -I | awk '{print $1}')\",
            \"version\": \"$AGENT_VERSION\",
            \"os_type\": \"$(uname -s)\",
            \"cpu_count\": $(nproc),
            \"python_version\": \"$(python3 --version 2>&1 | awk '{print $2}'||echo 'unknown')\"
        }" \
        "$SERVER_URL/api/v1/agents/register" 2>&1)
    
    if echo "$response" | grep -q '"agent_id"'; then
        log "Agent registered successfully"
        return 0
    else
        log_error "Failed to register agent: $response"
        return 1
    fi
}

################################################################################
# Heartbeat
################################################################################

send_heartbeat() {
    curl -s -X PUT \
        "$SERVER_URL/api/v1/agents/$AGENT_ID/heartbeat" \
        >/dev/null 2>&1 && log "Heartbeat sent" || log_error "Failed to send heartbeat"
}

################################################################################
# Main Loop
################################################################################

main() {
    log "Recur Agent started (v$AGENT_VERSION)"
    log "Configuration: $CONFIG_FILE"
    log "Server: $SERVER_URL"
    log "Agent ID: $AGENT_ID"
    
    load_config
    
    # Register agent
    register_agent || log_error "Failed to register agent (will retry later)"
    
    # Main check loop
    while true; do
        log "Starting health check cycle..."
        
        generate_report
        submit_report || log_error "Report submission failed"
        send_heartbeat
        
        local interval=$(get_system_interval)
        log "Next check in $interval seconds"
        sleep "$interval"
    done
}

################################################################################
# Entry Point
################################################################################

# Parse command line arguments
case "${1:-run}" in
    run)
        main
        ;;
    check)
        # Run a single check cycle
        register_agent
        generate_report
        submit_report
        ;;
    register)
        register_agent
        ;;
    *)
        echo "Usage: $0 {run|check|register}"
        exit 1
        ;;
esac
