import os

from flask import Flask
from flask_cors import CORS
from flask_smorest import Api

from .auth import seed_admin_if_missing
from .routes.api import blp as api_blp, storage as api_storage
from .routes.health import blp as health_blp


def _frontend_origin() -> str:
    """
    Frontend origin for CORS.

    Env:
      - MOBIKE_FRONTEND_ORIGIN (default: http://localhost:3000)
    """
    return os.environ.get("MOBIKE_FRONTEND_ORIGIN", "http://localhost:3000")


app = Flask(__name__)
app.url_map.strict_slashes = False

# Allow React dev server and optionally other origins if configured.
CORS(
    app,
    resources={r"/*": {"origins": [_frontend_origin(), "http://localhost:3000"]}},
    supports_credentials=False,
)

app.config["API_TITLE"] = "Mobike Bike Rental API"
app.config["API_VERSION"] = "v1"
app.config["OPENAPI_VERSION"] = "3.0.3"
app.config["OPENAPI_URL_PREFIX"] = "/docs"
app.config["OPENAPI_SWAGGER_UI_PATH"] = ""
app.config["OPENAPI_SWAGGER_UI_URL"] = "https://cdn.jsdelivr.net/npm/swagger-ui-dist/"


api = Api(app)
api.register_blueprint(health_blp)
api.register_blueprint(api_blp)

# Ensure seed users have usable passwords on first run.
seed_admin_if_missing(api_storage)
