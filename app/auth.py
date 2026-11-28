"""Xác thực người dùng bằng chế độ demo local hoặc Microsoft Entra ID."""
from __future__ import annotations

from functools import wraps

from flask import abort, current_app, g, redirect, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .services import log

# Trạng thái tài khoản ở chế độ đăng nhập bằng mật khẩu
PENDING = "pending"    # đã đăng ký, chờ quản trị viên duyệt
ACTIVE = "active"      # được phép đăng nhập
REJECTED = "rejected"  # quản trị viên từ chối hoặc khóa

STATUS_LABELS = {PENDING: "Chờ duyệt", ACTIVE: "Đang hoạt động", REJECTED: "Đã khóa"}

MIN_PASSWORD_LENGTH = 8

# Hash giả để so sánh khi email không tồn tại, tránh lộ email qua thời gian phản hồi
_DUMMY_HASH = generate_password_hash("khong-dung-mat-khau-nay")


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(user: dict | None, password: str) -> bool:
    if not user or not user.get("password_hash"):
        check_password_hash(_DUMMY_HASH, password)
        return False
    return check_password_hash(user["password_hash"], password)


def is_active(user: dict | None) -> bool:
    # Tài khoản cũ (demo/Entra) không có trường status được coi là đang hoạt động
    return bool(user) and user.get("status", ACTIVE) == ACTIVE


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
    user = repo.get_user(email) if email else None
    if app.config["AUTH_MODE"] == "password" and not is_active(user):
        # Tài khoản bị khóa sau khi đăng nhập sẽ mất quyền ngay ở request kế tiếp
        return None
    return user


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if g.user is None:
            if current_app.config["AUTH_MODE"] in ("demo", "entra", "password"):
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
