"""Tests for the server-side session inference module."""

from rock.sdk.model.server.session import SessionManager, _compute_fingerprint


def _msgs(content: str, extra_msgs: list | None = None):
    """Build a messages array with one user message."""
    msgs = [{"role": "user", "content": content}]
    if extra_msgs:
        msgs.extend(extra_msgs)
    return msgs


class TestComputeFingerprint:
    def test_basic_fingerprint(self):
        fp = _compute_fingerprint([{"role": "user", "content": "hello world"}])
        assert len(fp) == 16
        assert all(c in "0123456789abcdef" for c in fp)

    def test_same_content_same_fingerprint(self):
        fp1 = _compute_fingerprint([{"role": "user", "content": "fix the bug"}])
        fp2 = _compute_fingerprint([{"role": "user", "content": "fix the bug"}])
        assert fp1 == fp2

    def test_different_content_different_fingerprint(self):
        fp1 = _compute_fingerprint([{"role": "user", "content": "fix the bug"}])
        fp2 = _compute_fingerprint([{"role": "user", "content": "add a feature"}])
        assert fp1 != fp2

    def test_no_user_message_returns_empty(self):
        assert _compute_fingerprint([{"role": "system", "content": "you are helpful"}]) == ""
        assert _compute_fingerprint([]) == ""

    def test_uses_first_user_message_only(self):
        msgs = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "answer"},
            {"role": "user", "content": "follow up"},
        ]
        fp = _compute_fingerprint(msgs)
        fp_first = _compute_fingerprint([{"role": "user", "content": "first question"}])
        assert fp == fp_first

    def test_truncates_to_500_chars(self):
        long_content = "a" * 1000
        fp = _compute_fingerprint([{"role": "user", "content": long_content}])
        # Same as truncated version
        fp_truncated = _compute_fingerprint([{"role": "user", "content": "a" * 500}])
        assert fp == fp_truncated


class TestSessionManager:
    def test_new_user_gets_new_session(self):
        mgr = SessionManager(timeout_minutes=30)
        sid = mgr.infer_session_id("alice", _msgs("hello"), timestamp=1000.0)
        assert sid  # non-empty UUID string
        assert len(sid) == 36  # UUID format

    def test_same_conversation_same_session(self):
        """Same first user message within timeout → same session."""
        mgr = SessionManager(timeout_minutes=30)
        msgs = _msgs("fix the auth bug")

        sid1 = mgr.infer_session_id("alice", msgs, timestamp=1000.0)
        # Second request in same conversation (iflow sends accumulated messages)
        sid2 = mgr.infer_session_id(
            "alice",
            msgs + [{"role": "assistant", "content": "sure"}, {"role": "user", "content": "also fix tests"}],
            timestamp=1010.0,
        )
        assert sid1 == sid2

    def test_different_conversation_different_session(self):
        """Different first user message → new session."""
        mgr = SessionManager(timeout_minutes=30)

        sid1 = mgr.infer_session_id("alice", _msgs("fix the auth bug"), timestamp=1000.0)
        sid2 = mgr.infer_session_id("alice", _msgs("add logging to the API"), timestamp=1010.0)
        assert sid1 != sid2

    def test_timeout_creates_new_session(self):
        """Gap > timeout → new session even with same fingerprint."""
        mgr = SessionManager(timeout_minutes=30)
        msgs = _msgs("fix the auth bug")

        sid1 = mgr.infer_session_id("alice", msgs, timestamp=1000.0)
        # 31 minutes later
        sid2 = mgr.infer_session_id("alice", msgs, timestamp=1000.0 + 31 * 60)
        assert sid1 != sid2

    def test_within_timeout_same_session(self):
        """Gap < timeout with same fingerprint → same session."""
        mgr = SessionManager(timeout_minutes=30)
        msgs = _msgs("fix the auth bug")

        sid1 = mgr.infer_session_id("alice", msgs, timestamp=1000.0)
        # 29 minutes later
        sid2 = mgr.infer_session_id("alice", msgs, timestamp=1000.0 + 29 * 60)
        assert sid1 == sid2

    def test_no_messages_falls_back_to_time_gap(self):
        """Empty messages array — sessions split only by timeout."""
        mgr = SessionManager(timeout_minutes=30)

        sid1 = mgr.infer_session_id("alice", [], timestamp=1000.0)
        # Within timeout, empty fingerprint matches empty fingerprint
        sid2 = mgr.infer_session_id("alice", [], timestamp=1010.0)
        assert sid1 == sid2

        # After timeout
        sid3 = mgr.infer_session_id("alice", [], timestamp=1000.0 + 31 * 60)
        assert sid3 != sid1

    def test_different_users_independent(self):
        """Different users get independent sessions."""
        mgr = SessionManager(timeout_minutes=30)
        msgs = _msgs("same prompt")

        sid_alice = mgr.infer_session_id("alice", msgs, timestamp=1000.0)
        sid_bob = mgr.infer_session_id("bob", msgs, timestamp=1000.0)
        assert sid_alice != sid_bob

    def test_stale_session_cleanup(self):
        """Stale entries (>2x timeout) are cleaned up."""
        mgr = SessionManager(timeout_minutes=30)
        timeout_s = 30 * 60

        mgr.infer_session_id("alice", _msgs("hello"), timestamp=1000.0)
        assert "alice" in mgr._active_sessions

        # Another user triggers cleanup, alice is stale (>2x timeout)
        mgr.infer_session_id("bob", _msgs("hi"), timestamp=1000.0 + 2 * timeout_s + 1)
        assert "alice" not in mgr._active_sessions
        assert "bob" in mgr._active_sessions

    def test_explicit_header_takes_priority(self):
        """This test documents the expected behavior: if a session_id comes
        from headers, the inference is skipped (tested at integration level in utils.py)."""
        # SessionManager itself doesn't know about headers — that logic is in utils.py.
        # Here we just verify that infer_session_id always returns a valid UUID.
        mgr = SessionManager(timeout_minutes=30)
        sid = mgr.infer_session_id("alice", _msgs("hello"), timestamp=1000.0)
        assert len(sid) == 36
