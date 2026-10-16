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


# --- We Work Remotely --------------------------------------------------------

WWR_XML = """<rss><channel>
<item><title>Acme Robotics: Senior Backend Engineer</title>
<region>Anywhere in the World</region></item>
<item><title><![CDATA[Engine: Product Designer]]></title></item>
<item><title>Acme Robotics: Data Analyst</title></item>
</channel></rss>"""


def test_parse_wwr_feed_and_slugs():
    from job_radar.discovery import name_slugs, parse_wwr_feed

    assert parse_wwr_feed(WWR_XML) == [
        ("Acme Robotics", "Senior Backend Engineer"),
        ("Engine", "Product Designer"),
        ("Acme Robotics", "Data Analyst"),
    ]
    assert name_slugs("Customer.io") == ["customerio"]
    assert name_slugs("Acme Robotics Inc.") == ["acmerobotics", "acme-robotics", "acme"]


def test_find_board_needs_a_matching_title():
    from job_radar.discovery import NamedLead, find_board

    class Board(FakeAdapter):
        def list(self, org):
            if org not in self.boards:
                raise AdapterError("404")
            return self.boards[org]

    # "engine" exists on Greenhouse but is another company: no matching title.
    adapters = {
        "greenhouse": Board({"engine": [posting("1", "Truck Driver")]}),
        "lever": Board({}),
        "ashby": Board({"acmerobotics": [posting("2", "Senior Backend Engineer (Remote)")]}),
        "recruitee": Board({}),
        "workable": Board({}),
        "smartrecruiters": Board({}),
    }
    assert find_board(NamedLead("Engine", ["Product Designer"]), adapters) is None
    lead = NamedLead("Acme Robotics", ["Senior Backend Engineer", "Data Analyst"])
    assert find_board(lead, adapters) == ("ashby", "acmerobotics")


def test_import_named_leads_remembers_misses():
    from datetime import timedelta

    from job_radar.discovery import NamedLead, import_named_leads

    class Nothing(FakeAdapter):
        def list(self, org):
            raise AdapterError("404")

    adapters = {
        k: Nothing({})
        for k in ("greenhouse", "lever", "ashby", "recruitee", "workable", "smartrecruiters")
    }
    store = Store()
    store.add_company("Known Co", "lever", "known", now=T0)
    leads = [NamedLead("Known Co", ["x"]), NamedLead("Ghost", ["y"])]
    first = import_named_leads(store, leads, adapters, source="wwr", now=T0)
    assert (first["known"], first["missed"]) == (1, 1)
    again = import_named_leads(store, leads, adapters, source="wwr", now=T0 + timedelta(days=1))
    assert again["skipped_recent_miss"] == 1
    later = import_named_leads(store, leads, adapters, source="wwr", now=T0 + timedelta(days=31))
    assert later["missed"] == 1


# --- SmartRecruiters -------------------------------------------------------


def sr_job(job_id: str, remote: bool = True) -> dict:
    return {
        "id": job_id,
        "name": "Frontend Engineer",
        "location": {
            "city": "",
            "country": "tw",
            "remote": remote,
            "hybrid": False,
            "fullLocation": "Taiwan",
        },
        "function": {"label": "Engineering"},
        "releasedDate": "2026-10-16T08:37:34.756Z",
    }


def test_smartrecruiters_pages_and_fetches_remote_descriptions():
    from job_radar.adapters import SmartRecruitersAdapter

    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path.endswith("/postings"):
            offset = int(request.url.params["offset"])
            content = [sr_job(str(offset + i), remote=(offset + i) % 2 == 0) for i in range(100)]
            if offset == 100:
                content = content[:20]
            return httpx.Response(200, json={"totalFound": 120, "content": content})
        job = sr_job(request.url.path.rsplit("/", 1)[-1])
        job["jobAd"] = {"sections": {"jobDescription": {"text": "<p>Build UI</p>"}}}
        return httpx.Response(200, json=job)

    postings = SmartRecruitersAdapter(client(handler)).list("Acme")
    assert len(postings) == 120
    first = postings[0]
    assert (first.work_mode, first.location, first.ats_country) == (
        "remote",
        "Remote (Taiwan)",
        "TW",
    )
    assert first.description == "<p>Build UI</p>"
    assert first.url == "https://jobs.smartrecruiters.com/Acme/0"
    assert postings[1].work_mode == "onsite" and postings[1].description is None
    assert sum("/postings/" in u for u in calls) == 60  # one detail call per remote posting


def test_smartrecruiters_empty_company_is_no_board():
    from job_radar.adapters import SmartRecruitersAdapter

    adapter = SmartRecruitersAdapter(
        client(lambda r: httpx.Response(200, json={"totalFound": 0, "content": []}))
    )
    try:
        adapter.list("Nobody")
    except AdapterError:
        pass
    else:
        raise AssertionError("expected AdapterError")
    assert detect_ats("https://jobs.smartrecruiters.com/Acme/123-fe") == ("smartrecruiters", "Acme")
