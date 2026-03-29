"""
AI Decision Audit Logger for Self-Healing CI/CD
=================================================
Provides structured JSON logging of every AI healing decision for
compliance, debugging, and post-incident analysis.

Each audit entry captures:
  - timestamp          — When the decision was made (UTC ISO 8601)
  - health_status      — Health check result at the time of analysis
  - logs_analyzed      — Number of log lines fed to the AI
  - ai_decision        — RETRY / ROLLBACK / ESCALATE
  - confidence         — AI confidence score (0.0 - 1.0)
  - reason             — AI explanation of the root cause
  - suggested_fix      — Recommended permanent fix
  - action_taken       — What the healer actually did
  - result             — success / failure
  - duration_seconds   — Wall-clock time for the full healing cycle

Audit entries are appended to a JSONL file (one JSON object per line)
for easy streaming, grep, and ingestion by log aggregators.

Usage:
  # In code
  from audit_log import AuditLogger
  logger = AuditLogger()
  entry = logger.start_entry(health_status={...}, logs_analyzed=50)
  entry.set_decision("ROLLBACK", confidence=0.95, reason="...", suggested_fix="...")
  entry.set_result("success", action_taken="docker rollback")
  logger.commit(entry)

  # CLI — view recent decisions
  python audit_log.py recent --limit 10

  # CLI — search by decision type
  python audit_log.py search --decision ROLLBACK --days 7

  # CLI — export as JSON
  python audit_log.py export --days 30 --output audit_export.json
"""

import os
import sys
import json
import time
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

AUDIT_LOG_FILE = os.environ.get(
    "AUDIT_LOG_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "audit_log.jsonl"),
)

# ---------------------------------------------------------------------------
# Audit entry data class
# ---------------------------------------------------------------------------


@dataclass
class AuditEntry:
    """Represents a single AI healing decision audit record."""

    timestamp: str = ""
    health_status: dict = field(default_factory=dict)
    logs_analyzed: int = 0
    ai_decision: str = ""
    confidence: float = 0.0
    reason: str = ""
    suggested_fix: str = ""
    action_taken: str = ""
    result: str = ""
    duration_seconds: float = 0.0
    deploy_id: str = ""
    version: str = ""
    environment: str = "production"
    error_details: str = ""

    # Internal: not written to the log
    _start_time: float = field(default=0.0, repr=False)

    def set_decision(
        self,
        decision: str,
        confidence: float = 0.0,
        reason: str = "",
        suggested_fix: str = "",
    ) -> None:
        """Set the AI decision fields."""
        self.ai_decision = decision
        self.confidence = confidence
        self.reason = reason
        self.suggested_fix = suggested_fix

    def set_result(
        self,
        result: str,
        action_taken: str = "",
        error_details: str = "",
    ) -> None:
        """Set the outcome fields and calculate duration."""
        self.result = result
        self.action_taken = action_taken
        self.error_details = error_details
        if self._start_time > 0:
            self.duration_seconds = round(time.time() - self._start_time, 2)

    def to_dict(self) -> dict:
        """Convert to a clean dictionary (excludes internal fields)."""
        d = asdict(self)
        d.pop("_start_time", None)
        return d


# ---------------------------------------------------------------------------
# Audit logger
# ---------------------------------------------------------------------------


