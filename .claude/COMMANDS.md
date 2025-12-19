# Development Commands

## Backend
```bash
cd backend
source venv/bin/activate
uvicorn app.main:app --reload --port 8000
pytest
```

## Frontend
```bash
cd frontend
npm run dev      # dev server (port 5173)
npm run build    # production build
npm run lint     # eslint
```

## Docker
```bash
docker-compose up -d
docker-compose -f docker-compose.dev.yml up
```

## Quick Start
```bash
# Terminal 1: Backend
cd backend && source venv/bin/activate && uvicorn app.main:app --reload

# Terminal 2: Frontend
cd frontend && npm run dev
```

## API Test
```bash
# Health check
curl http://localhost:8000/health

# Analyze
curl -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"level_json": {...}}'
```
