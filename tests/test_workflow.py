"""Kiểm thử quy tắc nghiệp vụ (hàm thuần, không cần hạ tầng)."""
import pytest

from app import workflow as wf

NOW = "2026-11-16T03:00:00.000Z"
THRESHOLD = 20_000_000

AN = {"email": "an@example.com", "name": "An", "role": "employee", "department": "Kinh doanh"}
CUONG = {"email": "cuong@example.com", "name": "Cường", "role": "manager", "department": "Kinh doanh"}
DUNG = {"email": "dung@example.com", "name": "Dung", "role": "manager", "department": "Kỹ thuật"}
HOA = {"email": "hoa@example.com", "name": "Hoa", "role": "accountant", "department": "Tài chính - Kế toán"}
ADMIN = {"email": "admin@example.com", "name": "Admin", "role": "admin", "department": "Hành chính - Nhân sự"}


def make_doc(submitter=AN, amount=5_000_000, status=None):
    return {"id": "d1", "code": "CT-2026-0001", "title": "Hóa đơn", "amount": amount,
            "department": submitter["department"], "submitter": submitter["email"],
            "status": status or wf.initial_status(submitter), "versions": [{"version": 1}],
            "approvals": []}


def test_small_amount_is_approved_after_level_1():
    updates, audit, event = wf.decide(make_doc(), CUONG, "approve", "", THRESHOLD, NOW)
    assert updates["status"] == wf.APPROVED
    assert audit["from_status"] == wf.PENDING_L1 and audit["to_status"] == wf.APPROVED
    assert event["type"] == "document.approved"


def test_amount_at_threshold_goes_to_level_2():
    updates, _, event = wf.decide(make_doc(amount=THRESHOLD), CUONG, "approve", "", THRESHOLD, NOW)
    assert updates["status"] == wf.PENDING_L2
    assert event["type"] == "document.forwarded"


def test_level_2_approval_completes_the_flow():
    doc = make_doc(amount=50_000_000, status=wf.PENDING_L2)
    updates, _, _ = wf.decide(doc, HOA, "approve", "Đủ hồ sơ", THRESHOLD, NOW)
    assert updates["status"] == wf.APPROVED
    assert updates["approvals"][-1]["level"] == 2


def test_reject_requires_a_reason():
    with pytest.raises(wf.WorkflowError):
        wf.decide(make_doc(), CUONG, "reject", "   ", THRESHOLD, NOW)
    updates, _, event = wf.decide(make_doc(), CUONG, "reject", "Thiếu chữ ký", THRESHOLD, NOW)
    assert updates["status"] == wf.REJECTED and event["comment"] == "Thiếu chữ ký"


@pytest.mark.parametrize("actor", [AN, DUNG, HOA, ADMIN])
def test_only_the_department_manager_decides_at_level_1(actor):
    with pytest.raises(wf.WorkflowError):
        wf.decide(make_doc(), actor, "approve", "", THRESHOLD, NOW)


@pytest.mark.parametrize("actor", [AN, CUONG, ADMIN])
def test_only_the_accountant_decides_at_level_2(actor):
    with pytest.raises(wf.WorkflowError):
        wf.decide(make_doc(status=wf.PENDING_L2), actor, "approve", "", THRESHOLD, NOW)


def test_nobody_approves_their_own_document():
    doc = make_doc(submitter=CUONG)
    assert doc["status"] == wf.PENDING_L2  # chứng từ của trưởng bộ phận đi thẳng tới cấp 2
    assert not wf.can_decide(CUONG, doc)
    own = make_doc(submitter=HOA, status=wf.PENDING_L2)
    assert not wf.can_decide(HOA, own)


@pytest.mark.parametrize("status", [wf.APPROVED, wf.REJECTED])
def test_finished_documents_cannot_be_decided_again(status):
    with pytest.raises(wf.WorkflowError):
        wf.decide(make_doc(status=status), CUONG, "approve", "", THRESHOLD, NOW)


def test_resubmit_adds_a_version_and_restarts_the_flow():
    doc = make_doc(status=wf.REJECTED)
    updates, audit, event = wf.resubmit(doc, AN, {"filename": "v2.pdf"}, "Đã bổ sung", NOW)
    assert updates["status"] == wf.PENDING_L1
    assert [v["version"] for v in updates["versions"]] == [1, 2]
    assert audit["action"] == "resubmit" and event["type"] == "document.resubmitted"


def test_resubmit_is_limited_to_the_submitter_of_a_rejected_document():
    with pytest.raises(wf.WorkflowError):
        wf.resubmit(make_doc(status=wf.REJECTED), CUONG, {}, "", NOW)
    with pytest.raises(wf.WorkflowError):
        wf.resubmit(make_doc(status=wf.PENDING_L1), AN, {}, "", NOW)


def test_visibility_follows_role_and_department():
    doc = make_doc()
    assert wf.can_view(AN, doc) and wf.can_view(CUONG, doc)
    assert wf.can_view(HOA, doc) and wf.can_view(ADMIN, doc)
    assert not wf.can_view(DUNG, doc)
    other = {**AN, "email": "khac@example.com"}
    assert not wf.can_view(other, doc)
