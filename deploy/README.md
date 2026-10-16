# Deploy

Three pieces, each where it is allowed and cheapest (docs/spec.md, 部署計畫):

| Piece | Runs on | What it does |
| --- | --- | --- |
| CI | GitHub Actions (`.github/workflows/ci.yml`, `live.yml`) | Lint, offline tests, nightly ATS contract check |
| Daily crawl | Our own host, cron + Docker (`deploy/daily.sh`) | Crawl watched boards, export `feed.json`, publish it |
| Site | Static hosting | Reads `feed.json`; personal data stays in the visitor's browser |

The daily crawl does not run on GitHub-hosted runners: GitHub's terms limit them to
building, testing, deploying and publishing the software project, and rule out using
Actions as part of a serverless application.

## Host setup

```bash
git clone https://github.com/yinyaoqing/job-radar /opt/job-radar
docker build -t job-radar /opt/job-radar/worker
docker run --rm -v jr-data:/data job-radar companies import-remoteintech --region worldwide --region asia-pacific
docker run --rm -v jr-data:/data job-radar companies import-hn --months 2
docker run --rm -v jr-data:/data job-radar companies add ashby <org>   # boards you know
crontab -e   # add the line at the top of deploy/daily.sh
```

Publishing is a command you set, so any object store works, e.g.
`JOB_RADAR_PUBLISH_CMD='rclone copy /srv/job-radar/public r2:job-radar-feed'`.

Back up the `jr-data` volume (one SQLite file). Losing it only loses history:
the next crawl rebuilds the open postings.

## Secrets

None yet. LLM extraction (week 2) adds `ANTHROPIC_API_KEY`, kept in the host's
environment; the repo only has `.env.example`.
