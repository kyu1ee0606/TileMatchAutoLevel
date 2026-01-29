"""FastAPI application entry point."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .api.routes import analyze, generate, gboost, assess, simulate, leveling

# Get settings
settings = get_settings()

# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="타일매치 게임 레벨의 난이도 분석, 자동 생성, 게임부스트 연동을 위한 웹 기반 도구",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(analyze.router)
app.include_router(generate.router)
app.include_router(gboost.router)
app.include_router(assess.router)
app.include_router(simulate.router)
app.include_router(leveling.router)


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "description": "TileMatch Level Designer Tool API",
        "endpoints": {
            "analyze": "/api/analyze",
            "generate": "/api/generate",
            "simulate_visual": "/api/simulate/visual",
            "assess_multibot": "/api/assess/multibot",
            "assess_comprehensive": "/api/assess/comprehensive",
            "bot_profiles": "/api/assess/profiles",
            "gboost": "/api/gboost/{board_id}/{level_id}",
            "docs": "/docs",
        },
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "version": settings.app_version,
    }


@app.get("/debug/env")
async def debug_env():
    """Debug endpoint to check environment variables."""
    import os
    return {
        "gboost_url": settings.gboost_url,
        "gboost_project_id": settings.gboost_project_id,
        "env_gboost_url": os.getenv("GBOOST_URL"),
        "env_gboost_project_id": os.getenv("GBOOST_PROJECT_ID"),
        "cors_origins": settings.get_cors_origins(),
    }


if __name__ == "__main__":
    import os
    import uvicorn

    # Multi-worker: reload mode (debug) doesn't support workers
    # In production mode, use multiple workers for true parallelism
    worker_count = 1 if settings.debug else min(4, os.cpu_count() or 4)

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        workers=worker_count,
    )
