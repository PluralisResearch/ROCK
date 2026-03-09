"""SQLite-based trace storage for the ROCK Model Gateway."""

import json
import os
import sqlite3
import threading

_store: "TraceStore | None" = None


def init_store(db_path: str) -> "TraceStore":
    """Initialize the global trace store singleton."""
    global _store
    _store = TraceStore(db_path)
    return _store


def get_store() -> "TraceStore | None":
    """Get the global trace store instance, or None if not initialized."""
    return _store


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS traces (
    trace_id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    user_id TEXT NOT NULL DEFAULT 'anonymous',
    session_id TEXT NOT NULL DEFAULT '',
    agent_type TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    latency_ms REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'success',
    error TEXT,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    request_body TEXT,
    response_body TEXT
)
"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_traces_user_id ON traces (user_id)",
    "CREATE INDEX IF NOT EXISTS idx_traces_model ON traces (model)",
    "CREATE INDEX IF NOT EXISTS idx_traces_timestamp ON traces (timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_traces_status ON traces (status)",
]


class TraceStore:
    """Thread-safe SQLite trace store with WAL mode."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._is_memory = db_path == ":memory:"
        self._local = threading.local()
        self._shared_conn: sqlite3.Connection | None = None

        # Create directory if needed (skip for :memory:)
        if not self._is_memory:
            os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)

        # Initialize schema on the first connection
        conn = self._get_conn()
        conn.execute(_CREATE_TABLE)
        for idx_sql in _CREATE_INDEXES:
            conn.execute(idx_sql)
        conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        """Get a SQLite connection. Uses a shared connection for :memory: databases,
        thread-local connections for file-based databases."""
        if self._is_memory:
            if self._shared_conn is None:
                self._shared_conn = sqlite3.connect(":memory:", check_same_thread=False)
                self._shared_conn.row_factory = sqlite3.Row
            return self._shared_conn

        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn = conn
        return conn

    def insert(self, trace_data: dict):
        """Insert a trace record."""
        conn = self._get_conn()
        token_usage = trace_data.get("token_usage", {})
        conn.execute(
            """INSERT OR IGNORE INTO traces
            (trace_id, timestamp, user_id, session_id, agent_type, model,
             latency_ms, status, error, prompt_tokens, completion_tokens, total_tokens,
             request_body, response_body)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                trace_data["trace_id"],
                trace_data["timestamp"],
                trace_data.get("user_id", "anonymous"),
                trace_data.get("session_id", ""),
                trace_data.get("agent_type", ""),
                trace_data.get("model", ""),
                trace_data.get("latency_ms", 0),
                trace_data.get("status", "success"),
                trace_data.get("error"),
                token_usage.get("prompt_tokens", 0),
                token_usage.get("completion_tokens", 0),
                token_usage.get("total_tokens", 0),
                json.dumps(trace_data.get("request"), ensure_ascii=False) if trace_data.get("request") else None,
                json.dumps(trace_data.get("response"), ensure_ascii=False) if trace_data.get("response") else None,
            ),
        )
        conn.commit()

    def get_by_id(self, trace_id: str) -> dict | None:
        """Get a single trace by ID."""
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM traces WHERE trace_id = ?", (trace_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def query(
        self,
        user_id: str | None = None,
        model: str | None = None,
        status: str | None = None,
        agent_type: str | None = None,
        session_id: str | None = None,
        start: str | None = None,
        end: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """Query traces with optional filters."""
        conditions = []
        params: list = []

        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        if model:
            conditions.append("model = ?")
            params.append(model)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if agent_type:
            conditions.append("agent_type = ?")
            params.append(agent_type)
        if session_id:
            conditions.append("session_id = ?")
            params.append(session_id)
        if start:
            conditions.append("timestamp >= ?")
            params.append(start)
        if end:
            conditions.append("timestamp <= ?")
            params.append(end)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        sql = f"SELECT * FROM traces{where} ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        conn = self._get_conn()
        rows = conn.execute(sql, params).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_stats(
        self,
        user_id: str | None = None,
        model: str | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> dict:
        """Get aggregate statistics."""
        conditions = []
        params: list = []

        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        if model:
            conditions.append("model = ?")
            params.append(model)
        if start:
            conditions.append("timestamp >= ?")
            params.append(start)
        if end:
            conditions.append("timestamp <= ?")
            params.append(end)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""

        conn = self._get_conn()
        row = conn.execute(
            f"""SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success_count,
                SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as error_count,
                AVG(latency_ms) as avg_latency_ms,
                MIN(latency_ms) as min_latency_ms,
                MAX(latency_ms) as max_latency_ms,
                SUM(prompt_tokens) as total_prompt_tokens,
                SUM(completion_tokens) as total_completion_tokens,
                SUM(total_tokens) as total_tokens
            FROM traces{where}""",
            params,
        ).fetchone()

        return {
            "total": row["total"],
            "success_count": row["success_count"] or 0,
            "error_count": row["error_count"] or 0,
            "avg_latency_ms": round(row["avg_latency_ms"], 2) if row["avg_latency_ms"] else 0,
            "min_latency_ms": row["min_latency_ms"] or 0,
            "max_latency_ms": row["max_latency_ms"] or 0,
            "total_prompt_tokens": row["total_prompt_tokens"] or 0,
            "total_completion_tokens": row["total_completion_tokens"] or 0,
            "total_tokens": row["total_tokens"] or 0,
        }

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        """Convert a SQLite Row to a dict, parsing JSON fields."""
        d = dict(row)
        # Parse JSON body fields
        for field in ("request_body", "response_body"):
            if d.get(field):
                try:
                    d[field] = json.loads(d[field])
                except (json.JSONDecodeError, TypeError):
                    pass
        # Reconstruct token_usage
        d["token_usage"] = {
            "prompt_tokens": d.pop("prompt_tokens", 0),
            "completion_tokens": d.pop("completion_tokens", 0),
            "total_tokens": d.pop("total_tokens", 0),
        }
        return d
