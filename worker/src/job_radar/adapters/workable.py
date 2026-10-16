"""Workable public careers API.

The board list is ``POST /api/v3/accounts/<org>/jobs``, ten jobs a page, continued by
sending back ``nextPage`` as ``token``. A single job is ``GET /api/v2/.../jobs/<shortcode>``
and returns 404 once closed. ``workplace`` is ``remote`` / ``hybrid`` / ``on_site``.
"""

from __future__ import annotations

from typing import Any

from .base import Adapter, AdapterError, Posting, parse_iso

LIST_URL = "https://apply.workable.com/api/v3/accounts/{org}/jobs"
JOB_URL = "https://apply.workable.com/api/v2/accounts/{org}/jobs/{shortcode}"
PUBLIC_URL = "https://apply.workable.com/{org}/j/{shortcode}/"
WORKPLACES = {"remote": "remote", "hybrid": "hybrid", "on_site": "onsite"}
MAX_PAGES = 50


class WorkableAdapter(Adapter):
    name = "workable"

    def list(self, org: str) -> list[Posting]:
        body: dict[str, Any] = {"query": "", "location": [], "department": [], "worktype": []}
        postings: list[Posting] = []
        for _ in range(MAX_PAGES):
            resp = self._client.post(LIST_URL.format(org=org), json=body)
            if resp.status_code == 404:
                raise AdapterError(f"workable: no account named {org!r}")
            if resp.status_code != 200:
                raise AdapterError(f"workable: list {org} -> HTTP {resp.status_code}")
            data = resp.json()
            postings += [
                self._to_posting(org, job)
                for job in data.get("results", [])
                if job.get("state", "published") == "published"
            ]
            if not data.get("nextPage"):
                return [self._with_description(org, p) for p in postings]
            body["token"] = data["nextPage"]
        raise AdapterError(f"workable: {org} has more than {MAX_PAGES} pages")

    def _with_description(self, org: str, posting: Posting) -> Posting:
        """The board list has no description; remote postings need one for extraction,
        so they cost one more request each (throttled like every other call)."""
        if posting.work_mode != "remote" or posting.description:
            return posting
        try:
            detailed = self.get(org, posting.ats_job_id)
        except AdapterError:
            return posting
        return detailed or posting

    def get(self, org: str, job_id: str) -> Posting | None:
        job = self._get_json(JOB_URL.format(org=org, shortcode=job_id))
        return None if job is None else self._to_posting(org, job)

    def _to_posting(self, org: str, job: dict[str, Any]) -> Posting:
        locations = job.get("locations") or [job.get("location") or {}]
        places = []
        for loc in locations:
            if loc.get("hidden"):
                continue
            place = ", ".join(p for p in (loc.get("city"), loc.get("country")) if p)
            if place and place not in places:
                places.append(place)
        work_mode = WORKPLACES.get(job.get("workplace") or "")
        if work_mode is None:
            work_mode = "remote" if job.get("remote") else "unknown"
        if work_mode == "remote":
            places = [f"Remote ({p})" for p in places] or ["Remote"]
        parts = [job.get("description"), job.get("requirements"), job.get("benefits")]
        return Posting(
            ats=self.name,
            org=org,
            ats_job_id=job["shortcode"],
            title=job["title"],
            url=PUBLIC_URL.format(org=org, shortcode=job["shortcode"]),
            location=" / ".join(places) or None,
            work_mode=work_mode,
            department=" / ".join(job.get("department") or []) or None,
            published_at=parse_iso(job.get("published")),
            description="\n".join(p for p in parts if p) or None,
            raw=job,
        )
