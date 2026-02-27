# CADPrice

Manufacturing intelligence platform — STEP file analysis, costing, and 2D drawing generation.

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Python 3.12+ (for local development)
- Node.js 22+ (for React frontend)

### Run with Docker

```bash
cp .env.example .env
docker-compose up
```

Services:
- **API**: http://localhost:8000
- **Frontend**: http://localhost:3000
- **Health check**: http://localhost:8000/api/v1/health
- **MinIO Console**: http://localhost:9001 (minioadmin / minioadmin)

### Local Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run migrations
alembic upgrade head

# Start the API server
uvicorn cadprice.main:app --reload

# In a separate terminal — start the frontend dev server
cd frontend
npm install
npm run dev
```

The frontend dev server runs on http://localhost:3000 and proxies `/api` requests to the FastAPI backend on port 8000.

### Run Tests

```bash
# Backend
pytest -q

# Frontend
cd frontend && npm test
```

### Production Build

```bash
cd frontend && npm run build
```

This outputs static files to `frontend/dist/`, which FastAPI serves directly.
