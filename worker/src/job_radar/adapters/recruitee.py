"""Recruitee careers-site API. A closed offer (or unknown company) returns HTTP 404.

Offers are addressed by ``slug``, not the numeric id, so ``ats_job_id`` is the slug.
Timestamps look like ``2026-10-15 09:31:36 UTC``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..classify import work_mode_from_text
from .base import Adapter, AdapterError, Posting

BASE_URL = "https://{org}.recruitee.com/api/offers/"


class RecruiteeAdapter(Adapter):
    name = "recruitee"

    def list(self, org: str) -> list[Posting]:
        data = self._get_json(BASE_URL.format(org=org))
        if data is None:
            raise AdapterError(f"recruitee: no careers site named {org!r}")
        return [
            self._to_posting(org, offer)
            for offer in data.get("offers", [])
            if offer.get("status", "published") == "published"
        ]

    def get(self, org: str, job_id: str) -> Posting | None:
        data = self._get_json(f"{BASE_URL.format(org=org)}{job_id}")
        return None if data is None else self._to_posting(org, data["offer"])

    def _to_posting(self, org: str, offer: dict[str, Any]) -> Posting:
        parts = [offer.get("description"), offer.get("requirements")]
        return Posting(
            ats=self.name,
            org=org,
            ats_job_id=offer["slug"],
            title=offer["title"],
            url=offer["careers_url"],
            location=offer.get("location") or None,
            work_mode=_work_mode(offer),
            department=offer.get("department") or None,
            published_at=parse_recruitee_time(offer.get("published_at")),
            description="\n".join(p for p in parts if p) or None,
            raw=offer,
        )


def _work_mode(offer: dict[str, Any]) -> str:
    if offer.get("remote"):
        return "remote"
    if offer.get("hybrid"):
        return "hybrid"
    if offer.get("on_site"):
        return "onsite"
    return work_mode_from_text(offer.get("location"))


def parse_recruitee_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=UTC)
