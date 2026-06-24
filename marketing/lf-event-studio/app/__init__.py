import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv
from flask import Flask

# Load .env — use dotenv_values to correctly parse multi-line quoted values
# (e.g. SNOWFLAKE_PRIVATE_KEY) then inject into os.environ manually.
_env_path = Path(__file__).parent.parent / ".env"
load_dotenv(_env_path, override=True)

# Extra pass: dotenv_values handles multi-line double-quoted blocks correctly
for _k, _v in dotenv_values(_env_path).items():
    if _v is not None and not os.environ.get(_k):
        os.environ[_k] = _v


def create_app() -> Flask:
    app = Flask(__name__, template_folder="../templates")

    @app.after_request
    def add_cors(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response

    from .routes import bp
    app.register_blueprint(bp)
    return app
