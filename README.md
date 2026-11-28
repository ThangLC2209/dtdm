# Chứng từ số

Ứng dụng web Flask tiếp nhận, lưu trữ và phê duyệt chứng từ. Giữ nguyên quy trình nghiệp vụ hiện có, hỗ trợ chạy local và có thể triển khai Azure với đăng nhập Microsoft Entra ID, Azure SQL, Blob Storage và Service Bus.

## Chức năng

- Nộp chứng từ kèm tệp PDF, PNG, JPG, DOCX hoặc XLSX; lưu phiên bản và mã kiểm tra SHA-256.
- Quy trình phê duyệt nhiều cấp theo vai trò và hạn mức; không ai tự duyệt chứng từ của mình.
- Quản lý người dùng, vai trò, bộ phận, thông báo và nhật ký kiểm toán.
- Phân quyền phía máy chủ cho từng vai trò và chứng từ.

## Công nghệ

- Flask, Python 3.11+
- Đăng nhập thật: Microsoft Entra ID (OIDC authorization-code)
- Dữ liệu: Azure SQL; tệp riêng tư: Azure Blob Storage
- Sự kiện/thông báo: Azure Service Bus
- Container: Azure Container Apps
- Azure SDK dùng managed identity; bí mật phải đặt bằng secret/Key Vault.

## Chạy local

Cần Python 3.11 trở lên.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-local.txt
python scripts/seed_demo.py
python main.py
```

Mở http://127.0.0.1:8080. Chế độ local lưu JSON trong `data/` và dùng tài khoản mẫu không mật khẩu; chỉ dành cho phát triển/demo. Không dùng chế độ này với dữ liệu thật hoặc triển khai công khai.

### Đăng nhập bằng email và mật khẩu (`AUTH_MODE=password`)

Dùng khi chưa có Microsoft Entra ID nhưng vẫn cần tài khoản thật thay cho chế độ chọn tài khoản demo.

```powershell
$env:AUTH_MODE = "password"
$env:ADMIN_EMAILS = "admin@congty.vn"
$env:SECRET_KEY = "<chuỗi-ngẫu-nhiên-tối-thiểu-32-byte>"
python main.py
```

Luồng sử dụng:

1. Quản trị viên vào `/register`, đăng ký bằng email nằm trong `ADMIN_EMAILS`. Tài khoản này được kích hoạt ngay với quyền quản trị.
2. Nhân viên vào `/register`, nhập họ tên, email, bộ phận và mật khẩu (tối thiểu 8 ký tự). Tài khoản ở trạng thái **Chờ duyệt** và chưa đăng nhập được.
3. Quản trị viên vào **Người dùng**, chọn vai trò và bộ phận cho từng đăng ký rồi bấm **Duyệt** (hoặc **Từ chối**).
4. Từ đó nhân viên đăng nhập tại `/login` bằng email và mật khẩu đã đăng ký. Quản trị viên có thể **Khóa** hoặc **Mở khóa** tài khoản bất cứ lúc nào; tài khoản bị khóa mất quyền ngay ở thao tác kế tiếp.

Mật khẩu chỉ lưu dạng băm (Werkzeug `scrypt`), không lưu bản gốc. Hãy đăng ký email quản trị ngay sau khi triển khai, vì ai đăng ký email trong `ADMIN_EMAILS` trước sẽ nhận quyền quản trị. Chế độ này chưa có giới hạn số lần đăng nhập sai và chưa có chức năng quên mật khẩu.

Chạy kiểm thử:

```powershell
python -m pytest -q
```

## Cấu hình Azure

### 1. Đăng ký Microsoft Entra ID

Trong Microsoft Entra admin center, tạo App registration dạng single-tenant. Thêm Redirect URI kiểu Web: `https://<tên-miền>/auth/callback`. Tạo client secret và lưu trong Azure Key Vault; không commit secret vào repository. Ứng dụng dùng OpenID Connect với scope `openid`, `profile`, `email`.

