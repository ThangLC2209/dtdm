"""Xác thực người dùng bằng chế độ demo local hoặc Microsoft Entra ID."""
from __future__ import annotations

from functools import wraps

from flask import abort, current_app, g, redirect, session, url_for

from .services import log


def resolve_user(app, repo) -> dict | None:
    if app.config["AUTH_MODE"] == "entra":
        claims = session.get("entra_user")
        if not claims:
            return None
        email = (claims.get("preferred_username") or claims.get("email") or "").lower()
        if not email:
            return None
        user = repo.get_user(email)
        if user is None:
            # Hồ sơ mới luôn mặc định quyền nhân viên; chỉ email cấu hình mới là quản trị.
            role = "admin" if email in app.config["ADMIN_EMAILS"] else "employee"
            user = {"email": email, "name": claims.get("name") or email.split("@")[0],
                    "role": role, "department": "Hành chính - Nhân sự"}
            repo.upsert_user(user)
            log("INFO", "Đã tạo hồ sơ người dùng Microsoft mới", email=email, role=role)
        return user
    email = session.get("email")
    return repo.get_user(email) if email else None


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if g.user is None:
            if current_app.config["AUTH_MODE"] in ("demo", "entra"):
                return redirect(url_for("main.login"))
            abort(401)
        return view(*args, **kwargs)
    return wrapper


def roles_required(*roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapper(*args, **kwargs):
            if g.user["role"] not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapper
    return decorator
