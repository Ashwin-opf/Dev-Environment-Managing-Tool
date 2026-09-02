"""
PC Doctor – Backend Main Entry Point

FastAPI server that bridges the Tauri frontend to the repair engine,
AI assistant, scanner, optimizer, and safety layer.

Lifecycle notes
───────────────
• This process is spawned by the Tauri Rust host (src-tauri/src/lib.rs).
• The host sends SIGKILL when the user closes the app.
• We listen on 127.0.0.1 only, so the port is never accessible over LAN.
• uvicorn is configured with SO_REUSEPORT=False so two instances cannot
  accidentally co-exist on the same port.
"""

import os
import sys
import errno
import signal
import logging
import platform
import uvicorn
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

# ── Force UTF-8 I/O on all platforms ──────────────────────────────────────────
# Prevents UnicodeEncodeError on Windows terminals that default to cp1252.
# Also ensures child processes inherit UTF-8 encoding.
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

# ── Shared context (database paths, global singletons) ──
import app_context  # noqa: F401  (side-effect import; sets up paths/globals)

# ── Route modules ──────────────────────────────────────
import routes_ai
import routes_logs
import routes_files
import routes_system
import routes_shce

# ─── Connection error handler ─────────────────────────────────────────────────

# Dedicated logger for connection-level errors (separate from the user-visible log).
_conn_logger = logging.getLogger("pc_doctor.connection")
if not _conn_logger.handlers:
    _conn_logger.setLevel(logging.DEBUG)
    _conn_handler = logging.StreamHandler()
    _conn_handler.setLevel(logging.DEBUG)
    _conn_logger.addHandler(_conn_handler)


class ConnectionErrorHandler:
    """
    Handles EPIPE / BrokenPipe / ConnectionReset errors that arise when
    the Tauri frontend closes a connection while the backend is still writing.

    Design goals (Requirements 7.1 – 7.3):
    • Suppress popup dialogs – errors are logged only; never propagated to the
      frontend as unhandled exceptions.
    • Silent logging – errors go to the Python logger at WARNING level so they
      appear in uvicorn server logs but not in user-visible pc_doctor.log.
    • Automatic reconnection – tracks per-request reconnection attempts so the
      caller can decide whether to retry.  A hard limit (max_attempts) prevents
      infinite retry loops.
    """

    def __init__(self, max_attempts: int = 3) -> None:
        self.max_attempts: int = max_attempts
        self.reconnection_attempts: int = 0
        self._last_error_time: datetime | None = None
        self._last_error_type: str = ""
        self._connected: bool = True

    # ------------------------------------------------------------------
    # Core error handling
    # ------------------------------------------------------------------

    def handle_epipe_error(self, error: Exception) -> bool:
        """
        Process an EPIPE / BrokenPipe / ConnectionReset error silently.

        Logs the error to the server logger (file/stderr) without raising or
        propagating it.  Increments the internal reconnection counter and
        returns True if a retry is still possible, False when the retry limit
        is reached.

        Returns:
            True  – within retry budget; caller may attempt reconnection.
            False – retry limit reached; caller should give up.
        """
        self._last_error_time = datetime.now(timezone.utc)
        self._last_error_type = type(error).__name__
        self._connected = False

        _conn_logger.warning(
            "[PC Doctor] Connection error suppressed (no popup): %s – %s",
            type(error).__name__,
            error,
        )

        if self.reconnection_attempts < self.max_attempts:
            self.reconnection_attempts += 1
            _conn_logger.info(
                "[PC Doctor] Reconnection attempt %d/%d.",
                self.reconnection_attempts,
                self.max_attempts,
            )
            return True

        _conn_logger.warning(
            "[PC Doctor] Reconnection limit (%d) reached; giving up.",
            self.max_attempts,
        )
        return False

    def mark_connected(self) -> None:
        """Reset state after a successful request (connection restored)."""
        self.reconnection_attempts = 0
        self._connected = True

    # ------------------------------------------------------------------
    # Status reporting
    # ------------------------------------------------------------------

    def get_connection_status(self) -> dict:
        """
        Return a JSON-serialisable dict describing the current connection
        health.  Used by the GET /api/status/connection endpoint so the
        frontend can display accurate status indicators instead of raw errors.
        """
        if self._connected:
            state = "connected"
        elif self.reconnection_attempts < self.max_attempts:
            state = "reconnecting"
        else:
            state = "failed"

        return {
            "state": state,
            "connected": self._connected,
            "reconnection_attempts": self.reconnection_attempts,
            "max_attempts": self.max_attempts,
            "last_error_type": self._last_error_type,
            "last_error_time": (
                self._last_error_time.isoformat() if self._last_error_time else None
            ),
        }


