"""Command line entry point.

job-radar list  <ats> <org> [--remote] [--category C]  # open postings on a board
job-radar check <ats> <org> <job_id> # is this posting still open?

job-radar companies add <ats> <org> [--name NAME]
job-radar companies import-remoteintech [--probe] [--region worldwide ...]
job-radar companies list
job-radar crawl                      # fetch every watched board, open/close postings
job-radar postings [--category C] [--all-modes]  # open postings in the database
job-radar export --out feed.json     # public JSON feed (fully remote, all domains)

The database defaults to ``job-radar.db``; set ``--db`` or ``JOB_RADAR_DB``.
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
    comp.add_parser("list", help="show watched companies")

    sub.add_parser("crawl", help="fetch every watched board and update postings")

    p_postings = sub.add_parser("postings", help="open postings in the database")
    p_postings.add_argument("--category", choices=list(CATEGORIES), help="only this domain")
    p_postings.add_argument(
        "--all-modes", action="store_true", help="include hybrid and onsite postings"
    )

    p_export = sub.add_parser("export", help="write the public JSON feed")
    p_export.add_argument("--out", type=Path, default=Path("public/feed.json"))

    args = parser.parse_args(argv)
    # Windows consoles (cp950) cannot print every title character; never crash on output.
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")

    if args.command in ("list", "check"):
        return _board_command(args)

    from .store import Store

    store = Store(args.db)
    try:
        if args.command == "companies":
            return _companies_command(args, store)
        if args.command == "crawl":
            return _crawl_command(store)
        if args.command == "postings":
            return _postings_command(args, store)
        return _export_command(args, store)
    finally:
        store.close()


def _now() -> datetime:
    return datetime.now(UTC)


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
        for c in store.watched_companies():
            print(f"{c.ats}\t{c.ats_org}\t{c.name}")
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
    rows = store.open_postings(work_mode=None if args.all_modes else "remote")
    if args.category:
        rows = [r for r in rows if r["category"] == args.category]
    for r in rows:
        print(
            f"{r['company']}\t{r['title']}\t{r['category']}\t{r['work_mode']}\t"
            f"{r['location'] or '-'}\t{r['url']}"
        )
    print(f"{len(rows)} postings", file=sys.stderr)
    return 0


def _export_command(args: argparse.Namespace, store) -> int:
    from .export import write_feed

    feed = write_feed(store, args.out, _now())
    print(f"{feed['count']} open postings -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
