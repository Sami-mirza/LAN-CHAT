"""Flask application factory for LAN Chat."""

from __future__ import annotations

from flask import Flask

from config import Config
import routes


def create_app(cfg: Config) -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
        static_url_path="/static",
    )
    app.config["JSON_SORT_KEYS"] = False
    routes.init_routes(app, cfg)
    return app