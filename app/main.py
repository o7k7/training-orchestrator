from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi_limiter import FastAPILimiter

from app.k8s_job.job_router import job_router
from app.redis.redis_client import init_redis, get_redis, dispose_redis


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_redis()
    await FastAPILimiter.init(await get_redis())

    yield

    await dispose_redis()

app = FastAPI(title="Training Orchestrator", lifespan=lifespan)

app.include_router(job_router, prefix="/api/v1")

@app.get("/health")
async def health():
    return {"status": "ok"}