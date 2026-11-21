"""Các trang web và endpoint của ứng dụng."""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import os
import secrets
import uuid

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template, request,
                   send_file, session, url_for)
from werkzeug.utils import secure_filename

from . import auth, worker
from . import workflow as wf
from .services import log, now_iso

bp = Blueprint("main", __name__)

# Phần mở rộng được phép -> (content type, chữ ký đầu tệp để đối chiếu nội dung thật)
ALLOWED_FILES = {
    ".pdf": ("application/pdf", b"%PDF-"),
    ".png": ("image/png", b"\x89PNG\r\n\x1a\n"),
    ".jpg": ("image/jpeg", b"\xff\xd8\xff"),
    ".jpeg": ("image/jpeg", b"\xff\xd8\xff"),
    ".docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document",
              b"PK\x03\x04"),
    ".xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
              b"PK\x03\x04"),
}
PUBLIC_ENDPOINTS = {"main.healthz", "main.pubsub_push", "static"}


def svc():
    return current_app.extensions["svc"]


# --------------------------------------------------------------------------- hooks
@bp.before_app_request
def before_request():
    g.user = None
    if request.endpoint in PUBLIC_ENDPOINTS:
        return
    g.user = auth.resolve_user(current_app, svc().repo)
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    if request.method == "POST":
        sent = request.form.get("csrf_token", "")
        if not hmac.compare_digest(session["csrf"], sent):
            abort(400, description="Phiên làm việc đã hết hạn. Hãy tải lại trang và thử lại.")


@bp.after_app_request
def security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Content-Security-Policy",
                                "default-src 'self'; frame-ancestors 'none'")
    return response


@bp.app_context_processor
def inject_globals():
    unread = 0
    if g.get("user"):
        unread = sum(1 for n in svc().repo.list_notifications(g.user["email"]) if not n["read"])
    return {
        "user": g.get("user"),
        "unread": unread,
        "csrf_token": session.get("csrf", ""),
        "STATUS_LABELS": wf.STATUS_LABELS,
        "ROLES": wf.ROLES,
        "DOC_TYPES": wf.DOC_TYPES,
        "DEPARTMENTS": wf.DEPARTMENTS,
        "ACTION_LABELS": wf.ACTION_LABELS,
        "auth_mode": current_app.config["AUTH_MODE"],
        "threshold": current_app.config["LEVEL2_THRESHOLD"],
    }


@bp.app_errorhandler(400)
@bp.app_errorhandler(401)
@bp.app_errorhandler(403)
@bp.app_errorhandler(404)
@bp.app_errorhandler(413)
def handle_error(error):
    messages = {
        400: "Yêu cầu không hợp lệ.",
        401: "Bạn chưa đăng nhập.",
        403: "Bạn không có quyền thực hiện thao tác này.",
        404: "Không tìm thấy nội dung.",
        413: "Tệp vượt quá giới hạn 10 MB.",
    }
    detail = error.description if error.code == 400 and "Phiên" in str(error.description) else None
    return render_template("error.html", code=error.code,
                           message=detail or messages.get(error.code, "Có lỗi xảy ra.")), error.code


# --------------------------------------------------------------------------- helpers
def visible_documents(user: dict) -> list[dict]:
    repo = svc().repo
    if user["role"] in ("admin", "accountant"):
        return repo.list_documents()
    if user["role"] == "manager":
        docs = {d["id"]: d for d in repo.list_documents(department=user["department"])}
        docs.update({d["id"]: d for d in repo.list_documents(submitter=user["email"])})
        return sorted(docs.values(), key=lambda d: d["created_at"], reverse=True)
    return repo.list_documents(submitter=user["email"])


def get_viewable_document(doc_id: str) -> dict:
    doc = svc().repo.get_document(doc_id)
    if doc is None:
        abort(404)
    if not wf.can_view(g.user, doc):
        abort(403)
    return doc


