#!/usr/bin/env sh
# Daily public-data run on the host: crawl every watched board, then publish the feed.
# Crontab (host in UTC): 0 23 * * * /opt/job-radar/deploy/daily.sh >> /var/log/job-radar.log 2>&1
set -eu

IMAGE="${JOB_RADAR_IMAGE:-job-radar}"
DATA="${JOB_RADAR_DATA:-jr-data}"
OUT_DIR="${JOB_RADAR_OUT:-/srv/job-radar/public}"

mkdir -p "$OUT_DIR"
docker run --rm -v "$DATA:/data" "$IMAGE" crawl
docker run --rm -v "$DATA:/data" -v "$OUT_DIR:/out" "$IMAGE" export --out /out/feed.json

# Publish: the static site reads feed.json from object storage (see deploy/README.md).
if [ -n "${JOB_RADAR_PUBLISH_CMD:-}" ]; then
  sh -c "$JOB_RADAR_PUBLISH_CMD"
fi
