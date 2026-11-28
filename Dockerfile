# Cố định Debian 12 (bookworm) để khớp repo Microsoft cho ODBC Driver 18
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

WORKDIR /srv

# Microsoft ODBC Driver 18 cho pyodbc kết nối Azure SQL (kể cả xác thực managed identity)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl gnupg ca-certificates \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
       | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && echo "deb [arch=amd64,arm64 signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" \
       > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 unixodbc \
    && apt-get purge -y curl gnupg \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends gcc g++ unixodbc-dev \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y gcc g++ unixodbc-dev \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY main.py .
COPY app ./app

RUN useradd --create-home --uid 10001 appuser
USER appuser

# Web: gunicorn. Worker Service Bus dùng cùng image với lệnh: python -m app.servicebus_worker
CMD exec gunicorn --bind :$PORT --workers 2 --threads 8 --timeout 120 main:app
