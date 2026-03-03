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

COPY pyproject.toml README.md ./
COPY cadprice/__init__.py cadprice/
RUN pip install --no-cache-dir .

FROM deps AS runtime

COPY . .
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

EXPOSE 8000

CMD ["uvicorn", "cadprice.main:app", "--host", "0.0.0.0", "--port", "8000"]
