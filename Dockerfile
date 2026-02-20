FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

FROM base AS deps

COPY pyproject.toml ./
RUN pip install --no-cache-dir .

FROM deps AS runtime

COPY . .

EXPOSE 8000

CMD ["uvicorn", "cadprice.main:app", "--host", "0.0.0.0", "--port", "8000"]
