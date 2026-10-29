"""FastAPI app for the castle-allocation dashboard (deployed as one Vercel Python function).

Static files (the dashboard page, precomputed results and figures) live in
public/.  Vercel serves public/ from its CDN; the StaticFiles mount below
serves the same files when running locally with uvicorn.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from blotto import service

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"

app = FastAPI(title="Castle allocation lab", docs_url="/api/docs", openapi_url="/api/openapi.json")


async def _body(request: Request) -> dict:
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "request body must be JSON")
    if not isinstance(data, dict):
        raise HTTPException(400, "request body must be a JSON object")
    return data


def _run(fn, data):
    try:
        return fn(data)
    except service.UserError as e:
        raise HTTPException(400, str(e))


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/meta")
def meta():
    return service.meta()


@app.post("/api/evaluate")
async def evaluate(request: Request):
    return _run(service.evaluate, await _body(request))


@app.post("/api/best-response/g1")
async def best_response_g1(request: Request):
    return _run(service.best_response_g1, await _body(request))


@app.post("/api/optimize/g2")
async def optimize_g2(request: Request):
    return _run(service.optimize_g2, await _body(request))


@app.post("/api/self-play")
async def self_play(request: Request):
    return _run(service.self_play, await _body(request))


@app.post("/api/tournament")
async def tournament(request: Request):
    return _run(service.tournament, await _body(request))


@app.get("/")
def index():
    # on Vercel public/ is served by the CDN and is not bundled into the function
    page = PUBLIC / "index.html"
    return FileResponse(page) if page.exists() else RedirectResponse("/index.html")


if PUBLIC.exists():
    app.mount("/", StaticFiles(directory=PUBLIC), name="public")