class AuditLogger:
    """Manages the audit log file and provides query capabilities."""

    def __init__(self, log_file: Optional[str] = None):
        self.log_file = log_file or AUDIT_LOG_FILE

    def start_entry(
        self,
        health_status: Optional[dict] = None,
        logs_analyzed: int = 0,
        deploy_id: str = "",
        version: str = "",
        environment: str = "production",
    ) -> AuditEntry:
        """Create a new audit entry with the start timestamp.

        Call this at the beginning of a healing cycle, then populate
        the decision and result fields as the cycle progresses.
        """
        return AuditEntry(
            timestamp=datetime.utcnow().isoformat() + "Z",
            health_status=health_status or {},
            logs_analyzed=logs_analyzed,
            deploy_id=deploy_id,
            version=version,
            environment=environment,
            _start_time=time.time(),
        )

    def commit(self, entry: AuditEntry) -> None:
        """Write a completed audit entry to the log file.

        The entry is appended as a single JSON line (JSONL format).
        """
        # Ensure duration is calculated if not already set
        if entry.duration_seconds == 0.0 and entry._start_time > 0:
            entry.duration_seconds = round(time.time() - entry._start_time, 2)

        path = Path(self.log_file)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry.to_dict(), default=str) + "\n")

        print(
            f"[AUDIT] Logged: decision={entry.ai_decision} "
            f"confidence={entry.confidence:.0%} result={entry.result} "
            f"duration={entry.duration_seconds}s"
        )

    def read_all(self) -> list[dict]:
        """Read all audit entries from the log file."""
        path = Path(self.log_file)
        if not path.exists():
            return []

        entries = []
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return entries

    def query(
        self,
        decision: Optional[str] = None,
        result: Optional[str] = None,
        days: Optional[int] = None,
        min_confidence: Optional[float] = None,
        limit: Optional[int] = None,
    ) -> list[dict]:
        """Search audit entries with optional filters.

        Args:
            decision: Filter by AI decision (RETRY, ROLLBACK, ESCALATE).
            result: Filter by result (success, failure).
            days: Only include entries from the last N days.
            min_confidence: Only include entries with confidence >= this value.
            limit: Maximum number of entries to return (most recent first).

        Returns:
            Filtered list of audit entry dicts, most recent first.
        """
        entries = self.read_all()

        if days is not None:
            cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
            entries = [e for e in entries if e.get("timestamp", "") >= cutoff]

        if decision:
            entries = [
                e for e in entries
                if e.get("ai_decision", "").upper() == decision.upper()
            ]

        if result:
            entries = [
                e for e in entries
                if e.get("result", "").lower() == result.lower()
            ]

        if min_confidence is not None:
            entries = [
                e for e in entries
                if e.get("confidence", 0) >= min_confidence
            ]

        # Most recent first
        entries.sort(key=lambda e: e.get("timestamp", ""), reverse=True)

        if limit is not None:
            entries = entries[:limit]

        return entries


# ---------------------------------------------------------------------------
# CLI formatters
# ---------------------------------------------------------------------------


def _print_table(entries: list[dict]) -> None:
    """Print audit entries in a formatted table."""
    if not entries:
        print("\n  No audit entries found matching the criteria.\n")
        return

    print()
    print("=" * 100)
    print(f"  {'Timestamp':<22} {'Decision':<10} {'Confidence':<12} {'Result':<10} {'Duration':<10} {'Reason'}")
    print("-" * 100)

    for entry in entries:
        ts = entry.get("timestamp", "")[:19]
        decision = entry.get("ai_decision", "?")
        confidence = entry.get("confidence", 0)
        result = entry.get("result", "?")
        duration = entry.get("duration_seconds", 0)
        reason = entry.get("reason", "")[:40]

        conf_str = f"{confidence:.0%}"
        dur_str = f"{duration:.1f}s"

        print(f"  {ts:<22} {decision:<10} {conf_str:<12} {result:<10} {dur_str:<10} {reason}")

    print("-" * 100)
    print(f"  Total entries: {len(entries)}")
    print()


