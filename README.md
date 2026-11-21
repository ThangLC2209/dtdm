# Chứng từ số — demo hệ thống tiếp nhận, lưu trữ và phê duyệt chứng từ trên Google Cloud

Ứng dụng web Python Flask chạy trên Cloud Run. Tệp chứng từ nằm trong Cloud Storage, siêu dữ liệu
và nhật ký trong Firestore, sự kiện đi qua Pub/Sub tới một dịch vụ worker tạo thông báo.

## Cấu trúc thư mục

```
app/
  workflow.py        Quy tắc nghiệp vụ: trạng thái, vai trò, ai được duyệt (hàm thuần)
  routes.py          Trang web, kiểm tra tệp tải lên, endpoint nhận tin Pub/Sub
  auth.py            Đăng nhập demo hoặc xác minh JWT của Identity-Aware Proxy
  worker.py          Xử lý sự kiện -> thông báo (idempotent)
  services.py        Chọn backend theo cấu hình, ghi log JSON
  backends/local.py  Chạy trên máy: tệp JSON + thư mục tệp
  backends/gcp.py    Firestore + Cloud Storage + Pub/Sub
  templates/, static/
tests/               33 ca kiểm thử tự động (pytest)
scripts/seed_demo.py Tạo 6 chứng từ mẫu
deploy/deploy.sh     Triển khai lên Google Cloud bằng gcloud
deploy/cleanup.sh    Gỡ tài nguyên sau khi trình diễn
Dockerfile
```

## Chạy trên máy cá nhân (không cần Google Cloud)

Cần Python 3.11 trở lên.

```bash
python3 -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-local.txt
python scripts/seed_demo.py                              # tùy chọn: dữ liệu mẫu
python main.py                                           # mở http://127.0.0.1:8080
```

Dữ liệu nằm trong thư mục `data/`. Xóa thư mục này để bắt đầu lại.

Chạy kiểm thử:

```bash
python -m pytest -q
```

## Tài khoản mẫu (chế độ demo, không mật khẩu)

| Họ tên | Vai trò | Bộ phận |
| --- | --- | --- |
| Nguyễn Văn An | Nhân viên | Kinh doanh |
| Trần Thị Bình | Nhân viên | Kỹ thuật |
| Lê Minh Cường | Trưởng bộ phận | Kinh doanh |
| Phạm Thị Dung | Trưởng bộ phận | Kỹ thuật |
| Vũ Thị Hoa | Kế toán trưởng | Tài chính - Kế toán |
| Quản trị viên | Quản trị | Hành chính - Nhân sự |

## Quy trình phê duyệt

1. Nhân viên nộp chứng từ kèm tệp -> **Chờ trưởng bộ phận duyệt**.
2. Trưởng bộ phận cùng bộ phận duyệt:
   - số tiền dưới 20.000.000 ₫ -> **Đã duyệt**;
   - từ 20.000.000 ₫ trở lên -> **Chờ kế toán trưởng duyệt**.
3. Kế toán trưởng duyệt -> **Đã duyệt**.
4. Ở cấp nào cũng có thể từ chối (bắt buộc nêu lý do) -> **Bị từ chối**. Người nộp tải tệp đã
   sửa lên thành phiên bản mới và quy trình bắt đầu lại.

Không ai tự duyệt chứng từ của mình. Chứng từ do trưởng bộ phận nộp đi thẳng tới kế toán trưởng.

## Triển khai lên Google Cloud

Điều kiện: một project đã gắn tài khoản thanh toán, và `gcloud` đã đăng nhập (dùng Cloud Shell
là nhanh nhất).

```bash
PROJECT_ID=ten-project-cua-ban ./deploy/deploy.sh
```

Script thực hiện 9 bước: bật API, tạo Firestore, tạo bucket riêng tư (bật phiên bản và vòng đời),
tạo 3 service account, tạo topic và secret, gán quyền tối thiểu, build image bằng Cloud Build,
triển khai 2 dịch vụ Cloud Run (`chungtu-web`, `chungtu-worker`), tạo push subscription.
Cuối cùng script in ra địa chỉ của ứng dụng.

