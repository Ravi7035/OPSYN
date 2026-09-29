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

# Browser access for the OPSYN frontend (local Vite dev server + the
# deployed production URL configured via FRONTEND_URL). Origins are an
# explicit allow-list plus localhost loopback; never use "*" in production.
def _allowed_frontend_origins() -> list[str]:
    raw = settings.frontend_url or ""
    origins = []
    for entry in raw.split(","):
        origin = entry.strip().rstrip("/")
        if origin and origin.startswith(("http://", "https://")):
            origins.append(origin)
    return origins


app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_frontend_origins(),
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
