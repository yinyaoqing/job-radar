"""Can this candidate apply? Rules over the extracted location policy and the ATS field.

Output is ``eligible`` / ``blocked`` / ``unclear`` with reasons (docs/spec.md, 申請資格判斷).
The ATS location field and the JD text are judged separately; when both say something
definite and disagree, the answer is ``unclear`` and both reasons are shown, never a guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

EU = {
    "AT",
    "BE",
    "BG",
    "HR",
    "CY",
    "CZ",
    "DK",
    "EE",
    "FI",
    "FR",
    "DE",
    "GR",
    "HU",
    "IE",
    "IT",
    "LV",
    "LT",
    "LU",
    "MT",
    "NL",
    "PL",
    "PT",
    "RO",
    "SK",
    "SI",
    "ES",
    "SE",
}
EUROPE = EU | {"GB", "NO", "IS", "LI", "CH", "UA", "RS", "BA", "ME", "MK", "AL", "MD", "GE", "AM"}
MIDDLE_EAST = {"AE", "SA", "QA", "BH", "KW", "OM", "IL", "JO", "LB", "TR", "EG", "IQ"}
AFRICA = {"ZA", "NG", "KE", "GH", "MA", "TN", "EG", "ET", "UG", "RW", "SN", "CI", "TZ"}
NORTH_AMERICA = {"US", "CA", "MX"}
LATAM = {
    "MX",
    "BR",
    "AR",
    "CL",
    "CO",
    "PE",
    "UY",
    "PY",
    "BO",
    "EC",
    "VE",
    "CR",
    "PA",
    "GT",
    "DO",
    "SV",
    "HN",
    "NI",
    "PR",
}
ASIA = {
    "TW",
    "JP",
    "KR",
    "CN",
    "HK",
    "MO",
    "SG",
    "MY",
    "TH",
    "VN",
    "PH",
    "ID",
    "IN",
    "PK",
    "BD",
    "LK",
    "NP",
    "KH",
    "MM",
    "LA",
    "MN",
    "KZ",
    "UZ",
}
OCEANIA = {"AU", "NZ", "FJ", "PG"}
REGIONS: dict[str, set[str]] = {
    "EU": EU,
    "EEA": EU | {"NO", "IS", "LI"},
    "EUROPE": EUROPE,
    "UK": {"GB"},
    "EMEA": EUROPE | MIDDLE_EAST | AFRICA,
    "NORTH_AMERICA": NORTH_AMERICA,
    "LATAM": LATAM,
    "AMERICAS": NORTH_AMERICA | LATAM | {"JM", "TT", "BS", "BB"},
    "APAC": ASIA | OCEANIA,
    "ASIA": ASIA,
    "OCEANIA": OCEANIA,
    "AFRICA": AFRICA,
    "MIDDLE_EAST": MIDDLE_EAST,
    "DACH": {"DE", "AT", "CH"},
    "NORDICS": {"SE", "NO", "DK", "FI", "IS"},
    "BENELUX": {"BE", "NL", "LU"},
}

# Names seen in ATS location fields. Longest first so "United States" wins over "States".
_COUNTRY_NAMES = {
    "united states": "US",
    "usa": "US",
    "us": "US",
    "u.s.": "US",
    "america": "US",
    "west coast": "US",
    "u.s.a.": "US",
    "u.s.a": "US",
    "belgium": "BE",
    "austria": "AT",
    "denmark": "DK",
    "finland": "FI",
    "norway": "NO",
    "czech republic": "CZ",
    "czechia": "CZ",
    "romania": "RO",
    "greece": "GR",
    "hungary": "HU",
    "ukraine": "UA",
    "turkey": "TR",
    "egypt": "EG",
    "pakistan": "PK",
    "bangladesh": "BD",
    "sri lanka": "LK",
    "nepal": "NP",
    "china": "CN",
    "peru": "PE",
    "uruguay": "UY",
    "costa rica": "CR",
    "the netherlands": "NL",
    # US states, regions and big cities, and Canadian provinces, as ATS fields name them.
    "alabama": "US",
    "alaska": "US",
    "arizona": "US",
    "arkansas": "US",
    "california": "US",
    "colorado": "US",
    "connecticut": "US",
    "delaware": "US",
    "florida": "US",
    "hawaii": "US",
    "idaho": "US",
    "illinois": "US",
    "indiana": "US",
    "iowa": "US",
    "kansas": "US",
    "kentucky": "US",
    "louisiana": "US",
    "maine": "US",
    "maryland": "US",
    "massachusetts": "US",
    "michigan": "US",
    "minnesota": "US",
    "mississippi": "US",
    "missouri": "US",
    "montana": "US",
    "nebraska": "US",
    "nevada": "US",
    "ohio": "US",
    "oklahoma": "US",
    "oregon": "US",
    "pennsylvania": "US",
    "tennessee": "US",
    "texas": "US",
    "utah": "US",
    "vermont": "US",
    "virginia": "US",
    "wisconsin": "US",
    "wyoming": "US",
    "new hampshire": "US",
    "new jersey": "US",
    "new mexico": "US",
    "new york": "US",
    "north carolina": "US",
    "north dakota": "US",
    "rhode island": "US",
    "south carolina": "US",
    "south dakota": "US",
    "west virginia": "US",
    "washington": "US",
    "midwest": "US",
    "pacific northwest": "US",
    "bay area": "US",
    "san francisco": "US",
    "los angeles": "US",
    "seattle": "US",
    "chicago": "US",
    "boston": "US",
    "austin": "US",
    "denver": "US",
    "ontario": "CA",
    "quebec": "CA",
    "british columbia": "CA",
    "alberta": "CA",
    "toronto": "CA",
    "vancouver": "CA",
    "montreal": "CA",
    "east coast": "US",
    "canada": "CA",
    "mexico": "MX",
    "brazil": "BR",
    "argentina": "AR",
    "colombia": "CO",
    "chile": "CL",
    "united kingdom": "GB",
    "uk": "GB",
    "england": "GB",
    "ireland": "IE",
    "germany": "DE",
    "france": "FR",
    "spain": "ES",
    "portugal": "PT",
    "italy": "IT",
    "netherlands": "NL",
    "poland": "PL",
    "sweden": "SE",
    "switzerland": "CH",
    "india": "IN",
    "japan": "JP",
    "singapore": "SG",
    "taiwan": "TW",
    "hong kong": "HK",
    "korea": "KR",
    "south korea": "KR",
    "philippines": "PH",
    "vietnam": "VN",
    "indonesia": "ID",
    "malaysia": "MY",
    "thailand": "TH",
    "australia": "AU",
    "new zealand": "NZ",
    "israel": "IL",
    "united arab emirates": "AE",
    "uae": "AE",
    "south africa": "ZA",
    "nigeria": "NG",
    "kenya": "KE",
}
_REGION_WORDS = {
    "emea": "EMEA",
    "europe": "EUROPE",
    "european union": "EU",
    "eu": "EU",
    "eea": "EEA",
    "latam": "LATAM",
    "latin america": "LATAM",
    "south america": "LATAM",
    "north america": "NORTH_AMERICA",
    "americas": "AMERICAS",
    "amer": "AMERICAS",
    "apj": "APAC",
    "apac": "APAC",
    "asia pacific": "APAC",
    "asia-pacific": "APAC",
    "asia": "ASIA",
    "oceania": "OCEANIA",
    "africa": "AFRICA",
    "middle east": "MIDDLE_EAST",
    "dach": "DACH",
    "nordics": "NORDICS",
    "nordic": "NORDICS",
    "benelux": "BENELUX",
}
_WORLDWIDE = re.compile(r"worldwide|anywhere|global(ly)?\b|any (country|location)", re.I)
# US states and Canadian provinces show up as "Remote - CA"; treat a two-letter
# uppercase token after "Remote" as US when it is a state code.
_US_STATES = set(
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH "
    "NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split()
)


@dataclass(slots=True)
class Candidate:
    country: str = "TW"
    utc_offset: float = 8.0
    # Local hours the candidate is willing to be online (start, end), 24h clock.
    available_hours: tuple[float, float] = (8.0, 23.0)

    @property
    def regions(self) -> set[str]:
        return {name for name, members in REGIONS.items() if self.country in members}


@dataclass(slots=True)
class Assessment:
    label: str  # eligible | blocked | unclear
    reasons: list[str] = field(default_factory=list)
    quotes: list[str] = field(default_factory=list)


def policy_from_location_text(text: str | None, *, strict: bool = False) -> dict[str, Any] | None:
    """A rough policy from the ATS location field, or None when it says nothing definite
    (a bare "Remote" says nothing about where). ``strict`` is for job titles: only named
    countries and regions count, not "anywhere" or two-letter state codes."""
    if not text:
        return None
    lowered = f" {text.lower()} "
    countries: set[str] = set()
    regions: set[str] = set()
    for name, region in sorted(_REGION_WORDS.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"(?<![a-z]){re.escape(name)}(?![a-z])", lowered):
            regions.add(region)
            lowered = lowered.replace(name, " ")
    for name, code in sorted(_COUNTRY_NAMES.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"(?<![a-z.]){re.escape(name)}(?![a-z])", lowered):
            countries.add(code)
            lowered = lowered.replace(name, " ")
    if not strict:
        for token in re.findall(r"\b([A-Z]{2})\b", text):
            if token in _US_STATES and re.search(r"remote", text, re.I):
                countries.add("US")
        # "Chicago, IL" / "Austin, TX"
        if any(t in _US_STATES for t in re.findall(r",\s*([A-Z]{2})\b", text)):
            countries.add("US")
    if not countries and not regions:
        if strict:
            return None
        # "Anywhere" counts only when no place is named ("Anywhere, United States" is
        # the US, not the world).
        if _WORLDWIDE.search(text):
            return {"type": "worldwide", "countries": [], "regions": []}
        return None
    return {
        "type": "country_list" if countries and not regions else "region_list",
        "countries": sorted(countries),
        "regions": sorted(regions),
    }


def _overlap_hours(candidate: Candidate, reference_utc: float) -> float:
    """Overlap between the candidate's available hours and a 09:00-17:00 day at the
    reference offset, in hours (both mapped onto the candidate's local clock)."""
    shift = candidate.utc_offset - reference_utc
    team_start, team_end = 9 + shift, 17 + shift
    start, end = candidate.available_hours
    best = 0.0
    for day in (-24, 0, 24):
        best = max(best, min(end, team_end + day) - max(start, team_start + day))
    return max(0.0, best)


def field_policy(location: str | None, title: str | None = None) -> dict[str, Any] | None:
    """What the ATS fields say about where: the location field, else places the title
    names ("Account Executive, APAC", "Customer Success Manager - US")."""
    return policy_from_location_text(location) or policy_from_location_text(title, strict=True)


def has_time_limit(policy: dict[str, Any] | None) -> bool:
    if not policy:
        return False
    window = policy.get("timezone_window_utc") or {}
    complete = window.get("from_utc") is not None and window.get("to_utc") is not None
    return complete or bool(policy.get("required_overlap_hours"))


def judge_policy(policy: dict[str, Any], candidate: Candidate) -> tuple[str, str]:
    """(label, reason) for one policy, ignoring where it came from."""
    kind = policy.get("type", "unknown")
    if kind == "onsite_hybrid":
        return "blocked", "需要進辦公室"
    if kind == "unknown" and not has_time_limit(policy):
        return "unclear", "沒有說明可申請地區"

    label, reason = "eligible", "不限地區"
    if kind in ("country_list", "region_list"):
        countries = set(policy.get("countries") or [])
        regions = set(policy.get("regions") or [])
        allowed = candidate.country in countries or bool(regions & candidate.regions)
        names = ", ".join(sorted(countries | regions))
        if not allowed:
            return "blocked", f"限 {names}"
        label, reason = "eligible", f"可申請地區包含 {candidate.country}（{names}）"

    window = policy.get("timezone_window_utc")
    if window:
        lo, hi = window.get("from_utc"), window.get("to_utc")
        if lo is not None and hi is not None:
            if not lo <= candidate.utc_offset <= hi:
                return "blocked", f"限時區 UTC{lo:+g} 到 UTC{hi:+g}"
            label, reason = (
                "eligible",
                f"時區 UTC{lo:+g} 到 UTC{hi:+g} 包含 UTC{candidate.utc_offset:+g}",
            )
        elif kind == "timezone_window":
            return "unclear", "時區範圍不完整"

    hours = policy.get("required_overlap_hours")
    reference = policy.get("overlap_reference_utc")
    weekly = bool(hours and 12 < hours <= 60)
    if weekly:
        # More than 12 hours a day is impossible: the posting meant hours per week.
        hours = hours / 5
    if hours:
        if reference is None:
            return "unclear", f"要求重疊 {hours:g} 小時，但沒說和哪個時區"
        overlap = _overlap_hours(candidate, reference)
        if overlap < hours:
            return (
                "blocked",
                f"要求與 UTC{reference:+g} 重疊 {hours:g} 小時，只能重疊 {overlap:g} 小時",
            )
        reason += f"；與 UTC{reference:+g} 可重疊 {overlap:g} 小時"
        if weekly:
            reason += "（每週時數換算成每日）"
    elif kind == "timezone_window" and not window:
        # A time-zone limit the extraction could not turn into offsets ("Pacific time",
        # "West Coast") is a limit all the same; never read it as "anywhere".
        return "unclear", "有時區限制，但沒有可判斷的範圍"
    if kind == "unknown":
        # Time limits are checked even when the extraction found no place limit, so a
        # failed overlap still blocks; passing them does not make the place known.
        return "unclear", f"沒有說明可申請地區（時區條件符合：{reason.removeprefix('不限地區；')}）"
    return label, reason


def assess(
    *,
    work_mode: str,
    location_text: str | None,
    extraction: dict[str, Any] | None,
    candidate: Candidate | None = None,
    ats_country: str | None = None,
    title: str | None = None,
) -> Assessment:
    candidate = candidate or Candidate()
    if work_mode in ("onsite", "hybrid"):
        return Assessment("blocked", ["不是全遠端"])

    from_text = field_policy(location_text, title)
    text_verdict = judge_policy(from_text, candidate) if from_text else None

    policy = (extraction or {}).get("location_policy")
    verified = ((extraction or {}).get("checks") or {}).get("location_verified", True)
    jd_verdict = None
    quotes: list[str] = []
    if policy and (policy.get("type") != "unknown" or has_time_limit(policy)) and verified:
        jd_verdict = judge_policy(policy, candidate)
        quotes = list(policy.get("quotes") or [])

    blocked_by_requirement = _hard_requirement_block(extraction, candidate)
    if blocked_by_requirement:
        return Assessment("blocked", [blocked_by_requirement], quotes)

    # "Worldwide" in the ATS field is the default many boards show; a JD that narrows it
    # is more specific, not contradictory. Only a field naming places can conflict.
    text_is_specific = bool(from_text) and from_text["type"] != "worldwide"
    if jd_verdict and text_verdict:
        disagree = jd_verdict[0] != text_verdict[0]
        if disagree and text_is_specific and "unclear" not in (jd_verdict[0], text_verdict[0]):
            return Assessment(
                "unclear",
                [
                    f"職缺內文：{jd_verdict[1]}",
                    f"ATS 地點欄位「{location_text}」：{text_verdict[1]}",
                ],
                quotes,
            )
        if jd_verdict[0] == "unclear":
            return Assessment(text_verdict[0], [text_verdict[1]], quotes)
        return Assessment(jd_verdict[0], [jd_verdict[1]], quotes)
    if jd_verdict:
        return Assessment(jd_verdict[0], [jd_verdict[1]], quotes)
    if text_verdict:
        return Assessment(text_verdict[0], [f"依 ATS 地點欄位：{text_verdict[1]}"])
    if ats_country:
        # Last resort: the ATS's structured country, often a company-wide default.
        verdict = judge_policy({"type": "country_list", "countries": [ats_country]}, candidate)
        return Assessment(verdict[0], [f"內文與地點欄位都沒寫；ATS 設定的國家：{verdict[1]}"])
    reason = "抽取的地點引文對不上原文" if policy and not verified else "沒有說明可申請地區"
    return Assessment("unclear", [reason])


def _hard_requirement_block(extraction: dict[str, Any] | None, candidate: Candidate) -> str | None:
    for req in (extraction or {}).get("hard_requirements") or []:
        if req.get("type") == "clearance":
            return f"需要安全許可：{req.get('value')}"
        if req.get("type") == "citizenship":
            # Same parsing as the feed's hard_blocks, so the site agrees with this rule.
            named = policy_from_location_text(req.get("value")) or {}
            if candidate.country not in named.get("countries", []):
                return f"需要特定國籍：{req.get('value')}"
    return None
