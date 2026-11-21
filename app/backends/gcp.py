"""Backend Google Cloud: Firestore (siêu dữ liệu), Cloud Storage (tệp), Pub/Sub (sự kiện).

Thư viện google-cloud-* chỉ được nạp khi BACKEND=gcp, nên chạy thử trên máy không cần cài.
Trên Cloud Run, thư viện tự lấy thông tin xác thực của service account gắn với dịch vụ
(Application Default Credentials) - không có khóa JSON nào nằm trong mã nguồn hay image.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import google.auth
from google.auth.transport import requests as ga_requests
from google.cloud import firestore, pubsub_v1, storage
from google.cloud.firestore_v1.base_query import FieldFilter

VN_TZ = timezone(timedelta(hours=7))


class FirestoreRepo:
    def __init__(self, project: str | None = None):
        self.db = firestore.Client(project=project)

    # ---- người dùng ----
    def get_user(self, email: str) -> dict | None:
        snap = self.db.collection("users").document(email).get()
        return snap.to_dict() if snap.exists else None

    def list_users(self) -> list[dict]:
        users = [s.to_dict() for s in self.db.collection("users").stream()]
        return sorted(users, key=lambda u: u["email"])

    def upsert_user(self, user: dict) -> None:
        self.db.collection("users").document(user["email"]).set(user)

    # ---- chứng từ ----
    def next_code(self) -> str:
        """Số chứng từ tăng dần theo năm, cấp trong transaction để không trùng."""
        year = datetime.now(VN_TZ).year
        ref = self.db.collection("counters").document(f"documents-{year}")

        @firestore.transactional
        def _increment(tx):
            snap = ref.get(transaction=tx)
            n = (snap.to_dict()["value"] if snap.exists else 0) + 1
            tx.set(ref, {"value": n})
            return n

        return f"CT-{year}-{_increment(self.db.transaction()):04d}"

    def create_document(self, doc: dict, audit: dict) -> None:
        batch = self.db.batch()  # ghi chứng từ và nhật ký cùng lúc: cùng thành công hoặc cùng thất bại
        batch.set(self.db.collection("documents").document(doc["id"]), doc)
        batch.set(self.db.collection("audit_log").document(audit["id"]), audit)
        batch.commit()

    def get_document(self, doc_id: str) -> dict | None:
        snap = self.db.collection("documents").document(doc_id).get()
        return snap.to_dict() if snap.exists else None

    def list_documents(self, submitter: str | None = None,
                       department: str | None = None) -> list[dict]:
        # Chỉ dùng bộ lọc bằng trên một trường và sắp xếp ở phía ứng dụng,
        # nên không cần tạo chỉ mục tổng hợp (composite index) cho bản demo.
        query = self.db.collection("documents")
        if submitter:
            query = query.where(filter=FieldFilter("submitter", "==", submitter))
        elif department:
            query = query.where(filter=FieldFilter("department", "==", department))
        docs = [s.to_dict() for s in query.stream()]
        if submitter and department:
            docs = [d for d in docs if d["department"] == department]
        return sorted(docs, key=lambda d: d["created_at"], reverse=True)

    def transition(self, doc_id: str, fn) -> dict:
        """Chuyển trạng thái trong transaction.

        Firestore dùng kiểm soát đồng thời lạc quan: nếu hai người cùng bấm duyệt, một
        transaction sẽ được chạy lại, đọc trạng thái mới và bị quy tắc nghiệp vụ từ chối.
        """
        ref = self.db.collection("documents").document(doc_id)

        @firestore.transactional
        def _run(tx):
            snap = ref.get(transaction=tx)
            if not snap.exists:
                raise KeyError(doc_id)
            doc = snap.to_dict()
            updates, audit = fn(dict(doc))
            tx.update(ref, updates)
            tx.set(self.db.collection("audit_log").document(audit["id"]), audit)
            doc.update(updates)
            return doc

        return _run(self.db.transaction())

    # ---- nhật ký ----
    def list_audit(self, doc_id: str | None = None, limit: int = 200) -> list[dict]:
        col = self.db.collection("audit_log")
        if doc_id:
            rows = [s.to_dict() for s in
                    col.where(filter=FieldFilter("doc_id", "==", doc_id)).stream()]
            return sorted(rows, key=lambda r: r["at"])
        query = col.order_by("at", direction=firestore.Query.DESCENDING).limit(limit)
        return [s.to_dict() for s in query.stream()]

    # ---- thông báo ----
    def add_notification(self, n: dict) -> None:
        # Id của thông báo được suy ra từ id sự kiện. Pub/Sub có thể giao lại tin
        # (at-least-once); lần sau thấy tài liệu đã có thì bỏ qua: thao tác idempotent.
        ref = self.db.collection("notifications").document(n["id"])
        if not ref.get().exists:
            ref.set(n)

    def list_notifications(self, email: str, limit: int = 50) -> list[dict]:
        query = self.db.collection("notifications").where(filter=FieldFilter("to", "==", email))
        rows = [s.to_dict() for s in query.stream()]
        return sorted(rows, key=lambda n: n["at"], reverse=True)[:limit]

    def mark_notifications_read(self, email: str) -> None:
        query = (self.db.collection("notifications")
                 .where(filter=FieldFilter("to", "==", email)))
        batch = self.db.batch()
        count = 0
        for snap in query.stream():
            if not snap.to_dict().get("read"):
                batch.update(snap.reference, {"read": True})
                count += 1
                if count == 400:  # một batch ghi tối đa 500 thao tác
                    batch.commit()
                    batch, count = self.db.batch(), 0
        if count:
            batch.commit()


class GcsStorage:
    def __init__(self, bucket_name: str):
        self._client = storage.Client()
        self._bucket = self._client.bucket(bucket_name)

    def save(self, name: str, data: bytes, content_type: str) -> None:
        self._bucket.blob(name).upload_from_string(data, content_type=content_type)

    def read(self, name: str) -> bytes:
        return self._bucket.blob(name).download_as_bytes()

    def signed_url(self, name: str, filename: str, minutes: int = 5) -> str | None:
        """URL ký V4 có hạn ngắn: trình duyệt tải thẳng từ Cloud Storage, bucket vẫn riêng tư.

        Cloud Run không có khóa riêng của service account, nên việc ký được ủy thác cho
        IAM Credentials API (signBlob). Service account cần vai trò
        roles/iam.serviceAccountTokenCreator trên chính nó.
        """
        credentials, _ = google.auth.default()
        credentials.refresh(ga_requests.Request())
        ascii_name = filename.encode("ascii", "ignore").decode() or "chungtu"
        disposition = (f'attachment; filename="{ascii_name}"; '
                       f"filename*=UTF-8''{quote(filename)}")
        return self._bucket.blob(name).generate_signed_url(
            version="v4",
            expiration=timedelta(minutes=minutes),
            method="GET",
            response_disposition=disposition,
            service_account_email=credentials.service_account_email,
            access_token=credentials.token,
        )


class PubSubPublisher:
    def __init__(self, project: str | None, topic: str):
        if not project:
            _, project = google.auth.default()
        self._client = pubsub_v1.PublisherClient()
        self._topic_path = self._client.topic_path(project, topic)

    def publish(self, event: dict) -> None:
        data = json.dumps(event, ensure_ascii=False).encode("utf-8")
        future = self._client.publish(self._topic_path, data, type=event["type"])
        # Chờ kết quả ngay trong request: Cloud Run chỉ cấp CPU khi đang xử lý request
        future.result(timeout=10)
