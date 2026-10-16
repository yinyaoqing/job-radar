"""SQLite store for the public data tier: companies, postings, snapshots, runs.

Only public facts live here (what the ATS boards say). Anything personal (evidence,
CVs, applications) stays with the user, never in this database. Tables follow
docs/spec.md 資料模型; timestamps are ISO-8601 UTC strings.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .adapters import Posting

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    ats           TEXT NOT NULL,
    ats_org       TEXT NOT NULL,
    watch         INTEGER NOT NULL DEFAULT 1,
    source        TEXT,
    website       TEXT,
    region        TEXT,
    remote_policy TEXT,
    technologies  TEXT NOT NULL DEFAULT '[]',
    added_at      TEXT NOT NULL,
    UNIQUE (ats, ats_org)
);
CREATE TABLE IF NOT EXISTS postings (
    id               INTEGER PRIMARY KEY,
    company_id       INTEGER NOT NULL REFERENCES companies(id),
    ats_job_id       TEXT NOT NULL,
    title            TEXT NOT NULL,
    url              TEXT NOT NULL,
    location         TEXT,
    is_remote        INTEGER,
    published_at     TEXT,
    status           TEXT NOT NULL CHECK (status IN ('open', 'closed')),
    first_seen_at    TEXT NOT NULL,
    last_verified_at TEXT NOT NULL,
    closed_at        TEXT,
    UNIQUE (company_id, ats_job_id)
);
CREATE TABLE IF NOT EXISTS posting_snapshots (
    id           INTEGER PRIMARY KEY,
    posting_id   INTEGER NOT NULL REFERENCES postings(id),
    fetched_at   TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    jd_text      TEXT,
    raw_json     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS snapshots_by_posting ON posting_snapshots (posting_id, id);
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    step        TEXT NOT NULL,
    stats       TEXT NOT NULL DEFAULT '{}',
    error       TEXT,
    tokens      INTEGER NOT NULL DEFAULT 0,
    cost_usd    REAL NOT NULL DEFAULT 0
);
"""

COMPANY_EXTRA_COLUMNS = {"watch", "source", "website", "region", "remote_policy", "technologies"}


@dataclass(slots=True)
class Company:
    id: int
    name: str
    ats: str
    ats_org: str


@dataclass(slots=True)
class SyncResult:
    seen: int = 0
    new: int = 0
    changed: int = 0
    closed: int = 0


def content_hash(p: Posting) -> str:
    text = "\x1f".join([p.title, p.location or "", p.description or ""])
    return hashlib.sha256(text.encode()).hexdigest()


class Store:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    # --- companies ---------------------------------------------------------

    def add_company(
        self, name: str, ats: str, ats_org: str, *, now: datetime, **extra: Any
    ) -> tuple[int, bool]:
        """Insert a company unless (ats, ats_org) exists. Returns (id, inserted)."""
        row = self.db.execute(
            "SELECT id FROM companies WHERE ats = ? AND ats_org = ?", (ats, ats_org)
        ).fetchone()
        if row:
            return row["id"], False
        if unknown := set(extra) - COMPANY_EXTRA_COLUMNS:
            raise ValueError(f"unknown company columns: {sorted(unknown)}")
        technologies = json.dumps(extra.pop("technologies", []) or [])
        cols = ["name", "ats", "ats_org", "technologies", "added_at", *extra]
        vals = [name, ats, ats_org, technologies, now.isoformat(), *extra.values()]
        cur = self.db.execute(
            f"INSERT INTO companies ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
            vals,
        )
        self.db.commit()
        return cur.lastrowid, True

    def watched_companies(self) -> list[Company]:
        rows = self.db.execute(
            "SELECT id, name, ats, ats_org FROM companies WHERE watch = 1 ORDER BY ats, ats_org"
        )
        return [Company(**dict(r)) for r in rows]

    # --- postings ----------------------------------------------------------

    def sync_board(self, company_id: int, postings: Iterable[Posting], now: datetime) -> SyncResult:
        """Record one successful board fetch. The board is the truth: anything open that is
        no longer listed is closed. Call only after a fetch succeeded."""
        ts = now.isoformat()
        result = SyncResult()
        known = {
            r["ats_job_id"]: r
            for r in self.db.execute(
                """SELECT p.id, p.ats_job_id, p.status,
                          (SELECT content_hash FROM posting_snapshots s
                           WHERE s.posting_id = p.id ORDER BY s.id DESC LIMIT 1) AS last_hash
                   FROM postings p WHERE p.company_id = ?""",
                (company_id,),
            )
        }
        seen: set[str] = set()
        for p in postings:
            if p.ats_job_id in seen:
                continue
            seen.add(p.ats_job_id)
            result.seen += 1
            fields = (
                p.title,
                p.url,
                p.location,
                None if p.is_remote is None else int(p.is_remote),
                p.published_at.isoformat() if p.published_at else None,
            )
            row = known.get(p.ats_job_id)
            if row is None:
                cur = self.db.execute(
                    """INSERT INTO postings (company_id, ats_job_id, title, url, location,
                           is_remote, published_at, status, first_seen_at, last_verified_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)""",
                    (company_id, p.ats_job_id, *fields, ts, ts),
                )
                posting_id, last_hash = cur.lastrowid, None
                result.new += 1
            else:
                self.db.execute(
                    """UPDATE postings SET title = ?, url = ?, location = ?, is_remote = ?,
                           published_at = ?, status = 'open', last_verified_at = ?,
                           closed_at = NULL
                       WHERE id = ?""",
                    (*fields, ts, row["id"]),
                )
                posting_id, last_hash = row["id"], row["last_hash"]
            digest = content_hash(p)
            if digest != last_hash:
                self.db.execute(
                    """INSERT INTO posting_snapshots
                           (posting_id, fetched_at, content_hash, jd_text, raw_json)
                       VALUES (?, ?, ?, ?, ?)""",
                    (posting_id, ts, digest, p.description, json.dumps(p.raw, default=str)),
                )
                if last_hash is not None:
                    result.changed += 1
        for job_id, row in known.items():
            if job_id not in seen and row["status"] == "open":
                self.db.execute(
                    "UPDATE postings SET status = 'closed', closed_at = ? WHERE id = ?",
                    (ts, row["id"]),
                )
                result.closed += 1
        self.db.commit()
        return result

    def open_postings(self) -> list[sqlite3.Row]:
        return self.db.execute(
            """SELECT p.*, c.name AS company, c.ats, c.ats_org, c.website, c.region
               FROM postings p JOIN companies c ON c.id = p.company_id
               WHERE p.status = 'open'
               ORDER BY p.first_seen_at DESC, p.id DESC"""
        ).fetchall()

    # --- runs --------------------------------------------------------------

    def start_run(self, step: str, now: datetime) -> int:
        cur = self.db.execute(
            "INSERT INTO runs (started_at, step) VALUES (?, ?)", (now.isoformat(), step)
        )
        self.db.commit()
        return cur.lastrowid

    def finish_run(
        self, run_id: int, now: datetime, stats: dict[str, Any], error: str | None = None
    ) -> None:
        self.db.execute(
            "UPDATE runs SET finished_at = ?, stats = ?, error = ? WHERE id = ?",
            (now.isoformat(), json.dumps(stats), error, run_id),
        )
        self.db.commit()
