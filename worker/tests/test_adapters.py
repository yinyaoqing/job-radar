import json

import httpx
import pytest

from job_radar.adapters import AshbyAdapter, GreenhouseAdapter, LeverAdapter, RecruiteeAdapter


def client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


# --- Ashby -----------------------------------------------------------------


def test_ashby_get_open_posting():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["variables"] == {
            "organizationHostedJobsPageName": "acme",
            "jobPostingId": "abc",
        }
        job = {
            "id": "abc",
            "title": "Software engineer",
            "locationName": "Remote",
            "isListed": True,
            "publishedDate": "2025-07-28",
            "descriptionHtml": "<p>x</p>",
        }
        return httpx.Response(200, json={"data": {"jobPosting": job}})

    posting = AshbyAdapter(client(handler)).get("acme", "abc")
    assert posting is not None
    assert posting.title == "Software engineer"
    assert posting.url == "https://jobs.ashbyhq.com/acme/abc"
    assert posting.published_at.year == 2025


def test_ashby_null_posting_means_closed():
    closed = {"data": {"jobPosting": None}}
    adapter = AshbyAdapter(client(lambda r: httpx.Response(200, json=closed)))
    assert adapter.get("acme", "gone") is None
    assert not adapter.is_open("acme", "gone")


def test_ashby_list_skips_unlisted():
    jobs = [
        {
            "id": "1",
            "title": "A",
            "jobUrl": "u1",
            "isListed": True,
            "location": "Remote",
            "isRemote": True,
            "publishedAt": "2026-06-01T18:38:23.725+00:00",
        },
        {"id": "2", "title": "B", "jobUrl": "u2", "isListed": False},
    ]
    adapter = AshbyAdapter(client(lambda r: httpx.Response(200, json={"jobs": jobs})))
    [posting] = adapter.list("acme")
    assert posting.ats_job_id == "1"
    assert posting.work_mode == "remote"


def test_ashby_workplace_type_beats_location_text():
    job = {
        "id": "1",
        "title": "IT support technician",
        "jobUrl": "u",
        "isListed": True,
        "location": "Albany, NY",
        "workplaceType": "OnSite",
        "isRemote": False,
        "department": "Administration",
    }
    adapter = AshbyAdapter(client(lambda r: httpx.Response(200, json={"jobs": [job]})))
    [posting] = adapter.list("acme")
    assert (posting.work_mode, posting.department) == ("onsite", "Administration")


# --- Greenhouse ------------------------------------------------------------


def test_greenhouse_404_means_closed():
    adapter = GreenhouseAdapter(client(lambda r: httpx.Response(404)))
    assert adapter.get("acme", "1") is None


def test_greenhouse_unescapes_content():
    job = {
        "id": 5,
        "title": "FE",
        "absolute_url": "u",
        "location": {"name": "Remote"},
        "updated_at": "2026-10-15T04:20:01-04:00",
        "content": "&lt;p&gt;Hi&lt;/p&gt;",
    }
    posting = GreenhouseAdapter(client(lambda r: httpx.Response(200, json=job))).get("acme", "5")
    assert posting.description == "<p>Hi</p>"
    assert posting.ats_job_id == "5"


def test_greenhouse_list_asks_for_content_and_reads_departments():
    job = {
        "id": 7,
        "title": "Recruiter, GTM",
        "absolute_url": "u",
        "location": {"name": "Remote, United States"},
        "departments": [{"name": "Talent Acquisition"}],
        "offices": [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["content"] == "true"
        return httpx.Response(200, json={"jobs": [job]})

    [posting] = GreenhouseAdapter(client(handler)).list("acme")
    assert (posting.work_mode, posting.department) == ("remote", "Talent Acquisition")


# --- Lever -----------------------------------------------------------------


def test_lever_parses_epoch_ms_and_locations():
    job = {
        "id": "x",
        "text": "FE",
        "hostedUrl": "u",
        "createdAt": 1782120062758,
        "workplaceType": "remote",
        "categories": {"location": "Asia", "allLocations": ["Asia", "Taiwan, Taipei"]},
    }
    posting = LeverAdapter(client(lambda r: httpx.Response(200, json=job))).get("acme", "x")
    assert posting.location == "Asia / Taiwan, Taipei"
    assert posting.work_mode == "remote"
    assert posting.published_at.year == 2026


# --- Recruitee -------------------------------------------------------------


RECRUITEE_OFFER = {
    "id": 2783543,
    "slug": "frontend-engineer-2",
    "title": "Frontend Engineer",
    "careers_url": "https://acme.recruitee.com/o/frontend-engineer-2",
    "location": "Remote",
    "remote": True,
    "status": "published",
    "published_at": "2026-10-15 09:31:36 UTC",
    "description": "<p>Build UI</p>",
    "requirements": "<p>React</p>",
}


def test_recruitee_list_uses_slug_and_parses_time():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "acme.recruitee.com"
        draft = {**RECRUITEE_OFFER, "slug": "draft", "status": "draft"}
        return httpx.Response(200, json={"offers": [RECRUITEE_OFFER, draft]})

    [posting] = RecruiteeAdapter(client(handler)).list("acme")
    assert posting.ats_job_id == "frontend-engineer-2"
    assert posting.published_at.isoformat() == "2026-10-15T09:31:36+00:00"
    assert posting.description == "<p>Build UI</p>\n<p>React</p>"
    assert posting.work_mode == "remote"


def test_recruitee_get_and_404():
    offer = {"offer": RECRUITEE_OFFER}
    adapter = RecruiteeAdapter(client(lambda r: httpx.Response(200, json=offer)))
    assert adapter.get("acme", "frontend-engineer-2").title == "Frontend Engineer"
    assert RecruiteeAdapter(client(lambda r: httpx.Response(404))).get("acme", "x") is None


# --- Shared ----------------------------------------------------------------


def test_host_throttle_spaces_requests_per_host(monkeypatch):
    from job_radar.adapters import base

    clock = {"t": 100.0}
    sleeps: list[float] = []
    monkeypatch.setattr(base.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(base.time, "sleep", sleeps.append)
    throttle = base.HostThrottle(1.0)
    throttle(httpx.Request("GET", "https://a.example/1"))
    throttle(httpx.Request("GET", "https://a.example/2"))
    throttle(httpx.Request("GET", "https://b.example/1"))
    assert sleeps == [1.0]


def test_unexpected_status_raises():
    from job_radar.adapters import AdapterError

    adapter = LeverAdapter(client(lambda r: httpx.Response(500)))
    with pytest.raises(AdapterError):
        adapter.get("acme", "x")
