"""Command line entry point.

job-radar list  <ats> <org> [--remote] [--category C]  # open postings on a board
job-radar check <ats> <org> <job_id> # is this posting still open?

job-radar companies add <ats> <org> [--name NAME]
job-radar companies import-remoteintech [--probe] [--region worldwide ...]
job-radar companies import-hn [--months N]
job-radar companies list
job-radar crawl                      # fetch every watched board, open/close postings
job-radar extract [--limit N] [--max-cost USD]  # LLM extraction of new remote postings
job-radar postings [--category C] [--eligible] [--all-modes]  # open postings in the database
job-radar eval regions [--live]      # region trap eval (rules offline; --live calls the LLM)
job-radar export --out feed.json     # public JSON feed (fully remote, all domains)

The database defaults to ``job-radar.db``; set ``--db`` or ``JOB_RADAR_DB``.
Eligibility is judged for ``JOB_RADAR_COUNTRY`` (default TW) at ``JOB_RADAR_UTC_OFFSET``
(default 8). LLM calls need Anthropic credentials (``ANTHROPIC_API_KEY``).
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from .adapters import ADAPTERS, AdapterError
from .classify import CATEGORIES, classify


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="job-radar")
    parser.add_argument("--db", default=os.environ.get("JOB_RADAR_DB", "job-radar.db"))
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="list open postings on an ATS board")
    p_list.add_argument("ats", choices=sorted(ADAPTERS))
    p_list.add_argument("org")
    p_list.add_argument("--grep", help="only titles containing this text (case-insensitive)")
    p_list.add_argument("--remote", action="store_true", help="only fully remote postings")
    p_list.add_argument("--category", choices=list(CATEGORIES), help="only this domain")

    p_check = sub.add_parser("check", help="check whether one posting is still open")
    p_check.add_argument("ats", choices=sorted(ADAPTERS))
    p_check.add_argument("org")
    p_check.add_argument("job_id")

    p_comp = sub.add_parser("companies", help="manage the watched company list")
    comp = p_comp.add_subparsers(dest="action", required=True)
    p_add = comp.add_parser("add", help="watch one company board")
    p_add.add_argument("ats", choices=sorted(ADAPTERS))
    p_add.add_argument("org")
    p_add.add_argument("--name")
    p_import = comp.add_parser("import-remoteintech", help="import remoteintech/remote-jobs")
    p_import.add_argument(
        "--probe", action="store_true", help="try each company slug against every ATS (slow)"
    )
    p_import.add_argument(
        "--region",
        action="append",
        help="only these regions (repeatable), e.g. worldwide, asia-pacific",
    )
    p_hn = comp.add_parser("import-hn", help="import boards linked from HN 'Who is hiring?'")
    p_hn.add_argument("--months", type=int, default=1, help="how many monthly threads")
    comp.add_parser("list", help="show watched companies with open/remote counts")
    comp.add_parser("reset-failures", help="crawl boards skipped after repeated failures again")

    sub.add_parser("crawl", help="fetch every watched board and update postings")

    p_postings = sub.add_parser("postings", help="open postings in the database")
    p_postings.add_argument("--category", choices=list(CATEGORIES), help="only this domain")
    p_postings.add_argument(
        "--all-modes", action="store_true", help="include hybrid and onsite postings"
    )
    p_postings.add_argument(
        "--eligible", action="store_true", help="only postings you can apply to (see below)"
    )

    p_extract = sub.add_parser("extract", help="LLM-extract new remote postings")
    p_extract.add_argument("--limit", type=int, default=200)
    p_extract.add_argument("--max-cost", type=float, default=1.0, help="USD budget for this run")
    p_extract.add_argument(
        "--retry-failed", action="store_true", help="try refused/failed postings again"
    )

    p_eval = sub.add_parser("eval", help="run an eval set")
    p_eval.add_argument("suite", choices=["regions"])
    p_eval.add_argument(
        "--live", action="store_true", help="extract with the LLM (costs API calls)"
    )
    p_eval.add_argument("--out", type=Path, help="write the report as JSON")
    p_eval.add_argument(
        "--write-web-fixture",
        action="store_true",
        help="regenerate web/lib/__fixtures__/region-traps.json from the cases",
    )

    p_export = sub.add_parser("export", help="write the public JSON feed")
    p_export.add_argument("--out", type=Path, default=Path("public/feed.json"))
    p_export.add_argument(
        "--sample",
        action="store_true",
        help="write the fictional demo feed to web/public/sample-feed.json instead",
    )

    args = parser.parse_args(argv)
    if getattr(args, "sample", False):
        return _sample_command()
    # Windows consoles (cp950) cannot print every title character; never crash on output.
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")

    if args.command in ("list", "check"):
        return _board_command(args)
    if args.command == "eval":
        return _eval_command(args)

    from .store import Store

    store = Store(args.db)
    try:
        if args.command == "companies":
            return _companies_command(args, store)
        if args.command == "crawl":
            return _crawl_command(store)
        if args.command == "postings":
            return _postings_command(args, store)
        if args.command == "extract":
            return _extract_command(args, store)
        return _export_command(args, store)
    finally:
        store.close()


def _now() -> datetime:
    return datetime.now(UTC)


def _candidate():
    from .eligibility import Candidate

    return Candidate(
        country=os.environ.get("JOB_RADAR_COUNTRY", "TW").upper(),
        utc_offset=float(os.environ.get("JOB_RADAR_UTC_OFFSET", "8")),
    )


def _board_command(args: argparse.Namespace) -> int:
    adapter = ADAPTERS[args.ats]()
    try:
        if args.command == "list":
            postings = adapter.list(args.org)
            if args.grep:
                postings = [p for p in postings if args.grep.lower() in p.title.lower()]
            if args.remote:
                postings = [p for p in postings if p.work_mode == "remote"]
            labelled = [(p, classify(p.title, p.department)) for p in postings]
            if args.category:
                labelled = [(p, c) for p, c in labelled if c == args.category]
            postings = [p for p, _ in labelled]
            for p, category in labelled:
                print(
                    f"{p.ats_job_id}\t{p.title}\t{category}\t{p.work_mode}\t"
                    f"{p.location or '-'}\t{p.url}"
                )
            print(f"{len(postings)} postings", file=sys.stderr)
        else:
            posting = adapter.get(args.org, args.job_id)
            if posting is None:
                print(f"CLOSED  {args.ats}/{args.org}/{args.job_id}")
                return 1
            print(f"OPEN    {posting.title} ({posting.location or '-'})  {posting.url}")
    except AdapterError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


def _companies_command(args: argparse.Namespace, store) -> int:
    if args.action == "add":
        _, inserted = store.add_company(
            args.name or args.org, args.ats, args.org, now=_now(), source="manual"
        )
        print("added" if inserted else "already watched")
        return 0
    if args.action == "list":
        rows = store.company_stats()
        for r in rows:
            state = f"failing x{r['fail_count']}" if r["fail_count"] else "ok"
            print(
                f"{r['ats']}\t{r['ats_org']}\t{r['name']}\t{r['source'] or '-'}\t"
                f"open {r['open_postings']}\tremote {r['remote_postings']}\t{state}"
            )
        print(f"{len(rows)} companies", file=sys.stderr)
        return 0
    if args.action == "reset-failures":
        print(f"{store.reset_failures()} boards back in the crawl")
        return 0
    if args.action == "import-hn":
        from .discovery import HN_SOURCE, harvest_hn

        leads = harvest_hn(months=args.months)
        added = 0
        for lead in leads:
            _, inserted = store.add_company(
                lead.company, lead.ats, lead.org, now=_now(), source=HN_SOURCE
            )
            added += inserted
        print(f"{len(leads)} boards linked, {added} newly watched")
        return 0

    from .discovery import SOURCE, detect_ats, fetch_remoteintech, probe

    listed = fetch_remoteintech()
    if args.region:
        listed = [c for c in listed if c.region in args.region]
    adapters = {ats: cls() for ats, cls in ADAPTERS.items()}
    added = matched = 0
    for c in listed:
        hit, source = detect_ats(c.careers_url), SOURCE
        if hit is None and args.probe:
            hit, source = probe(c.slug, adapters), f"{SOURCE}-probe"
        if hit is None:
            continue
        matched += 1
        _, inserted = store.add_company(
            c.name,
            *hit,
            now=_now(),
            source=source,
            website=c.website,
            region=c.region,
            remote_policy=c.remote_policy,
            technologies=c.technologies,
        )
        added += inserted
    print(f"{len(listed)} listed, {matched} on a supported ATS, {added} newly watched")
    return 0


def _crawl_command(store) -> int:
    from .pipeline import crawl

    stats = crawl(store)
    print(
        f"boards ok {stats.boards_ok}, failed {stats.boards_failed}; postings seen {stats.seen}, "
        f"new {stats.new}, changed {stats.changed}, closed {stats.closed}"
    )
    for err in stats.errors:
        print(f"  {err}", file=sys.stderr)
    # Partial failure is normal (a board moves ATS); only fail when nothing worked.
    return 1 if stats.boards_failed and not stats.boards_ok else 0


def _postings_command(args: argparse.Namespace, store) -> int:
    from .eligibility import assess
    from .extract import SCHEMA_VERSION

    candidate = _candidate()
    rows = store.open_postings(work_mode=None if args.all_modes else "remote")
    if args.category:
        rows = [r for r in rows if r["category"] == args.category]
    shown = 0
    for r in rows:
        verdict = assess(
            work_mode=r["work_mode"],
            location_text=r["location"],
            extraction=store.latest_extraction(r["id"], SCHEMA_VERSION),
            candidate=candidate,
        )
        if args.eligible and verdict.label != "eligible":
            continue
        shown += 1
        print(
            f"{r['company']}\t{r['title']}\t{r['category']}\t{verdict.label}\t"
            f"{r['location'] or '-'}\t{r['url']}"
        )
    print(f"{shown} postings", file=sys.stderr)
    return 0


def _extract_command(args: argparse.Namespace, store) -> int:
    from .extract import EXTRACT_MODEL, claude_extractor
    from .pipeline import extract_pending

    if args.retry_failed:
        print(f"{store.retry_failed_extractions()} failed extractions queued again")
    stats = extract_pending(
        store,
        claude_extractor(EXTRACT_MODEL),
        model=EXTRACT_MODEL,
        limit=args.limit,
        max_cost_usd=args.max_cost,
    )
    print(
        f"extracted {stats.extracted}, failed {stats.failed}, empty {stats.skipped_empty}, "
        f"cost US${stats.cost_usd:.4f}" + ("; stopped at budget" if stats.stopped_at_budget else "")
    )
    for err in stats.errors[:20]:
        print(f"  {err}", file=sys.stderr)
    return 0


def _eval_command(args: argparse.Namespace) -> int:
    import json

    from .evaluate import load_cases, run_live, run_rules

    cases = load_cases()
    if args.write_web_fixture:
        from .evaluate import WEB_FIXTURE, web_fixture

        WEB_FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        WEB_FIXTURE.write_text(
            json.dumps(web_fixture(cases), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"wrote {WEB_FIXTURE}")
    if args.live:
        from .extract import EXTRACT_MODEL, claude_extractor

        report = run_live(cases, claude_extractor(EXTRACT_MODEL), EXTRACT_MODEL, _candidate())
    else:
        report = run_rules(cases, _candidate())
    summary = report.summary()
    print(
        f"{summary['mode']}: {summary['cases']} cases, accuracy {summary['accuracy']:.1%}, "
        f"blocked recall {summary['blocked_recall']:.1%}, cost US${summary['cost_usd']:.4f} "
        f"-> {'PASS' if summary['passed'] else 'FAIL'}"
    )
    for f in summary["failures"]:
        print(f"  {f['id']}: expected {f['expected']}, got {f['got']} ({'; '.join(f['reasons'])})")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if summary["passed"] else 1


def _sample_command() -> int:
    import json

    from .sample import SAMPLE_FEED, build_sample_feed

    feed = build_sample_feed()
    SAMPLE_FEED.parent.mkdir(parents=True, exist_ok=True)
    SAMPLE_FEED.write_text(json.dumps(feed, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{feed['count']} sample postings -> {SAMPLE_FEED}")
    return 0


def _export_command(args: argparse.Namespace, store) -> int:
    from .export import write_feed

    feed = write_feed(store, args.out, _now())
    print(f"{feed['count']} open postings -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
