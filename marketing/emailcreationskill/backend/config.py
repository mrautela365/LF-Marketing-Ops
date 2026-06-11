import os
from pathlib import Path
from dotenv import load_dotenv, dotenv_values

_env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=_env_path, override=False)

# Claude Code injects its own ANTHROPIC_API_KEY session token into the subprocess
# environment. That token is NOT valid for direct Anthropic API calls.
# Only trust a key that was explicitly written in the .env file.
_file_values = dotenv_values(dotenv_path=_env_path) if _env_path.exists() else {}
ANTHROPIC_API_KEY = _file_values.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

HUBSPOT_ACCESS_TOKEN = os.getenv("HUBSPOT_ACCESS_TOKEN", "")
HUBSPOT_PORTAL_ID = os.getenv("HUBSPOT_PORTAL_ID", "8112310")

GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "")
