"""Server-side session inference for the ROCK Model Gateway.

Groups related requests into sessions by fingerprinting the first user message
in each conversation. iflow CLI accumulates messages across requests, so the
first user message stays constant within a single conversation.
"""

import hashlib
import threading
import time
import uuid

from rock.logger import init_logger

logger = init_logger(__name__)

_manager: "SessionManager | None" = None


def init_session_manager(timeout_minutes: int = 30) -> "SessionManager":
    """Initialize the global session manager singleton."""
    global _manager
    _manager = SessionManager(timeout_minutes=timeout_minutes)
    logger.info(f"Session manager initialized (timeout={timeout_minutes}m)")
    return _manager


def get_session_manager() -> "SessionManager | None":
    """Get the global session manager instance, or None if not initialized."""
    return _manager


def _compute_fingerprint(messages: list[dict]) -> str:
    """Compute a fingerprint from the first user-role message content.

    Returns the first 16 hex chars of SHA-256(content[:500]), or empty string
    if no user message is found.
    """
    for msg in messages:
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, list):
                # Handle multimodal content (list of content parts)
                text_parts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
                content = " ".join(text_parts)
            content = str(content)[:500]
            return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
    return ""


class SessionManager:
    """Infers session IDs from request patterns.

    Algorithm:
    - Fingerprint = SHA-256 of first user message content (truncated to 500 chars)
    - Same user + same fingerprint + within timeout → same session
    - Different fingerprint or timeout exceeded → new session
    - Stale entries (>2x timeout) are lazily cleaned up on each call
    """

    def __init__(self, timeout_minutes: int = 30):
        self.timeout_seconds = timeout_minutes * 60
        self._lock = threading.Lock()
        # {user_id: {"session_id": str, "fingerprint": str, "last_seen": float}}
        self._active_sessions: dict[str, dict] = {}

    def infer_session_id(self, user_id: str, messages: list[dict], timestamp: float | None = None) -> str:
        """Infer a session ID for the given request.

        Args:
            user_id: The user making the request.
            messages: The messages array from the chat completion request.
            timestamp: Unix timestamp of the request. Defaults to time.time().

        Returns:
            A session ID (UUID string).
        """
        now = timestamp if timestamp is not None else time.time()
        fingerprint = _compute_fingerprint(messages)

        with self._lock:
            self._cleanup_stale(now)

            entry = self._active_sessions.get(user_id)

            if entry is None:
                # New user — new session
                session_id = str(uuid.uuid4())
            elif (now - entry["last_seen"]) > self.timeout_seconds:
                # Timeout exceeded — new session
                session_id = str(uuid.uuid4())
            elif fingerprint and entry.get("fingerprint") and fingerprint != entry["fingerprint"]:
                # Different conversation — new session
                session_id = str(uuid.uuid4())
            else:
                # Same conversation, within timeout — reuse session
                session_id = entry["session_id"]

            self._active_sessions[user_id] = {
                "session_id": session_id,
                "fingerprint": fingerprint or (entry["fingerprint"] if entry else ""),
                "last_seen": now,
            }

            return session_id

    def _cleanup_stale(self, now: float):
        """Remove entries older than 2x timeout. Must be called with lock held."""
        cutoff = now - (self.timeout_seconds * 2)
        stale_users = [uid for uid, entry in self._active_sessions.items() if entry["last_seen"] < cutoff]
        for uid in stale_users:
            del self._active_sessions[uid]
