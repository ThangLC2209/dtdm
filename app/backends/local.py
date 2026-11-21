"""Backend chạy trên máy cá nhân: dữ liệu trong một tệp JSON, tệp chứng từ trên đĩa.

Cùng giao diện với backend Google Cloud (xem gcp.py) để mã nghiệp vụ không phải thay đổi.
"""
from __future__ import annotations

import copy
import json
import os
import threading
from datetime import datetime, timedelta, timezone

VN_TZ = timezone(timedelta(hours=7))


class LocalRepo:
    def __init__(self, data_dir: str):
        os.makedirs(data_dir, exist_ok=True)
        self._path = os.path.join(data_dir, "db.json")
        self._lock = threading.RLock()
        self._db = {"users": {}, "documents": {}, "audit_log": [], "notifications": {},
                    "counters": {}}
        if os.path.exists(self._path):
            with open(self._path, encoding="utf-8") as f:
                self._db.update(json.load(f))

    def _save(self) -> None:
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._db, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self._path)  # ghi nguyên tử, tránh hỏng tệp khi tắt đột ngột

    # ---- người dùng ----
    def get_user(self, email: str) -> dict | None:
        with self._lock:
            return copy.deepcopy(self._db["users"].get(email))

    def list_users(self) -> list[dict]:
        with self._lock:
            return sorted(copy.deepcopy(list(self._db["users"].values())),
                          key=lambda u: u["email"])

    def upsert_user(self, user: dict) -> None:
        with self._lock:
            self._db["users"][user["email"]] = copy.deepcopy(user)
            self._save()

    # ---- chứng từ ----
    def next_code(self) -> str:
        year = datetime.now(VN_TZ).year
        with self._lock:
            key = f"documents-{year}"
            n = self._db["counters"].get(key, 0) + 1
            self._db["counters"][key] = n
            self._save()
        return f"CT-{year}-{n:04d}"

    def create_document(self, doc: dict, audit: dict) -> None:
        with self._lock:
            self._db["documents"][doc["id"]] = copy.deepcopy(doc)
            self._db["audit_log"].append(copy.deepcopy(audit))
            self._save()

    def get_document(self, doc_id: str) -> dict | None:
        with self._lock:
            return copy.deepcopy(self._db["documents"].get(doc_id))

    def list_documents(self, submitter: str | None = None,
                       department: str | None = None) -> list[dict]:
        with self._lock:
            docs = copy.deepcopy(list(self._db["documents"].values()))
        if submitter:
            docs = [d for d in docs if d["submitter"] == submitter]
        if department:
            docs = [d for d in docs if d["department"] == department]
        return sorted(docs, key=lambda d: d["created_at"], reverse=True)

    def transition(self, doc_id: str, fn) -> dict:
        """Đọc - kiểm tra - ghi trong một khối khóa (tương đương transaction của Firestore)."""
        with self._lock:
            doc = self._db["documents"].get(doc_id)
            if doc is None:
                raise KeyError(doc_id)
            updates, audit = fn(copy.deepcopy(doc))
            doc.update(copy.deepcopy(updates))
            self._db["audit_log"].append(copy.deepcopy(audit))
            self._save()
            return copy.deepcopy(doc)

    # ---- nhật ký ----
    def list_audit(self, doc_id: str | None = None, limit: int = 200) -> list[dict]:
        with self._lock:
            rows = copy.deepcopy(self._db["audit_log"])
        if doc_id:
            rows = [r for r in rows if r["doc_id"] == doc_id]
            return sorted(rows, key=lambda r: r["at"])
        return sorted(rows, key=lambda r: r["at"], reverse=True)[:limit]

    # ---- thông báo ----
    def add_notification(self, n: dict) -> None:
        with self._lock:
            # Khóa theo id nên ghi trùng (Pub/Sub giao lại tin) không tạo bản sao
            self._db["notifications"].setdefault(n["id"], copy.deepcopy(n))
            self._save()

    def list_notifications(self, email: str, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = [copy.deepcopy(n) for n in self._db["notifications"].values()
                    if n["to"] == email]
        return sorted(rows, key=lambda n: n["at"], reverse=True)[:limit]

    def mark_notifications_read(self, email: str) -> None:
        with self._lock:
            for n in self._db["notifications"].values():
                if n["to"] == email:
                    n["read"] = True
            self._save()


class LocalStorage:
    """Lưu tệp trên đĩa; không có URL ký nên ứng dụng tự gửi tệp về trình duyệt."""

    def __init__(self, data_dir: str):
        self._root = os.path.abspath(os.path.join(data_dir, "files"))
        os.makedirs(self._root, exist_ok=True)

    def _full(self, name: str) -> str:
        path = os.path.abspath(os.path.join(self._root, name))
        if not path.startswith(self._root + os.sep):
            raise ValueError("Đường dẫn tệp không hợp lệ")
        return path

    def save(self, name: str, data: bytes, content_type: str) -> None:
        path = self._full(name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)

    def read(self, name: str) -> bytes:
        with open(self._full(name), "rb") as f:
            return f.read()

    def signed_url(self, name: str, filename: str, minutes: int = 5) -> str | None:
        return None


class LocalPublisher:
    """Không có Pub/Sub: gọi thẳng hàm xử lý sự kiện trong cùng tiến trình."""

    def __init__(self, handler):
        self._handler = handler

    def publish(self, event: dict) -> None:
        self._handler(event)
