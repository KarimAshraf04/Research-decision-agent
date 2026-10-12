"""Human-in-the-loop approval queue (SQLite, stdlib only)."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from rdi import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS approvals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  question TEXT NOT NULL,
  reasons TEXT NOT NULL,
  report_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',   -- pending | approved | rejected
  reviewer TEXT, note TEXT,
  created_at TEXT NOT NULL, decided_at TEXT
)"""


class ApprovalQueue:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or config.APPROVAL_DB  # resolved at call time so tests can redirect it
        with self._conn() as c:
            c.execute(_SCHEMA)

    def _conn(self):
        return sqlite3.connect(self.db_path)

    def create(self, run_id: str, question: str, reasons: list[str], report_json: str) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO approvals(run_id, question, reasons, report_json, created_at) VALUES (?,?,?,?,?)",
                (run_id, question, json.dumps(reasons), report_json, datetime.now(timezone.utc).isoformat()),
            )
            return int(cur.lastrowid)

    def list(self, status: str | None = "pending") -> list[dict]:
        q = "SELECT id, run_id, question, reasons, status, reviewer, note, created_at FROM approvals"
        args: tuple = ()
        if status:
            q += " WHERE status = ?"
            args = (status,)
        with self._conn() as c:
            rows = c.execute(q + " ORDER BY id DESC", args).fetchall()
        keys = ["id", "run_id", "question", "reasons", "status", "reviewer", "note", "created_at"]
        return [dict(zip(keys, r)) for r in rows]

    def get(self, approval_id: int) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT id, run_id, question, reasons, report_json, status, reviewer, note FROM approvals WHERE id=?",
                          (approval_id,)).fetchone()
        if not r:
            return None
        return dict(zip(["id", "run_id", "question", "reasons", "report_json", "status", "reviewer", "note"], r))

    def latest_for_run(self, run_id: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT id FROM approvals WHERE run_id=? ORDER BY id DESC LIMIT 1", (run_id,)).fetchone()
        return self.get(r[0]) if r else None

    def decide(self, approval_id: int, approved: bool, reviewer: str, note: str = "") -> dict:
        if not reviewer.strip():
            raise ValueError("Reviewer name is required.")
        rec = self.get(approval_id)
        if rec is None:
            raise ValueError(f"No approval #{approval_id}")
        if rec["status"] != "pending":
            raise ValueError(f"Approval #{approval_id} is already {rec['status']}.")
        with self._conn() as c:
            c.execute("UPDATE approvals SET status=?, reviewer=?, note=?, decided_at=? WHERE id=?",
                      ("approved" if approved else "rejected", reviewer.strip(), note,
                       datetime.now(timezone.utc).isoformat(), approval_id))
        return self.get(approval_id)  # type: ignore[return-value]