Biến tùy chọn: `REGION` (mặc định `asia-southeast1`), `BUCKET`, `LEVEL2_THRESHOLD`, `AUTH_MODE`.

### Bật đăng nhập Google qua Identity-Aware Proxy (tùy chọn)

Mặc định bản triển khai ở chế độ demo: ai có địa chỉ cũng chọn được tài khoản mẫu. Chỉ dùng cho
buổi trình diễn với dữ liệu giả. Để chỉ người được cấp quyền mới vào được:

1. Console -> Cloud Run -> `chungtu-web` -> Security -> **Require authentication** ->
   **Identity-Aware Proxy (IAP)** -> Edit policy -> thêm email được phép. Với project không thuộc
   tổ chức nào, lần bật IAP đầu tiên cần làm trong Console.
2. Chuyển ứng dụng sang chế độ `iap`:

```bash
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
gcloud run services update chungtu-web --region=asia-southeast1 \
  --update-env-vars="AUTH_MODE=iap,ADMIN_EMAILS=ban@gmail.com,IAP_AUDIENCE=/projects/${PROJECT_NUMBER}/locations/asia-southeast1/services/chungtu-web"
```

Thêm người dùng bằng dòng lệnh:

```bash
gcloud iap web add-iam-policy-binding --resource-type=cloud-run --service=chungtu-web \
  --region=asia-southeast1 --member=user:dongnghiep@gmail.com --role=roles/iap.httpsResourceAccessor
```

Người trong `ADMIN_EMAILS` nhận vai trò Quản trị ở lần đăng nhập đầu và phân vai trò cho người
khác tại trang **Người dùng**.

### Gỡ tài nguyên

```bash
PROJECT_ID=ten-project-cua-ban ./deploy/cleanup.sh
```

### Lỗi thường gặp

| Hiện tượng | Cách xử lý |
| --- | --- |
| `gcloud builds submit` báo thiếu quyền | Gán `roles/cloudbuild.builds.builder` cho service account mà Cloud Build dùng (mặc định là Compute Engine default service account) |
| `--allow-unauthenticated` bị từ chối | Chính sách tổ chức chặn truy cập công khai; dùng IAP như trên |
| Tải tệp chậm, log có "Không tạo được URL ký" | Thiếu `roles/iam.serviceAccountTokenCreator` của `chungtu-web` trên chính nó; ứng dụng vẫn gửi tệp qua Cloud Run |
| Không thấy thông báo mới | Xem log của `chungtu-worker`; kiểm tra subscription `chungtu-events-push` và quyền `roles/run.invoker` của `chungtu-pubsub` |

## Biến môi trường

| Biến | Mặc định | Ý nghĩa |
| --- | --- | --- |
| `BACKEND` | `local` | `local` hoặc `gcp` |
| `AUTH_MODE` | `demo` | `demo` hoặc `iap` |
| `SECRET_KEY` | giá trị thử | Khóa ký session cookie; trên Cloud Run lấy từ Secret Manager |
| `BUCKET` | | Tên bucket Cloud Storage |
| `PUBSUB_TOPIC` | `chungtu-events` | Topic nhận sự kiện |
| `LEVEL2_THRESHOLD` | `20000000` | Ngưỡng số tiền cần duyệt cấp 2 |
| `IAP_AUDIENCE` | | Audience của JWT do IAP cấp |
| `ADMIN_EMAILS` | | Email nhận quyền quản trị ở lần đăng nhập đầu (chế độ `iap`) |
| `ENABLE_WORKER` | `0` | `1` trên dịch vụ worker: mở `/internal/pubsub` |
| `DATA_DIR` | `./data` | Thư mục dữ liệu khi `BACKEND=local` |

## Trạng thái kiểm thử

Bản local và 33 ca kiểm thử đã chạy đạt. Backend Google Cloud (`backends/gcp.py`) và
`deploy.sh` được viết theo tài liệu chính thức, tên cờ lệnh đã đối chiếu với `gcloud` 570, nhưng
chưa được chạy trên một project thật. Hãy chạy `deploy.sh` trước buổi bảo vệ ít nhất một lần.
