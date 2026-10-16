"""Daily email digest for self-use (docs/spec.md, 每日 Email): the newest postings you can
apply to, in the domains you follow, since the last digest.

Config comes from the environment so nothing personal lands in the repo:
JOB_RADAR_COUNTRY / JOB_RADAR_UTC_OFFSET (who is applying), JOB_RADAR_CATEGORIES (comma
list of domains, empty = all), and for sending SMTP_HOST, SMTP_PORT, SMTP_USER,
SMTP_PASSWORD, DIGEST_FROM, DIGEST_TO.
"""

from __future__ import annotations

import html
import smtplib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.message import EmailMessage
from types import SimpleNamespace
from typing import Any

from .classify import CATEGORIES, is_general_application
from .eligibility import Candidate, assess
from .extract import SCHEMA_VERSION
from .store import Store

DEFAULT_LIMIT = 5


@dataclass(slots=True)
class DigestItem:
    company: str
    title: str
    category: str
    location: str | None
    url: str
    reason: str
    fit: int | None = None


def last_digest_at(store: Store) -> datetime | None:
    row = store.db.execute(
        "SELECT max(started_at) AS at FROM runs WHERE step = 'digest' AND error IS NULL"
    ).fetchone()
    return datetime.fromisoformat(row["at"]) if row and row["at"] else None


def select(
    store: Store,
    *,
    candidate: Candidate,
    since: datetime,
    categories: set[str] | None = None,
    limit: int = DEFAULT_LIMIT,
    evidence=None,
) -> tuple[list[DigestItem], int]:
    """Up to ``limit`` eligible postings first seen after ``since`` and how many matched in
    total. With an evidence store, best fit first; otherwise newest first."""
    from .cv import fit

    matched: list[DigestItem] = []
    for row in store.open_postings(work_mode="remote"):
        if row["first_seen_at"] <= since.isoformat() or is_general_application(row["title"]):
            continue
        if categories and row["category"] not in categories:
            continue
        extraction = store.latest_extraction(row["id"], SCHEMA_VERSION)
        verdict = assess(
            work_mode=row["work_mode"],
            location_text=row["location"],
            extraction=extraction,
            candidate=candidate,
        )
        if verdict.label != "eligible":
            continue
        matched.append(
            DigestItem(
                company=row["company"],
                title=row["title"],
                category=CATEGORIES.get(row["category"], row["category"]),
                location=row["location"],
                url=row["url"],
                reason="；".join(verdict.reasons),
                fit=(fit(extraction, evidence) or SimpleNamespace(score=None)).score
                if evidence
                else None,
            )
        )
    if evidence:
        # Stable sort keeps newest-first among equal scores; unscored postings go last.
        matched.sort(key=lambda item: -1 if item.fit is None else -item.fit)
    return matched[:limit], len(matched)


def render(items: list[DigestItem], total: int, now: datetime) -> tuple[str, str, str]:
    """(subject, plain text, HTML)."""
    day = now.strftime("%Y-%m-%d")
    if not items:
        subject = f"Job Radar {day}：今天沒有新的可申請職缺"
    else:
        subject = f"Job Radar {day}：{total} 個新的可申請職缺"
    lines = [subject, ""]
    for i, item in enumerate(items, 1):
        lines += [
            f"{i}. {item.company}｜{item.title}"
            + (f"（適配 {item.fit}）" if item.fit is not None else ""),
            f"   {item.category} · {item.location or '-'} · {item.reason}",
            f"   {item.url}",
        ]
    if total > len(items):
        lines += ["", f"另有 {total - len(items)} 個，請到網站查看。"]
    text = "\n".join(lines) + "\n"

    rows = "".join(
        f"<li><p><strong>{html.escape(item.company)}</strong>｜"
        f'<a href="{html.escape(item.url)}">{html.escape(item.title)}</a><br>'
        f"<small>{html.escape(item.category)} · {html.escape(item.location or '-')} · "
        f"{html.escape(item.reason)}</small></p></li>"
        for item in items
    )
    more = f"<p>另有 {total - len(items)} 個，請到網站查看。</p>" if total > len(items) else ""
    body = f"<ol>{rows}</ol>{more}" if items else "<p>今天沒有新的可申請職缺。</p>"
    return subject, text, f"<h2>{html.escape(subject)}</h2>{body}"


def send(
    subject: str, text: str, html_body: str, env: Mapping[str, str], smtp=smtplib.SMTP
) -> None:
    missing = [k for k in ("SMTP_HOST", "DIGEST_FROM", "DIGEST_TO") if not env.get(k)]
    if missing:
        raise RuntimeError(f"digest: missing {', '.join(missing)}")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = env["DIGEST_FROM"]
    message["To"] = env["DIGEST_TO"]
    message.set_content(text)
    message.add_alternative(html_body, subtype="html")
    with smtp(env["SMTP_HOST"], int(env.get("SMTP_PORT", "587"))) as server:
        server.starttls()
        if env.get("SMTP_USER"):
            server.login(env["SMTP_USER"], env.get("SMTP_PASSWORD", ""))
        server.send_message(message)


def run(
    store: Store,
    *,
    candidate: Candidate,
    categories: set[str] | None,
    now: datetime,
    env: Mapping[str, str],
    deliver: bool,
    smtp=smtplib.SMTP,
    evidence=None,
) -> dict[str, Any]:
    since = last_digest_at(store) or now - timedelta(days=1)
    items, total = select(
        store, candidate=candidate, since=since, categories=categories, evidence=evidence
    )
    subject, text, html_body = render(items, total, now)
    if deliver:
        run_id = store.start_run("digest", now)
        try:
            send(subject, text, html_body, env, smtp)
        except Exception as exc:
            store.finish_run(run_id, now, {"items": len(items)}, error=str(exc))
            raise
        store.finish_run(run_id, now, {"items": len(items), "total": total})
    return {"subject": subject, "text": text, "html": html_body, "total": total}
