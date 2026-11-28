"""Kiểm thử đầu-cuối qua HTTP với backend local (không cần Google Cloud)."""
import base64
import io
import json
import re

import pytest

from app import create_app
from app import workflow as wf

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
AN, BINH = "an.nguyen@example.com", "binh.tran@example.com"
CUONG, DUNG = "cuong.le@example.com", "dung.pham@example.com"
HOA, ADMIN = "hoa.vu@example.com", "admin@example.com"


@pytest.fixture
def app(tmp_path):
    return create_app({"BACKEND": "local", "AUTH_MODE": "demo", "DATA_DIR": str(tmp_path),
                       "TESTING": True, "SECRET_KEY": "test"})


@pytest.fixture
def repo(app):
    return app.extensions["svc"].repo


class Browser:
    """Một phiên trình duyệt: tự đính kèm CSRF token như biểu mẫu thật."""

    def __init__(self, app, email=None):
        self.client = app.test_client()
        if email:
            self.post("/login", {"email": email})

    def csrf(self):
        self.client.get("/healthz")
        with self.client.session_transaction() as session:
            if "csrf" not in session:
                session["csrf"] = "t" * 32
            return session["csrf"]

    def get(self, url):
        return self.client.get(url)

    def post(self, url, data=None, follow=False):
        payload = {"csrf_token": self.csrf(), **(data or {})}
        return self.client.post(url, data=payload, content_type="multipart/form-data",
                                follow_redirects=follow)

    def submit(self, amount="5.000.000", title="Hóa đơn thuê văn phòng", content=PDF,
               filename="hoa-don.pdf"):
        return self.post("/documents", {"title": title, "type": "invoice", "amount": amount,
                                        "description": "Tháng 11",
                                        "file": (io.BytesIO(content), filename)})


def doc_id_of(response):
    return re.search(r"/documents/([0-9a-f]{32})", response.headers["Location"]).group(1)


def test_requires_login(app):
    response = Browser(app).get("/")
    assert response.status_code == 302 and response.headers["Location"].endswith("/login")


def test_submit_stores_file_metadata_and_notifies_the_manager(app, repo):
    an = Browser(app, AN)
    response = an.submit()
    assert response.status_code == 302
    doc = repo.get_document(doc_id_of(response))
    assert doc["code"].startswith("CT-") and doc["code"].endswith("-0001")
    assert doc["status"] == wf.PENDING_L1 and doc["amount"] == 5_000_000
    version = doc["versions"][0]
    assert version["size"] == len(PDF) and len(version["sha256"]) == 64
    assert app.extensions["svc"].storage.read(version["object_name"]) == PDF
    assert [n["to"] for n in repo.list_notifications(CUONG)] == [CUONG]
    assert repo.list_notifications(DUNG) == []  # trưởng bộ phận khác không nhận


def test_two_level_approval_end_to_end(app, repo):
    doc_id = doc_id_of(Browser(app, AN).submit(amount="45.000.000"))
    Browser(app, CUONG).post(f"/documents/{doc_id}/decision", {"action": "approve"})
    assert repo.get_document(doc_id)["status"] == wf.PENDING_L2
    Browser(app, HOA).post(f"/documents/{doc_id}/decision",
                           {"action": "approve", "comment": "Đủ hồ sơ"})
    doc = repo.get_document(doc_id)
    assert doc["status"] == wf.APPROVED
    assert [a["level"] for a in doc["approvals"]] == [1, 2]
    assert [h["action"] for h in repo.list_audit(doc_id)] == ["submit", "approve", "approve"]
    messages = [n["message"] for n in repo.list_notifications(AN)]
    assert len(messages) == 2 and "Quy trình hoàn tất" in messages[0]


def test_reject_then_resubmit_creates_version_2(app, repo):
    an = Browser(app, AN)
    doc_id = doc_id_of(an.submit())
    cuong = Browser(app, CUONG)
    cuong.post(f"/documents/{doc_id}/decision", {"action": "reject"})  # thiếu lý do
    assert repo.get_document(doc_id)["status"] == wf.PENDING_L1
    cuong.post(f"/documents/{doc_id}/decision", {"action": "reject", "comment": "Sai số tiền"})
    assert repo.get_document(doc_id)["status"] == wf.REJECTED
    an.post(f"/documents/{doc_id}/resubmit",
            {"comment": "Đã sửa", "file": (io.BytesIO(PDF + b"v2"), "hoa-don-v2.pdf")})
    doc = repo.get_document(doc_id)
    assert doc["status"] == wf.PENDING_L1 and len(doc["versions"]) == 2
    assert an.get(f"/documents/{doc_id}/file/2").data == PDF + b"v2"
    assert an.get(f"/documents/{doc_id}/file/1").data == PDF  # phiên bản cũ vẫn còn


