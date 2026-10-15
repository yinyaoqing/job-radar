import json

import httpx
import pytest

from job_radar.adapters import AshbyAdapter, GreenhouseAdapter, LeverAdapter


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
    assert [p.ats_job_id for p in adapter.list("acme")] == ["1"]


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
    assert posting.is_remote is True
    assert posting.published_at.year == 2026


def test_unexpected_status_raises():
    from job_radar.adapters import AdapterError

    adapter = LeverAdapter(client(lambda r: httpx.Response(500)))
    with pytest.raises(AdapterError):
        adapter.get("acme", "x")
