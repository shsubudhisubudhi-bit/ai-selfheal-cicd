"""
AI Self-Healing Module
======================
Analyzes deployment logs using OpenAI GPT-4o and decides:
- RETRY: Try deploying again (transient error)
- ROLLBACK: Revert to previous stable version (code/config error)
- ESCALATE: Alert human (unknown/critical error)

Integrates with:
- audit_log.py: Structured logging of every AI decision for compliance
- dora_metrics.py: DORA metrics tracking (failures, recoveries, MTTR)

Used by GitHub Actions after a failed health check.
"""

import os
import sys
import json
import subprocess
import requests
from datetime import datetime
from openai import OpenAI

# Import audit and DORA modules (same directory)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_log import AuditLogger, AuditEntry  # noqa: E402
from dora_metrics import record_failure, record_recovery  # noqa: E402

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
DEPLOY_HOST = os.environ.get("DEPLOY_HOST", "localhost")
HEALTH_URL = os.environ.get("HEALTH_URL", f"http://{DEPLOY_HOST}:9090/health")

# Initialize the audit logger
audit = AuditLogger()

SYSTEM_PROMPT = """You are an AI DevOps engineer analyzing deployment failures.
You will receive application logs and health check results from a failed deployment.

Analyze the error and respond with EXACTLY one JSON object:
{
    "decision": "RETRY" | "ROLLBACK" | "ESCALATE",
    "reason": "Brief explanation of what went wrong",
    "confidence": 0.0-1.0,
    "suggested_fix": "What should be done to fix this permanently"
}

Decision criteria:
- RETRY: Transient errors (timeout, network blip, rate limit, resource temporarily unavailable)
- ROLLBACK: Application errors (crash, bad code, config error, dependency failure)
- ESCALATE: Infrastructure issues (disk full, out of memory, security breach, unknown errors)

Be concise and precise. This is an automated pipeline."""


def check_health(url: str) -> dict:
    """Check application health endpoint."""
    try:
        resp = requests.get(url, timeout=10)
        return {
            "status_code": resp.status_code,
            "body": resp.json(),
            "healthy": resp.status_code == 200,
        }
    except requests.exceptions.ConnectionError:
        return {"status_code": 0, "body": "Connection refused", "healthy": False}
    except Exception as e:
        return {"status_code": 0, "body": str(e), "healthy": False}


def get_container_logs(container_name: str = "selfheal-app", lines: int = 50) -> str:
    """Get recent container logs from Docker or Kubernetes."""
    # Try kubectl first (for AKS/K8s environments)
    try:
        result = subprocess.run(
            ["kubectl", "logs", "-l", "app=selfheal-app", "-n", "selfheal", "--tail", str(lines)],
            capture_output=True, text=True, timeout=15
        )
        if result.stdout.strip():
            return result.stdout + result.stderr
    except Exception:
        pass
    # Fallback to Docker (for VPS/local environments)
    try:
        result = subprocess.run(
            ["docker", "logs", "--tail", str(lines), container_name],
            capture_output=True, text=True, timeout=10
        )
        return result.stdout + result.stderr
    except Exception as e:
        return f"Failed to get logs: {e}"


def analyze_failure(health_result: dict, logs: str) -> dict:
    """Send failure data to OpenAI for analysis."""
    if not OPENAI_API_KEY:
        print("[WARN] No OPENAI_API_KEY set, defaulting to ROLLBACK")
        return {
            "decision": "ROLLBACK",
            "reason": "No AI analysis available (API key not configured)",
            "confidence": 0.5,
            "suggested_fix": "Configure OPENAI_API_KEY for AI-powered analysis",
        }

    client = OpenAI(api_key=OPENAI_API_KEY)

    user_prompt = f"""Deployment failed. Analyze and decide what to do.

HEALTH CHECK RESULT:
{json.dumps(health_result, indent=2)}

APPLICATION LOGS (last 50 lines):
{logs[-3000:]}

TIMESTAMP: {datetime.utcnow().isoformat()}

Respond with a JSON decision."""

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=300,
            response_format={"type": "json_object"},
        )
        result = json.loads(response.choices[0].message.content)
        return result
    except Exception as e:
        print(f"[ERROR] AI analysis failed: {e}")
        return {
            "decision": "ROLLBACK",
            "reason": f"AI analysis failed: {e}",
            "confidence": 0.3,
            "suggested_fix": "Check OpenAI API key and connectivity",
        }


