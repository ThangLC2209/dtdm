# Hướng dẫn triển khai Chứng từ số lên Azure

Tài liệu này hướng dẫn triển khai ứng dụng lên Microsoft Azure bằng script `deploy/azure-deploy.ps1`.

> Script nằm trên nhánh **`feature/azure-deployment`** (đã gồm cả đăng nhập bằng mật khẩu). Nhánh này chưa được gộp vào `Chungtu_Azure`.

## Kiến trúc sau khi triển khai

| Thành phần | Dịch vụ Azure | Ghi chú |
| --- | --- | --- |
| Ứng dụng web | Container Apps (`<tiền-tố>-web`) | HTTPS công khai, 1–3 bản chạy |
| Worker thông báo | Container Apps (`<tiền-tố>-worker`) | Không mở cổng, nhận sự kiện từ Service Bus |
| Cơ sở dữ liệu | Azure SQL (serverless) | Tự tạm dừng sau 60 phút không dùng; chỉ xác thực Microsoft Entra |
| Tệp chứng từ | Blob Storage, container `documents` | Riêng tư, tắt shared key, giữ bản xóa 30 ngày, bật versioning |
| Hàng đợi sự kiện | Service Bus (Basic), queue `chungtu-events` | Chỉ dùng managed identity |
| Bí mật | Key Vault | `SECRET_KEY` sinh ngẫu nhiên |
| Image | Azure Container Registry | Build trên Azure, không cần Docker ở máy |
| Danh tính | Managed identity | Web và worker dùng chung, không có mật khẩu trong cấu hình |

## Bước 1: Chuẩn bị (làm một lần)

1. Có tài khoản Azure với subscription. Bản dùng thử miễn phí cũng được. Bạn cần quyền **Owner** trên subscription.
2. Cài Azure CLI:

   ```powershell
   winget install Microsoft.AzureCLI
   ```

3. Nên cài thêm `sqlcmd`, để script tự cấp quyền SQL và bạn bỏ qua được Bước 5:

   ```powershell
   winget install sqlcmd
   ```

4. Cài xong, đóng và mở lại PowerShell để nhận lệnh mới.

## Bước 2: Lấy code nhánh triển khai

Tải file zip của nhánh `feature/azure-deployment` trên GitHub, hoặc dùng git:

```powershell
git clone -b feature/azure-deployment https://github.com/ThangLC2209/dtdm.git
cd dtdm
```

## Bước 3: Đăng nhập Azure và lấy Subscription ID

```powershell
az login
az account list -o table
```

Ghi lại giá trị ở cột `SubscriptionId`.

## Bước 4: Chạy script triển khai

Windows mặc định chặn chạy script, nên cần mở khóa cho cửa sổ PowerShell hiện tại:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Chạy script (thay giá trị trong `< >`):

```powershell
.\deploy\azure-deploy.ps1 -SubscriptionId <SubscriptionId> -ResourceGroup rg-chungtu -AdminEmails "email-quan-tri@congty.vn"
```

Script chạy khoảng 15–25 phút. Khi xong, nó in ra địa chỉ ứng dụng dạng `https://<tiền-tố>-web.<vùng>.azurecontainerapps.io`.

### Tham số của script

| Tham số | Bắt buộc | Mặc định | Ý nghĩa |
| --- | --- | --- | --- |
| `-SubscriptionId` | Có | | Subscription Azure |
| `-ResourceGroup` | Có | | Tên Resource Group sẽ tạo hoặc dùng lại |
| `-AdminEmails` | Có | | Email quản trị viên đầu tiên, nhiều email cách nhau bằng dấu phẩy |
| `-Location` | Không | `southeastasia` | Vùng Azure |
| `-Prefix` | Không | Tự sinh | Tiền tố tên tài nguyên, chỉ chữ thường và số, 3–12 ký tự |
| `-AuthMode` | Không | `password` | `password` (email + mật khẩu) hoặc `entra` (Microsoft Entra ID) |
| `-EntraClientId` | Khi dùng `entra` | | Application (client) ID của App registration |
| `-EntraClientSecret` | Khi dùng `entra` | | Client secret, nhập dạng SecureString |

## Bước 5: Cấp quyền SQL cho managed identity

Bước này chỉ cần khi script in ra dòng **"BƯỚC BẮT BUỘC CÒN LẠI"**, tức là máy chưa có `sqlcmd`.

