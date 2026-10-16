"""Ashby: public posting API for the board, hosted-jobs GraphQL for a single posting.

A closed posting comes back from GraphQL as ``{"data": {"jobPosting": null}}``.
"""

from __future__ import annotations

from typing import Any

from ..classify import work_mode_from_text
from .base import Adapter, AdapterError, Posting, country_code, parse_iso

WORKPLACE_TYPES = {"Remote": "remote", "Hybrid": "hybrid", "OnSite": "onsite"}

BOARD_URL = "https://api.ashbyhq.com/posting-api/job-board/{org}"
GRAPHQL_URL = "https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobPosting"
POSTING_QUERY = """
query ApiJobPosting($organizationHostedJobsPageName: String!, $jobPostingId: String!) {
  jobPosting(
    organizationHostedJobsPageName: $organizationHostedJobsPageName
    jobPostingId: $jobPostingId
  ) {
    id
    title
    locationName
    isListed
    publishedDate
    descriptionHtml
  }
}
"""


class AshbyAdapter(Adapter):
    name = "ashby"

    def list(self, org: str) -> list[Posting]:
        data = self._get_json(BOARD_URL.format(org=org))
        if data is None:
            raise AdapterError(f"ashby: no job board named {org!r}")
        return [self._from_board(org, job) for job in data.get("jobs", []) if job.get("isListed")]

    def get(self, org: str, job_id: str) -> Posting | None:
        resp = self._send(
            "POST",
            GRAPHQL_URL,
            json={
                "operationName": "ApiJobPosting",
                "variables": {"organizationHostedJobsPageName": org, "jobPostingId": job_id},
                "query": POSTING_QUERY,
            },
        )
        if resp.status_code != 200:
            raise AdapterError(f"ashby: GraphQL -> HTTP {resp.status_code}")
        body = resp.json()
        if body.get("errors"):
            raise AdapterError(f"ashby: GraphQL errors {body['errors']}")
        job = (body.get("data") or {}).get("jobPosting")
        if job is None:
            return None
        return Posting(
            ats=self.name,
            org=org,
            ats_job_id=job["id"],
            title=job["title"],
            url=f"https://jobs.ashbyhq.com/{org}/{job['id']}",
            location=job.get("locationName"),
            work_mode=work_mode_from_text(job.get("locationName")),
            published_at=parse_iso(job.get("publishedDate")),
            description=job.get("descriptionHtml"),
            raw=job,
        )

    def _from_board(self, org: str, job: dict[str, Any]) -> Posting:
        work_mode = WORKPLACE_TYPES.get(job.get("workplaceType") or "")
        if work_mode is None:
            work_mode = (
                "remote" if job.get("isRemote") else work_mode_from_text(job.get("location"))
            )
        return Posting(
            ats=self.name,
            org=org,
            ats_job_id=job["id"],
            title=job["title"],
            url=job["jobUrl"],
            location=job.get("location"),
            work_mode=work_mode,
            department=job.get("department") or job.get("team"),
            ats_country=country_code(
                ((job.get("address") or {}).get("postalAddress") or {}).get("addressCountry")
            ),
            published_at=parse_iso(job.get("publishedAt")),
            description=job.get("descriptionPlain"),
            raw=job,
        )