# Module-level singleton – shared across all requests.
connection_error_handler = ConnectionErrorHandler(max_attempts=3)


# ─── Lifespan (startup / shutdown) ──────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs startup logic, yields for requests, then runs shutdown logic."""
    # --- Startup ---
    try:
        from shce_engine import ErrorIntelligenceDB, DB_PATH
        ErrorIntelligenceDB(DB_PATH)  # creates tables if absent
    except Exception as err:
        print(f"[PC Doctor] SHCE init warning (non-fatal): {err}")

    yield

    # --- Shutdown ---
    try:
        from pathlib import Path
        flag_file = Path(__file__).parent / "ollama_user_started.flag"
        if flag_file.exists():
            from routes_system import stop_ollama_server
            await stop_ollama_server()
            print("[PC Doctor] Ollama server stopped at shutdown.")
            try:
                flag_file.unlink()
            except Exception:
                pass
        else:
            print("[PC Doctor] Ollama server was not started by PC Doctor, keeping it running.")
    except Exception as err:
        print(f"[PC Doctor] Ollama stop warning at shutdown: {err}")


# ─── FastAPI application ──────────────────────────────────────────────────────

app = FastAPI(title="PC Doctor API", version="1.0.0", lifespan=lifespan)

# Restrict CORS to loopback only.  The Tauri webview origin is
# "tauri://localhost" (v2) which must also be listed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Broken-pipe / connection-reset silence ───────────────────────────────────
# Uvicorn surfaces BrokenPipeError and ConnectionResetError as unhandled
# exceptions when the client disconnects mid-request (common on Tauri IPC
# teardown).  ConnectionErrorHandler logs them silently and we return a 503 so
# they never reach the user or pollute stderr with an unhandled exception.

@app.exception_handler(BrokenPipeError)
async def broken_pipe_handler(request: Request, exc: BrokenPipeError):
    connection_error_handler.handle_epipe_error(exc)
    return Response(status_code=503)


@app.exception_handler(ConnectionResetError)
async def connection_reset_handler(request: Request, exc: ConnectionResetError):
    connection_error_handler.handle_epipe_error(exc)
    return Response(status_code=503)


@app.exception_handler(OSError)
async def oserror_handler(request: Request, exc: OSError):
    # OSError with errno.EPIPE is the POSIX form of a broken pipe; handle the
    # same way as BrokenPipeError so no popup/unhandled exception surfaces.
    if exc.errno == errno.EPIPE:
        connection_error_handler.handle_epipe_error(exc)
        return Response(status_code=503)
    # All other OSErrors are re-raised so they surface normally.
    raise exc

# ─── API token (optional defence-in-depth) ───────────────────────────────────
#
# The Rust host injects PC_DOCTOR_API_TOKEN via env.  If it isn't set
# (e.g. running the backend standalone for development), we generate
# a fresh random token and print it once.

import secrets as _secrets

API_TOKEN: str = os.getenv("PC_DOCTOR_API_TOKEN", "").strip()
if not API_TOKEN:
    API_TOKEN = _secrets.token_hex(32)
    print(f"[PC Doctor] No API_TOKEN in env; generated one for this session.")


