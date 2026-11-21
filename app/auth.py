"""Xác định người dùng hiện tại.

demo: người trình diễn chọn một tài khoản mẫu, email được giữ trong session cookie đã ký.
iap:  Identity-Aware Proxy đã xác thực người dùng bằng tài khoản Google trước khi request
      tới ứng dụng, và gắn một JWT đã ký vào header X-Goog-IAP-JWT-Assertion.
      Ứng dụng kiểm tra chữ ký, hạn dùng và audience của JWT rồi mới tin email trong đó.
"""
from __future__ import annotations

from functools import wraps

from flask import abort, current_app, g, redirect, request, session, url_for

from .services import log

IAP_CERTS_URL = "https://www.gstatic.com/iap/verify/public_key"


def _email_from_iap(app) -> str | None:
    token = request.headers.get("X-Goog-IAP-JWT-Assertion")
    if not token:
        return None
    from google.auth.transport import requests as ga_requests
    from google.oauth2 import id_token
    try:
        claims = id_token.verify_token(token, ga_requests.Request(),
                                       audience=app.config["IAP_AUDIENCE"],
                                       certs_url=IAP_CERTS_URL)
    except Exception as exc:  # chữ ký sai, hết hạn hoặc sai audience
        log("WARNING", "JWT của IAP không hợp lệ", error=str(exc))
        return None
    return (claims.get("email") or "").lower() or None


def resolve_user(app, repo) -> dict | None:
    if app.config["AUTH_MODE"] == "iap":
        email = _email_from_iap(app)
        if not email:
            return None
        user = repo.get_user(email)
        if user is None:
            # Lần đầu đăng nhập: tạo hồ sơ với quyền thấp nhất; quản trị viên nâng quyền sau
            role = "admin" if email in app.config["ADMIN_EMAILS"] else "employee"
            user = {"email": email, "name": email.split("@")[0], "role": role,
                    "department": "Hành chính - Nhân sự"}
            repo.upsert_user(user)
            log("INFO", "Tạo hồ sơ người dùng mới", email=email, role=role)
        return user
    email = session.get("email")
    return repo.get_user(email) if email else None


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if g.user is None:
            if current_app.config["AUTH_MODE"] == "demo":
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
