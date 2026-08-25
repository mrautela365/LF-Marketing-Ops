import os
from pathlib import Path
from dotenv import load_dotenv, dotenv_values

_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    load_dotenv(dotenv_path=_env_path, override=True)

# Claude Code injects its own ANTHROPIC_API_KEY session token into the subprocess
# environment. That token is NOT valid for direct Anthropic API calls.
# Only trust a key that was explicitly written in the .env file.
_file_values = dotenv_values(dotenv_path=_env_path) if _env_path.exists() else {}
ANTHROPIC_API_KEY = _file_values.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL") or "claude-sonnet-4-6"

# LiteLLM proxy (used only if ANTHROPIC_API_KEY is unset — see llm/gateway.backend_name())
LITELLM_BASE_URL = os.getenv("LITELLM_BASE_URL", "")
LITELLM_API_KEY = os.getenv("LITELLM_API_KEY", "")

HUBSPOT_ACCESS_TOKEN = os.getenv("HUBSPOT_ACCESS_TOKEN", "")
HUBSPOT_PORTAL_ID = os.getenv("HUBSPOT_PORTAL_ID", "")

# Optional — only needed for audience_builder/tools.py's snowflake_query tool
# (used by the discovery agent to look up past event editions). Read directly
# via os.environ in audience_builder/tools.py, not exposed as named constants
# here, matching emailcreationskill/backend/config.py's pattern. If unset,
# snowflake_query() raises a clear RuntimeError rather than silently no-op'ing:
#   SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_PRIVATE_KEY (required)
#   SNOWFLAKE_DATABASE (default ANALYTICS), SNOWFLAKE_SCHEMA (default Silver_Segment)
#   SNOWFLAKE_WAREHOUSE, SNOWFLAKE_ROLE (optional)
