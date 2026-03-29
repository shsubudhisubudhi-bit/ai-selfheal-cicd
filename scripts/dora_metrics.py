"""
DORA Metrics Tracker for AI Self-Healing CI/CD
===============================================
Tracks the four key DORA (DevOps Research and Assessment) metrics:

  1. Deployment Frequency    — How often code is deployed to production
  2. Lead Time for Changes   — Time from commit to production deploy
  3. Mean Time to Recovery    — Average time to restore service after failure
  4. Change Failure Rate      — Percentage of deployments causing failures

Events are stored in a JSON log file (dora_events.json) and can be
queried via CLI or exposed as Prometheus-compatible /metrics output.

Usage:
  # Record events
  python dora_metrics.py record-deploy --commit abc123 --version v1.2.0
  python dora_metrics.py record-failure --deploy-id <id> --description "health check failed"
  python dora_metrics.py record-recovery --deploy-id <id>

  # View metrics
  python dora_metrics.py summary
  python dora_metrics.py prometheus
"""

import os
import sys
import json
import uuid
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

EVENTS_FILE = os.environ.get(
    "DORA_EVENTS_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dora_events.json"),
)

# ---------------------------------------------------------------------------
# Event storage helpers
# ---------------------------------------------------------------------------


def _load_events() -> list[dict]:
    """Load all events from the JSON log file."""
    path = Path(EVENTS_FILE)
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, IOError):
        return []


