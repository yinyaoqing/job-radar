"""SmartRecruiters public Posting API (no key; only for customers whose plan exposes it).

``/v1/companies/<org>/postings`` pages with ``limit``/``offset``. An unknown company answers
200 with nothing, so zero postings counts as "no board" here, which keeps probing and the
failing-board counter honest. A single posting is ``.../postings/<id>`` (404 once closed);
only that carries the description, so remote postings cost one more request each.
"""

from __future__ import annotations

from typing import Any

from .base import Adapter, AdapterError, Posting, parse_iso

LIST_URL = "https://api.smartrecruiters.com/v1/companies/{org}/postings"
PUBLIC_URL = "https://jobs.smartrecruiters.com/{org}/{id}"
PAGE = 100
MAX_PAGES = 100


class SmartRecruitersAdapter(Adapter):
    name = "smartrecruiters"

    def list(self, org: str) -> list[Posting]:
        postings: list[Posting] = []
        for page in range(MAX_PAGES):
            data = self._get_json(
                LIST_URL.format(org=org), params={"limit": PAGE, "offset": page * PAGE}
            )
            if data is None:
                raise AdapterError(f"smartrecruiters: no company named {org!r}")
            content = data.get("content") or []
            postings += [self._to_posting(org, job) for job in content]
            if page == 0 and not data.get("totalFound"):
                raise AdapterError(f"smartrecruiters: no public postings for {org!r}")
            if len(postings) >= (data.get("totalFound") or 0) or not content:
                return [self._with_description(org, p) for p in postings]
        raise AdapterError(f"smartrecruiters: {org} has more than {MAX_PAGES} pages")

    def get(self, org: str, job_id: str) -> Posting | None:
        job = self._get_json(f"{LIST_URL.format(org=org)}/{job_id}")
        if job is None or job.get("active") is False:
            return None
        return self._to_posting(org, job)

    def _with_description(self, org: str, posting: Posting) -> Posting:
        if posting.work_mode != "remote" or posting.description:
            return posting
        try:
            return self.get(org, posting.ats_job_id) or posting
        except AdapterError:
            return posting

    def _to_posting(self, org: str, job: dict[str, Any]) -> Posting:
        loc = job.get("location") or {}
        if loc.get("remote"):
            work_mode = "remote"
        elif loc.get("hybrid"):
            work_mode = "hybrid"
        elif loc.get("city") or loc.get("country"):
            work_mode = "onsite"
        else:
            work_mode = "unknown"
        place = (loc.get("fullLocation") or "").replace(", ,", ",").strip(", ") or None
        if work_mode == "remote":
            place = f"Remote ({place})" if place else "Remote"
        sections = ((job.get("jobAd") or {}).get("sections")) or {}
        description = "\n".join(
            s["text"]
            for key in ("jobDescription", "qualifications", "additionalInformation")
            if (s := sections.get(key)) and s.get("text")
        )
        department = (job.get("department") or {}).get("label") or (job.get("function") or {}).get(
            "label"
        )
        return Posting(
            ats=self.name,
            org=org,
            ats_job_id=str(job["id"]),
            title=job["name"],
            url=job.get("postingUrl") or PUBLIC_URL.format(org=org, id=job["id"]),
            location=place,
            work_mode=work_mode,
            department=department,
            ats_country=(loc.get("country") or "").upper() or None,
            published_at=parse_iso(job.get("releasedDate")),
            description=description or None,
            raw=job,
        )
