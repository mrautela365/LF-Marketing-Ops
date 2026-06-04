from pathlib import Path
from pydantic_settings import BaseSettings
from typing import Optional

# Look for .env in current working directory AND in the email_service folder
_possible_env = [
    Path(".env"),
    Path(__file__).parent / ".env",
    Path(__file__).parent.parent / ".env",
]
_env_file = next((str(p) for p in _possible_env if p.exists()), ".env")


class Settings(BaseSettings):
    anthropic_api_key: Optional[str] = None
    hubspot_access_token: Optional[str] = None
    asana_token: Optional[str] = None
    google_credentials_path: Optional[str] = None
    hubspot_portal_id: str = "8112310"

    model_config = {"env_file": _env_file, "env_file_encoding": "utf-8"}


settings = Settings()
print(f"[config] env_file={_env_file} | api_key={'SET' if settings.anthropic_api_key else 'NOT SET'}")
