"""Build a CV from a curated config instead of the LLM writer (``cv.py``).

``cv.py`` has the model choose and reword evidence. This module is the hand-curated
path: the wording is written once into a phrase book, and each posting gets a small
config naming which phrases to use, in what order, under which role headings. Both
paths end in the same ``lint`` gate, so a curated CV is held to the same rule — every
sentence cites evidence, nothing from the never-claim list appears, and it fits the
page target.

Three files, three jobs:

- ``evidence.yaml`` — the facts (what is true, with the numbers). Owned by ``cv.py``.
- ``phrases.yaml``  — the wording (one finished sentence per entry, citing evidence ids).
  A number therefore appears in exactly one phrase, so updating it rebuilds every CV
  that uses it.
- ``<posting>/cv.yaml`` — the tailoring (which phrases, what order, headings, layout).

A phrase renders as ``label`` + separator + ``text``, optionally with a ``tail`` the
config appends. That covers the three ways the same fact is normally re-pitched — a
different lead-in label, an extra closing clause, or a shorter variant stored as its
own phrase — without copying the factual body.
"""

from __future__ import annotations

import html
import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from .cv import (
    CvDraft,
    EvidenceStore,
    LintReport,
    count_pdf_pages,
    find_chrome,
    lint,
    render_html,
    visible_text,
)

# --- phrase book -----------------------------------------------------------


@dataclass(slots=True)
class Phrase:
    id: str
    cites: list[str]
    text: str
    label: str = ""


@dataclass(slots=True)
class PhraseBook:
    """Finished sentences, keyed by language then phrase id."""

    langs: dict[str, dict[str, Phrase]]

    @classmethod
    def load(cls, path: Path, store: EvidenceStore | None = None) -> PhraseBook:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        langs: dict[str, dict[str, Phrase]] = {}
        unknown: list[str] = []
        for lang, entries in data.items():
            if lang.startswith("_"):  # notes / shared anchors
                continue
            items: dict[str, Phrase] = {}
            for pid, raw in (entries or {}).items():
                cites = [str(c) for c in raw.get("cites") or []]
                if not cites:
                    raise ValueError(f"phrase {lang}/{pid} cites no evidence")
                if store is not None:
                    unknown += [f"{lang}/{pid} -> {c}" for c in cites if c not in store.evidence]
                items[str(pid)] = Phrase(
                    id=str(pid),
                    cites=cites,
                    text=str(raw["text"]),
                    label=str(raw.get("label") or ""),
                )
            langs[str(lang)] = items
        if unknown:
            raise ValueError("phrases cite unknown evidence ids: " + ", ".join(unknown))
        return cls(langs=langs)

    def get(self, lang: str, pid: str) -> Phrase:
        try:
            return self.langs[lang][pid]
        except KeyError:
            raise KeyError(f"no phrase {pid!r} for language {lang!r}") from None


# --- config ----------------------------------------------------------------


class Use(BaseModel):
    """One phrase as used by one CV. A bare string in YAML means ``{id: <string>}``."""

    id: str
    label: str | None = Field(
        default=None, description="Overrides the phrase's own label; an empty string drops it"
    )
    tail: str = Field(default="", description="Clause appended in place of the final full stop")

    @model_validator(mode="before")
    @classmethod
    def _allow_bare_id(cls, value: Any) -> Any:
        return {"id": value} if isinstance(value, str) else value


class SectionSpec(BaseModel):
    role: str
    bullets: list[Use]


class SkillGroup(BaseModel):
    """A labelled row of skills. An unnamed group renders as one plain joined line."""

    group: str = ""
    items: list[str]


class Layout(BaseModel):
    """Type-area knobs, mostly used to fit the page target. The defaults restate
    ``cv.py``'s own values, so leaving this out changes nothing that renders."""

    page_margin: str = "16mm 16mm"
    font: float = 10.5
    line: float = 1.45
    h2_margin: str = "14pt 0 4pt"
    h3_size: str = "10.5pt"
    h3_margin: str = "8pt 0 2pt"


