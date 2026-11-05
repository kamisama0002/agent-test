"""Hermes 风格的历史会话检索。

Hermes 把历史消息写入 SQLite，并用 FTS5 做 session_search；中文场景下
默认 tokenizer 往往不能按短语命中，因此这里在 FTS 行里额外存一份
“CJK bigram”检索文本，查询时生成同样的 token。

实现范围：
- sessions / messages 两张表；
- messages_fts 是独立的 FTS5 索引表；
- 若当前 Python SQLite 没编译 FTS5，自动退化为 LIKE，保证项目可跑。
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tokens(text: str) -> list[str]:
    """英文按词，中文按相邻二元组；用于简单的跨语言检索。"""

    tokens: list[str] = []
    for chunk in re.findall(r"[A-Za-z0-9_]+|[\u3400-\u9fff]+", text):
        if re.fullmatch(r"[\u3400-\u9fff]+", chunk):
            if len(chunk) == 1:
                tokens.append(chunk)
            else:
                tokens.extend(chunk[index:index + 2] for index in range(len(chunk) - 1))
        else:
            tokens.append(chunk.lower())
    return list(dict.fromkeys(token for token in tokens if token))


def _search_text(text: str) -> str:
    tokens = _tokens(text)
    return " ".join(tokens)


class SessionStore:
    """SQLite-backed conversation archive."""

    def __init__(self, home: Path) -> None:
        self.home = Path(home).resolve()
        self.path = self.home / "sessions" / "sessions.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.connection = sqlite3.connect(str(self.path), check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self._fts_enabled = False
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, self.connection:
            self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(session_id) REFERENCES sessions(id)
                );
                CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
                """
            )
            try:
                self.connection.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                        message_id UNINDEXED,
                        content,
                        search_text,
                        tokenize='unicode61'
                    )
                    """
                )
                self._fts_enabled = True
            except sqlite3.OperationalError:
                self._fts_enabled = False

    def create_session(self, title: str = "", metadata: dict[str, Any] | None = None) -> str:
        session_id = f"session-{uuid.uuid4().hex[:12]}"
        with self._lock, self.connection:
            self.connection.execute(
                "INSERT INTO sessions(id, title, started_at, metadata) VALUES(?, ?, ?, ?)",
                (session_id, title, _now(), json.dumps(metadata or {}, ensure_ascii=False)),
            )
        return session_id

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        with self._lock, self.connection:
            cursor = self.connection.execute(
                "INSERT INTO messages(session_id, role, content, created_at, metadata) VALUES(?, ?, ?, ?, ?)",
                (session_id, role, content, _now(), json.dumps(metadata or {}, ensure_ascii=False)),
            )
            message_id = int(cursor.lastrowid)
            if self._fts_enabled:
                try:
                    self.connection.execute(
                        "INSERT INTO messages_fts(message_id, content, search_text) VALUES(?, ?, ?)",
                        (message_id, content, _search_text(content)),
                    )
                except sqlite3.OperationalError:
                    self._fts_enabled = False
            return message_id

    def end_session(self, session_id: str, metadata: dict[str, Any] | None = None) -> None:
        with self._lock, self.connection:
            if metadata:
                old = self.connection.execute(
                    "SELECT metadata FROM sessions WHERE id = ?", (session_id,)
                ).fetchone()
                merged: dict[str, Any] = {}
                if old:
                    try:
                        merged.update(json.loads(old["metadata"] or "{}"))
                    except json.JSONDecodeError:
                        pass
                merged.update(metadata)
                payload = json.dumps(merged, ensure_ascii=False)
            else:
                payload = None
            if payload is None:
                self.connection.execute("UPDATE sessions SET ended_at = ? WHERE id = ?", (_now(), session_id))
            else:
                self.connection.execute(
                    "UPDATE sessions SET ended_at = ?, metadata = ? WHERE id = ?",
                    (_now(), payload, session_id),
                )

    def _snippet(self, content: str, query: str, width: int = 120) -> str:
        needle = query.strip()
        folded = content.casefold()
        index = folded.find(needle.casefold()) if needle else -1
        if index < 0:
            for token in _tokens(query):
                index = folded.find(token.casefold())
                if index >= 0:
                    break
        if index < 0:
            return content[:width] + ("..." if len(content) > width else "")
        start = max(0, index - width // 3)
        end = min(len(content), index + width)
        prefix = "..." if start else ""
        suffix = "..." if end < len(content) else ""
        return prefix + content[start:end].replace("\n", " ") + suffix

    def search(
        self,
        query: str,
        limit: int = 8,
        *,
        session_id: str | None = None,
        role: str | None = None,
    ) -> list[dict[str, Any]]:
        query = query.strip()
        if not query:
            return []
        limit = max(1, min(int(limit), 50))
        params: list[Any] = []
        if self._fts_enabled and _tokens(query):
            tokens = _tokens(query)
            # OR 比 AND 更适合自然语言问题；CJK bigram 也在这里参与匹配。
            fts_query = " OR ".join(f'"{token.replace(chr(34), "")}"' for token in tokens)
            where = ["messages_fts MATCH ?"]
            params.append(fts_query)
            if session_id:
                where.append("m.session_id = ?")
                params.append(session_id)
            if role:
                where.append("m.role = ?")
                params.append(role)
            params.append(limit)
            sql = f"""
                SELECT m.id, m.session_id, m.role, m.content, m.created_at, s.title,
                       bm25(messages_fts) AS score
                FROM messages_fts
                JOIN messages m ON m.id = messages_fts.message_id
                JOIN sessions s ON s.id = m.session_id
                WHERE {' AND '.join(where)}
                ORDER BY score ASC, m.id DESC
                LIMIT ?
            """
            try:
                with self._lock:
                    rows = self.connection.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                rows = []
                self._fts_enabled = False
            if rows:
                return [self._row_to_result(row, query) for row in rows]
        # 退化路径：对 content 做 LIKE，适合 FTS5 未编译或查询没有 token 的情况。
        clauses = ["content LIKE ?"]
        like_params: list[Any] = [f"%{query}%"]
        if session_id:
            clauses.append("session_id = ?")
            like_params.append(session_id)
        if role:
            clauses.append("role = ?")
            like_params.append(role)
        like_params.append(limit)
        sql = f"""
            SELECT m.id, m.session_id, m.role, m.content, m.created_at, s.title, 0 AS score
            FROM messages m JOIN sessions s ON s.id = m.session_id
            WHERE {' AND '.join('m.' + clause if not clause.startswith('m.') else clause for clause in clauses)}
            ORDER BY m.id DESC LIMIT ?
        """
        with self._lock:
            rows = self.connection.execute(sql, like_params).fetchall()
        return [self._row_to_result(row, query) for row in rows]

    def _row_to_result(self, row: sqlite3.Row, query: str) -> dict[str, Any]:
        content = str(row["content"])
        return {
            "message_id": row["id"],
            "session_id": row["session_id"],
            "session_title": row["title"],
            "role": row["role"],
            "created_at": row["created_at"],
            "snippet": self._snippet(content, query),
            "score": row["score"],
        }

    def list_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.connection.execute(
                """
                SELECT s.id, s.title, s.started_at, s.ended_at, COUNT(m.id) AS message_count
                FROM sessions s LEFT JOIN messages m ON m.session_id = s.id
                GROUP BY s.id ORDER BY s.started_at DESC LIMIT ?
                """,
                (max(1, min(limit, 100)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_session(self, session_id: str, limit: int = 100) -> dict[str, Any] | None:
        with self._lock:
            session = self.connection.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if session is None:
                return None
            messages = self.connection.execute(
                "SELECT role, content, created_at FROM messages WHERE session_id = ? ORDER BY id ASC LIMIT ?",
                (session_id, max(1, limit)),
            ).fetchall()
        return {"session": dict(session), "messages": [dict(row) for row in messages]}

    def close(self) -> None:
        with self._lock:
            self.connection.close()
