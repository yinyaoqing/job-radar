"""Two agents around the CV lint gate: one writes, one checks, code decides.

``cv.py`` asks the model for a CV once and lints it. The lint is deterministic and
strict about what it can see -- a sentence with no citation, an unknown evidence id, a
never-claim term, an unsupported skill -- and blind to the failure that matters most:
a sentence that cites real evidence and then says more than the evidence does
("cut load time to 1.6s" cited correctly, written as "to 0.9s"). Catching that needs
a reader, so this module adds one, and gives the writer a way to act on what the
lint and the reader report.

- The **writer** is an agent with tools over the evidence store (search, read) and one
  tool to submit a draft. It decides what to look up; a draft that does not validate
  is returned to it as a tool error.
- The **reviewer** is a separate agent with its own instructions. It sees the posting,
  the draft, and the text of the evidence each sentence cites -- never the writer's
  conversation -- and reports sentences that go beyond their evidence.
- The **gate** stays in code. A draft is accepted only when the lint passes and the
  reviewer raises nothing blocking. Neither agent can approve its own output, and a
  reviewer complaint that does not quote a sentence actually in the draft is discarded.

Only this step is multi-agent. Crawling, eligibility rules and extraction stay
deterministic or single-call on purpose: their order is fixed and their results are
checked by tests and an eval, so a model choosing the next step would add cost and
remove reproducibility for nothing.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError

from . import cv
from .cv import CvDraft, Evidence, EvidenceStore
from .extract import PRICE_PER_MTOK, ExtractionFailed

WRITER_MODEL = "claude-sonnet-5-5"
REVIEWER_MODEL = "claude-sonnet-5-5"
# USD per million tokens (input, output). Sonnet 5.5 as published on 2026-11-03.
PRICES = {**PRICE_PER_MTOK, "claude-sonnet-5-5": (2.00, 10.00)}
BETAS = ["server-side-fallback-2026-07-01"]

MAX_ROUNDS = 3
MAX_WRITER_TURNS = 12
DEFAULT_MAX_COST_USD = 0.50

BLOCKING = ("overclaim", "wrong_citation")


@dataclass(slots=True)
class Spend:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, usage: Any) -> None:
        self.input_tokens += int(getattr(usage, "input_tokens", 0) or 0)
        self.output_tokens += int(getattr(usage, "output_tokens", 0) or 0)

    @property
    def usd(self) -> float:
        price_in, price_out = PRICES[self.model]
        return (self.input_tokens * price_in + self.output_tokens * price_out) / 1_000_000


# --- review ----------------------------------------------------------------


class Issue(BaseModel):
    sentence: str = Field(description="The draft sentence, copied exactly")
    kind: Literal["overclaim", "wrong_citation", "missed_requirement"]
    detail: str = Field(description="What the sentence says that its evidence does not")


class Review(BaseModel):
    issues: list[Issue] = Field(default_factory=list)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def anchored(review: Review, draft: CvDraft) -> tuple[list[Issue], list[Issue]]:
    """Split issues into those quoting a sentence that is in the draft and the rest.

    A blocking issue must point at something. One that quotes text the draft does not
    contain cannot be acted on and may be the reviewer inventing a problem, so it is
    kept for the record and has no say in the verdict. `missed_requirement` is about
    what is absent, so it needs no anchor."""
    present = {_norm(s.text) for s in cv._sentences(draft)}
    kept, dropped = [], []
    for issue in review.issues:
        ok = issue.kind == "missed_requirement" or _norm(issue.sentence) in present
        (kept if ok else dropped).append(issue)
    return kept, dropped


# --- the loop --------------------------------------------------------------

Writer = Callable[[dict[str, Any], dict[str, Any] | None, EvidenceStore, list[str]], tuple]
Reviewer = Callable[[dict[str, Any], dict[str, Any] | None, CvDraft, EvidenceStore], tuple]


@dataclass(slots=True)
class Round:
    lint: dict[str, Any]
    issues: list[dict[str, Any]] = field(default_factory=list)
    discarded: list[dict[str, Any]] = field(default_factory=list)
    reviewed: bool = False
    cost_usd: float = 0.0


@dataclass(slots=True)
class LoopResult:
    draft: CvDraft | None
    accepted: bool
    stopped: str  # accepted | max_rounds | budget
    rounds: list[Round] = field(default_factory=list)
    cost_usd: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "stopped": self.stopped,
            "rounds": [
                {
                    "lint": r.lint,
                    "reviewed": r.reviewed,
                    "issues": r.issues,
                    "discarded": r.discarded,
                    "cost_usd": round(r.cost_usd, 4),
                }
                for r in self.rounds
            ],
            "cost_usd": round(self.cost_usd, 4),
        }


def _lint_feedback(report: cv.LintReport) -> list[str]:
    out = [f"No evidence cited for: {t!r}" for t in report.uncited]
    out += [f"Evidence id {i!r} does not exist" for i in report.unknown_ids]
    out += [f"Remove {t!r}: it is on the never-claim list" for t in report.never_claim_hits]
    out += [
        f"Skill {s!r} is not in the tags or claims of any evidence you cite"
        for s in report.unsupported_skills
    ]
    return out


def run(
    posting: dict[str, Any],
    extraction: dict[str, Any] | None,
    store: EvidenceStore,
    writer: Writer,
    reviewer: Reviewer,
    *,
    max_rounds: int = MAX_ROUNDS,
    max_cost_usd: float = DEFAULT_MAX_COST_USD,
) -> LoopResult:
    """Write, lint, review, and hand the findings back, until accepted or out of
    rounds or budget. The reviewer is only paid for once the lint passes: lint
    failures are free to detect and have to be fixed regardless."""
    result = LoopResult(draft=None, accepted=False, stopped="max_rounds")
    feedback: list[str] = []
    for _ in range(max_rounds):
        if result.cost_usd >= max_cost_usd:
            result.stopped = "budget"
            break
        draft, cost = writer(posting, extraction, store, feedback)
        result.draft = draft
        report = cv.lint(draft, store, cv.visible_text(cv.render_html(draft, store)))
        this = Round(lint=report.as_dict(), cost_usd=cost)
        result.rounds.append(this)
        result.cost_usd += cost
        if not report.passed:
            feedback = _lint_feedback(report)
            continue
        if result.cost_usd >= max_cost_usd:
            result.stopped = "budget"
            break
        review, cost = reviewer(posting, extraction, draft, store)
        kept, dropped = anchored(review, draft)
        this.reviewed = True
        this.issues = [i.model_dump() for i in kept]
        this.discarded = [i.model_dump() for i in dropped]
        this.cost_usd += cost
        result.cost_usd += cost
        if not any(i.kind in BLOCKING for i in kept):
            result.accepted = True
            result.stopped = "accepted"
            break
        feedback = [f"[{i.kind}] {i.sentence!r}: {i.detail}" for i in kept]
    return result


def as_cv_writer(
    store: EvidenceStore,
    writer: Writer,
    reviewer: Reviewer,
    sink: list[LoopResult],
    **limits: Any,
):
    """Adapt the loop to the ``writer`` argument of ``cv.generate``, which then renders,
    lints and prints as usual. The loop's record is appended to ``sink``."""

    def write(posting, extraction, _evidence: list[Evidence]) -> CvDraft:
        result = run(posting, extraction, store, writer, reviewer, **limits)
        sink.append(result)
        if result.draft is None:
            raise ExtractionFailed(f"no draft produced (stopped: {result.stopped})")
        return result.draft

    return write


