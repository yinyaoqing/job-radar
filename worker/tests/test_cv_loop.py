"""The writer/reviewer loop, with both agents faked: what is under test is the
orchestration and the gate, not a model."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from job_radar import cv
from job_radar import cv_loop as loop
from job_radar.extract import ExtractionFailed

EVALS = Path(__file__).resolve().parents[2] / "evals" / "cv"
POSTING = {"title": "Senior Frontend Engineer", "company": "Northwind", "url": "https://x/j/1"}
EXTRACTION = {"must_have": [{"skill": "React", "quote": ""}], "nice_to_have": []}
GOOD = "Cut checkout load from 4.1s to 1.6s."
INFLATED = "Cut checkout load from 4.1s to 0.9s."


@pytest.fixture
def store() -> cv.EvidenceStore:
    return cv.EvidenceStore.load(EVALS / "example-evidence.yaml")


def draft(text=GOOD, ids=("e1",), skills=("React",)) -> cv.CvDraft:
    sentence = cv.CitedSentence(text=text, evidence_ids=list(ids))
    return cv.CvDraft(
        summary=[cv.CitedSentence(text="Frontend engineer.", evidence_ids=["e1"])],
        sections=[cv.RoleSection(role="Frontend Engineer", bullets=[sentence])],
        skills=list(skills),
    )


def scripted_writer(*drafts, cost=0.01):
    seen = []

    def write(posting, extraction, store, feedback):
        seen.append(list(feedback))
        return drafts[min(len(seen), len(drafts)) - 1], cost

    return write, seen


def scripted_reviewer(*reviews, cost=0.02):
    seen = []

    def review(posting, extraction, d, store):
        seen.append(d)
        return reviews[min(len(seen), len(reviews)) - 1], cost

    return review, seen


def issue(sentence, kind="overclaim", detail="says more than the evidence"):
    return loop.Issue(sentence=sentence, kind=kind, detail=detail)


# --- the gate ----------------------------------------------------------------


def test_a_clean_draft_is_accepted_in_one_round(store):
    writer, _ = scripted_writer(draft())
    reviewer, reviewed = scripted_reviewer(loop.Review())
    result = loop.run(POSTING, EXTRACTION, store, writer, reviewer)
    assert result.accepted and result.stopped == "accepted"
    assert len(result.rounds) == 1 and len(reviewed) == 1
    assert result.cost_usd == pytest.approx(0.03)


def test_a_lint_failure_goes_back_to_the_writer_without_paying_the_reviewer(store):
    bad = draft(ids=(), skills=("React", "Kubernetes"))
    writer, feedback = scripted_writer(bad, draft())
    reviewer, reviewed = scripted_reviewer(loop.Review())
    result = loop.run(POSTING, EXTRACTION, store, writer, reviewer)
    assert result.accepted and len(result.rounds) == 2
    assert not result.rounds[0].reviewed and len(reviewed) == 1
    assert feedback[0] == []
    assert any("No evidence cited" in f for f in feedback[1])
    assert any("Kubernetes" in f for f in feedback[1])


def test_an_overclaim_the_lint_cannot_see_is_sent_back(store):
    """The inflated number cites real evidence, so the lint passes it."""
    writer, feedback = scripted_writer(draft(INFLATED), draft())
    reviewer, _ = scripted_reviewer(loop.Review(issues=[issue(INFLATED)]), loop.Review())
    result = loop.run(POSTING, EXTRACTION, store, writer, reviewer)
    assert result.rounds[0].lint["passed"] and result.rounds[0].issues
    assert INFLATED in feedback[1][0] and "overclaim" in feedback[1][0]
    assert result.accepted and result.draft.sections[0].bullets[0].text == GOOD


def test_the_reviewer_cannot_approve_a_draft_that_fails_the_lint(store):
    writer, _ = scripted_writer(draft(ids=()))
    reviewer, reviewed = scripted_reviewer(loop.Review())
    result = loop.run(POSTING, EXTRACTION, store, writer, reviewer, max_rounds=2)
    assert not result.accepted and result.stopped == "max_rounds"
    assert reviewed == [] and len(result.rounds) == 2


def test_an_issue_quoting_text_that_is_not_in_the_draft_is_discarded(store):
    writer, _ = scripted_writer(draft())
    reviewer, _ = scripted_reviewer(loop.Review(issues=[issue("Led a team of 40 engineers.")]))
    result = loop.run(POSTING, EXTRACTION, store, writer, reviewer)
    assert result.accepted
    assert result.rounds[0].issues == [] and len(result.rounds[0].discarded) == 1


def test_a_missed_requirement_is_reported_but_does_not_block(store):
    writer, _ = scripted_writer(draft())
    note = issue("", kind="missed_requirement", detail="e3 shows Storybook")
    reviewer, _ = scripted_reviewer(loop.Review(issues=[note]))
    result = loop.run(POSTING, EXTRACTION, store, writer, reviewer)
    assert result.accepted and result.rounds[0].issues[0]["kind"] == "missed_requirement"


def test_it_stops_when_the_reviewer_is_never_satisfied(store):
    writer, _ = scripted_writer(draft(INFLATED))
    reviewer, _ = scripted_reviewer(loop.Review(issues=[issue(INFLATED)]))
    result = loop.run(POSTING, EXTRACTION, store, writer, reviewer, max_rounds=3)
    assert not result.accepted and result.stopped == "max_rounds" and len(result.rounds) == 3


def test_it_stops_at_the_budget(store):
    writer, _ = scripted_writer(draft(INFLATED), cost=0.30)
    reviewer, reviewed = scripted_reviewer(loop.Review(issues=[issue(INFLATED)]), cost=0.30)
    result = loop.run(POSTING, EXTRACTION, store, writer, reviewer, max_cost_usd=0.50)
    assert result.stopped == "budget" and not result.accepted
    assert len(result.rounds) == 1 and len(reviewed) == 1
    assert result.as_dict()["cost_usd"] == 0.6


# --- what each agent sees -----------------------------------------------------


def test_the_reviewer_sees_evidence_text_and_nothing_of_the_writer(store):
    message = loop.review_message(POSTING, EXTRACTION, draft(INFLATED), store)
    assert INFLATED in message
    assert "cutting page load from 4.1s to 1.6s" in message  # the evidence it cites
    assert "Unused evidence:" in message and "- e5:" in message
    assert "search_evidence" not in message and "rejected" not in message


def test_review_message_marks_an_unknown_evidence_id(store):
    assert "(no such evidence)" in loop.review_message(POSTING, None, draft(ids=("zz",)), store)


# --- the Claude writer agent, against a fake client --------------------------


def tool_use(name, tool_input, call_id):
    return SimpleNamespace(type="tool_use", name=name, input=tool_input, id=call_id)


def fake_client(*turns):
    calls = []

    def create(**kwargs):
        calls.append({**kwargs, "messages": list(kwargs["messages"])})
        content, stop = turns[len(calls) - 1]
        usage = SimpleNamespace(input_tokens=1000, output_tokens=100)
        return SimpleNamespace(content=content, stop_reason=stop, usage=usage, stop_details="x")

    return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create))), calls


def test_writer_agent_searches_then_submits_and_recovers_from_a_bad_draft(store):
    good = draft().model_dump()
    client, calls = fake_client(
        ([tool_use("search_evidence", {"query": "react"}, "t1")], "tool_use"),
        ([tool_use("read_evidence", {"ids": ["nope"]}, "t2")], "tool_use"),
        ([tool_use("submit_cv", {"summary": "not a list"}, "t3")], "tool_use"),
        ([SimpleNamespace(type="text", text="done")], "end_turn"),
        ([tool_use("submit_cv", good, "t4")], "tool_use"),
    )
    result, cost = loop.claude_writer(client=client)(POSTING, EXTRACTION, store, ["fix the number"])
    assert result == draft()
    assert cost == pytest.approx(5 * (1000 * 2.00 + 100 * 10.00) / 1_000_000)
    assert calls[0]["model"] == "claude-sonnet-5-5" and calls[0]["fallbacks"] == "default"
    assert "tool_choice" not in calls[0], "forced tool choice is rejected by this model"
    assert "fix the number" in calls[0]["messages"][0]["content"]
    search = calls[1]["messages"][-1]["content"][0]
    assert (
        search["tool_use_id"] == "t1"
        and not search["is_error"]
        and '"id": "e1"' in (search["content"])
    )
    assert calls[2]["messages"][-1]["content"][0]["is_error"], "unknown id is a tool error"
    assert "does not match the schema" in calls[3]["messages"][-1]["content"][0]["content"]
    assert calls[4]["messages"][-1]["content"] == "Call submit_cv with the finished draft."


def test_writer_agent_refusal_and_runaway_are_errors(store):
    client, _ = fake_client(([], "refusal"))
    with pytest.raises(ExtractionFailed, match="refused"):
        loop.claude_writer(client=client)(POSTING, None, store, [])
    forever = [([tool_use("search_evidence", {"query": "x"}, "t")], "tool_use")]
    client, calls = fake_client(*forever * loop.MAX_WRITER_TURNS)
    with pytest.raises(ExtractionFailed, match="did not submit"):
        loop.claude_writer(client=client)(POSTING, None, store, [])
    assert len(calls) == loop.MAX_WRITER_TURNS


def test_reviewer_agent_parses_and_prices(store):
    seen = {}

    def parse(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(
            stop_reason="end_turn",
            parsed_output=loop.Review(issues=[issue(INFLATED)]),
            usage=SimpleNamespace(input_tokens=2000, output_tokens=200),
        )

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(parse=parse)))
    review, cost = loop.claude_reviewer(client=client)(POSTING, None, draft(INFLATED), store)
    assert review.issues[0].kind == "overclaim"
    assert cost == pytest.approx((2000 * 2.00 + 200 * 10.00) / 1_000_000)
    assert seen["output_format"] is loop.Review and seen["system"] == loop.REVIEWER_SYSTEM


# --- wiring into cv.generate --------------------------------------------------


def test_the_loop_plugs_into_generate(store, tmp_path):
    writer, _ = scripted_writer(draft(INFLATED), draft())
    reviewer, _ = scripted_reviewer(loop.Review(issues=[issue(INFLATED)]), loop.Review())
    sink = []
    result = cv.generate(
        POSTING, EXTRACTION, store, loop.as_cv_writer(store, writer, reviewer, sink), tmp_path
    )
    assert result.lint.passed and sink[0].accepted and len(sink[0].rounds) == 2
    assert GOOD in (tmp_path / "cv.html").read_text(encoding="utf-8")


# --- the reviewer eval --------------------------------------------------------


def test_every_eval_case_passes_the_lint_and_changes_one_sentence(store):
    spec = loop.load_cases(EVALS / "review-cases.yaml")
    kinds = [c["kind"] for c in spec["cases"]]
    assert kinds.count("planted") == 12 and kinds.count("clean") == 8
    for case in spec["cases"]:
        d = loop.case_draft(spec, case)
        assert cv.lint(d, store, cv.visible_text(cv.render_html(d, store))).passed, case["id"]
        assert case["text"] in [s.text for s in cv._sentences(d)]


def test_eval_scores_a_perfect_and_a_silent_reviewer(store):
    spec = loop.load_cases(EVALS / "review-cases.yaml")
    planted = {c["text"] for c in spec["cases"] if c["kind"] == "planted"}

    def perfect(posting, extraction, d, store):
        hits = [issue(s.text) for s in cv._sentences(d) if s.text in planted]
        return loop.Review(issues=hits), 0.0

    report = loop.evaluate_reviewer(spec, store, perfect)
    assert report["recall"] == 1.0 and report["false_alarm_rate"] == 0.0 and not report["missed"]

    silent = loop.evaluate_reviewer(spec, store, lambda *a: (loop.Review(), 0.0))
    assert silent["recall"] == 0.0 and len(silent["missed"]) == 12

    def paranoid(posting, extraction, d, store):
        return loop.Review(issues=[issue(s.text) for s in cv._sentences(d)]), 0.0

    assert loop.evaluate_reviewer(spec, store, paranoid)["false_alarm_rate"] == 1.0


def test_eval_stops_at_its_budget(store):
    spec = loop.load_cases(EVALS / "review-cases.yaml")
    report = loop.evaluate_reviewer(spec, store, lambda *a: (loop.Review(), 0.4), max_cost_usd=1.0)
    assert report["stopped_at_budget"] and report["cases"] == 3
