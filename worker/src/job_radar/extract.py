"""LLM extraction: JD text -> the fixed JSON schema in docs/spec.md (抽取 schema).

Anti-hallucination (docs/spec.md, 防幻覺規則): every quote is string-matched against the
JD. A skill or hard requirement whose quote is not in the text is dropped; a location
policy without one matching quote is kept but marked unverified, which eligibility
treats as "unclear". ``no_ai_policy`` is never switched off by a failed check, because
a false "AI is fine" is the costly mistake.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

from .textutil import normalize, quote_in

# Bumped when the schema or the prompt changes meaning; older extractions are redone.
SCHEMA_VERSION = 2
EXTRACT_MODEL = "claude-haiku-5-5"
# USD per million tokens for prompts up to 100K tokens (docs: claude-api models table).
PRICE_PER_MTOK = {"claude-haiku-5-5": (0.10, 0.50)}

Region = Literal[
    "EU",
    "EEA",
    "EUROPE",
    "UK",
    "EMEA",
    "NORTH_AMERICA",
    "LATAM",
    "AMERICAS",
    "APAC",
    "ASIA",
    "OCEANIA",
    "AFRICA",
    "MIDDLE_EAST",
]


class TimezoneWindow(BaseModel):
    from_utc: float = Field(description="Westmost allowed UTC offset in hours, e.g. -5")
    to_utc: float = Field(description="Eastmost allowed UTC offset in hours, e.g. 3")


class LocationPolicy(BaseModel):
    type: Literal[
        "worldwide", "region_list", "country_list", "timezone_window", "onsite_hybrid", "unknown"
    ]
    countries: list[str] = Field(description="ISO-3166 alpha-2 codes the JD allows")
    regions: list[Region] = Field(description="Regions the JD allows, when it names regions")
    timezone_window_utc: TimezoneWindow | None
    required_overlap_hours: float | None = Field(
        description="Hours of daily overlap the JD requires with overlap_reference_utc"
    )
    overlap_reference_utc: float | None = Field(
        description="UTC offset of the team the overlap is with, e.g. -5 for US Eastern"
    )
    work_authorization_required: bool = Field(
        description="True when the candidate must already be allowed to work in a listed country"
    )
    quotes: list[str] = Field(description="Verbatim JD sentences this policy is based on")


class QuotedSkill(BaseModel):
    skill: str
    quote: str


class HardRequirement(BaseModel):
    type: Literal["degree", "years", "language", "clearance", "citizenship", "other"]
    value: str
    quote: str


class Salary(BaseModel):
    min: float | None
    max: float | None
    currency: str | None
    period: Literal["year", "month", "hour", "unknown"]


class ApplicationForm(BaseModel):
    no_ai_policy: bool = Field(description="True when the posting forbids AI-written answers")
    no_ai_quote: str | None
    required_links: list[Literal["github", "linkedin", "portfolio", "code_sample", "other"]]
    questions: list[str]


class Extraction(BaseModel):
    title: str
    seniority: Literal["intern", "junior", "mid", "senior", "staff", "principal", "unknown"]
    employment: Literal["full_time", "contract", "part_time", "unknown"]
    location_policy: LocationPolicy
    must_have: list[QuotedSkill]
    nice_to_have: list[QuotedSkill]
    hard_requirements: list[HardRequirement]
    salary: Salary | None
    application_form: ApplicationForm


SYSTEM_PROMPT = """You extract facts from one job posting into the given JSON schema.

Only record what the posting states. When it does not say, use "unknown", an empty list or null.
Every "quote" and every entry of "quotes" must be copied verbatim from the posting text, so a
program can find it with a substring search. Do not paraphrase, translate or join sentences.

Location policy, the field people rely on most:
- "worldwide": the posting says anyone anywhere may apply. "Remote", "remote-first" or
  "distributed team" alone does not say where you may live: that is "unknown".
- "country_list" / "region_list": it names the countries or regions candidates must be in or
  be authorised to work in. Put ISO codes in "countries" and region names in "regions".
