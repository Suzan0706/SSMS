# Build from the repository root so the Phase 0 baseline (design/sql/schema.sql) is part of the image:
#   docker build -f ssms/api/Dockerfile -t ssms-api .
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY ssms/api/pyproject.toml ./
RUN pip install --upgrade pip && pip install .

COPY ssms/api/alembic.ini ./
COPY ssms/api/migrations ./migrations
COPY ssms/api/app ./app
COPY design/sql/schema.sql ./migrations/sql/0001_baseline.sql

RUN useradd --system --uid 10001 --home /app ssms && mkdir -p /data && chown ssms /data
USER ssms
ENV SSMS_STORAGE_DIR=/data

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/health/live').status != 200)"
# Behind Nginx: trust X-Forwarded-For from the proxy network only (set FORWARDED_ALLOW_IPS).
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY:-2} --proxy-headers --forwarded-allow-ips ${FORWARDED_ALLOW_IPS:-127.0.0.1}"]
