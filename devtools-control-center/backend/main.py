"""
DevTools & Control Center — Standalone Server Entry Point
==========================================================
FastAPI application that serves the Dev Tools marketplace, package
resolution pipeline, real-time update stream, and Control Center
approval queue & snapshot rollback engine.
"""

import os
import sys
import platform
import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn

# ── Force UTF-8 I/O on all platforms ──────────────────────────────────────────
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

# ── Route modules ─────────────────────────────────────────────────────────────
import routes_control_center
import routes_devtools

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.info("[DevTools & Control Center] Backend started.")
    yield
    logging.info("[DevTools & Control Center] Backend shutting down.")


app = FastAPI(
    title="DevTools & Control Center",
    version="1.0.0",
    description="Unified Developer Tools Store, Resolution Pipeline & Control Center",
    lifespan=lifespan,
)

# ── CORS Middleware ───────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Include API Routers ───────────────────────────────────────────────────────
app.include_router(routes_control_center.router)
app.include_router(routes_devtools.router)


# ── Health & Diagnostic endpoints ─────────────────────────────────────────────
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "devtools-control-center",
        "version": "1.0.0",
        "os": platform.system(),
        "arch": platform.machine(),
    }


@app.get("/api/status/system")
async def system_status():
    """System information & active package managers on host machine."""
    from adapters.registry import get_active_adapter_names
    return {
        "ok": True,
        "os": f"{platform.system()} {platform.release()}",
        "architecture": platform.machine(),
        "hostname": platform.node(),
        "active_package_managers": get_active_adapter_names(),
        "service": "DevTools Store & Control Center",
    }



# ── Mount Frontend Static Assets ──────────────────────────────────────────────
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    async def serve_index():
        index_file = FRONTEND_DIR / "index.html"
        if index_file.exists():
            return FileResponse(str(index_file))
        return JSONResponse({"status": "healthy", "frontend": "index.html not found"})

    @app.get("/{file_name:path}")
    async def serve_static(file_name: str):
        target = FRONTEND_DIR / file_name
        if target.exists() and target.is_file():
            return FileResponse(str(target))
        index_file = FRONTEND_DIR / "index.html"
        if index_file.exists():
            return FileResponse(str(index_file))
        return JSONResponse({"error": "File not found"}, status_code=404)


if __name__ == "__main__":
    host = os.getenv("API_HOST", "127.0.0.1")
    port = int(os.getenv("API_PORT", "8790"))
    print(f"[DevTools & Control Center] Starting server on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