# --- Claude: the writer agent ----------------------------------------------

WRITER_SYSTEM = (
    cv.SYSTEM_PROMPT
    + """

You work with tools. Use search_evidence and read_evidence to find what the posting asks
for, then call submit_cv once with the finished draft. Do not write the CV as text.
When you are given review findings, fix exactly those and resubmit; do not defend the
earlier wording."""
)

WRITER_TOOLS = [
    {
        "name": "search_evidence",
        "description": "Find evidence about a topic. Returns the best matches with id, "
        "role, tags and the full claim.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Skills or topics to look for"},
                "limit": {"type": "integer", "description": "How many to return (default 8)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_evidence",
        "description": "Read evidence entries by id, to check exact numbers and wording.",
        "input_schema": {
            "type": "object",
            "properties": {"ids": {"type": "array", "items": {"type": "string"}}},
            "required": ["ids"],
        },
    },
    {
        "name": "submit_cv",
        "description": "Submit the finished CV draft. Call this exactly once when done.",
        "input_schema": CvDraft.model_json_schema(),
    },
]


def _show(e: Evidence) -> dict[str, Any]:
    return {"id": e.id, "role": e.role, "tags": e.tags, "claim": e.claim}


def _run_tool(name: str, args: dict[str, Any], store: EvidenceStore) -> tuple[str, bool]:
    """(result text, is_error) for the two read-only tools."""
    if name == "search_evidence":
        limit = max(1, min(int(args.get("limit") or 8), 20))
        hits = cv.rank_evidence(store, [str(args.get("query", ""))], limit=limit)
        return json.dumps([_show(e) for e in hits], ensure_ascii=False), False
    if name == "read_evidence":
        ids = [str(i) for i in args.get("ids") or []]
        missing = [i for i in ids if i not in store.evidence]
        if missing:
            return f"no such evidence id: {missing}", True
        return json.dumps([_show(store.evidence[i]) for i in ids], ensure_ascii=False), False
    return f"unknown tool {name!r}", True