class CvSpec(BaseModel):
    lang: Literal["zh", "en"] = "en"
    out: str = Field(default="cv", description="Output basename, e.g. cv_zh-TW")
    page_target: int = 2
    profile: dict[str, Any] = Field(default_factory=dict)
    layout: Layout = Field(default_factory=Layout)
    summary: list[Use] = Field(default_factory=list)
    sections: list[SectionSpec] = Field(default_factory=list)
    skills: list[SkillGroup] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _allow_flat_skills(cls, value: Any) -> Any:
        """``skills: [a, b, c]`` means one unnamed group, i.e. a single joined line."""
        if isinstance(value, dict):
            skills = value.get("skills")
            if isinstance(skills, list) and all(isinstance(s, str) for s in skills) and skills:
                value = {**value, "skills": [{"group": "", "items": skills}]}
        return value

    @classmethod
    def load(cls, path: Path) -> CvSpec:
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


# --- locale ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Locale:
    lang_attr: str
    sep: str
    summary: str
    experience: str
    skills: str
    education: str
    skills_join: str
    summary_as_list: bool
    font_fallback: str | None = None


LOCALES = {
    "zh": Locale(
        lang_attr="zh-Hant-TW",
        sep="：",
        summary="簡介",
        experience="經歷與專案",
        skills="技能",
        education="學歷",
        skills_join="、",
        summary_as_list=True,
        font_fallback='"Microsoft JhengHei"',
    ),
    "en": Locale(
        lang_attr="en",
        sep=": ",
        summary="Summary",
        experience="Experience",
        skills="Skills",
        education="Education",
        skills_join=", ",
        summary_as_list=False,
    ),
}


# --- resolve ---------------------------------------------------------------


def render_phrase(phrase: Phrase, use: Use, locale: Locale) -> str:
    """``label`` + separator + ``text``, with ``tail`` replacing the final full stop."""
    label = phrase.label if use.label is None else use.label
    body = phrase.text
    if use.tail:
        body = body.rstrip("。.") + use.tail
    return (label + locale.sep if label else "") + body


def resolve(spec: CvSpec, book: PhraseBook) -> CvDraft:
    """The config plus the phrase book as a ``CvDraft``, ready to render and lint."""
    locale = LOCALES[spec.lang]

    def sentence(use: Use) -> dict[str, Any]:
        phrase = book.get(spec.lang, use.id)
        return {"text": render_phrase(phrase, use, locale), "evidence_ids": list(phrase.cites)}

    return CvDraft.model_validate(
        {
            "summary": [sentence(u) for u in spec.summary],
            "sections": [
                {"role": s.role, "bullets": [sentence(u) for u in s.bullets]} for s in spec.sections
            ],
            "skills": [item for group in spec.skills for item in group.items],
        }
    )


# --- render ----------------------------------------------------------------


def _skill_rows(spec: CvSpec, locale: Locale) -> str:
    esc = html.escape
    return "".join(
        f"<p class='skills'><b>{esc(g.group)}{locale.sep.strip()}</b>"
        f"{esc(locale.skills_join.join(g.items))}</p>"
        for g in spec.skills
    )