def parse_amount(raw: str) -> int:
    digits = (raw or "").replace(".", "").replace(",", "").replace(" ", "")
    if not digits.isdigit():
        raise ValueError("Số tiền phải là số nguyên không âm (đơn vị: đồng).")
    amount = int(digits)
    if amount > 10 ** 12:
        raise ValueError("Số tiền vượt quá giới hạn cho phép.")
    return amount


def read_upload(doc_id: str) -> dict:
    """Kiểm tra tệp tải lên, lưu vào kho tệp và trả về siêu dữ liệu của tệp."""
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        raise ValueError("Hãy chọn tệp chứng từ.")
    ext = os.path.splitext(upload.filename)[1].lower()
    if ext not in ALLOWED_FILES:
        raise ValueError("Chỉ nhận tệp PDF, PNG, JPG, DOCX hoặc XLSX.")
    content_type, magic = ALLOWED_FILES[ext]
    data = upload.read()
    if not data:
        raise ValueError("Tệp rỗng.")
    if not data.startswith(magic):
        raise ValueError("Nội dung tệp không khớp với phần mở rộng.")
    stem = secure_filename(os.path.splitext(upload.filename)[0]) or "chungtu"
    object_name = f"documents/{doc_id}/{uuid.uuid4().hex}/{stem}{ext}"
    svc().storage.save(object_name, data, content_type)
    return {
        "object_name": object_name,
        "filename": os.path.basename(upload.filename.replace("\\", "/")),
        "content_type": content_type,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def publish(event: dict) -> None:
    """Phát sự kiện. Lỗi phát tin không làm hỏng thao tác đã được ghi vào cơ sở dữ liệu."""
    try:
        svc().publisher.publish(event)
    except Exception as exc:
        log("ERROR", "Không phát được sự kiện", event_type=event["type"],
            doc_id=event["doc_id"], error=str(exc))


# --------------------------------------------------------------------------- đăng nhập demo
@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_app.config["AUTH_MODE"] != "demo":
        abort(404)
    if request.method == "POST":
        user = svc().repo.get_user(request.form.get("email", ""))
        if user is None:
            abort(400)
        session["email"] = user["email"]
        return redirect(url_for("main.dashboard"))
    order = list(wf.ROLES)
    people = sorted(svc().repo.list_users(), key=lambda u: (order.index(u["role"]), u["email"]))
    return render_template("login.html", users=people)


@bp.post("/logout")
def logout():
    session.pop("email", None)
    return redirect(url_for("main.login") if current_app.config["AUTH_MODE"] == "demo"
                    else url_for("main.dashboard"))


# --------------------------------------------------------------------------- chứng từ
@bp.get("/")
@auth.login_required
def dashboard():
    docs = visible_documents(g.user)
    todo = [d for d in docs if wf.can_decide(g.user, d)]
    mine = [d for d in docs if d["submitter"] == g.user["email"]]
    counts = {status: sum(1 for d in docs if d["status"] == status) for status in wf.STATUS_LABELS}
    return render_template("dashboard.html", todo=todo, mine=mine[:8], counts=counts,
                           total=len(docs))


@bp.get("/documents")
@auth.login_required
def list_documents():
    docs = visible_documents(g.user)
    status = request.args.get("status", "")
    doc_type = request.args.get("type", "")
    keyword = request.args.get("q", "").strip().lower()
    if status in wf.STATUS_LABELS:
        docs = [d for d in docs if d["status"] == status]
    if doc_type in wf.DOC_TYPES:
        docs = [d for d in docs if d["type"] == doc_type]
    if keyword:
        docs = [d for d in docs
                if keyword in d["title"].lower() or keyword in d["code"].lower()
                or keyword in d["submitter_name"].lower()]
    return render_template("list.html", docs=docs, status=status, doc_type=doc_type,
                           keyword=request.args.get("q", ""))


@bp.get("/documents/new")
@auth.login_required
def new_document():
    return render_template("new.html", form={})


@bp.post("/documents")
@auth.login_required
def create_document():
    form = request.form
    doc_id = uuid.uuid4().hex
    try:
        title = form.get("title", "").strip()
        if not 3 <= len(title) <= 150:
            raise ValueError("Tiêu đề cần từ 3 đến 150 ký tự.")
        if form.get("type") not in wf.DOC_TYPES:
            raise ValueError("Hãy chọn loại chứng từ.")
        amount = parse_amount(form.get("amount", ""))
        description = form.get("description", "").strip()[:1000]
        file_meta = read_upload(doc_id)
    except ValueError as exc:
        flash(str(exc), "error")
        return render_template("new.html", form=form), 400

    now = now_iso()
    doc = {
        "id": doc_id,
        "code": svc().repo.next_code(),
        "title": title,
        "type": form["type"],
        "amount": amount,
        "description": description,
        "department": g.user["department"],
        "submitter": g.user["email"],
        "submitter_name": g.user["name"],
        "status": wf.initial_status(g.user),
        "versions": [{**file_meta, "version": 1, "uploaded_at": now,
                      "uploaded_by": g.user["email"]}],
        "approvals": [],
        "created_at": now,
        "updated_at": now,
    }
    audit, event = wf.submit(doc, g.user, now)
    svc().repo.create_document(doc, audit)
    publish(event)
    log("INFO", "Đã tiếp nhận chứng từ", doc_id=doc_id, code=doc["code"], actor=g.user["email"])
    flash(f"Đã nộp chứng từ {doc['code']}.", "success")
    return redirect(url_for("main.document_detail", doc_id=doc_id))


@bp.get("/documents/<doc_id>")
@auth.login_required
def document_detail(doc_id):
    doc = get_viewable_document(doc_id)
    return render_template("detail.html", doc=doc, history=svc().repo.list_audit(doc_id),
                           can_decide=wf.can_decide(g.user, doc),
                           can_resubmit=wf.can_resubmit(g.user, doc))


@bp.post("/documents/<doc_id>/decision")
@auth.login_required
def decide(doc_id):
    get_viewable_document(doc_id)
    action = request.form.get("action", "")
    comment = request.form.get("comment", "")[:500]
    threshold = current_app.config["LEVEL2_THRESHOLD"]
    now = now_iso()
    events = []

    def change(doc):
        updates, audit, event = wf.decide(doc, g.user, action, comment, threshold, now)
        events[:] = [event]  # transaction có thể chạy lại: chỉ giữ sự kiện của lần cuối
        return updates, audit

    try:
        doc = svc().repo.transition(doc_id, change)
    except wf.WorkflowError as exc:
        flash(str(exc), "error")
        return redirect(url_for("main.document_detail", doc_id=doc_id))
    publish(events[0])
    log("INFO", "Đã xử lý chứng từ", doc_id=doc_id, action=action, status=doc["status"],
        actor=g.user["email"])
    flash(f"Chứng từ {doc['code']}: {wf.STATUS_LABELS[doc['status']].lower()}.", "success")
    return redirect(url_for("main.document_detail", doc_id=doc_id))


@bp.post("/documents/<doc_id>/resubmit")
@auth.login_required
def resubmit(doc_id):
    doc = get_viewable_document(doc_id)
    if not wf.can_resubmit(g.user, doc):
        abort(403)
    try:
        file_meta = read_upload(doc_id)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("main.document_detail", doc_id=doc_id))
    note = request.form.get("comment", "")[:500]
    now = now_iso()
    events = []

    def change(current):
        updates, audit, event = wf.resubmit(current, g.user, file_meta, note, now)
        events[:] = [event]
        return updates, audit

    try:
        doc = svc().repo.transition(doc_id, change)
    except wf.WorkflowError as exc:
        flash(str(exc), "error")
        return redirect(url_for("main.document_detail", doc_id=doc_id))
    publish(events[0])
    flash(f"Đã nộp lại chứng từ {doc['code']} (phiên bản {len(doc['versions'])}).", "success")
    return redirect(url_for("main.document_detail", doc_id=doc_id))


