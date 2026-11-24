"""Cấu hình ứng dụng, đọc từ biến môi trường (theo nguyên tắc 12-factor)."""
import os


def load_config() -> dict:
    env = os.environ.get
    backend = env("BACKEND", "local")
    auth_mode = env("AUTH_MODE", "demo")
    return {
        "BACKEND": backend,
        "AUTH_MODE": auth_mode,
        "SECRET_KEY": env("SECRET_KEY", "chi-dung-khi-chay-thu"),
        "DATA_DIR": env("DATA_DIR", "./data"),
        "GCP_PROJECT": env("GOOGLE_CLOUD_PROJECT"),
        "BUCKET": env("BUCKET"),
        "PUBSUB_TOPIC": env("PUBSUB_TOPIC", "chungtu-events"),
        "IAP_AUDIENCE": env("IAP_AUDIENCE"),
        "AZURE_SQL_URL": env("AZURE_SQL_URL"),
        "AZURE_STORAGE_ACCOUNT_URL": env("AZURE_STORAGE_ACCOUNT_URL"),
        "AZURE_STORAGE_CONTAINER": env("AZURE_STORAGE_CONTAINER", "documents"),
        "AZURE_SERVICEBUS_CONNECTION_STRING": env("AZURE_SERVICEBUS_CONNECTION_STRING"),
        "AZURE_SERVICEBUS_NAMESPACE": env("AZURE_SERVICEBUS_NAMESPACE"),
        "AZURE_SERVICEBUS_QUEUE": env("AZURE_SERVICEBUS_QUEUE", "chungtu-events"),
        "AZURE_TENANT_ID": env("AZURE_TENANT_ID"),
        "AZURE_CLIENT_ID": env("AZURE_CLIENT_ID"),
        "AZURE_CLIENT_SECRET": env("AZURE_CLIENT_SECRET"),
        "AZURE_REDIRECT_URI": env("AZURE_REDIRECT_URI"),
        "AZURE_AUTHORITY": env("AZURE_AUTHORITY"),
        "AZURE_POST_LOGOUT_REDIRECT_URI": env("AZURE_POST_LOGOUT_REDIRECT_URI", "/login"),
        "ADMIN_EMAILS": [e.strip().lower() for e in env("ADMIN_EMAILS", "").split(",") if e.strip()],
        "LEVEL2_THRESHOLD": int(env("LEVEL2_THRESHOLD", "20000000")),
        "MAX_CONTENT_LENGTH": 10 * 1024 * 1024,
        "ENABLE_WORKER": env("ENABLE_WORKER", "0") == "1",
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": backend in ("azure", "gcp") or env("COOKIE_SECURE", "0") == "1",
    }
