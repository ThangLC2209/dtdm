"""Worker nhận sự kiện chứng từ từ Azure Service Bus và tạo thông báo.

Chạy như một Container App riêng (không mở ingress), cùng image với web:
    python -m app.servicebus_worker

worker.handle_event là idempotent (id thông báo cố định theo sự kiện + người nhận),
nên tin nhắn bị giao lại sau sự cố vẫn không tạo thông báo trùng.
"""
from __future__ import annotations

import json
import signal
import time

from . import worker
from .config import load_config, validate_config
from .services import build_services, log

_running = True


def _stop(*_):
    global _running
    _running = False


def run() -> None:
    config = load_config()
    validate_config(config)
    if config["BACKEND"] != "azure":
        raise SystemExit("Worker Service Bus chỉ dùng với BACKEND=azure.")
    # ENABLE_WORKER để build_services không tạo dữ liệu demo
    config["ENABLE_WORKER"] = True
    from .backends.azure import servicebus_client
    repo = build_services(config).repo
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    log("INFO", "Worker Service Bus bắt đầu", queue=config["AZURE_SERVICEBUS_QUEUE"])

    while _running:
        try:
            client = servicebus_client(config["AZURE_SERVICEBUS_CONNECTION_STRING"],
                                       config["AZURE_SERVICEBUS_NAMESPACE"])
            with client, client.get_queue_receiver(queue_name=config["AZURE_SERVICEBUS_QUEUE"],
                                                   max_wait_time=30) as receiver:
                while _running:
                    for message in receiver.receive_messages(max_message_count=20, max_wait_time=30):
                        try:
                            event = json.loads(str(message))
                            count = worker.handle_event(repo, event)
                            receiver.complete_message(message)
                            log("INFO", "Đã xử lý sự kiện", event_type=event.get("type"),
                                doc_id=event.get("doc_id"), notifications=count)
                        except (ValueError, KeyError) as exc:
                            # Tin nhắn hỏng không bao giờ xử lý được: chuyển vào dead-letter
                            receiver.dead_letter_message(message, reason="invalid-event",
                                                         error_description=str(exc)[:200])
                            log("ERROR", "Sự kiện không hợp lệ", error=str(exc))
                        except Exception as exc:  # lỗi tạm thời (DB...): trả lại để thử lại
                            receiver.abandon_message(message)
                            log("ERROR", "Xử lý sự kiện thất bại, sẽ thử lại", error=str(exc))
        except Exception as exc:
            log("ERROR", "Mất kết nối Service Bus, kết nối lại sau 10 giây", error=str(exc))
            time.sleep(10)
    log("INFO", "Worker Service Bus dừng")


if __name__ == "__main__":
    run()