@bp.get("/documents/<doc_id>/file/<int:version>")
@auth.login_required
def download(doc_id, version):
    doc = get_viewable_document(doc_id)
    meta = next((v for v in doc["versions"] if v["version"] == version), None)
    if meta is None:
        abort(404)
    log("INFO", "Tải tệp chứng từ", doc_id=doc_id, version=version, actor=g.user["email"])
    try:
        url = svc().storage.signed_url(meta["object_name"], meta["filename"])
    except Exception as exc:  # thiếu quyền ký: vẫn phục vụ tệp qua ứng dụng
        log("WARNING", "Không tạo được URL ký, gửi tệp qua ứng dụng", error=str(exc))
        url = None
    if url:
        return redirect(url)
    data = svc().storage.read(meta["object_name"])
    return send_file(io.BytesIO(data), mimetype=meta["content_type"], as_attachment=True,
                     download_name=meta["filename"])


# --------------------------------------------------------------------------- thông báo
@bp.get("/notifications")
@auth.login_required
def notifications():
    items = svc().repo.list_notifications(g.user["email"])
    svc().repo.mark_notifications_read(g.user["email"])
    return render_template("notifications.html", items=items)


# --------------------------------------------------------------------------- quản trị
@bp.get("/admin/audit")
@auth.roles_required("admin", "accountant")
def audit_log():
    return render_template("audit.html", rows=svc().repo.list_audit())


