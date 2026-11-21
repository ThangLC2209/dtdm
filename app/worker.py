"""Xử lý sự kiện chứng từ: tạo thông báo cho đúng người nhận.

Trên Google Cloud, hàm này chạy trong dịch vụ Cloud Run "worker", được Pub/Sub gọi qua
push subscription. Trên máy cá nhân, nó được gọi trực tiếp trong cùng tiến trình.
"""
from __future__ import annotations

from . import workflow as wf


def recipients(users: list[dict], event: dict) -> list[str]:
    status = event["status"]
    submitter = event["submitter"]
    if status == wf.PENDING_L1:
        return [u["email"] for u in users
                if u["role"] == "manager" and u["department"] == event["department"]
                and u["email"] != submitter]
    if status == wf.PENDING_L2:
        to = [u["email"] for u in users if u["role"] == "accountant" and u["email"] != submitter]
        if event["type"] == "document.forwarded":
            to.append(submitter)  # báo cho người nộp biết chứng từ đã qua cấp 1
        return to
    return [submitter]  # APPROVED / REJECTED


def message_for(event: dict, to: str) -> str:
    code, title, actor = event["code"], event["title"], event["actor_name"]
    kind = event["type"]
    if kind == "document.submitted":
        return f"{actor} vừa nộp chứng từ {code} - {title}. Chứng từ đang chờ bạn duyệt."
    if kind == "document.resubmitted":
        return f"{actor} đã nộp lại chứng từ {code} - {title}. Chứng từ đang chờ bạn duyệt."
    if kind == "document.forwarded":
        if to == event["submitter"]:
            return f"Chứng từ {code} đã được {actor} duyệt cấp 1 và chuyển tới kế toán trưởng."
        return f"Chứng từ {code} - {title} đã qua cấp 1 và đang chờ bạn duyệt cấp 2."
    if kind == "document.approved":
        return f"Chứng từ {code} - {title} đã được {actor} duyệt. Quy trình hoàn tất."
    if kind == "document.rejected":
        return f"Chứng từ {code} - {title} bị {actor} từ chối. Lý do: {event['comment']}"
    return f"Chứng từ {code} có cập nhật mới."


def handle_event(repo, event: dict) -> int:
    """Trả về số thông báo đã ghi. Gọi lại nhiều lần với cùng sự kiện cho cùng kết quả."""
    count = 0
    for email in recipients(repo.list_users(), event):
        repo.add_notification({
            "id": f"{event['id']}__{email}",
            "to": email,
            "doc_id": event["doc_id"],
            "code": event["code"],
            "message": message_for(event, email),
            "at": event["at"],
            "read": False,
        })
        count += 1
    return count
