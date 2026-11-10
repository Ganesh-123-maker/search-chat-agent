"""Persistent memory: what you asked, and when.

Every turn is stored in a local SQLite file (memory.db, git-ignored)
with a timestamp, so the agent can answer questions about its own
history — "what did I ask yesterday?", "when did I ask about X?" —
and can resolve follow-ups ("and what about its price?") from the
previous turn instead of pretending the conversation never happened.

Nothing leaves this machine: no cloud, no API key, no account.
Delete memory.db to forget everything.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,          -- ISO-8601 UTC timestamp of the turn
    role TEXT NOT NULL,        -- 'user' | 'agent'
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_turns_ts ON turns(ts);
CREATE INDEX IF NOT EXISTS idx_turns_role ON turns(role);
"""

_STOPWORDS = set("what when where which who did do does is are was were the a an "
                 "of to in on for and or my i you me it that this ask asked about "
                 "tell me please".split())


def _keywords(text: str) -> set:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if len(w) > 2 and w not in _STOPWORDS}


class Memory:
    def __init__(self, path: str = "memory.db"):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self):
        self.conn.close()

    def remember(self, role: str, text: str, ts: str | None = None) -> None:
        ts = ts or datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.conn.execute("INSERT INTO turns (ts, role, text) VALUES (?, ?, ?)",
                          (ts, role, text))
        self.conn.commit()

    def recent(self, n: int = 5) -> list:
        rows = self.conn.execute(
            "SELECT ts, role, text FROM turns ORDER BY id DESC LIMIT ?",
            (n,)).fetchall()
        return [{"ts": ts, "role": role, "text": text}
                for ts, role, text in reversed(rows)]

    def search(self, query: str, n: int = 5) -> list:
        """Keyword recall: turns sharing a content word with the query,
        most recent first. Returns [] when nothing matches — the agent
        must then say so, not invent a past conversation."""
        keys = _keywords(query)
        if not keys:
            return []
        # A single shared generic word ("capital") is not evidence the
        # turn was about this topic — require at least 2 matching
        # keywords when the query has 2 or more.
        min_overlap = 2 if len(keys) >= 2 else 1
        rows = self.conn.execute(
            "SELECT ts, role, text FROM turns WHERE role='user' "
            "ORDER BY id DESC LIMIT 200").fetchall()
        scored = []
        for ts, role, text in rows:
            overlap = len(keys & _keywords(text))
            if overlap >= min_overlap:
                scored.append((overlap, ts, text))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [{"ts": ts, "text": text, "matches": overlap}
                for overlap, ts, text in scored[:n]]

    def user_questions(self, n: int = 20) -> list:
        rows = self.conn.execute(
            "SELECT ts, text FROM turns WHERE role='user' "
            "ORDER BY id DESC LIMIT ?", (n,)).fetchall()
        return [{"ts": ts, "text": text} for ts, text in rows]
