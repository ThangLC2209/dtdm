FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY app ./app

# Không chạy bằng root bên trong container
RUN useradd --create-home --uid 10001 appuser
USER appuser

# Cloud Run truyền cổng qua biến PORT. Một worker, nhiều luồng: hợp với tác vụ chủ yếu chờ I/O.
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 main:app
