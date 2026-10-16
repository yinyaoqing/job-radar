import io
import json
import tarfile
from datetime import UTC, datetime, timedelta

import pytest

from job_radar.adapters import Adapter, AdapterError, Posting
from job_radar.discovery import detect_ats, parse_company, probe, read_tarball
from job_radar.export import build_feed, write_feed
from job_radar.pipeline import crawl
from job_radar.store import Store

T0 = datetime(2026, 10, 19, 23, 0, tzinfo=UTC)


def posting(
    job_id: str,
    title: str = "Frontend Engineer",
    description: str = "jd",
    work_mode: str = "remote",
    department: str | None = None,
) -> Posting:
    return Posting(
        ats="lever",
        org="acme",
        ats_job_id=job_id,
        title=title,
        url=f"https://jobs.lever.co/acme/{job_id}",
        location="Remote",
        work_mode=work_mode,
        department=department,
        description=description,
        raw={"id": job_id},
    )


class FakeAdapter(Adapter):
    name = "fake"

    def __init__(self, boards: dict[str, list[Posting] | Exception]) -> None:
        self.boards = boards

    def list(self, org: str) -> list[Posting]:
        board = self.boards[org]
        if isinstance(board, Exception):
            raise board
        return board

    def get(self, org: str, job_id: str) -> Posting | None:
        return next((p for p in self.list(org) if p.ats_job_id == job_id), None)


def snapshot_count(store: Store) -> int:
    return store.db.execute("SELECT count(*) FROM posting_snapshots").fetchone()[0]


# --- store -----------------------------------------------------------------


def test_sync_board_opens_changes_and_closes():
    store = Store()
    cid, _ = store.add_company("Acme", "lever", "acme", now=T0)

    first = store.sync_board(cid, [posting("a"), posting("b")], T0)
    assert (first.new, first.closed) == (2, 0)

    later = T0 + timedelta(days=1)
    second = store.sync_board(cid, [posting("a", description="jd v2")], later)
    assert (second.new, second.changed, second.closed) == (0, 1, 1)
    assert snapshot_count(store) == 3  # a, b, then a's new content

    open_ids = [r["ats_job_id"] for r in store.open_postings()]
    assert open_ids == ["a"]
    assert store.open_postings()[0]["last_verified_at"] == later.isoformat()


def test_sync_board_reopens_and_skips_unchanged_snapshot():
    store = Store()
    cid, _ = store.add_company("Acme", "lever", "acme", now=T0)
    store.sync_board(cid, [posting("a")], T0)
    store.sync_board(cid, [], T0 + timedelta(days=1))
    store.sync_board(cid, [posting("a")], T0 + timedelta(days=2))
    row = store.open_postings()[0]
    assert row["closed_at"] is None
    assert snapshot_count(store) == 1


def test_add_company_is_idempotent_and_rejects_unknown_columns():
    store = Store()
    first = store.add_company("Acme", "lever", "acme", now=T0, technologies=["react"])
    assert store.add_company("Acme again", "lever", "acme", now=T0) == (first[0], False)
    with pytest.raises(ValueError):
        store.add_company("X", "lever", "x", now=T0, **{"name); DROP TABLE companies; --": 1})


# --- pipeline --------------------------------------------------------------


def test_crawl_isolates_failing_board_and_keeps_its_postings_open():
    store = Store()
    ok_id, _ = store.add_company("Acme", "lever", "acme", now=T0)
    bad_id, _ = store.add_company("Broken", "lever", "broken", now=T0)
    store.sync_board(bad_id, [posting("old")], T0)

    boards = {"acme": [posting("a")], "broken": AdapterError("HTTP 503")}
    stats = crawl(store, adapter_for=lambda ats: FakeAdapter(boards), now=lambda: T0)

    assert (stats.boards_ok, stats.boards_failed, stats.new) == (1, 1, 1)
    assert "lever/broken" in stats.errors[0]
    assert {r["ats_job_id"] for r in store.open_postings()} == {"a", "old"}
    run = store.db.execute("SELECT step, finished_at, stats FROM runs").fetchone()
    assert run["step"] == "crawl" and run["finished_at"]
    assert json.loads(run["stats"])["boards_failed"] == 1