def test_access_control(app, repo):
    doc_id = doc_id_of(Browser(app, AN).submit())
    assert Browser(app, BINH).get(f"/documents/{doc_id}").status_code == 403
    assert Browser(app, BINH).get(f"/documents/{doc_id}/file/1").status_code == 403
    assert Browser(app, DUNG).get(f"/documents/{doc_id}").status_code == 403
    for email in (AN, CUONG, HOA, ADMIN):
        assert Browser(app, email).get(f"/documents/{doc_id}").status_code == 200
    # Người nộp và quản trị viên không duyệt được
    for email in (AN, ADMIN, HOA):
        Browser(app, email).post(f"/documents/{doc_id}/decision", {"action": "approve"})
    assert repo.get_document(doc_id)["status"] == wf.PENDING_L1
    assert Browser(app, AN).get("/admin/audit").status_code == 403
    assert Browser(app, HOA).get("/admin/users").status_code == 403
    assert Browser(app, ADMIN).get("/admin/users").status_code == 200


def test_a_decided_document_cannot_be_decided_twice(app, repo):
    doc_id = doc_id_of(Browser(app, AN).submit())
    cuong = Browser(app, CUONG)
    cuong.post(f"/documents/{doc_id}/decision", {"action": "approve"})
    cuong.post(f"/documents/{doc_id}/decision", {"action": "reject", "comment": "Đổi ý"})
    assert repo.get_document(doc_id)["status"] == wf.APPROVED
    assert len(repo.list_audit(doc_id)) == 2


@pytest.mark.parametrize("content, filename, amount", [
    (b"MZ\x90\x00 not a pdf", "virus.pdf", "1000"),      # nội dung không khớp phần mở rộng
    (PDF, "script.exe", "1000"),                          # phần mở rộng không cho phép
    (b"", "rong.pdf", "1000"),                            # tệp rỗng
    (PDF, "hoa-don.pdf", "mười triệu"),                   # số tiền sai
])
def test_invalid_submissions_are_rejected(app, repo, content, filename, amount):
    response = Browser(app, AN).submit(content=content, filename=filename, amount=amount)
    assert response.status_code == 400
    assert repo.list_documents() == []


def test_upload_over_10_mb_is_refused(app, repo):
    big = b"%PDF-" + b"0" * (10 * 1024 * 1024)
    assert Browser(app, AN).submit(content=big).status_code == 413
    assert repo.list_documents() == []


def test_post_without_csrf_token_is_refused(app, repo):
    client = app.test_client()
    client.post("/login", data={"email": AN})
    with client.session_transaction() as session:
        assert "email" not in session
    assert client.post("/documents", data={"title": "x"}).status_code == 400


def test_list_filters(app):
    an = Browser(app, AN)
    an.submit(title="Hóa đơn điện")
    an.submit(title="Hợp đồng bảo trì", amount="30.000.000")
    page = an.get("/documents?q=bảo+trì").get_data(as_text=True)
    assert "Hợp đồng bảo trì" in page and "Hóa đơn điện" not in page
    assert "Hóa đơn điện" in an.get("/documents?status=PENDING_L1").get_data(as_text=True)
    assert "Không có chứng từ phù hợp" in an.get("/documents?status=APPROVED").get_data(as_text=True)


def test_admin_can_change_roles(app, repo):
    Browser(app, ADMIN).post("/admin/users", {"email": BINH, "name": "Trần Thị Bình",
                                              "role": "accountant",
                                              "department": "Tài chính - Kế toán"})
    assert repo.get_user(BINH)["role"] == "accountant"
    Browser(app, ADMIN).post("/admin/users", {"email": ADMIN, "role": "employee",
                                              "department": "Kinh doanh"})
    assert repo.get_user(ADMIN)["role"] == "admin"  # không tự hạ quyền


def envelope(event):
    data = base64.b64encode(json.dumps(event).encode()).decode()
    return {"message": {"data": data, "messageId": "m-1"}, "subscription": "s"}


def test_pubsub_endpoint_is_closed_on_the_web_service(app):
    assert app.test_client().post("/internal/pubsub", json=envelope({})).status_code == 404


def test_pubsub_push_is_idempotent(tmp_path):
    worker_app = create_app({"BACKEND": "local", "AUTH_MODE": "demo", "ENABLE_WORKER": True,
                             "DATA_DIR": str(tmp_path), "TESTING": True})
    repo = worker_app.extensions["svc"].repo
    repo.upsert_user({"email": CUONG, "name": "Cường", "role": "manager",
                      "department": "Kinh doanh"})
    event = {"id": "e1", "type": "document.submitted", "doc_id": "d1", "code": "CT-2026-0001",
             "title": "Hóa đơn", "department": "Kinh doanh", "submitter": AN,
             "status": wf.PENDING_L1, "actor": AN, "actor_name": "An", "comment": "",
             "at": "2026-11-16T03:00:00.000Z"}
    client = worker_app.test_client()
    for _ in range(3):  # Pub/Sub giao tin ít nhất một lần: có thể trùng
        assert client.post("/internal/pubsub", json=envelope(event)).status_code == 204
    assert len(repo.list_notifications(CUONG)) == 1
    # Tin hỏng được xác nhận để không bị giao lại mãi
    bad = {"message": {"data": "khong-phai-base64!!", "messageId": "m-2"}}
    assert client.post("/internal/pubsub", json=bad).status_code == 204


