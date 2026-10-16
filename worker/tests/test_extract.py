from types import SimpleNamespace

import pytest

from job_radar.eligibility import Candidate, assess, policy_from_location_text
from job_radar.evaluate import load_cases, run_live, run_rules
from job_radar.export import build_feed
from job_radar.extract import (
    SCHEMA_VERSION,
    ApplicationForm,
    Extraction,
    ExtractionFailed,
    HardRequirement,
    LocationPolicy,
    PostingInput,
    QuotedSkill,
    Usage,
    check_quotes,
    claude_extractor,
)
from job_radar.pipeline import extract_pending
from job_radar.store import Store
from job_radar.textutil import html_to_text, normalize, quote_in

from .test_pipeline import T0, posting

JD = (
    "<p>We hire worldwide.</p><ul><li>5+ years of TypeScript</li>"
    "<li>Experience with React &amp; Next.js</li></ul>"
    "<p>Please don’t use AI tools to write your answers.</p>"
)


def extraction(**overrides) -> Extraction:
    base = dict(
        title="Frontend Engineer",
        seniority="senior",
        employment="full_time",
        location_policy=LocationPolicy(
            type="worldwide",
            countries=[],
            regions=[],
            timezone_window_utc=None,
            required_overlap_hours=None,
            overlap_reference_utc=None,
            work_authorization_required=False,
            quotes=["We hire worldwide."],
        ),
        must_have=[
            QuotedSkill(skill="TypeScript", quote="5+ years of TypeScript"),
            QuotedSkill(skill="Go", quote="Deep experience with Go"),  # not in the JD
        ],
        nice_to_have=[],
        hard_requirements=[
            HardRequirement(type="years", value="5", quote="5+ years of TypeScript")
        ],
        salary=None,
        application_form=ApplicationForm(
            no_ai_policy=True,
            no_ai_quote="Please don't use AI tools to write your answers.",
            required_links=[],
            questions=[],
        ),
    )
    base.update(overrides)
    return Extraction(**base)


# --- text ------------------------------------------------------------------


def test_html_to_text_keeps_list_items_on_lines():
    text = html_to_text(JD)
    assert "- 5+ years of TypeScript" in text.splitlines()
    assert "React & Next.js" in text


def test_quote_match_ignores_case_space_and_curly_quotes():
    source = normalize(html_to_text(JD))
    assert quote_in("please DON'T use  AI tools", source)
    assert not quote_in("", source)
    assert not quote_in("We hire in the US only", source)


# --- quote checks ----------------------------------------------------------


def test_check_quotes_drops_unfound_skill_and_keeps_verified_policy():
    posting_input = PostingInput("Frontend Engineer", "Remote", None, html_to_text(JD))
    payload = check_quotes(extraction(), posting_input)
    assert [s["skill"] for s in payload["must_have"]] == ["TypeScript"]
    assert payload["checks"]["location_verified"] is True
    assert payload["checks"]["no_ai_verified"] is True
    assert payload["checks"]["dropped_quotes"] == ["must_have: Deep experience with Go"]


def test_unverified_policy_makes_eligibility_unclear():
    posting_input = PostingInput("Frontend Engineer", "Remote", None, "Join us.")
    payload = check_quotes(extraction(), posting_input)
    assert payload["checks"]["location_verified"] is False
    verdict = assess(work_mode="remote", location_text="Remote", extraction=payload)
    assert verdict.label == "unclear"


# --- Claude call -----------------------------------------------------------


def fake_client(stop_reason="end_turn", parsed=None):
    calls = []

    def parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            stop_reason=stop_reason,
            stop_details=None,
            parsed_output=parsed,
            usage=SimpleNamespace(input_tokens=1000, output_tokens=200),
        )

    return SimpleNamespace(messages=SimpleNamespace(parse=parse)), calls


def test_claude_extractor_sends_schema_and_returns_usage():
    client, calls = fake_client(parsed=extraction())
    result, usage = claude_extractor(client=client)(PostingInput("T", "Remote", None, "jd"))
    assert result.title == "Frontend Engineer"
    assert calls[0]["model"] == "claude-haiku-5-5"
    assert calls[0]["output_format"] is Extraction
    assert usage.cost_usd("claude-haiku-5-5") == pytest.approx(0.0002)


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_claude_extractor_raises_on_unusable_response(stop_reason):
    client, _ = fake_client(stop_reason=stop_reason, parsed=None)
    with pytest.raises(ExtractionFailed):
        claude_extractor(client=client)(PostingInput("T", None, None, "jd"))


# --- pipeline --------------------------------------------------------------


def store_with_postings(n: int) -> Store:
    store = Store()
    cid, _ = store.add_company("Acme", "lever", "acme", now=T0)
    store.sync_board(cid, [posting(str(i), description=JD) for i in range(n)], T0)
    return store


def test_extract_pending_stores_checked_payload_and_cost():
    store = store_with_postings(2)

    def llm(p):
        return extraction(), Usage(1000, 200)

    stats = extract_pending(store, llm, model="claude-haiku-5-5", now=lambda: T0)
    assert (stats.extracted, stats.failed) == (2, 0)
    assert stats.cost_usd == pytest.approx(0.0004)
    assert store.pending_extractions(SCHEMA_VERSION, 10) == []
    row = store.open_postings()[0]
    stored = store.latest_extraction(row["id"], SCHEMA_VERSION)
    assert stored["checks"]["location_verified"] is True