def _save_events(events: list[dict]) -> None:
    """Persist events to the JSON log file."""
    path = Path(EVENTS_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(events, fh, indent=2, default=str)


def _append_event(event: dict) -> dict:
    """Append a single event and return it."""
    events = _load_events()
    events.append(event)
    _save_events(events)
    return event


# ---------------------------------------------------------------------------
# Recording functions
# ---------------------------------------------------------------------------


def record_deployment(
    commit_sha: str = "",
    version: str = "",
    environment: str = "production",
    commit_timestamp: Optional[str] = None,
) -> dict:
    """Record a successful deployment.

    Args:
        commit_sha: The git commit hash that was deployed.
        version: Semantic version or image tag.
        environment: Target environment (production, staging, etc.).
        commit_timestamp: ISO timestamp of the original commit.
            Used to calculate lead time for changes.

    Returns:
        The recorded event dict including its generated deploy_id.
    """
    now = datetime.utcnow().isoformat()
    deploy_id = str(uuid.uuid4())[:8]

    # Calculate lead time if commit timestamp is provided
    lead_time_seconds = None
    if commit_timestamp:
        try:
            commit_dt = datetime.fromisoformat(commit_timestamp.replace("Z", "+00:00").replace("+00:00", ""))
            lead_time_seconds = (datetime.utcnow() - commit_dt).total_seconds()
        except (ValueError, TypeError):
            pass

    event = {
        "type": "deployment",
        "deploy_id": deploy_id,
        "timestamp": now,
        "commit_sha": commit_sha,
        "version": version,
        "environment": environment,
        "commit_timestamp": commit_timestamp,
        "lead_time_seconds": lead_time_seconds,
        "status": "success",
    }
    _append_event(event)
    print(f"[DORA] Deployment recorded: id={deploy_id} version={version} env={environment}")
    return event


def record_failure(
    deploy_id: str = "",
    description: str = "",
    severity: str = "critical",
) -> dict:
    """Record a deployment failure or production incident.

    Args:
        deploy_id: ID of the deployment that caused the failure.
        description: Human-readable description of what failed.
        severity: Severity level (critical, warning, info).

    Returns:
        The recorded failure event dict.
    """
    now = datetime.utcnow().isoformat()
    failure_id = str(uuid.uuid4())[:8]

    event = {
        "type": "failure",
        "failure_id": failure_id,
        "deploy_id": deploy_id,
        "timestamp": now,
        "description": description,
        "severity": severity,
        "recovered": False,
        "recovery_timestamp": None,
        "mttr_seconds": None,
    }
    _append_event(event)
    print(f"[DORA] Failure recorded: id={failure_id} deploy={deploy_id} severity={severity}")
    return event


def record_recovery(
    deploy_id: str = "",
    failure_id: str = "",
    method: str = "ai-healer",
) -> dict:
    """Record a recovery from a failure, updating the original failure event.

    Args:
        deploy_id: The deployment that was recovered.
        failure_id: Specific failure ID (if known).
        method: Recovery method (ai-healer, rollback, manual, retry).

    Returns:
        The recorded recovery event dict with MTTR.
    """
    now = datetime.utcnow()
    events = _load_events()

    # Find the matching failure event to calculate MTTR
    mttr_seconds = None
    matched_failure_id = failure_id

    for event in reversed(events):
        if event.get("type") != "failure":
            continue
        if event.get("recovered"):
            continue
        # Match by failure_id or deploy_id
        if failure_id and event.get("failure_id") != failure_id:
            continue
        if not failure_id and deploy_id and event.get("deploy_id") != deploy_id:
            continue

        # Calculate MTTR
        try:
            fail_dt = datetime.fromisoformat(event["timestamp"])
            mttr_seconds = (now - fail_dt).total_seconds()
        except (ValueError, TypeError):
            pass

        # Update the failure event in place
        event["recovered"] = True
        event["recovery_timestamp"] = now.isoformat()
        event["mttr_seconds"] = mttr_seconds
        matched_failure_id = event.get("failure_id", "")
        break

    recovery_event = {
        "type": "recovery",
        "recovery_id": str(uuid.uuid4())[:8],
        "failure_id": matched_failure_id,
        "deploy_id": deploy_id,
        "timestamp": now.isoformat(),
        "method": method,
        "mttr_seconds": mttr_seconds,
    }
    events.append(recovery_event)
    _save_events(events)

    mttr_display = f"{mttr_seconds:.1f}s" if mttr_seconds else "unknown"
    print(f"[DORA] Recovery recorded: deploy={deploy_id} method={method} MTTR={mttr_display}")
    return recovery_event


# ---------------------------------------------------------------------------
# Metrics calculation
# ---------------------------------------------------------------------------


def calculate_metrics(days: int = 30) -> dict:
    """Calculate all four DORA metrics over a given time window.

    Args:
        days: Number of days to look back (default 30).

    Returns:
        Dictionary with all four DORA metrics and their classifications.
    """
    events = _load_events()
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

    # Filter events within the time window
    deployments = [
        e for e in events
        if e.get("type") == "deployment" and e.get("timestamp", "") >= cutoff
    ]
    failures = [
        e for e in events
        if e.get("type") == "failure" and e.get("timestamp", "") >= cutoff
    ]
    recoveries = [
        e for e in events
        if e.get("type") == "recovery" and e.get("timestamp", "") >= cutoff
    ]

    total_deploys = len(deployments)
    total_failures = len(failures)

    # --- 1. Deployment Frequency ---
    if days > 0 and total_deploys > 0:
        deploy_freq_per_day = total_deploys / days
    else:
        deploy_freq_per_day = 0.0

    if deploy_freq_per_day >= 1.0:
        freq_class = "Elite"
    elif deploy_freq_per_day >= 1 / 7:
        freq_class = "High"
    elif deploy_freq_per_day >= 1 / 30:
        freq_class = "Medium"
    else:
        freq_class = "Low"

    # --- 2. Lead Time for Changes ---
    lead_times = [
        e["lead_time_seconds"]
        for e in deployments
        if e.get("lead_time_seconds") is not None
    ]
    avg_lead_time = sum(lead_times) / len(lead_times) if lead_times else None

    if avg_lead_time is None:
        lt_class = "N/A"
    elif avg_lead_time < 3600:
        lt_class = "Elite"
    elif avg_lead_time < 86400:
        lt_class = "High"
    elif avg_lead_time < 604800:
        lt_class = "Medium"
    else:
        lt_class = "Low"

    # --- 3. Mean Time to Recovery (MTTR) ---
    mttrs = [
        e["mttr_seconds"]
        for e in recoveries
        if e.get("mttr_seconds") is not None
    ]
    # Also pull from failure events that have been marked recovered
    for e in failures:
        if e.get("mttr_seconds") is not None:
            mttrs.append(e["mttr_seconds"])

    # Deduplicate by using the set of unique values
    avg_mttr = sum(set(mttrs)) / len(set(mttrs)) if mttrs else None

    if avg_mttr is None:
        mttr_class = "N/A"
    elif avg_mttr < 3600:
        mttr_class = "Elite"
    elif avg_mttr < 86400:
        mttr_class = "High"
    elif avg_mttr < 604800:
        mttr_class = "Medium"
    else:
        mttr_class = "Low"

    # --- 4. Change Failure Rate ---
    if total_deploys > 0:
        change_failure_rate = (total_failures / total_deploys) * 100
    else:
        change_failure_rate = 0.0

    if change_failure_rate <= 5:
        cfr_class = "Elite"
    elif change_failure_rate <= 10:
        cfr_class = "High"
    elif change_failure_rate <= 30:
        cfr_class = "Medium"
    else:
        cfr_class = "Low"

    return {
        "window_days": days,
        "total_deployments": total_deploys,
        "total_failures": total_failures,
        "total_recoveries": len(recoveries),
        "deployment_frequency": {
            "deploys_per_day": round(deploy_freq_per_day, 2),
            "classification": freq_class,
        },
        "lead_time_for_changes": {
            "avg_seconds": round(avg_lead_time, 1) if avg_lead_time else None,
            "avg_human": _format_duration(avg_lead_time),
            "classification": lt_class,
        },
        "mean_time_to_recovery": {
            "avg_seconds": round(avg_mttr, 1) if avg_mttr else None,
            "avg_human": _format_duration(avg_mttr),
            "classification": mttr_class,
        },
        "change_failure_rate": {
            "percentage": round(change_failure_rate, 1),
            "classification": cfr_class,
        },
    }


def _format_duration(seconds: Optional[float]) -> str:
    """Format seconds into a human-readable duration string."""
    if seconds is None:
        return "N/A"
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.1f}m"
    if seconds < 86400:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds / 86400:.1f}d"


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------


