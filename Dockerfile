FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

WORKDIR /srv

COPY requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends gcc g++ unixodbc-dev curl gnupg \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y gcc g++ \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY main.py .
COPY app ./app

RUN useradd --create-home --uid 10001 appuser
USER appuser

CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 main:app
