"""
HubSpot Draft Email — FastAPI + FastMCP server.

Serves three surfaces from one process:
  GET  /          → Web UI (3-tab email manager)
  GET  /setup     → Credential setup page
  POST /mcp       → MCP StreamableHTTP endpoint (for Claude / Claude Code)
  GET  /api/*     → REST endpoints called by the web UI
  GET  /health    → Health check
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from mcp.server.fastmcp import FastMCP

from src.api_routes import hubspot as hubspot_routes
from src.api_routes import setup as setup_routes
from src.lib.credentials import is_fully_configured
from src.mcp_tools import hubspot_account
from src.mcp_tools import hubspot_email
from src.mcp_tools import hubspot_lists

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)

# ── MCP Server ────────────────────────────────────────────────────────────────

mcp = FastMCP(
    name="hubspot-draft-email",
    instructions=(
        "HubSpot Draft Email Manager. Use these tools to create, validate, and manage "
        "HubSpot marketing email drafts. Workflow: (1) validate audience lists, "
        "(2) confirm subscription type with user, (3) run QA, (4) create draft only if "
        "QA verdict is not BLOCKED. Never auto-send — always create as DRAFT."
    ),
)

# Register all MCP tools
hubspot_account.register(mcp)
hubspot_lists.register(mcp)
hubspot_email.register(mcp)

# ── FastAPI App ───────────────────────────────────────────────────────────────

PUBLIC_DIR = Path(__file__).parent / "public"

_mcp_sub_app = mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configured = is_fully_configured()
    logger.info(
        "HubSpot Draft Email starting on port %s — HubSpot: %s",
        os.environ.get("PORT", 8001),
        "✅ configured" if configured else "❌ NOT configured — visit /setup",
    )
    async with mcp.session_manager.run():
        yield
    logger.info("HubSpot Draft Email shutting down.")


app = FastAPI(
    title="HubSpot Draft Email",
    version="1.0.0",
    description="MCP server + web UI for creating and managing HubSpot marketing email drafts",
    lifespan=lifespan,
)

# Mount the MCP sub-app at /mcp (Claude Code connects to http://localhost:8001/mcp/mcp)
app.mount("/mcp", _mcp_sub_app)

# Static files
if PUBLIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(PUBLIC_DIR)), name="static")

# REST API routers
app.include_router(hubspot_routes.router)
app.include_router(setup_routes.router)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    """Health check — reports configuration status."""
    from src.lib.credentials import is_hubspot_configured, is_asana_configured
    return {
        "status": "ok",
        "version": "1.0.0",
        "configured": is_fully_configured(),
        "hubspot_connected": is_hubspot_configured(),
        "asana_connected": is_asana_configured(),
    }


@app.get("/")
async def root():
    """Serve the main web UI, or redirect to /setup if not configured."""
    if not is_fully_configured():
        return RedirectResponse(url="/setup")
    index = PUBLIC_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {
        "message": "HubSpot Draft Email MCP Server is running.",
        "mcp_endpoint": "/mcp",
        "health": "/health",
        "setup": "/setup",
    }


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8001))
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=port,
        reload=True,
        log_level="info",
    )