# --------------------------------------------------------------------------- đăng nhập mật khẩu
BOSS, NEW = "boss@congty.vn", "nv.moi@congty.vn"


@pytest.fixture
def pw_app(tmp_path):
    return create_app({"BACKEND": "local", "AUTH_MODE": "password", "DATA_DIR": str(tmp_path),
                       "TESTING": True, "SECRET_KEY": "test", "ADMIN_EMAILS": [BOSS]})


def register(browser, email, password="matkhau-123", confirm=None, name="Người Mới"):
    return browser.post("/register", {"email": email, "name": name, "department": "Kỹ thuật",
                                      "password": password, "confirm": confirm or password})


def pw_login(browser, email, password="matkhau-123"):
    return browser.post("/login", {"email": email, "password": password})


def test_password_mode_full_flow(pw_app):
    repo = pw_app.extensions["svc"].repo
    # Email trong ADMIN_EMAILS được kích hoạt ngay làm quản trị viên
    register(Browser(pw_app), BOSS, name="Sếp")
    assert repo.get_user(BOSS)["role"] == "admin" and repo.get_user(BOSS)["status"] == "active"

    # Nhân viên đăng ký: chờ duyệt, không đăng nhập được, mật khẩu không lưu dạng thô
    register(Browser(pw_app), NEW)
    stored = repo.get_user(NEW)
    assert stored["status"] == "pending" and stored["role"] == "employee"
    assert "matkhau-123" not in json.dumps(stored)
    staff = Browser(pw_app)
    pw_login(staff, NEW)
    assert staff.get("/").status_code == 302

    # Quản trị viên duyệt và cấp quyền trưởng bộ phận
    admin = Browser(pw_app)
    pw_login(admin, BOSS)
    assert NEW in admin.get("/admin/users").get_data(as_text=True)
    admin.post("/admin/users", {"email": NEW, "name": "Người Mới", "role": "manager",
                                "department": "Kỹ thuật", "action": "approve"})
    approved = repo.get_user(NEW)
    assert approved["status"] == "active" and approved["role"] == "manager"
    assert approved["password_hash"] == stored["password_hash"]  # không mất mật khẩu

    # Sau khi duyệt, nhân viên đăng nhập bằng email + mật khẩu là vào được
    staff = Browser(pw_app)
    assert pw_login(staff, NEW).headers["Location"].endswith("/")
    assert staff.get("/").status_code == 200

    # Khóa tài khoản: phiên đang mở mất quyền ngay
    admin.post("/admin/users", {"email": NEW, "action": "lock"})
    assert staff.get("/").status_code == 302


def test_password_login_rejects_bad_credentials(pw_app):
    register(Browser(pw_app), BOSS)
    b = Browser(pw_app)
    assert pw_login(b, BOSS, "sai-mat-khau").status_code == 200
    assert b.get("/").status_code == 302
    assert pw_login(b, "khong.co@congty.vn").status_code == 200
    assert b.get("/").status_code == 302


def test_registration_validation(pw_app):
    repo = pw_app.extensions["svc"].repo
    register(Browser(pw_app), NEW, password="ngan")
    assert repo.get_user(NEW) is None
    register(Browser(pw_app), NEW, password="matkhau-123", confirm="matkhau-456")
    assert repo.get_user(NEW) is None
    register(Browser(pw_app), NEW)
    original = repo.get_user(NEW)["password_hash"]
    register(Browser(pw_app), NEW, password="mat-khau-khac")  # không ghi đè tài khoản đã có
    assert repo.get_user(NEW)["password_hash"] == original


def test_employee_cannot_approve(pw_app):
    repo = pw_app.extensions["svc"].repo
    register(Browser(pw_app), BOSS)
    register(Browser(pw_app), NEW)
    admin = Browser(pw_app)
    pw_login(admin, BOSS)
    admin.post("/admin/users", {"email": NEW, "name": "Người Mới", "role": "employee",
                                "department": "Kỹ thuật", "action": "approve"})
    register(Browser(pw_app), "khac@congty.vn")
    staff = Browser(pw_app)
    pw_login(staff, NEW)
    response = staff.post("/admin/users", {"email": "khac@congty.vn", "role": "admin",
                                           "department": "Kỹ thuật", "action": "approve"})
    assert response.status_code == 403
    assert repo.get_user("khac@congty.vn")["status"] == "pending"


def test_register_page_is_closed_outside_password_mode(app):
    assert app.test_client().get("/register").status_code == 404