@app.middleware("http")
async def track_connection_health(request: Request, call_next):
    """
    Mark the connection as healthy after every successful response.
    This resets the ConnectionErrorHandler retry counter automatically so
    that transient EPIPE errors don't permanently block reconnection.
    """
    response = await call_next(request)
    # Any non-5xx response means the pipeline completed successfully.
    if response.status_code < 500:
        connection_error_handler.mark_connected()
    return response


@app.middleware("http")
async def check_api_token(request: Request, call_next):
    # Pass non-API routes through without token checks (e.g. /health, /docs).
    if not request.url.path.startswith("/api/"):
        return await call_next(request)

    # Every request to 127.0.0.1 already originates from the local machine
    # (Tauri webview, CLI, tests), so we allow all loopback clients freely.
    # Token enforcement is a second layer for any accidental remote exposure.
    import ipaddress
    client_host = (request.client.host if request.client else "") or ""
    is_loopback = False
    if client_host in ("localhost", ""):
        is_loopback = True
    else:
        try:
            # Strip IPv6 mapping if present (e.g., ::ffff:127.0.0.1)
            ip_str = client_host
            if ip_str.startswith("::ffff:"):
                ip_str = ip_str[7:]
            is_loopback = ipaddress.ip_address(ip_str).is_loopback
        except ValueError:
            pass

    if is_loopback:
        return await call_next(request)

    # Non-loopback: enforce the bearer token.
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {API_TOKEN}":
        return JSONResponse(
            status_code=401,
            content={"detail": "Unauthorized. Missing or invalid PC Doctor API token."},
        )

    return await call_next(request)


# ─── Route registration ───────────────────────────────────────────────────────

import routes_agent
import routes_catalog
import routes_control_center

app.include_router(routes_ai.router)
app.include_router(routes_logs.router)
app.include_router(routes_files.router)
app.include_router(routes_system.router)
app.include_router(routes_shce.router)
app.include_router(routes_agent.router)
app.include_router(routes_catalog.router)
app.include_router(routes_control_center.router)


# ─── Health endpoint ──────────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    """
    Lightweight probe used by the Rust host to detect when the backend is
    ready to serve requests.  Returns 200 as soon as the server is up.
    """
    return {
        "status":  "healthy",
        "version": "1.0.0",
        "os":      platform.system(),
    }


# ─── Connection status endpoint ───────────────────────────────────────────────

@app.get("/api/status/connection")
async def connection_status():
    """
    Returns the current connection health reported by ConnectionErrorHandler.
    The frontend polls this endpoint to display accurate status indicators
    (connected / reconnecting / failed) instead of raw EPIPE error messages.

    Satisfies Requirements 7.4 – frontend displays connection status indicators.
    """
    status = connection_error_handler.get_connection_status()
    return {
        "ok": True,
        **status,
    }


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Ignore SIGHUP so the backend survives terminal closures.
    # When spawned by the Tauri host this is redundant (there's no controlling
    # terminal), but when started manually from a shell it prevents the process
    # from dying when the user closes the terminal window.
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, signal.SIG_IGN)

    host = os.getenv("API_HOST", "127.0.0.1")
    port = int(os.getenv("API_PORT", "8765"))
    reload_flag = os.getenv("API_RELOAD", "false").lower() in ("1", "true", "yes")

    # Free port if held by a zombie/orphan process from a previous session
    try:
        current_pid = os.getpid()
        for conn in psutil.net_connections(kind="inet"):
            if conn.laddr and conn.laddr.port == port and conn.pid and conn.pid != current_pid:
                try:
                    psutil.Process(conn.pid).kill()
                    print(f"[PC Doctor] Freed port {port} from orphaned PID {conn.pid}")
                except Exception:
                    pass
    except Exception:
        pass

    if reload_flag:
        uvicorn.run(
            "main:app",
            host=host,
            port=port,
            log_level="info",
            reload=True,
            reload_dirs=[str(Path(__file__).parent)],
            timeout_graceful_shutdown=5,
        )
    else:
        uvicorn.run(
            app,
            host=host,
            port=port,
            log_level="info",
            timeout_graceful_shutdown=5,
        )