def _brief(posting: dict[str, Any], extraction: dict[str, Any] | None) -> str:
    must = [s["skill"] for s in (extraction or {}).get("must_have") or []]
    nice = [s["skill"] for s in (extraction or {}).get("nice_to_have") or []]
    return (
        f"Posting: {posting['title']} at {posting['company']}\n"
        f"Must have: {', '.join(must) or '(not extracted)'}\n"
        f"Nice to have: {', '.join(nice) or '(none)'}"
    )


def claude_writer(model: str = WRITER_MODEL, client: Any = None) -> Writer:
    import anthropic

    client = client or anthropic.Anthropic()

    def write(posting, extraction, store: EvidenceStore, feedback: list[str]):
        spend = Spend(model)
        content = _brief(posting, extraction)
        if feedback:
            content += "\n\nA previous draft was rejected. Findings to fix:\n" + "\n".join(
                f"- {f}" for f in feedback
            )
        messages: list[dict[str, Any]] = [{"role": "user", "content": content}]
        for _ in range(MAX_WRITER_TURNS):
            response = client.beta.messages.create(
                model=model,
                max_tokens=16000,
                system=WRITER_SYSTEM,
                tools=WRITER_TOOLS,
                messages=messages,
                output_config={"effort": "medium"},
                betas=BETAS,
                fallbacks="default",
            )
            spend.add(response.usage)
            if response.stop_reason == "refusal":
                raise ExtractionFailed(f"writer refused: {response.stop_details}")
            # The whole content goes back, thinking blocks included.
            messages.append({"role": "assistant", "content": response.content})
            calls = [b for b in response.content if b.type == "tool_use"]
            if not calls:
                messages.append(
                    {"role": "user", "content": "Call submit_cv with the finished draft."}
                )
                continue
            results = []
            for call in calls:
                if call.name == "submit_cv":
                    try:
                        return CvDraft.model_validate(call.input), spend.usd
                    except ValidationError as exc:
                        text, bad = f"draft does not match the schema: {exc}", True
                else:
                    text, bad = _run_tool(call.name, dict(call.input), store)
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": call.id,
                        "content": text,
                        "is_error": bad,
                    }
                )
            messages.append({"role": "user", "content": results})
        raise ExtractionFailed(f"writer did not submit a draft in {MAX_WRITER_TURNS} turns")

    return write


# --- Claude: the reviewer agent --------------------------------------------

REVIEWER_SYSTEM = """You check a CV draft against the evidence it cites. You did not write it.

For each sentence you are given the sentence and the full text of the evidence it cites.
Report a sentence only when it states something its cited evidence does not:

- overclaim: a number, technology, scope, seniority, team size, duration, employer or
  outcome that is absent from, or different from, the cited evidence.
- wrong_citation: the sentence is about something other than what its cited evidence says.
- missed_requirement: a must-have of the posting is supported by evidence listed under
  "Unused evidence" and the draft does not mention it. Use this sparingly.

Rewording, shortening, reordering and leaving things out are all allowed and are not
issues. Do not report style. Copy the sentence exactly into `sentence`. If every
sentence is supported, return no issues."""


def review_message(
    posting: dict[str, Any],
    extraction: dict[str, Any] | None,
    draft: CvDraft,
    store: EvidenceStore,
) -> str:
    """What the reviewer sees: the posting, each sentence with its evidence, and the
    evidence the draft left out. Nothing from the writer's conversation."""
    lines = [_brief(posting, extraction), "", "Draft sentences:"]
    cited: set[str] = set()
    for n, s in enumerate(cv._sentences(draft), start=1):
        lines.append(f"{n}. {s.text}")
        for eid in s.evidence_ids:
            cited.add(eid)
            e = store.evidence.get(eid)
            lines.append(f"   evidence {eid}: {e.claim if e else '(no such evidence)'}")
    lines.append("")
    lines.append(f"Skills line: {', '.join(draft.skills)}")
    unused = [e for e in store.evidence.values() if e.id not in cited]
    if unused:
        lines += ["", "Unused evidence:"] + [f"- {e.id}: {e.claim}" for e in unused]
    return "\n".join(lines)


