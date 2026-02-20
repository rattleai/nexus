# CADPrice

Manufacturing intelligence platform — STEP file analysis, costing, and 2D drawing generation.

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Python 3.12+ (for local development)
- Node.js 20+ (for Tailwind CSS builds)

### Run with Docker

```bash
cp .env.example .env
docker-compose up
```

Services:
- **API**: http://localhost:8000
- **Health check**: http://localhost:8000/api/v1/health
- **MinIO Console**: http://localhost:9001 (minioadmin / minioadmin)

### Local Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run migrations
alembic upgrade head

# Start the server
uvicorn cadprice.main:app --reload

# Build CSS
npm install
npm run watch:css
```

### Run Tests

```bash
pytest -q
```
