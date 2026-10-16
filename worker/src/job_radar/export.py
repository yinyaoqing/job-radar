"""Public JSON feed for the static site.

Only listing facts and a link back to the ATS go out. The JD body stays out: it is the
employer's text, and the apply page is the place to read it.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .store import Store

FEED_VERSION = 1
ATTRIBUTION = [
    {
        "name": "remoteintech/remote-jobs",
        "url": "https://github.com/remoteintech/remote-jobs",
        "license": "ISC",
        "used_for": "company discovery",
    }
]


def build_feed(store: Store, now: datetime) -> dict[str, Any]:
    postings = [
        {
            "id": f"{r['ats']}:{r['ats_org']}:{r['ats_job_id']}",
            "company": r["company"],
            "company_website": r["website"],
            "company_region": r["region"],
            "title": r["title"],
            "location": r["location"],
            "is_remote": None if r["is_remote"] is None else bool(r["is_remote"]),
            "url": r["url"],
            "ats": r["ats"],
            "published_at": r["published_at"],
            "first_seen_at": r["first_seen_at"],
            "last_verified_at": r["last_verified_at"],
        }
        for r in store.open_postings()
    ]
    return {
        "version": FEED_VERSION,
        "generated_at": now.isoformat(),
        "count": len(postings),
        "attribution": ATTRIBUTION,
        "postings": postings,
    }


def write_feed(store: Store, out: Path, now: datetime) -> dict[str, Any]:
    feed = build_feed(store, now)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(feed, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(out)
    return feed
