#!/usr/bin/env sh
# Daily run on the host: crawl every watched board, extract new remote postings,
# publish the feed, then email the digest.
# Crontab (host in UTC): 0 23 * * * /opt/job-radar/deploy/daily.sh >> /var/log/job-radar.log 2>&1
#   (23:00 UTC = 07:00 Taiwan; the digest lands before 08:00)
# Secrets live in $JOB_RADAR_ENV (default /opt/job-radar/.env), never in the repo:
#   ANTHROPIC_API_KEY, SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, DIGEST_FROM,
#   DIGEST_TO, JOB_RADAR_COUNTRY, JOB_RADAR_UTC_OFFSET, JOB_RADAR_CATEGORIES,
#   JOB_RADAR_EXTRACT_BUDGET (USD per day, default 1)
set -eu

IMAGE="${JOB_RADAR_IMAGE:-job-radar}"
DATA="${JOB_RADAR_DATA:-jr-data}"
OUT_DIR="${JOB_RADAR_OUT:-/srv/job-radar/public}"
ENV_FILE="${JOB_RADAR_ENV:-/opt/job-radar/.env}"

run() {
  if [ -f "$ENV_FILE" ]; then
    docker run --rm --env-file "$ENV_FILE" -v "$DATA:/data" "$@"
  else
    docker run --rm -v "$DATA:/data" "$@"
  fi
}
has() { [ -f "$ENV_FILE" ] && grep -q "^$1=." "$ENV_FILE"; }

mkdir -p "$OUT_DIR"
run "$IMAGE" crawl
if has ANTHROPIC_API_KEY; then
  run "$IMAGE" extract --max-cost "${JOB_RADAR_EXTRACT_BUDGET:-1}"
fi
run -v "$OUT_DIR:/out" "$IMAGE" export --out /out/feed.json

# Publish: the static site reads feed.json from object storage (see deploy/README.md).
if [ -n "${JOB_RADAR_PUBLISH_CMD:-}" ]; then
  sh -c "$JOB_RADAR_PUBLISH_CMD"
fi

if has SMTP_HOST; then
  run "$IMAGE" digest --send
fi
