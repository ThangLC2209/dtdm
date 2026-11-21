"""Ứng dụng tiếp nhận, lưu trữ và phê duyệt chứng từ."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import Flask

from .config import load_config
from .routes import bp
from .services import build_services

VN_TZ = timezone(timedelta(hours=7))


def format_money(value) -> str:
    return f"{int(value):,}".replace(",", ".") + " ₫"


def format_time(iso: str) -> str:
    """Chuỗi ISO (UTC) -> giờ Việt Nam, dạng dd/mm/yyyy HH:MM."""
    moment = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(VN_TZ)
    return moment.strftime("%d/%m/%Y %H:%M")


def format_size(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f} MB".replace(".", ",")
    return f"{max(1, round(size / 1024))} KB"


def create_app(overrides: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(load_config())
    if overrides:
        app.config.update(overrides)
    app.extensions["svc"] = build_services(app.config)
    app.jinja_env.filters.update(money=format_money, vntime=format_time, filesize=format_size)
    app.register_blueprint(bp)
    return app
