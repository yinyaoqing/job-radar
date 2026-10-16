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
from .classify import classify

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
    fail_count    INTEGER NOT NULL DEFAULT 0,
    last_error    TEXT,
    last_ok_at    TEXT,
    UNIQUE (ats, ats_org)
);
CREATE TABLE IF NOT EXISTS postings (
    id               INTEGER PRIMARY KEY,
    company_id       INTEGER NOT NULL REFERENCES companies(id),
    ats_job_id       TEXT NOT NULL,
    title            TEXT NOT NULL,
    url              TEXT NOT NULL,
    location         TEXT,
    work_mode        TEXT NOT NULL DEFAULT 'unknown',
    department       TEXT,
    category         TEXT NOT NULL DEFAULT 'other',
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
CREATE TABLE IF NOT EXISTS extractions (
    id             INTEGER PRIMARY KEY,
    snapshot_id    INTEGER NOT NULL REFERENCES posting_snapshots(id),
    model          TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    payload        TEXT,
    error          TEXT,
    input_tokens   INTEGER NOT NULL DEFAULT 0,
    output_tokens  INTEGER NOT NULL DEFAULT 0,
    cost_usd       REAL NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL,
    UNIQUE (snapshot_id, schema_version)
);
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

# Columns added after the first schema; older databases get them on open.
ADDED_COLUMNS = {
    "companies": {
        "fail_count": "INTEGER NOT NULL DEFAULT 0",
        "last_error": "TEXT",
        "last_ok_at": "TEXT",
    },
    "postings": {
        "work_mode": "TEXT NOT NULL DEFAULT 'unknown'",
        "department": "TEXT",
        "category": "TEXT NOT NULL DEFAULT 'other'",
    },
}

MAX_FAILURES = 3

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
        self._add_missing_columns()

    def _add_missing_columns(self) -> None:
        for table, columns in ADDED_COLUMNS.items():
            have = {r["name"] for r in self.db.execute(f"PRAGMA table_info({table})")}
            for name, decl in columns.items():
                if name not in have:
                    self.db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
        self.db.commit()

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

    def watched_companies(self, max_failures: int = MAX_FAILURES) -> list[Company]:
        """Watched boards, minus those that failed ``max_failures`` crawls in a row
        (moved ATS, renamed board). ``reset_failures`` puts them back."""
        rows = self.db.execute(
            """SELECT id, name, ats, ats_org FROM companies
               WHERE watch = 1 AND fail_count < ? ORDER BY ats, ats_org""",
            (max_failures,),
        )
        return [Company(**dict(r)) for r in rows]

    def record_board_result(self, company_id: int, now: datetime, error: str | None) -> None:
        if error is None:
            self.db.execute(
                "UPDATE companies SET fail_count = 0, last_error = NULL, last_ok_at = ? "
                "WHERE id = ?",
                (now.isoformat(), company_id),
            )
        else:
            self.db.execute(
                "UPDATE companies SET fail_count = fail_count + 1, last_error = ? WHERE id = ?",
                (error[:500], company_id),
            )
        self.db.commit()

    def reset_failures(self) -> int:
        cur = self.db.execute("UPDATE companies SET fail_count = 0 WHERE fail_count > 0")
        self.db.commit()
        return cur.rowcount

    def company_stats(self) -> list[sqlite3.Row]:
        return self.db.execute(
            """SELECT c.ats, c.ats_org, c.name, c.source, c.fail_count, c.last_error,
                      (SELECT count(*) FROM postings p
                       WHERE p.company_id = c.id AND p.status = 'open') AS open_postings,
                      (SELECT count(*) FROM postings p WHERE p.company_id = c.id
                       AND p.status = 'open' AND p.work_mode = 'remote') AS remote_postings
               FROM companies c WHERE c.watch = 1 ORDER BY c.ats, c.ats_org"""
        ).fetchall()

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
                p.work_mode,
                p.department,
                classify(p.title, p.department),
                p.published_at.isoformat() if p.published_at else None,
            )
            row = known.get(p.ats_job_id)
            if row is None:
                cur = self.db.execute(
                    """INSERT INTO postings (company_id, ats_job_id, title, url, location,
                           work_mode, department, category, published_at, status,
                           first_seen_at, last_verified_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)""",
                    (company_id, p.ats_job_id, *fields, ts, ts),
                )
                posting_id, last_hash = cur.lastrowid, None
                result.new += 1
            else:
                self.db.execute(
                    """UPDATE postings SET title = ?, url = ?, location = ?, work_mode = ?,
                           department = ?, category = ?, published_at = ?, status = 'open',
                           last_verified_at = ?, closed_at = NULL
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

    def open_postings(self, work_mode: str | None = None) -> list[sqlite3.Row]:
        sql = """SELECT p.*, c.name AS company, c.ats, c.ats_org, c.website, c.region
                 FROM postings p JOIN companies c ON c.id = p.company_id
                 WHERE p.status = 'open'"""
        params: tuple[str, ...] = ()
        if work_mode:
            sql += " AND p.work_mode = ?"
            params = (work_mode,)
        return self.db.execute(sql + " ORDER BY p.first_seen_at DESC, p.id DESC", params).fetchall()

    def posting_by_key(self, key: str) -> sqlite3.Row | None:
        """A posting by the feed's id, ``ats:org:job_id``."""
        ats, org, job_id = key.split(":", 2)
        return self.db.execute(
            """SELECT p.*, c.name AS company FROM postings p
               JOIN companies c ON c.id = p.company_id
               WHERE c.ats = ? AND c.ats_org = ? AND p.ats_job_id = ?""",
            (ats, org, job_id),
        ).fetchone()

    # --- extractions --------------------------------------------------------

    def pending_extractions(self, schema_version: int, limit: int) -> list[sqlite3.Row]:
        """Latest snapshot of each open remote posting with no extraction at this version,
        newest postings first. A failed attempt also counts, so a refusal is not retried
        every day; ``retry_failed_extractions`` clears them."""
        return self.db.execute(
            """SELECT s.id AS snapshot_id, p.title, p.location, p.department, s.jd_text
               FROM postings p
               JOIN posting_snapshots s ON s.id = (
                   SELECT max(id) FROM posting_snapshots WHERE posting_id = p.id)
               WHERE p.status = 'open' AND p.work_mode = 'remote'
                 AND NOT EXISTS (SELECT 1 FROM extractions e
                                 WHERE e.snapshot_id = s.id AND e.schema_version = ?)
               ORDER BY p.first_seen_at DESC, p.id DESC
               LIMIT ?""",
            (schema_version, limit),
        ).fetchall()

    def save_extraction(
        self,
        snapshot_id: int,
        *,
        model: str,
        schema_version: int,
        now: datetime,
        payload: dict[str, Any] | None = None,
        error: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
    ) -> None:
        self.db.execute(
            """INSERT OR REPLACE INTO extractions (snapshot_id, model, schema_version, payload,
                   error, input_tokens, output_tokens, cost_usd, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                snapshot_id,
                model,
                schema_version,
                None if payload is None else json.dumps(payload, ensure_ascii=False),
                error,
                input_tokens,
                output_tokens,
                cost_usd,
                now.isoformat(),
            ),
        )
        self.db.commit()

    def retry_failed_extractions(self) -> int:
        cur = self.db.execute("DELETE FROM extractions WHERE payload IS NULL")
        self.db.commit()
        return cur.rowcount

    def latest_extraction(self, posting_id: int, schema_version: int) -> dict[str, Any] | None:
        """The extraction of the newest snapshot that has one (an edited JD keeps showing the
        previous extraction until the new one lands)."""
        row = self.db.execute(
            """SELECT e.payload FROM extractions e
               JOIN posting_snapshots s ON s.id = e.snapshot_id
               WHERE s.posting_id = ? AND e.schema_version = ? AND e.payload IS NOT NULL
               ORDER BY s.id DESC LIMIT 1""",
            (posting_id, schema_version),
        ).fetchone()
        return None if row is None else json.loads(row["payload"])

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
