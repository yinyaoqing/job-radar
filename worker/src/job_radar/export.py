"""Public JSON feed for the static site: open, fully remote postings in every domain.

Only listing facts and a link back to the ATS go out. The JD body and the extraction
quotes stay out: they are the employer's text, and the apply page is the place to read
it. ``categories`` lists every domain with its count, in display order, so the site can
build its filter from the feed.

Eligibility depends on where the visitor lives, so the feed carries what the site needs
to judge it in the browser (web/lib/eligibility.ts mirrors eligibility.judge_policy):
``location_policy`` from the JD (only when its quotes were found in the text) and
``field_policy`` parsed from the ATS location field.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from .classify import CATEGORIES, is_general_application
from .eligibility import REGIONS, has_time_limit, policy_from_location_text
from .extract import SCHEMA_VERSION
from .store import Store

FEED_VERSION = 3
ATTRIBUTION = [
    {
        "name": "remoteintech/remote-jobs",
        "url": "https://github.com/remoteintech/remote-jobs",
        "license": "ISC",
        "used_for": "company discovery",
    },
    {
        "name": "Hacker News: Ask HN: Who is hiring?",
        "url": "https://news.ycombinator.com/submitted?id=whoishiring",
        "used_for": "company discovery",
    },
]
POLICY_KEYS = (
    "type",
    "countries",
    "regions",
    "timezone_window_utc",
    "required_overlap_hours",
    "overlap_reference_utc",
)


def hard_blocks(extraction: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Clearance and citizenship requirements; ``countries`` lists the citizenships that
    satisfy one (empty when the value names none, which the site treats as blocking)."""
    blocks = []
    for r in (extraction or {}).get("hard_requirements") or []:
        if r.get("type") not in ("clearance", "citizenship"):
            continue
        named = policy_from_location_text(r.get("value")) if r["type"] == "citizenship" else None
        countries = (named or {}).get("countries", [])
        blocks.append({"type": r["type"], "value": r.get("value"), "countries": countries})
    return blocks


def _from_extraction(extraction: dict[str, Any] | None) -> dict[str, Any]:
    if not extraction:
        return {"extracted": False}
    checks = extraction.get("checks") or {}
    policy = extraction.get("location_policy") or {}
    verified = bool(checks.get("location_verified")) and (
        policy.get("type") != "unknown" or has_time_limit(policy)
    )
    blocks = hard_blocks(extraction)
    salary = extraction.get("salary")
    if salary and salary.get("min") is None and salary.get("max") is None:
        salary = None
    return {
        "extracted": True,
        "location_policy": {k: policy.get(k) for k in POLICY_KEYS} if verified else None,
        "hard_blocks": blocks,
        "seniority": extraction.get("seniority"),
        "employment": extraction.get("employment"),
        "salary": salary,
        "skills": [s["skill"] for s in extraction.get("must_have") or []][:12],
        "no_ai_policy": bool((extraction.get("application_form") or {}).get("no_ai_policy")),
    }


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
            "field_policy": policy_from_location_text(r["location"]),
            "url": r["url"],
            "ats": r["ats"],
            "published_at": r["published_at"],
            "first_seen_at": r["first_seen_at"],
            "last_verified_at": r["last_verified_at"],
            **_from_extraction(store.latest_extraction(r["id"], SCHEMA_VERSION)),
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
        # Country codes per region, so the site judges region lists the same way.
        "regions": {name: sorted(members) for name, members in REGIONS.items()},
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