- "timezone_window": it limits candidates to UTC offsets (e.g. "UTC-3 to UTC+3", "Americas time
  zones"). Fill timezone_window_utc. A required overlap of N hours with a team goes in
  required_overlap_hours and overlap_reference_utc.
- Convert named time zones to standard UTC offsets: Pacific/PST/PT -8, Mountain -7,
  Central/CST -6, Eastern/EST/ET -5, GMT/UK 0, CET +1, EET +2, IST (India) +5.5, SGT +8,
  JST +9, AEST +10. "US Pacific or Central time" is timezone_window_utc from -8 to -6.
- Fixed working hours ("9am-6pm PST", "must work EST business hours") are an overlap
  requirement: required_overlap_hours = the length of those hours (business hours = 8),
  overlap_reference_utc = that zone's offset.
- An overlap or working-hours requirement that does not limit where you live: type
  "worldwide" with the overlap fields filled.
- A place that implies a country ("US West Coast", "Bay Area", "South Central US") also goes
  in countries, and the type is "country_list".
- Never leave a time-zone limit without numbers: if the posting names a zone, give offsets.
- Overlap with a team or office in a named city ("our Singapore office") is an overlap
  requirement with that city's offset; on its own it does not restrict where you live, so
  use type "worldwide" unless the posting also limits location.
- "onsite_hybrid": the role needs office attendance.
- The ATS location field is given separately. If the posting text and that field disagree,
  follow the posting text and quote it.

Application form: set no_ai_policy only when the posting forbids AI-generated application
material, and quote that sentence in no_ai_quote."""


@dataclass(slots=True)
class PostingInput:
    title: str
    location: str | None
    department: str | None
    jd_text: str

    def user_message(self) -> str:
        return (
            f"Title: {self.title}\n"
            f"ATS location field: {self.location or '(none)'}\n"
            f"Department: {self.department or '(none)'}\n\n"
            f"Posting text:\n{self.jd_text}"
        )

    def source_text(self) -> str:
        return "\n".join([self.title, self.location or "", self.jd_text])


@dataclass(slots=True)
class Usage:
    input_tokens: int
    output_tokens: int

    def cost_usd(self, model: str) -> float:
        price_in, price_out = PRICE_PER_MTOK[model]
        return (self.input_tokens * price_in + self.output_tokens * price_out) / 1_000_000


class ExtractionFailed(RuntimeError):
    """The model refused or returned nothing usable; the posting stays unextracted."""


LLM = Callable[[PostingInput], tuple[Extraction, Usage]]


def claude_extractor(model: str = EXTRACT_MODEL, client: Any = None) -> LLM:
    import anthropic

    client = client or anthropic.Anthropic()

    def call(posting: PostingInput) -> tuple[Extraction, Usage]:
        response = client.messages.parse(
            model=model,
            max_tokens=8000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": posting.user_message()}],
            output_format=Extraction,
            # Fixed-schema extraction: low effort keeps thinking short on a cheap route.
            output_config={"effort": "low"},
        )
        if response.stop_reason == "refusal":
            raise ExtractionFailed(f"refused: {response.stop_details}")
        if response.stop_reason == "max_tokens" or response.parsed_output is None:
            raise ExtractionFailed(f"no parsed output (stop_reason={response.stop_reason})")
        usage = Usage(response.usage.input_tokens, response.usage.output_tokens)
        return response.parsed_output, usage

    return call


def check_quotes(extraction: Extraction, posting: PostingInput) -> dict[str, Any]:
    """Drop or flag claims whose quotes are not in the posting. Returns the payload to store."""
    source = normalize(posting.source_text())
    dropped: list[str] = []

    def keep(items: list, field: str) -> list:
        kept = []
        for item in items:
            if quote_in(item.quote, source):
                kept.append(item)
            else:
                dropped.append(f"{field}: {item.quote[:80]}")
        return kept

    extraction.must_have = keep(extraction.must_have, "must_have")
    extraction.nice_to_have = keep(extraction.nice_to_have, "nice_to_have")
    extraction.hard_requirements = keep(extraction.hard_requirements, "hard_requirements")

    policy = extraction.location_policy
    matched = [q for q in policy.quotes if quote_in(q, source)]
    dropped += [f"location_policy: {q[:80]}" for q in policy.quotes if q not in matched]
    policy.quotes = matched
    location_verified = policy.type == "unknown" or bool(matched)

    form = extraction.application_form
    no_ai_verified = not form.no_ai_policy or bool(
        form.no_ai_quote and quote_in(form.no_ai_quote, source)
    )

    payload = extraction.model_dump()
    payload["checks"] = {
        "location_verified": location_verified,
        "no_ai_verified": no_ai_verified,
        "dropped_quotes": dropped,
    }
    return payload
