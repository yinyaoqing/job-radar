"""Region trap eval (docs/spec.md, 評估): accuracy and blocked recall for one candidate.

``rules`` feeds each case's hand-written policy to the eligibility rules (offline, runs
in CI). ``live`` extracts each case's text with the LLM first, so it measures the whole
path a real posting takes; it costs API calls and needs credentials.
Targets: accuracy >= 90%, blocked recall >= 95%.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .eligibility import Candidate, assess

DEFAULT_CASES = Path(__file__).resolve().parents[3] / "evals" / "region_traps" / "cases.yaml"
TARGET_ACCURACY = 0.90
TARGET_BLOCKED_RECALL = 0.95


@dataclass(slots=True)
class Result:
    case_id: str
    trap: str
    expected: str
    got: str
    reasons: list[str]


@dataclass(slots=True)
class Report:
    mode: str
    results: list[Result] = field(default_factory=list)
    cost_usd: float = 0.0

    @property
    def accuracy(self) -> float:
        return sum(r.expected == r.got for r in self.results) / max(1, len(self.results))

    @property
    def blocked_recall(self) -> float:
        blocked = [r for r in self.results if r.expected == "blocked"]
        return sum(r.got == "blocked" for r in blocked) / max(1, len(blocked))

    @property
    def passed(self) -> bool:
        return self.accuracy >= TARGET_ACCURACY and self.blocked_recall >= TARGET_BLOCKED_RECALL

    def failures(self) -> list[Result]:
        return [r for r in self.results if r.expected != r.got]

    def confusion(self) -> Counter:
        return Counter((r.expected, r.got) for r in self.results)

    def summary(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "cases": len(self.results),
            "accuracy": round(self.accuracy, 4),
            "blocked_recall": round(self.blocked_recall, 4),
            "passed": self.passed,
            "cost_usd": round(self.cost_usd, 4),
            "failures": [
                {"id": r.case_id, "expected": r.expected, "got": r.got, "reasons": r.reasons}
                for r in self.failures()
            ],
        }


def load_cases(path: Path = DEFAULT_CASES) -> list[dict[str, Any]]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def policy_from_case(short: dict[str, Any]) -> dict[str, Any]:
    tz = short.get("tz")
    overlap = short.get("overlap")
    return {
        "type": short.get("type", "unknown"),
        "countries": short.get("countries", []),
        "regions": short.get("regions", []),
        "timezone_window_utc": {"from_utc": tz[0], "to_utc": tz[1]} if tz else None,
        "required_overlap_hours": overlap[0] if overlap else None,
        "overlap_reference_utc": overlap[1] if overlap else None,
        "quotes": [],
    }


def run_rules(cases: list[dict[str, Any]], candidate: Candidate | None = None) -> Report:
    report = Report("rules")
    for case in cases:
        extraction = {
            "location_policy": policy_from_case(case.get("policy") or {}),
            "hard_requirements": case.get("hard_requirements", []),
            "checks": {"location_verified": True},
        }
        verdict = assess(
            work_mode=case.get("work_mode", "remote"),
            location_text=case.get("location"),
            extraction=extraction,
            candidate=candidate,
        )
        report.results.append(
            Result(case["id"], case["trap"], case["expected"], verdict.label, verdict.reasons)
        )
    return report


def run_live(
    cases: list[dict[str, Any]], llm, model: str, candidate: Candidate | None = None
) -> Report:
    from .extract import ExtractionFailed, PostingInput, check_quotes

    report = Report("live")
    for case in cases:
        posting = PostingInput(
            title=case.get("title", "Software Engineer"),
            location=case.get("location"),
            department=None,
            jd_text=case["text"],
        )
        try:
            extraction, usage = llm(posting)
        except ExtractionFailed as exc:
            report.results.append(
                Result(case["id"], case["trap"], case["expected"], "error", [str(exc)])
            )
            continue
        report.cost_usd += usage.cost_usd(model)
        payload = check_quotes(extraction, posting)
        verdict = assess(
            work_mode=case.get("work_mode", "remote"),
            location_text=case.get("location"),
            extraction=payload,
            candidate=candidate,
        )
        report.results.append(
            Result(case["id"], case["trap"], case["expected"], verdict.label, verdict.reasons)
        )
    return report


WEB_FIXTURE = DEFAULT_CASES.parents[2] / "web" / "lib" / "__fixtures__" / "region-traps.json"


def web_fixture(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The region trap cases as feed postings, for web/lib/eligibility.test.ts: the site's
    port of the rules must reach the same verdicts from the same feed fields."""
    from .eligibility import policy_from_location_text
    from .export import hard_blocks

    fixture = []
    for case in cases:
        policy = policy_from_case(case.get("policy") or {})
        fixture.append(
            {
                "id": case["id"],
                "expected": case["expected"],
                "posting": {
                    "work_mode": case.get("work_mode", "remote"),
                    "location": case.get("location"),
                    "field_policy": policy_from_location_text(case.get("location")),
                    "extracted": True,
                    "location_policy": None
                    if policy["type"] == "unknown"
                    else {k: v for k, v in policy.items() if k != "quotes"},
                    "hard_blocks": hard_blocks(
                        {"hard_requirements": case.get("hard_requirements", [])}
                    ),
                },
            }
        )
    return fixture
