"""FastAPI application entry point."""
import json
import logging
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .api.routes import analyze, generate, gboost, assess, simulate, leveling, rl_sim, production_store, tune, study

_diag_logger = logging.getLogger("diag.422")

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

# Diagnostic: log validation errors with body so we can see what FE sends
@app.exception_handler(RequestValidationError)
async def _log_validation_errors(request: Request, exc: RequestValidationError):
    body = b""
    try:
        body = await request.body()
    except Exception:
        pass
    body_preview = body[:2000].decode("utf-8", errors="replace")
    errors = exc.errors()
    _diag_logger.error(
        "422 on %s %s | errors=%s | body=%s",
        request.method, request.url.path, json.dumps(errors, default=str), body_preview,
    )
    return JSONResponse(status_code=422, content={"detail": errors})


# Include routers
app.include_router(analyze.router)
app.include_router(generate.router)
app.include_router(gboost.router)
app.include_router(assess.router)
app.include_router(simulate.router)
app.include_router(leveling.router)
app.include_router(rl_sim.router)
app.include_router(production_store.router)
app.include_router(tune.router)
app.include_router(study.router)


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


@app.on_event("startup")
async def startup_event():
    """프로세스 풀 워밍업 — 첫 요청의 워커 스폰 지연(2~3초) 제거 (RL 시뮬 + 레벨 생성)."""
    import asyncio
    from .api.routes.rl_sim import warmup_pool
    from .api.routes.generate import warmup_gen_pool
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, warmup_pool)
    loop.run_in_executor(None, warmup_gen_pool)


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup ProcessPoolExecutor on shutdown.

    ⚠️ 이 훅은 **정상 종료(SIGTERM/SIGINT)** 에서만 돈다. `kill -9` 로 죽이면 실행되지
    않고 워커가 부모를 잃어 PID 1 로 넘어간다 — 그렇게 쌓인 고아가 실측 1985개였다
    (프로세스 2638개 중 75%). 재시작은 반드시 TERM 을 먼저 보낼 것.
    """
    # ⚠️ 순서 주의: 아래 shutdown_* 헬퍼들이 전역 참조를 None 으로 만든다.
    # 워커를 명시적으로 죽이려면 **참조가 살아 있는 지금** 풀 객체를 먼저 붙잡아야 한다.
    live_pools = _iter_live_pools()

    from .api.routes.generate import _bot_process_pool, shutdown_gen_pool
    if _bot_process_pool is not None:
        _bot_process_pool.shutdown(wait=False)
    shutdown_gen_pool()
    from .api.routes.rl_sim import shutdown_pool
    shutdown_pool()
    # [누수 차단] bot_simulator 의 모듈 전역 풀만 이 훅에서 빠져 있었다.
    # 봇 시뮬(순차검증·난이도 판정)이 쓰는 풀이라 실사용 빈도가 가장 높은데도 아무도 닫지 않았다.
    try:
        from .core import bot_simulator as _bs
        if _bs._process_pool is not None:
            _bs._process_pool.shutdown(wait=False)
            _bs._process_pool = None
    except Exception:  # noqa: BLE001 — 종료 경로라 실패해도 막지 않는다
        pass

    # [최종 회수] shutdown(wait=False) 는 '더 이상 작업을 받지 않는다'는 신호일 뿐,
    # 워커가 실제로 죽는 걸 기다리지 않는다. 부모가 곧바로 종료하면 워커는 아직 살아 있고
    # 그대로 PID 1 로 입양돼 영구 잔류한다 — 실측으로 종료 1회당 20여 개가 남았다.
    # 그래서 각 풀의 자식 프로세스를 명시적으로 죽인다(멱등, 이미 죽었으면 무시).
    #
    # wait=True 를 쓰지 않는 이유: 진행 중인 시뮬이 길면 종료가 그만큼 지연되고,
    # 재시작이 잦은 개발 환경에서 오히려 좀비를 늘린다. 여기서는 즉시 종료가 옳다.
    import contextlib
    for pool in live_pools:
        with contextlib.suppress(Exception):   # 풀 하나가 터져도 나머지는 정리한다
            # ⚠️ `_processes` 는 워커를 아직 안 띄운 풀에서 **None** 이다(속성은 존재).
            # getattr 기본값은 '속성 없음'에만 걸리므로 None 을 못 걸러 AttributeError 가 났고,
            # 그 예외가 훅 전체를 중단시켜 `Application shutdown failed` → 오히려 정리가 안 됐다.
            procs = list((getattr(pool, "_processes", None) or {}).values())
            for p in procs:
                with contextlib.suppress(Exception):
                    if p.is_alive():
                        p.terminate()
            for p in procs:
                with contextlib.suppress(Exception):
                    p.join(timeout=1.0)
                    if p.is_alive():
                        p.kill()


def _iter_live_pools():
    """현재 살아 있는 ProcessPoolExecutor 전부. 풀이 5개로 흩어져 있어 모아서 순회한다."""
    pools = []
    try:
        from .api.routes import generate as _g
        pools += [_g._bot_process_pool, _g._gen_process_pool, _g._autoplay_process_pool]
    except Exception:  # noqa: BLE001
        pass
    try:
        from .api.routes import rl_sim as _r
        pools.append(_r._pool)
    except Exception:  # noqa: BLE001
        pass
    try:
        from .core import bot_simulator as _b
        pools.append(_b._process_pool)
    except Exception:  # noqa: BLE001
        pass
    return [p for p in pools if p is not None]


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
