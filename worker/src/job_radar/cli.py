"""Command line entry point.

job-radar list  <ats> <org>          # open postings on a board
job-radar check <ats> <org> <job_id> # is this posting still open?
"""

from __future__ import annotations

import argparse
import sys

from .adapters import ADAPTERS, AdapterError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="job-radar")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="list open postings on an ATS board")
    p_list.add_argument("ats", choices=sorted(ADAPTERS))
    p_list.add_argument("org")
    p_list.add_argument("--grep", help="only titles containing this text (case-insensitive)")

    p_check = sub.add_parser("check", help="check whether one posting is still open")
    p_check.add_argument("ats", choices=sorted(ADAPTERS))
    p_check.add_argument("org")
    p_check.add_argument("job_id")

    args = parser.parse_args(argv)
    # Windows consoles (cp950) cannot print every title character; never crash on output.
    sys.stdout.reconfigure(errors="replace")
    adapter = ADAPTERS[args.ats]()

    try:
        if args.command == "list":
            postings = adapter.list(args.org)
            if args.grep:
                postings = [p for p in postings if args.grep.lower() in p.title.lower()]
            for p in postings:
                print(f"{p.ats_job_id}\t{p.title}\t{p.location or '-'}\t{p.url}")
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


if __name__ == "__main__":
    raise SystemExit(main())
