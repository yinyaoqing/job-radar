"""Daily crawl: fetch every watched board, record what is open, close what disappeared.

One thread per ATS, so hosts are fetched in parallel while each host still gets at most
one request a second (adapters share ``THROTTLE``). A failed board is logged and skipped:
its postings keep their last state rather than being closed on a network error.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

import httpx

from .adapters import ADAPTERS, Adapter, AdapterError, Posting
from .store import Company, Store


@dataclass(slots=True)
class CrawlStats:
    boards_ok: int = 0
    boards_failed: int = 0
    seen: int = 0
    new: int = 0
    changed: int = 0
    closed: int = 0
    errors: list[str] = field(default_factory=list)


def crawl(
    store: Store,
    *,
    adapter_for: Callable[[str], Adapter] = lambda ats: ADAPTERS[ats](),
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> CrawlStats:
    companies = [c for c in store.watched_companies() if c.ats in ADAPTERS]
    by_ats: dict[str, list[Company]] = defaultdict(list)
    for c in companies:
        by_ats[c.ats].append(c)

    def fetch_all(ats: str, group: list[Company]) -> list[tuple[Company, list[Posting] | str]]:
        adapter = adapter_for(ats)
        out: list[tuple[Company, list[Posting] | str]] = []
        for c in group:
            try:
                out.append((c, adapter.list(c.ats_org)))
            except (AdapterError, httpx.HTTPError, ValueError) as exc:
                out.append((c, f"{c.ats}/{c.ats_org}: {exc}"))
        return out

    run_id = store.start_run("crawl", now())
    stats = CrawlStats()
    with ThreadPoolExecutor(max_workers=max(1, len(by_ats))) as pool:
        futures = [pool.submit(fetch_all, ats, group) for ats, group in by_ats.items()]
        # Writes stay on this thread; sqlite connections are not shared across threads.
        for future in futures:
            for company, result in future.result():
                if isinstance(result, str):
                    stats.boards_failed += 1
                    stats.errors.append(result)
                    store.record_board_result(company.id, now(), result)
                    continue
                stats.boards_ok += 1
                store.record_board_result(company.id, now(), None)
                synced = store.sync_board(company.id, result, now())
                stats.seen += synced.seen
                stats.new += synced.new
                stats.changed += synced.changed
                stats.closed += synced.closed
    summary = asdict(stats)
    summary["errors"] = stats.errors[:50]
    store.finish_run(run_id, now(), summary)
    return stats
