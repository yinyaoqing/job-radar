# Job Radar — notes for Claude

Spec: `docs/spec.md` is a de-personalised public copy of the private Claude Doc linked in README. When the doc changes, port the change by hand; never re-export it over this file.

## Rules

- `private/` holds the owner's real job-search data (shortlists, application notes). It is gitignored. Read it for context, never copy its contents into tracked files, fixtures or the public demo.
- **This repo is public.** Commit messages, branch names and PR text are published too, so they must not name an employer, client, private repo or posting from `private/`. Describe the change, not whose data it was tested on.
- The ATS is the source of truth for "is this posting open". Aggregators (Remote Rocketship, WWR, GitHub lists) only discover companies.
- No automatic application submission, and no drafting answers for forms that forbid AI.
- CV generation may only cite facts from the evidence store; never claim tech the owner has not used; the never-claim list lives in `private/`, not in tracked files.
- A private repo is never linked from a CV, and its code never reaches a tracked file. Its
  work may be described in the evidence store only when the owner has explicitly allowed
  that repo by name; anything holding credentials or client certificates stays out entirely.

## Commands

```bash
cd worker && uv sync
uv run pytest            # offline
uv run pytest -m live    # real ATS endpoints
uv run ruff check . && uv run ruff format --check .
```

## Two ways to make a CV

Both end in the same `lint` gate — every sentence cites evidence, nothing from the
never-claim list appears, and the PDF fits the page target.

- **`cv.py`** — the model picks and rewords evidence for a posting (`job-radar cv <id>`).
- **`curated.py`** — hand-written wording, kept in a phrase book and reused across postings.
  `evidence.yaml` holds the facts, `phrases.yaml` the finished sentences and their citations,
  and each posting a small `cv.yaml` choosing phrases, order, headings and type area. Loading
  the phrase book fails on a citation to an evidence id that does not exist. Formats:
  `evals/cv/example-{evidence,phrases,cv}.yaml`, with a fictional person.

## ATS quirks (verified 2026-10-15)

- Ashby: board `api.ashbyhq.com/posting-api/job-board/<org>`; single posting via `jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobPosting`, closed = `jobPosting: null`.
- Greenhouse: 404 = closed; `content` is HTML-escaped.
- Lever: 404 = closed; `createdAt` is epoch ms; `categories.allLocations` lists every location.
- Windows console is cp950: the CLI prints with `errors="replace"`.
