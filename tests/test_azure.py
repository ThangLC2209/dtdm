"""Kiểm thử backend Azure không cần tài nguyên Azure thật (SQLite thay Azure SQL, mock Service Bus)."""
import json
import sys
import types

import pytest

from app import create_app, worker
from app.backends import azure
from app.config import load_config, validate_config


@pytest.fixture
def repo(tmp_path):
    return azure.AzureSQLRepo(f"sqlite:///{tmp_path / 'chungtu.db'}")


def test_sql_repo_keeps_vietnamese_and_marks_notifications_read(repo):
    repo.upsert_user({"email": "an@congty.vn", "name": "Nguyễn Văn Ấn", "role": "employee",
                      "department": "Kỹ thuật"})
    assert repo.get_user("an@congty.vn")["name"] == "Nguyễn Văn Ấn"
    note = {"id": "e1__an@congty.vn", "to": "an@congty.vn", "doc_id": "d1", "code": "CT-1",
            "message": "Chứng từ đã được duyệt", "at": "2026-11-28T00:00:00.000Z", "read": False}
    repo.add_notification(note)
    repo.add_notification(note)  # idempotent: không tạo trùng
    assert len(repo.list_notifications("an@congty.vn")) == 1
    repo.mark_notifications_read("an@congty.vn")
    assert repo.list_notifications("an@congty.vn")[0]["read"] is True


def test_sql_repo_transition_writes_audit_atomically(repo):
    doc = {"id": "d1", "code": repo.next_code(), "status": "PENDING_L1", "created_at": "x"}
    repo.create_document(doc, {"id": "a1", "doc_id": "d1", "at": "1"})
    repo.transition("d1", lambda d: ({"status": "APPROVED"}, {"id": "a2", "doc_id": "d1", "at": "2"}))
    assert repo.get_document("d1")["status"] == "APPROVED"
    assert [a["id"] for a in repo.list_audit("d1")] == ["a1", "a2"]
    assert repo.next_code().endswith("0002")


def test_publisher_reuses_client_for_many_events(monkeypatch):
    sent = []

    class Sender:
        def __enter__(self): return self
        def __exit__(self, *exc): return False
        def send_messages(self, message): sent.append(message)

    class Client:
        closed = False
        def get_queue_sender(self, queue_name):
            assert not self.closed and queue_name == "q"
            return Sender()

    fake = types.ModuleType("azure.servicebus")
    fake.ServiceBusMessage = lambda body, message_id: (json.loads(body), message_id)
    monkeypatch.setitem(sys.modules, "azure.servicebus", fake)
    monkeypatch.setattr(azure, "servicebus_client", lambda conn, ns: Client())
    publisher = azure.AzureServiceBusPublisher(None, "chungtu-sb", "q")  # đúng 3 tham số như services.py
    publisher.publish({"id": "e1"})
    publisher.publish({"id": "e2"})
    assert [m[1] for m in sent] == ["e1", "e2"]


def test_worker_creates_notifications_from_event(repo):
    repo.upsert_user({"email": "sep@congty.vn", "name": "Sếp", "role": "manager", "department": "Kỹ thuật"})
    event = {"id": "e1", "type": "document.submitted", "doc_id": "d1", "code": "CT-1", "title": "Hóa đơn",
             "department": "Kỹ thuật", "submitter": "an@congty.vn", "status": "PENDING_L1",
             "actor": "an@congty.vn", "actor_name": "An", "comment": "", "at": "2026-11-28T00:00:00.000Z"}
    assert worker.handle_event(repo, event) == 1
    assert worker.handle_event(repo, event) == 1  # giao lại không tạo trùng
    assert len(repo.list_notifications("sep@congty.vn")) == 1


@pytest.mark.parametrize("overrides, problem", [
    ({"SECRET_KEY": "chi-dung-khi-chay-thu"}, "SECRET_KEY"),
    ({"SECRET_KEY": "ngan"}, "SECRET_KEY"),
    ({"AUTH_MODE": "demo"}, "AUTH_MODE=demo"),
    ({"ADMIN_EMAILS": []}, "ADMIN_EMAILS"),
])
def test_cloud_config_rejects_unsafe_settings(overrides, problem):
    config = {**load_config(), "BACKEND": "azure", "AUTH_MODE": "password",
              "SECRET_KEY": "x" * 40, "ADMIN_EMAILS": ["admin@congty.vn"], **overrides}
    with pytest.raises(RuntimeError, match=problem):
        validate_config(config)


def test_cloud_config_accepts_safe_settings():
    validate_config({**load_config(), "BACKEND": "azure", "AUTH_MODE": "password",
                     "SECRET_KEY": "x" * 40, "ADMIN_EMAILS": ["admin@congty.vn"]})


def test_create_app_refuses_unsafe_cloud_config():
    with pytest.raises(RuntimeError):
        create_app({"BACKEND": "azure", "AUTH_MODE": "demo"})
