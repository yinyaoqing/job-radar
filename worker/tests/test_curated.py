from pathlib import Path

import pytest
import yaml

from job_radar import curated
from job_radar.cv import EvidenceStore

EVALS = Path(__file__).resolve().parents[2] / "evals" / "cv"
EXAMPLE_EVIDENCE = EVALS / "example-evidence.yaml"
EXAMPLE_PHRASES = EVALS / "example-phrases.yaml"
EXAMPLE_CV = EVALS / "example-cv.yaml"


@pytest.fixture
def store() -> EvidenceStore:
    return EvidenceStore.load(EXAMPLE_EVIDENCE)


@pytest.fixture
def book(store: EvidenceStore) -> curated.PhraseBook:
    return curated.PhraseBook.load(EXAMPLE_PHRASES, store)


# --- phrase book -----------------------------------------------------------


def test_load_rejects_phrases_citing_unknown_evidence(store, tmp_path):
    path = tmp_path / "phrases.yaml"
    path.write_text(
        "en:\n  made-up:\n    cites: [e1, nope]\n    text: Something.\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="nope"):
        curated.PhraseBook.load(path, store)


def test_load_rejects_phrase_without_citation(store, tmp_path):
    path = tmp_path / "phrases.yaml"
    path.write_text("en:\n  bare:\n    text: Something.\n", encoding="utf-8")
    with pytest.raises(ValueError, match="cites no evidence"):
        curated.PhraseBook.load(path, store)


def test_load_without_a_store_skips_the_citation_check(tmp_path):
    path = tmp_path / "phrases.yaml"
    path.write_text("en:\n  x:\n    cites: [whatever]\n    text: Something.\n", encoding="utf-8")
    assert curated.PhraseBook.load(path).get("en", "x").cites == ["whatever"]


def test_missing_phrase_names_the_id_and_language(book):
    with pytest.raises(KeyError, match="no-such-phrase"):
        book.get("en", "no-such-phrase")


# --- label and tail --------------------------------------------------------


def test_bare_string_use_means_that_id():
    assert curated.Use.model_validate("e1").id == "e1"


def test_phrase_renders_with_its_own_label(book):
    out = curated.render_phrase(book.get("en", "e1"), curated.Use(id="e1"), curated.LOCALES["en"])
    assert out.startswith("Performance: Rebuilt the checkout flow")


def test_label_can_be_overridden_and_dropped(book):
    phrase = book.get("en", "e1")
    locale = curated.LOCALES["en"]
    assert curated.render_phrase(phrase, curated.Use(id="e1", label="Speed"), locale).startswith(
        "Speed: Rebuilt"
    )
    assert curated.render_phrase(phrase, curated.Use(id="e1", label=""), locale).startswith(
        "Rebuilt"
    )


def test_tail_replaces_the_final_full_stop(book):
    out = curated.render_phrase(
        book.get("en", "e4"), curated.Use(id="e4", tail=" — and on call."), curated.LOCALES["en"]
    )
    assert out.endswith("30k monthly users — and on call.")
    assert "users. —" not in out


def test_chinese_label_uses_the_chinese_separator(book):
    out = curated.render_phrase(book.get("zh", "e1"), curated.Use(id="e1"), curated.LOCALES["zh"])
    assert out.startswith("效能：以 React")


# --- resolve ---------------------------------------------------------------


def test_every_resolved_sentence_cites_its_phrase_evidence(book):
    spec = curated.CvSpec.load(EXAMPLE_CV)
    draft = curated.resolve(spec, book)
    assert [s.evidence_ids for s in draft.summary] == [["e1", "e2"]]
    bullets = [b for section in draft.sections for b in section.bullets]
    assert all(b.evidence_ids for b in bullets)
    assert ["e3", "e6"] in [b.evidence_ids for b in bullets]


def test_skills_groups_flatten_in_order(book):
    spec = curated.CvSpec.load(EXAMPLE_CV)
    draft = curated.resolve(spec, book)
    assert draft.skills[:2] == ["React", "Next.js"]
    assert draft.skills[-1] == "Playwright"


def test_flat_skills_list_becomes_one_unnamed_group():
    spec = curated.CvSpec.model_validate({"skills": ["React", "Vue"]})
    assert [(g.group, g.items) for g in spec.skills] == [("", ["React", "Vue"])]


# --- render ----------------------------------------------------------------


def test_english_render_keeps_headings_and_applies_the_layout(book, store):
    spec = curated.CvSpec.load(EXAMPLE_CV)
    page = curated.render(spec, curated.resolve(spec, book), store)
    assert "<h2>Summary</h2>" in page and "<h2>Experience</h2>" in page
    assert "font-size: 9.8pt; line-height: 1.36;" in page
    assert "margin: 12mm 13mm;" in page
    assert "page-break-after: avoid" in page  # role heading stays with its first bullet


def test_grouped_skills_render_as_labelled_rows(book, store):
    spec = curated.CvSpec.load(EXAMPLE_CV)
    page = curated.render(spec, curated.resolve(spec, book), store)
    assert "<b>Front end:</b>React, Next.js" in page
    assert page.count("<p class='skills'>") == 2


def test_chinese_render_translates_headings_and_lists_the_summary(book, store):
    spec = curated.CvSpec.model_validate(
        {
            "lang": "zh",
            "summary": ["e1"],
            "sections": [{"role": "前端工程師", "bullets": ["e2", "e5"]}],
            "skills": ["React"],
        }
    )
    page = curated.render(spec, curated.resolve(spec, book), store)
    assert "<html lang='zh-Hant-TW'>" in page
    assert "<h2>簡介</h2><ul><li><span" in page  # summary becomes a bullet list
    assert "<h2>經歷與專案</h2>" in page and "<h2>技能</h2>" in page
    assert "<h2>學歷</h2>" in page
    assert "Microsoft JhengHei" in page
    assert "Summary" not in page and "Experience" not in page


def test_default_layout_restates_the_stylesheet_values(book, store):
    """Omitting `layout` must not change any rendered value (only the CSS whitespace,
    since the substitution puts font size and line height on one line)."""
    spec = curated.CvSpec.model_validate({"summary": ["e1"]})
    page = curated.render(spec, curated.resolve(spec, book), store)
    assert "font-size: 10.5pt; line-height: 1.45;" in page
    assert "margin: 16mm 16mm;" in page
    assert "h3 { font-size: 10.5pt; margin: 8pt 0 2pt; }" in page


# --- build -----------------------------------------------------------------


def test_build_writes_the_outputs_and_passes_the_lint(book, store, tmp_path):
    config = tmp_path / "cv.yaml"
    config.write_text(EXAMPLE_CV.read_text(encoding="utf-8"), encoding="utf-8")
    report = curated.build(config, store, book, pdf=False)
    assert report.passed, report.as_dict()
    assert (tmp_path / "cv_en.html").exists()
    assert (tmp_path / "draft.json").exists()
    assert (tmp_path / "lint.json").exists()


def test_build_fails_the_lint_on_a_never_claim_word(store, tmp_path):
    # "Rust" is on the example store's never-claim list.
    phrases = tmp_path / "phrases.yaml"
    phrases.write_text(
        "en:\n  slip:\n    cites: [e4]\n    text: Wrote the booking APIs in Rust.\n",
        encoding="utf-8",
    )
    config = tmp_path / "cv.yaml"
    config.write_text(yaml.safe_dump({"summary": ["slip"]}), encoding="utf-8")
    report = curated.build(config, store, curated.PhraseBook.load(phrases, store), pdf=False)
    assert not report.passed
    assert report.never_claim_hits == ["Rust"]


def test_build_reports_skills_no_cited_evidence_supports(store, tmp_path):
    phrases = tmp_path / "phrases.yaml"
    phrases.write_text(
        "en:\n  ok:\n    cites: [e1]\n    text: Rebuilt checkout in React.\n", encoding="utf-8"
    )
    config = tmp_path / "cv.yaml"
    config.write_text(
        yaml.safe_dump({"summary": ["ok"], "skills": ["React", "Elixir"]}), encoding="utf-8"
    )
    report = curated.build(config, store, curated.PhraseBook.load(phrases, store), pdf=False)
    assert report.unsupported_skills == ["Elixir"]


def test_language_names_are_not_checked_as_skills(store, tmp_path):
    phrases = tmp_path / "phrases.yaml"
    phrases.write_text(
        "zh:\n  ok:\n    cites: [e1]\n    text: 以 React 重寫結帳流程。\n", encoding="utf-8"
    )
    config = tmp_path / "cv.yaml"
    config.write_text(
        yaml.safe_dump(
            {"lang": "zh", "summary": ["ok"], "skills": ["React", "華語／台語（母語）"]},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    report = curated.build(config, store, curated.PhraseBook.load(phrases, store), pdf=False)
    assert report.unsupported_skills == []
