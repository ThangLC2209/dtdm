"""Quy tắc nghiệp vụ của quy trình phê duyệt chứng từ.

Mọi hàm ở đây đều thuần (không đọc/ghi cơ sở dữ liệu, không gọi mạng) nên:
  * kiểm thử được bằng unit test,
  * chạy an toàn bên trong transaction của Firestore (transaction có thể bị chạy lại).
"""
from __future__ import annotations

import uuid

PENDING_L1 = "PENDING_L1"
PENDING_L2 = "PENDING_L2"
APPROVED = "APPROVED"
REJECTED = "REJECTED"

STATUS_LABELS = {
    PENDING_L1: "Chờ trưởng bộ phận duyệt",
    PENDING_L2: "Chờ kế toán trưởng duyệt",
    APPROVED: "Đã duyệt",
    REJECTED: "Bị từ chối",
}

ROLES = {
    "employee": "Nhân viên",
    "manager": "Trưởng bộ phận",
    "accountant": "Kế toán trưởng",
    "admin": "Quản trị",
}

DOC_TYPES = {
    "invoice": "Hóa đơn",
    "payment_request": "Đề nghị thanh toán",
    "receipt": "Phiếu thu",
    "payment_voucher": "Phiếu chi",
    "contract": "Hợp đồng",
    "other": "Khác",
}

DEPARTMENTS = ["Kinh doanh", "Kỹ thuật", "Hành chính - Nhân sự", "Tài chính - Kế toán"]

ACTION_LABELS = {
    "submit": "Nộp chứng từ",
    "approve": "Duyệt",
    "reject": "Từ chối",
    "resubmit": "Nộp lại",
}


class WorkflowError(Exception):
    """Thao tác không hợp lệ theo quy tắc nghiệp vụ (trả về HTTP 400/403)."""


def initial_status(submitter: dict) -> str:
    """Chứng từ do trưởng bộ phận tự nộp bỏ qua cấp 1 và đi thẳng tới kế toán trưởng."""
    return PENDING_L2 if submitter["role"] == "manager" else PENDING_L1


def can_view(user: dict, doc: dict) -> bool:
    if user["role"] in ("admin", "accountant"):
        return True
    if doc["submitter"] == user["email"]:
        return True
    return user["role"] == "manager" and doc["department"] == user["department"]


def can_decide(user: dict, doc: dict) -> bool:
    """Người dùng có được duyệt/từ chối chứng từ ở trạng thái hiện tại không."""
    if doc["submitter"] == user["email"]:
        return False  # tách biệt nhiệm vụ: không ai tự duyệt chứng từ của mình
    if doc["status"] == PENDING_L1:
        return user["role"] == "manager" and user["department"] == doc["department"]
    if doc["status"] == PENDING_L2:
        return user["role"] == "accountant"
    return False


def can_resubmit(user: dict, doc: dict) -> bool:
    return doc["status"] == REJECTED and doc["submitter"] == user["email"]


def _audit(doc: dict, user: dict, action: str, from_status: str | None, to_status: str,
           comment: str, now: str) -> dict:
    return {
        "id": uuid.uuid4().hex,
        "doc_id": doc["id"],
        "code": doc["code"],
        "at": now,
        "actor": user["email"],
        "actor_name": user["name"],
        "actor_role": user["role"],
        "action": action,
        "from_status": from_status,
        "to_status": to_status,
        "comment": comment,
    }


def _event(event_type: str, doc: dict, user: dict, status: str, comment: str, now: str) -> dict:
    return {
        "id": uuid.uuid4().hex,
        "type": event_type,
        "doc_id": doc["id"],
        "code": doc["code"],
        "title": doc["title"],
        "department": doc["department"],
        "submitter": doc["submitter"],
        "status": status,
        "actor": user["email"],
        "actor_name": user["name"],
        "comment": comment,
        "at": now,
    }


def submit(doc: dict, user: dict, now: str) -> tuple[dict, dict]:
    """Trả về (bản ghi nhật ký, sự kiện) cho một chứng từ vừa được tạo."""
    return (
        _audit(doc, user, "submit", None, doc["status"], "", now),
        _event("document.submitted", doc, user, doc["status"], "", now),
    )


def decide(doc: dict, user: dict, action: str, comment: str, threshold: int,
           now: str) -> tuple[dict, dict, dict]:
    """Duyệt hoặc từ chối. Trả về (các trường cần cập nhật, bản ghi nhật ký, sự kiện)."""
    if action not in ("approve", "reject"):
        raise WorkflowError("Thao tác không hợp lệ.")
    if not can_decide(user, doc):
        raise WorkflowError("Bạn không có quyền xử lý chứng từ này ở trạng thái hiện tại.")
    comment = (comment or "").strip()
    if action == "reject" and not comment:
        raise WorkflowError("Cần nêu lý do khi từ chối.")

    current = doc["status"]
    level = 1 if current == PENDING_L1 else 2
    if action == "reject":
        new_status, event_type = REJECTED, "document.rejected"
    elif level == 1 and doc["amount"] >= threshold:
        new_status, event_type = PENDING_L2, "document.forwarded"
    else:
        new_status, event_type = APPROVED, "document.approved"

    decision = {
        "level": level,
        "decision": action,
        "by": user["email"],
        "by_name": user["name"],
        "at": now,
        "comment": comment,
    }
    updates = {
        "status": new_status,
        "updated_at": now,
        "approvals": list(doc.get("approvals", [])) + [decision],
    }
    return (
        updates,
        _audit(doc, user, action, current, new_status, comment, now),
        _event(event_type, doc, user, new_status, comment, now),
    )


def resubmit(doc: dict, user: dict, file_meta: dict, note: str,
             now: str) -> tuple[dict, dict, dict]:
    """Người nộp tải phiên bản tệp mới sau khi bị từ chối; quy trình duyệt bắt đầu lại."""
    if not can_resubmit(user, doc):
        raise WorkflowError("Chỉ người nộp mới được nộp lại chứng từ đã bị từ chối.")
    note = (note or "").strip()
    new_status = initial_status(user)
    versions = list(doc.get("versions", []))
    versions.append({**file_meta, "version": len(versions) + 1, "uploaded_at": now,
                     "uploaded_by": user["email"]})
    updates = {"status": new_status, "updated_at": now, "versions": versions}
    return (
        updates,
        _audit(doc, user, "resubmit", doc["status"], new_status, note, now),
        _event("document.resubmitted", doc, user, new_status, note, now),
    )
