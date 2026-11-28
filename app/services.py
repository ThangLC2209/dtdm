"""Khởi tạo các thành phần hạ tầng theo cấu hình."""
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
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def log(severity: str, message: str, **fields) -> None:
    print(json.dumps({"severity": severity, "message": message, **fields}, ensure_ascii=False),
          file=sys.stdout, flush=True)


@dataclass
class Services:
    repo: object
    storage: object
    publisher: object


def build_services(config: dict) -> Services:
    backend = config["BACKEND"]
    if backend == "azure":
        from .backends.azure import AzureBlobStorage, AzureSQLRepo, AzureServiceBusPublisher
        repo = AzureSQLRepo(config["AZURE_SQL_URL"])
        storage = AzureBlobStorage(config["AZURE_STORAGE_ACCOUNT_URL"], config["AZURE_STORAGE_CONTAINER"])
        publisher = AzureServiceBusPublisher(config["AZURE_SERVICEBUS_CONNECTION_STRING"],
                                             config["AZURE_SERVICEBUS_NAMESPACE"],
                                             config["AZURE_SERVICEBUS_QUEUE"])
        # Hàng đợi chỉ chuyển sự kiện; worker riêng (app/servicebus_worker.py) tạo thông báo
    elif backend == "gcp":
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
        log("INFO", "Đã tạo dữ liệu người dùng mẫu cho chế độ demo", count=len(DEMO_USERS))
    return Services(repo=repo, storage=storage, publisher=publisher)