def claude_reviewer(model: str = REVIEWER_MODEL, client: Any = None) -> Reviewer:
    import anthropic

    client = client or anthropic.Anthropic()

    def review(posting, extraction, draft: CvDraft, store: EvidenceStore):
        spend = Spend(model)
        response = client.beta.messages.parse(
            model=model,
            max_tokens=8000,
            system=REVIEWER_SYSTEM,
            messages=[
                {"role": "user", "content": review_message(posting, extraction, draft, store)}
            ],
            output_format=Review,
            output_config={"effort": "medium"},
            betas=BETAS,
            fallbacks="default",
        )
        spend.add(response.usage)
        if response.stop_reason == "refusal":
            raise ExtractionFailed(f"reviewer refused: {response.stop_details}")
        if response.parsed_output is None:
            raise ExtractionFailed(f"no review (stop_reason={response.stop_reason})")
        return response.parsed_output, spend.usd

    return review


# --- eval: does the reviewer catch what the lint cannot? ---------------------


def load_cases(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def case_draft(spec: dict[str, Any], case: dict[str, Any]) -> CvDraft:
    """The base draft with one bullet replaced by the case's sentence."""
    base = json.loads(json.dumps(spec["base_draft"]))
    section, index = case.get("replace", [0, 0])
    base["sections"][section]["bullets"][index] = {
        "text": case["text"],
        "evidence_ids": case["evidence_ids"],
    }
    return CvDraft.model_validate(base)


def evaluate_reviewer(
    spec: dict[str, Any],
    store: EvidenceStore,
    reviewer: Reviewer,
    *,
    max_cost_usd: float = 1.0,
) -> dict[str, Any]:
    """Run the reviewer over drafts that all pass the lint. `planted` cases hide one
    sentence that says more than its evidence; `clean` cases are faithful rewordings.

    - recall: planted cases where a blocking issue is anchored on the planted sentence.
    - false_alarm_rate: clean cases with any anchored blocking issue.
    """
    posting, extraction = spec["posting"], spec.get("extraction")
    rows, cost, stopped = [], 0.0, False
    for case in spec["cases"]:
        if cost >= max_cost_usd:
            stopped = True
            break
        draft = case_draft(spec, case)
        report = cv.lint(draft, store, cv.visible_text(cv.render_html(draft, store)))
        if not report.passed:
            raise ValueError(f"case {case['id']} must pass the lint: {report.as_dict()}")
        review, spent = reviewer(posting, extraction, draft, store)
        cost += spent
        kept, _ = anchored(review, draft)
        blocking = [i for i in kept if i.kind in BLOCKING]
        on_target = [i for i in blocking if _norm(i.sentence) == _norm(case["text"])]
        rows.append(
            {
                "id": case["id"],
                "kind": case["kind"],
                "defect": case.get("defect"),
                "caught": bool(on_target),
                "flagged": [i.sentence for i in blocking],
            }
        )
    planted = [r for r in rows if r["kind"] == "planted"]
    clean = [r for r in rows if r["kind"] == "clean"]
    return {
        "cases": len(rows),
        "planted": len(planted),
        "clean": len(clean),
        "recall": round(sum(r["caught"] for r in planted) / len(planted), 4) if planted else None,
        "false_alarm_rate": round(sum(bool(r["flagged"]) for r in clean) / len(clean), 4)
        if clean
        else None,
        "missed": [r["id"] for r in planted if not r["caught"]],
        "false_alarms": [r["id"] for r in clean if r["flagged"]],
        "cost_usd": round(cost, 4),
        "stopped_at_budget": stopped,
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    """``python -m job_radar.cv_loop <cases.yaml> <evidence.yaml> [--max-cost N] [--out F]``

    Calls the API. The cost is capped by --max-cost (default US$1)."""
    import argparse

    parser = argparse.ArgumentParser(description="Reviewer eval on planted overclaims")
    parser.add_argument("cases", type=Path)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--max-cost", type=float, default=1.0)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    report = evaluate_reviewer(
        load_cases(args.cases),
        EvidenceStore.load(args.evidence),
        claude_reviewer(),
        max_cost_usd=args.max_cost,
    )
    report["model"] = REVIEWER_MODEL
    if args.out:
        args.out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
