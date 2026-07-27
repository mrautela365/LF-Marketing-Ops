import os
from pathlib import Path
from dotenv import load_dotenv, dotenv_values

# Checked in priority order (later entries win) so survey_workflow/.env takes
# precedence over emailcreationskill/.env when both exist (this config module
# is shared by both apps via sys.path insertion).
_env_paths = [
    Path(__file__).parent.parent / ".env",                              # emailcreationskill/.env
    Path(__file__).parent.parent.parent / "survey_workflow" / ".env",   # survey_workflow/.env
]
for _p in _env_paths:
    if _p.exists():
        load_dotenv(dotenv_path=_p, override=True)

# Claude Code injects its own ANTHROPIC_API_KEY session token into the subprocess
# environment. That token is NOT valid for direct Anthropic API calls.
# Only trust a key that was explicitly written in a .env file.
_file_values = {}
for _p in _env_paths:
    if _p.exists():
        _file_values.update(dotenv_values(dotenv_path=_p))
ANTHROPIC_API_KEY = _file_values.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

HUBSPOT_ACCESS_TOKEN = os.getenv("HUBSPOT_ACCESS_TOKEN", "")
HUBSPOT_PORTAL_ID = os.getenv("HUBSPOT_PORTAL_ID", "8112310")

GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "")

# Shared secret for the /api/stage-from-brief endpoint (skill integration).
# If left empty, the endpoint warns but still accepts calls (local dev only).
INTERNAL_API_TOKEN = os.getenv("INTERNAL_API_TOKEN", "")

ASANA_ACCESS_TOKEN = os.getenv("ASANA_ACCESS_TOKEN", "")

# Optional marker appended to the name of every HubSpot asset this service creates
# (cloned emails, audience/suppression lists) so test/dev runs can be found and bulk
# -deleted later, e.g. ASSET_TAG=psh-test -> "... [psh-test]". Leave unset in prod.
ASSET_TAG = os.getenv("ASSET_TAG", "").strip()


def tag_asset_name(name: str) -> str:
    """Append ASSET_TAG to a HubSpot asset name. No-op when ASSET_TAG is unset."""
    if not ASSET_TAG or not name:
        return name
    suffix = f" [{ASSET_TAG}]"
    return name if name.endswith(suffix) else f"{name}{suffix}"

# LiteLLM proxy (takes priority over direct Anthropic API key when both are set)
LITELLM_BASE_URL = os.getenv("LITELLM_BASE_URL", "")
LITELLM_API_KEY  = os.getenv("LITELLM_API_KEY",  "")

# Snowflake credentials (for audience list building)
# Keys are read directly from os.environ in audience_tools.py — listed here for .env documentation.
# SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_PRIVATE_KEY (PEM),
# SNOWFLAKE_DATABASE (default: ANALYTICS), SNOWFLAKE_SCHEMA (default: Silver_Segment),
# SNOWFLAKE_WAREHOUSE (optional), SNOWFLAKE_ROLE (optional)