def execute_decision(decision: dict, audit_entry: AuditEntry, container_name: str = "selfheal-app"):
    """Execute the AI's decision and update audit/DORA tracking."""
    action = decision.get("decision", "ESCALATE").upper()
    reason = decision.get("reason", "Unknown")
    confidence = decision.get("confidence", 0)

    print(f"\n{'='*60}")
    print(f"AI DECISION: {action}")
    print(f"REASON: {reason}")
    print(f"CONFIDENCE: {confidence:.0%}")
    print(f"SUGGESTED FIX: {decision.get('suggested_fix', 'N/A')}")
    print(f"{'='*60}\n")

    # Record the decision in audit log
    audit_entry.set_decision(
        decision=action,
        confidence=confidence,
        reason=reason,
        suggested_fix=decision.get("suggested_fix", ""),
    )

    # Record failure in DORA metrics
    deploy_id = os.environ.get("DEPLOY_ID", audit_entry.deploy_id or "unknown")
    failure_event = record_failure(
        deploy_id=deploy_id,
        description=reason,
        severity="critical" if action == "ESCALATE" else "warning",
    )

    if action == "RETRY":
        print("[ACTION] Retrying deployment...")
        # Try kubectl first, fallback to docker
        result = subprocess.run(
            ["kubectl", "rollout", "restart", "deployment/selfheal-app", "-n", "selfheal"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            subprocess.run(["docker", "restart", container_name], capture_output=True, timeout=30)
        print("[ACTION] Deployment restarted. Waiting 30s for health check...")
        import time
        time.sleep(30)
        health = check_health(HEALTH_URL)
        if health["healthy"]:
            print("[SUCCESS] Application recovered after retry!")
            audit_entry.set_result("success", action_taken="deployment restart (retry)")
            record_recovery(deploy_id=deploy_id, method="retry")
            return True
        else:
            print("[FAIL] Retry failed. Escalating to ROLLBACK...")
            action = "ROLLBACK"

    if action == "ROLLBACK":
        print("[ACTION] Rolling back to previous stable version...")
        # Try kubectl rollback first (K8s/AKS)
        result = subprocess.run(
            ["kubectl", "rollout", "undo", "deployment/selfheal-app", "-n", "selfheal"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            print(f"[ACTION] kubectl rollback: {result.stdout.strip()}")
        else:
            # Fallback: patch FAIL_MODE to false
            subprocess.run([
                "kubectl", "set", "env", "deployment/selfheal-app",
                "FAIL_MODE=false", "-n", "selfheal"
            ], capture_output=True, text=True, timeout=30)
            print("[ACTION] Patched FAIL_MODE=false")
        import time
        time.sleep(30)
        health = check_health(HEALTH_URL)
        if health["healthy"]:
            print("[SUCCESS] Rollback successful! App is healthy on previous version.")
            audit_entry.set_result("success", action_taken="rollback to stable")
            record_recovery(deploy_id=deploy_id, method="rollback")
            return True
        else:
            print("[FAIL] Rollback also failed. Escalating...")
            audit_entry.set_result(
                "failure",
                action_taken="rollback attempted but failed",
                error_details="Health check still failing after rollback",
            )

    # ESCALATE
    print("[ESCALATE] Sending alert to operations team...")
    print(f"[ESCALATE] Error summary: {reason}")
    if audit_entry.result == "":
        audit_entry.set_result("failure", action_taken="escalated to human operator")
    # In production: send Slack/email/PagerDuty alert
    return False


def main():
    """Main self-healing flow with audit logging and DORA tracking."""
    print(f"\n{'='*60}")
    print("AI SELF-HEALING PIPELINE")
    print(f"Timestamp: {datetime.utcnow().isoformat()}")
    print(f"{'='*60}\n")

    # Step 1: Check health
    print("[STEP 1] Checking application health...")
    health = check_health(HEALTH_URL)
    print(f"  Status: {health['status_code']}")
    print(f"  Healthy: {health['healthy']}")

    if health["healthy"]:
        print("\n[OK] Application is healthy. No action needed.")
        sys.exit(0)

    # Step 2: Gather logs
    print("\n[STEP 2] Gathering application logs...")
    logs = get_container_logs()
    log_line_count = len(logs.splitlines())
    print(f"  Log lines collected: {log_line_count}")

    # Start audit entry
    audit_entry = audit.start_entry(
        health_status=health,
        logs_analyzed=log_line_count,
        deploy_id=os.environ.get("DEPLOY_ID", ""),
        version=os.environ.get("APP_VERSION", ""),
        environment=os.environ.get("DEPLOY_ENV", "production"),
    )

    # Step 3: AI Analysis
    print("\n[STEP 3] Sending to AI for analysis...")
    decision = analyze_failure(health, logs)

    # Step 4: Execute
    print("\n[STEP 4] Executing AI decision...")
    success = execute_decision(decision, audit_entry)

    # Step 5: Commit audit log
    audit.commit(audit_entry)

    # Step 6: Final status
    print(f"\n[RESULT] Self-healing {'SUCCEEDED' if success else 'FAILED'}")
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