# --- discovery -------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://jobs.ashbyhq.com/Acme", ("ashby", "Acme")),
        ("https://boards.greenhouse.io/acme/jobs/123", ("greenhouse", "acme")),
        ("https://job-boards.greenhouse.io/acme", ("greenhouse", "acme")),
        ("https://boards.greenhouse.io/embed/job_board?for=acme", ("greenhouse", "acme")),
        ("https://jobs.lever.co/acme?team=eng", ("lever", "acme")),
        ("https://acme.recruitee.com/", ("recruitee", "acme")),
        ("https://acme.com/careers", None),
        (None, None),
    ],
)
def test_detect_ats(url, expected):
    assert detect_ats(url) == expected


COMPANY_MD = """---
title: "Acme"
slug: acme
website: https://acme.example/
careers_url: https://jobs.lever.co/acme
region: worldwide
remote_policy: fully-remote
technologies:
  - typescript
  - react
---

## Company blurb
"""


def test_parse_company_and_read_tarball():
    company = parse_company("acme", COMPANY_MD)
    assert company.name == "Acme"
    assert company.technologies == ["typescript", "react"]
    assert parse_company("x", "no frontmatter") is None

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, text in [
            ("remote-jobs-main/src/companies/acme.md", COMPANY_MD),
            ("remote-jobs-main/README.md", "# readme"),
        ]:
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    assert [c.slug for c in read_tarball(buf.getvalue())] == ["acme"]


def test_probe_returns_first_board_that_exists():
    class Missing(FakeAdapter):
        def list(self, org):
            raise AdapterError("404")

    adapters = {
        "greenhouse": Missing({}),
        "lever": FakeAdapter({"acme": []}),
        "ashby": Missing({}),
        "recruitee": Missing({}),
        "workable": Missing({}),
    }
    assert probe("acme", adapters) == ("lever", "acme")
    assert probe("nobody", {k: Missing({}) for k in adapters}) is None


# --- export ----------------------------------------------------------------


def test_feed_has_open_postings_without_jd_text(tmp_path):
    store = Store()
    cid, _ = store.add_company("Acme", "lever", "acme", now=T0, website="https://acme.example")
    store.sync_board(cid, [posting("a", description="secret-ish full JD")], T0)

    feed = build_feed(store, T0)
    assert feed["count"] == 1
    item = feed["postings"][0]
    assert item["id"] == "lever:acme:a"
    assert item["work_mode"] == "remote"
    assert item["category"] == "engineering"
    assert "secret-ish" not in json.dumps(feed)

    out = tmp_path / "public" / "feed.json"
    write_feed(store, out, T0)
    assert json.loads(out.read_text(encoding="utf-8"))["count"] == 1


def test_feed_is_remote_only_and_counts_every_category():
    store = Store()
    cid, _ = store.add_company("Acme", "lever", "acme", now=T0)
    store.sync_board(
        cid,
        [
            posting("eng", "Backend Engineer"),
            posting("mkt", "Growth Marketing Manager"),
            posting("hyb", "Recruiter", work_mode="hybrid"),
            posting("ons", "Accountant", work_mode="onsite"),
        ],
        T0,
    )
    feed = build_feed(store, T0)
    assert {p["id"].split(":")[-1] for p in feed["postings"]} == {"eng", "mkt"}
    counts = {c["id"]: c["count"] for c in feed["categories"]}
    assert counts["engineering"] == 1 and counts["marketing"] == 1
    assert counts["people"] == 0  # hybrid recruiter is out of scope
    assert [c["id"] for c in feed["categories"]][-1] == "other"


def test_old_database_gets_new_columns(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.execute(
        """CREATE TABLE postings (id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL,
           ats_job_id TEXT NOT NULL, title TEXT NOT NULL, url TEXT NOT NULL, location TEXT,
           is_remote INTEGER, published_at TEXT, status TEXT NOT NULL,
           first_seen_at TEXT NOT NULL, last_verified_at TEXT NOT NULL, closed_at TEXT,
           UNIQUE (company_id, ats_job_id))"""
    )
    db.commit()
    db.close()

    store = Store(path)
    cid, _ = store.add_company("Acme", "lever", "acme", now=T0)
    store.sync_board(cid, [posting("a")], T0)
    assert store.open_postings(work_mode="remote")[0]["category"] == "engineering"
