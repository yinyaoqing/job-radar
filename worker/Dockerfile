# Daily crawl image: `docker run -v jr-data:/data job-radar crawl`
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

RUN useradd --create-home radar && mkdir /data && chown radar /data
USER radar
ENV JOB_RADAR_DB=/data/job-radar.db
VOLUME ["/data"]

ENTRYPOINT ["job-radar"]
CMD ["crawl"]
