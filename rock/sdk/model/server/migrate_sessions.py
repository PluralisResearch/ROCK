"""Backfill session IDs for existing traces using the session inference algorithm.

Usage:
    cd ROCK && .venv/bin/python -m rock.sdk.model.server.migrate_sessions --db-path data/traces.db
"""

import argparse
import json
import sqlite3
import sys

from rock.sdk.model.server.session import SessionManager


def migrate(db_path: str, timeout_minutes: int = 30, dry_run: bool = False):
    """Read existing traces and backfill session_id using the fingerprint algorithm."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Count traces needing migration
    total = conn.execute("SELECT COUNT(*) FROM traces").fetchone()[0]
    empty_sessions = conn.execute("SELECT COUNT(*) FROM traces WHERE session_id = '' OR session_id IS NULL").fetchone()[
        0
    ]
    print(f"Database: {db_path}")
    print(f"Total traces: {total}")
    print(f"Traces without session_id: {empty_sessions}")

    if empty_sessions == 0:
        print("Nothing to migrate.")
        conn.close()
        return

    # Build a session manager with the same algorithm
    mgr = SessionManager(timeout_minutes=timeout_minutes)

    # Process traces in chronological order per user
    rows = conn.execute(
        "SELECT trace_id, timestamp, user_id, request_body FROM traces ORDER BY user_id, timestamp ASC"
    ).fetchall()

    updated = 0
    for row in rows:
        trace_id = row["trace_id"]
        user_id = row["user_id"]
        timestamp_str = row["timestamp"]

        # Parse timestamp to unix time
        from datetime import datetime

        try:
            dt = datetime.fromisoformat(timestamp_str)
            ts = dt.timestamp()
        except (ValueError, TypeError):
            ts = 0.0

        # Extract messages from request_body
        messages = []
        if row["request_body"]:
            try:
                req = json.loads(row["request_body"]) if isinstance(row["request_body"], str) else row["request_body"]
                messages = req.get("messages", [])
            except (json.JSONDecodeError, AttributeError):
                pass

        session_id = mgr.infer_session_id(user_id, messages, timestamp=ts)

        if not dry_run:
            conn.execute("UPDATE traces SET session_id = ? WHERE trace_id = ?", (session_id, trace_id))
            updated += 1

        if updated % 100 == 0 and updated > 0:
            conn.commit()
            print(f"  Updated {updated} traces...")

    conn.commit()
    conn.close()

    action = "Would update" if dry_run else "Updated"
    print(f"{action} {updated} traces with inferred session IDs.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill session IDs for existing traces")
    parser.add_argument("--db-path", required=True, help="Path to the SQLite traces database")
    parser.add_argument("--timeout-minutes", type=int, default=30, help="Session timeout in minutes (default: 30)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")
    args = parser.parse_args()

    try:
        migrate(args.db_path, timeout_minutes=args.timeout_minutes, dry_run=args.dry_run)
    except FileNotFoundError:
        print(f"Error: Database file not found: {args.db_path}", file=sys.stderr)
        sys.exit(1)
    except sqlite3.OperationalError as e:
        print(f"Error: SQLite error: {e}", file=sys.stderr)
        sys.exit(1)
