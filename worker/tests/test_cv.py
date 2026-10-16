from pathlib import Path
from types import SimpleNamespace

import pytest

from job_radar import cv

EXAMPLE = Path(__file__).resolve().parents[2] / "evals" / "cv" / "example-evidence.yaml"
POSTING = {
    "title": "Senior Frontend Engineer",
    "company": "Northwind",
    "url": "https://example.com/j/1",
}
EXTRACTION = {
    "must_have": [{"skill": "React", "quote": ""}, {"skill": "GraphQL", "quote": ""}],
    "nice_to_have": [{"skill": "Playwright", "quote": ""}],
    "hard_requirements": [{"type": "years", "value": "5+ years", "quote": ""}],
    "application_form": {
        "no_ai_policy": True,
        "questions": ["Why us?"],
        "required_links": ["github"],
    },
}


@pytest.fixture
def store() -> cv.EvidenceStore:
    return cv.EvidenceStore.load(EXAMPLE)


def draft(**overrides) -> cv.CvDraft:
    base = dict(
        summary=[
            cv.CitedSentence(
                text="Frontend engineer who speeds up React apps.", evidence_ids=["e1"]
            )
        ],
        sections=[
            cv.RoleSection(
                role="Frontend Engineer, Example Commerce (2022–2026)",
                bullets=[
                    cv.CitedSentence(
                        text="Cut checkout load from 4.1s to 1.6s.", evidence_ids=["e1"]
                    ),
                    cv.CitedSentence(text="Moved 120 pages to Next.js.", evidence_ids=["e2"]),
                ],
            )
        ],
        skills=["React", "TypeScript", "Next.js"],
    )
    base.update(overrides)
    return cv.CvDraft(**base)


def test_load_rejects_duplicate_ids(tmp_path):
    path = tmp_path / "e.yaml"
    path.write_text("evidence:\n- {id: a, claim: x}\n- {id: a, claim: y}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        cv.EvidenceStore.load(path)


def test_rank_puts_matching_tags_first(store):
    ranked = cv.rank_evidence(store, ["Playwright", "testing"], limit=2)
    assert ranked[0].id == "e5"


def test_clean_draft_passes_lint(store):
    d = draft()
    page = cv.render_html(d, store)
    report = cv.lint(d, store, cv.visible_text(page), pages=2)
    assert report.passed, report.as_dict()
    assert "data-evidence='e1'" in page


def test_lint_catches_each_failure(store):
    d = draft(
        summary=[cv.CitedSentence(text="Ran Kubernetes clusters.", evidence_ids=[])],
        sections=[
            cv.RoleSection(role="X", bullets=[cv.CitedSentence(text="y", evidence_ids=["e99"])])
        ],
        skills=["React", "Go"],
    )
    report = cv.lint(d, store, cv.visible_text(cv.render_html(d, store)), pages=3)
    assert report.uncited == ["Ran Kubernetes clusters."]
    assert report.unknown_ids == ["e99"]
    assert report.never_claim_hits == ["Kubernetes"]
    # Nothing cited supports either skill ("Go" is not matched inside "Google" either).
    assert report.unsupported_skills == ["React", "Go"]
    assert not report.passed


def test_notes_list_questions_without_answers_and_report_gaps(store):
    notes = cv.application_notes(POSTING, EXTRACTION, store, draft())
    assert "表單禁止使用 AI" in notes
    assert "1. Why us?" in notes
    assert "GraphQL：證據庫沒有對應經歷" in notes
    assert "| React | 必備 | e1（已用於 CV）" in notes
    assert "必填連結：github" in notes


def test_generate_writes_files_and_lints(store, tmp_path):
    seen = {}

    def writer(posting, extraction, evidence):
        seen["evidence"] = [e.id for e in evidence]
        return draft()

    result = cv.generate(POSTING, EXTRACTION, store, writer, tmp_path / "out")
    assert result.lint.passed
    assert {p.name for p in (tmp_path / "out").iterdir()} == {
        "cv.html",
        "draft.json",
        "lint.json",
        "notes.md",
    }
    assert seen["evidence"][0] == "e1"  # React evidence ranks first for this posting


def test_claude_writer_uses_fallbacks_and_handles_refusal(store):
    calls = []

    def parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            stop_reason="refusal", stop_details="general_harms", parsed_output=None
        )

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(parse=parse)))
    from job_radar.extract import ExtractionFailed

    with pytest.raises(ExtractionFailed):
        cv.claude_writer(client=client)(POSTING, EXTRACTION, list(store.evidence.values()))
    assert calls[0]["model"] == "claude-sonnet-5-5"
    assert calls[0]["fallbacks"] == "default"
    assert "id=e1" in calls[0]["messages"][0]["content"]


def test_pdf_page_count():
    assert cv.count_pdf_pages(b"<< /Type /Pages >> << /Type /Page >> << /Type/Page >>") == 2
