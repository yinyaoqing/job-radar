import json

import httpx

from job_radar.adapters import AdapterError, WorkableAdapter
from job_radar.discovery import detect_ats, harvest_hn, parse_hn_comment
from job_radar.pipeline import crawl
from job_radar.store import Store

from .test_pipeline import T0, FakeAdapter, posting


def client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


# --- Workable --------------------------------------------------------------


def workable_job(shortcode: str, workplace: str = "remote", **extra) -> dict:
    return {
        "shortcode": shortcode,
        "title": "Senior Designer",
        "state": "published",
        "remote": workplace == "remote",
        "workplace": workplace,
        "locations": [{"city": "", "country": "United States", "hidden": False}],
        "department": ["Design"],
        "published": "2026-10-07T00:00:00.000Z",
        **extra,
    }


def test_workable_list_follows_next_page_token():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":  # detail for the remote posting
            return httpx.Response(200, json=workable_job("A", description="<p>Full JD</p>"))
        body = json.loads(request.content)
        if "token" not in body:
            return httpx.Response(200, json={"results": [workable_job("A")], "nextPage": "t2"})
        assert body["token"] == "t2"
        return httpx.Response(200, json={"results": [workable_job("B", "on_site")]})

    first, second = WorkableAdapter(client(handler)).list("acme")
    assert first.url == "https://apply.workable.com/acme/j/A/"
    assert (first.work_mode, first.location) == ("remote", "Remote (United States)")
    assert first.department == "Design"
    assert first.description == "<p>Full JD</p>"  # fetched because the list has none
    assert second.description is None  # onsite: no extra request
    assert (second.work_mode, second.location) == ("onsite", "United States")


def test_workable_unknown_account_and_closed_job():
    adapter = WorkableAdapter(client(lambda r: httpx.Response(404)))
    try:
        adapter.list("nobody")
    except AdapterError:
        pass
    else:
        raise AssertionError("expected AdapterError")
    assert adapter.get("acme", "GONE") is None


# --- URL detection ---------------------------------------------------------


def test_detect_ats_workable_and_greenhouse_embed():
    assert detect_ats("https://apply.workable.com/seeq/j/1B6E0A1710/") == ("workable", "seeq")
    assert detect_ats("https://sumble-inc.workable.com/") == ("workable", "sumble-inc")
    assert detect_ats("https://apply.workable.com/j/FE43DE896A") is None
    embed = "https://boards.greenhouse.io/embed/job_app?for=acme&token=123"
    assert detect_ats(embed) == ("greenhouse", "acme")


# --- HN --------------------------------------------------------------------


COMMENT = (
    "Acme Robotics | Senior Engineer | REMOTE (Worldwide)<p>Apply: "
    '<a href="https:&#x2F;&#x2F;grnh.se&#x2F;abc1">grnh.se&#x2F;abc1</a> or '
    '<a href="https:&#x2F;&#x2F;jobs.ashbyhq.com&#x2F;acme&#x2F;123">ashby</a>'
)


def test_parse_hn_comment():
    company, urls = parse_hn_comment(COMMENT)
    assert company == "Acme Robotics"
    assert urls == ["https://grnh.se/abc1", "https://jobs.ashbyhq.com/acme/123"]


def test_harvest_hn_resolves_short_links_and_dedupes():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/search_by_date":
            hits = [
                {"objectID": "2", "title": "Ask HN: Who wants to be hired? (October 2026)"},
                {"objectID": "1", "title": "Ask HN: Who is hiring? (October 2026)"},
            ]
            return httpx.Response(200, json={"hits": hits})
        if request.url.path == "/api/v1/items/1":
            again = 'Acme again | x <a href="https://jobs.ashbyhq.com/acme">a</a>'
            return httpx.Response(200, json={"children": [{"text": COMMENT}, {"text": again}]})
        if request.url.host == "grnh.se":
            location = "https://job-boards.greenhouse.io/acmerobotics/jobs/1?gh_src=abc1"
            return httpx.Response(301, headers={"location": location})
        raise AssertionError(f"unexpected {request.url}")

    leads = harvest_hn(client(handler))
    assert [(lead.company, lead.ats, lead.org) for lead in leads] == [
        ("Acme Robotics", "greenhouse", "acmerobotics"),
        ("Acme Robotics", "ashby", "acme"),
    ]


# --- failing boards --------------------------------------------------------


def test_board_is_skipped_after_three_failures_until_reset():
    store = Store()
    store.add_company("Gone", "lever", "gone", now=T0)
    boards = {"gone": AdapterError("404")}
    for _ in range(3):
        crawl(store, adapter_for=lambda ats: FakeAdapter(boards), now=lambda: T0)
    assert store.watched_companies() == []
    assert store.company_stats()[0]["fail_count"] == 3

    boards["gone"] = [posting("a")]
    assert store.reset_failures() == 1
    stats = crawl(store, adapter_for=lambda ats: FakeAdapter(boards), now=lambda: T0)
    assert stats.boards_ok == 1
    assert store.company_stats()[0]["fail_count"] == 0


def test_parse_hn_comment_trims_a_pitch_from_the_company_name():
    text = "DuckBank - we are looking for people who are excited to join | Engineer | Remote"
    assert parse_hn_comment(text)[0] == "DuckBank"
    assert parse_hn_comment("Short Name Inc | Role")[0] == "Short Name Inc"