1. Vào Azure Portal, mở SQL database **`chungtu`**, chọn **Query editor**.
2. Đăng nhập bằng tài khoản Microsoft đã dùng để chạy script.
3. Dán đoạn T-SQL mà script in ra, rồi bấm **Run**. Đoạn đó có dạng:

   ```sql
   CREATE USER [<tiền-tố>-id] FROM EXTERNAL PROVIDER;
   ALTER ROLE db_datareader ADD MEMBER [<tiền-tố>-id];
   ALTER ROLE db_datawriter ADD MEMBER [<tiền-tố>-id];
   ALTER ROLE db_ddladmin ADD MEMBER [<tiền-tố>-id];
   ```

4. Chạy lại lệnh ở Bước 4 để ứng dụng khởi động lại với quyền mới.

## Bước 6: Tạo tài khoản quản trị

1. Mở `https://<địa-chỉ>/register`.
2. Đăng ký **ngay** bằng đúng email đã truyền vào `-AdminEmails`. Tài khoản này được kích hoạt với quyền quản trị.

> Ai đăng ký email quản trị trước sẽ nhận quyền quản trị, nên hãy làm bước này ngay sau khi triển khai.

Sau đó:
- Nhân viên tự đăng ký tại `/register`. Tài khoản ở trạng thái **Chờ duyệt**.
- Quản trị viên vào trang **Người dùng**, chọn vai trò và bộ phận, rồi bấm **Duyệt**.
- Nhân viên đăng nhập tại `/login` bằng email và mật khẩu đã đăng ký.

## Bước 7: Kiểm tra

- Mở `https://<địa-chỉ>/healthz`. Nếu thấy `{"status": "ok"}` là ứng dụng đang chạy.
- Xem log ứng dụng web:

  ```powershell
  az containerapp logs show --name <tiền-tố>-web --resource-group rg-chungtu --follow
  ```

- Xem log worker (kiểm tra thông báo có được tạo không):

  ```powershell
  az containerapp logs show --name <tiền-tố>-worker --resource-group rg-chungtu --follow
  ```

## Dùng Microsoft Entra ID thay cho mật khẩu (tùy chọn)

1. Trong Microsoft Entra admin center, tạo **App registration** dạng single-tenant và tạo một client secret.
2. Chạy script với tham số Entra:

   ```powershell
   .\deploy\azure-deploy.ps1 -SubscriptionId <SubscriptionId> -ResourceGroup rg-chungtu -AdminEmails "email-quan-tri@congty.vn" -AuthMode entra -EntraClientId <client-id> -EntraClientSecret (Read-Host -AsSecureString)
   ```

3. Thêm Redirect URI mà script in ra (`https://<địa-chỉ>/auth/callback`) vào App registration, kiểu **Web**.

## Cập nhật phiên bản mới

Khi code thay đổi, chạy lại lệnh ở Bước 4. Script giữ nguyên dữ liệu và tài nguyên, chỉ build image mới và cập nhật Container Apps.

## Xử lý sự cố thường gặp

| Hiện tượng | Nguyên nhân thường gặp | Cách xử lý |
| --- | --- | --- |
| Script báo không chạy được file `.ps1` | Windows chặn script | Chạy lệnh `Set-ExecutionPolicy` ở Bước 4 |
| Lỗi quyền khi tạo role assignment | Tài khoản không phải Owner | Nhờ người có quyền Owner chạy, hoặc cấp thêm quyền User Access Administrator |
| Trang web lỗi 500, log báo lỗi đăng nhập SQL | Chưa cấp quyền SQL | Làm Bước 5 |
| Log báo `Cấu hình không hợp lệ` | Thiếu `SECRET_KEY` hoặc `ADMIN_EMAILS` | Chạy lại script, kiểm tra tham số `-AdminEmails` |
| Không có thông báo khi nộp hoặc duyệt chứng từ | Worker không chạy | Xem log worker ở Bước 7 |
| Tên tài nguyên bị trùng | Tên toàn cầu (Storage, ACR, Key Vault) đã có người dùng | Chạy lại với `-Prefix` khác |

## Chi phí và dọn dẹp

- SQL serverless tự tạm dừng khi không dùng, nên tốn ít khi để không.
- Hai Container Apps chạy tối thiểu mỗi cái 1 bản, nên có chi phí cố định hằng tháng.
- Xóa toàn bộ để dừng tính phí. **Lệnh này xóa cả dữ liệu và không hoàn tác được:**

  ```powershell
  az group delete --name rg-chungtu
  ```

> Lưu ý: Key Vault sau khi xóa được giữ ở trạng thái "đã xóa mềm" 30 ngày. Nếu muốn tạo lại với cùng tên trước thời hạn đó, cần purge trong Azure Portal hoặc dùng `-Prefix` khác.
