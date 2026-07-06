"""
Credential resolution — three-tier priority:
  1. Environment variable already set (covers Claude Code MCP env block)
  2. .env file in the mcp-server directory (python-dotenv)
  3. Not found → server marks itself unconfigured; web UI /setup page handles it
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the mcp-server root (one level above this file's package)
_ENV_FILE = Path(__file__).parent.parent.parent / ".env"
load_dotenv(dotenv_path=_ENV_FILE, override=False)  # override=False: env vars win over .env


def get_hubspot_api_key() -> str | None:
    return os.environ.get("HUBSPOT_API_KEY") or None


def get_asana_pat() -> str | None:
    return os.environ.get("ASANA_PAT") or None


def is_hubspot_configured() -> bool:
    return bool(get_hubspot_api_key())


def is_asana_configured() -> bool:
    return bool(get_asana_pat())


def is_fully_configured() -> bool:
    """HubSpot is required; Asana is optional (only needed for pre-fill)."""
    return is_hubspot_configured()


def save_credentials(hubspot_api_key: str | None, asana_pat: str | None) -> None:
    """
    Persist credentials to the .env file so they survive server restarts.
    Only writes non-empty values; existing values in the file are preserved.
    """
    existing: dict[str, str] = {}
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                existing[k.strip()] = v.strip()

    if hubspot_api_key:
        existing["HUBSPOT_API_KEY"] = hubspot_api_key
    if asana_pat:
        existing["ASANA_PAT"] = asana_pat

    lines = [f"{k}={v}" for k, v in existing.items()]
    _ENV_FILE.write_text("\n".join(lines) + "\n")

    # Reload into os.environ immediately
    load_dotenv(dotenv_path=_ENV_FILE, override=True)
