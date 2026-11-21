"""Khởi tạo các thành phần hạ tầng theo cấu hình (local hoặc Google Cloud)."""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

from . import worker

DEMO_USERS = [
    ("an.nguyen@example.com", "Nguyễn Văn An", "employee", "Kinh doanh"),
    ("binh.tran@example.com", "Trần Thị Bình", "employee", "Kỹ thuật"),
    ("cuong.le@example.com", "Lê Minh Cường", "manager", "Kinh doanh"),
    ("dung.pham@example.com", "Phạm Thị Dung", "manager", "Kỹ thuật"),
    ("hoa.vu@example.com", "Vũ Thị Hoa", "accountant", "Tài chính - Kế toán"),
    ("admin@example.com", "Quản trị viên", "admin", "Hành chính - Nhân sự"),
]


def now_iso() -> str:
    """Thời điểm hiện tại theo UTC, dạng ISO 8601 (so sánh chuỗi cũng đúng thứ tự thời gian)."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def log(severity: str, message: str, **fields) -> None:
    """Ghi log dạng JSON ra stdout; Cloud Logging tự nhận trường severity và message."""
    print(json.dumps({"severity": severity, "message": message, **fields}, ensure_ascii=False),
          file=sys.stdout, flush=True)


@dataclass
class Services:
    repo: object
    storage: object
    publisher: object


def build_services(config: dict) -> Services:
    if config["BACKEND"] == "gcp":
        from .backends import gcp
        repo = gcp.FirestoreRepo(config.get("GCP_PROJECT"))
        storage = gcp.GcsStorage(config["BUCKET"])
        publisher = gcp.PubSubPublisher(config.get("GCP_PROJECT"), config["PUBSUB_TOPIC"])
    else:
        from .backends import local
        repo = local.LocalRepo(config["DATA_DIR"])
        storage = local.LocalStorage(config["DATA_DIR"])
        publisher = local.LocalPublisher(lambda event: worker.handle_event(repo, event))

    if config["AUTH_MODE"] == "demo" and not config["ENABLE_WORKER"] and not repo.list_users():
        for email, name, role, department in DEMO_USERS:
            repo.upsert_user({"email": email, "name": name, "role": role,
                              "department": department})
        log("INFO", "Đã tạo tài khoản mẫu cho chế độ demo", count=len(DEMO_USERS))
    return Services(repo=repo, storage=storage, publisher=publisher)
