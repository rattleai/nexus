FROM node:22-alpine AS frontend-build

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

FROM base AS deps

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY app/__init__.py app/
RUN pip install --no-cache-dir .

FROM deps AS runtime

# Run as non-root user for security
RUN addgroup --system --gid 1001 appgroup && \
    adduser --system --uid 1001 --ingroup appgroup appuser

COPY --chown=appuser:appgroup . .
COPY --from=frontend-build --chown=appuser:appgroup /app/frontend/dist ./frontend/dist

USER appuser

EXPOSE 8000

# WEB_CONCURRENCY controls the number of uvicorn worker processes.
# With deploy.replicas in docker-compose, 1-2 workers per container is typical.
ENV WEB_CONCURRENCY=1

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["curl", "-sf", "http://localhost:8000/api/v1/health/live"]

# --proxy-headers: trust X-Forwarded-For/Proto from reverse proxy (nginx)
# --forwarded-allow-ips=*: accept proxy headers from any IP (nginx is the only ingress)
# exec: replaces shell with uvicorn for proper PID 1 signal handling
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY} --proxy-headers --forwarded-allow-ips='*'"]
