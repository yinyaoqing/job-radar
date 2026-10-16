"""Tailored CV drafts and application notes (docs/spec.md, 客製 CV 草稿, 申請筆記).

Rules (CLAUDE.md): a CV may only state facts from the evidence store, each sentence
cites evidence ids, and nothing on the never-claim list may appear. The model chooses
and rewords evidence; this module assembles the HTML and lints the result. The
evidence store is a YAML file the owner keeps in ``private/`` (see
evals/cv/example-evidence.yaml for the format, with a fictional person).

Application notes never contain drafted answers: when a form forbids AI, only the
question list is produced, and otherwise only questions plus matching evidence.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

CV_MODEL = "claude-sonnet-5-5"
MAX_EVIDENCE = 20


# --- evidence store --------------------------------------------------------


@dataclass(slots=True)
class Evidence:
    id: str
    claim: str
    tags: list[str]
    source: str | None = None
    role: str | None = None


@dataclass(slots=True)
class EvidenceStore:
    profile: dict[str, Any]
    evidence: dict[str, Evidence]
    never_claim: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> EvidenceStore:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        items = {}
        for raw in data.get("evidence") or []:
            item = Evidence(
                id=str(raw["id"]),
                claim=str(raw["claim"]),
                tags=[str(t) for t in raw.get("tags") or []],
                source=raw.get("source"),
                role=raw.get("role"),
            )
            if item.id in items:
                raise ValueError(f"duplicate evidence id {item.id!r}")
            items[item.id] = item
        return cls(
            profile=data.get("profile") or {},
            evidence=items,
            never_claim=[str(t) for t in data.get("never_claim") or []],
        )


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9+#.]+", text.lower()) if len(w) > 1}


def rank_evidence(
    store: EvidenceStore, requirements: list[str], limit: int = MAX_EVIDENCE
) -> list[Evidence]:
    """Evidence sharing the most words with the posting's requirements (tags count double).
    Keyword overlap stands in for the spec's embedding search until the store is big."""
    wanted = _words(" ".join(requirements))

    def score(e: Evidence) -> int:
        return 2 * len(_words(" ".join(e.tags)) & wanted) + len(_words(e.claim) & wanted)

    ranked = sorted(store.evidence.values(), key=lambda e: (-score(e), e.id))
    return ranked[:limit]


# --- LLM draft -------------------------------------------------------------


class CitedSentence(BaseModel):
    text: str
    evidence_ids: list[str] = Field(description="Ids of the evidence this sentence states")


class RoleSection(BaseModel):
    role: str = Field(description="Role heading exactly as given in the evidence")
    bullets: list[CitedSentence]


class CvDraft(BaseModel):
    summary: list[CitedSentence] = Field(description="Two or three sentences")
    sections: list[RoleSection]
    skills: list[str] = Field(description="Only skills named in the cited evidence tags or claims")


SYSTEM_PROMPT = """You tailor a CV to one job posting using only the evidence list provided.

Rules:
- Every sentence states facts from the evidence it cites in evidence_ids. Do not add numbers,
  technologies, employers, titles or outcomes that the cited evidence does not contain.
- You may shorten and reorder evidence, and lead with what the posting asks for.
- Group bullets under the evidence's own "role" headings.
- Skills must appear in the tags or claims of evidence you cite.
- If the posting asks for something the evidence does not show, leave it out; the gap is
  reported separately. Never fill a gap."""


def _user_message(
    posting: dict[str, Any], extraction: dict[str, Any] | None, evidence: list[Evidence]
) -> str:
    must = [s["skill"] for s in (extraction or {}).get("must_have") or []]
    nice = [s["skill"] for s in (extraction or {}).get("nice_to_have") or []]
    lines = [
        f"Posting: {posting['title']} at {posting['company']}",
        f"Must have: {', '.join(must) or '(not extracted)'}",
        f"Nice to have: {', '.join(nice) or '(none)'}",
        "",
        "Evidence:",
    ]
    lines += [
        f"- id={e.id} role={e.role or '-'} tags={','.join(e.tags)} :: {e.claim}" for e in evidence
    ]
    return "\n".join(lines)


def claude_writer(model: str = CV_MODEL, client: Any = None):
    import anthropic

    from .extract import ExtractionFailed

    client = client or anthropic.Anthropic()

    def write(
        posting: dict[str, Any], extraction: dict[str, Any] | None, evidence: list[Evidence]
    ) -> CvDraft:
        response = client.beta.messages.parse(
            model=model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _user_message(posting, extraction, evidence)}],
            output_format=CvDraft,
            # Server-side fallback: a classifier decline is retried on the recommended model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if response.stop_reason == "refusal":
            raise ExtractionFailed(f"refused: {response.stop_details}")
        if response.parsed_output is None:
            raise ExtractionFailed(f"no CV draft (stop_reason={response.stop_reason})")
        return response.parsed_output

    return write


# --- lint ------------------------------------------------------------------


