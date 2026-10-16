"""Rule-based labels for the public feed: work mode and job domain.

No LLM here (docs/spec.md, LLM 設計: rules first). Domains are fixed slugs the site
filters on; ATS departments are free text ("Revenue", "Talent Acquisition"), so the
title is tried first and the department only when the title says nothing.
"""

from __future__ import annotations

import re

WORK_MODES = ("remote", "hybrid", "onsite", "unknown")

# Display order on the site. Labels are what the filter shows.
CATEGORIES: dict[str, str] = {
    "engineering": "工程",
    "data": "資料與分析",
    "product": "產品",
    "design": "設計",
    "marketing": "行銷",
    "sales": "業務",
    "customer": "客戶成功與支援",
    "operations": "營運",
    "finance": "財務",
    "people": "人資與招募",
    "legal": "法務與合規",
    "content": "內容與社群",
    "other": "其他",
}

# First match wins, so order settles overlaps: "Product Designer" is design,
# "Product Marketing Manager" marketing, "Solutions Engineer" sales,
# "Customer Success Engineer" customer, "IT Recruiter" people.
_RULES: list[tuple[str, str]] = [
    (
        "sales",
        r"\bsales\b|solutions? (engineer|architect|consultant)|account executive|"
        r"account manager|business development|\b[bs]dr\b|partnerships?\b|revenue\b",
    ),
    (
        "customer",
        r"customer (success|support|service|experience|care)|technical support|"
        r"support (engineer|specialist|agent|representative)|help ?desk|\bcsm\b|"
        r"implementation (manager|specialist|consultant)|client (manager|partner|success|services)",
    ),
    ("people", r"recruit|talent|\bhr\b|human resources|\bpeople\b"),
    (
        "finance",
        r"financ|accountant|accounting|controller|payroll|\btax\b|treasury|fp&a|"
        r"bookkeep|\baudit|billing",
    ),
    (
        "legal",
        r"\blegal\b|counsel|lawyer|attorney|compliance|paralegal|privacy|\baml\b|\bkyc\b",
    ),
    ("design", r"designer|\bdesign\b|\bux\b|\bui\b|user research"),
    (
        "marketing",
        r"marketing|marketer|growth(?! engineer)|\bseo\b|demand gen|\bbrand\b|"
        r"communications|\bpr\b|social media",
    ),
    (
        "data",
        r"\bdata\b|analytics|machine learning|\bml\b|scientist|statistic|"
        r"business intelligence|\bbi\b",
    ),
    (
        "product",
        r"product (manager|owner|management|lead|director|operations)|head of product|"
        r"\bvp,? (of )?product|\bproduct\b$",
    ),
    (
        "content",
        r"writer|\beditor|copywrit|\bcontent\b|translat|locali[sz]ation|community|journalis",
    ),
    (
        "engineering",
        r"engineer|developer|devops|\bsre\b|programmer|architect|security|\bqa\b|"
        r"test automation|\bit\b|sysadmin|infrastructure|software|front-?end|back-?end|"
        r"full[- ]?stack|\bmobile\b|\bios\b|android|technician",
    ),
    (
        "operations",
        r"operations|\bops\b|project (manager|lead)|program manager|chief of staff|"
        r"executive assistant|\boffice\b|administrat|logistics|supply chain|procurement|"
        r"sourcing|fulfil?lment|strategy",
    ),
    ("data", r"\banalyst\b"),
]
_COMPILED = [(cat, re.compile(rx, re.I)) for cat, rx in _RULES]

# "Don't see a role? Apply here": a talent pool, not an opening; kept out of the feed.
_GENERAL_APPLICATION = re.compile(
    r"don.?t see|general application|open application|spontaneous application|"
    r"talent (pool|community|network)|future (opportunities|openings)",
    re.I,
)

_HYBRID = re.compile(r"hybrid", re.I)
_REMOTE = re.compile(r"remote|anywhere|worldwide|distributed|work from home|\bwfh\b", re.I)


def classify(title: str, department: str | None = None) -> str:
    for text in (title, department):
        if not text:
            continue
        for category, pattern in _COMPILED:
            if pattern.search(text):
                return category
    return "other"


def is_general_application(title: str) -> bool:
    return bool(_GENERAL_APPLICATION.search(title))


def work_mode_from_text(*texts: str | None) -> str:
    """Fallback when the ATS has no structured flag: read the location text."""
    joined = " ".join(t for t in texts if t)
    if not joined.strip():
        return "unknown"
    if _HYBRID.search(joined):
        return "hybrid"
    if _REMOTE.search(joined):
        return "remote"
    return "onsite"