def render(spec: CvSpec, draft: CvDraft, store: EvidenceStore) -> str:
    """``render_html`` plus this spec's locale and type-area settings."""
    locale = LOCALES[spec.lang]
    page = render_html(draft, store)
    layout = spec.layout

    if any(g.group for g in spec.skills):
        # Grouped skills: one labelled row per group, in place of the single joined line.
        rows = _skill_rows(spec, locale)
        page = re.sub(r"<p class='skills'>.*?</p>", lambda _m: rows, page, count=1, flags=re.S)

    if locale.lang_attr != "en":
        page = page.replace("<html lang='en'>", f"<html lang='{locale.lang_attr}'>")
    if locale.summary_as_list:
        page = re.sub(
            r"<h2>Summary</h2>\s*<p>(.*?)</p>",
            lambda m: (
                f"<h2>{locale.summary}</h2><ul>"
                + re.sub(r"(<span [^>]*>.*?</span>)\s*", r"<li>\1</li>", m.group(1), flags=re.S)
                + "</ul>"
            ),
            page,
            count=1,
            flags=re.S,
        )
    elif locale.summary != "Summary":
        page = page.replace("<h2>Summary</h2>", f"<h2>{locale.summary}</h2>")
    for english, translated in (
        ("Experience", locale.experience),
        ("Skills", locale.skills),
        ("Education", locale.education),
    ):
        if translated != english:
            page = page.replace(f"<h2>{english}</h2>", f"<h2>{translated}</h2>")

    page = page.replace(
        "@page { size: A4; margin: 16mm 16mm; }",
        f"@page {{ size: A4; margin: {layout.page_margin}; }}",
    )
    page = re.sub(
        r"font-size: 10.5pt;\s+line-height: 1.45;",
        f"font-size: {layout.font}pt; line-height: {layout.line};",
        page,
    )
    page = page.replace("margin: 14pt 0 4pt;", f"margin: {layout.h2_margin};")
    page = page.replace(
        "h3 { font-size: 10.5pt; margin: 8pt 0 2pt; }",
        f"h3 {{ font-size: {layout.h3_size}; margin: {layout.h3_margin}; }}",
    )
    # Keep a role heading with its first bullet rather than alone at a page foot.
    page = page.replace(
        ".skills { margin: 0; }",
        ".skills { margin: 0 0 1pt; } h3 { break-after: avoid; page-break-after: avoid; }",
    )
    if locale.font_fallback:
        page = page.replace(
            'body { font-family: "Noto Sans TC"',
            f'body {{ font-family: "Noto Sans TC", {locale.font_fallback}',
        )
    return page


# --- PDF -------------------------------------------------------------------


def print_pdf(html_path: Path, pdf_path: Path, chrome: str) -> bytes:
    """Headless Chrome needs its own profile directory here, or it writes nothing at all
    and still exits 0, so the mtime is checked rather than trusted."""
    before = pdf_path.stat().st_mtime if pdf_path.exists() else 0.0
    subprocess.run(
        [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--user-data-dir={Path(tempfile.gettempdir()) / 'job-radar-chrome-profile'}",
            f"--print-to-pdf={pdf_path.as_posix()}",
            html_path.resolve().as_uri(),
        ],
        check=True,
        capture_output=True,
        timeout=180,
    )
    if not pdf_path.exists() or pdf_path.stat().st_mtime <= before:
        raise RuntimeError(f"Chrome wrote no PDF to {pdf_path}")
    return pdf_path.read_bytes()


# --- whole build -----------------------------------------------------------

_CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿]")


def build(
    spec_path: Path,
    store: EvidenceStore,
    book: PhraseBook,
    *,
    pdf: bool = True,
) -> LintReport:
    """Build one curated CV beside its config. Writes the HTML, the PDF, ``draft.json``
    and ``lint.json``, and returns the lint report."""
    spec = CvSpec.load(spec_path)
    out_dir = spec_path.parent
    store = EvidenceStore(
        profile={**store.profile, **spec.profile},
        evidence=store.evidence,
        never_claim=store.never_claim,
    )

    draft = resolve(spec, book)
    page = render(spec, draft, store)
    html_path = out_dir / f"{spec.out}.html"
    html_path.write_text(page, encoding="utf-8")

    pages = None
    if pdf:
        chrome = find_chrome()
        if chrome is None:
            raise RuntimeError("curated: PDF output needs Chrome; set CHROME_PATH")
        pages = count_pdf_pages(print_pdf(html_path, out_dir / f"{spec.out}.pdf", chrome))

    # Language names ("華語／台語（母語）") are listed on the CV but are not evidence-backed
    # skills, so they are kept out of the unsupported-skills check.
    lint_draft = draft.model_copy(deep=True)
    lint_draft.skills = [s for s in draft.skills if not _CJK.search(s)]
    report = lint(lint_draft, store, visible_text(page), pages)
    report.page_target = spec.page_target

    (out_dir / "draft.json").write_text(
        json.dumps(draft.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "lint.json").write_text(
        json.dumps(report.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report
