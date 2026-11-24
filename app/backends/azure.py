"""Backend Azure: SQL, Blob Storage và Service Bus."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from sqlalchemy import Column, Integer, MetaData, String, Table, Text, create_engine, select, update

VN_TZ = timezone(timedelta(hours=7))
metadata = MetaData()
users = Table("users", metadata, Column("email", String(320), primary_key=True), Column("payload", Text, nullable=False))
documents = Table("documents", metadata, Column("id", String(64), primary_key=True), Column("payload", Text, nullable=False))
audit_log = Table("audit_log", metadata, Column("id", String(64), primary_key=True), Column("doc_id", String(64), nullable=False), Column("at", String(40), nullable=False), Column("payload", Text, nullable=False))
notifications = Table("notifications", metadata, Column("id", String(400), primary_key=True), Column("recipient", String(320), nullable=False), Column("at", String(40), nullable=False), Column("payload", Text, nullable=False))
counters = Table("counters", metadata, Column("name", String(100), primary_key=True), Column("value", Integer, nullable=False))


def _payload(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False)


class AzureSQLRepo:
    """Repository SQL; cập nhật chứng từ và audit log theo cùng transaction."""

    def __init__(self, url: str):
        if not url:
            raise ValueError("Cần cấu hình AZURE_SQL_URL.")
        self.engine = create_engine(url, pool_pre_ping=True, pool_recycle=1800)
        metadata.create_all(self.engine)

    def get_user(self, email: str) -> dict | None:
        with self.engine.connect() as conn:
            value = conn.execute(select(users.c.payload).where(users.c.email == email)).scalar_one_or_none()
        return json.loads(value) if value else None

    def list_users(self) -> list[dict]:
        with self.engine.connect() as conn:
            values = conn.execute(select(users.c.payload)).scalars().all()
        return sorted((json.loads(value) for value in values), key=lambda user: user["email"])

    def upsert_user(self, user: dict) -> None:
        with self.engine.begin() as conn:
            result = conn.execute(update(users).where(users.c.email == user["email"]).values(payload=_payload(user)))
            if result.rowcount == 0:
                conn.execute(users.insert().values(email=user["email"], payload=_payload(user)))

    def next_code(self) -> str:
        year = datetime.now(VN_TZ).year
        name = f"documents-{year}"
        with self.engine.begin() as conn:
            row = conn.execute(select(counters.c.value).where(counters.c.name == name).with_for_update()).first()
            value = row[0] + 1 if row else 1
            if row:
                conn.execute(update(counters).where(counters.c.name == name).values(value=value))
            else:
                conn.execute(counters.insert().values(name=name, value=value))
        return f"CT-{year}-{value:04d}"

    def create_document(self, doc: dict, audit: dict) -> None:
        with self.engine.begin() as conn:
            conn.execute(documents.insert().values(id=doc["id"], payload=_payload(doc)))
            conn.execute(audit_log.insert().values(id=audit["id"], doc_id=audit["doc_id"], at=audit["at"], payload=_payload(audit)))

    def get_document(self, doc_id: str) -> dict | None:
        with self.engine.connect() as conn:
            value = conn.execute(select(documents.c.payload).where(documents.c.id == doc_id)).scalar_one_or_none()
        return json.loads(value) if value else None

    def list_documents(self, submitter: str | None = None, department: str | None = None) -> list[dict]:
        with self.engine.connect() as conn:
            values = conn.execute(select(documents.c.payload)).scalars().all()
        result = [json.loads(value) for value in values]
        if submitter:
            result = [doc for doc in result if doc["submitter"] == submitter]
        if department:
            result = [doc for doc in result if doc["department"] == department]
        return sorted(result, key=lambda doc: doc["created_at"], reverse=True)

    def transition(self, doc_id: str, fn) -> dict:
        with self.engine.begin() as conn:
            row = conn.execute(select(documents.c.payload).where(documents.c.id == doc_id).with_for_update()).first()
            if row is None:
                raise KeyError(doc_id)
            doc = json.loads(row[0])
            updates, audit = fn(dict(doc))
            doc.update(updates)
            conn.execute(update(documents).where(documents.c.id == doc_id).values(payload=_payload(doc)))
            conn.execute(audit_log.insert().values(id=audit["id"], doc_id=audit["doc_id"], at=audit["at"], payload=_payload(audit)))
            return doc

    def list_audit(self, doc_id: str | None = None, limit: int = 200) -> list[dict]:
        query = select(audit_log.c.payload)
        if doc_id:
            query = query.where(audit_log.c.doc_id == doc_id).order_by(audit_log.c.at)
        else:
            query = query.order_by(audit_log.c.at.desc()).limit(limit)
        with self.engine.connect() as conn:
            values = conn.execute(query).scalars().all()
        return [json.loads(value) for value in values]

    def add_notification(self, notification: dict) -> None:
        with self.engine.begin() as conn:
            exists = conn.execute(select(notifications.c.id).where(notifications.c.id == notification["id"])).first()
            if exists is None:
                conn.execute(notifications.insert().values(id=notification["id"], recipient=notification["to"], at=notification["at"], payload=_payload(notification)))

    def list_notifications(self, email: str, limit: int = 50) -> list[dict]:
        with self.engine.connect() as conn:
            values = conn.execute(select(notifications.c.payload).where(notifications.c.recipient == email).order_by(notifications.c.at.desc()).limit(limit)).scalars().all()
        return [json.loads(value) for value in values]

    def mark_notifications_read(self, email: str) -> None:
        with self.engine.begin() as conn:
            rows = conn.execute(select(notifications.c.id, notifications.c.payload).where(notifications.c.recipient == email)).all()
            for row in rows:
                item = json.loads(row["payload"])
                if not item.get("read"):
                    item["read"] = True
                    conn.execute(update(notifications).where(notifications.c.id == row["id"]).values(payload=_payload(item)))


class AzureBlobStorage:
    def __init__(self, account_url: str, container_name: str):
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient
        self._service = BlobServiceClient(account_url=account_url, credential=DefaultAzureCredential())
        self._container = self._service.get_container_client(container_name)
        try:
            self._container.create_container()
        except Exception as exc:
            if getattr(exc, "status_code", None) != 409:
                raise

    def save(self, name: str, data: bytes, content_type: str) -> None:
        from azure.storage.blob import ContentSettings
        self._container.upload_blob(name, data, overwrite=False, content_settings=ContentSettings(content_type=content_type))

    def read(self, name: str) -> bytes:
        return self._container.download_blob(name).readall()

    def signed_url(self, name: str, filename: str, minutes: int = 5) -> str | None:
        # Nếu thiếu quyền tạo delegation key, routes sẽ gửi tệp qua ứng dụng.
        from azure.storage.blob import BlobSasPermissions, generate_blob_sas
        now = datetime.now(timezone.utc)
        key = self._service.get_user_delegation_key(now - timedelta(minutes=1), now + timedelta(minutes=minutes))
        token = generate_blob_sas(account_name=self._service.account_name, container_name=self._container.container_name,
                                  blob_name=name, user_delegation_key=key, permission=BlobSasPermissions(read=True),
                                  expiry=now + timedelta(minutes=minutes),
                                  content_disposition=f"attachment; filename=chungtu; filename*=UTF-8''{quote(filename)}")
        return f"{self._container.url}/{quote(name)}?{token}"


class AzureServiceBusPublisher:
    def __init__(self, connection_string: str | None, queue_name: str):
        from azure.identity import DefaultAzureCredential
        from azure.servicebus import ServiceBusClient
        if connection_string:
            self._client = ServiceBusClient.from_connection_string(connection_string)
        else:
            import os
            namespace = os.environ.get("AZURE_SERVICEBUS_NAMESPACE")
            if not namespace:
                raise ValueError("Cần cấu hình AZURE_SERVICEBUS_NAMESPACE hoặc connection string.")
            self._client = ServiceBusClient(f"{namespace}.servicebus.windows.net", DefaultAzureCredential())
        self._queue = queue_name

    def publish(self, event: dict) -> None:
        from azure.servicebus import ServiceBusMessage
        with self._client:
            with self._client.get_queue_sender(queue_name=self._queue) as sender:
                sender.send_messages(ServiceBusMessage(_payload(event), message_id=event["id"]))