def print_summary(days: int = 30) -> None:
    """Print a formatted summary table of DORA metrics to stdout."""
    metrics = calculate_metrics(days)

    print()
    print("=" * 68)
    print(f"  DORA METRICS SUMMARY  (last {days} days)")
    print("=" * 68)
    print()
    print(f"  Total Deployments:  {metrics['total_deployments']}")
    print(f"  Total Failures:     {metrics['total_failures']}")
    print(f"  Total Recoveries:   {metrics['total_recoveries']}")
    print()
    print("-" * 68)
    print(f"  {'Metric':<30} {'Value':<20} {'Level':<10}")
    print("-" * 68)

    df = metrics["deployment_frequency"]
    print(f"  {'Deployment Frequency':<30} {df['deploys_per_day']}/day{'':<13} {df['classification']:<10}")

    lt = metrics["lead_time_for_changes"]
    lt_val = lt["avg_human"]
    print(f"  {'Lead Time for Changes':<30} {lt_val:<20} {lt['classification']:<10}")

    mttr = metrics["mean_time_to_recovery"]
    mttr_val = mttr["avg_human"]
    print(f"  {'Mean Time to Recovery':<30} {mttr_val:<20} {mttr['classification']:<10}")

    cfr = metrics["change_failure_rate"]
    cfr_val = f"{cfr['percentage']}%"
    print(f"  {'Change Failure Rate':<30} {cfr_val:<20} {cfr['classification']:<10}")

    print("-" * 68)
    print()
    print("  Classification: Elite > High > Medium > Low")
    print("  (Based on DORA 2023 State of DevOps Report thresholds)")
    print()


