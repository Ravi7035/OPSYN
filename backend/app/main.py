"""FastAPI application entrypoint."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import agent, health, incidents, memory, simulator
from app.config.settings import get_settings

settings = get_settings()

app = FastAPI(
    title="SRE Incident Response Backend",
    description=(
        "Layered backend foundation for the SRE AI Incident Response project. "
        "API -> Service -> Hindsight Cloud memory layer."
    ),
    version="0.1.0",
)

# Dev-only browser access for the local OPSYN frontend (Vite dev server).
# Restricts origins to localhost loopback; never use "*" in production.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)

app.include_router(health.router)
app.include_router(memory.router)
app.include_router(simulator.router)
app.include_router(agent.router)
app.include_router(incidents.router)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}
