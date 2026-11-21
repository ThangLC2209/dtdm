"""Tạo dữ liệu mẫu cho buổi trình diễn (chạy với backend local).

    python scripts/seed_demo.py

Kịch bản đi qua đúng các trang web như người dùng thật: nộp, duyệt, từ chối, nộp lại.
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402

AN, BINH = "an.nguyen@example.com", "binh.tran@example.com"
CUONG, DUNG = "cuong.le@example.com", "dung.pham@example.com"
HOA = "hoa.vu@example.com"


def make_pdf(lines: list[str]) -> bytes:
    """Sinh một tệp PDF một trang, hợp lệ, chỉ bằng thư viện chuẩn (chữ không dấu)."""
    text = ["BT", "/F1 14 Tf", "72 770 Td", "20 TL"]
    for line in lines:
        safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        text.append(f"({safe}) Tj T*")
    text.append("ET")
    stream = "\n".join(text).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    return bytes(out)


class Session:
    def __init__(self, app, email):
        self.client = app.test_client()
        self.client.get("/login")
        self.post("/login", {"email": email})

    def post(self, url, data):
        with self.client.session_transaction() as session:
            token = session["csrf"]
        return self.client.post(url, data={"csrf_token": token, **data},
                                content_type="multipart/form-data")

    def submit(self, title, doc_type, amount, description, filename):
        pdf = make_pdf(["CHUNG TU DEMO", title_ascii(title), f"So tien: {amount} VND",
                        "Tep mau phuc vu trinh dien do an Dien toan dam may."])
        response = self.post("/documents", {
            "title": title, "type": doc_type, "amount": amount, "description": description,
            "file": (io.BytesIO(pdf), filename)})
        return response.headers["Location"].rstrip("/").split("/")[-1]

    def decide(self, doc_id, action, comment=""):
        self.post(f"/documents/{doc_id}/decision", {"action": action, "comment": comment})


def title_ascii(text: str) -> str:
    import unicodedata
    text = text.replace("Đ", "D").replace("đ", "d")
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def main():
    app = create_app({"BACKEND": "local", "AUTH_MODE": "demo"})
    if app.extensions["svc"].repo.list_documents():
        print("Đã có dữ liệu, bỏ qua. Xóa thư mục data/ nếu muốn tạo lại.")
        return
    an, binh = Session(app, AN), Session(app, BINH)
    cuong, dung, hoa = Session(app, CUONG), Session(app, DUNG), Session(app, HOA)

    d1 = an.submit("Hóa đơn thuê văn phòng tháng 11", "invoice", "45.000.000",
                   "Công ty TNHH Bất động sản Sao Mai, kỳ 11/2026", "hoa-don-thue-van-phong.pdf")
    cuong.decide(d1, "approve", "Đúng hợp đồng thuê")
    hoa.decide(d1, "approve", "Đủ hồ sơ, đã đối chiếu hợp đồng")

    d2 = an.submit("Đề nghị thanh toán chi phí tiếp khách", "payment_request", "3.200.000",
                   "Tiếp đoàn khách hàng ngày 10/11", "de-nghi-thanh-toan.pdf")
    cuong.decide(d2, "approve")

    d3 = binh.submit("Hóa đơn mua máy chủ thử nghiệm", "invoice", "68.500.000",
                     "02 máy chủ cho phòng lab", "hoa-don-may-chu.pdf")
    dung.decide(d3, "approve", "Trong ngân sách quý 4")

    d4 = binh.submit("Phiếu chi mua văn phòng phẩm", "payment_voucher", "1.850.000",
                     "Giấy in, mực in, bút", "phieu-chi-vpp.pdf")
    dung.decide(d4, "reject", "Thiếu hóa đơn bán lẻ đính kèm")

    an.submit("Hợp đồng bảo trì phần mềm CRM", "contract", "120.000.000",
              "Gia hạn 12 tháng với nhà cung cấp", "hop-dong-bao-tri.pdf")
    cuong.submit("Đề nghị tạm ứng công tác Đà Nẵng", "payment_request", "8.000.000",
                 "Công tác 3 ngày, 2 người", "tam-ung-cong-tac.pdf")
    print("Đã tạo 6 chứng từ mẫu trong thư mục data/.")


if __name__ == "__main__":
    main()
