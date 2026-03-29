#!/usr/bin/env bash
# ============================================================
# Blue/Green Deployment Switch Script
# ============================================================
# Toggles the production service between the blue and green slots.
# After switching, verifies health of the new active slot and
# automatically rolls back if the health check fails.
#
# Usage:
#   ./blue_green_switch.sh              # Auto-detect and toggle
#   ./blue_green_switch.sh blue         # Switch to blue
#   ./blue_green_switch.sh green        # Switch to green
#
# Environment variables:
#   NAMESPACE       — Kubernetes namespace (default: selfheal)
#   SERVICE_NAME    — Service to patch (default: selfheal-app-bg)
#   HEALTH_PATH     — Health check path (default: /health)
#   HEALTH_RETRIES  — Number of health check attempts (default: 5)
#   HEALTH_DELAY    — Seconds between retries (default: 5)
# ============================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NAMESPACE="${NAMESPACE:-selfheal}"
SERVICE_NAME="${SERVICE_NAME:-selfheal-app-bg}"
CONFIGMAP_NAME="blue-green-state"
HEALTH_PATH="${HEALTH_PATH:-/health}"
HEALTH_RETRIES="${HEALTH_RETRIES:-5}"
HEALTH_DELAY="${HEALTH_DELAY:-5}"

# Colors for terminal output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

log_info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

get_current_slot() {
    kubectl get svc "$SERVICE_NAME" -n "$NAMESPACE" \
        -o jsonpath='{.spec.selector.slot}' 2>/dev/null || echo "unknown"
}

get_opposite_slot() {
    local current="$1"
    if [ "$current" = "blue" ]; then
        echo "green"
    else
        echo "blue"
    fi
}

