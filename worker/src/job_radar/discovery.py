"""Company discovery: find ATS boards worth watching.

- remoteintech/remote-jobs (ISC licensed; credit it where shown): one Markdown file per
  company with YAML frontmatter. Few careers URLs point straight at an ATS, so ``probe``
  can also try the company slug against each supported ATS board.
- HN "Ask HN: Who is hiring?": the monthly thread's top-level comments link to postings;
  ``grnh.se`` short links are resolved to their Greenhouse board.
"""

from __future__ import annotations

import html
import io
import re
import tarfile
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field

import httpx
import yaml

from .adapters import Adapter, AdapterError
from .adapters.base import USER_AGENT

TARBALL_URL = "https://codeload.github.com/remoteintech/remote-jobs/tar.gz/refs/heads/main"
SOURCE = "remoteintech"

HN_SOURCE = "hn"
HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"
HN_ITEM_URL = "https://hn.algolia.com/api/v1/items/{id}"
HN_THREAD_TITLE = "Ask HN: Who is hiring?"
SHORTLINK_HOSTS = ("grnh.se",)

ATS_URL_PATTERNS = [
    ("ashby", re.compile(r"^https?://jobs\.ashbyhq\.com/([^/?#]+)", re.I)),
    (
        "greenhouse",
        re.compile(r"^https?://(?:job-)?boards\.greenhouse\.io/embed/.*[?&]for=([^&#]+)", re.I),
    ),
    ("greenhouse", re.compile(r"^https?://(?:job-)?boards\.greenhouse\.io/([^/?#]+)", re.I)),
    ("lever", re.compile(r"^https?://jobs\.lever\.co/([^/?#]+)", re.I)),
    ("recruitee", re.compile(r"^https?://([a-z0-9-]+)\.recruitee\.com", re.I)),
    ("workable", re.compile(r"^https?://apply\.workable\.com/(?!j/|api/)([^/?#]+)", re.I)),
    ("workable", re.compile(r"^https?://(?!apply\.|www\.)([a-z0-9-]+)\.workable\.com", re.I)),
]
# Ashby boards are case-sensitive and usually match the slug; try cheaper hosts first.
PROBE_ORDER = ["greenhouse", "lever", "ashby", "recruitee", "workable"]


@dataclass(slots=True)
class ListedCompany:
    slug: str
    name: str
    website: str | None = None
    careers_url: str | None = None
    region: str | None = None
    remote_policy: str | None = None
    technologies: list[str] = field(default_factory=list)


def detect_ats(url: str | None) -> tuple[str, str] | None:
    """``(ats, org)`` when a careers URL is an ATS board we support."""
    if not url:
        return None
    for ats, pattern in ATS_URL_PATTERNS:
        if m := pattern.match(url.strip()):
            org = m.group(1)
            if ats == "greenhouse" and org == "embed":
                continue
            return ats, org
    return None


def parse_company(slug: str, markdown: str) -> ListedCompany | None:
    if not markdown.startswith("---"):
        return None
    try:
        _, front, _ = markdown.split("---", 2)
        meta = yaml.safe_load(front) or {}
    except (ValueError, yaml.YAMLError):
        return None
    return ListedCompany(
        slug=str(meta.get("slug") or slug),
        name=str(meta.get("title") or slug),
        website=meta.get("website"),
        careers_url=meta.get("careers_url"),
        region=meta.get("region"),
        remote_policy=meta.get("remote_policy"),
        technologies=[str(t) for t in meta.get("technologies") or []],
    )


def read_tarball(data: bytes) -> Iterator[ListedCompany]:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar:
            parts = member.name.split("/")
            if not member.isfile() or parts[-3:-1] != ["src", "companies"]:
                continue
            if not parts[-1].endswith(".md"):
                continue
            fh = tar.extractfile(member)
            if fh is None:
                continue
            company = parse_company(parts[-1][:-3], fh.read().decode("utf-8", "replace"))
            if company:
                yield company


def fetch_remoteintech(client: httpx.Client | None = None) -> list[ListedCompany]:
    client = client or httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True
    )
    resp = client.get(TARBALL_URL)
    resp.raise_for_status()
    return list(read_tarball(resp.content))


def probe(slug: str, adapters: Mapping[str, Adapter]) -> tuple[str, str] | None:
    """Find a supported ATS board named after the slug. Costs up to one request per ATS.

    A hit can be a different company that took the same slug; probed companies are
    stored with their own ``source`` so they can be reviewed before they are trusted.
    """
    for ats in PROBE_ORDER:
        try:
            adapters[ats].list(slug)
        except (AdapterError, httpx.HTTPError, ValueError):
            continue
        return ats, slug
    return None


@dataclass(slots=True)
class HiringLead:
    company: str
    ats: str
    org: str
    url: str


def hn_threads(client: httpx.Client, months: int = 1) -> list[str]:
    """Ids of the newest monthly hiring threads, newest first."""
    resp = client.get(
        HN_SEARCH_URL,
        params={"tags": "story,author_whoishiring", "query": "who is hiring", "hitsPerPage": 20},
    )
    resp.raise_for_status()
    hits = [h for h in resp.json()["hits"] if h["title"].startswith(HN_THREAD_TITLE)]
    return [h["objectID"] for h in hits[:months]]


def parse_hn_comment(text: str) -> tuple[str, list[str]]:
    """Company name (the part before the first ``|``) and every linked URL."""
    unescaped = html.unescape(text)
    urls = re.findall(r'href="([^"]+)"', unescaped)
    plain = re.sub(r"<[^>]+>", " ", unescaped)
    company = re.sub(r"\s+", " ", plain.split("|", 1)[0]).strip()
    if len(company) > 40:
        # "Acme - we are looking for people who..." : keep the name before the pitch.
        company = re.split(r"\s+[-–—(:]\s*|,\s", company, maxsplit=1)[0]
    return company[:80], urls


def resolve_shortlink(client: httpx.Client, url: str) -> str:
    if not url.split("//", 1)[-1].startswith(SHORTLINK_HOSTS):
        return url
    try:
        resp = client.get(url, follow_redirects=False)
    except httpx.HTTPError:
        return url
    return resp.headers.get("location", url)


def harvest_hn(client: httpx.Client | None = None, months: int = 1) -> list[HiringLead]:
    """One lead per ATS board linked from the hiring threads (first mention wins)."""
    client = client or httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60)
    leads: dict[tuple[str, str], HiringLead] = {}
    for thread_id in hn_threads(client, months):
        resp = client.get(HN_ITEM_URL.format(id=thread_id))
        resp.raise_for_status()
        for comment in resp.json().get("children", []):
            company, urls = parse_hn_comment(comment.get("text") or "")
            for url in urls:
                hit = detect_ats(resolve_shortlink(client, url))
                if hit and hit not in leads:
                    leads[hit] = HiringLead(company or hit[1], *hit, url)
    return list(leads.values())