def prometheus_metrics(days: int = 30) -> str:
    """Generate Prometheus-compatible /metrics text output.

    Returns:
        String in Prometheus exposition format.
    """
    metrics = calculate_metrics(days)
    lines = [
        "# HELP dora_deployment_frequency_per_day Number of deployments per day",
        "# TYPE dora_deployment_frequency_per_day gauge",
        f'dora_deployment_frequency_per_day{{window="{days}d"}} {metrics["deployment_frequency"]["deploys_per_day"]}',
        "",
        "# HELP dora_lead_time_seconds Average lead time for changes in seconds",
        "# TYPE dora_lead_time_seconds gauge",
        f'dora_lead_time_seconds{{window="{days}d"}} {metrics["lead_time_for_changes"]["avg_seconds"] or 0}',
        "",
        "# HELP dora_mttr_seconds Mean time to recovery in seconds",
        "# TYPE dora_mttr_seconds gauge",
        f'dora_mttr_seconds{{window="{days}d"}} {metrics["mean_time_to_recovery"]["avg_seconds"] or 0}',
        "",
        "# HELP dora_change_failure_rate_percent Percentage of deployments causing failures",
        "# TYPE dora_change_failure_rate_percent gauge",
        f'dora_change_failure_rate_percent{{window="{days}d"}} {metrics["change_failure_rate"]["percentage"]}',
        "",
        "# HELP dora_total_deployments Total number of deployments in window",
        "# TYPE dora_total_deployments gauge",
        f'dora_total_deployments{{window="{days}d"}} {metrics["total_deployments"]}',
        "",
        "# HELP dora_total_failures Total number of failures in window",
        "# TYPE dora_total_failures gauge",
        f'dora_total_failures{{window="{days}d"}} {metrics["total_failures"]}',
        "",
        "# HELP dora_total_recoveries Total number of recoveries in window",
        "# TYPE dora_total_recoveries gauge",
        f'dora_total_recoveries{{window="{days}d"}} {metrics["total_recoveries"]}',
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="DORA Metrics Tracker for AI Self-Healing CI/CD"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- record-deploy ---
    p_deploy = subparsers.add_parser("record-deploy", help="Record a deployment")
    p_deploy.add_argument("--commit", default="", help="Git commit SHA")
    p_deploy.add_argument("--version", default="", help="Version or image tag")
    p_deploy.add_argument("--env", default="production", help="Target environment")
    p_deploy.add_argument("--commit-time", default=None, help="ISO timestamp of commit")

    # --- record-failure ---
    p_fail = subparsers.add_parser("record-failure", help="Record a failure")
    p_fail.add_argument("--deploy-id", default="", help="Deployment ID that failed")
    p_fail.add_argument("--description", default="", help="Failure description")
    p_fail.add_argument("--severity", default="critical", help="Severity level")

    # --- record-recovery ---
    p_recover = subparsers.add_parser("record-recovery", help="Record a recovery")
    p_recover.add_argument("--deploy-id", default="", help="Deployment ID recovered")
    p_recover.add_argument("--failure-id", default="", help="Specific failure ID")
    p_recover.add_argument("--method", default="ai-healer", help="Recovery method")

    # --- summary ---
    p_summary = subparsers.add_parser("summary", help="Print DORA metrics summary")
    p_summary.add_argument("--days", type=int, default=30, help="Lookback window in days")

    # --- prometheus ---
    p_prom = subparsers.add_parser("prometheus", help="Output Prometheus metrics format")
    p_prom.add_argument("--days", type=int, default=30, help="Lookback window in days")

    args = parser.parse_args()

    if args.command == "record-deploy":
        record_deployment(
            commit_sha=args.commit,
            version=args.version,
            environment=args.env,
            commit_timestamp=args.commit_time,
        )
    elif args.command == "record-failure":
        record_failure(
            deploy_id=args.deploy_id,
            description=args.description,
            severity=args.severity,
        )
    elif args.command == "record-recovery":
        record_recovery(
            deploy_id=args.deploy_id,
            failure_id=args.failure_id,
            method=args.method,
        )
    elif args.command == "summary":
        print_summary(days=args.days)
    elif args.command == "prometheus":
        print(prometheus_metrics(days=args.days))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