def _print_detail(entry: dict) -> None:
    """Print a single audit entry in full detail."""
    print()
    print("=" * 60)
    print(f"  Timestamp:       {entry.get('timestamp', '')}")
    print(f"  Decision:        {entry.get('ai_decision', '')}")
    print(f"  Confidence:      {entry.get('confidence', 0):.0%}")
    print(f"  Result:          {entry.get('result', '')}")
    print(f"  Duration:        {entry.get('duration_seconds', 0):.1f}s")
    print(f"  Action Taken:    {entry.get('action_taken', '')}")
    print(f"  Deploy ID:       {entry.get('deploy_id', '')}")
    print(f"  Version:         {entry.get('version', '')}")
    print(f"  Environment:     {entry.get('environment', '')}")
    print(f"  Logs Analyzed:   {entry.get('logs_analyzed', 0)}")
    print(f"  Reason:          {entry.get('reason', '')}")
    print(f"  Suggested Fix:   {entry.get('suggested_fix', '')}")
    if entry.get("error_details"):
        print(f"  Error Details:   {entry.get('error_details', '')}")
    print(f"  Health Status:   {json.dumps(entry.get('health_status', {}))}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="AI Decision Audit Logger — query and view healing decisions"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- recent ---
    p_recent = subparsers.add_parser("recent", help="Show recent audit entries")
    p_recent.add_argument("--limit", type=int, default=10, help="Number of entries to show")

    # --- search ---
    p_search = subparsers.add_parser("search", help="Search audit entries")
    p_search.add_argument("--decision", help="Filter by decision (RETRY, ROLLBACK, ESCALATE)")
    p_search.add_argument("--result", help="Filter by result (success, failure)")
    p_search.add_argument("--days", type=int, help="Only last N days")
    p_search.add_argument("--min-confidence", type=float, help="Minimum confidence threshold")
    p_search.add_argument("--limit", type=int, default=20, help="Max entries to show")

    # --- detail ---
    p_detail = subparsers.add_parser("detail", help="Show full detail of most recent entry")
    p_detail.add_argument("--index", type=int, default=0, help="Entry index (0 = most recent)")

    # --- stats ---
    subparsers.add_parser("stats", help="Show aggregate statistics")

    # --- export ---
    p_export = subparsers.add_parser("export", help="Export entries as JSON")
    p_export.add_argument("--days", type=int, default=30, help="Export last N days")
    p_export.add_argument("--output", default=None, help="Output file (default: stdout)")

    args = parser.parse_args()
    logger = AuditLogger()

    if args.command == "recent":
        entries = logger.query(limit=args.limit)
        _print_table(entries)

    elif args.command == "search":
        entries = logger.query(
            decision=args.decision,
            result=args.result,
            days=args.days,
            min_confidence=args.min_confidence,
            limit=args.limit,
        )
        _print_table(entries)

    elif args.command == "detail":
        entries = logger.query(limit=args.index + 1)
        if args.index < len(entries):
            _print_detail(entries[args.index])
        else:
            print(f"\n  No entry at index {args.index}.\n")

    elif args.command == "stats":
        entries = logger.read_all()
        if not entries:
            print("\n  No audit entries found.\n")
            return

        total = len(entries)
        decisions = {}
        results = {}
        durations = []

        for e in entries:
            d = e.get("ai_decision", "UNKNOWN")
            r = e.get("result", "unknown")
            decisions[d] = decisions.get(d, 0) + 1
            results[r] = results.get(r, 0) + 1
            if e.get("duration_seconds"):
                durations.append(e["duration_seconds"])

        avg_duration = sum(durations) / len(durations) if durations else 0
        success_rate = (results.get("success", 0) / total * 100) if total > 0 else 0

        print()
        print("=" * 50)
        print("  AUDIT LOG STATISTICS")
        print("=" * 50)
        print(f"  Total Decisions:      {total}")
        print(f"  Success Rate:         {success_rate:.1f}%")
        print(f"  Avg Duration:         {avg_duration:.1f}s")
        print()
        print("  Decisions by Type:")
        for d, count in sorted(decisions.items()):
            print(f"    {d:<15} {count}")
        print()
        print("  Results:")
        for r, count in sorted(results.items()):
            print(f"    {r:<15} {count}")
        print("=" * 50)
        print()

    elif args.command == "export":
        entries = logger.query(days=args.days)
        output = json.dumps(entries, indent=2, default=str)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as fh:
                fh.write(output)
            print(f"[AUDIT] Exported {len(entries)} entries to {args.output}")
        else:
            print(output)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
