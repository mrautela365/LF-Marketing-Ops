"""
HubSpot Form Manager — FastAPI + FastMCP server.

Serves three surfaces from one process:
  GET  /          → Web UI (3-tab form manager)
  GET  /setup     → Credential setup page
  POST /mcp       → MCP StreamableHTTP endpoint (for Claude Code)
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

from src.api_routes import asana as asana_routes
from src.api_routes import hubspot as hubspot_routes
from src.api_routes import setup as setup_routes
from src.lib.credentials import is_fully_configured
from src.mcp_tools import asana as asana_tools
from src.mcp_tools import hubspot_account
from src.mcp_tools import hubspot_forms
from src.mcp_tools import hubspot_marketing

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)

# ── MCP Server ────────────────────────────────────────────────────────────────

mcp = FastMCP(
    name="hubspot-form-manager",
    instructions=(
        "HubSpot Form Manager. Use these tools to create, delete, and manage HubSpot forms "
        "on behalf of users. Always confirm brand, subscription type, and workflow with the "
        "user before creating a form — never assume defaults."
    ),
)

# Register all MCP tools
hubspot_account.register(mcp)
hubspot_forms.register(mcp)
hubspot_marketing.register(mcp)
asana_tools.register(mcp)

# ── FastAPI App ───────────────────────────────────────────────────────────────

PUBLIC_DIR = Path(__file__).parent / "public"



# Build the MCP sub-app now so we can access its session manager in our lifespan
_mcp_sub_app = mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Combined lifespan:
    1. Starts the MCP session manager's task group (required for StreamableHTTP transport)
    2. Logs startup status
    """
    configured = is_fully_configured()
    logger.info(
        "HubSpot Form Manager starting on port %s — HubSpot: %s",
        os.environ.get("PORT", 8000),
        "✅ configured" if configured else "❌ NOT configured — visit /setup",
    )
    # Run the MCP session manager (initialises the internal anyio task group)
    async with mcp.session_manager.run():
        yield
    logger.info("HubSpot Form Manager shutting down.")


app = FastAPI(
    title="HubSpot Form Manager",
    version="1.0.0",
    description="MCP server + web UI for managing HubSpot forms",
    lifespan=lifespan,
)

# Mount the MCP sub-app — the sub-app's internal route is /mcp, so the full
# path for Claude Code to use is http://localhost:8000/mcp/mcp
app.mount("/mcp", _mcp_sub_app)

# Static files (CSS, JS)
if PUBLIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(PUBLIC_DIR)), name="static")

# Include REST API routers
app.include_router(hubspot_routes.router)
app.include_router(asana_routes.router)
app.include_router(setup_routes.router)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    """Health check — also reports configuration status."""
    from src.lib.credentials import is_asana_configured, is_hubspot_configured
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
        "message": "HubSpot Form Manager MCP Server is running.",
        "web_ui": "public/index.html not found — serve this server and open /setup.",
        "mcp_endpoint": "/mcp",
        "health": "/health",
    }


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=port,
        reload=True,
        log_level="info",
    )
