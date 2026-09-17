"""SQLite persistence layer for LAN Chat.

Single-file database backing every piece of server state: sessions (identify
a browser), users (approved participants), join requests (approval queue),
banned names, and messages. SQLite is part of the Python standard library,
so the app keeps its zero-dependency, works-offline property.

Concurrency: Flask's dev server is threaded, so every call opens its own
short-lived connection (SQLite handles that fine at LAN scale) with WAL
mode for concurrent readers/writers.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
import threading
from datetime import datetime
from typing import List, Optional

HEARTBEAT_TIMEOUT_SECONDS = 90  # a user is "online" if seen within this window

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    sid        TEXT PRIMARY KEY,
    csrf       TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS users (
    sid         TEXT PRIMARY KEY REFERENCES sessions(sid) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    name_norm   TEXT NOT NULL UNIQUE,
    is_admin    INTEGER NOT NULL DEFAULT 0,
    last_seen   TEXT NOT NULL,
    joined_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS join_requests (
    sid          TEXT PRIMARY KEY REFERENCES sessions(sid) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    name_norm    TEXT NOT NULL UNIQUE,
    status       TEXT NOT NULL CHECK (status IN ('pending', 'rejected')),
    requested_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user       TEXT NOT NULL,
    text       TEXT NOT NULL,
    kind       TEXT NOT NULL DEFAULT 'chat' CHECK (kind IN ('chat', 'system', 'voice')),
    time       TEXT NOT NULL,
    audio_data BLOB,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _norm(name: str) -> str:
    """Case-insensitive key used for uniqueness (SQLite UNIQUE is sensitive)."""
    return name.lower().strip()


def _now() -> datetime:
    return datetime.now()


class DB:
    def __init__(self, path: str = ":memory:") -> None:
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.path = path
        # ":memory:" must be a single shared connection, or each open() gets a
        # brand-new empty database. Held for the lifetime of the object.
        self._memory_conn: Optional[sqlite3.Connection] = None
        # Serialises all DB operations so a single in-memory connection (and,
        # harmlessly, file connections) is never used by two threads at once.
        self._lock = threading.RLock()
        if path == ":memory:":
            self._memory_conn = sqlite3.connect(path, check_same_thread=False)
            self._memory_conn.row_factory = sqlite3.Row
            self._memory_conn.executescript(SCHEMA)
        else:
            self._init_schema()

    # ── plumbing ───────────────────────────────────────────────────────────
    def _connect(self) -> sqlite3.Connection:
        if self._memory_conn is not None:
            return self._memory_conn
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextlib.contextmanager
    def _op(self):
        """Serialised DB operation with the same commit/rollback semantics as
        `with conn:`. Every public method runs its work inside this context."""
        with self._lock:
            conn = self._connect()
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
            finally:
                if self._memory_conn is None:
                    conn.close()

    def _init_schema(self) -> None:
        with self._op() as conn:
            conn.executescript(SCHEMA)
        self._migrate_schema()

    def _migrate_schema(self) -> None:
        """Apply incremental schema changes to existing databases.

        SQLite can't alter a CHECK constraint or add a column with non-constant
        defaults, so when an older messages table is missing the `audio_data`
        column (and the narrower kind CHECK) we rebuild the table atomically
        inside the single `_op()` transaction. Existing rows are preserved.
        """
        with self._op() as conn:
            cols = {row[1] for row in conn.execute(
                "PRAGMA table_info(messages)").fetchall()}
            if "audio_data" in cols:
                return
            conn.execute(
                """
                CREATE TABLE messages_new (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user       TEXT NOT NULL,
                    text       TEXT NOT NULL,
                    kind       TEXT NOT NULL DEFAULT 'chat'
                               CHECK (kind IN ('chat', 'system', 'voice')),
                    time       TEXT NOT NULL,
                    audio_data BLOB,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            conn.execute(
                """
                INSERT INTO messages_new (id, user, text, kind, time, created_at)
                SELECT id, user, text, kind, time, created_at FROM messages
                """
            )
            conn.execute("DROP TABLE messages")
            conn.execute("ALTER TABLE messages_new RENAME TO messages")

    # ── sessions / CSRF ────────────────────────────────────────────────────
    def create_session(self, sid: str, csrf: str) -> None:
        with self._op() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO sessions (sid, csrf) VALUES (?, ?)", (sid, csrf)
            )

    def csrf_for(self, sid: str) -> Optional[str]:
        with self._op() as conn:
            row = conn.execute("SELECT csrf FROM sessions WHERE sid = ?", (sid,)).fetchone()
        return row["csrf"] if row else None

    # ── names (case-insensitive collision checking) ────────────────────────
    def name_is_taken(self, name: str, exclude_sid: Optional[str] = None) -> bool:
        """True if `name` is an active user or a pending request held by anyone else."""
        key = _norm(name)
        with self._op() as conn:
            row = conn.execute(
                "SELECT sid FROM users WHERE name_norm = ?", (key,)
            ).fetchone()
            if row and row["sid"] != exclude_sid:
                return True
            row = conn.execute(
                "SELECT sid FROM join_requests "
                "WHERE name_norm = ? AND status = 'pending'",
                (key,),
            ).fetchone()
            return bool(row and row["sid"] != exclude_sid)

    def exists_any_session(self, sid: str) -> bool:
        with self._op() as conn:
            row = conn.execute("SELECT 1 FROM sessions WHERE sid = ?", (sid,)).fetchone()
        return row is not None

    # ── join requests ──────────────────────────────────────────────────────
    def add_join_request(self, sid: str, name: str) -> None:
        """Create/replace a join request; a stale rejected row is overwritten."""
        key = _norm(name)
        with self._op() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO join_requests "
                "(sid, name, name_norm, status, requested_at) VALUES (?, ?, ?, 'pending', ?)",
                (sid, name, key, _now().isoformat(timespec="seconds")),
            )

    def get_join_request(self, sid: str) -> Optional[dict]:
        with self._op() as conn:
            row = conn.execute(
                "SELECT * FROM join_requests WHERE sid = ?", (sid,)
            ).fetchone()
        return dict(row) if row else None

    def approve_join_request(self, name: str) -> bool:
        """Approve the oldest pending request with this name and promote it to a user."""
        key = _norm(name)
        with self._op() as conn:
            row = conn.execute(
                "SELECT * FROM join_requests WHERE name_norm = ? AND status = 'pending' "
                "ORDER BY requested_at LIMIT 1",
                (key,),
            ).fetchone()
            if not row:
                return False
            conn.execute(
                "INSERT OR REPLACE INTO users (sid, name, name_norm, is_admin, last_seen, joined_at) "
                "VALUES (?, ?, ?, 0, ?, ?)",
                (row["sid"], row["name"], key, _now().isoformat(timespec="seconds"),
                 row["requested_at"]),
            )
            conn.execute("DELETE FROM join_requests WHERE sid = ?", (row["sid"],))
        return True

    def reject_join_request(self, name: str) -> bool:
        key = _norm(name)
        with self._op() as conn:
            cur = conn.execute(
                "UPDATE join_requests SET status = 'rejected' "
                "WHERE name_norm = ? AND status = 'pending'",
                (key,),
            )
        return cur.rowcount > 0

    def list_pending(self) -> List[dict]:
        with self._op() as conn:
            rows = conn.execute(
                "SELECT * FROM join_requests WHERE status = 'pending' ORDER BY requested_at"
            ).fetchall()
        return [dict(r) for r in rows]

    def cancel_join_request(self, sid: str) -> bool:
        """Withdraw this session's pending join request (if any)."""
        with self._op() as conn:
            cur = conn.execute(
                "DELETE FROM join_requests WHERE sid = ? AND status = 'pending'", (sid,)
            )
        return cur.rowcount > 0

    # ── users / presence ───────────────────────────────────────────────────
    def get_user(self, sid: str) -> Optional[dict]:
        with self._op() as conn:
            row = conn.execute("SELECT * FROM users WHERE sid = ?", (sid,)).fetchone()
        return dict(row) if row else None

    def get_user_by_name(self, name: str) -> Optional[dict]:
        with self._op() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE name_norm = ?", (_norm(name),)
            ).fetchone()
        return dict(row) if row else None

    def add_user(self, sid: str, name: str, is_admin: bool = False) -> None:
        with self._op() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO users "
                "(sid, name, name_norm, is_admin, last_seen, joined_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (sid, name, _norm(name), int(is_admin), _now().isoformat(timespec="seconds"),
                 _now().isoformat(timespec="seconds")),
            )

    def touch(self, sid: str) -> None:
        with self._op() as conn:
            conn.execute(
                "UPDATE users SET last_seen = ? WHERE sid = ?",
                (_now().isoformat(timespec="seconds"), sid),
            )

    def remove_user(self, sid: str) -> Optional[str]:
        """Remove a user from the room; keep the browser session so CSRF still works."""
        with self._op() as conn:
            row = conn.execute(
                "SELECT name FROM users WHERE sid = ?", (sid,)
            ).fetchone()
            if not row:
                return None
            name = row["name"]
            conn.execute("DELETE FROM join_requests WHERE sid = ?", (sid,))
            conn.execute("DELETE FROM users WHERE sid = ?", (sid,))
        return name

    def delete_session(self, sid: str) -> None:
        """Fully drop a browser session (used on explicit logout)."""
        with self._op() as conn:
            conn.execute("DELETE FROM users WHERE sid = ?", (sid,))
            conn.execute("DELETE FROM join_requests WHERE sid = ?", (sid,))
            conn.execute("DELETE FROM sessions WHERE sid = ?", (sid,))

    def expire_stale_sessions(self) -> List[str]:
        """Return names of online users idle past the timeout (they are removed)."""
        from time import time

        cutoff = datetime.fromtimestamp(time() - HEARTBEAT_TIMEOUT_SECONDS)
        removed: List[str] = []
        with self._op() as conn:
            rows = conn.execute(
                "SELECT sid, name FROM users WHERE last_seen < ?", (cutoff.isoformat(timespec="seconds"),)
            ).fetchall()
            for row in rows:
                # Keep the session row so a returning browser still has a valid CSRF.
                conn.execute("DELETE FROM users WHERE sid = ?", (row["sid"],))
                removed.append(row["name"])
        return removed

    def list_online_users(self) -> List[dict]:
        from time import time

        cutoff = datetime.fromtimestamp(time() - HEARTBEAT_TIMEOUT_SECONDS)
        with self._op() as conn:
            rows = conn.execute(
                "SELECT name, is_admin, last_seen FROM users "
                "WHERE last_seen >= ? ORDER BY name COLLATE NOCASE",
                (cutoff.isoformat(timespec="seconds"),),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── messages ───────────────────────────────────────────────────────────
    def add_message(self, user: str, text: str, kind: str = "chat",
                    audio_data: Optional[bytes] = None) -> int:
        with self._op() as conn:
            cur = conn.execute(
                "INSERT INTO messages (user, text, kind, time, audio_data, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (user, text, kind, _now().strftime("%H:%M"), audio_data,
                 _now().isoformat(timespec="seconds")),
            )
            return cur.lastrowid

    def add_system_message(self, text: str) -> int:
        return self.add_message("System", text, kind="system")

    def get_voice_data(self, message_id: int) -> Optional[bytes]:
        """Return the raw audio BLOB for a voice message, or None."""
        with self._op() as conn:
            row = conn.execute(
                "SELECT audio_data FROM messages WHERE id = ? AND kind = 'voice'",
                (message_id,),
            ).fetchone()
        return row["audio_data"] if row else None

    def get_last_message_id(self) -> int:
        with self._op() as conn:
            row = conn.execute("SELECT COALESCE(MAX(id), 0) AS m FROM messages").fetchone()
        return int(row["m"])

    _MSG_COLS = ("id, user, text, kind, time, created_at")  # no audio_data — keeps list queries light

    def get_messages(self, after: int = 0, before: Optional[int] = None,
                     limit: int = 100) -> List[dict]:
        with self._op() as conn:
            if before is not None:
                rows = conn.execute(
                    "SELECT " + self._MSG_COLS + " FROM messages WHERE id < ? ORDER BY id DESC LIMIT ?",
                    (before, limit),
                ).fetchall()
                rows.reverse()
            elif after <= 0:
                # Initial history: newest page (not the oldest rows from id > 0).
                rows = conn.execute(
                    "SELECT " + self._MSG_COLS + " FROM messages ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
                rows.reverse()
            else:
                rows = conn.execute(
                    "SELECT " + self._MSG_COLS + " FROM messages WHERE id > ? ORDER BY id ASC LIMIT ?",
                    (after, limit),
                ).fetchall()
        return [dict(r) for r in rows]

    def has_messages_before(self, before: int) -> bool:
        with self._op() as conn:
            row = conn.execute(
                "SELECT 1 FROM messages WHERE id < ? LIMIT 1", (before,)
            ).fetchone()
        return row is not None

    def clear_messages(self) -> None:
        with self._op() as conn:
            conn.execute("DELETE FROM messages")

    def message_count(self) -> int:
        with self._op() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM messages").fetchone()
        return int(row["c"])