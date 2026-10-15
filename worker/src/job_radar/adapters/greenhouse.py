"""Greenhouse job board API. A closed posting returns HTTP 404."""

from __future__ import annotations

import html
from typing import Any

from .base import Adapter, AdapterError, Posting, parse_iso

BASE_URL = "https://boards-api.greenhouse.io/v1/boards/{org}/jobs"


class GreenhouseAdapter(Adapter):
    name = "greenhouse"

    def list(self, org: str) -> list[Posting]:
        data = self._get_json(BASE_URL.format(org=org))
        if data is None:
            raise AdapterError(f"greenhouse: no board named {org!r}")
        return [self._to_posting(org, job) for job in data.get("jobs", [])]

    def get(self, org: str, job_id: str) -> Posting | None:
        job = self._get_json(f"{BASE_URL.format(org=org)}/{job_id}")
        return None if job is None else self._to_posting(org, job)

    def _to_posting(self, org: str, job: dict[str, Any]) -> Posting:
        content = job.get("content")
        return Posting(
            ats=self.name,
            org=org,
            ats_job_id=str(job["id"]),
            title=job["title"],
            url=job["absolute_url"],
            location=(job.get("location") or {}).get("name"),
            published_at=parse_iso(job.get("first_published") or job.get("updated_at")),
            # Greenhouse returns the description HTML-escaped.
            description=html.unescape(content) if content else None,
            raw=job,
        )