check_deployment_ready() {
    local slot="$1"
    local deploy_name="selfheal-app-${slot}"
    local ready

    ready=$(kubectl get deployment "$deploy_name" -n "$NAMESPACE" \
        -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")

    if [ "${ready:-0}" -gt 0 ]; then
        return 0
    else
        return 1
    fi
}

health_check() {
    local slot="$1"
    local attempt=1

    log_info "Running health checks against slot: $slot"

    # Get a pod IP from the target deployment for direct health checking
    local pod_name
    pod_name=$(kubectl get pods -n "$NAMESPACE" \
        -l "app=selfheal-app,slot=${slot}" \
        -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")

    if [ -z "$pod_name" ]; then
        log_error "No pods found for slot $slot"
        return 1
    fi

    while [ $attempt -le "$HEALTH_RETRIES" ]; do
        log_info "Health check attempt $attempt/$HEALTH_RETRIES..."

        # Port-forward and check health (or use kubectl exec)
        local status
        status=$(kubectl exec "$pod_name" -n "$NAMESPACE" -- \
            wget -q -O - --timeout=5 "http://localhost:9090${HEALTH_PATH}" 2>/dev/null \
            | grep -o '"status":"[^"]*"' | head -1 || echo "")

        if echo "$status" | grep -q '"healthy"'; then
            log_ok "Health check PASSED (attempt $attempt)"
            return 0
        fi

        log_warn "Health check attempt $attempt failed. Waiting ${HEALTH_DELAY}s..."
        sleep "$HEALTH_DELAY"
        attempt=$((attempt + 1))
    done

    log_error "Health check FAILED after $HEALTH_RETRIES attempts"
    return 1
}

switch_traffic() {
    local target_slot="$1"
    local timestamp
    timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

    log_info "Patching service $SERVICE_NAME to route traffic to: $target_slot"

    kubectl patch svc "$SERVICE_NAME" -n "$NAMESPACE" \
        --type='json' \
        -p="[{\"op\": \"replace\", \"path\": \"/spec/selector/slot\", \"value\": \"${target_slot}\"}]"

    # Update the state ConfigMap
    kubectl patch configmap "$CONFIGMAP_NAME" -n "$NAMESPACE" \
        --type='merge' \
        -p="{\"data\":{\"active-slot\":\"${target_slot}\",\"last-switch-timestamp\":\"${timestamp}\",\"last-switch-reason\":\"blue-green switch\"}}" \
        2>/dev/null || log_warn "Could not update ConfigMap (non-critical)"

    # Update the preview service to point to the opposite slot
    local preview_slot
    preview_slot=$(get_opposite_slot "$target_slot")
    kubectl patch svc "selfheal-app-preview" -n "$NAMESPACE" \
        --type='json' \
        -p="[{\"op\": \"replace\", \"path\": \"/spec/selector/slot\", \"value\": \"${preview_slot}\"}]" \
        2>/dev/null || log_warn "Could not update preview service (non-critical)"

    log_ok "Traffic switched to: $target_slot"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

main() {
    echo ""
    echo "============================================================"
    echo "  BLUE/GREEN DEPLOYMENT SWITCH"
    echo "  Namespace: $NAMESPACE"
    echo "  Service:   $SERVICE_NAME"
    echo "  Timestamp: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    echo "============================================================"
    echo ""

    # Determine current and target slots
    local current_slot
    current_slot=$(get_current_slot)
    log_info "Current active slot: $current_slot"

    local target_slot
    if [ -n "${1:-}" ]; then
        target_slot="$1"
        if [ "$target_slot" != "blue" ] && [ "$target_slot" != "green" ]; then
            log_error "Invalid slot: $target_slot. Must be 'blue' or 'green'."
            exit 1
        fi
        if [ "$target_slot" = "$current_slot" ]; then
            log_warn "Slot $target_slot is already active. Nothing to do."
            exit 0
        fi
    else
        target_slot=$(get_opposite_slot "$current_slot")
    fi

    log_info "Target slot: $target_slot"

    # Step 1: Verify target deployment is ready
    echo ""
    log_info "Step 1: Verifying deployment selfheal-app-${target_slot} is ready..."

    if ! check_deployment_ready "$target_slot"; then
        log_error "Deployment selfheal-app-${target_slot} is not ready. Aborting switch."
        log_error "Ensure the target deployment has running pods before switching."
        exit 1
    fi
    log_ok "Deployment selfheal-app-${target_slot} is ready"

    # Step 2: Pre-switch health check on the target slot
    echo ""
    log_info "Step 2: Pre-switch health check on $target_slot..."

    if ! health_check "$target_slot"; then
        log_error "Pre-switch health check failed for $target_slot. Aborting."
        log_error "Fix the $target_slot deployment before switching traffic."
        exit 1
    fi

    # Step 3: Switch traffic
    echo ""
    log_info "Step 3: Switching traffic from $current_slot to $target_slot..."
    switch_traffic "$target_slot"

    # Step 4: Post-switch verification
    echo ""
    log_info "Step 4: Post-switch verification..."
    sleep 3  # Allow time for service endpoint propagation

    if health_check "$target_slot"; then
        echo ""
        log_ok "============================================================"
        log_ok "  SWITCH COMPLETE"
        log_ok "  Active slot:   $target_slot"
        log_ok "  Previous slot: $current_slot (now idle/preview)"
        log_ok "============================================================"
        echo ""
        exit 0
    else
        # ROLLBACK: Switch back to the previous slot
        echo ""
        log_error "Post-switch health check FAILED!"
        log_warn "ROLLING BACK to previous slot: $current_slot"

        switch_traffic "$current_slot"

        # Verify rollback
        sleep 3
        if health_check "$current_slot"; then
            log_ok "Rollback successful. Traffic restored to $current_slot."
        else
            log_error "CRITICAL: Rollback health check also failed!"
            log_error "Manual intervention required."
        fi

        echo ""
        log_error "============================================================"
        log_error "  SWITCH FAILED — ROLLED BACK"
        log_error "  Active slot:   $current_slot (restored)"
        log_error "  Failed slot:   $target_slot (needs investigation)"
        log_error "============================================================"
        echo ""
        exit 1
    fi
}

main "$@"
