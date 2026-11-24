## Bối cảnh
Ứng dụng Flask hiện có đã triển khai quy trình tiếp nhận chứng từ, quản lý phiên bản, phê duyệt, phân quyền, thông báo và nhật ký kiểm toán. Đăng nhập hiện chỉ ở chế độ chọn tài khoản demo hoặc phụ thuộc Google IAP; dữ liệu dùng JSON cục bộ hoặc Firestore/Cloud Storage/Pub/Sub. Mục tiêu là giữ nguyên nghiệp vụ, bổ sung đăng nhập tài khoản thật, phân quyền, dữ liệu bền vững và khả năng triển khai Azure.

## Cách triển khai đề xuất

1. **Thay xác thực Google bằng Microsoft Entra ID OIDC.** Bổ sung luồng authorization-code và callback, kiểm tra state/nonce, xác thực token phía máy chủ, đăng xuất và tạo hồ sơ người dùng lần đầu với quyền tối thiểu `employee`. Dùng danh sách email quản trị ban đầu có cấu hình; không cho tự đăng ký nhận quyền cao. Chỉ giữ đăng nhập demo cho môi trường local/test. Duy trì chức năng quản trị hiện tại để gán vai trò và bộ phận.
2. **Thêm dịch vụ Azure sau các giao diện backend hiện có.** Tạo repository Azure SQL dùng SQLAlchemy với chuyển trạng thái chứng từ theo transaction và lưu bền vững người dùng, chứng từ, audit log, thông báo, bộ đếm. Dùng Azure Blob Storage cho tệp riêng tư có phiên bản và Azure Service Bus cho sự kiện bất đồng bộ cùng worker đã xác thực. Giữ `workflow.py` và hợp đồng giao tiếp đang được routes/worker sử dụng. Chọn Azure bằng cấu hình rõ ràng, vẫn giữ backend local cho phát triển và kiểm thử. Dùng managed identity và bí mật từ Key Vault khi triển khai; không đưa thông tin xác thực vào mã nguồn hoặc image.
3. **Điều chỉnh giao diện đăng nhập và khung trang, giữ nguyên màn hình nghiệp vụ.** Thay nội dung chọn tài khoản demo bằng nút đăng nhập/đăng xuất Microsoft, cải thiện khả năng dùng trên màn hình nhỏ khi cần và đổi footer sang nội dung trung tính/Azure. Giữ các trang nộp/duyệt chứng từ, thông báo, nhật ký và quản trị người dùng.
4. **Thay hướng dẫn triển khai bằng Azure.** Bổ sung quy trình triển khai container, cấu hình managed identity, SQL, Blob, Service Bus, đăng ký ứng dụng Entra ID, secrets và worker. Cập nhật README để Azure là hướng dẫn chính bằng tiếng Việt. Giữ các tệp GCP cũ hoặc đánh dấu ngừng dùng rõ ràng; không xóa khi chưa có phương án di trú. Cập nhật requirements, cấu hình runtime và ignore.
5. **Kiểm thử local và kiểm thử tập trung.** Bổ sung test cho state/nonce và xử lý lỗi OIDC, cấp quyền an toàn khi tạo người dùng, phân quyền route, hành vi Azure repository/storage/publisher qua mock và tính idempotent của sự kiện worker. Chạy toàn bộ test hiện có và ghi rõ bước Azure cần tenant/subscription nên không thể kiểm chứng khi thiếu thông tin truy cập.

## Tệp quan trọng
- Xác thực và routes: `app/auth.py`, `app/routes.py`, `app/config.py`, `app/__init__.py`
- Chọn dịch vụ và backend: `app/services.py`, `app/backends/local.py`, các module Azure mới trong `app/backends/`
- Giao diện: `app/templates/base.html`, `app/templates/login.html`, `app/static/style.css`
- Runtime và triển khai: `requirements.txt`, `Dockerfile`, `README.md`, tài nguyên `deploy/azure.*` mới
- Kiểm thử: `tests/test_app.py`, test xác thực/backend mới
- Giữ nguyên quy tắc nghiệp vụ trong `app/workflow.py` và thông báo trong `app/worker.py`, trừ khi cần điều chỉnh giao diện tích hợp.

## Kiểm chứng
Chạy toàn bộ test bằng môi trường Python của dự án. Kiểm tra callback OIDC từ chối state/nonce/chữ ký/issuer/audience/hạn dùng sai; người dùng mới mặc định quyền thấp nhất; route nhạy cảm vẫn được phân quyền; ghi dữ liệu có transaction; blob không công khai; sự kiện worker gửi trùng vẫn idempotent. Kiểm tra tĩnh cấu hình container và triển khai. Đăng ký Entra thực tế, tạo tài nguyên Azure và đăng nhập đầu-cuối trên đám mây cần tenant/subscription của người dùng; chỉ thực hiện khi có cấu hình cần thiết và được cho phép triển khai.