### 2. Tạo dịch vụ Azure

Tạo Azure SQL Database, Storage Account, Service Bus namespace/queue và Azure Container Apps Environment trong region phù hợp. Blob container `documents` cần để private; bật soft delete/versioning theo chính sách lưu trữ. Bật managed identity cho Container App và cấp quyền tối thiểu: `Storage Blob Data Contributor`, `Azure Service Bus Data Sender`/`Receiver`; giới hạn SQL identity vào database ứng dụng. Lưu `SECRET_KEY` và `AZURE_CLIENT_SECRET` trong Key Vault.

### 3. Cấu hình ứng dụng

Đặt các giá trị trong Container Apps secrets/environment:

| Biến | Mục đích |
| --- | --- |
| `BACKEND` | `azure` |
| `AUTH_MODE` | `entra` |
| `SECRET_KEY` | Khóa ký session cookie ngẫu nhiên, tối thiểu 32 byte |
| `AZURE_TENANT_ID` | Tenant ID Entra |
| `AZURE_CLIENT_ID` | Application (client) ID |
| `AZURE_CLIENT_SECRET` | Secret app registration; nên lấy từ Key Vault |
| `AZURE_REDIRECT_URI` | URL callback tuyệt đối, ví dụ `https://<host>/auth/callback` |
| `AZURE_POST_LOGOUT_REDIRECT_URI` | Đường dẫn sau đăng xuất; mặc định `/login` |
| `ADMIN_EMAILS` | Email quản trị khởi tạo, cách nhau bằng dấu phẩy |
| `AZURE_SQL_URL` | SQLAlchemy URL đến Azure SQL |
| `AZURE_STORAGE_ACCOUNT_URL` | `https://<storage>.blob.core.windows.net` |
| `AZURE_STORAGE_CONTAINER` | Private container; mặc định `documents` |
| `AZURE_SERVICEBUS_NAMESPACE` | Namespace, không gồm `.servicebus.windows.net` |
| `AZURE_SERVICEBUS_QUEUE` | Queue; mặc định `chungtu-events` |
| `LEVEL2_THRESHOLD` | Hạn mức duyệt cấp 2; mặc định `20000000` |

Tạo Container App với image đã push vào Azure Container Registry, port 8080, HTTPS ingress, managed identity, secrets tham chiếu Key Vault và các biến trên. `deploy/azure-deploy.ps1` chỉ hỗ trợ bước đầu tạo Resource Group và Container Apps Environment; script không tự tạo database, storage, queue hoặc đăng ký Entra.

Worker Service Bus cần chạy riêng (consumer hoặc Container Apps Job); không mở endpoint worker công khai nếu chưa có cơ chế xác thực phù hợp. Trước production cần xác minh SQL TLS, Blob private, quyền tối thiểu, cookie secure, secret rotation, backup/restore và đăng nhập đầu-cuối.

`pyodbc` cần Microsoft ODBC Driver 18 for SQL Server trong container. Cần bổ sung driver Microsoft theo hướng dẫn chính thức trước khi dùng Azure SQL; Dockerfile hiện chưa cài driver này.

## Chuyển dữ liệu khỏi Google Cloud

Backend GCP cũ và script triển khai cũ được giữ tạm để không phá hệ thống hiện tại. Dữ liệu không tự động chuyển sang Azure. Trước khi di trú cần xuất Firestore/Cloud Storage, chuyển đổi dữ liệu sang Azure SQL/Blob, đối chiếu số lượng và hash, chạy thử trên bản sao rồi mới lập lịch chuyển đổi. Không xóa tài nguyên Google trước khi xác nhận di trú thành công và có backup phục hồi.

## Trạng thái

Các chức năng nghiệp vụ hiện có được giữ lại. Backend Azure và xác thực Entra mới cần được kiểm thử trên môi trường có dependency và cấu hình tenant/subscription thật trước production; tài liệu/script không tự triển khai tài nguyên Azure.
