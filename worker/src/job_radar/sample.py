"""The fictional feed behind the site's demo and tests (web/public/sample-feed.json).

Built with the real exporter from made-up companies, so its shape always matches
``build_feed``; every link points at example.com. Regenerate with
``job-radar export --sample``; tests fail when it is out of date.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .adapters import Posting
from .export import build_feed
from .extract import SCHEMA_VERSION
from .store import Store

SAMPLE_FEED = Path(__file__).resolve().parents[3] / "web" / "public" / "sample-feed.json"
GENERATED_AT = datetime(2026, 10, 16, 0, 0, tzinfo=UTC)
UNEXTRACTED = "unextracted"

# (company, title, department, ATS location field, location policy, extras)
_POSTINGS: list[tuple[str, str, str, str, Any, dict[str, Any]]] = [
    (
        "Northwind Labs",
        "Senior Frontend Engineer",
        "Engineering",
        "Remote - Worldwide",
        {"type": "worldwide"},
        {"skills": ["TypeScript", "React", "Next.js"], "salary": (120000, 160000, "USD", "year")},
    ),
    (
        "Northwind Labs",
        "Product Designer",
        "Design",
        "Remote",
        {"type": "region_list", "regions": ["APAC"]},
        {"skills": ["Figma", "Design systems"]},
    ),
    (
        "Blue Harbor",
        "Backend Engineer (Go)",
        "Platform",
        "Remote (USA)",
        {"type": "country_list", "countries": ["US"]},
        {"skills": ["Go", "PostgreSQL"]},
    ),
    (
        "Blue Harbor",
        "Customer Success Manager",
        "Customer Success",
        "Remote - EMEA",
        {"type": "region_list", "regions": ["EMEA"]},
        {},
    ),
    (
        "Kestrel Data",
        "Data Analyst",
        "Analytics",
        "Remote",
        {"type": "timezone_window", "timezone_window_utc": {"from_utc": 5, "to_utc": 10}},
        {"skills": ["SQL", "dbt"]},
    ),
    (
        "Kestrel Data",
        "Machine Learning Engineer",
        "Research",
        "Remote",
        {"type": "worldwide", "required_overlap_hours": 4, "overlap_reference_utc": -8},
        {"skills": ["Python", "PyTorch"]},
    ),
    (
        "Lumen Health",
        "Telehealth Physician",
        "Clinical",
        "Remote - US",
        {"type": "country_list", "countries": ["US"]},
        {"blocks": [{"type": "citizenship", "value": "US citizen"}]},
    ),
    ("Lumen Health", "Content Writer", "Marketing", "Remote", None, {}),
    (
        "Orbit Commerce",
        "Growth Marketing Manager",
        "Marketing",
        "Remote",
        {"type": "worldwide", "required_overlap_hours": 2, "overlap_reference_utc": 1},
        {"salary": (80000, 100000, "EUR", "year")},
    ),
    (
        "Orbit Commerce",
        "Account Executive, APAC",
        "Sales",
        "Singapore (Remote)",
        {"type": "region_list", "regions": ["APAC"]},
        {},
    ),
    (
        "Tidewater",
        "Technical Recruiter",
        "People",
        "Remote - Taiwan",
        {"type": "country_list", "countries": ["TW"]},
        {"no_ai": True},
    ),
    ("Tidewater", "Finance Operations Lead", "Finance", "Remote", UNEXTRACTED, {}),
    (
        "Quillfeather",
        "Senior Product Manager",
        "Product",
        "Remote - Americas; Remote - Asia",
        None,
        {"skills": ["B2B SaaS"]},
    ),
    (
        "Quillfeather",
        "Privacy Counsel",
        "Legal",
        "Remote (Europe)",
        {"type": "region_list", "regions": ["EU"]},
        {},
    ),
]


def _extraction(policy: dict[str, Any] | None, extras: dict[str, Any]) -> dict[str, Any]:
    salary = extras.get("salary")
    return {
        "title": "",
        "seniority": "senior",
        "employment": "full_time",
        "location_policy": {
            "type": "unknown",
            "countries": [],
            "regions": [],
            "timezone_window_utc": None,
            "required_overlap_hours": None,
            "overlap_reference_utc": None,
            "work_authorization_required": False,
            "quotes": ["(sample)"],
            **(policy or {}),
        },
        "must_have": [{"skill": s, "quote": s} for s in extras.get("skills", [])],
        "nice_to_have": [],
        "hard_requirements": [{**b, "quote": b["value"]} for b in extras.get("blocks", [])],
        "salary": {"min": salary[0], "max": salary[1], "currency": salary[2], "period": salary[3]}
        if salary
        else None,
        "application_form": {
            "no_ai_policy": bool(extras.get("no_ai")),
            "no_ai_quote": None,
            "required_links": [],
            "questions": [],
        },
        "checks": {"location_verified": True, "no_ai_verified": True, "dropped_quotes": []},
    }


def build_sample_feed() -> dict[str, Any]:
    store = Store()
    boards: dict[str, list[Posting]] = defaultdict(list)
    for i, (company, title, department, location, _, _) in enumerate(_POSTINGS):
        slug = company.lower().replace(" ", "-")
        boards[company].append(
            Posting(
                ats="ashby",
                org=slug,
                ats_job_id=f"sample-{i:02d}",
                title=title,
                url=f"https://example.com/jobs/{slug}/{i:02d}",
                location=location,
                work_mode="remote",
                department=department,
                description=f"Sample posting {i}.",
            )
        )
    for company, postings in boards.items():
        slug = postings[0].org
        cid, _ = store.add_company(
            company, "ashby", slug, now=GENERATED_AT, website=f"https://{slug}.example.com"
        )
        store.sync_board(cid, postings, GENERATED_AT)

    for i, (_, _, _, _, policy, extras) in enumerate(_POSTINGS):
        row = store.db.execute(
            """SELECT p.id AS posting_id, s.id AS snapshot_id FROM postings p
               JOIN posting_snapshots s ON s.posting_id = p.id WHERE p.ats_job_id = ?""",
            (f"sample-{i:02d}",),
        ).fetchone()
        # Spread first-seen dates so the demo shows both new and older postings.
        seen = (GENERATED_AT - timedelta(days=i % 6, hours=i)).isoformat()
        store.db.execute(
            "UPDATE postings SET first_seen_at = ? WHERE id = ?", (seen, row["posting_id"])
        )
        if policy != UNEXTRACTED:
            store.save_extraction(
                row["snapshot_id"],
                model="sample",
                schema_version=SCHEMA_VERSION,
                now=GENERATED_AT,
                payload=_extraction(policy, extras),
            )
    store.db.commit()
    return build_feed(store, GENERATED_AT)
