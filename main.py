from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from routers import check, rules
from services.rate_limiter_service import RateLimiterService
from storage.memory_backend import MemoryBackend
from storage.redis_backend import RedisBackend


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown hook — like IHostedService in .NET.

    Creates the shared service + storage backend once at startup.
    Anything before `yield` runs on startup; after `yield` runs on shutdown.
    """
    if settings.storage_backend == "redis":
        client = aioredis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db,
        )
        storage = RedisBackend(client)
        await storage.initialize()
        app.state.service = RateLimiterService(storage=storage)
        yield
        await storage.close()
    else:
        storage = MemoryBackend()
        app.state.service = RateLimiterService(storage=storage)
        yield


app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)

# CORS — allow all origins for development. Lock down in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(check.router)
app.include_router(rules.router)


@app.get("/api/v1/health")
async def health_check():
    return {"status": "healthy"}