def test_extract_pending_records_refusals_but_retries_api_errors():
    store = store_with_postings(2)
    seen = []

    def llm(p):
        seen.append(p)
        if len(seen) == 1:
            raise ExtractionFailed("refused")
        raise ConnectionError("network down")

    stats = extract_pending(store, llm, model="claude-haiku-5-5", workers=1, now=lambda: T0)
    assert stats.failed == 2
    # The refusal is recorded; the network error stays pending for the next run.
    assert len(store.pending_extractions(SCHEMA_VERSION, 10)) == 1
    assert store.retry_failed_extractions() == 1
    assert len(store.pending_extractions(SCHEMA_VERSION, 10)) == 2


def test_extract_pending_stops_at_budget():
    store = store_with_postings(5)

    def llm(p):
        return extraction(), Usage(1_000_000, 0)  # US$0.10 a call

    stats = extract_pending(
        store, llm, model="claude-haiku-5-5", max_cost_usd=0.15, workers=1, now=lambda: T0
    )
    assert stats.extracted == 2
    assert stats.stopped_at_budget


def test_edited_jd_gets_a_new_extraction_but_shows_the_old_meanwhile():
    store = store_with_postings(1)
    extract_pending(store, lambda p: (extraction(), Usage(1, 1)), model="claude-haiku-5-5")
    cid = store.watched_companies()[0].id
    store.sync_board(cid, [posting("0", description=JD + "<p>Now with Rust.</p>")], T0)
    assert len(store.pending_extractions(SCHEMA_VERSION, 10)) == 1
    row = store.open_postings()[0]
    assert store.latest_extraction(row["id"], SCHEMA_VERSION) is not None


# --- eligibility -----------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Remote", None),
        ("Remote - Worldwide", {"type": "worldwide", "countries": [], "regions": []}),
        ("Remote (USA)", {"type": "country_list", "countries": ["US"], "regions": []}),
        ("Remote - CA", {"type": "country_list", "countries": ["US"], "regions": []}),
        (
            "UNITED STATES - Remote, LATAM - Remote",
            {"type": "region_list", "countries": ["US"], "regions": ["LATAM"]},
        ),
        ("Remote - Asia Pacific", {"type": "region_list", "countries": [], "regions": ["APAC"]}),
        ("Anywhere, United States", {"type": "country_list", "countries": ["US"], "regions": []}),
    ],
)
def test_policy_from_location_text(text, expected):
    assert policy_from_location_text(text) == expected


def test_other_candidates_get_their_own_answer():
    berlin = Candidate(country="DE", utc_offset=1)
    extraction_eu = {
        "location_policy": {"type": "region_list", "countries": [], "regions": ["EU"]},
        "checks": {"location_verified": True},
    }
    assert (
        assess(
            work_mode="remote", location_text="Remote", extraction=extraction_eu, candidate=berlin
        ).label
        == "eligible"
    )
    assert (
        assess(work_mode="remote", location_text="Remote", extraction=extraction_eu).label
        == "blocked"
    )


# --- evals -----------------------------------------------------------------


def test_region_trap_rules_meet_targets():
    report = run_rules(load_cases())
    assert len(report.results) >= 30
    assert report.passed, report.summary()["failures"]


def test_live_eval_scores_what_the_llm_extracts():
    cases = [
        c for c in load_cases() if c["id"] in ("worldwide-explicit", "remote-but-us-residents")
    ]

    def llm(p):
        # A model that always says "worldwide", quoting the case text verbatim.
        policy = extraction().location_policy.model_copy(update={"quotes": [p.jd_text]})
        return extraction(location_policy=policy, must_have=[]), Usage(100, 10)

    report = run_live(cases, llm, "claude-haiku-5-5")
    assert report.accuracy == 0.5
    assert report.blocked_recall == 0.0
    assert not report.passed


# --- feed ------------------------------------------------------------------


def test_feed_carries_policy_but_no_quotes():
    store = store_with_postings(1)
    extract_pending(store, lambda p: (extraction(), Usage(1, 1)), model="claude-haiku-5-5")
    item = build_feed(store, T0)["postings"][0]
    assert item["extracted"] is True
    assert item["location_policy"]["type"] == "worldwide"
    assert item["skills"] == ["TypeScript"]
    assert item["no_ai_policy"] is True
    assert "We hire worldwide." not in str(item)


def test_web_eligibility_fixture_is_current():
    import json

    from job_radar.evaluate import WEB_FIXTURE, web_fixture

    expected = web_fixture(load_cases())
    current = json.loads(WEB_FIXTURE.read_text(encoding="utf-8"))
    assert current == expected, "run: uv run job-radar eval regions --write-web-fixture"


def test_sample_feed_is_current():
    import json

    from job_radar.sample import SAMPLE_FEED, build_sample_feed

    assert json.loads(SAMPLE_FEED.read_text(encoding="utf-8")) == build_sample_feed(), (
        "run: uv run job-radar export --sample"
    )


def test_timezone_limit_without_offsets_is_unclear_not_anywhere():
    extraction = {
        "location_policy": {"type": "timezone_window", "timezone_window_utc": None},
        "checks": {"location_verified": True},
    }
    verdict = assess(work_mode="remote", location_text="Remote", extraction=extraction)
    assert verdict.label == "unclear"
    assert policy_from_location_text("Remote (West Coast)")["countries"] == ["US"]


def test_failed_overlap_blocks_even_when_place_is_unknown():
    unknown_with_overlap = {
        "location_policy": {
            "type": "unknown",
            "required_overlap_hours": 4,
            "overlap_reference_utc": -5,
        },
        "checks": {"location_verified": True},
    }
    assert (
        assess(work_mode="remote", location_text="Remote", extraction=unknown_with_overlap).label
        == "blocked"
    )
    unknown_with_overlap["location_policy"]["overlap_reference_utc"] = 1
    verdict = assess(work_mode="remote", location_text="Remote", extraction=unknown_with_overlap)
    assert verdict.label == "unclear"