@dataclass(slots=True)
class LintReport:
    uncited: list[str] = field(default_factory=list)
    unknown_ids: list[str] = field(default_factory=list)
    never_claim_hits: list[str] = field(default_factory=list)
    unsupported_skills: list[str] = field(default_factory=list)
    pages: int | None = None
    page_target: int = 2

    @property
    def passed(self) -> bool:
        return not (
            self.uncited
            or self.unknown_ids
            or self.never_claim_hits
            or self.unsupported_skills
            or (self.pages is not None and self.pages > self.page_target)
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "uncited": self.uncited,
            "unknown_ids": self.unknown_ids,
            "never_claim_hits": self.never_claim_hits,
            "unsupported_skills": self.unsupported_skills,
            "pages": self.pages,
        }


def _sentences(draft: CvDraft) -> list[CitedSentence]:
    return list(draft.summary) + [b for s in draft.sections for b in s.bullets]


def lint(
    draft: CvDraft, store: EvidenceStore, rendered_text: str, pages: int | None = None
) -> LintReport:
    report = LintReport(pages=pages)
    cited: set[str] = set()
    for sentence in _sentences(draft):
        if not sentence.evidence_ids:
            report.uncited.append(sentence.text)
        for eid in sentence.evidence_ids:
            if eid in store.evidence:
                cited.add(eid)
            elif eid not in report.unknown_ids:
                report.unknown_ids.append(eid)
    lowered = rendered_text.lower()
    for term in store.never_claim:
        if re.search(rf"(?<![a-z0-9]){re.escape(term.lower())}(?![a-z0-9])", lowered):
            report.never_claim_hits.append(term)
    support = " ".join(
        " ".join(store.evidence[eid].tags) + " " + store.evidence[eid].claim for eid in cited
    ).lower()
    for skill in draft.skills:
        if not re.search(rf"(?<![a-z0-9]){re.escape(skill.lower())}(?![a-z0-9])", support):
            report.unsupported_skills.append(skill)
    return report


# --- HTML ------------------------------------------------------------------

_STYLE = """
@page { size: A4; margin: 16mm 16mm; }
body { font-family: "Noto Sans TC", "Helvetica Neue", Arial, sans-serif; font-size: 10.5pt;
       line-height: 1.45; color: #1f2328; margin: 0; }
h1 { font-size: 20pt; margin: 0; } h2 { font-size: 12pt; margin: 14pt 0 4pt;
     border-bottom: 1px solid #d0d7de; padding-bottom: 2pt; }
h3 { font-size: 10.5pt; margin: 8pt 0 2pt; } ul { margin: 0; padding-left: 14pt; }
.contact { color: #57606a; margin-top: 2pt; } .skills { margin: 0; }
"""


def render_html(draft: CvDraft, store: EvidenceStore) -> str:
    p = store.profile
    esc = html.escape
    contact = " · ".join(esc(str(p[k])) for k in ("email", "location", "website") if p.get(k))
    links = " · ".join(esc(str(link)) for link in p.get("links") or [])
    parts = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        f"<title>{esc(str(p.get('name', 'CV')))}</title><style>{_STYLE}</style></head><body>",
        f"<h1>{esc(str(p.get('name', '')))}</h1>",
        f"<p class='contact'>{esc(str(p.get('headline', '')))}</p>",
        f"<p class='contact'>{contact}{' · ' + links if links else ''}</p>",
        "<h2>Summary</h2>",
        "<p>"
        + " ".join(
            f"<span data-evidence='{esc(','.join(s.evidence_ids))}'>{esc(s.text)}</span>"
            for s in draft.summary
        )
        + "</p>",
        "<h2>Experience</h2>",
    ]
    for section in draft.sections:
        parts.append(f"<h3>{esc(section.role)}</h3><ul>")
        parts += [
            f"<li data-evidence='{esc(','.join(b.evidence_ids))}'>{esc(b.text)}</li>"
            for b in section.bullets
        ]
        parts.append("</ul>")
    if draft.skills:
        parts.append(f"<h2>Skills</h2><p class='skills'>{esc(', '.join(draft.skills))}</p>")
    for extra in p.get("education") or []:
        parts.append(f"<h2>Education</h2><p>{esc(str(extra))}</p>")
    parts.append("</body></html>")
    return "".join(parts)


def visible_text(page: str) -> str:
    return html.unescape(re.sub(r"<style.*?</style>|<[^>]+>", " ", page, flags=re.S))


