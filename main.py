"""Điểm khởi chạy. Trên Cloud Run: gunicorn main:app. Trên máy cá nhân: python main.py"""
import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "8080")), debug=False)
