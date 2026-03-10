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
    "CREATE INDEX IF NOT EXISTS idx_traces_session_id ON traces (session_id)",
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

    def get_user_stats(
        self,
        start: str | None = None,
        end: str | None = None,
    ) -> list[dict]:
        """Get per-user aggregate statistics."""
        conditions = []
        params: list = []

        if start:
            conditions.append("timestamp >= ?")
            params.append(start)
        if end:
            conditions.append("timestamp <= ?")
            params.append(end)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""

        conn = self._get_conn()
        rows = conn.execute(
            f"""SELECT
                user_id,
                COUNT(*) as request_count,
                SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as error_count,
                ROUND(AVG(latency_ms), 2) as avg_latency_ms,
                SUM(total_tokens) as total_tokens,
                SUM(prompt_tokens) as total_prompt_tokens,
                SUM(completion_tokens) as total_completion_tokens,
                MAX(timestamp) as last_active
            FROM traces{where}
            GROUP BY user_id
            ORDER BY request_count DESC""",
            params,
        ).fetchall()

        return [
            {
                "user_id": row["user_id"],
                "request_count": row["request_count"],
                "error_count": row["error_count"] or 0,
                "avg_latency_ms": row["avg_latency_ms"] or 0,
                "total_tokens": row["total_tokens"] or 0,
                "total_prompt_tokens": row["total_prompt_tokens"] or 0,
                "total_completion_tokens": row["total_completion_tokens"] or 0,
                "last_active": row["last_active"],
            }
            for row in rows
        ]

    def get_session_stats(
        self,
        user_id: str | None = None,
        start: str | None = None,
        end: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """Get per-session aggregate statistics (excludes empty session_id)."""
        conditions = ["session_id != ''"]
        params: list = []

        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        if start:
            conditions.append("timestamp >= ?")
            params.append(start)
        if end:
            conditions.append("timestamp <= ?")
            params.append(end)

        where = " WHERE " + " AND ".join(conditions)

        conn = self._get_conn()
        rows = conn.execute(
            f"""SELECT
                session_id,
                user_id,
                COUNT(*) as request_count,
                MIN(timestamp) as start_time,
                MAX(timestamp) as end_time,
                SUM(total_tokens) as total_tokens,
                SUM(prompt_tokens) as total_prompt_tokens,
                SUM(completion_tokens) as total_completion_tokens,
                ROUND(AVG(latency_ms), 2) as avg_latency_ms,
                SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as error_count
            FROM traces{where}
            GROUP BY session_id
            ORDER BY start_time DESC
            LIMIT ? OFFSET ?""",
            params + [limit, offset],
        ).fetchall()

        return [
            {
                "session_id": row["session_id"],
                "user_id": row["user_id"],
                "request_count": row["request_count"],
                "start_time": row["start_time"],
                "end_time": row["end_time"],
                "total_tokens": row["total_tokens"] or 0,
                "total_prompt_tokens": row["total_prompt_tokens"] or 0,
                "total_completion_tokens": row["total_completion_tokens"] or 0,
                "avg_latency_ms": row["avg_latency_ms"] or 0,
                "error_count": row["error_count"] or 0,
            }
            for row in rows
        ]

    def get_timeline(
        self,
        interval: str = "hour",
        user_id: str | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> list[dict]:
        """Get time-bucketed aggregation of traces."""
        conditions = []
        params: list = []

        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        if start:
            conditions.append("timestamp >= ?")
            params.append(start)
        if end:
            conditions.append("timestamp <= ?")
            params.append(end)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""

        if interval == "day":
            bucket_expr = "strftime('%Y-%m-%d', timestamp)"
        else:
            bucket_expr = "strftime('%Y-%m-%dT%H:00:00', timestamp)"

        conn = self._get_conn()
        rows = conn.execute(
            f"""SELECT
                {bucket_expr} as bucket,
                COUNT(*) as request_count,
                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success_count,
                SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as error_count,
                ROUND(AVG(latency_ms), 2) as avg_latency_ms,
                SUM(prompt_tokens) as total_prompt_tokens,
                SUM(completion_tokens) as total_completion_tokens,
                SUM(total_tokens) as total_tokens
            FROM traces{where}
            GROUP BY bucket
            ORDER BY bucket ASC""",
            params,
        ).fetchall()

        return [
            {
                "bucket": row["bucket"],
                "request_count": row["request_count"],
                "success_count": row["success_count"] or 0,
                "error_count": row["error_count"] or 0,
                "avg_latency_ms": row["avg_latency_ms"] or 0,
                "total_prompt_tokens": row["total_prompt_tokens"] or 0,
                "total_completion_tokens": row["total_completion_tokens"] or 0,
                "total_tokens": row["total_tokens"] or 0,
            }
            for row in rows
        ]

    def get_conversation(
        self,
        session_id: str | None = None,
        user_id: str | None = None,
        trace_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Get conversation messages extracted from trace request/response bodies.

        Returns a list of trace records with full bodies, ordered chronologically.
        Filter by session_id, user_id, or a single trace_id.
        """
        conditions = []
        params: list = []

        if trace_id:
            conditions.append("trace_id = ?")
            params.append(trace_id)
        elif session_id:
            conditions.append("session_id = ?")
            params.append(session_id)
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""

        conn = self._get_conn()
        rows = conn.execute(
            f"""SELECT trace_id, timestamp, user_id, session_id, model, latency_ms, status, error,
                       prompt_tokens, completion_tokens, total_tokens, request_body, response_body
            FROM traces{where}
            ORDER BY timestamp ASC
            LIMIT ?""",
            params + [limit],
        ).fetchall()

        results = []
        for row in rows:
            record = dict(row)
            # Parse JSON bodies
            for field in ("request_body", "response_body"):
                if record.get(field):
                    try:
                        record[field] = json.loads(record[field])
                    except (json.JSONDecodeError, TypeError):
                        pass

            # Extract conversation turns from this trace
            messages = []
            req = record.get("request_body")
            if isinstance(req, dict):
                raw_msgs = req.get("messages", [])
                for msg in raw_msgs:
                    entry = {
                        "role": msg.get("role", "unknown"),
                        "content": self._extract_content(msg.get("content", "")),
                    }
                    # Preserve tool_calls on assistant messages
                    if msg.get("tool_calls"):
                        entry["tool_calls"] = [
                            {"name": tc.get("function", {}).get("name", ""), "arguments": tc.get("function", {}).get("arguments", "")}
                            for tc in msg["tool_calls"]
                        ]
                    # Preserve tool_call_id on tool messages
                    if msg.get("role") == "tool" and msg.get("tool_call_id"):
                        entry["tool_call_id"] = msg["tool_call_id"]
                    messages.append(entry)

            # Extract assistant reply from response
            resp = record.get("response_body")
            assistant_content = ""
            assistant_tool_calls = []
            if isinstance(resp, dict):
                choices = resp.get("choices", [])
                if choices:
                    msg = choices[0].get("message", {})
                    assistant_content = self._extract_content(msg.get("content", ""))
                    if msg.get("tool_calls"):
                        assistant_tool_calls = [
                            {"name": tc.get("function", {}).get("name", ""), "arguments": tc.get("function", {}).get("arguments", "")}
                            for tc in msg["tool_calls"]
                        ]

            record["token_usage"] = {
                "prompt_tokens": record.pop("prompt_tokens", 0),
                "completion_tokens": record.pop("completion_tokens", 0),
                "total_tokens": record.pop("total_tokens", 0),
            }
            record["messages"] = messages
            record["assistant_reply"] = assistant_content
            if assistant_tool_calls:
                record["assistant_tool_calls"] = assistant_tool_calls
            # Remove bulky raw bodies from response
            record.pop("request_body", None)
            record.pop("response_body", None)
            results.append(record)

        return results

    @staticmethod
    def _extract_content(content) -> str:
        """Extract text from message content (handles string and multimodal list formats)."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    parts.append(part.get("text", ""))
            return " ".join(parts)
        return str(content) if content else ""

    def update_session_id(self, trace_id: str, session_id: str):
        """Update the session_id for an existing trace."""
        conn = self._get_conn()
        conn.execute("UPDATE traces SET session_id = ? WHERE trace_id = ?", (session_id, trace_id))
        conn.commit()

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
