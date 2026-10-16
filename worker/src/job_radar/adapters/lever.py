"""Lever postings API. A closed posting returns HTTP 404; ``createdAt`` is epoch milliseconds."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..classify import work_mode_from_text
from .base import Adapter, AdapterError, Posting, country_code

BASE_URL = "https://api.lever.co/v0/postings/{org}"
WORKPLACE_TYPES = {"remote": "remote", "hybrid": "hybrid", "onsite": "onsite"}


class LeverAdapter(Adapter):
    name = "lever"

    def list(self, org: str) -> list[Posting]:
        data = self._get_json(BASE_URL.format(org=org), params={"mode": "json"})
        if data is None:
            raise AdapterError(f"lever: no postings site named {org!r}")
        return [self._to_posting(org, job) for job in data]

    def get(self, org: str, job_id: str) -> Posting | None:
        job = self._get_json(f"{BASE_URL.format(org=org)}/{job_id}", params={"mode": "json"})
        return None if job is None else self._to_posting(org, job)

    def _to_posting(self, org: str, job: dict[str, Any]) -> Posting:
        categories = job.get("categories") or {}
        locations = categories.get("allLocations") or [categories.get("location")]
        location = " / ".join(loc for loc in locations if loc) or None
        created = job.get("createdAt")
        return Posting(
            ats=self.name,
            org=org,
            ats_job_id=job["id"],
            title=job["text"],
            url=job["hostedUrl"],
            location=location,
            work_mode=WORKPLACE_TYPES.get(job.get("workplaceType") or "")
            or work_mode_from_text(location),
            department=categories.get("team") or categories.get("department"),
            ats_country=country_code(job.get("country")),
            published_at=datetime.fromtimestamp(created / 1000, tz=UTC) if created else None,
            description=job.get("descriptionPlain"),
            raw=job,
        )
