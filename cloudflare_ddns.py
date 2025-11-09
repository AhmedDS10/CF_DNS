#!/bin/bash

################################################################################
# Cloudflare Dynamic DNS Updater
# Monitors your public IP address and updates Cloudflare DNS records when it changes.
################################################################################

# Configuration
CF_API_TOKEN="your_cloudflare_api_token_here"
CF_ZONE_ID="your_zone_id_here"
CF_RECORD_NAME="subdomain.example.com"  # The DNS record to update
CHECK_INTERVAL=300  # Check every 5 minutes (in seconds)

# Files
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IP_CACHE_FILE="$HOME/.cloudflare_ddns_ip.txt"
LOG_FILE="$HOME/.cloudflare_ddns.log"
PID_FILE="$HOME/.cloudflare_ddns.pid"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

################################################################################
# Functions
################################################################################

log() {
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] $1" | tee -a "$LOG_FILE"
}

log_error() {
    echo -e "${RED}✗ $1${NC}" | tee -a "$LOG_FILE"
}

log_success() {
    echo -e "${GREEN}✓ $1${NC}" | tee -a "$LOG_FILE"
}

log_info() {
    echo -e "${YELLOW}ℹ $1${NC}" | tee -a "$LOG_FILE"
}

get_public_ip() {
    local ip=""
    local services=(
        "https://api.ipify.org"
        "https://ifconfig.me/ip"
        "https://icanhazip.com"
    )
    
    for service in "${services[@]}"; do
        ip=$(curl -s --max-time 5 "$service" 2>/dev/null | tr -d '[:space:]')
        if [[ $ip =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]]; then
            echo "$ip"
            return 0
        fi
    done
    
    return 1
}

get_cached_ip() {
    if [[ -f "$IP_CACHE_FILE" ]]; then
        cat "$IP_CACHE_FILE"
    fi
}

save_cached_ip() {
    echo "$1" > "$IP_CACHE_FILE"
}

get_dns_record() {
    local response=$(curl -s -X GET \
        "https://api.cloudflare.com/client/v4/zones/$CF_ZONE_ID/dns_records?name=$CF_RECORD_NAME" \
        -H "Authorization: Bearer $CF_API_TOKEN" \
        -H "Content-Type: application/json")
    
    echo "$response"
}

update_dns_record() {
    local record_id="$1"
    local new_ip="$2"
    local record_data="$3"
    
    # Extract record details
    local record_type=$(echo "$record_data" | grep -o '"type":"[^"]*"' | head -1 | cut -d'"' -f4)
    local proxied=$(echo "$record_data" | grep -o '"proxied":[^,}]*' | head -1 | cut -d':' -f2)
    local ttl=$(echo "$record_data" | grep -o '"ttl":[^,}]*' | head -1 | cut -d':' -f2)
    
    # Default values if not found
    [[ -z "$record_type" ]] && record_type="A"
    [[ -z "$proxied" ]] && proxied="false"
    [[ -z "$ttl" ]] && ttl="1"
    
    local update_data=$(cat <<EOF
{
    "type": "$record_type",
    "name": "$CF_RECORD_NAME",
    "content": "$new_ip",
    "ttl": $ttl,
    "proxied": $proxied
}
EOF
)
    
    local response=$(curl -s -X PUT \
        "https://api.cloudflare.com/client/v4/zones/$CF_ZONE_ID/dns_records/$record_id" \
        -H "Authorization: Bearer $CF_API_TOKEN" \
        -H "Content-Type: application/json" \
        --data "$update_data")
    
    echo "$response"
}

check_and_update() {
    log "Checking IP address..."
    
    # Get current public IP
    local current_ip=$(get_public_ip)
    if [[ -z "$current_ip" ]]; then
        log_error "Could not determine public IP address"
        return 1
    fi
    
    log_success "Current IP: $current_ip"
    
    # Get cached IP
    local cached_ip=$(get_cached_ip)
    
    # Check if IP has changed
    if [[ "$current_ip" == "$cached_ip" ]]; then
        log_info "IP address unchanged, no update needed"
        return 0
    fi
    
    log_info "IP address changed: $cached_ip → $current_ip"
    
    # Get DNS record
    local record_response=$(get_dns_record)
    
    # Check if request was successful
    local success=$(echo "$record_response" | grep -o '"success":[^,]*' | cut -d':' -f2)
    if [[ "$success" != "true" ]]; then
        log_error "Failed to fetch DNS record from Cloudflare"
        return 1
    fi
    
    # Extract record ID
    local record_id=$(echo "$record_response" | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)
    if [[ -z "$record_id" ]]; then
        log_error "DNS record not found: $CF_RECORD_NAME"
        return 1
    fi
    
    # Update DNS record
    local update_response=$(update_dns_record "$record_id" "$current_ip" "$record_response")
    
    # Check if update was successful
    local update_success=$(echo "$update_response" | grep -o '"success":[^,]*' | cut -d':' -f2)
    if [[ "$update_success" == "true" ]]; then
        log_success "DNS record updated successfully!"
        log_success "$CF_RECORD_NAME → $current_ip"
        save_cached_ip "$current_ip"
        return 0
    else
        log_error "Failed to update DNS record"
        return 1
    fi
}

