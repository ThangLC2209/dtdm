"""Cấu hình ứng dụng, đọc từ biến môi trường (theo nguyên tắc 12-factor)."""
import os


def load_config() -> dict:
    env = os.environ.get
    return {
        # local: lưu tệp + JSON trên đĩa (chạy thử trên máy cá nhân)
        # gcp:   Cloud Storage + Firestore + Pub/Sub
        "BACKEND": env("BACKEND", "local"),
        # demo: chọn tài khoản mẫu để đăng nhập (không mật khẩu, chỉ để trình diễn)
        # iap:  danh tính do Identity-Aware Proxy xác thực
        "AUTH_MODE": env("AUTH_MODE", "demo"),
        "SECRET_KEY": env("SECRET_KEY", "chi-dung-khi-chay-thu"),
        "DATA_DIR": env("DATA_DIR", "./data"),
        "GCP_PROJECT": env("GOOGLE_CLOUD_PROJECT"),
        "BUCKET": env("BUCKET"),
        "PUBSUB_TOPIC": env("PUBSUB_TOPIC", "chungtu-events"),
        # /projects/<PROJECT_NUMBER>/locations/<REGION>/services/<SERVICE_NAME>
        "IAP_AUDIENCE": env("IAP_AUDIENCE"),
        # Email được cấp vai trò quản trị ở lần đăng nhập đầu tiên (chế độ iap)
        "ADMIN_EMAILS": [e.strip().lower() for e in env("ADMIN_EMAILS", "").split(",") if e.strip()],
        # Chứng từ có số tiền từ ngưỡng này trở lên phải qua duyệt cấp 2
        "LEVEL2_THRESHOLD": int(env("LEVEL2_THRESHOLD", "20000000")),
        # Giới hạn kích thước request (tệp tải lên): 10 MB
        "MAX_CONTENT_LENGTH": 10 * 1024 * 1024,
        # Chỉ bật trên dịch vụ worker: mở endpoint nhận tin đẩy từ Pub/Sub
        "ENABLE_WORKER": env("ENABLE_WORKER", "0") == "1",
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": env("BACKEND", "local") == "gcp",
    }
