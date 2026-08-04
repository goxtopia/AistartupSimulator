"""FastAPI entrypoint for AI Startup Simulator."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app.api.routes import router
from backend.app.core.config_loader import ROOT

FRONTEND = ROOT / "frontend"

app = FastAPI(
    title="AI Startup Simulator",
    description="Config-driven AI lab tycoon web game",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")

if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")
    assets = FRONTEND / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")


@app.get("/")
def index():
    index_path = FRONTEND / "index.html"
    if not index_path.exists():
        return {"message": "Frontend missing", "api": "/api/health"}
    return FileResponse(index_path)


@app.get("/favicon.ico")
def favicon():
    # inline empty to avoid 404 noise
    return FileResponse(FRONTEND / "index.html") if (FRONTEND / "index.html").exists() else {}
