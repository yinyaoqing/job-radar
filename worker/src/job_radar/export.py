"""Public JSON feed for the static site: open, fully remote postings in every domain.

Only listing facts and a link back to the ATS go out. The JD body stays out: it is the
employer's text, and the apply page is the place to read it. ``categories`` lists every
domain with its count, in display order, so the site can build its filter from the feed.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from .classify import CATEGORIES, is_general_application
from .store import Store

FEED_VERSION = 2
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
            "category": r["category"],
            "department": r["department"],
            "location": r["location"],
            "work_mode": r["work_mode"],
            "url": r["url"],
            "ats": r["ats"],
            "published_at": r["published_at"],
            "first_seen_at": r["first_seen_at"],
            "last_verified_at": r["last_verified_at"],
        }
        for r in store.open_postings(work_mode="remote")
        if not is_general_application(r["title"])
    ]
    counts = Counter(p["category"] for p in postings)
    return {
        "version": FEED_VERSION,
        "generated_at": now.isoformat(),
        "scope": "fully remote, all domains",
        "count": len(postings),
        "categories": [
            {"id": slug, "label": label, "count": counts.get(slug, 0)}
            for slug, label in CATEGORIES.items()
        ],
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
