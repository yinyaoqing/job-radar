# Job Radar — notes for Claude

Spec: `docs/spec.md` is a de-personalised public copy of the private Claude Doc linked in README. When the doc changes, port the change by hand; never re-export it over this file.

## Rules

- `private/` holds the owner's real job-search data (shortlists, application notes). It is gitignored. Read it for context, never copy its contents into tracked files, fixtures or the public demo.
- The ATS is the source of truth for "is this posting open". Aggregators (Remote Rocketship, WWR, GitHub lists) only discover companies.
- No automatic application submission, and no drafting answers for forms that forbid AI.
- CV generation may only cite facts from the evidence store; never claim tech the owner has not used; the never-claim list lives in `private/`, not in tracked files.
- Private repos are never imported into the evidence store or linked.

## Commands

```bash
cd worker && uv sync
uv run pytest            # offline
uv run pytest -m live    # real ATS endpoints
uv run ruff check . && uv run ruff format --check .
```

## ATS quirks (verified 2026-10-15)

- Ashby: board `api.ashbyhq.com/posting-api/job-board/<org>`; single posting via `jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobPosting`, closed = `jobPosting: null`.
- Greenhouse: 404 = closed; `content` is HTML-escaped.
- Lever: 404 = closed; `createdAt` is epoch ms; `categories.allLocations` lists every location.
- Windows console is cp950: the CLI prints with `errors="replace"`.