def count_pdf_pages(pdf: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page(?!s)", pdf))


# --- application notes -----------------------------------------------------


@dataclass(slots=True)
class RequirementMatch:
    skill: str
    must: bool
    hits: list[str]


def match_requirements(
    extraction: dict[str, Any] | None, store: EvidenceStore
) -> list[RequirementMatch]:
    """Each extracted must-have / nice-to-have with the evidence ids that mention it."""
    extraction = extraction or {}
    reqs = [(s["skill"], True) for s in extraction.get("must_have") or []]
    reqs += [(s["skill"], False) for s in extraction.get("nice_to_have") or []]
    indexed = [(e.id, _words(" ".join(e.tags) + " " + e.claim)) for e in store.evidence.values()]
    return [
        RequirementMatch(skill, must, [eid for eid, words in indexed if _words(skill) & words])
        for skill, must in reqs
    ]


@dataclass(slots=True)
class Fit:
    score: int  # 0-100: weighted share of requirements some evidence mentions
    matched: list[str]
    gaps: list[str]


def fit(extraction: dict[str, Any] | None, store: EvidenceStore) -> Fit | None:
    """Keyword fit against the evidence store (must-haves weigh 2, nice-to-haves 1).
    None when the posting has no extracted requirements to compare."""
    matches = match_requirements(extraction, store)
    if not matches:
        return None
    total = sum(2 if m.must else 1 for m in matches)
    got = sum(2 if m.must else 1 for m in matches if m.hits)
    return Fit(
        score=round(100 * got / total),
        matched=[m.skill for m in matches if m.hits],
        gaps=[m.skill for m in matches if m.must and not m.hits],
    )


def application_notes(
    posting: dict[str, Any],
    extraction: dict[str, Any] | None,
    store: EvidenceStore,
    draft: CvDraft | None,
) -> str:
    """JD <-> CV mapping, form questions and gaps, as Markdown. No answers are drafted."""
    extraction = extraction or {}
    cited = {eid for s in (_sentences(draft) if draft else []) for eid in s.evidence_ids}
    lines = [f"# {posting['company']}｜{posting['title']}", "", f"- 職缺：{posting['url']}"]
    form = extraction.get("application_form") or {}
    if form.get("no_ai_policy"):
        lines.append("- **表單禁止使用 AI**：以下只列題目，請自己作答。")
    lines += ["", "## JD 要求 ↔ 證據", "", "| 要求 | 類型 | 對應證據 |", "| --- | --- | --- |"]
    gaps = []
    for match in match_requirements(extraction, store):
        shown = ", ".join(f"{h}{'（已用於 CV）' if h in cited else ''}" for h in match.hits[:4])
        kind = "必備" if match.must else "加分"
        lines.append(f"| {match.skill} | {kind} | {shown or '—'} |")
        if not match.hits and match.must:
            gaps.append(match.skill)
    for req in extraction.get("hard_requirements") or []:
        lines.append(f"| {req.get('value')} | 硬性條件（{req.get('type')}） | 請自行確認 |")
    lines += ["", "## 缺口", ""]
    lines += [f"- {g}：證據庫沒有對應經歷，CV 不會提到。" for g in gaps] or ["- 沒有必備條件缺口。"]
    questions = form.get("questions") or []
    if questions:
        lines += ["", "## 表單題目", ""]
        lines += [f"{i}. {q}" for i, q in enumerate(questions, 1)]
    links = form.get("required_links") or []
    if links:
        lines += ["", f"必填連結：{', '.join(links)}"]
    return "\n".join(lines) + "\n"


# --- whole run -------------------------------------------------------------

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def find_chrome() -> str | None:
    import os
    import shutil

    for candidate in [os.environ.get("CHROME_PATH"), *CHROME_PATHS, shutil.which("chromium")]:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def print_pdf(html_path: Path, pdf_path: Path, chrome: str) -> bytes:
    import subprocess

    subprocess.run(
        [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_path}",
            html_path.resolve().as_uri(),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )
    return pdf_path.read_bytes()


@dataclass(slots=True)
class CvResult:
    out_dir: Path
    lint: LintReport
    evidence_used: list[str]


def generate(
    posting: dict[str, Any],
    extraction: dict[str, Any] | None,
    store: EvidenceStore,
    writer,
    out_dir: Path,
    *,
    pdf: bool = False,
) -> CvResult:
    import json

    requirements = [s["skill"] for s in (extraction or {}).get("must_have") or []]
    requirements += [s["skill"] for s in (extraction or {}).get("nice_to_have") or []]
    requirements.append(posting["title"])
    evidence = rank_evidence(store, requirements)
    draft = writer(posting, extraction, evidence)

    out_dir.mkdir(parents=True, exist_ok=True)
    page = render_html(draft, store)
    html_path = out_dir / "cv.html"
    html_path.write_text(page, encoding="utf-8")
    pages = None
    if pdf:
        chrome = find_chrome()
        if chrome is None:
            raise RuntimeError("cv: --pdf needs Chrome; set CHROME_PATH")
        pages = count_pdf_pages(print_pdf(html_path, out_dir / "cv.pdf", chrome))
    report = lint(draft, store, visible_text(page), pages)
    (out_dir / "draft.json").write_text(
        json.dumps(draft.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "lint.json").write_text(
        json.dumps(report.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "notes.md").write_text(
        application_notes(posting, extraction, store, draft), encoding="utf-8"
    )
    used = sorted({eid for s in _sentences(draft) for eid in s.evidence_ids})
    return CvResult(out_dir, report, used)
