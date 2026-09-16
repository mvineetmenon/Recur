#!/bin/bash

################################################################################
# Recur Health Check Agent
# Lightweight agent that executes health checks and reports to central server
#
# All check logic lives in health_check_utils.py (next to this script).
# This script handles config/env, registration, loop, submission, heartbeat.
################################################################################

set -euo pipefail

# Configuration
AGENT_VERSION="0.1.0"
CONFIG_FILE="${RECUR_AGENT_CONFIG_FILE:-/etc/recur/config.yaml}"
SERVER_URL="${RECUR_AGENT_SERVER_URL:-http://localhost:8000}"
AGENT_ID="${RECUR_AGENT_ID:-$(hostname)}"
LOG_FILE="${RECUR_AGENT_LOG_FILE:-/var/log/recur-agent.log}"

################################################################################
# Path resolution (symlink-safe, so the agent works from /usr/local/bin too)
################################################################################

resolve_script_dir() {
    local source="${BASH_SOURCE[0]}"
    local dir

    while [[ -h "$source" ]]; do
        dir="$(cd "$(dirname "$source")" && pwd)"
        source="$(readlink "$source")"
        [[ "$source" != /* ]] && source="$dir/$source"
    done

    cd "$(dirname "$source")" && pwd
}

# State
SCRIPT_DIR="$(resolve_script_dir)"
TEMP_DIR="${TEMP_DIR:-.}"
REPORT_FILE="${TEMP_DIR}/recur-report-$$.json"
HEALTH_CHECK_PY="${SCRIPT_DIR}/health_check_utils.py"

################################################################################
# Logging
################################################################################

log() {
    # File logging is best-effort: a non-writable LOG_FILE (e.g. running
    # unprivileged) must not kill the agent under `set -euo pipefail`.
    local line="[$(date +'%Y-%m-%d %H:%M:%S')] $*"
    echo "$line"
    tee -a "$LOG_FILE" >/dev/null 2>&1 <<<"$line" || true
}

log_error() {
    local line="[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $*"
    echo "$line" >&2
    tee -a "$LOG_FILE" >/dev/null 2>&1 <<<"$line" || true
}

################################################################################
# Configuration Loading
################################################################################

load_config() {
    if [[ ! -f "$CONFIG_FILE" ]]; then
        log_error "Configuration file not found: $CONFIG_FILE"
        exit 1
    fi

    if [[ ! -f "$HEALTH_CHECK_PY" ]]; then
        log_error "Health check helper not found: $HEALTH_CHECK_PY"
        exit 1
    fi

    log "Loading configuration from: $CONFIG_FILE"
}

# Get the root system check interval (seconds) via the Python helper
get_system_interval() {
    local interval
    interval=$(python3 "$HEALTH_CHECK_PY" --config "$CONFIG_FILE" \
        --agent-id "$AGENT_ID" --print-interval 2>/dev/null) || interval=""
    if [[ "$interval" =~ ^[0-9]+$ ]] && [[ "$interval" -gt 0 ]]; then
        echo "$interval"
    else
        echo 60
    fi
}

################################################################################
# Report Generation
################################################################################

generate_report() {
    # The Python helper runs every configured check (including nested
    # dependencies) and writes the full report envelope:
    #   { "agent_id", "timestamp", "system_status": { system_id, tasks, dependencies, ... } }
    if ! python3 "$HEALTH_CHECK_PY" \
        --config "$CONFIG_FILE" \
        --agent-id "$AGENT_ID" \
        --output "$REPORT_FILE"; then
        log_error "Health check execution failed"
        return 1
    fi

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

        generate_report || log_error "Report generation failed"
        submit_report || log_error "Report submission failed"
        send_heartbeat

        local interval
        interval=$(get_system_interval)
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
        load_config
        register_agent || true
        generate_report
        submit_report
        ;;
    register)
        register_agent
        ;;
    report)
        # Generate a report file only (useful for debugging)
        load_config
        generate_report
        echo "$REPORT_FILE"
        ;;
    *)
        echo "Usage: $0 {run|check|register|report}"
        exit 1
        ;;
esac