@bp.route("/admin/users", methods=["GET", "POST"])
@auth.roles_required("admin")
def users():
    repo = svc().repo
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        name = request.form.get("name", "").strip()[:80]
        role = request.form.get("role")
        department = request.form.get("department")
        if "@" not in email or role not in wf.ROLES or department not in wf.DEPARTMENTS:
            flash("Thông tin người dùng không hợp lệ.", "error")
        elif email == g.user["email"] and role != "admin":
            flash("Không thể tự hạ quyền quản trị của chính mình.", "error")
        else:
            existing = repo.get_user(email) or {}
            repo.upsert_user({"email": email, "role": role, "department": department,
                              "name": name or existing.get("name") or email.split("@")[0]})
            log("NOTICE", "Cập nhật người dùng", target=email, role=role, actor=g.user["email"])
            flash(f"Đã lưu người dùng {email}.", "success")
        return redirect(url_for("main.users"))
    return render_template("users.html", users=repo.list_users())


# --------------------------------------------------------------------------- hạ tầng
@bp.get("/healthz")
def healthz():
    return {"status": "ok"}


@bp.post("/internal/pubsub")
def pubsub_push():
    """Nhận tin đẩy từ Pub/Sub (chỉ bật trên dịch vụ worker).

    Dịch vụ worker được triển khai với --no-allow-unauthenticated, nên Cloud Run đã kiểm tra
    OIDC token của Pub/Sub trước khi request tới đây.
    Trả về 2xx nghĩa là xác nhận (ack); mã khác khiến Pub/Sub giao lại tin.
    """
    if not current_app.config["ENABLE_WORKER"]:
        abort(404)
    envelope = request.get_json(silent=True) or {}
    message = envelope.get("message") or {}
    try:
        event = json.loads(base64.b64decode(message.get("data", "")).decode("utf-8"))
        required = ("id", "type", "doc_id", "code", "title", "status", "submitter", "department")
        if not all(key in event for key in required):
            raise ValueError("thiếu trường bắt buộc")
    except Exception as exc:
        # Tin hỏng thì giao lại bao nhiêu lần cũng hỏng: ghi log rồi xác nhận để bỏ qua
        log("ERROR", "Bỏ qua tin Pub/Sub không hợp lệ", error=str(exc),
            message_id=message.get("messageId"))
        return "", 204
    count = worker.handle_event(svc().repo, event)
    log("INFO", "Đã xử lý sự kiện", event_type=event["type"], doc_id=event["doc_id"],
        notifications=count, message_id=message.get("messageId"))
    return "", 204