start_daemon() {
    # Check if already running
    if [[ -f "$PID_FILE" ]]; then
        local old_pid=$(cat "$PID_FILE")
        if ps -p "$old_pid" > /dev/null 2>&1; then
            echo "Service is already running (PID: $old_pid)"
            echo "To stop it, run: $0 stop"
            exit 1
        else
            # Stale PID file
            rm -f "$PID_FILE"
        fi
    fi
    
    echo "Starting Cloudflare DDNS service..."
    
    # Start in background
    nohup "$0" monitor > /dev/null 2>&1 &
    local pid=$!
    echo $pid > "$PID_FILE"
    
    log_success "Service started (PID: $pid)"
    echo "Log file: $LOG_FILE"
    echo "To stop: $0 stop"
    echo "To check status: $0 status"
    echo "To view logs: tail -f $LOG_FILE"
}

stop_daemon() {
    if [[ ! -f "$PID_FILE" ]]; then
        echo "Service is not running"
        exit 1
    fi
    
    local pid=$(cat "$PID_FILE")
    if ps -p "$pid" > /dev/null 2>&1; then
        echo "Stopping Cloudflare DDNS service (PID: $pid)..."
        kill "$pid"
        rm -f "$PID_FILE"
        log_success "Service stopped"
    else
        echo "Service is not running (stale PID file removed)"
        rm -f "$PID_FILE"
    fi
}

status_daemon() {
    if [[ ! -f "$PID_FILE" ]]; then
        echo "Service is not running"
        exit 1
    fi
    
    local pid=$(cat "$PID_FILE")
    if ps -p "$pid" > /dev/null 2>&1; then
        echo "Service is running (PID: $pid)"
        echo "Monitoring: $CF_RECORD_NAME"
        echo "Check interval: $CHECK_INTERVAL seconds"
        echo "Log file: $LOG_FILE"
        if [[ -f "$IP_CACHE_FILE" ]]; then
            echo "Last known IP: $(cat $IP_CACHE_FILE)"
        fi
    else
        echo "Service is not running (stale PID file found)"
        rm -f "$PID_FILE"
        exit 1
    fi
}

monitor_loop() {
    log "=========================================="
    log "Cloudflare Dynamic DNS Updater Started"
    log "=========================================="
    log "Monitoring: $CF_RECORD_NAME"
    log "Check interval: $CHECK_INTERVAL seconds"
    log "=========================================="
    
    while true; do
        check_and_update
        sleep "$CHECK_INTERVAL"
    done
}

validate_config() {
    if [[ "$CF_API_TOKEN" == "your_cloudflare_api_token_here" ]]; then
        echo "ERROR: Please configure your Cloudflare API token in the script"
        echo ""
        echo "To get your API token:"
        echo "1. Go to https://dash.cloudflare.com/profile/api-tokens"
        echo "2. Create a token with 'Edit DNS' permissions"
        exit 1
    fi
    
    if [[ "$CF_ZONE_ID" == "your_zone_id_here" ]]; then
        echo "ERROR: Please configure your Cloudflare Zone ID"
        echo ""
        echo "To find your Zone ID:"
        echo "1. Go to your Cloudflare dashboard"
        echo "2. Select your domain"
        echo "3. Find Zone ID in the right sidebar"
        exit 1
    fi
    
    # Check for required commands
    for cmd in curl grep; do
        if ! command -v "$cmd" &> /dev/null; then
            echo "ERROR: Required command '$cmd' not found"
            exit 1
        fi
    done
}

################################################################################
# Main
################################################################################

case "${1:-start}" in
    start)
        validate_config
        start_daemon
        ;;
    stop)
        stop_daemon
        ;;
    restart)
        stop_daemon
        sleep 2
        start_daemon
        ;;
    status)
        status_daemon
        ;;
    monitor)
        # Internal command - runs the actual monitoring loop
        validate_config
        monitor_loop
        ;;
    check)
        # One-time check without daemon
        validate_config
        check_and_update
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|check}"
        echo ""
        echo "Commands:"
        echo "  start   - Start the service in the background"
        echo "  stop    - Stop the service"
        echo "  restart - Restart the service"
        echo "  status  - Check if service is running"
        echo "  check   - Run a one-time IP check (no daemon)"
        exit 1
        ;;
esac
